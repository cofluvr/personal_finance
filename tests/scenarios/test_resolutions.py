"""Resolving unresolved records, end to end, using synthetic data only (D-050)."""

import re

import pytest
from test_confirmations import confirm, confirm_ok
from test_corrections import CorrectionLedger
from test_decisions import (
    CAFE,
    OTHER,
    SOURCE_TABLES,
    WHOLE_MONTH,
)
from test_supersession import holding

from personal_finance.reconcile.decisions import (
    ITEM_NOT_FOUND,
    ITEM_WRONG_ACCOUNT,
    STALE_ACCOUNT,
    STALE_REVISION,
)
from personal_finance.reconcile.record_resolutions import (
    AMOUNT_INVALID,
    COMPLETION_BOUND,
    DATE_INVALID,
    DESCRIPTION_BLANK,
    ITEM_NOT_UNRESOLVED,
    NEEDS_AMOUNT,
    NEEDS_DATE,
    RESOLUTION_NOT_ACTIVE,
    RESOLUTION_NOT_FOUND,
    RESOLUTION_WRONG_ACCOUNT,
    STALE_RESOLUTION_REVISION,
    VALUE_ALREADY_READ,
)
from personal_finance.reports import resolution_evidence

# A card row with no amount, and one the parser cannot split into columns.
CAFE_NO_AMOUNT = "01/10/2026,SYNTHETIC CAFE,,"
UNREADABLE = "not a row of this layout"


class ResolutionLedger(CorrectionLedger):
    def unresolved(self):
        return self.items("unresolved_record")

    def complete(self, item, revision=None, account="A", **values):
        words = ["review", "complete", item, "--account", account,
                 "--revision", revision or self.revision(item)]
        for name, value in values.items():
            words.append(f"--{name.replace('_', '-')}={value}")
        return self.run(*words)

    def complete_ok(self, item, **values):
        code, out, err = self.complete(item, **values)
        assert code == 0, err
        return re.search(r"Resolution (\S+) recorded", out)[1]

    def dismiss(self, item, revision=None, account="A"):
        return self.run("review", "dismiss", item, "--account", account,
                        "--revision", revision or self.revision(item))

    def dismiss_ok(self, item):
        code, out, err = self.dismiss(item)
        assert code == 0, err
        return re.search(r"Resolution (\S+) recorded", out)[1]

    def resolution_show(self, resolution):
        code, out, err = self.run("review", "resolution", "show", resolution)
        assert code == 0, err
        return out

    def resolution_revision(self, resolution):
        return re.search(r"Revision: (u1-[0-9a-f]{16})", self.resolution_show(resolution))[1]

    def undo_resolution(self, resolution, revision=None, account="A"):
        return self.run("review", "resolution", "undo", resolution, "--account", account,
                        "--revision", revision or self.resolution_revision(resolution))

    def undo_resolution_ok(self, resolution):
        code, out, err = self.undo_resolution(resolution)
        assert code == 0, err
        return out

    def link_rules(self):
        conn = self.conn()
        found = sorted(row[0] for row in conn.execute("SELECT link_rule FROM transaction_source"))
        conn.close()
        return found


@pytest.fixture
def ledger(tmp_path, capsys):
    return ResolutionLedger(tmp_path, capsys)


def one_unresolved(ledger, row=CAFE_NO_AMOUNT):
    ledger.card("a.csv", row)
    (item,) = ledger.unresolved()
    return item


def blocked_pair(ledger, broken=UNREADABLE):
    """a.csv and b.csv hold the same purchase under complete coverage, and a.csv a row the parser
    could not read, which keeps their match from being confident (D-024)."""
    ledger.card("a.csv", CAFE, broken, extra=WHOLE_MONTH)
    ledger.card("b.csv", CAFE, extra=WHOLE_MONTH)
    (item,) = ledger.unresolved()
    return item


class TestComplete:  # U1, U2
    def test_a_missing_amount_becomes_one_transaction(self, ledger):  # U1
        item = one_unresolved(ledger)
        assert ledger.count() == 0
        code, out, err = ledger.complete(item, amount="-6.50")
        assert code == 0, err
        assert "row completed, supplying amount" in out
        assert ledger.count() == 1 and ledger.net() == "-6.50"
        assert ledger.unresolved() == []
        assert ledger.link_rules() == ["completed_record"]
        totals = ledger.totals()
        assert "unresolved records are not included" not in totals
        assert "Transactions holding a row you completed by hand: 1" in totals

    def test_only_the_origin_is_added_to_source_tables(self, ledger):
        item = one_unresolved(ledger)
        before = ledger.dump(SOURCE_TABLES)
        ledger.complete_ok(item, amount="-6.50")
        after = ledger.dump(SOURCE_TABLES)
        for table in SOURCE_TABLES:
            if table != "source_record_origin":
                assert after[table] == before[table], table
        assert len(after["source_record_origin"]) == len(before["source_record_origin"]) + 1

    def test_a_row_with_every_value_read_is_completed_with_nothing_supplied(self, ledger):  # U2
        ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,MAYBE")
        (item,) = ledger.unresolved()
        code, out, _ = ledger.complete(item)
        assert code == 0 and "supplying nothing, since every value was read" in out
        assert ledger.net() == "-5.00"
        assert "Status: unknown" in ledger.run("trace", holding(ledger, "a.csv"))[1]

    def test_an_unreadable_row_needs_an_amount_and_a_date(self, ledger):
        item = one_unresolved(ledger, UNREADABLE)
        assert NEEDS_AMOUNT in ledger.complete(item)[2]
        assert NEEDS_DATE in ledger.complete(item, amount="-6.50")[2]
        ledger.complete_ok(item, amount="-6.50", posting_date="2026-01-10",
                           description="SYNTHETIC CAFE")
        assert ledger.net() == "-6.50"

    def test_a_description_can_stay_missing(self, ledger):
        item = one_unresolved(ledger, UNREADABLE)
        ledger.complete_ok(item, amount="-6.50", transaction_date="2026-01-10")
        assert "Description: missing" in ledger.run("trace", ledger.run("transactions")[1].split()[0])[1]


class TestRefusals:  # U3
    def nothing_changes(self, ledger, result, message):
        code, out, err = result
        assert code == 2 and message in err, err

    def refused(self, ledger, attempt, message):
        before = ledger.dump()
        self.nothing_changes(ledger, attempt(), message)
        assert ledger.dump() == before

    def test_wrong_account(self, ledger):
        item = one_unresolved(ledger)
        ledger.add_account("B")
        self.refused(ledger, lambda: ledger.complete(item, account="B", amount="-6.50"),
                     ITEM_WRONG_ACCOUNT)
        self.refused(ledger, lambda: ledger.dismiss(item, account="B"), ITEM_WRONG_ACCOUNT)

    def test_an_unknown_item(self, ledger):
        one_unresolved(ledger)
        self.refused(ledger, lambda: ledger.complete("nope", revision="r5-0", amount="-6.50"),
                     ITEM_NOT_FOUND)
        self.refused(ledger, lambda: ledger.dismiss("nope", revision="r5-0"), ITEM_NOT_FOUND)

    def test_an_item_of_another_kind(self, ledger):
        ledger.card("a.csv", CAFE)
        ledger.card("b.csv", CAFE)
        (item,) = ledger.items()
        self.refused(ledger, lambda: ledger.dismiss(item), ITEM_NOT_UNRESOLVED)

    def test_a_stale_token_and_one_of_the_last_version(self, ledger):
        item = one_unresolved(ledger)
        for token in ("r5-0000000000000000", "r4-" + ledger.revision(item)[3:]):
            self.refused(ledger, lambda: ledger.complete(item, revision=token, amount="-6.50"),
                         STALE_REVISION)
            self.refused(ledger, lambda: ledger.dismiss(item, revision=token), STALE_REVISION)

    def test_a_resolved_item_is_gone(self, ledger):
        item = one_unresolved(ledger)
        token = ledger.revision(item)
        ledger.complete_ok(item, amount="-6.50")
        self.refused(ledger, lambda: ledger.dismiss(item, revision=token), ITEM_NOT_FOUND)

    @pytest.mark.parametrize(("values", "message"), [
        ({"amount": "-6.50", "posting_date": "2026-01-11"},
         VALUE_ALREADY_READ.format(field="posting_date")),
        ({"amount": "-6.50", "description": "OTHER"},
         VALUE_ALREADY_READ.format(field="description")),
        ({}, NEEDS_AMOUNT),
    ])
    def test_a_value_that_was_read_or_one_that_is_lacking(self, ledger, values, message):
        item = one_unresolved(ledger)
        self.refused(ledger, lambda: ledger.complete(item, **values), message)

    @pytest.mark.parametrize(("values", "message"), [
        ({"amount": "-6.505"}, AMOUNT_INVALID),
        ({"amount": "six"}, AMOUNT_INVALID),
        ({"amount": "-6.50", "posting_date": "01/10/2026"}, DATE_INVALID),
        ({"amount": "-6.50", "transaction_date": "2026-02-30"}, DATE_INVALID),
        ({"amount": "-6.50", "posting_date": "2026-01-10", "description": "   "},
         DESCRIPTION_BLANK),
    ])
    def test_an_invalid_value_is_not_repeated(self, ledger, values, message):
        item = one_unresolved(ledger, UNREADABLE)
        before = ledger.dump()
        code, out, err = ledger.complete(item, **values)
        assert code == 2 and message in err
        for value in values.values():
            if value.strip() and value != "-6.50":
                assert value not in err and value not in out
        assert ledger.dump() == before


class TestStaleAccount:  # U4
    def stale(self, ledger):
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()

    def test_every_command_is_refused_and_nothing_is_reconciled(self, ledger):
        ledger.card("a.csv", CAFE, CAFE_NO_AMOUNT)
        (item,) = ledger.unresolved()
        resolution = ledger.complete_ok(item, amount="-9.00")
        undo_token = ledger.resolution_revision(resolution)
        ledger.card("b.csv", UNREADABLE)
        (other,) = ledger.unresolved()
        other_token = ledger.revision(other)
        self.stale(ledger)
        before = ledger.dump()
        for result in (ledger.complete(other, revision=other_token, amount="-1.00",
                                       posting_date="2026-01-10"),
                       ledger.dismiss(other, revision=other_token),
                       ledger.undo_resolution(resolution, undo_token)):
            code, _, err = result
            assert code == 2 and STALE_ACCOUNT in err
        assert ledger.dump() == before


class TestMatching:  # U5, U6, U7
    def test_an_identical_row_of_another_document_is_raised_not_merged(self, ledger):  # U5
        ledger.card("a.csv", CAFE, extra=WHOLE_MONTH)
        ledger.card("b.csv", CAFE_NO_AMOUNT, extra=WHOLE_MONTH)
        (item,) = ledger.unresolved()
        ledger.complete_ok(item, amount="-6.50")
        assert ledger.count() == 2 and ledger.net() == "-13.00"
        (candidates,) = ledger.items("cross_document_candidates")
        assert len(ledger.transactions(candidates)) == 2

    def test_a_shared_reliable_id_raises_an_item_and_never_merges(self, ledger):
        ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
        ledger.checking("b.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,,")
        (item,) = ledger.unresolved()
        ledger.complete_ok(item, amount="-5.00")
        assert ledger.count() == 2
        (shared,) = ledger.items("cross_document_external_id")
        out = ledger.show(shared)
        assert "completed_record_shares_id" in out
        assert "never merged automatically" in out

    def test_an_unreadable_row_blocks_until_completed_with_values_that_rule_it_out(self, ledger):
        item = blocked_pair(ledger)  # U6
        assert ledger.count() == 2 and ledger.net() == "-13.00"
        ledger.complete_ok(item, amount="-9.00", posting_date="2026-01-15",
                           description="SYNTHETIC GROCER")
        assert ledger.count() == 2 and ledger.net() == "-15.50"
        assert "exact_coverage_pair" in ledger.link_rules()

    def test_an_unreadable_row_is_named_as_unresolved_even_beside_a_completed_one(self, ledger):
        ledger.card("a.csv", CAFE, UNREADABLE, UNREADABLE, extra=WHOLE_MONTH)
        ledger.card("b.csv", CAFE, extra=WHOLE_MONTH)
        first, _ = ledger.unresolved()
        ledger.complete_ok(first, amount="-6.50", posting_date="2026-01-10",
                           description="SYNTHETIC CAFE")
        (candidates,) = ledger.items("cross_document_candidates")
        out = ledger.show(candidates)
        assert "unresolved_row:" in out and "completed_row:" not in out

    def test_a_completion_alike_the_pair_keeps_blocking_it(self, ledger):
        item = blocked_pair(ledger)
        ledger.complete_ok(item, amount="-6.50", posting_date="2026-01-10",
                           description="SYNTHETIC CAFE")
        assert ledger.count() == 3
        assert "exact_coverage_pair" not in ledger.link_rules()
        (candidates,) = ledger.items("cross_document_candidates")
        assert "completed_row" in ledger.show(candidates)

    def test_confirming_counts_once_and_the_source_record_supplies_values(self, ledger):  # U7
        ledger.card("a.csv", CAFE, extra=WHOLE_MONTH)
        ledger.card("b.csv", "01/10/2026,,," , extra=WHOLE_MONTH)
        (item,) = ledger.unresolved()
        ledger.complete_ok(item, amount="-6.50", description="SYNTHETIC CAFE")
        (candidates,) = ledger.items("cross_document_candidates")
        one, two = ledger.transactions(candidates)
        confirm_ok(ledger, candidates, (one, two))
        assert ledger.count() == 1 and ledger.net() == "-6.50"
        transaction = holding(ledger, "a.csv")
        for shown in (ledger.run("trace", transaction)[1], ledger.transaction_show(transaction)):
            primary = shown.split("Source a.csv")[1].split("Source")[0]
            assert "Role: primary" in primary
            assert "not selected on: read from the source, then completed by hand" in shown


class TestDismiss:  # U8
    def test_a_dismissal_creates_nothing_and_unblocks_the_pair(self, ledger):
        item = blocked_pair(ledger)
        code, out, err = ledger.dismiss(item)
        assert code == 0, err
        assert "Transactions: 2 before, 1 now." in out
        assert ledger.count() == 1 and ledger.net() == "-6.50"
        assert "exact_coverage_pair" in ledger.link_rules()
        totals = ledger.totals()
        assert "Rows you dismissed as adding no transaction: 1" in totals
        assert "unresolved records are not included" not in totals
        assert ledger.unresolved() == []


class TestUndo:  # U9, U10, U11
    def test_undoing_a_completion_equals_never_completing_it(self, ledger, tmp_path, capsys):  # U9
        item = blocked_pair(ledger)
        resolution = ledger.complete_ok(item, amount="-9.00", posting_date="2026-01-15",
                                        description="SYNTHETIC GROCER")
        out = ledger.undo_resolution_ok(resolution)
        assert "The row is unresolved again" in out
        assert len(ledger.unresolved()) == 1

        folder = tmp_path / "plain"
        folder.mkdir()
        plain = ResolutionLedger(folder, capsys)
        blocked_pair(plain)
        assert ledger.view() == plain.view()
        assert ledger.net() == plain.net() == "-13.00"
        assert resolution_evidence.load_resolution(ledger.conn(), resolution).state == "undone"

    def test_completing_again_revives_the_same_transaction(self, ledger):
        item = one_unresolved(ledger)
        first = ledger.complete_ok(item, amount="-6.50")
        transaction = holding(ledger, "a.csv")
        ledger.undo_resolution_ok(first)
        assert ledger.count() == 0
        (again,) = ledger.unresolved()
        ledger.complete_ok(again, amount="-6.00")
        assert holding(ledger, "a.csv") == transaction
        history = ledger.run("trace", transaction)[1]
        assert "retired (record_completion_undone)" in history
        assert "revived (record_completed)" in history

    def test_undo_waits_for_a_confirmation_binding_the_record(self, ledger):  # U10
        ledger.card("a.csv", CAFE, extra=WHOLE_MONTH)
        ledger.card("b.csv", CAFE_NO_AMOUNT, extra=WHOLE_MONTH)
        (item,) = ledger.unresolved()
        resolution = ledger.complete_ok(item, amount="-6.50")
        (candidates,) = ledger.items("cross_document_candidates")
        decision = confirm_ok(ledger, candidates, tuple(ledger.transactions(candidates)))
        assert f"Refused while decision {decision}" in ledger.resolution_show(resolution)
        before = ledger.dump()
        code, _, err = ledger.undo_resolution(resolution)
        assert code == 2 and COMPLETION_BOUND.format(entries=f"decision {decision}") in err
        assert ledger.dump() == before
        assert ledger.undo(decision)[0] == 0
        ledger.undo_resolution_ok(resolution)
        assert ledger.count() == 1

    def test_undo_waits_for_a_correction_binding_the_record(self, ledger):
        item = one_unresolved(ledger)
        resolution = ledger.complete_ok(item, amount="-6.50")
        correction = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-6.00")
        assert ledger.net() == "-6.00"  # U12: a completed transaction can be corrected.
        code, _, err = ledger.undo_resolution(resolution)
        assert code == 2 and f"correction {correction}" in err
        assert ledger.undo_correction(correction)[0] == 0
        ledger.undo_resolution_ok(resolution)

    def test_undoing_a_dismissal_restores_the_blocker(self, ledger):  # U11
        item = blocked_pair(ledger)
        resolution = ledger.dismiss_ok(item)
        assert ledger.count() == 1
        out = ledger.undo_resolution_ok(resolution)
        assert "Transactions: 1 before, 2 now." in out
        assert "exact_coverage_pair" not in ledger.link_rules()
        assert "dismissed" not in ledger.totals()
        (raised,) = ledger.unresolved()
        assert f"The row is unresolved again, as item {raised}." in out

    def test_undo_refusals(self, ledger):
        item = one_unresolved(ledger)
        resolution = ledger.complete_ok(item, amount="-6.50")
        token = ledger.resolution_revision(resolution)
        ledger.add_account("B")
        for result, message in (
            (ledger.undo_resolution("nope", "u1-0"), RESOLUTION_NOT_FOUND),
            (ledger.undo_resolution(resolution, token, account="B"), RESOLUTION_WRONG_ACCOUNT),
            (ledger.undo_resolution(resolution, "u1-0000000000000000"), STALE_RESOLUTION_REVISION),
        ):
            assert result[0] == 2 and message in result[2]
        assert ledger.undo_resolution(resolution, token)[0] == 0
        code, _, err = ledger.undo_resolution(resolution, token)
        assert code == 2 and RESOLUTION_NOT_ACTIVE in err


class TestSurvival:  # U12
    def test_resolutions_survive_imports_reconcile_and_unrelated_files(self, ledger):
        item = blocked_pair(ledger)
        ledger.dismiss_ok(item)
        ledger.card("c.csv", CAFE_NO_AMOUNT)
        (other,) = ledger.unresolved()
        ledger.complete_ok(other, amount="-3.00")
        view = ledger.view()
        net = ledger.net()
        ledger.load_path(ledger.folder / "a.csv", *WHOLE_MONTH)
        assert ledger.run("reconcile")[0] == 0
        assert ledger.view() == view and ledger.net() == net
        ledger.card("x.csv", OTHER)
        assert ledger.count() == 3


class TestTokens:  # U13
    def test_the_version_is_pinned(self):
        assert resolution_evidence.RESOLUTION_REVISION_VERSION == 1

    def test_the_definition_is_pinned(self, ledger):
        item = one_unresolved(ledger)
        resolution = ledger.complete_ok(item, amount="-6.50")
        # Computed for this ledger when version 1 was built.
        assert ledger.resolution_revision(resolution) == "u1-eef46741adfc3a9f"

    def test_an_unrelated_file_leaves_it_unchanged(self, ledger):
        item = one_unresolved(ledger)
        resolution = ledger.complete_ok(item, amount="-6.50")
        token = ledger.resolution_revision(resolution)
        ledger.card("x.csv", OTHER)
        assert ledger.resolution_revision(resolution) == token

    def test_a_related_file_changes_it(self, ledger):
        ledger.card("a.csv", CAFE, UNREADABLE, extra=WHOLE_MONTH)
        (item,) = ledger.unresolved()
        resolution = ledger.dismiss_ok(item)
        token = ledger.resolution_revision(resolution)
        ledger.card("b.csv", CAFE, extra=WHOLE_MONTH)
        assert ledger.resolution_revision(resolution) != token
        code, _, err = ledger.undo_resolution(resolution, token)
        assert code == 2 and STALE_RESOLUTION_REVISION in err

    def test_a_completion_changes_its_transaction_token(self, ledger, tmp_path, capsys):
        tokens = []
        for amount in ("-6.50", "-6.00"):
            folder = tmp_path / amount
            folder.mkdir()
            other = ResolutionLedger(folder, capsys)
            (item,) = [one_unresolved(other)]
            other.complete_ok(item, amount=amount)
            tokens.append(other.transaction_revision(holding(other, "a.csv")))
        assert tokens[0] != tokens[1]
        assert all(token.startswith("t3-") for token in tokens)


class TestPrivacy:  # U16, U17
    def test_routine_commands_show_no_values(self, ledger):
        item = one_unresolved(ledger, UNREADABLE)
        code, out, err = ledger.complete(item, amount="-123.45", posting_date="2026-01-10",
                                         description="SECRET MERCHANT")
        assert code == 0, err
        resolution = re.search(r"Resolution (\S+) recorded", out)[1]
        for text in (out, ledger.run("review", "resolutions")[1],
                     ledger.resolution_show(resolution), ledger.run("review", "list")[1]):
            assert "123.45" not in text and "SECRET" not in text

    def test_displays_mark_and_escape_completed_values(self, ledger):
        item = one_unresolved(ledger, UNREADABLE)
        ledger.complete_ok(item, amount="-6.50", posting_date="2026-01-10",
                           description="CAFE\x1b[2J\nRevision: t3-0000000000000000")
        transaction = holding(ledger, "a.csv")
        for text in (ledger.transaction_show(transaction), ledger.run("trace", transaction)[1],
                     ledger.run("transactions")[1]):
            assert "\x1b" not in text
            assert "\nRevision: t3-0000000000000000" not in text
        for shown in (ledger.transaction_show(transaction), ledger.run("trace", transaction)[1]):
            assert "Completed by hand, supplying what the parser could not read:" in shown
            assert "Posting date: 2026-01-10" in shown.split("Completed by hand")[1]
        assert "(completed by hand)" in ledger.run("transactions")[1]

    def test_import_summaries_disclose_resolutions(self, ledger):
        item = blocked_pair(ledger)
        ledger.dismiss_ok(item)
        out = ledger.card("c.csv", OTHER)
        assert "Rows you dismissed as adding no transaction: 1" in out


def test_confirm_refusal_names_no_values(ledger):
    """review confirm on an item holding a completed record behaves as for any transaction."""
    ledger.card("a.csv", CAFE, extra=WHOLE_MONTH)
    ledger.card("b.csv", CAFE_NO_AMOUNT, extra=WHOLE_MONTH)
    (item,) = ledger.unresolved()
    ledger.complete_ok(item, amount="-6.50")
    (candidates,) = ledger.items("cross_document_candidates")
    one, two = ledger.transactions(candidates)
    code, _, err = confirm(ledger, candidates, (one, two), revision="r5-0000000000000000")
    assert code == 2 and "6.50" not in err
