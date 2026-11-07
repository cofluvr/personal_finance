"""Confirming possible duplicates, end to end, using synthetic data only (D-046)."""

import re
from dataclasses import replace

import pytest
from test_decisions import (
    CAFE,
    CARD_HEADER,
    FIRST_HALF,
    OTHER,
    SECOND_HALF,
    SOURCE_TABLES,
    WHOLE_MONTH,
    Ledger,
    chain,
    conflict_on_a_merge,
    pair_up,
    three_of_them,
)

from personal_finance.cli import CONFIRM_NOTICE
from personal_finance.reconcile import decisions as decisions_module
from personal_finance.reconcile.apply import reconcile_account
from personal_finance.reconcile.decisions import (
    CONFIRM_UNSUPPORTED,
    CONFIRMS_NOTHING,
    DECISION_NOT_ACTIVE,
    DECISION_WRONG_ACCOUNT,
    KEEP_UNKNOWN,
    STALE_DECISION_REVISION,
    SUPERSEDES_NOTHING,
    GROUP_DISTINCT_IDS,
    GROUP_NOT_CONNECTED,
    GROUP_OUTSIDE,
    GROUP_REPEATED,
    GROUP_SHARES_DOCUMENT,
    ITEM_NOT_FOUND,
    ITEM_WRONG_ACCOUNT,
    STALE_ACCOUNT,
    STALE_REVISION,
    STATES_NOTHING,
    TOO_MANY,
    WOULD_CHANGE_MORE,
)
from personal_finance.reconcile.rules import DEFAULT_RULES


def confirm(ledger, item, *groups, revision=None, account="A", supersedes=None,
            supersedes_revision=None, keep=()):
    words = ["review", "confirm", item, "--account", account,
             "--revision", revision or ledger.revision(item)]
    for group in groups:
        words += ["--group", *group]
    if supersedes:
        words += ["--supersedes", supersedes, "--supersedes-revision",
                  supersedes_revision or ledger.decision_revision(supersedes)]
    for number in keep:
        words += ["--keep", str(number)]
    return ledger.run(*words)


def confirm_ok(ledger, item, *groups, **options):
    code, out, err = confirm(ledger, item, *groups, **options)
    assert code == 0, err
    return re.search(r"Decision (\S+) recorded", out)[1]


def relations(ledger):
    """Stated pairs per relation, as numbers of distinct pair numbers."""
    rows = ledger.dump()["decision_constraint"]
    found = {}
    for row in rows:
        found.setdefault(row[2], set()).add((row[1], row[3]))
    return {relation: len(pairs) for relation, pairs in found.items()}


def movement(ledger):
    return ledger.totals().splitlines()[:4]


@pytest.fixture
def ledger(tmp_path, capsys):
    return Ledger(tmp_path, capsys)


class TestConfirm:
    def test_a_two_member_item_joins_and_closes(self, ledger):  # C1
        item, one, two = pair_up(ledger)
        assert "Net account movement: -13.00" in ledger.totals()
        before = ledger.dump()

        code, out, _ = confirm(ledger, item, (one, two))

        assert code == 0
        assert "Transactions: 2 before, 1 now." in out
        assert f"Item {item} closed" in out
        assert CONFIRM_NOTICE in out
        assert ledger.count() == 1
        assert ledger.items() == []
        assert "Net account movement: -6.50" in ledger.totals()
        after = ledger.dump()
        for table in SOURCE_TABLES:
            assert after[table] == before[table], table
        assert {row[4] for row in after["transaction_source"]} == {"confirmed_same_event"}

    def test_moves_name_the_confirmation(self, ledger):
        item, one, two = pair_up(ledger)
        decision = confirm_ok(ledger, item, (one, two))
        conn = ledger.conn()
        moves = conn.execute(
            "SELECT action, reason, decision_id FROM transaction_link_history"
        ).fetchall()
        conn.close()
        assert moves == [("merged", "confirmed_same_event", decision)]

    def test_part_of_a_group_leaves_the_rest_open(self, ledger):  # C2
        item, one, two, three = three_of_them(ledger)
        code, out, _ = confirm(ledger, item, (one, two))
        assert code == 0 and f"Item {item} stays open" in out
        (remaining,) = ledger.items()
        members = ledger.transactions(remaining)
        assert len(members) == 2 and three in members
        assert len(ledger.direct_pairs(remaining)) == 1
        assert "Already decided, as one event:" in ledger.show(remaining)

    def test_the_stored_rows_are_the_stated_partition(self, ledger):  # C3
        item, one, two, three = three_of_them(ledger)
        code, out, _ = confirm(ledger, item, (one, two), (three,))
        assert code == 0 and f"Item {item} closed" in out
        assert relations(ledger) == {"same_event": 1, "different_event": 2}
        assert ledger.count() == 2
        assert ledger.items() == []

    def test_one_group_says_nothing_about_the_others(self, ledger):  # C4
        item, one, two, _ = three_of_them(ledger)
        confirm_ok(ledger, item, (one, two))
        assert relations(ledger) == {"same_event": 1}

    def test_a_chain_can_be_confirmed_through_its_middle(self, ledger):
        item, first, middle, last = chain(ledger)
        confirm_ok(ledger, item, (first, middle, last))
        assert ledger.count() == 1

    def test_the_way_groups_are_stated_does_not_matter(self, tmp_path, capsys):
        views = []
        for name, groups in (("one", (("a.csv", "b.csv"), ("c.csv",))),
                             ("two", (("c.csv",), ("b.csv", "a.csv")))):
            folder = tmp_path / name
            folder.mkdir()
            ledger = Ledger(folder, capsys)
            item, *_ = three_of_them(ledger)
            by_file = self.by_file(ledger)
            confirm_ok(ledger, item, *[[by_file[file] for file in group] for group in groups])
            views.append(ledger.view())
        assert views[0] == views[1]

    @staticmethod
    def by_file(ledger):
        conn = ledger.conn()
        found = dict(conn.execute(
            """SELECT document.file_name, link.transaction_id FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ).fetchall())
        conn.close()
        return found


class TestOneDocument:  # C6
    def two_rows_and_one(self, ledger):
        ledger.card("a.csv", CAFE, CAFE)
        ledger.card("b.csv", CAFE)
        (item,) = ledger.items()
        by_row = {}
        conn = ledger.conn()
        for transaction_id, name, row in conn.execute(
            """SELECT link.transaction_id, document.file_name, record.record_index
               FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id
               JOIN source_record record ON record.id = link.source_record_id"""
        ):
            by_row[name, row] = transaction_id
        conn.close()
        return item, by_row

    def test_the_partition_separates_them(self, ledger):
        item, rows = self.two_rows_and_one(ledger)
        first, second = sorted(key for key in rows if key[0] == "a.csv")
        (other,) = [key for key in rows if key[0] == "b.csv"]
        confirm_ok(ledger, item, (rows[first], rows[other]), (rows[second],))
        assert ledger.count() == 2
        assert ledger.items("cross_document") == []

    def test_one_group_of_all_three_is_refused(self, ledger):
        item, rows = self.two_rows_and_one(ledger)
        before = ledger.dump()
        code, _, err = confirm(ledger, item, tuple(rows.values()))
        assert code == 2 and GROUP_SHARES_DOCUMENT in err
        assert ledger.dump() == before


class TestRefusals:  # C5
    def refused(self, ledger, result, message, before):
        code, out, err = result
        assert code == 2
        assert message in err
        assert out == ""
        assert ledger.dump() == before

    def test_wrong_account(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.add_account("B")
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, (one, two), account="B"), ITEM_WRONG_ACCOUNT,
                     before)

    def test_unknown_item(self, ledger):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, "nope", (one, two), revision=token), ITEM_NOT_FOUND,
                     before)

    def test_an_old_token(self, ledger):
        item, one, two = pair_up(ledger)
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, (one, two), revision="r3-0000000000000000"),
                     STALE_REVISION, before)

    def test_a_version_2_token_of_the_same_digest(self, ledger):
        item, one, two = pair_up(ledger)
        token = "r2-" + ledger.revision(item)[3:]
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, (one, two), revision=token), STALE_REVISION,
                     before)

    def test_a_stale_account_is_refused_and_not_reconciled(self, ledger):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, (one, two), revision=token), STALE_ACCOUNT,
                     before)

    @pytest.mark.parametrize("shape", ["two groups", "one group"])
    def test_a_transaction_named_twice(self, ledger, shape):
        item, one, two, three = three_of_them(ledger)
        before = ledger.dump()
        groups = [(one, two), (two, three)] if shape == "two groups" else [(one, two, one)]
        self.refused(ledger, confirm(ledger, item, *groups), GROUP_REPEATED, before)

    def test_a_transaction_outside_the_item(self, ledger):
        ledger.card("a.csv", CAFE, OTHER)
        ledger.card("b.csv", CAFE)
        (item,) = ledger.items()
        one, two = ledger.transactions(item)
        conn = ledger.conn()
        (outside,) = [row[0] for row in conn.execute("SELECT id FROM ledger_transaction")
                      if row[0] not in (one, two)]
        conn.close()
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, (one, outside)), GROUP_OUTSIDE, before)

    def test_ends_of_a_chain_are_not_connected(self, ledger):
        item, first, _, last = chain(ledger)
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, (first, last)), GROUP_NOT_CONNECTED, before)

    def test_a_contradiction_without_supersedes(self, ledger):
        item, one, two, _ = three_of_them(ledger)
        decision = ledger.reject_ok(item, (one, two))
        before = ledger.dump()
        code, out, err = confirm(ledger, item, (one, two))
        self.refused(ledger, (code, out, err), "--supersedes", before)
        assert decision in err

    def test_too_many_transactions(self, ledger, monkeypatch):
        item, one, two, three = three_of_them(ledger)
        monkeypatch.setattr(decisions_module, "MAX_CONFIRMED", 2)
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, (one, two, three)), TOO_MANY.split(" at ")[0],
                     before)

    def test_fifty_is_the_limit(self):
        assert decisions_module.MAX_CONFIRMED == 50
        assert "at most 50 transactions" in TOO_MANY

    def test_one_transaction_states_nothing(self, ledger):
        item, one, _ = pair_up(ledger)
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, (one,)), STATES_NOTHING, before)

    def test_only_single_groups_on_a_candidate_item_is_a_rejection(self, ledger):
        item, one, two = pair_up(ledger)
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, (one,), (two,)), CONFIRMS_NOTHING, before)

    def test_an_external_id_item(self, ledger):
        ledger.checking("a.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        ledger.checking("b.csv", "S-1,2026-01-09,2026-01-12,SYNTHETIC CAFE,-5.00,POSTED")
        (item,) = ledger.items()
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, tuple(ledger.transactions(item))),
                     CONFIRM_UNSUPPORTED, before)

    def test_an_unresolved_item(self, ledger):
        ledger.card("a.csv", "01/10/2026,SYNTHETIC CAFE,not money,")
        (item,) = ledger.items()
        before = ledger.dump()
        self.refused(ledger, confirm(ledger, item, ("x", "y")), CONFIRM_UNSUPPORTED, before)


class TestSurvival:  # C7
    def confirmed(self, ledger):
        item, one, two = pair_up(ledger)
        confirm_ok(ledger, item, (one, two))
        return ledger.view()

    def test_a_repeat_import(self, ledger):
        view = self.confirmed(ledger)
        ledger.load_path(ledger.folder / "a.csv", *FIRST_HALF)
        assert ledger.view() == view

    def test_reconcile(self, ledger):
        view = self.confirmed(ledger)
        assert ledger.run("reconcile")[0] == 0
        assert ledger.view() == view

    def test_an_unrelated_file(self, ledger):
        self.confirmed(ledger)
        ledger.card("other.csv", OTHER)
        assert ledger.count() == 2
        assert ledger.items() == []

    def test_a_rules_change(self, ledger):
        view = self.confirmed(ledger)
        rules = replace(DEFAULT_RULES, date_window_days=0, similarity_threshold_percent=100)
        conn = ledger.conn()
        (account,) = conn.execute("SELECT id FROM account").fetchone()
        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, account, rules)
        conn.execute("COMMIT")
        conn.close()
        assert ledger.view()["transactions"] == view["transactions"]


class TestAutomaticEvidence:  # C8
    def test_a_valid_merge_joins_the_confirmed_unit(self, ledger):
        item, one, two = pair_up(ledger)
        confirm_ok(ledger, item, (one, two))
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        assert ledger.count() == 1
        assert ledger.items() == []
        assert "Net account movement: -6.50" in ledger.totals()

    def test_each_row_of_a_document_joins_only_its_own_unit(self, ledger):
        # a has two alike rows, and row 2 is confirmed with b. c pairs row for row with a.
        ledger.card("a.csv", CAFE, CAFE, extra=WHOLE_MONTH)
        ledger.card("b.csv", CAFE)
        (item,) = ledger.items()
        conn = ledger.conn()
        found = {
            (name, row): transaction_id
            for transaction_id, name, row in conn.execute(
                """SELECT link.transaction_id, document.file_name, record.record_index
                   FROM transaction_source link
                   JOIN source_document document ON document.id = link.source_document_id
                   JOIN source_record record ON record.id = link.source_record_id"""
            )
        }
        conn.close()
        confirm_ok(ledger, item, (found["a.csv", 2], found["b.csv", 1]))
        ledger.card("c.csv", CAFE, CAFE, extra=WHOLE_MONTH)
        assert ledger.count() == 2
        assert ledger.items("decision_conflict") == []
        conn = ledger.conn()
        sizes = sorted(row[0] for row in conn.execute(
            "SELECT COUNT(*) FROM transaction_source GROUP BY transaction_id"
        ))
        conn.close()
        assert sizes == [2, 3]


class TestConflicts:  # C9
    def withheld(self, ledger):
        conflict_on_a_merge(ledger)
        ledger.card("e.csv", CAFE, extra=WHOLE_MONTH)
        (conflict,) = ledger.items("decision_conflict")
        return conflict, TestConfirm.by_file(ledger)

    def test_a_partition_settles_a_withheld_match(self, ledger):
        conflict, by_file = self.withheld(ledger)
        assert ledger.count() == 4
        code, out, _ = confirm(ledger, conflict, (by_file["p.csv"], by_file["q.csv"],
                                                  by_file["e.csv"]), (by_file["b.csv"],))
        assert code == 0 and f"Item {conflict} closed" in out
        assert ledger.items() == []
        assert ledger.count() == 2
        assert "Decision conflicts" not in ledger.totals()

    def test_keeping_all_of_them_apart_settles_it(self, ledger):
        conflict, by_file = self.withheld(ledger)
        groups = [(by_file[name],) for name in ("p.csv", "q.csv", "b.csv", "e.csv")]
        assert confirm(ledger, conflict, *groups)[0] == 0
        assert ledger.items() == []
        assert ledger.count() == 4

    def test_part_of_a_conflict_leaves_it_open(self, ledger):
        conflict, by_file = self.withheld(ledger)
        assert confirm(ledger, conflict, (by_file["p.csv"], by_file["q.csv"]))[0] == 0
        assert len(ledger.items("decision_conflict")) == 1
        assert ledger.count() == 3

    def test_a_changed_basis_is_settled_by_a_partition(self, ledger):
        ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
        ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        ledger.card("x.csv", "01/10/2026,SYNTHETIC CAFE,5.00,")
        (item,) = ledger.items()
        ledger.reject_ok(item, ledger.direct_pairs(item)[0])
        ledger.checking("c.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")
        (conflict,) = ledger.items("decision_conflict")
        assert "decision_basis_changed" in ledger.show(conflict)

        members = ledger.transactions(conflict)
        assert confirm(ledger, conflict, *[(member,) for member in members])[0] == 0
        assert ledger.items("decision_conflict") == []
        assert ledger.count() == 4

    def test_joining_a_rejected_pair_needs_supersedes(self, ledger):
        conflict, by_file = self.withheld(ledger)
        before = ledger.dump()
        code, _, err = confirm(ledger, conflict, (by_file["p.csv"], by_file["b.csv"]))
        assert code == 2 and "keeps apart" in err
        assert ledger.dump() == before


class TestUndo:  # C12
    def test_equals_a_ledger_built_without_it(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        other = Ledger(tmp_path, capsys, "other.db")
        a = ledger.write("a.csv", CARD_HEADER, [CAFE])
        b = ledger.write("b.csv", CARD_HEADER, [CAFE])
        for target in (ledger, other):
            target.load_path(a, *FIRST_HALF)
            target.load_path(b, *SECOND_HALF)
        (item,) = ledger.items()
        decision = confirm_ok(ledger, item, tuple(ledger.transactions(item)))
        code, out, _ = ledger.undo(decision)
        assert code == 0 and "Transactions: 1 before, 2 now." in out
        assert ledger.view() == other.view()

    def test_equals_a_ledger_built_without_it_after_imports_since(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        other = Ledger(tmp_path, capsys, "other.db")
        a = ledger.write("a.csv", CARD_HEADER, [CAFE])
        b = ledger.write("b.csv", CARD_HEADER, [CAFE])
        c = ledger.write("c.csv", CARD_HEADER, [CAFE, OTHER])
        for target in (ledger, other):
            target.load_path(a, *FIRST_HALF)
            target.load_path(b, *SECOND_HALF)
        (item,) = ledger.items()
        decision = confirm_ok(ledger, item, tuple(ledger.transactions(item)))
        for target in (ledger, other):
            target.load_path(c)
        assert ledger.undo(decision)[0] == 0
        assert ledger.view() == other.view()

    def test_undo_revives_the_retired_id(self, ledger):  # C21
        item, one, two = pair_up(ledger)
        conn = ledger.conn()
        created = dict(conn.execute("SELECT id, created_at FROM ledger_transaction"))
        conn.close()
        decision = confirm_ok(ledger, item, (one, two))
        conn = ledger.conn()
        (kept,) = [row[0] for row in conn.execute("SELECT id FROM ledger_transaction")]
        conn.close()
        assert kept in (one, two)
        assert ledger.undo(decision)[0] == 0
        conn = ledger.conn()
        assert dict(conn.execute("SELECT id, created_at FROM ledger_transaction")) == created
        conn.close()


class TestLedgerGuard:  # C14
    @pytest.mark.parametrize(
        "statement",
        [
            "UPDATE transaction_source SET link_rule = link_rule WHERE 0",
            "DELETE FROM transaction_source WHERE source_record_id = "
            "(SELECT MIN(source_record_id) FROM transaction_source)",
        ],
        ids=["control", "an extra change"],
    )
    def test_more_than_the_stated_merges_rolls_back(self, ledger, monkeypatch, statement):
        ledger.card("a.csv", CAFE, OTHER, extra=FIRST_HALF)
        ledger.card("b.csv", CAFE, extra=SECOND_HALF)
        (item,) = ledger.items()
        token = ledger.revision(item)
        groups = [tuple(ledger.transactions(item))]
        before = ledger.dump()
        real = decisions_module.reconcile_account

        def changing(conn, *args, **kwargs):
            result = real(conn, *args, **kwargs)
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(statement)
            return result

        monkeypatch.setattr(decisions_module, "reconcile_account", changing)
        code, _, err = confirm(ledger, item, *groups, revision=token)
        if "WHERE 0" in statement:
            assert code == 0
        else:
            assert code == 2 and WOULD_CHANGE_MORE in err
            assert ledger.dump() == before


class TestTokens:  # C17
    def test_a_confirmation_changes_an_overlapping_items_token(self, ledger):
        ledger.card("a.csv", CAFE)
        ledger.card("b.csv", CAFE)
        ledger.card("c.csv", "01/12/2026,SYNTHETIC CAFE,6.50,")
        (item,) = ledger.items()
        token = ledger.revision(item)
        by_file = TestConfirm.by_file(ledger)
        confirm_ok(ledger, item, (by_file["a.csv"], by_file["b.csv"]))
        (remaining,) = ledger.items()
        assert ledger.revision(remaining) != token


class TestPrivacy:  # C13
    def test_confirm_prints_counts_and_no_amounts_or_descriptions(self, ledger):
        item, one, two = pair_up(ledger)
        code, out, err = confirm(ledger, item, (one, two))
        assert code == 0
        assert "6.50" not in out + err and "SYNTHETIC" not in out + err

    def test_refusals_print_no_amounts_or_descriptions(self, ledger):
        item, one, two = pair_up(ledger)
        code, out, err = confirm(ledger, item, (one,), (two,))
        assert code == 2
        assert "6.50" not in out + err and "SYNTHETIC" not in out + err


def state_of(ledger, decision):
    out = ledger.run("review", "decision", "show", decision)[1]
    return re.search(r"Status: (\S+)", out)[1]


def four_of_them(ledger):
    """Four lookalikes, so that rejecting a few pairs still leaves all four in the item."""
    for name in ("a.csv", "b.csv", "c.csv", "d.csv"):
        ledger.card(name, CAFE)
    (item,) = ledger.items()
    by_file = TestConfirm.by_file(ledger)
    return item, *(by_file[name] for name in ("a.csv", "b.csv", "c.csv", "d.csv"))


class TestSuperseding:  # C10, C11
    def rejected(self, ledger, *pairs):
        item, one, two, three = three_of_them(ledger)
        named = {"one": one, "two": two, "three": three}
        decision = ledger.reject_ok(item, *[(named[left], named[right]) for left, right in pairs])
        return item, decision, one, two, three

    def test_a_confirmation_replaces_a_rejection(self, ledger):
        item, old, one, two, _ = self.rejected(ledger, ("one", "two"))
        code, out, _ = confirm(ledger, item, (one, two), supersedes=old)
        assert code == 0
        assert f"Supersedes decision {old}: 1 of its pairs contradicted, 0 kept." in out
        assert ledger.count() == 2
        assert state_of(ledger, old) == "superseded"
        shown = ledger.run("review", "decision", "show", old)[1]
        assert "Superseded by decision" in shown and "Revision" not in shown

    def test_the_result_equals_confirming_without_the_rejection(self, tmp_path, capsys):
        views = []
        for name, reject_first in (("one", True), ("two", False)):
            folder = tmp_path / name
            folder.mkdir()
            ledger = Ledger(folder, capsys)
            item, one, two, _ = three_of_them(ledger)
            if reject_first:
                old = ledger.reject_ok(item, (one, two))
                confirm_ok(ledger, item, (one, two), supersedes=old)
            else:
                confirm_ok(ledger, item, (one, two))
            views.append(ledger.view())
        assert views[0] == views[1]

    def test_every_old_pair_must_be_contradicted_or_kept(self, ledger):
        item, one, two, three, _ = four_of_them(ledger)
        old = ledger.reject_ok(item, (one, two), (one, three))
        before = ledger.dump()
        code, _, err = confirm(ledger, item, (one, two), supersedes=old)
        assert code == 2 and "pair 2 of the superseded decision" in err and "--keep 2" in err
        assert ledger.dump() == before

    def test_a_kept_pair_is_copied_record_for_record(self, ledger):
        item, one, two, three, _ = four_of_them(ledger)
        old = ledger.reject_ok(item, (one, two), (one, three))
        conn = ledger.conn()
        old_rows = conn.execute(
            """SELECT relation, left_record_id, right_record_id FROM decision_constraint
               WHERE decision_id = ? AND pair_number = 2""",
            (old,),
        ).fetchall()
        conn.close()
        new = confirm_ok(ledger, item, (one, two), supersedes=old, keep=(2,))
        conn = ledger.conn()
        new_rows = conn.execute(
            """SELECT relation, left_record_id, right_record_id FROM decision_constraint
               WHERE decision_id = ? AND relation = 'different_event'""",
            (new,),
        ).fetchall()
        conn.close()
        assert new_rows == old_rows and len(new_rows) == 1
        # The joined transaction stays apart from three, and both are undecided against four.
        (remaining,) = ledger.items()
        pairs = [set(pair) for pair in ledger.direct_pairs(remaining)]
        assert len(pairs) == 2
        assert not any(three in pair and pair & {one, two} for pair in pairs)

    @pytest.mark.parametrize("keep, message", [((1,), "cannot be kept"), ((5,), KEEP_UNKNOWN)])
    def test_a_bad_keep_is_refused(self, ledger, keep, message):
        item, old, one, two, _ = self.rejected(ledger, ("one", "two"))
        before = ledger.dump()
        code, _, err = confirm(ledger, item, (one, two), supersedes=old, keep=keep)
        assert code == 2 and message in err
        assert ledger.dump() == before

    def test_superseding_what_is_not_contradicted_is_refused(self, ledger):
        item, old, one, two, _ = self.rejected(ledger, ("one", "three"))
        before = ledger.dump()
        code, _, err = confirm(ledger, item, (one, two), supersedes=old, keep=(1,))
        assert code == 2 and SUPERSEDES_NOTHING in err
        assert ledger.dump() == before

    def test_only_the_named_decision_can_be_contradicted(self, ledger):
        item, one, two, three, _ = four_of_them(ledger)
        first = ledger.reject_ok(item, (one, two))
        second = ledger.reject_ok(item, (two, three))
        before = ledger.dump()
        code, _, err = confirm(ledger, item, (one, two, three), supersedes=first)
        assert code == 2 and "only the decision named with --supersedes" in err and second in err
        assert ledger.dump() == before

    @pytest.mark.parametrize("stale", ["item", "decision"])
    def test_both_tokens_are_checked(self, ledger, stale):
        item, old, one, two, _ = self.rejected(ledger, ("one", "two"))
        before = ledger.dump()
        if stale == "item":
            result = confirm(ledger, item, (one, two), revision="r3-0000000000000000",
                             supersedes=old)
            message = STALE_REVISION
        else:
            result = confirm(ledger, item, (one, two), supersedes=old,
                             supersedes_revision="d2-0000000000000000")
            message = STALE_DECISION_REVISION
        assert result[0] == 2 and message in result[2]
        assert ledger.dump() == before

    def test_an_undone_decision_cannot_be_superseded(self, ledger):
        item, old, one, two, _ = self.rejected(ledger, ("one", "two"))
        token = ledger.decision_revision(old)
        assert ledger.undo(old)[0] == 0
        (item,) = ledger.items()
        code, _, err = confirm(ledger, item, (one, two), supersedes=old, supersedes_revision=token)
        assert code == 2 and DECISION_NOT_ACTIVE in err

    def test_the_two_options_go_together(self, ledger):
        item, one, two = pair_up(ledger)
        code, _, err = ledger.run("review", "confirm", item, "--account", "A", "--revision",
                                  ledger.revision(item), "--group", one, two, "--keep", "1")
        assert code == 2 and "--keep needs --supersedes" in err

    def test_undo_restores_the_superseded_decision(self, ledger):
        item, old, one, two, _ = self.rejected(ledger, ("one", "two"))
        view = ledger.view()
        new = confirm_ok(ledger, item, (one, two), supersedes=old)
        assert "Restores decision" in ledger.run("review", "decision", "show", new)[1]
        code, out, _ = ledger.undo(new)
        assert code == 0 and f"Decision {old}, which it superseded, applies again." in out
        assert state_of(ledger, old) == "active"
        restored = ledger.view()
        assert restored["constraints"] == view["constraints"]
        assert restored["movement"] == view["movement"]

    def test_a_superseded_decision_cannot_be_undone(self, ledger):
        item, old, one, two, _ = self.rejected(ledger, ("one", "two"))
        token = ledger.decision_revision(old)
        new = confirm_ok(ledger, item, (one, two), supersedes=old)
        before = ledger.dump()
        code, _, err = ledger.undo(old, token)
        assert code == 2 and new in err and "Undo that decision instead" in err
        assert ledger.dump() == before

    def test_undo_refuses_to_restore_a_contradiction(self, ledger):
        item, old, one, two, _ = self.rejected(ledger, ("one", "two"))
        new = confirm_ok(ledger, item, (one, two), supersedes=old)
        (remaining,) = ledger.items()
        later = confirm_ok(ledger, remaining, tuple(ledger.transactions(remaining)))
        assert ledger.count() == 1
        before = ledger.dump()
        code, _, err = ledger.undo(new)
        assert code == 2 and f"restore decision {old}" in err
        assert ledger.dump() == before

        assert ledger.undo(later)[0] == 0
        assert ledger.undo(new)[0] == 0
        assert ledger.count() == 3
        assert state_of(ledger, old) == "active"

    def test_a_rejection_that_closed_its_item_is_undone_then_confirmed(self, ledger):
        item, one, two = pair_up(ledger)
        old = ledger.reject_ok(item, (one, two))
        assert ledger.items() == []
        assert ledger.undo(old)[0] == 0
        (reopened,) = ledger.items()
        confirm_ok(ledger, reopened, tuple(ledger.transactions(reopened)))
        assert ledger.count() == 1

    def test_the_decision_list_shows_kinds_and_states(self, ledger):
        item, old, one, two, _ = self.rejected(ledger, ("one", "two"))
        new = confirm_ok(ledger, item, (one, two), supersedes=old)
        out = ledger.run("review", "decisions")[1]
        assert f"Decision {old}: superseded, reject, 1 pairs" in out
        assert f"Decision {new}: active, confirm, 1 pairs" in out


class TestTotals:  # C13
    def test_totals_disclose_confirmed_transactions(self, ledger):
        item, one, two, _ = three_of_them(ledger)
        assert "confirmed as one event" not in ledger.totals()
        confirm_ok(ledger, item, (one, two))
        assert "- 1 transactions hold records you confirmed as one event" in ledger.totals()

    def test_the_line_goes_with_undo(self, ledger):
        item, one, two = pair_up(ledger)
        decision = confirm_ok(ledger, item, (one, two))
        assert ledger.undo(decision)[0] == 0
        assert "confirmed as one event" not in ledger.totals()


class TestMoreRefusals:
    def test_an_item_that_is_not_open(self, ledger):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        conn = ledger.conn()
        conn.execute("UPDATE review_issue SET status = 'resolved', resolved_at = '2026-02-01'")
        conn.close()
        code, _, err = confirm(ledger, item, (one, two), revision=token)
        assert code == 2 and "not open" in err

    def test_superseding_another_accounts_decision(self, ledger):
        item, one, two, _ = three_of_them(ledger)
        old = ledger.reject_ok(item, (one, two))
        token = ledger.decision_revision(old)
        ledger.add_account("B")
        ledger.card("x.csv", CAFE, account="B")
        ledger.card("y.csv", CAFE, account="B")
        (other,) = set(ledger.items()) - {item}
        before = ledger.dump()
        code, _, err = confirm(ledger, other, tuple(ledger.transactions(other)), account="B",
                               supersedes=old, supersedes_revision=token)
        assert code == 2 and DECISION_WRONG_ACCOUNT in err
        assert ledger.dump() == before

    def test_supersedes_needs_its_revision(self, ledger):
        item, one, two, _ = three_of_them(ledger)
        old = ledger.reject_ok(item, (one, two))
        code, _, err = ledger.run("review", "confirm", item, "--account", "A", "--revision",
                                  ledger.revision(item), "--group", one, two, "--supersedes", old)
        assert code == 2 and "must be given together" in err

    def test_the_undo_preview_counts_the_restored_decision(self, ledger):
        item, one, two, _ = three_of_them(ledger)
        old = ledger.reject_ok(item, (one, two))
        new = confirm_ok(ledger, item, (one, two), supersedes=old)
        out = ledger.run("review", "decision", "show", new)[1]
        assert "Transactions: 2 now, 3 after" in out


class TestUniqueIds:  # D-026
    def test_a_chain_cannot_join_two_unique_ids(self, ledger):
        ledger.checking("a.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        ledger.card("b.csv", "01/10/2026,SYNTHETIC CAFE,5.00,")
        ledger.checking("c.csv", "S-2,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        (item,) = ledger.items()
        before = ledger.dump()
        code, _, err = confirm(ledger, item, tuple(ledger.transactions(item)))
        assert code == 2 and GROUP_DISTINCT_IDS in err
        assert ledger.dump() == before


class TestSupersedingConfirmations:  # C10, C11
    def test_a_confirmations_same_event_pair_must_be_kept(self, ledger):
        item, one, two, three = three_of_them(ledger)
        old = confirm_ok(ledger, item, (one, two), (three,))
        conn = ledger.conn()
        (joined,) = [row[0] for row in conn.execute("SELECT id FROM ledger_transaction")
                     if row[0] in (one, two)]
        conn.close()
        assert ledger.undo(old)[0] == 0
        (item,) = ledger.items()
        old = confirm_ok(ledger, item, (one, two), (three,))
        ledger.card("d.csv", CAFE)
        (item,) = ledger.items()
        before = ledger.dump()
        code, _, err = confirm(ledger, item, (joined, three), supersedes=old)
        # Pairs between groups are numbered first, so the same_event pair is the third.
        assert code == 2 and "pair 3 of the superseded decision" in err
        assert ledger.dump() == before
        assert confirm(ledger, item, (joined, three), supersedes=old, keep=(3,))[0] == 0
        assert ledger.count() == 2

    def test_the_undo_preview_counts_a_withholding_restored(self, ledger):
        # A and B are halves, x is a lookalike. Restoring A≠B withholds C's later match.
        ledger.card("a.csv", CAFE, extra=FIRST_HALF)
        ledger.card("b.csv", CAFE, extra=SECOND_HALF)
        ledger.card("x.csv", CAFE)
        (item,) = ledger.items()
        by_file = TestConfirm.by_file(ledger)
        old = ledger.reject_ok(item, (by_file["a.csv"], by_file["b.csv"]))
        new = confirm_ok(ledger, item, (by_file["a.csv"], by_file["b.csv"]), supersedes=old)
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        assert ledger.count() == 2
        out = ledger.run("review", "decision", "show", new)[1]
        assert "Transactions: 2 now, 4 after" in out
        assert ledger.undo(new)[0] == 0
        assert ledger.count() == 4
