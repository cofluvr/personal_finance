"""Value corrections, end to end, using synthetic data only (D-049)."""

import re
from dataclasses import replace

import pytest
from test_confirmations import confirm, confirm_ok
from test_decisions import CAFE, FIRST_HALF, SOURCE_TABLES, WHOLE_MONTH, Ledger, pair_up
from test_separations import ID_ROW, SeparationLedger, merged_three, merged_two
from test_supersession import holding

from personal_finance.reconcile.apply import load_constraints, load_evidence, reconcile_account
from personal_finance.reconcile.corrections import (
    AMOUNT_INVALID,
    CHANGES_NOTHING,
    CORRECTION_NOT_ACTIVE,
    CORRECTION_SUPERSEDED,
    CORRECTION_SUPERSEDED_IN_CHAIN,
    DATE_INVALID,
    DESCRIPTION_BLANK,
    FIELD_ALREADY_CORRECTED,
    FIELD_UNSETTLED,
    FIELD_UNSUPPORTED,
    STALE_CORRECTION_REVISION,
    STALE_TRANSACTION_REVISION,
    SUPERSEDES_NOT_HERE,
    SUPERSEDES_OTHER_FIELD,
    TRANSACTION_NOT_FOUND,
    TRANSACTION_WRONG_ACCOUNT,
)
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.decisions import (
    JOINS_DISAGREEING_CORRECTIONS,
    SPLITS_CORRECTED_RECORDS,
    STALE_ACCOUNT,
    STALE_DECISION_REVISION,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports import correction_evidence

CORRECTION_TABLES = ("value_correction", "value_correction_record", "value_correction_event",
                     "transaction_correction")


class CorrectionLedger(SeparationLedger):
    def transaction_show(self, transaction):
        code, out, err = self.run("review", "transaction", "show", transaction)
        assert code == 0, err
        return out

    def transaction_revision(self, transaction):
        return re.search(r"Revision: (t8-[0-9a-f]{16})", self.transaction_show(transaction))[1]

    def correct(self, transaction, field, value, revision=None, account="A", supersedes=None,
                supersedes_revision=None):
        words = ["review", "correct", transaction, "--account", account,
                 "--revision", revision or self.transaction_revision(transaction),
                 "--field", field, f"--value={value}"]
        if supersedes:
            words += ["--supersedes", supersedes, "--supersedes-revision",
                      supersedes_revision or self.correction_revision(supersedes)]
        return self.run(*words)

    def correct_ok(self, transaction, field, value, **options):
        code, out, err = self.correct(transaction, field, value, **options)
        assert code == 0, err
        return re.search(r"Correction (\S+) recorded", out)[1]

    def correction_show(self, correction):
        code, out, err = self.run("review", "correction", "show", correction)
        assert code == 0, err
        return out

    def correction_revision(self, correction):
        return re.search(r"Revision: (c3-[0-9a-f]{16})", self.correction_show(correction))[1]

    def correction_state(self, correction):
        return re.search(r"Status: (\S+)", self.correction_show(correction))[1]

    def undo_correction(self, correction, revision=None, account="A"):
        return self.run("review", "correction", "undo", correction, "--account", account,
                        "--revision", revision or self.correction_revision(correction))

    def net(self):
        return re.search(r"Net account movement: (\S+)", self.totals())[1]

    def field_states(self):
        """Each corrected field as its transaction's file names, the field and its state."""
        conn = self.conn()
        names = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            names.setdefault(transaction_id, []).append(name)
        found = sorted(
            (tuple(sorted(names[transaction_id])), field, state)
            for transaction_id, field, state in conn.execute(
                "SELECT transaction_id, field, state FROM transaction_correction"
            )
        )
        conn.close()
        return found

    def bound_files(self, correction):
        conn = self.conn()
        found = sorted(row[0] for row in conn.execute(
            """SELECT document.file_name FROM value_correction_record bound
               JOIN source_record record ON record.id = bound.source_record_id
               JOIN source_document document ON document.id = record.source_document_id
               WHERE bound.correction_id = ?""",
            (correction,),
        ))
        conn.close()
        return found

    def account_id(self, name="A"):
        conn = self.conn()
        (found,) = conn.execute("SELECT id FROM account WHERE display_name = ?", (name,)).fetchone()
        conn.close()
        return found


@pytest.fixture
def ledger(tmp_path, capsys):
    return CorrectionLedger(tmp_path, capsys)


def single(ledger):
    """One card row of 6.50 out, in a.csv."""
    ledger.card("a.csv", CAFE)
    return holding(ledger, "a.csv")


def merged_by_id_then_split(ledger):
    """a and b merged by a reliable ID, corrected, then c, which makes the IDs conflict."""
    ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
    ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
    (transaction,) = ledger.merges()
    correction = ledger.correct_ok(transaction, "amount", "-4.00")
    ledger.checking("c.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")
    return correction


class TestCorrect:  # V1, V2
    def test_an_amount_changes_totals_by_exactly_the_difference(self, ledger):  # V1
        transaction = single(ledger)
        assert ledger.net() == "-6.50"
        before = ledger.dump((*SOURCE_TABLES, "ledger_transaction", "transaction_source"))
        ledger.correct_ok(transaction, "amount", "-6.00")
        assert ledger.net() == "-6.00"
        assert ledger.dump((*SOURCE_TABLES, "ledger_transaction", "transaction_source")) == before
        listed = ledger.run("transactions")[1]
        assert "-6.00" in listed and "(corrected)" in listed and "-6.50" not in listed
        traced = ledger.run("trace", transaction)[1]
        assert "Amount: -6.50" in traced and "amount: corrected to -6.00" in traced

    @pytest.mark.parametrize(("field", "value", "shown"), [
        ("transaction_date", "2026-01-08", "2026-01-08"),
        ("posting_date", "2026-01-11", "2026-01-11"),
        ("description", "SYNTHETIC CAFE AND BAKERY", "SYNTHETIC CAFE AND BAKERY"),
    ])
    def test_every_other_field_changes_only_what_it_names(self, ledger, field, value, shown):
        transaction = single(ledger)
        ledger.correct_ok(transaction, field, value)
        assert ledger.net() == "-6.50"
        assert shown in ledger.run("transactions")[1]
        assert ledger.field_states() == [(("a.csv",), field, "applied")]

    def test_a_merged_transaction_binds_every_record(self, ledger):
        transaction, _ = merged_two(ledger)
        code, out, _ = ledger.correct(transaction, "amount", "-6.00")
        assert code == 0 and "binding 2 records" in out
        correction = re.search(r"Correction (\S+) recorded", out)[1]
        assert ledger.bound_files(correction) == ["a.csv", "b.csv"]

    def test_derivation_never_reads_a_correction(self, ledger):  # V2
        ledger.card("a.csv", "01/10/2026,SYNTHETIC CAFE,6.50,", extra=WHOLE_MONTH)
        ledger.card("b.csv", "01/10/2026,SYNTHETIC CAFE,6.00,", extra=WHOLE_MONTH)
        conn = ledger.conn()
        account = ledger.account_id()
        before = derive(*load_evidence(conn, account)[:3], DEFAULT_RULES,
                        load_constraints(conn, account))
        conn.close()

        # Now alike in every parsed value but one, which a correction may not stand in for.
        ledger.correct_ok(holding(ledger, "b.csv"), "amount", "-6.50")
        conn = ledger.conn()
        after = derive(*load_evidence(conn, account)[:3], DEFAULT_RULES,
                       load_constraints(conn, account))
        conn.close()
        assert after == before
        assert ledger.count() == 2 and ledger.items() == []
        assert ledger.net() == "-13.00"

    def test_review_show_lists_corrections_apart_from_source_values(self, ledger):
        item, one, _ = pair_up(ledger)
        correction = ledger.correct_ok(one, "amount", "-6.00")
        out = ledger.show(item)
        section = out.split("Corrections, kept apart from the source values above:\n")[1]
        assert f"Correction {correction}: amount corrected to -6.00" in section
        assert "amount: the corrected value is used" in section
        assert "Amount: -6.50" in out


class TestRefusals:  # V3
    def refused(self, ledger, result, message):
        code, _, err = result
        assert code == 2
        assert message in err

    def nothing_changes(self, ledger, attempt, message):
        before = ledger.dump()
        self.refused(ledger, attempt(), message)
        assert ledger.dump() == before

    def test_wrong_account(self, ledger):
        transaction = single(ledger)
        ledger.add_account("B")
        self.nothing_changes(
            ledger, lambda: ledger.correct(transaction, "amount", "-6.00", account="B"),
            TRANSACTION_WRONG_ACCOUNT,
        )

    def test_an_unknown_transaction(self, ledger):
        single(ledger)
        self.nothing_changes(
            ledger, lambda: ledger.correct("nope", "amount", "-6.00", revision="t8-0"),
            TRANSACTION_NOT_FOUND,
        )

    def test_a_stale_token_and_one_of_the_last_version(self, ledger):
        transaction = single(ledger)
        old_version = "t7-" + ledger.transaction_revision(transaction).split("-")[1]
        for token in ("t8-0000000000000000", old_version):
            self.nothing_changes(
                ledger, lambda: ledger.correct(transaction, "amount", "-6.00", revision=token),
                STALE_TRANSACTION_REVISION,
            )

    @pytest.mark.parametrize("field", ["status", "settlement_status", "external_id", "amount_cents"])
    def test_an_unsupported_field(self, ledger, field):
        transaction = single(ledger)
        self.nothing_changes(ledger, lambda: ledger.correct(transaction, field, "posted"),
                             FIELD_UNSUPPORTED)

    @pytest.mark.parametrize(("field", "value", "message"), [
        ("amount", "-6.505", AMOUNT_INVALID),
        ("amount", "six", AMOUNT_INVALID),
        ("amount", "", AMOUNT_INVALID),
        ("transaction_date", "01/10/2026", DATE_INVALID),
        ("transaction_date", "20260110", DATE_INVALID),
        ("posting_date", "2026-02-30", DATE_INVALID),
        ("posting_date", "", DATE_INVALID),
        ("description", "   ", DESCRIPTION_BLANK),
    ])
    def test_an_invalid_value_is_not_repeated(self, ledger, field, value, message):
        transaction = single(ledger)
        before = ledger.dump()
        code, out, err = ledger.correct(transaction, field, value)
        assert code == 2 and message in err
        if value.strip():
            assert value not in err and value not in out
        assert ledger.dump() == before

    def test_a_value_that_changes_nothing(self, ledger):
        transaction = single(ledger)
        self.nothing_changes(ledger, lambda: ledger.correct(transaction, "amount", "-6.50"),
                             CHANGES_NOTHING)
        correction = ledger.correct_ok(transaction, "amount", "-6.00")
        self.nothing_changes(
            ledger, lambda: ledger.correct(transaction, "amount", "-6.00", supersedes=correction),
            CHANGES_NOTHING,
        )

    def test_a_corrected_field_without_supersedes(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "amount", "-6.00")
        self.nothing_changes(ledger, lambda: ledger.correct(transaction, "amount", "-5.00"),
                             FIELD_ALREADY_CORRECTED.format(correction=correction))
        # Another field is a separate correction.
        ledger.correct_ok(transaction, "posting_date", "2026-01-11")

    def test_superseding_a_correction_of_another_field(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "posting_date", "2026-01-11")
        self.nothing_changes(
            ledger, lambda: ledger.correct(transaction, "amount", "-6.00", supersedes=correction),
            SUPERSEDES_OTHER_FIELD,
        )

    def test_superseding_a_correction_applying_elsewhere(self, ledger):
        item, one, two = pair_up(ledger)
        elsewhere = ledger.correct_ok(one, "amount", "-6.00")
        self.nothing_changes(
            ledger, lambda: ledger.correct(two, "amount", "-5.00", supersedes=elsewhere),
            SUPERSEDES_NOT_HERE,
        )

    def test_superseding_an_undone_correction(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "amount", "-6.00")
        token = ledger.correction_revision(correction)
        assert ledger.undo_correction(correction, token)[0] == 0
        self.nothing_changes(
            ledger,
            lambda: ledger.correct(transaction, "amount", "-5.00", supersedes=correction,
                                   supersedes_revision=token),
            CORRECTION_NOT_ACTIVE,
        )
        self.nothing_changes(ledger, lambda: ledger.undo_correction(correction, token),
                             CORRECTION_NOT_ACTIVE)

    def test_a_stale_correction_token(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "amount", "-6.00")
        for attempt in (
            lambda: ledger.correct(transaction, "amount", "-5.00", supersedes=correction,
                                   supersedes_revision="c3-0000000000000000"),
            lambda: ledger.undo_correction(correction, "c3-0000000000000000"),
        ):
            self.nothing_changes(ledger, attempt, STALE_CORRECTION_REVISION)

    def test_superseding_an_unsettled_field(self, ledger):
        _, one, _ = disagreeing_after_undo(ledger)
        transaction = holding(ledger, "a.csv")
        state = ledger.field_states()
        assert state == [(("a.csv", "b.csv"), "amount", "conflict")]
        self.nothing_changes(
            ledger, lambda: ledger.correct(transaction, "amount", "-4.00", supersedes=one),
            FIELD_UNSETTLED.split("{")[0],
        )
        self.nothing_changes(ledger, lambda: ledger.correct(transaction, "amount", "-4.00"),
                             FIELD_UNSETTLED.split("{")[0])

    def test_superseding_one_of_two_agreeing_corrections(self, ledger):
        item, one, two = pair_up(ledger)
        first = ledger.correct_ok(one, "amount", "-6.00")
        ledger.correct_ok(two, "amount", "-6.00")
        (item,) = ledger.items()
        confirm_ok(ledger, item, (one, two))
        assert ledger.field_states() == [(("a.csv", "b.csv"), "amount", "applied")]
        transaction = holding(ledger, "a.csv")
        self.nothing_changes(
            ledger, lambda: ledger.correct(transaction, "amount", "-4.00", supersedes=first),
            FIELD_UNSETTLED.split("{")[0],
        )

    def test_supersedes_needs_its_revision(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "amount", "-6.00")
        code, _, err = ledger.run(
            "review", "correct", transaction, "--account", "A",
            "--revision", ledger.transaction_revision(transaction), "--field", "amount",
            "--value=-5.00", "--supersedes", correction,
        )
        assert code == 2 and "must be given together" in err


def disagreeing_after_undo(ledger):
    """a and b merged, separated, corrected differently, and merged again by undoing the
    separation. Returns the two corrections and the separation."""
    transaction, records = merged_two(ledger)
    separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
    one = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-6.00")
    two = ledger.correct_ok(holding(ledger, "b.csv"), "amount", "-5.00")
    code, out, err = ledger.undo(separation)
    assert code == 0, err
    assert "Corrected fields now using their source value" in out
    return separation, one, two


class TestStaleAccount:  # V4
    def stale(self, ledger):
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()

    def test_correct_and_undo_are_refused_and_nothing_is_reconciled(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "amount", "-6.00")
        token = ledger.correction_revision(correction)
        revision = ledger.transaction_revision(transaction)
        self.stale(ledger)
        before = ledger.dump()
        for result in (ledger.correct(transaction, "posting_date", "2026-01-11", revision=revision),
                       ledger.undo_correction(correction, token)):
            code, _, err = result
            assert code == 2 and STALE_ACCOUNT in err
        assert ledger.dump() == before
        assert "undo will be refused until it is" in ledger.correction_show(correction)


class TestSurvival:  # V5
    def corrected(self, ledger):
        transaction = single(ledger)
        ledger.correct_ok(transaction, "amount", "-6.00")
        return ledger.field_states()

    def test_a_repeat_import(self, ledger):
        states = self.corrected(ledger)
        ledger.load_path(ledger.folder / "a.csv")
        assert ledger.field_states() == states and ledger.net() == "-6.00"

    def test_reconcile(self, ledger):
        states = self.corrected(ledger)
        assert ledger.run("reconcile")[0] == 0
        assert ledger.field_states() == states and ledger.net() == "-6.00"

    def test_an_unrelated_file(self, ledger):
        states = self.corrected(ledger)
        ledger.card("other.csv", "03/20/2026,SYNTHETIC GROCER,9.00,")
        assert ledger.field_states() == states and ledger.net() == "-15.00"

    def test_a_rules_change(self, ledger):
        states = self.corrected(ledger)
        conn = ledger.conn()
        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, ledger.account_id(), replace(DEFAULT_RULES, date_window_days=5))
        conn.execute("COMMIT")
        conn.close()
        assert ledger.field_states() == states and ledger.net() == "-6.00"


class TestNewRecords:  # V6
    def test_a_re_export_that_merges_keeps_it_applied_and_binds_nothing_new(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        correction = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-4.00")
        ledger.checking("b.csv", ID_ROW)
        assert ledger.count() == 1
        assert ledger.bound_files(correction) == ["a.csv"]
        assert ledger.field_states() == [(("a.csv", "b.csv"), "amount", "applied")]
        assert ledger.net() == "-4.00"

    def test_a_re_export_that_does_not_merge_is_not_corrected(self, ledger):
        transaction = single(ledger)
        ledger.correct_ok(transaction, "amount", "-6.00")
        ledger.card("again.csv", CAFE)
        assert ledger.count() == 2
        assert ledger.field_states() == [(("a.csv",), "amount", "applied")]
        assert ledger.net() == "-12.50"


class TestSeveralCorrections:  # V7
    def test_agreeing_corrections_apply_once(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.correct_ok(one, "amount", "-6.00")
        ledger.correct_ok(two, "amount", "-6.00")
        (item,) = ledger.items()
        confirm_ok(ledger, item, (one, two))
        assert ledger.count() == 1
        assert ledger.field_states() == [(("a.csv", "b.csv"), "amount", "applied")]
        assert ledger.net() == "-6.00"

    def test_disagreeing_corrections_use_the_source_value_and_are_disclosed_apart(self, ledger):
        disagreeing_after_undo(ledger)
        assert ledger.count() == 1
        assert ledger.net() == "-6.50"
        totals = ledger.totals()
        assert "keeping a source value because corrections disagree: 1" in totals
        assert "possible-duplicate" not in totals and "Decision conflicts" not in totals
        assert ledger.items() == []
        listed = ledger.run("review", "corrections")[1]
        assert re.search(r"^Transaction \S+, amount: corrections disagree", listed, re.MULTILINE)
        assert "corrections disagree, so the source value is used" in ledger.transaction_show(
            holding(ledger, "a.csv"))

    def test_undoing_one_settles_it(self, ledger):
        _, one, two = disagreeing_after_undo(ledger)
        assert ledger.undo_correction(two)[0] == 0
        assert ledger.field_states() == [(("a.csv", "b.csv"), "amount", "applied")]
        assert ledger.net() == "-6.00"


class TestSplits:  # V8
    def test_an_automatic_split_changes_the_basis_in_every_part(self, ledger):
        correction = merged_by_id_then_split(ledger)
        assert ledger.count() == 3
        assert ledger.field_states() == [
            (("a.csv",), "amount", "basis_changed"),
            (("b.csv",), "amount", "basis_changed"),
        ]
        assert ledger.net() == "-15.00"
        assert "binds records now in several transactions: 2" in ledger.totals()
        out = ledger.correction_show(correction)
        assert out.count("basis changed now, source value, uncorrected after") == 2

    def test_undoing_it_returns_the_source_values(self, ledger):
        correction = merged_by_id_then_split(ledger)
        code, out, _ = ledger.undo_correction(correction)
        assert code == 0 and "Corrected fields now using" not in out
        assert ledger.field_states() == []
        assert ledger.net() == "-15.00"


class TestDecisionCommands:  # V9, V10
    def test_confirming_disagreeing_corrections_refuses(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.correct_ok(one, "amount", "-6.00")
        ledger.correct_ok(two, "amount", "-5.00")
        (item,) = ledger.items()
        before = ledger.dump()
        code, _, err = confirm(ledger, item, (one, two))
        assert code == 2 and JOINS_DISAGREEING_CORRECTIONS in err
        assert ledger.dump() == before

    def test_separating_a_correction_s_records_refuses(self, ledger):
        transaction, records = merged_three(ledger)
        ledger.correct_ok(transaction, "amount", "-6.00")
        before = ledger.dump()
        code, _, err = ledger.separate(transaction, [records["a.csv"]],
                                       [records["b.csv"], records["c.csv"]])
        assert code == 2 and SPLITS_CORRECTED_RECORDS in err
        assert ledger.dump() == before

    def test_separating_records_a_correction_does_not_bind_is_allowed(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-4.00")
        ledger.checking("b.csv", ID_ROW)
        (transaction,) = ledger.merges()
        records = ledger.records(transaction)
        ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        assert ledger.field_states() == [(("a.csv",), "amount", "applied")]
        assert ledger.net() == "-9.00"

    def test_a_correction_made_since_makes_the_undo_token_stale(self, ledger):  # V10
        item, one, two = pair_up(ledger)
        decision = confirm_ok(ledger, item, (one, two))
        old = ledger.decision_revision(decision)
        assert "Changes which corrected values apply" not in ledger.run(
            "review", "decision", "show", decision)[1]
        ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-6.00")
        before = ledger.dump()
        code, _, err = ledger.undo(decision, old)
        assert code == 2 and STALE_DECISION_REVISION in err
        assert ledger.dump() == before

        shown = ledger.run("review", "decision", "show", decision)[1]
        assert "Changes which corrected values apply" in shown
        code, out, _ = ledger.undo(decision)
        assert code == 0
        assert "because corrections disagree or lost their basis: 2" in out
        assert ledger.field_states() == [
            (("a.csv",), "amount", "basis_changed"),
            (("b.csv",), "amount", "basis_changed"),
        ]

    def test_a_rejection_is_unaffected(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-6.00")
        (item,) = ledger.items()
        ledger.reject_ok(item, (one, two))
        assert ledger.field_states() == [(("a.csv",), "amount", "applied")]


def chain_of_three(ledger):
    transaction = single(ledger)
    first = ledger.correct_ok(transaction, "amount", "-6.00")
    second = ledger.correct_ok(transaction, "amount", "-5.00", supersedes=first)
    third = ledger.correct_ok(transaction, "amount", "-4.00", supersedes=second)
    return first, second, third


class TestChains:  # V11
    def test_only_the_newest_applies(self, ledger):
        corrections = chain_of_three(ledger)
        assert [ledger.correction_state(each) for each in corrections] == [
            "superseded", "superseded", "active"]
        assert ledger.net() == "-4.00"

    def test_undo_steps_back_one_link_at_a_time(self, ledger):
        first, second, third = chain_of_three(ledger)
        code, out, _ = ledger.undo_correction(third)
        assert code == 0 and f"Correction {second}, which it superseded, applies again." in out
        assert ledger.net() == "-5.00"
        assert ledger.undo_correction(second)[0] == 0
        assert ledger.net() == "-6.00"
        code, out, _ = ledger.undo_correction(first)
        assert code == 0 and "which it superseded" not in out
        assert ledger.net() == "-6.50"

    def test_a_superseded_correction_names_the_newest(self, ledger):
        first, second, third = chain_of_three(ledger)
        before = ledger.dump()
        code, _, err = ledger.undo_correction(first, "c3-0000000000000000")
        assert code == 2
        assert CORRECTION_SUPERSEDED_IN_CHAIN.format(newer=second, newest=third) in err
        code, _, err = ledger.undo_correction(second, "c3-0000000000000000")
        assert code == 2 and CORRECTION_SUPERSEDED.format(newer=third) in err
        code, _, err = ledger.correct(holding(ledger, "a.csv"), "amount", "-3.00",
                                      supersedes=first, supersedes_revision="c3-0")
        assert code == 2 and f"newest correction of the chain, {third}" in err
        assert ledger.dump() == before
        shown = ledger.correction_show(first)
        assert f"Superseded by correction {second}." in shown
        assert f"Newest of its chain: correction {third}" in shown

    def test_restoring_a_correction_is_never_refused(self, ledger):
        """A restored correction can disagree with another and is still restored (D-049)."""
        transaction, records = merged_two(ledger)
        separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        first = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-5.00")
        second = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-6.00", supersedes=first)
        ledger.correct_ok(holding(ledger, "b.csv"), "amount", "-6.00")
        assert ledger.undo(separation)[0] == 0
        assert ledger.field_states() == [(("a.csv", "b.csv"), "amount", "applied")]
        code, out, _ = ledger.undo_correction(second)
        assert code == 0 and "because corrections disagree or lost their basis: 1" in out
        assert ledger.field_states() == [(("a.csv", "b.csv"), "amount", "conflict")]


class TestUndo:  # V12
    def built(self, tmp_path, capsys, name, files, corrected):
        folder = tmp_path / name
        folder.mkdir()
        ledger = CorrectionLedger(folder, capsys)
        ledger.card("a.csv", CAFE)
        if corrected:
            correction = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-6.00")
        for file_name, row in files:
            ledger.card(file_name, row)
        if corrected:
            assert ledger.undo_correction(correction)[0] == 0
        return ledger

    @pytest.mark.parametrize("files", [(), (("x.csv", "03/20/2026,SYNTHETIC GROCER,9.00,"),
                                            ("y.csv", CAFE))])
    def test_it_equals_a_ledger_built_without_it(self, tmp_path, capsys, files):
        undone = self.built(tmp_path, capsys, "undone", files, corrected=True)
        never = self.built(tmp_path, capsys, "never", files, corrected=False)
        assert undone.view() == never.view()
        assert undone.field_states() == never.field_states() == []
        assert len(undone.dump(CORRECTION_TABLES)["value_correction_event"]) == 2


class TestTokens:  # V13
    def test_the_versions_are_pinned(self):
        assert correction_evidence.CORRECTION_REVISION_VERSION == 3

    def test_the_correction_token_is_pinned(self, tmp_path, capsys):
        """Computed for this ledger when M2.6 was built, as a regression pin."""
        ledger = CorrectionLedger(tmp_path, capsys)
        path = tmp_path / "a.csv"
        path.write_text("Date,Description,Debit,Credit\n" + CAFE + "\n")
        ledger.load_path(path)
        correction = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-6.00")
        assert ledger.correction_revision(correction) == PINNED_CORRECTION_REVISION

    def test_a_correction_changes_the_tokens_of_its_transaction_and_items(self, ledger):
        item, one, two = pair_up(ledger)
        item_before = ledger.revision(item)
        one_before, two_before = ledger.transaction_revision(one), ledger.transaction_revision(two)
        ledger.correct_ok(one, "amount", "-6.00")
        (item,) = ledger.items()
        assert ledger.revision(item) != item_before
        assert ledger.transaction_revision(one) != one_before
        assert ledger.transaction_revision(two) == two_before

    def test_last_version_tokens_of_the_same_digest_are_refused(self, ledger):
        item, one, two = pair_up(ledger)
        code, _, _ = ledger.reject(item, (one, two), revision="r5-" + ledger.revision(item).split("-")[1])
        assert code == 2
        decision = confirm_ok(ledger, item, (one, two))
        code, _, _ = ledger.undo(decision, "d4-" + ledger.decision_revision(decision)[3:])
        assert code == 2

    def test_an_unrelated_file_leaves_the_correction_token_unchanged(self, ledger):
        correction = ledger.correct_ok(single(ledger), "amount", "-6.00")
        token = ledger.correction_revision(correction)
        ledger.card("other.csv", "03/20/2026,SYNTHETIC GROCER,9.00,")
        assert ledger.correction_revision(correction) == token

    def test_a_merging_re_export_changes_it(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        correction = ledger.correct_ok(holding(ledger, "a.csv"), "amount", "-4.00")
        token = ledger.correction_revision(correction)
        ledger.checking("b.csv", ID_ROW)
        assert ledger.correction_revision(correction) != token

    def test_another_correction_of_the_field_changes_it(self, ledger):
        _, one, two = disagreeing_after_undo(ledger)
        token = ledger.correction_revision(one)
        assert ledger.undo_correction(two)[0] == 0
        assert ledger.correction_revision(one) != token


    def test_undoing_an_agreeing_correction_changes_what_undo_would_leave(self, ledger):
        """Both apply the same value, so only the outcome after this one's undo differs."""
        item, one, two = pair_up(ledger)
        first = ledger.correct_ok(one, "amount", "-6.00")
        second = ledger.correct_ok(two, "amount", "-6.00")
        (item,) = ledger.items()
        confirm_ok(ledger, item, (one, two))
        token = ledger.correction_revision(first)
        assert "corrected now, corrected after" in ledger.correction_show(first)
        assert ledger.undo_correction(second)[0] == 0
        assert ledger.field_states() == [(("a.csv", "b.csv"), "amount", "applied")]
        assert ledger.correction_revision(first) != token
        assert "corrected now, source value, uncorrected after" in ledger.correction_show(first)
        before = ledger.dump()
        code, _, err = ledger.undo_correction(first, token)
        assert code == 2 and STALE_CORRECTION_REVISION in err
        assert ledger.dump() == before

# Set when M2.6 was built, after its immaterial inputs were removed (D-049).
PINNED_CORRECTION_REVISION = "c3-e2235f95e29f164e"


class TestPrivacy:  # V16
    SENTINEL_ROW = "01/10/2026,SENTINELMERCHANT,6.51,"

    def test_routine_correction_commands_show_no_amounts_or_descriptions(self, ledger):
        ledger.card("a.csv", self.SENTINEL_ROW)
        transaction = holding(ledger, "a.csv")
        outputs = []
        code, out, err = ledger.correct(transaction, "amount", "-4.27")
        outputs += [out, err]
        correction = re.search(r"Correction (\S+) recorded", out)[1]
        code, out, err = ledger.correct(transaction, "description", "SENTINELFIXED")
        outputs += [out, err]
        for words in (("review", "corrections"), ("review", "correction", "show", correction)):
            code, out, err = ledger.run(*words)
            assert code == 0
            outputs += [out, err]
        code, out, err = ledger.undo_correction(correction)
        outputs += [out, err]
        code, out, err = ledger.correct(transaction, "amount", "-9.99", revision="t8-0")
        outputs += [out, err]
        text = "".join(outputs)
        for sentinel in ("6.51", "4.27", "9.99", "SENTINEL"):
            assert sentinel not in text

    def test_displays_escape_a_corrected_description(self, ledger):
        transaction = single(ledger)
        hostile = "CAFE\x1b[2J\nRevision: t8-0000000000000000"
        ledger.correct_ok(transaction, "description", hostile)
        for out in (ledger.transaction_show(transaction), ledger.run("trace", transaction)[1],
                    ledger.run("transactions")[1]):
            assert "\x1b" not in out
            assert "\nRevision: t8-0000000000000000" not in out
