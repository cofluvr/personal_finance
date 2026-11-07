"""Separating machine-made merges, end to end, using synthetic data only (D-047)."""

import re
from dataclasses import replace

import pytest
from test_confirmations import confirm_ok, relations
from test_decisions import (
    CAFE,
    CARD_HEADER,
    FIRST_HALF,
    OTHER,
    SECOND_HALF,
    SOURCE_TABLES,
    WHOLE_MONTH,
    Ledger,
    pair_up,
)

from personal_finance.cli import ID_OVERRIDE_NOTICE, SEPARATE_NOTICE
from personal_finance.reconcile import decisions as decisions_module
from personal_finance.reconcile.apply import reconcile_account
from personal_finance.reconcile.decisions import (
    IN_CONFLICT,
    NOTHING_AUTOMATIC,
    ONE_GROUP,
    ONE_RECORD,
    RECORD_OUTSIDE,
    RECORD_REPEATED,
    RECORD_UNNAMED,
    SPLITS_CONFIRMED,
    STALE_ACCOUNT,
    STALE_TRANSACTION_REVISION,
    TOO_MANY_RECORDS,
    TRANSACTION_NOT_FOUND,
    TRANSACTION_WRONG_ACCOUNT,
    WOULD_SPLIT_MORE,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports import review_evidence

ID_ROW = "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED"


class SeparationLedger(Ledger):
    def merges(self):
        out = self.run("review", "merges")[1]
        return re.findall(r"^Transaction (\S+): \d+ records", out, re.MULTILINE)

    def merge_show(self, transaction):
        code, out, _ = self.run("review", "merge", "show", transaction)
        assert code == 0
        return out

    def merge_revision(self, transaction):
        return re.search(r"Revision: (t1-[0-9a-f]{16})", self.merge_show(transaction))[1]

    def records(self, transaction):
        """Record IDs by file name, read from the evidence and never from ID order."""
        found = re.findall(
            r"^  Source (\S+), row \d+\n    Record: (\S+)$", self.merge_show(transaction),
            re.MULTILINE,
        )
        return dict(found)

    def separate(self, transaction, *groups, revision=None, account="A"):
        words = ["review", "separate", transaction, "--account", account,
                 "--revision", revision or self.merge_revision(transaction)]
        for group in groups:
            words += ["--group", *group]
        return self.run(*words)

    def separate_ok(self, transaction, *groups, **options):
        code, out, err = self.separate(transaction, *groups, **options)
        assert code == 0, err
        return re.search(r"Decision (\S+) recorded", out)[1]

    def link_rules(self):
        """Link rule by file name."""
        conn = self.conn()
        found = dict(conn.execute(
            """SELECT document.file_name, link.link_rule FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ))
        conn.close()
        return found

    def together(self):
        """File names grouped by transaction, in no particular order."""
        conn = self.conn()
        found = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            found.setdefault(transaction_id, set()).add(name)
        conn.close()
        return sorted(sorted(names) for names in found.values())


@pytest.fixture
def ledger(tmp_path, capsys):
    return SeparationLedger(tmp_path, capsys)


def merged_two(ledger):
    """a and b merged by an exact coverage pair."""
    ledger.card("a.csv", CAFE, extra=FIRST_HALF)
    ledger.card("b.csv", CAFE, extra=FIRST_HALF)
    (transaction,) = ledger.merges()
    return transaction, ledger.records(transaction)


def merged_three(ledger):
    for name in ("a.csv", "b.csv", "c.csv"):
        ledger.card(name, CAFE, extra=WHOLE_MONTH)
    (transaction,) = ledger.merges()
    return transaction, ledger.records(transaction)


def merged_by_id(ledger):
    ledger.checking("a.csv", ID_ROW)
    ledger.checking("b.csv", ID_ROW)
    (transaction,) = ledger.merges()
    return transaction, ledger.records(transaction)


def absorbed(ledger):
    """a and b confirmed as one event, then c joined to them automatically."""
    item, one, two = pair_up(ledger)
    confirm_ok(ledger, item, (one, two))
    ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
    (transaction,) = ledger.merges()
    return transaction, ledger.records(transaction)


def movement(ledger):
    return ledger.totals().splitlines()[:4]


class TestSeparate:
    def test_an_exact_merge_into_single_records(self, ledger):  # P1
        transaction, records = merged_two(ledger)
        assert ledger.count() == 1
        assert "Net account movement: -6.50" in ledger.totals()
        before = ledger.dump()

        code, out, _ = ledger.separate(transaction, [records["a.csv"]], [records["b.csv"]])

        assert code == 0
        assert "2 groups separated" in out
        assert "Transactions: 1 before, 2 now." in out
        assert SEPARATE_NOTICE in out
        assert "overrides that match" not in out
        assert ledger.count() == 2
        assert "Net account movement: -13.00" in ledger.totals()
        after = ledger.dump()
        for table in SOURCE_TABLES:
            assert after[table] == before[table], table
        assert relations(ledger) == {"different_event": 1}
        assert ledger.merges() == []

    def test_no_item_and_no_conflict_is_raised(self, ledger):  # P8
        transaction, records = merged_two(ledger)
        ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        assert ledger.items() == []
        assert "conflict" not in ledger.totals()

    def test_a_reliable_id_merge(self, ledger):  # P2
        transaction, records = merged_by_id(ledger)
        assert ledger.link_rules() == {"a.csv": "reliable_external_id", "b.csv": "reliable_external_id"}
        code, out, _ = ledger.separate(transaction, [records["a.csv"]], [records["b.csv"]])
        assert code == 0
        assert ID_OVERRIDE_NOTICE.format(guarantee="stable_unique") in out
        assert ledger.count() == 2
        assert ledger.items() == []

    def test_three_documents_keeping_two_together(self, ledger):  # P3
        transaction, records = merged_three(ledger)
        assert ledger.count() == 1
        ledger.separate_ok(transaction, [records["a.csv"], records["b.csv"]], [records["c.csv"]])
        assert ledger.together() == [["a.csv", "b.csv"], ["c.csv"]]
        assert relations(ledger) == {"same_event": 1, "different_event": 2}
        assert ledger.link_rules() == {
            "a.csv": "confirmed_same_event", "b.csv": "confirmed_same_event", "c.csv": "new_record"
        }
        assert ledger.items() == []
        totals = ledger.totals()
        assert "- 1 transactions hold records you confirmed as one event" in totals
        assert "- 2 transactions hold records you separated from an automatic match" in totals

    def test_the_groups_are_stored_as_parts_of_one_transaction(self, ledger):
        transaction, records = merged_three(ledger)
        ledger.separate_ok(transaction, [records["c.csv"]], [records["a.csv"], records["b.csv"]])
        conn = ledger.conn()
        rows = conn.execute(
            """SELECT relation, left_transaction_id, right_transaction_id, left_record_id,
                      right_record_id, left_part, right_part
               FROM decision_constraint"""
        ).fetchall()
        target = conn.execute("SELECT target_kind, target_id, kind FROM decision").fetchall()
        conn.close()
        assert target == [("transaction", transaction, "confirm")]
        part = {records["c.csv"]: 1, records["a.csv"]: 2, records["b.csv"]: 2}
        for relation, left_transaction, right_transaction, left, right, left_part, right_part in rows:
            assert left_transaction == right_transaction == transaction
            assert (left_part, right_part) == (part[left], part[right])
            assert relation == ("same_event" if left_part == right_part else "different_event")
        assert len(rows) == 3

    def test_an_absorbed_record_can_be_separated_from_a_confirmed_core(self, ledger):
        transaction, records = absorbed(ledger)
        assert ledger.count() == 1
        assert set(ledger.link_rules().values()) == {"confirmed_same_event"}
        ledger.separate_ok(transaction, [records["a.csv"], records["b.csv"]], [records["c.csv"]])
        assert ledger.together() == [["a.csv", "b.csv"], ["c.csv"]]
        assert ledger.items() == []

    def test_moves_and_trace_name_the_separation(self, ledger):  # P22
        transaction, records = merged_two(ledger)
        decision = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        conn = ledger.conn()
        moves = conn.execute(
            """SELECT action, reason, decision_id FROM transaction_link_history
               WHERE decision_id IS NOT NULL"""
        ).fetchall()
        conn.close()
        assert moves == [("split", "automatic_match_withheld", decision)]
        traces = "".join(ledger.run("trace", other)[1] for other in ledger_ids(ledger))
        assert f"automatic_match_withheld, decision {decision}" in traces

    def test_one_group_keeps_the_id_and_the_other_revives(self, ledger):  # P13
        transaction, records = merged_two(ledger)
        conn = ledger.conn()
        origin = dict(conn.execute(
            "SELECT source_record_id, original_transaction_id FROM source_record_origin"
        ))
        conn.close()
        ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        conn = ledger.conn()
        holders = dict(conn.execute("SELECT source_record_id, transaction_id FROM transaction_source"))
        revived = conn.execute(
            """SELECT history.transaction_id, history.transaction_created_at, entry.created_at
               FROM transaction_identity_history history
               JOIN ledger_transaction entry ON entry.id = history.transaction_id
               WHERE history.event = 'revived'"""
        ).fetchall()
        conn.close()
        assert holders[records["a.csv"]] == transaction
        assert holders[records["b.csv"]] == origin[records["b.csv"]] != transaction
        assert len(revived) == 1
        (revived_id, kept_created, created) = revived[0]
        assert revived_id == origin[records["b.csv"]] and kept_created == created


def ledger_ids(ledger):
    conn = ledger.conn()
    found = [row[0] for row in conn.execute("SELECT id FROM ledger_transaction")]
    conn.close()
    return found


class TestRefusals:  # P4
    def refused(self, ledger, message, transaction, *groups, **options):
        before = ledger.dump()
        code, out, err = ledger.separate(transaction, *groups, **options)
        assert code == 2, out
        assert message in err
        assert ledger.dump() == before

    def test_wrong_account(self, ledger):
        transaction, records = merged_two(ledger)
        ledger.add_account("B")
        self.refused(ledger, TRANSACTION_WRONG_ACCOUNT, transaction, [records["a.csv"]],
                     [records["b.csv"]], account="B")

    def test_unknown_transaction(self, ledger):
        _, records = merged_two(ledger)
        self.refused(ledger, TRANSACTION_NOT_FOUND, "no-such-transaction", [records["a.csv"]],
                     [records["b.csv"]], revision="t1-0000000000000000")

    def test_a_stale_token(self, ledger):
        transaction, records = merged_two(ledger)
        self.refused(ledger, STALE_TRANSACTION_REVISION, transaction, [records["a.csv"]],
                     [records["b.csv"]], revision="t1-0000000000000000")

    def test_a_token_from_before_new_evidence(self, ledger):
        ledger.card("a.csv", CAFE, extra=WHOLE_MONTH)
        ledger.card("b.csv", CAFE, extra=WHOLE_MONTH)
        (transaction,) = ledger.merges()
        token = ledger.merge_revision(transaction)
        records = ledger.records(transaction)
        ledger.card("c.csv", CAFE, extra=WHOLE_MONTH)
        assert ledger.merges() == [transaction]
        assert ledger.merge_revision(transaction) != token
        self.refused(ledger, STALE_TRANSACTION_REVISION, transaction,
                     [records["a.csv"]], [records["b.csv"]], revision=token)

    def test_a_record_left_unnamed(self, ledger):
        transaction, records = merged_three(ledger)
        self.refused(ledger, RECORD_UNNAMED, transaction, [records["a.csv"]], [records["b.csv"]])

    def test_a_record_named_twice(self, ledger):
        transaction, records = merged_two(ledger)
        self.refused(ledger, RECORD_REPEATED, transaction, [records["a.csv"]],
                     [records["b.csv"], records["a.csv"]])

    def test_a_record_from_another_transaction(self, ledger):
        transaction, records = merged_two(ledger)
        ledger.card("x.csv", OTHER)
        conn = ledger.conn()
        (other,) = conn.execute(
            """SELECT link.source_record_id FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id
               WHERE document.file_name = 'x.csv'"""
        ).fetchone()
        conn.close()
        self.refused(ledger, RECORD_OUTSIDE, transaction, [records["a.csv"]],
                     [records["b.csv"], other])

    def test_a_single_group(self, ledger):
        transaction, records = merged_two(ledger)
        self.refused(ledger, ONE_GROUP, transaction, [records["a.csv"], records["b.csv"]])

    def test_a_transaction_of_one_record(self, ledger):
        ledger.card("a.csv", CAFE)
        (transaction,) = ledger_ids(ledger)
        (record,) = ledger.records(transaction).values()
        self.refused(ledger, ONE_RECORD, transaction, [record])

    def test_a_transaction_confirmed_as_one_event(self, ledger):
        item, one, two = pair_up(ledger)
        confirm_ok(ledger, item, (one, two))
        assert ledger.merges() == []
        (transaction,) = ledger_ids(ledger)
        records = ledger.records(transaction)
        self.refused(ledger, NOTHING_AUTOMATIC, transaction, [records["a.csv"]],
                     [records["b.csv"]])

    def test_splitting_a_confirmed_core(self, ledger):
        transaction, records = absorbed(ledger)
        conn = ledger.conn()
        (confirmation,) = conn.execute("SELECT id FROM decision").fetchone()
        conn.close()
        self.refused(ledger, SPLITS_CONFIRMED.format(decisions=confirmation), transaction,
                     [records["a.csv"]], [records["b.csv"], records["c.csv"]])

    def test_a_transaction_in_an_open_conflict(self, ledger):
        transaction, records = merged_two(ledger)
        token = ledger.merge_revision(transaction)
        conn = ledger.conn()
        conn.execute(
            """INSERT INTO review_issue (id, kind, rule, evidence_json)
               VALUES ('conflict', 'decision_conflict', 'identity_decision', '{}')"""
        )
        conn.execute(
            "INSERT INTO review_issue_subject (review_issue_id, transaction_id) VALUES (?, ?)",
            ("conflict", transaction),
        )
        conn.close()
        self.refused(ledger, IN_CONFLICT, transaction, [records["a.csv"]], [records["b.csv"]],
                     revision=token)

    def test_too_many_records(self, ledger, monkeypatch):
        transaction, records = merged_three(ledger)
        monkeypatch.setattr(decisions_module, "MAX_CONFIRMED", 2)
        self.refused(ledger, TOO_MANY_RECORDS, transaction, [records["a.csv"]],
                     [records["b.csv"]], [records["c.csv"]])

    def test_a_stale_account_is_not_reconciled(self, ledger):  # P5
        transaction, records = merged_two(ledger)
        token = ledger.merge_revision(transaction)
        conn = ledger.conn()
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?", ("0" * 64,))
        conn.close()
        self.refused(ledger, STALE_ACCOUNT, transaction, [records["a.csv"]], [records["b.csv"]],
                     revision=token)


class TestSurvival:  # P6
    def test_repeat_imports_reconcile_unrelated_files_and_a_rules_change(self, ledger):
        transaction, records = merged_three(ledger)
        ledger.separate_ok(transaction, [records["a.csv"], records["b.csv"]], [records["c.csv"]])
        expected = ledger.view()
        ledger.load_path(ledger.folder / "a.csv", *WHOLE_MONTH)
        ledger.card("x.csv", OTHER)
        assert ledger.run("reconcile")[0] == 0
        conn = ledger.conn()
        conn.execute("BEGIN IMMEDIATE")
        accounts = [row[0] for row in conn.execute("SELECT id FROM account")]
        for account in accounts:
            reconcile_account(conn, account, replace(DEFAULT_RULES, date_window_days=4))
        conn.execute("COMMIT")
        conn.close()
        assert ledger.together() == [["a.csv", "b.csv"], ["c.csv"], ["x.csv"]]
        assert ledger.items() == []
        assert expected["constraints"] == ledger.view()["constraints"]


class TestLaterEvidence:  # P7
    def test_a_re_export_that_would_rejoin_them_raises_an_open_conflict(self, ledger):
        transaction, records = merged_by_id(ledger)
        ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        ledger.checking("c.csv", ID_ROW)
        (conflict,) = ledger.items("decision_conflict")
        assert "automatic_match_withheld" in ledger.show(conflict)
        assert ledger.count() == 3
        assert ledger.together() == [["a.csv"], ["b.csv"], ["c.csv"]]


class TestLedgerGuard:  # P9
    @pytest.mark.parametrize(
        "statement",
        [
            "UPDATE transaction_source SET link_rule = link_rule WHERE 0",
            "DELETE FROM transaction_source WHERE source_document_id = "
            "(SELECT id FROM source_document WHERE file_name = 'x.csv')",
            "INSERT INTO review_issue (id, kind, rule) VALUES "
            "('injected', 'decision_conflict', 'identity_decision'); "
            "INSERT INTO review_issue_subject (review_issue_id, transaction_id) "
            "SELECT 'injected', link.transaction_id FROM transaction_source link "
            "JOIN source_document document ON document.id = link.source_document_id "
            "WHERE document.file_name = 'a.csv'",
        ],
        ids=["control", "an extra change", "a conflict on its records"],
    )
    def test_more_than_the_stated_split_rolls_back(self, ledger, monkeypatch, statement):
        transaction, records = merged_two(ledger)
        ledger.card("x.csv", OTHER)
        token = ledger.merge_revision(transaction)
        before = ledger.dump()
        real = decisions_module.reconcile_account

        def changing(conn, *args, **kwargs):
            result = real(conn, *args, **kwargs)
            conn.execute("PRAGMA foreign_keys = OFF")
            for part in statement.split("; "):
                conn.execute(part)
            return result

        monkeypatch.setattr(decisions_module, "reconcile_account", changing)
        code, _, err = ledger.separate(transaction, [records["a.csv"]], [records["b.csv"]],
                                       revision=token)
        if "WHERE 0" in statement:
            assert code == 0
        else:
            assert code == 2 and WOULD_SPLIT_MORE in err
            assert ledger.dump() == before


class TestUndo:  # P10, P11
    def test_equals_a_ledger_built_without_it(self, tmp_path, capsys):
        ledger = SeparationLedger(tmp_path, capsys)
        other = SeparationLedger(tmp_path, capsys, "other.db")
        paths = [ledger.write(name, CARD_HEADER, [CAFE]) for name in ("a.csv", "b.csv", "c.csv")]
        for target in (ledger, other):
            for path in paths:
                target.load_path(path, *WHOLE_MONTH)
        (transaction,) = ledger.merges()
        records = ledger.records(transaction)
        decision = ledger.separate_ok(
            transaction, [records["a.csv"], records["b.csv"]], [records["c.csv"]]
        )
        code, out, _ = ledger.undo(decision)
        assert code == 0 and "Transactions: 2 before, 1 now." in out
        assert ledger.view() == other.view()

    def test_equals_a_ledger_built_without_it_after_imports_since(self, tmp_path, capsys):
        ledger = SeparationLedger(tmp_path, capsys)
        other = SeparationLedger(tmp_path, capsys, "other.db")
        a = ledger.write("a.csv", CARD_HEADER, [CAFE])
        b = ledger.write("b.csv", CARD_HEADER, [CAFE])
        c = ledger.write("c.csv", CARD_HEADER, [CAFE, OTHER])
        for target in (ledger, other):
            target.load_path(a, *FIRST_HALF)
            target.load_path(b, *FIRST_HALF)
        (transaction,) = ledger.merges()
        records = ledger.records(transaction)
        decision = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        for target in (ledger, other):
            target.load_path(c, *WHOLE_MONTH)
        assert ledger.undo(decision)[0] == 0
        assert ledger.view() == other.view()

    def test_undo_after_a_later_confirmation_follows_the_joining_rules(self, ledger):  # P11
        transaction, records = merged_two(ledger)
        separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        ledger.card("x.csv", CAFE)
        (item,) = ledger.items()
        by_file = {}
        for member in ledger.transactions(item):
            by_file.update((name, member) for name in ledger.records(member))
        confirm_ok(ledger, item, (by_file["b.csv"], by_file["x.csv"]))
        assert ledger.together() == [["a.csv"], ["b.csv", "x.csv"]]

        assert ledger.undo(separation)[0] == 0
        # The exact pair a–b joins the confirmed unit {b, x}: one record per document, no
        # distinct IDs and nothing kept apart, so all three are one transaction (D-046).
        assert ledger.together() == [["a.csv", "b.csv", "x.csv"]]
        assert ledger.items() == []

    def test_undo_says_totals_may_change_and_the_merge_returns(self, ledger):
        transaction, records = merged_two(ledger)
        decision = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        assert "Undoing a separation can lower totals." in ledger.totals()
        assert ledger.undo(decision)[0] == 0
        assert "Net account movement: -6.50" in ledger.totals()
        assert "separated" not in ledger.totals()


class TestSuperseding:  # P12
    def test_a_confirmation_supersedes_a_separation(self, ledger):
        transaction, records = merged_three(ledger)
        separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]],
                                        [records["c.csv"]])
        assert ledger.items() == []
        ledger.card("x.csv", CAFE)
        (item,) = ledger.items()
        by_file = {}
        for member in ledger.transactions(item):
            by_file.update((name, member) for name in ledger.records(member))
        # Joining a and b contradicts pair 1 of the separation, and its other pairs must be kept.
        code, _, err = ledger.run(
            "review", "confirm", item, "--account", "A", "--revision", ledger.revision(item),
            "--group", by_file["a.csv"], by_file["b.csv"],
            "--supersedes", separation,
            "--supersedes-revision", ledger.decision_revision(separation),
        )
        assert code == 2 and "neither contradicted" in err

        # Keeping every pair it does not contradict, read by file name and never by number.
        shown = ledger.run("review", "decision", "show", separation)[1]
        pairs = {
            int(number): set(re.findall(r"^    (\S+) row", body, re.MULTILINE))
            for number, body in re.findall(
                r"^Pair (\d+) of \d+: \S+\n(.*?)(?=^Pair |^  Revision)", shown,
                re.MULTILINE | re.DOTALL,
            )
        }
        assert sorted(map(sorted, pairs.values())) == [
            ["a.csv", "b.csv"], ["a.csv", "c.csv"], ["b.csv", "c.csv"]
        ]
        keep = [number for number, names in pairs.items() if names != {"a.csv", "b.csv"}]
        decision = confirm_ok(ledger, item, (by_file["a.csv"], by_file["b.csv"]),
                              supersedes=separation, keep=keep)
        assert ledger.together() == [["a.csv", "b.csv"], ["c.csv"], ["x.csv"]]
        out = ledger.run("review", "decisions")[1]
        assert f"Decision {separation}: superseded, separate" in out

        code, out, _ = ledger.undo(decision)
        assert code == 0 and f"Decision {separation}, which it superseded, applies again." in out
        assert ledger.together() == [["a.csv"], ["b.csv"], ["c.csv"], ["x.csv"]]


class TestTotals:  # P14
    def test_the_line_counts_separated_transactions_and_names_no_amounts(self, ledger):
        transaction, records = merged_two(ledger)
        code, out, _ = ledger.separate(transaction, [records["a.csv"]], [records["b.csv"]])
        assert code == 0
        assert "6.50" not in out and "CAFE" not in out
        assert "- 2 transactions hold records you separated from an automatic match" in ledger.totals()

    def test_merges_lists_ids_and_counts_only(self, ledger):
        transaction, _ = merged_three(ledger)
        code, out, _ = ledger.run("review", "merges")
        assert code == 0
        assert f"Transaction {transaction}: 3 records, exact_coverage_pair" in out
        assert "Transactions holding records joined automatically: 1" in out
        assert "6.50" not in out and "CAFE" not in out

    def test_decisions_show_a_separation_as_such(self, ledger):
        transaction, records = merged_two(ledger)
        decision = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        assert f"Decision {decision}: active, separate, 1 pairs" in ledger.run("review", "decisions")[1]
        out = ledger.run("review", "decision", "show", decision)[1]
        assert "Kind: separate" in out
        assert f"From transaction: {transaction}" in out
        assert f"At decision time: both in {transaction}, groups 1 and 2" in out


class TestTokens:  # P15
    def test_the_version_is_pinned(self):
        assert review_evidence.TRANSACTION_REVISION_VERSION == 1
        assert review_evidence.REVISION_VERSION == 3

    def test_equal_in_any_import_order(self, tmp_path, capsys):
        tokens = []
        for number, order in enumerate((("a.csv", "b.csv", "c.csv"), ("c.csv", "a.csv", "b.csv"))):
            folder = tmp_path / str(number)
            folder.mkdir()
            ledger = SeparationLedger(folder, capsys)
            paths = {name: folder / name for name in order}
            for index, name in enumerate(sorted(paths)):
                paths[name].write_text(CARD_HEADER + " " * index + CAFE + "\n")
            for name in order:
                ledger.load_path(paths[name], *WHOLE_MONTH)
            (transaction,) = ledger.merges()
            tokens.append(ledger.merge_revision(transaction))
        assert tokens[0] == tokens[1]

    def test_unchanged_by_a_repeat_import_or_reconcile(self, ledger):
        transaction, _ = merged_two(ledger)
        token = ledger.merge_revision(transaction)
        ledger.load_path(ledger.folder / "a.csv", *FIRST_HALF)
        assert ledger.run("reconcile")[0] == 0
        ledger.card("x.csv", OTHER)
        assert ledger.merge_revision(transaction) == token

    def test_a_separation_changes_an_overlapping_items_token(self, ledger):
        transaction, records = merged_two(ledger)
        ledger.card("x.csv", CAFE)
        (item,) = ledger.items()
        token = ledger.revision(item)
        ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        (remaining,) = ledger.items()
        assert ledger.revision(remaining) != token


class TestEscaping:  # P21
    def test_merge_show_escapes_descriptions(self, ledger):
        row = '01/10/2026,"SYNTHETIC\x1b[2J CAFE\nRevision: t1-0000000000000000",6.50,'
        ledger.card("a.csv", row, extra=FIRST_HALF)
        ledger.card("b.csv", row, extra=FIRST_HALF)
        (transaction,) = ledger.merges()
        out = ledger.merge_show(transaction)
        assert "\x1b" not in out
        assert len(re.findall(r"^\s*Revision: ", out, re.MULTILINE)) == 1
        assert "CAFE\\nRevision" in out
