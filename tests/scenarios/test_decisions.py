"""Rejecting pairs and undoing decisions, end to end, using synthetic data only (D-042 to D-045)."""

import re
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from ledger_view import semantic_view

from personal_finance import cli
from personal_finance.cli import CONFLICT_NOTICE, UNDO_NOTICE, main
from personal_finance.db.migrate import connect
from personal_finance.reconcile import decisions as decisions_module
from personal_finance.reconcile.apply import load_constraints, reconcile_account
from personal_finance.reconcile.cross_document import (
    REASON_WITHHELD,
    RULE_CANDIDATES,
    ReviewItem,
)
from personal_finance.reconcile.decisions import (
    DECISION_NOT_ACTIVE,
    DECISION_WRONG_ACCOUNT,
    ITEM_NOT_FOUND,
    ITEM_UNSUPPORTED,
    ITEM_WRONG_ACCOUNT,
    PAIR_DECIDED,
    PAIR_NOT_DIRECT,
    PAIR_OUTSIDE,
    PAIR_REPEATED,
    PAIR_SAME,
    STALE_ACCOUNT,
    STALE_DECISION_REVISION,
    STALE_REVISION,
    WOULD_CHANGE_LEDGER,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports import decision_evidence
from personal_finance.reports.decision_evidence import load_decision, undo_outlook

CARD_HEADER = "Date,Description,Debit,Credit\n"
CHECKING_HEADER = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
CAFE = "01/10/2026,SYNTHETIC CAFE,6.50,"
OTHER = "03/20/2026,SYNTHETIC GROCER,9.00,"

SOURCE_TABLES = ("source_document", "source_record", "record_parse", "document_coverage",
                 "document_interpretation", "source_record_origin")
ALL_TABLES = (*SOURCE_TABLES, "ledger_transaction", "transaction_source", "review_issue",
              "review_issue_subject", "transaction_link_history", "transaction_identity_history",
              "decision", "decision_constraint", "decision_event", "account_reconciliation",
              "value_correction", "value_correction_record", "value_correction_event",
              "transaction_correction", "record_resolution", "record_resolution_event",
              "coverage_declaration", "coverage_declaration_event", "type_classification",
              "type_classification_record", "type_classification_event",
              "transaction_classification", "transfer_match", "transfer_match_side",
              "transfer_match_record", "transfer_match_event", "transfer_match_effect")
# Created by 0010, 0011, 0013 and 0014, children first (D-050, D-051, D-053, D-054).
RESOLUTION_TABLES = ("record_resolution_event", "record_resolution")
DECLARATION_TABLES = ("coverage_declaration_event", "coverage_declaration")
CLASSIFICATION_TABLES = ("transaction_classification", "type_classification_event",
                         "type_classification_record", "type_classification")
TRANSFER_TABLES = ("transfer_match_effect", "transfer_match_event", "transfer_match_record",
                   "transfer_match_side", "transfer_match")


def declared(start, end):
    return ["--declare-complete-coverage", "--coverage-start", start, "--coverage-end", end,
            "--coverage-basis", "posting"]


# Two exports overlapping by a single day do not merge, and one spanning both merges with each.
FIRST_HALF = declared("2026-01-01", "2026-01-10")
SECOND_HALF = declared("2026-01-10", "2026-01-20")
WHOLE_MONTH = declared("2026-01-01", "2026-01-20")


class Ledger:
    def __init__(self, folder: Path, capsys, name="ledger.db"):
        self.folder = folder
        self.path = folder / name
        self.capsys = capsys
        self.db = str(self.path)
        self.files = 0
        assert self.run("init")[0] == 0
        self.add_account("A")

    def add_account(self, name, account_type="checking"):
        code, _, _ = self.run("account", "add", "--name", name, "--type", account_type)
        assert code == 0

    def run(self, *command):
        self.capsys.readouterr()
        words = list(command)
        position = 2 if words[0] in ("account", "review") else 1
        if words[:2] in (["review", "decision"], ["review", "merge"], ["review", "transaction"],
                         ["review", "correction"], ["review", "resolution"],
                         ["review", "coverage"], ["review", "classification"]):
            position = 3
        words[position:position] = ["--db", self.db]
        code = main(words)
        captured = self.capsys.readouterr()
        return code, captured.out, captured.err

    def write(self, name, header, rows):
        # Spaces the parser strips, so that files with equal rows are not byte-identical.
        self.files += 1
        path = self.folder / name
        path.write_text(header + " " * self.files + "".join(f"{row}\n" for row in rows))
        return path

    def load_path(self, path, *extra, account="A", layout="synthetic_card_v1"):
        code, out, _ = self.run("import", "--account", account, "--layout", layout, *extra, str(path))
        assert code == 0, out
        return out

    def card(self, name, *rows, extra=(), account="A"):
        return self.load_path(self.write(name, CARD_HEADER, rows), *extra, account=account)

    def checking(self, name, *rows):
        return self.load_path(
            self.write(name, CHECKING_HEADER, rows), layout="synthetic_checking_v1"
        )

    def conn(self):
        return connect(self.path)

    def items(self, text=""):
        out = self.run("review", "list")[1]
        return re.findall(rf"^Item (\S+): .*{re.escape(text)}", out, re.MULTILINE)

    def show(self, item):
        code, out, _ = self.run("review", "show", item)
        assert code == 0
        return out

    def revision(self, item):
        return re.search(r"Revision: (r7-[0-9a-f]{16})", self.show(item))[1]

    def transactions(self, item):
        return re.findall(r"^Transaction \d+ of \d+: (\S+)", self.show(item), re.MULTILINE)

    def direct_pairs(self, item):
        section = self.show(item).split("Direct candidate pairs, undecided:\n")[1]
        return re.findall(r"^  ([0-9a-f-]{36}) ([0-9a-f-]{36})$", section, re.MULTILINE)

    def reject(self, item, *pairs, revision=None, account="A"):
        words = ["review", "reject", item, "--account", account,
                 "--revision", revision or self.revision(item)]
        for left, right in pairs:
            words += ["--pair", left, right]
        return self.run(*words)

    def reject_ok(self, item, *pairs):
        code, out, err = self.reject(item, *pairs)
        assert code == 0, err
        return re.search(r"Decision (\S+) recorded", out)[1]

    def decision_revision(self, decision):
        out = self.run("review", "decision", "show", decision)[1]
        return re.search(r"Revision: (d6-[0-9a-f]{16})", out)[1]

    def undo(self, decision, revision=None, account="A"):
        return self.run("review", "undo", decision, "--account", account,
                        "--revision", revision or self.decision_revision(decision))

    def totals(self):
        return self.run("totals")[1]

    def count(self):
        conn = self.conn()
        found = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()[0]
        conn.close()
        return found

    def dump(self, tables=ALL_TABLES):
        conn = self.conn()
        found = {
            table: sorted(conn.execute(f"SELECT * FROM {table}").fetchall(), key=repr)
            for table in tables
        }
        conn.close()
        return found

    def view(self):
        conn = self.conn()
        found = semantic_view(conn)
        conn.close()
        return found


@pytest.fixture
def ledger(tmp_path, capsys):
    return Ledger(tmp_path, capsys)


def pair_up(ledger):
    """Two unmerged candidates, returning their item and their two transactions."""
    ledger.card("a.csv", CAFE, extra=FIRST_HALF)
    ledger.card("b.csv", CAFE, extra=SECOND_HALF)
    (item,) = ledger.items()
    return item, *ledger.transactions(item)


def three_of_them(ledger):
    for name in ("a.csv", "b.csv", "c.csv"):
        ledger.card(name, CAFE)
    (item,) = ledger.items()
    return item, *ledger.transactions(item)


def chain(ledger):
    """A–B–C: A and C are too far apart to be linked directly."""
    ledger.card("a.csv", "01/01/2026,SYNTHETIC CAFE,6.50,")
    ledger.card("b.csv", "01/04/2026,SYNTHETIC CAFE,6.50,")
    ledger.card("c.csv", "01/07/2026,SYNTHETIC CAFE,6.50,")
    (item,) = ledger.items()
    return item, *ledger.transactions(item)


def conflict_on_a_merge(ledger):
    """{P,Q} merged and rejected against B, then E, which joins everything, arrives."""
    ledger.card("p.csv", CAFE, extra=FIRST_HALF)
    ledger.card("q.csv", CAFE, extra=FIRST_HALF)
    ledger.card("b.csv", CAFE, extra=SECOND_HALF)
    (item,) = ledger.items()
    assert ledger.count() == 2
    decision = ledger.reject_ok(item, ledger.direct_pairs(item)[0])
    return decision


class TestReject:
    def test_totals_and_memberships_stay_and_source_evidence_is_identical(self, ledger):  # S3
        item, one, two = pair_up(ledger)
        before, totals = ledger.dump(), ledger.totals().splitlines()[:4]

        ledger.reject_ok(item, (one, two))

        after = ledger.dump()
        assert ledger.totals().splitlines()[:4] == totals
        for table in (*SOURCE_TABLES, "ledger_transaction", "transaction_source",
                      "transaction_link_history", "transaction_identity_history"):
            assert after[table] == before[table], table

    def test_it_binds_the_cross_product_of_the_records(self, ledger):
        ledger.card("p.csv", CAFE, extra=FIRST_HALF)
        ledger.card("q.csv", CAFE, extra=FIRST_HALF)
        ledger.card("b.csv", CAFE, extra=SECOND_HALF)
        (item,) = ledger.items()
        (pair,) = ledger.direct_pairs(item)
        code, out, _ = ledger.reject(item, pair)
        assert code == 0
        assert "Source-record pairs bound: 2. New records are not bound." in out
        assert len(ledger.dump()["decision_constraint"]) == 2

    def test_a_two_member_item_closes_and_undo_raises_a_new_one(self, ledger):  # S4
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)

        code, out, _ = ledger.reject(item, (one, two))
        assert code == 0 and f"Item {item} closed" in out
        assert ledger.items() == []
        assert ledger.dump()["review_issue"] == []
        decision = re.search(r"Decision (\S+) recorded", out)[1]

        assert ledger.undo(decision)[0] == 0
        (reopened,) = ledger.items()
        assert reopened != item
        assert ledger.revision(reopened) == token

    def test_no_item_is_ever_marked_resolved(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.reject_ok(item, (one, two))
        assert not [row for row in ledger.dump()["review_issue"] if row[2] == "resolved"]

    def test_a_three_member_item_keeps_the_undecided_pairs_open(self, ledger):  # S4
        item, one, two, three = three_of_them(ledger)
        code, out, _ = ledger.reject(item, (one, two))
        assert code == 0 and f"Item {item} stays open" in out
        assert ledger.items() == [item]
        remaining = {frozenset(pair) for pair in ledger.direct_pairs(item)}
        assert remaining == {frozenset((one, three)), frozenset((two, three))}

    def test_several_pairs_are_one_atomic_decision(self, ledger):
        item, one, two, three = three_of_them(ledger)
        code, out, _ = ledger.reject(item, (one, two), (one, three))
        assert code == 0 and "2 pairs rejected" in out
        assert len(ledger.dump()["decision"]) == 1
        assert ledger.transactions(item) == [two, three] or set(ledger.transactions(item)) == {
            two, three
        }

    def test_review_show_lists_the_decided_pair_and_the_account(self, ledger):
        item, one, two, _ = three_of_them(ledger)
        decision = ledger.reject_ok(item, (one, two))
        out = ledger.show(item)
        assert "Account: A (" in out
        assert "Already decided, as different events:" in out
        assert f"Decision {decision}:" in out

    def test_the_revision_changes_with_a_decision(self, ledger):
        item, one, two, _ = three_of_them(ledger)
        before = ledger.revision(item)
        ledger.reject_ok(item, (one, two))
        assert ledger.revision(item) != before


class TestItemRevision:
    def built(self, tmp_path, capsys, name, stated):
        """Three lookalikes from shared files, with decisions stated as the caller chooses."""
        ledger = Ledger(tmp_path, capsys, name)
        for path in sorted(tmp_path.glob("*.csv")):
            ledger.load_path(path)
        (item,) = ledger.items()
        by_file = {}
        conn = ledger.conn()
        for transaction_id, file_name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            by_file[file_name] = transaction_id
        conn.close()
        for left, right in stated:
            ledger.reject_ok(item, (by_file[left], by_file[right]))
        return ledger.revision(item)

    def test_it_does_not_depend_on_how_decisions_were_stated(self, tmp_path, capsys):
        writer = Ledger(tmp_path, capsys, "writer.db")
        for name in ("a.csv", "b.csv", "c.csv", "d.csv"):
            writer.write(name, CARD_HEADER, [CAFE])
        plain = self.built(tmp_path, capsys, "one.db", [("a.csv", "b.csv"), ("c.csv", "d.csv")])
        swapped = self.built(tmp_path, capsys, "two.db", [("b.csv", "a.csv"), ("d.csv", "c.csv")])
        reordered = self.built(tmp_path, capsys, "three.db", [("d.csv", "c.csv"), ("a.csv", "b.csv")])
        assert plain == swapped == reordered

    def test_a_decision_elsewhere_in_the_account_does_not_change_it(self, ledger):
        ledger.card("a.csv", CAFE, "04/10/2026,SYNTHETIC BOOKS,9.00,")
        ledger.card("b.csv", CAFE, "04/10/2026,SYNTHETIC BOOKS,9.00,")
        first, second = ledger.items()
        token = ledger.revision(second)
        ledger.reject_ok(first, tuple(ledger.transactions(first)))
        assert ledger.revision(second) == token


class TestDirectPairsOnly:
    def test_a_chain_cannot_reject_its_ends(self, ledger):  # S18
        item, one, two, three = chain(ledger)
        before = ledger.dump()
        code, _, err = ledger.reject(item, (one, three))
        assert code == 2 and PAIR_NOT_DIRECT in err
        assert ledger.dump() == before

    def test_a_chain_lists_only_its_direct_pairs(self, ledger):
        item, one, two, three = chain(ledger)
        assert {frozenset(pair) for pair in ledger.direct_pairs(item)} == {
            frozenset((one, two)), frozenset((two, three))
        }

    def test_one_bad_pair_refuses_the_whole_decision(self, ledger):
        item, one, two, three = chain(ledger)
        before = ledger.dump()
        code, _, err = ledger.reject(item, (one, two), (one, three))
        assert code == 2 and PAIR_NOT_DIRECT in err
        assert ledger.dump() == before

    def test_a_link_of_the_chain_can_be_rejected(self, ledger):
        item, one, two, three = chain(ledger)
        ledger.reject_ok(item, (one, two))
        assert set(ledger.transactions(item)) == {two, three}

    def test_two_records_of_one_document_are_not_a_direct_pair(self, ledger):
        ledger.card("a.csv", CAFE, CAFE)
        ledger.card("b.csv", CAFE)
        item = next(iter(ledger.items("cross_document_candidates")))
        one, two = [
            row[0] for row in ledger.conn().execute(
                """SELECT link.transaction_id FROM transaction_source link
                   JOIN source_document document ON document.id = link.source_document_id
                   WHERE document.file_name = 'a.csv'"""
            )
        ]
        code, _, err = ledger.reject(item, (one, two))
        assert code == 2 and PAIR_NOT_DIRECT in err

    def test_a_long_list_of_pairs_says_it_stops(self, ledger, monkeypatch):
        monkeypatch.setattr(cli, "DIRECT_PAIRS_SHOWN", 1)
        item, *_ = three_of_them(ledger)
        out = ledger.show(item)
        assert "Only the first 1 are listed." in out
        assert len(ledger.direct_pairs(item)) == 1

    def test_a_short_list_says_nothing_of_the_kind(self, ledger):
        item, *_ = three_of_them(ledger)
        assert "are listed" not in ledger.show(item)

    def test_a_rejected_pair_is_refused_when_repeated(self, ledger):
        item, one, two, _ = three_of_them(ledger)
        ledger.reject_ok(item, (one, two))
        before = ledger.dump()
        code, _, err = ledger.reject(item, (two, one))
        assert code == 2 and PAIR_DECIDED in err
        assert ledger.dump() == before


class TestRefusals:  # S5
    def refused(self, ledger, result, message):
        code, out, err = result
        assert code == 2
        assert message in err
        assert out == ""

    def test_wrong_account(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.add_account("B")
        before = ledger.dump()
        self.refused(ledger, ledger.reject(item, (one, two), account="B"), ITEM_WRONG_ACCOUNT)
        assert ledger.dump() == before

    def test_unknown_item(self, ledger):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        before = ledger.dump()
        self.refused(ledger, ledger.reject("no-such-item", (one, two), revision=token),
                     ITEM_NOT_FOUND)
        assert ledger.dump() == before

    def test_a_matching_token_on_the_wrong_item(self, ledger):
        ledger.card("a.csv", CAFE, "02/10/2026,SYNTHETIC BOOKS,9.00,")
        ledger.card("b.csv", CAFE, "02/10/2026,SYNTHETIC BOOKS,9.00,")
        first, second = ledger.items()
        before = ledger.dump()
        code, _, err = ledger.reject(
            second, *[tuple(ledger.transactions(second))], revision=ledger.revision(first)
        )
        assert code == 2 and STALE_REVISION in err
        assert ledger.dump() == before

    def test_an_old_token(self, ledger):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        ledger.card("c.csv", CAFE)
        before = ledger.dump()
        self.refused(ledger, ledger.reject(item, (one, two), revision=token), STALE_REVISION)
        assert ledger.dump() == before

    def test_an_invented_token(self, ledger):
        item, one, two = pair_up(ledger)
        self.refused(ledger, ledger.reject(item, (one, two), revision="r2-0000000000000000"),
                     STALE_REVISION)

    def test_a_version_2_token_of_the_same_digest(self, ledger):
        item, one, two = pair_up(ledger)
        token = "r2-" + ledger.revision(item)[3:]
        self.refused(ledger, ledger.reject(item, (one, two), revision=token), STALE_REVISION)

    def test_a_pair_outside_the_item(self, ledger):
        ledger.card("a.csv", CAFE, OTHER)
        ledger.card("b.csv", CAFE)
        (item,) = ledger.items()
        one, _ = ledger.transactions(item)
        conn = ledger.conn()
        (outside,) = conn.execute(
            "SELECT id FROM ledger_transaction WHERE description = 'SYNTHETIC GROCER'"
        ).fetchone()
        conn.close()
        before = ledger.dump()
        self.refused(ledger, ledger.reject(item, (one, outside)), PAIR_OUTSIDE)
        assert ledger.dump() == before

    def test_the_same_transaction_twice(self, ledger):
        item, one, _ = pair_up(ledger)
        self.refused(ledger, ledger.reject(item, (one, one)), PAIR_SAME)

    @pytest.mark.parametrize("flip", [False, True])
    def test_a_repeated_pair(self, ledger, flip):
        item, one, two = pair_up(ledger)
        again = (two, one) if flip else (one, two)
        before = ledger.dump()
        self.refused(ledger, ledger.reject(item, (one, two), again), PAIR_REPEATED)
        assert ledger.dump() == before

    def test_an_external_id_item(self, ledger):
        ledger.checking("a.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        ledger.checking("b.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")
        (item,) = ledger.items("cross_document_external_id")
        before = ledger.dump()
        self.refused(ledger, ledger.reject(item, tuple(ledger.transactions(item))), ITEM_UNSUPPORTED)
        assert ledger.dump() == before

    def test_an_unresolved_item(self, ledger):
        ledger.card("a.csv", "01/10/2026,SYNTHETIC CAFE,not money,")
        (item,) = ledger.items()
        self.refused(ledger, ledger.reject(item, ("x", "y")), ITEM_UNSUPPORTED)

    def test_a_decision_conflict_item(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.reject_ok(item, (one, two))
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        (conflict,) = ledger.items("decision_conflict")
        first, second, *_ = ledger.transactions(conflict)
        self.refused(ledger, ledger.reject(conflict, (first, second)), ITEM_UNSUPPORTED)

    def test_an_item_of_any_status_other_than_open(self, ledger):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        conn = ledger.conn()
        conn.execute("UPDATE review_issue SET status = 'resolved', resolved_at = '2026-02-01'")
        conn.close()
        code, _, err = ledger.reject(item, (one, two), revision=token)
        assert code == 2 and "not open" in err


class TestStaleAccount:  # S6
    def stale(self, ledger):
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()

    def test_a_rejection_is_refused_and_nothing_is_reconciled(self, ledger):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        self.stale(ledger)
        before = ledger.dump()
        code, _, err = ledger.reject(item, (one, two), revision=token)
        assert code == 2 and STALE_ACCOUNT in err
        assert ledger.dump() == before

    def test_an_undo_is_refused_and_nothing_is_reconciled(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        token = ledger.decision_revision(decision)
        self.stale(ledger)
        before = ledger.dump()
        code, _, err = ledger.undo(decision, token)
        assert code == 2 and STALE_ACCOUNT in err
        assert ledger.dump() == before

    def test_decision_show_warns(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        self.stale(ledger)
        out = ledger.run("review", "decision", "show", decision)[1]
        assert "undo will be refused until it is" in out

    def test_reconciling_then_inspecting_again_works(self, ledger):
        item, one, two = pair_up(ledger)
        self.stale(ledger)
        assert ledger.run("reconcile")[0] == 0
        assert ledger.reject(item, (one, two))[0] == 0


class TestSurvival:  # S7
    def decided(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.reject_ok(item, (one, two))
        return ledger.view()

    def test_a_repeat_import(self, ledger):
        view = self.decided(ledger)
        ledger.load_path(ledger.folder / "a.csv", *FIRST_HALF)
        assert ledger.view() == view

    def test_reconcile(self, ledger):
        view = self.decided(ledger)
        assert ledger.run("reconcile")[0] == 0
        assert ledger.view() == view

    def test_an_unrelated_file(self, ledger):
        self.decided(ledger)
        ledger.card("other.csv", OTHER)
        assert ledger.count() == 3
        assert ledger.items() == []

    def test_a_rules_change(self, ledger):
        view = self.decided(ledger)
        rules = replace(DEFAULT_RULES, date_window_days=5)
        conn = ledger.conn()
        (account,) = conn.execute("SELECT id FROM account").fetchone()
        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, account, rules)
        conn.execute("COMMIT")
        conn.close()
        assert ledger.view() == view


class TestConflicts:
    def withheld(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        out = ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        return decision, out

    def test_a_third_document_gives_three_transactions_and_a_conflict(self, ledger):  # S8
        self.withheld(ledger)
        assert ledger.count() == 3
        assert len(ledger.items("decision_conflict")) == 1
        assert ledger.items("possible_duplicate") == []

    def test_it_is_counted_apart_from_possible_duplicates(self, ledger):  # S9
        decision, out = self.withheld(ledger)
        ledger.card("d.csv", "04/10/2026,SYNTHETIC BOOKS,9.00,")
        out = ledger.card("e.csv", "04/10/2026,SYNTHETIC BOOKS,9.00,")
        assert "Open review groups: 1, covering 2 distinct affected transactions." in out
        assert "Decision conflicts: 1, covering 3 distinct affected transactions" in out

        totals = ledger.totals()
        assert "1 possible-duplicate groups cover 2 distinct transactions" in totals
        assert "- Decision conflicts: 1, covering 3 distinct affected transactions" in totals

        listing = ledger.run("review", "list")[1]
        assert "Open review items: 2" in listing
        assert "Of which decision conflicts, which are not possible duplicates: 1" in listing

    def test_counts_never_claim_to_be_disjoint(self, ledger):  # S20
        self.withheld(ledger)
        assert "One transaction can appear in several of these counts." in ledger.totals()

    def test_a_transaction_can_be_in_both_a_conflict_and_a_candidate(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.reject_ok(item, (one, two))
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        ledger.card("d.csv", CAFE)
        totals = ledger.totals()
        assert "1 possible-duplicate groups cover 4 distinct transactions" in totals
        assert "Decision conflicts: 1, covering 3 distinct affected transactions" in totals

    def test_nothing_is_said_while_there_are_no_conflicts(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.reject_ok(item, (one, two))
        assert "conflict" not in ledger.totals().lower()

    def test_the_item_explains_the_withheld_match_only(self, ledger):  # S20
        self.withheld(ledger)
        (conflict,) = ledger.items("decision_conflict")
        out = ledger.show(conflict)
        assert "Kind: decision_conflict" in out
        assert f"{REASON_WITHHELD}: {cli.REASON_EXPLANATIONS[REASON_WITHHELD]}" in out
        assert "decision_basis_changed" not in out
        assert CONFLICT_NOTICE in out
        assert "Already decided, as different events:" in out
        assert "no exact adjustment" not in out

    def test_a_split_of_a_bound_transaction_changes_the_basis_only(self, ledger):  # S12, S20
        ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
        ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        ledger.card("x.csv", "01/10/2026,SYNTHETIC CAFE,5.00,")
        (item,) = ledger.items()
        decision = ledger.reject_ok(item, ledger.direct_pairs(item)[0])
        assert ledger.count() == 2

        ledger.checking("c.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")

        assert ledger.count() == 4
        (conflict,) = ledger.items("decision_conflict")
        out = ledger.show(conflict)
        assert "decision_basis_changed: " in out
        assert "automatic_match_withheld" not in out
        assert "withheld" not in out
        assert "Transactions in conflicts where a decision's basis changed: 2." in ledger.totals()
        assert "automatic match was withheld" not in ledger.totals()
        assert decision in out

    def test_both_reasons_are_explained(self, ledger):  # S19, S20
        conflict_on_a_merge(ledger)
        ledger.card("e.csv", CAFE, extra=WHOLE_MONTH)
        (conflict,) = ledger.items("decision_conflict")
        out = ledger.show(conflict)
        assert f"automatic_match_withheld: {cli.REASON_EXPLANATIONS['automatic_match_withheld']}" in out
        assert f"decision_basis_changed: {cli.REASON_EXPLANATIONS['decision_basis_changed']}" in out
        totals = ledger.totals()
        assert "where an automatic match was withheld: 4" in totals
        assert "where a decision's basis changed: 4" in totals

    def test_later_evidence_can_split_an_existing_merge_and_says_so(self, ledger):  # S19
        decision = conflict_on_a_merge(ledger)
        assert "Net account movement: -13.00" in ledger.totals()
        source = ledger.dump(SOURCE_TABLES)
        links = ledger.dump(("transaction_link_history",))["transaction_link_history"]

        out = ledger.card("e.csv", CAFE, extra=WHOLE_MONTH)

        assert ledger.count() == 4
        totals = ledger.totals()
        assert "Net account movement: -26.00" in totals
        assert "which can raise the transaction count and account movements" in totals
        assert "which can raise the transaction count and account movements" in out
        after = ledger.dump(SOURCE_TABLES)
        for table in SOURCE_TABLES:
            assert set(source[table]) <= set(after[table])
        history = ledger.dump(("transaction_link_history",))["transaction_link_history"]
        assert set(links) <= set(history)
        conn = ledger.conn()
        assert conn.execute(
            """SELECT action, reason, decision_id FROM transaction_link_history
               WHERE reason = 'automatic_match_withheld'"""
        ).fetchall() == [("split", "automatic_match_withheld", decision)]
        conn.close()

    def test_a_reconcile_prints_conflicts_too(self, ledger):
        self.withheld(ledger)
        assert "Decision conflicts: 1" in ledger.run("reconcile")[1]

    def test_a_new_lookalike_is_an_ordinary_candidate(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.reject_ok(item, (one, two))
        ledger.card("c.csv", CAFE)
        assert ledger.items("decision_conflict") == []
        assert len(ledger.items("cross_document_candidates")) == 1


class TestOverlappingItems:  # S10
    def test_a_decision_in_one_item_applies_in_the_other(self, ledger):
        days = range(1, 31, 3)
        ledger.card("a.csv", *[f"01/{day:02d}/2026,SYNTHETIC CAFE,6.50," for day in days[::2]])
        ledger.card("b.csv", *[f"01/{day:02d}/2026,SYNTHETIC CAFE,6.50," for day in days[1::2]])
        items = ledger.items()
        members = {item: set(ledger.transactions(item)) for item in items}
        first, second = next(
            (one, other) for one in items for other in items
            if one != other and members[one] & members[other]
        )
        shared = next(iter(members[first] & members[second]))
        pair = next(pair for pair in ledger.direct_pairs(first) if shared in pair)
        other_token = ledger.revision(second)

        ledger.reject_ok(first, pair)

        if second in ledger.items():
            assert ledger.revision(second) != other_token
            assert "Already decided, as different events:" in ledger.show(second)
        for item in ledger.items():
            assert frozenset(pair) not in {
                frozenset(found) for found in ledger.direct_pairs(item)
            }


class TestReExport:  # S11
    def test_the_decision_does_not_transfer_to_a_new_record(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.reject_ok(item, (one, two))

        ledger.card("again.csv", CAFE)

        (again,) = ledger.items("cross_document_candidates")
        members = ledger.transactions(again)
        assert len(members) == 3
        (new,) = set(members) - {one, two}
        assert {frozenset(pair) for pair in ledger.direct_pairs(again)} == {
            frozenset((one, new)), frozenset((two, new))
        }
        assert len(ledger.dump()["decision_constraint"]) == 1


class TestRejectionMustNotMoveAnything:  # S19
    def test_a_rejection_that_reports_moves_rolls_back(self, ledger, monkeypatch):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        before = ledger.dump()
        real = decisions_module.reconcile_account

        def moving(*args, **kwargs):
            return replace(real(*args, **kwargs), moved_records=1)

        monkeypatch.setattr(decisions_module, "reconcile_account", moving)
        code, _, err = ledger.reject(item, (one, two), revision=token)
        assert code == 2 and WOULD_CHANGE_LEDGER in err
        assert "later workflow" in err
        assert ledger.dump() == before

    @pytest.mark.parametrize(
        "statement",
        [
            "UPDATE ledger_transaction SET amount_cents = amount_cents - 1",
            "DELETE FROM review_issue_subject WHERE 0",
        ],
        ids=["totals change", "control"],
    )
    def test_a_rejection_that_changes_totals_rolls_back(self, ledger, monkeypatch, statement):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        before = ledger.dump()
        real = decisions_module.reconcile_account

        def changing(conn, *args, **kwargs):
            result = real(conn, *args, **kwargs)
            conn.execute(statement)
            return result

        monkeypatch.setattr(decisions_module, "reconcile_account", changing)
        code = ledger.reject(item, (one, two), revision=token)[0]
        if "UPDATE" in statement:
            assert code == 2
            assert ledger.dump() == before
        else:
            assert code == 0


class TestUndo:
    def test_totals_follow_current_evidence_not_a_snapshot(self, ledger):
        item, one, two = pair_up(ledger)
        assert "Net account movement: -13.00" in ledger.totals()
        decision = ledger.reject_ok(item, (one, two))
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        assert "Net account movement: -19.50" in ledger.totals()

        code, out, _ = ledger.undo(decision)

        assert code == 0
        assert "Net account movement: -6.50" in ledger.totals()
        assert "Transactions: 3 before, 1 now." in out
        assert UNDO_NOTICE in out
        assert ledger.items() == []

    def test_show_previews_the_effect(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        out = ledger.run("review", "decision", "show", decision)[1]
        assert "Transactions: 3 now, 1 after" in out

    def test_equals_a_ledger_built_without_the_decision(self, tmp_path, capsys):  # S13
        ledger = Ledger(tmp_path, capsys)
        other = Ledger(tmp_path, capsys, "other.db")
        a = ledger.write("a.csv", CARD_HEADER, [CAFE])
        b = ledger.write("b.csv", CARD_HEADER, [CAFE])
        for target in (ledger, other):
            target.load_path(a, *FIRST_HALF)
            target.load_path(b, *SECOND_HALF)

        (item,) = ledger.items()
        decision = ledger.reject_ok(item, tuple(ledger.transactions(item)))
        assert ledger.undo(decision)[0] == 0
        assert ledger.view() == other.view()

    def test_equals_a_ledger_built_without_it_after_imports_since(self, tmp_path, capsys):  # S13
        ledger = Ledger(tmp_path, capsys)
        other = Ledger(tmp_path, capsys, "other.db")
        a = ledger.write("a.csv", CARD_HEADER, [CAFE])
        b = ledger.write("b.csv", CARD_HEADER, [CAFE])
        c = ledger.write("c.csv", CARD_HEADER, [CAFE, OTHER])
        d = ledger.write("d.csv", CARD_HEADER, [CAFE])
        for target in (ledger, other):
            target.load_path(a, *FIRST_HALF)
            target.load_path(b, *SECOND_HALF)
        (item,) = ledger.items()
        decision = ledger.reject_ok(item, tuple(ledger.transactions(item)))
        for target in (ledger, other):
            target.load_path(c, *declared("2026-01-01", "2026-03-31"))
            target.load_path(d)

        assert ledger.undo(decision)[0] == 0
        assert ledger.view() == other.view()

    def test_another_decision_keeps_applying(self, ledger):
        item, one, two, three = three_of_them(ledger)
        first = ledger.reject_ok(item, (one, two))
        ledger.reject_ok(item, (one, three))
        assert ledger.undo(first)[0] == 0
        assert {frozenset(pair) for pair in ledger.direct_pairs(item)} == {
            frozenset((one, two)), frozenset((two, three))
        }

    def test_undoing_twice_is_refused(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        token = ledger.decision_revision(decision)
        assert ledger.undo(decision, token)[0] == 0
        before = ledger.dump()
        code, _, err = ledger.undo(decision, token)
        assert code == 2 and DECISION_NOT_ACTIVE in err
        assert ledger.dump() == before

    def test_wrong_account_is_refused(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        ledger.add_account("B")
        token = ledger.decision_revision(decision)
        before = ledger.dump()
        code, _, err = ledger.undo(decision, token, account="B")
        assert code == 2 and DECISION_WRONG_ACCOUNT in err
        assert ledger.dump() == before

    def test_another_decisions_token_is_refused(self, ledger):
        item, one, two, three = three_of_them(ledger)
        first = ledger.reject_ok(item, (one, two))
        second = ledger.reject_ok(item, (one, three))
        before = ledger.dump()
        code, _, err = ledger.undo(first, ledger.decision_revision(second))
        assert code == 2 and STALE_DECISION_REVISION in err
        assert ledger.dump() == before

    def test_an_unknown_decision_is_refused(self, ledger):
        pair_up(ledger)
        code, _, err = ledger.run("review", "undo", "nope", "--account", "A", "--revision", "d1-0")
        assert code == 2 and "decision not found" in err
        assert ledger.run("review", "decision", "show", "nope")[0] == 2


class TestUndoToken:  # S21
    def decided(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        return decision, ledger.decision_revision(decision)

    def test_evidence_that_changes_the_regrouping_makes_undo_refuse(self, ledger):
        decision, token = self.decided(ledger)
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        before = ledger.dump()
        code, _, err = ledger.undo(decision, token)
        assert code == 2 and STALE_DECISION_REVISION in err
        assert ledger.dump() == before
        assert ledger.undo(decision)[0] == 0

    def test_a_lookalike_that_joins_the_review_changes_the_token(self, ledger):
        decision, token = self.decided(ledger)
        ledger.card("c.csv", CAFE)
        assert ledger.decision_revision(decision) != token

    def test_another_decision_touching_the_records_changes_the_token(self, ledger):
        item, one, two, three = three_of_them(ledger)
        decision = ledger.reject_ok(item, (one, two))
        token = ledger.decision_revision(decision)
        ledger.reject_ok(item, (one, three))
        assert ledger.decision_revision(decision) != token

    def test_a_decision_with_no_effect_on_grouping_still_changes_the_token(self, ledger):
        decision, token = self.decided(ledger)
        ledger.card("other.csv", OTHER)
        conn = ledger.conn()
        (left,) = conn.execute(
            "SELECT left_record_id FROM decision_constraint WHERE decision_id = ?", (decision,)
        ).fetchone()
        (right,) = conn.execute(
            """SELECT link.source_record_id FROM transaction_source link
               JOIN ledger_transaction entry ON entry.id = link.transaction_id
               WHERE entry.description = 'SYNTHETIC GROCER'"""
        ).fetchone()
        (account,) = conn.execute("SELECT id FROM account").fetchone()
        conn.execute(
            """INSERT INTO decision (id, account_id, target_id, target_revision)
               VALUES ('other', ?, 'issue', 'r2-0')""",
            (account,),
        )
        conn.execute(
            """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                   left_transaction_id, right_transaction_id, left_record_id, right_record_id)
               VALUES ('other', 'different_event', 1, 't1', 't2', ?, ?)""",
            (left, right),
        )
        conn.close()
        assert ledger.decision_revision(decision) != token

    def test_an_item_regrouped_away_from_the_bound_records_counts(self, ledger, monkeypatch):
        """Calendar blocks let undo change an item holding no bound record (D-031). That is
        hard to reach from files, so the derivation is given such an item directly."""
        decision, _ = self.decided(ledger)
        ledger.card("x.csv", OTHER)
        ledger.card("y.csv", OTHER)
        conn = ledger.conn()
        decided = load_decision(conn, decision)
        far = [row[0] for row in conn.execute(
            """SELECT link.source_record_id FROM transaction_source link
               JOIN ledger_transaction entry ON entry.id = link.transaction_id
               WHERE entry.description = 'SYNTHETIC GROCER'"""
        )]
        real = decision_evidence.derive
        extra = ReviewItem(RULE_CANDIDATES, tuple((record,) for record in far), ("regrouped",),
                           "2026-03-20", "2026-03-20")

        def regrouping(documents, records, unresolved, rules, constraints):
            result = real(documents, records, unresolved, rules, constraints)
            if any(item.decision_id == decision for item in constraints):
                return result
            return replace(result, items=(*result.items, extra))

        plain = undo_outlook(conn, decided, DEFAULT_RULES).revision
        monkeypatch.setattr(decision_evidence, "derive", regrouping)
        assert undo_outlook(conn, decided, DEFAULT_RULES).revision != plain
        conn.close()

    def test_an_unrelated_file_does_not(self, ledger):
        decision, token = self.decided(ledger)
        ledger.card("other.csv", OTHER)
        assert ledger.decision_revision(decision) == token
        assert ledger.undo(decision, token)[0] == 0

    def test_a_repeat_import_and_a_reconcile_do_not(self, ledger):
        decision, token = self.decided(ledger)
        ledger.load_path(ledger.folder / "a.csv", *FIRST_HALF)
        ledger.run("reconcile")
        assert ledger.decision_revision(decision) == token

    def test_a_rules_change_does(self, ledger):
        decision, token = self.decided(ledger)
        rules = replace(DEFAULT_RULES, date_window_days=5)
        conn = ledger.conn()
        (account,) = conn.execute("SELECT id FROM account").fetchone()
        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, account, rules)
        conn.execute("COMMIT")
        changed = undo_outlook(conn, load_decision(conn, decision), rules).revision
        conn.close()
        assert changed != token

    def test_equal_evidence_gives_an_equal_token_in_another_ledger(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        other = Ledger(tmp_path, capsys, "other.db")
        a = ledger.write("a.csv", CARD_HEADER, [CAFE])
        b = ledger.write("b.csv", CARD_HEADER, [CAFE])
        ledger.load_path(a, *FIRST_HALF)
        ledger.load_path(b, *SECOND_HALF)
        other.load_path(b, *SECOND_HALF)
        other.load_path(a, *FIRST_HALF)
        tokens = []
        for target in (ledger, other):
            (item,) = target.items()
            decision = target.reject_ok(item, tuple(target.transactions(item)))
            tokens.append(target.decision_revision(decision))
        assert tokens[0] == tokens[1]

    def test_the_token_has_the_documented_form(self, ledger):
        _, token = self.decided(ledger)
        assert re.fullmatch(r"d6-[0-9a-f]{16}", token)


class TestConstraintsApplied:
    def insert(self, ledger, relation):
        conn = ledger.conn()
        left, right = [row[0] for row in conn.execute("SELECT id FROM source_record")]
        (account,) = conn.execute("SELECT id FROM account WHERE display_name = 'A'").fetchone()
        conn.execute(
            """INSERT INTO decision (id, account_id, target_id, target_revision)
               VALUES ('d', ?, 'issue', 'r2-0')""",
            (account,),
        )
        conn.execute(
            """INSERT INTO decision_constraint (decision_id, relation, pair_number,
                   left_transaction_id, right_transaction_id, left_record_id, right_record_id)
               VALUES ('d', ?, 1, 't1', 't2', ?, ?)""",
            (relation, left, right),
        )
        return conn, account

    def test_same_event_is_never_read_as_a_rejection(self, ledger):
        pair_up(ledger)
        conn, account = self.insert(ledger, "same_event")
        (constraint,) = load_constraints(conn, account)
        assert constraint.relation == "same_event"
        conn.close()

    def test_a_different_event_row_is_read(self, ledger):
        pair_up(ledger)
        conn, account = self.insert(ledger, "different_event")
        (constraint,) = load_constraints(conn, account)
        assert constraint.relation == "different_event" and not constraint.confirmation
        conn.close()

    def test_another_accounts_decisions_are_not_read(self, ledger):
        pair_up(ledger)
        ledger.add_account("B")
        conn, _ = self.insert(ledger, "different_event")
        (other,) = conn.execute("SELECT id FROM account WHERE display_name = 'B'").fetchone()
        assert load_constraints(conn, other) == ()
        conn.close()


class TestHistory:  # S14
    def test_a_decision_stays_on_record_after_undo(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        rows = ledger.dump()
        assert ledger.undo(decision)[0] == 0
        after = ledger.dump()
        assert after["decision"] == rows["decision"]
        assert after["decision_constraint"] == rows["decision_constraint"]
        assert [row[2] for row in after["decision_event"]] == ["made", "undone"]

        out = ledger.run("review", "decisions")[1]
        assert f"Decision {decision}: undone" in out
        out = ledger.run("review", "decision", "show", decision)[1]
        assert "Status: undone" in out and "no longer applies" in out
        assert "Revision" not in out

    def test_moves_caused_by_undo_name_the_decision(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        assert ledger.undo(decision)[0] == 0
        conn = ledger.conn()
        moves = conn.execute(
            "SELECT DISTINCT action, decision_id FROM transaction_link_history"
        ).fetchall()
        conn.close()
        assert moves == [("merged", decision)]

    def test_trace_names_the_decision(self, ledger):
        decision = conflict_on_a_merge(ledger)
        ledger.card("e.csv", CAFE, extra=WHOLE_MONTH)
        conn = ledger.conn()
        (source,) = conn.execute(
            "SELECT from_transaction_id FROM transaction_link_history "
            "WHERE reason = 'automatic_match_withheld'"
        ).fetchone()
        conn.close()
        assert f"decision {decision}" in ledger.run("trace", source)[1]

    def test_retired_ids_revive_with_their_created_at(self, ledger):
        decision = conflict_on_a_merge(ledger)
        conn = ledger.conn()
        (retired, created_at), = conn.execute(
            "SELECT transaction_id, transaction_created_at FROM transaction_identity_history "
            "WHERE event = 'retired'"
        ).fetchall()
        conn.close()

        ledger.card("e.csv", CAFE, extra=WHOLE_MONTH)

        conn = ledger.conn()
        assert conn.execute(
            "SELECT created_at FROM ledger_transaction WHERE id = ?", (retired,)
        ).fetchone() == (created_at,)
        assert conn.execute(
            "SELECT transaction_created_at FROM transaction_identity_history "
            "WHERE transaction_id = ? AND event = 'revived'",
            (retired,),
        ).fetchone() == (created_at,)
        conn.close()

        assert ledger.undo(decision)[0] == 0
        conn = ledger.conn()
        assert conn.execute(
            "SELECT COUNT(*) FROM transaction_identity_history WHERE transaction_id = ?", (retired,)
        ).fetchone()[0] == 3
        conn.close()


class TestPrivacy:  # S17
    AMOUNT = "6.50"
    TEXT = "SYNTHETIC CAFE"

    def assert_clean(self, *texts):
        for text in texts:
            assert self.AMOUNT not in text
            assert self.TEXT not in text

    def test_reject_undo_and_decisions_show_no_financial_data(self, ledger):
        item, one, two = pair_up(ledger)
        code, out, err = ledger.reject(item, (one, two))
        assert code == 0
        self.assert_clean(out, err)
        decision = re.search(r"Decision (\S+) recorded", out)[1]

        code, out, err = ledger.run("review", "decisions")
        assert code == 0
        self.assert_clean(out, err)

        code, out, err = ledger.undo(decision)
        assert code == 0
        self.assert_clean(out, err)

    def test_refusals_show_no_financial_data(self, ledger):
        item, one, two = pair_up(ledger)
        for result in (
            ledger.reject(item, (one, one)),
            ledger.reject(item, (one, "other")),
            ledger.reject(item, (one, two), revision="r2-0"),
            ledger.reject("nope", (one, two), revision="r2-0"),
        ):
            assert result[0] == 2
            self.assert_clean(*result[1:])

    def test_decision_show_presents_no_amounts_or_descriptions_either(self, ledger):
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        self.assert_clean(ledger.run("review", "decision", "show", decision)[1])

    def test_an_unexpected_error_shows_no_details(self, ledger, monkeypatch):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)

        def broken(*args, **kwargs):
            raise RuntimeError(f"{self.TEXT} {self.AMOUNT}")

        monkeypatch.setattr(decisions_module, "reconcile_account", broken)
        before = ledger.dump()
        code, out, err = ledger.reject(item, (one, two), revision=token)
        assert code == 2
        self.assert_clean(out, err)
        assert ledger.dump() == before

    def test_a_file_name_cannot_imitate_output_in_decided_sections(self, ledger):
        ledger.card("a\nDecision forged.csv", CAFE, extra=FIRST_HALF)
        ledger.card("b.csv", CAFE, extra=SECOND_HALF)
        ledger.card("c.csv", CAFE)
        (item,) = ledger.items()
        conn = ledger.conn()
        (forged,) = conn.execute(
            """SELECT link.transaction_id FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id
               WHERE document.file_name LIKE 'a%'"""
        ).fetchone()
        conn.close()
        pair = next(pair for pair in ledger.direct_pairs(item) if forged in pair)
        decision = ledger.reject_ok(item, pair)
        decided = ledger.show(item).split("Already decided")[1].split("Direct candidate")[0]
        for text in (decided, ledger.run("review", "decision", "show", decision)[1]):
            assert "\nDecision forged" not in text
            assert "a\\nDecision forged.csv" in text


class TestRollback:
    def test_a_failure_while_applying_leaves_no_decision(self, ledger, monkeypatch):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        before = ledger.dump()
        monkeypatch.setattr(
            decisions_module, "reconcile_account",
            lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("locked")),
        )
        assert ledger.reject(item, (one, two), revision=token)[0] == 2
        assert ledger.dump() == before

    def test_a_busy_ledger_changes_nothing(self, ledger):
        item, one, two = pair_up(ledger)
        token = ledger.revision(item)
        before = ledger.dump()
        blocker = sqlite3.connect(ledger.path, timeout=0, isolation_level=None)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            code, _, err = ledger.reject(item, (one, two), revision=token)
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()
        assert code == 2 and "busy" in err
        assert ledger.dump() == before
