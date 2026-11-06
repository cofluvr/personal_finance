"""Cross-document reconciliation end to end, using only synthetic data."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from ledger_view import semantic_view

from personal_finance.cli import main
from personal_finance.db.migrate import (
    MIGRATIONS_DIR,
    connect,
    create_database,
    load_migrations,
    migrate,
    schema_version,
)
from personal_finance.ingest import pipeline
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.reconcile import apply
from personal_finance.reconcile.apply import (
    ReconcileResult,
    is_current,
    reconcile_account,
    stale_accounts,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports.totals import account_movement

REPO = Path(__file__).resolve().parents[2]
CHECKING_HEADER = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
CARD_HEADER = "Date,Description,Debit,Credit\n"
JANUARY = ("2026-01-01", "2026-01-31", "posting")

ALL_TABLES = (
    "source_document", "document_coverage", "document_interpretation", "source_record",
    "record_parse", "source_record_origin", "ledger_transaction", "transaction_source",
    "transaction_link_history", "transaction_identity_history", "review_issue",
    "review_issue_subject",
    "account_reconciliation",
)


def distinct_bytes(tmp_path, rows):
    """Lead with spaces the parser strips, so files with equal rows are not byte-identical."""
    padding = " " * len(list(tmp_path.glob("*.csv")))
    return "".join(f"{padding if position == 0 else ''}{row}\n" for position, row in enumerate(rows))


def dump(conn):
    return {
        table: sorted(map(repr, conn.execute(f"SELECT * FROM {table}").fetchall()))
        for table in ALL_TABLES
    }


@pytest.fixture
def account(conn):
    for account_id in ("acct", "other"):
        conn.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES (?, ?, 'checking')",
            (account_id, account_id),
        )
    return "acct"


@pytest.fixture
def card(conn, account, tmp_path):
    """Import ID-less rows. Each file name must be new."""

    def run(name, *rows, declared=None, account_id="acct"):
        path = tmp_path / name
        body = distinct_bytes(tmp_path, rows)
        path.write_text(CARD_HEADER + body, encoding="utf-8")
        coverage = declare_complete(*declared) if declared else None
        (result,) = import_files(
            conn, [path], account_id=account_id, layout=SYNTHETIC_CARD_V1,
            declared_coverage=coverage,
        )
        assert result.outcome != "failed", result
        return result

    return run


@pytest.fixture
def checking(conn, account, tmp_path):
    """Import rows with IDs and optional metadata lines."""

    def run(name, *rows, metadata=(), layout=SYNTHETIC_CHECKING_V1, declared=None):
        path = tmp_path / name
        lines = [f"# {line}\n" for line in metadata]
        body = distinct_bytes(tmp_path, rows)
        path.write_text("".join(lines) + CHECKING_HEADER + body, encoding="utf-8")
        coverage = declare_complete(*declared) if declared else None
        (result,) = import_files(
            conn, [path], account_id="acct", layout=layout, declared_coverage=coverage
        )
        assert result.outcome != "failed", result
        return result

    return run


def cafe(day="01/10/2026", amount="5.00", description="SYNTHETIC CAFE"):
    return f"{day},{description},{amount},"


def complete_metadata(end="2026-01-31", generated=None, start="2026-01-01", basis="posting"):
    lines = ["coverage-kind: complete", f"coverage-start: {start}", f"coverage-end: {end}",
             f"coverage-basis: {basis}"]
    return lines + ([f"generated-on: {generated}"] if generated else [])


def transactions(conn):
    return conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()[0]


def open_items(conn):
    return conn.execute(
        """SELECT rule, evidence_json, (SELECT COUNT(*) FROM review_issue_subject subject
                                        WHERE subject.review_issue_id = issue.id)
           FROM review_issue issue
           WHERE status = 'open' AND kind = 'possible_duplicate' AND rule LIKE 'cross_document%'"""
    ).fetchall()


def reasons(conn):
    return sorted(reason for _, evidence, _ in open_items(conn)
                  for reason in json.loads(evidence)["reasons"])


class TestConfidentMatches:
    def test_a2_a_reordered_export_adds_no_transactions(self, conn, card):
        rows = [cafe("01/05/2026"), cafe("01/06/2026"), cafe("01/07/2026", "9.00")]
        card("a.csv", *rows, declared=JANUARY)
        result = card("b.csv", *reversed(rows), declared=JANUARY)

        assert transactions(conn) == 3
        assert (result.valid_records, result.consolidated_records) == (3, 3)
        assert conn.execute("SELECT COUNT(*) FROM transaction_source").fetchone() == (6,)
        assert open_items(conn) == []

    def test_a2_with_reliable_ids(self, conn, checking):
        rows = ["S-1,2026-01-05,2026-01-06,SYNTHETIC CAFE,-5.00,POSTED",
                "S-2,2026-01-07,2026-01-08,SYNTHETIC CAFE,-5.00,POSTED"]
        checking("a.csv", *rows)
        checking("b.csv", *reversed(rows))
        assert transactions(conn) == 2

    def test_a3_overlapping_periods_count_the_overlap_once(self, conn, card):
        card("a.csv", cafe("01/05/2026", "1.00"), cafe("01/20/2026", "2.00"), declared=JANUARY)
        card("b.csv", cafe("01/20/2026", "2.00"), cafe("02/10/2026", "3.00"),
             declared=("2026-01-15", "2026-02-15", "posting"))

        assert transactions(conn) == 3
        assert account_movement(conn).outflow_cents == 600
        assert open_items(conn) == []

    def test_a4_identical_purchases_survive_an_overlapping_file(self, conn, card):
        card("a.csv", cafe(), cafe(), declared=JANUARY)
        card("b.csv", cafe(), cafe(), cafe("01/20/2026", "2.00"), declared=JANUARY)
        assert transactions(conn) == 3
        assert account_movement(conn).outflow_cents == 1200

    def test_a5a_two_against_three_with_complete_coverage(self, conn, card):
        card("a.csv", cafe(), cafe(), declared=JANUARY)
        card("b.csv", cafe(), cafe(), cafe(), declared=JANUARY)
        assert transactions(conn) == 3
        assert open_items(conn) == []

    def test_a20_a_reliable_id_needs_no_coverage(self, conn, checking):
        checking("a.csv", "S-1,,2026-01-06,SYNTHETIC CAFE,-5.00,POSTED")
        checking("b.csv", "S-1,,2026-01-06,SYNTHETIC CAFE,-5.00,POSTED", "S-2,,2026-01-07,X,-1.00,")
        assert transactions(conn) == 2

    def test_a32_a_user_declared_end_date_is_confident(self, conn, card):
        card("a.csv", cafe("01/31/2026"), declared=JANUARY)
        card("b.csv", cafe("01/31/2026"), declared=("2026-01-15", "2026-01-31", "posting"))
        assert transactions(conn) == 1
        assert open_items(conn) == []

    def test_a45_a_reliable_id_is_confident_on_a_single_day_overlap(self, conn, checking):
        row = "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED"
        checking("a.csv", row, declared=("2026-01-01", "2026-01-10", "posting"))
        checking("b.csv", row, declared=("2026-01-10", "2026-01-20", "posting"))
        assert transactions(conn) == 1
        assert open_items(conn) == []

    def test_a44_an_id_match_needs_no_similar_description(self, conn, checking):
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        checking("b.csv", "S-1,,2026-01-10,COMPLETELY OTHER WORDS,-5.00,POSTED")
        assert transactions(conn) == 1
        descriptions = conn.execute(
            "SELECT description FROM record_parse ORDER BY description"
        ).fetchall()
        assert descriptions == [("COMPLETELY OTHER WORDS",), ("SYNTHETIC CAFE",)]

    def test_a46_unknown_status_stays_unknown_in_its_source(self, conn, checking):
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,")
        checking("b.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")

        assert transactions(conn) == 1
        statuses = conn.execute(
            "SELECT settlement_status FROM record_parse ORDER BY settlement_status"
        ).fetchall()
        assert statuses == [("posted",), ("unknown",)]
        assert conn.execute("SELECT settlement_status FROM ledger_transaction").fetchone() == ("posted",)


class TestPossibleDuplicates:
    @pytest.mark.parametrize("second", [None, "partial"])
    def test_a5b_all_records_stay_separate_in_one_item(self, conn, card, checking, second):
        card("a.csv", cafe(), cafe())
        if second is None:
            card("b.csv", cafe(), cafe(), cafe(), declared=JANUARY)
        else:
            row = ",2026-01-10,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED"
            checking("b.csv", row, row, row, metadata=["coverage-kind: partial"])

        assert transactions(conn) == 5
        assert account_movement(conn).outflow_cents == 2500
        assert [count for _, _, count in open_items(conn)] == [5]

    def test_a6_a_near_match_is_kept_counted_and_listed(self, conn, card):
        card("a.csv", cafe("01/10/2026"))
        card("b.csv", cafe("01/11/2026"))
        assert transactions(conn) == 2
        assert reasons(conn) == ["similar_description"]

    def test_a7_a_conflicting_amount_is_flagged(self, conn, checking):
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        checking("b.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-6.00,POSTED")
        assert transactions(conn) == 2
        assert open_items(conn)[0][0] == "cross_document_external_id"

    def test_a8_the_same_rows_in_two_accounts_never_match(self, conn, card):
        card("a.csv", cafe(), declared=JANUARY)
        card("b.csv", cafe(), declared=JANUARY, account_id="other")
        assert transactions(conn) == 2
        assert open_items(conn) == []

    def test_a21_an_unreliable_id_is_not_identity(self, conn, checking):
        unreliable = replace(
            SYNTHETIC_CHECKING_V1, layout_id="test_unreliable_ids",
            external_id_guarantee="none", external_id_namespace=None,
        )
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED", layout=unreliable)
        checking("b.csv", "S-1,,2026-01-10,SYNTHETIC GROCER,-5.00,POSTED", layout=unreliable)
        assert transactions(conn) == 2
        assert open_items(conn) == []

        checking("c.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED", "S-9,,2026-01-01,X,-1.00,",
                 layout=unreliable)
        assert transactions(conn) == 4
        assert reasons(conn) == ["coverage_unknown"]

    def test_a22_a_single_day_overlap_stays_flagged_when_declared(self, conn, card):
        card("a.csv", cafe(), declared=("2026-01-01", "2026-01-10", "posting"))
        card("b.csv", cafe(), declared=("2026-01-10", "2026-01-20", "posting"))
        assert transactions(conn) == 2
        assert reasons(conn) == ["single_day_overlap"]

    def test_a24_different_date_bases_are_flagged(self, conn, checking):
        row = ",2026-01-10,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED"
        checking("a.csv", row, metadata=complete_metadata(generated="2026-02-05"))
        checking("b.csv", row, "S-9,,2026-01-01,X,-1.00,",
                 metadata=complete_metadata(generated="2026-02-05", basis="transaction"))
        assert reasons(conn) == ["different_basis"]

    def test_a27_rows_without_a_counterpart_are_not_flagged(self, conn, card):
        card("a.csv", cafe("01/05/2026", "1.00"))
        card("b.csv", cafe("01/20/2026", "2.00"))
        assert open_items(conn) == []

    @pytest.mark.parametrize("generated", [None, "2026-01-31"])
    def test_a33_a_metadata_end_date_is_not_assumed_complete(self, conn, checking, generated):
        row = ",2026-01-31,2026-01-31,SYNTHETIC CAFE,-5.00,POSTED"
        metadata = complete_metadata(generated=generated)
        checking("a.csv", row, metadata=metadata)
        checking("b.csv", row, "S-9,,2026-01-01,X,-1.00,", metadata=metadata)
        assert transactions(conn) == 3
        assert reasons(conn) == ["boundary_date"]

    def test_a33_contrast_a_passed_end_date_is_confident(self, conn, checking):
        row = ",2026-01-31,2026-01-31,SYNTHETIC CAFE,-5.00,POSTED"
        metadata = complete_metadata(generated="2026-02-02")
        checking("a.csv", row, metadata=metadata)
        checking("b.csv", row, "S-9,,2026-01-01,X,-1.00,", metadata=metadata)
        assert transactions(conn) == 2

    def test_a34_a_conflicting_date_or_status_is_flagged(self, conn, checking):
        checking("a.csv", "S-1,,2026-01-10,A CAFE,-5.00,POSTED", "S-2,2026-01-11,,B CAFE,-5.00,PENDING")
        checking("b.csv", "S-1,,2026-01-12,A CAFE,-5.00,POSTED", "S-2,2026-01-11,2026-01-12,B CAFE,-5.00,POSTED")
        assert transactions(conn) == 4
        rules = sorted(rule for rule, _, _ in open_items(conn))
        assert rules.count("cross_document_external_id") == 2

    def test_a34_an_id_repeated_within_a_document_is_flagged(self, conn, checking):
        row = "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED"
        checking("a.csv", row, row)
        checking("b.csv", row)
        assert transactions(conn) == 3
        assert "external_id_repeated" in reasons(conn)

    def test_a35_an_unresolved_row_keeps_the_match_possible(self, conn, card):
        card("a.csv", cafe(), "01/10/2026,SYNTHETIC CAFE,,", declared=JANUARY)
        card("b.csv", cafe(), declared=JANUARY)

        assert transactions(conn) == 2
        assert reasons(conn) == ["unresolved_row"]
        assert account_movement(conn).unresolved_records == 1

    def test_a35_contrast_an_unrelated_unresolved_row_changes_nothing(self, conn, card):
        card("a.csv", cafe(), "01/20/2026,SYNTHETIC CAFE,,", declared=JANUARY)
        card("b.csv", cafe(), declared=JANUARY)
        assert transactions(conn) == 1
        assert account_movement(conn).unresolved_records == 1

    def test_a42_unrelated_purchases_create_nothing(self, conn, card):
        card("a.csv", cafe())
        card("b.csv", cafe(description="SYNTHETIC GROCER"))
        assert open_items(conn) == []

    def test_a43_a_variation_is_flagged_and_never_merged(self, conn, card):
        card("a.csv", cafe(description="SQ *SYNTHETIC CAFE #1042"), declared=JANUARY)
        card("b.csv", cafe(day="01/11/2026", description="SYNTHETIC CAFE OAKLAND"), declared=JANUARY)
        assert transactions(conn) == 2
        assert len(open_items(conn)) == 1


class TestProvenance:
    def test_a36_every_source_stays_linked_and_evidence_is_unchanged(self, conn, card):
        card("a.csv", cafe(), declared=JANUARY)
        evidence = dump(conn)
        card("b.csv", cafe(), declared=JANUARY)

        (merged,) = conn.execute("SELECT id FROM ledger_transaction").fetchall()
        links = conn.execute(
            "SELECT source_document_id, link_rule FROM transaction_source WHERE transaction_id = ?",
            merged,
        ).fetchall()
        assert len(links) == 2
        assert {rule for _, rule in links} == {"exact_coverage_pair"}
        after = dump(conn)
        for table in ("source_document", "source_record", "record_parse", "document_coverage"):
            assert set(evidence[table]) <= set(after[table])

    def test_a_merge_is_recorded_with_its_reason(self, conn, card):
        first = card("a.csv", cafe(), declared=JANUARY)
        second = card("b.csv", cafe(), declared=JANUARY)
        (row,) = conn.execute(
            """SELECT action, reason, rules_fingerprint, trigger_document_id
               FROM transaction_link_history"""
        ).fetchall()
        assert row == ("merged", "exact_coverage_pair", DEFAULT_RULES.fingerprint(),
                       second.source_document_id)
        assert first.source_document_id != second.source_document_id

    def test_the_earliest_imported_transaction_keeps_its_id(self, conn, card):
        card("a.csv", cafe(), declared=JANUARY)
        before = conn.execute("SELECT id FROM ledger_transaction").fetchone()
        card("b.csv", cafe(), declared=JANUARY)
        assert conn.execute("SELECT id FROM ledger_transaction").fetchall() == [before]

    def test_an_unmatched_transaction_keeps_its_id(self, conn, card):
        card("a.csv", cafe("01/05/2026", "1.00"), cafe("01/06/2026", "2.00"), declared=JANUARY)
        before = set(conn.execute("SELECT id FROM ledger_transaction").fetchall())
        card("b.csv", cafe("01/06/2026", "2.00"), declared=JANUARY)
        assert set(conn.execute("SELECT id FROM ledger_transaction").fetchall()) == before

    def test_a_primary_source_change_leaves_totals_alone(self, conn, checking):
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,")
        before = account_movement(conn)
        checking("b.csv", "S-1,2026-01-09,2026-01-10,FULLER NAME,-5.00,POSTED")

        after = account_movement(conn)
        assert (after.net_cents, after.transactions) == (before.net_cents, before.transactions)
        assert conn.execute(
            "SELECT description, transaction_date, settlement_status FROM ledger_transaction"
        ).fetchone() == ("FULLER NAME", "2026-01-09", "posted")


class TestPrimarySource:
    def test_every_transaction_records_a_primary_among_its_own_sources(self, conn, checking, card):
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,", "S-2,,2026-01-11,X,-1.00,")
        checking("b.csv", "S-1,2026-01-09,2026-01-10,FULLER NAME,-5.00,POSTED")
        assert conn.execute(
            """SELECT COUNT(*) FROM ledger_transaction entry
               WHERE NOT EXISTS (SELECT 1 FROM transaction_source link
                                 WHERE link.transaction_id = entry.id
                                   AND link.source_record_id = entry.primary_source_record_id)"""
        ).fetchone() == (0,)

    def test_displayed_values_equal_the_primary_records_parse(self, conn, checking):
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,")
        checking("b.csv", "S-1,2026-01-09,2026-01-10,FULLER NAME,-5.00,POSTED")
        assert conn.execute(
            """SELECT entry.description = parse.description,
                      entry.settlement_status = parse.settlement_status
               FROM ledger_transaction entry
               JOIN record_parse parse ON parse.source_record_id = entry.primary_source_record_id"""
        ).fetchall() == [(1, 1)]


class TestSplits:
    unknown = "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,"
    posted_one = "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED"
    posted_two = "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED"

    def test_a_merge_splits_when_a_later_document_makes_it_inconsistent(self, conn, checking):
        checking("a.csv", self.unknown)
        checking("b.csv", self.posted_one)
        assert transactions(conn) == 1

        checking("c.csv", self.posted_two)

        assert transactions(conn) == 3
        assert open_items(conn)[0][0] == "cross_document_external_id"
        assert account_movement(conn).outflow_cents == 1500
        assert conn.execute(
            "SELECT action, reason FROM transaction_link_history ORDER BY id"
        ).fetchall() == [
            ("merged", "reliable_external_id"),
            ("split", "external_id_conflict"),
        ]
        assert conn.execute("SELECT COUNT(*) FROM transaction_source").fetchone() == (3,)

    def test_a_split_gives_a_record_its_original_id_back(self, conn, checking):
        checking("a.csv", self.unknown)
        checking("b.csv", self.posted_one)
        (retired,) = conn.execute(
            "SELECT from_transaction_id FROM transaction_link_history"
        ).fetchone()
        assert conn.execute("SELECT 1 FROM ledger_transaction WHERE id = ?", (retired,)).fetchone() is None

        checking("c.csv", self.posted_two)

        assert conn.execute(
            "SELECT posting_date FROM ledger_transaction WHERE id = ?", (retired,)
        ).fetchone() == ("2026-01-10",)

    def test_identity_survives_merge_retirement_split_and_revival(self, conn, checking, monkeypatch):
        distinctive = "2026-01-02T03:04:05.678Z"
        original = apply.reconcile_account

        def stamp_new_rows_first(connection, *args, **kwargs):
            connection.execute("UPDATE ledger_transaction SET created_at = ?", (distinctive,))
            return original(connection, *args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(pipeline, "reconcile_account", stamp_new_rows_first)
            checking("a.csv", self.unknown)
            checking("b.csv", self.posted_one)
        retired, = conn.execute(
            "SELECT from_transaction_id FROM transaction_link_history"
        ).fetchone()
        (retirement,) = conn.execute(
            """SELECT event, reason, transaction_created_at FROM transaction_identity_history
               WHERE transaction_id = ?""",
            (retired,),
        ).fetchall()
        assert retirement == ("retired", "reliable_external_id", distinctive)
        original_created_at = distinctive
        assert conn.execute("SELECT 1 FROM ledger_transaction WHERE id = ?", (retired,)).fetchone() is None

        checking("c.csv", self.posted_two)

        assert conn.execute(
            "SELECT created_at FROM ledger_transaction WHERE id = ?", (retired,)
        ).fetchone() == (original_created_at,)
        assert conn.execute(
            """SELECT event, reason, transaction_created_at FROM transaction_identity_history
               WHERE transaction_id = ? ORDER BY id""",
            (retired,),
        ).fetchall() == [
            ("retired", "reliable_external_id", original_created_at),
            ("revived", "external_id_conflict", original_created_at),
        ]

    def test_an_id_retired_again_keeps_its_timestamp(self, conn, card, tmp_path):
        strict = replace(DEFAULT_RULES, similarity_threshold_percent=76)
        row = cafe(description="BLUE BOTTLE COFFEE OAKLAND")
        first = tmp_path / "a.csv"
        second = tmp_path / "b.csv"
        first.write_text(CARD_HEADER + row + "\n01/10/2026,BLUE BOTTLE COFFEE BERKELEY,,\n", encoding="utf-8")
        second.write_text(CARD_HEADER + row + "\n", encoding="utf-8")
        declared = declare_complete(*JANUARY)
        for path in (first, second):
            import_files(conn, [path], account_id="acct", layout=SYNTHETIC_CARD_V1,
                         declared_coverage=declared)
        original = dict(conn.execute("SELECT id, created_at FROM ledger_transaction"))
        assert len(original) == 2

        for rules in (strict, DEFAULT_RULES, strict, DEFAULT_RULES):
            conn.execute("BEGIN IMMEDIATE")
            reconcile_account(conn, "acct", rules)
            conn.execute("COMMIT")

        assert dict(conn.execute("SELECT id, created_at FROM ledger_transaction")) == original
        events = conn.execute(
            "SELECT event FROM transaction_identity_history ORDER BY id"
        ).fetchall()
        assert events == [("retired",), ("revived",), ("retired",), ("revived",)]

    def test_an_id_retired_before_identity_history_uses_its_link_timestamp(self, conn, checking):
        checking("a.csv", self.unknown)
        checking("b.csv", self.posted_one)
        conn.executescript(
            """DROP TRIGGER transaction_identity_history_no_delete;
               DELETE FROM transaction_identity_history;"""
        )
        link_time = conn.execute(
            """SELECT link.created_at FROM transaction_source link
               JOIN transaction_link_history history
                   ON history.source_record_id = link.source_record_id"""
        ).fetchone()
        checking("c.csv", self.posted_two)

        retired, = conn.execute(
            "SELECT from_transaction_id FROM transaction_link_history ORDER BY id LIMIT 1"
        ).fetchone()
        assert conn.execute(
            "SELECT created_at FROM ledger_transaction WHERE id = ?", (retired,)
        ).fetchone() == link_time

    def test_the_split_outcome_matches_never_having_merged(self, conn, checking, tmp_path):
        checking("a.csv", self.unknown)
        checking("b.csv", self.posted_one)
        checking("c.csv", self.posted_two)
        split = semantic_view(conn)

        path = tmp_path / "other.db"
        create_database(path)
        other = connect(path)
        other.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'checking')"
        )
        files = [tmp_path / name for name in ("c.csv", "a.csv", "b.csv")]
        import_files(other, files, account_id="acct", layout=SYNTHETIC_CHECKING_V1)
        assert semantic_view(other) == split
        other.close()


    def test_a_same_document_issue_stays_with_its_own_record_through_a_split(self, conn, checking):
        pending = "S-7,2026-01-09,,SYNTHETIC CAFE,-5.00,PENDING"
        checking("a.csv", self.posted_one, pending)
        checking("b.csv", self.unknown)
        checking("c.csv", self.posted_two)

        statuses = conn.execute(
            """SELECT parse.settlement_status
               FROM review_issue_subject subject
               JOIN review_issue issue ON issue.id = subject.review_issue_id
               JOIN transaction_source link ON link.transaction_id = subject.transaction_id
               JOIN record_parse parse ON parse.source_record_id = link.source_record_id
               WHERE issue.rule = 'same_document_pending_posted'
               ORDER BY 1"""
        ).fetchall()
        assert statuses == [("pending",), ("posted",)]

    def test_a_split_caused_by_a_rule_change_says_so(self, conn, card, tmp_path):
        strict = replace(DEFAULT_RULES, similarity_threshold_percent=76)
        row = cafe(description="BLUE BOTTLE COFFEE OAKLAND")
        blocker = "01/10/2026,BLUE BOTTLE COFFEE BERKELEY,,"
        first = tmp_path / "a.csv"
        second = tmp_path / "b.csv"
        first.write_text(CARD_HEADER + row + "\n" + blocker + "\n", encoding="utf-8")
        second.write_text(CARD_HEADER + row + "\n", encoding="utf-8")
        for path in (first, second):
            import_files(conn, [path], account_id="acct", layout=SYNTHETIC_CARD_V1,
                         declared_coverage=declare_complete(*JANUARY), rules=strict)
        assert transactions(conn) == 1

        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, "acct", DEFAULT_RULES)
        conn.execute("COMMIT")

        assert transactions(conn) == 2
        assert conn.execute(
            "SELECT action, reason, rules_fingerprint FROM transaction_link_history ORDER BY id DESC"
        ).fetchone() == ("split", "matching_rules_changed", DEFAULT_RULES.fingerprint())


class TestRepeatsAndReview:
    def test_a1_a38_repeat_imports_change_nothing(self, conn, card, tmp_path):
        card("a.csv", cafe(), cafe("01/11/2026"))
        card("b.csv", cafe(), declared=JANUARY)
        before = dump(conn)

        for name in ("a.csv", "b.csv", "a.csv"):
            (result,) = import_files(
                conn, [tmp_path / name], account_id="acct", layout=SYNTHETIC_CARD_V1
            )
            assert result.outcome == "already_imported"
            assert result.reconciled is False
        assert dump(conn) == before

    def test_a_group_grows_in_place_when_a_document_joins(self, conn, card):
        card("a.csv", cafe())
        card("b.csv", cafe())
        (issue,) = conn.execute("SELECT id FROM review_issue").fetchall()
        card("c.csv", cafe())
        assert conn.execute("SELECT id FROM review_issue").fetchall() == [issue]
        assert [count for _, _, count in open_items(conn)] == [3]

    def test_two_groups_joined_by_a_document_become_one_item(self, conn, card):
        card("a.csv", cafe("01/01/2026"), cafe("01/07/2026"))
        card("b.csv", cafe("01/01/2026"), cafe("01/07/2026"))
        assert len(open_items(conn)) == 2
        card("c.csv", cafe("01/04/2026"))
        assert [count for _, _, count in open_items(conn)] == [5]

    def test_a_same_document_issue_follows_its_records_through_a_merge(self, conn, checking):
        rows = ["S-1,2026-01-05,,SYNTHETIC CAFE,-6.50,PENDING", "S-2,2026-01-05,2026-01-06,SYNTHETIC CAFE,-6.50,POSTED"]
        checking("a.csv", "S-9,,2026-01-01,X,-1.00,", "S-2,2026-01-05,2026-01-06,SYNTHETIC CAFE,-6.50,POSTED")
        checking("b.csv", *rows)

        subjects = conn.execute(
            """SELECT COUNT(*) FROM review_issue_subject subject
               JOIN review_issue issue ON issue.id = subject.review_issue_id
               JOIN ledger_transaction entry ON entry.id = subject.transaction_id
               WHERE issue.rule = 'same_document_pending_posted'"""
        ).fetchone()
        assert subjects == (2,)

    def test_a_resolved_issue_is_not_reopened_or_rewritten(self, conn, card):
        card("a.csv", cafe())
        card("b.csv", cafe())
        conn.execute(
            """UPDATE review_issue SET status = 'resolved',
                      resolved_at = '2026-02-01T00:00:00.000Z'"""
        )
        before = conn.execute("SELECT * FROM review_issue").fetchall()

        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, "acct")
        conn.execute("COMMIT")

        assert conn.execute("SELECT * FROM review_issue").fetchall() == before
        assert open_items(conn) == []


class TestAtomicity:
    @pytest.mark.parametrize(
        "step",
        ["write_transactions", "write_links", "write_review_items", "repoint_other_issues",
         "retire_unused_transactions"],
    )
    def test_a37_a_failure_at_any_stage_leaves_no_partial_state(
        self, conn, card, tmp_path, monkeypatch, step
    ):
        card("a.csv", cafe(), cafe("01/12/2026", "2.00"), declared=JANUARY)
        card("b.csv", cafe("01/12/2026", "2.00"))
        before = dump(conn)
        path = tmp_path / "c.csv"
        path.write_text(CARD_HEADER + cafe("01/12/2026", "2.00") + "\n" + cafe() + "\n", encoding="utf-8")
        original = getattr(apply._State, step)

        def fail_after(self, *args):
            original(self, *args)
            raise RuntimeError("injected")

        with monkeypatch.context() as patch:
            patch.setattr(apply._State, step, fail_after)
            (failed,) = import_files(
                conn, [path], account_id="acct", layout=SYNTHETIC_CARD_V1,
                declared_coverage=declare_complete(*JANUARY),
            )
        assert (failed.outcome, failed.failure_code) == ("failed", "internal_error")
        assert dump(conn) == before

        (retried,) = import_files(
            conn, [path], account_id="acct", layout=SYNTHETIC_CARD_V1,
            declared_coverage=declare_complete(*JANUARY),
        )
        assert retried.outcome == "imported"

    def test_a37_a_process_crash_during_matching_leaves_no_partial_state(self, db_path, tmp_path):
        conn = connect(db_path)
        conn.execute("INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'checking')")
        first = tmp_path / "a.csv"
        second = tmp_path / "b.csv"
        first.write_text(CARD_HEADER + cafe() + "\n", encoding="utf-8")
        second.write_text(CARD_HEADER + cafe() + "\n" + cafe("01/11/2026", "2.00") + "\n", encoding="utf-8")
        declared = declare_complete(*JANUARY)
        import_files(conn, [first], account_id="acct", layout=SYNTHETIC_CARD_V1, declared_coverage=declared)
        before = dump(conn)
        conn.close()

        script = """
import os, sys
from pathlib import Path
from personal_finance.db.migrate import connect
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.reconcile import apply

original = apply._State.write_links
def crash(self, *args):
    original(self, *args)
    os._exit(9)
apply._State.write_links = crash
import_files(connect(Path(sys.argv[1])), [Path(sys.argv[2])], account_id="acct",
             layout=SYNTHETIC_CARD_V1,
             declared_coverage=declare_complete("2026-01-01", "2026-01-31", "posting"))
"""
        env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        done = subprocess.run([sys.executable, "-c", script, str(db_path), str(second)], env=env)
        assert done.returncode == 9

        conn = connect(db_path)
        assert dump(conn) == before
        (result,) = import_files(
            conn, [second], account_id="acct", layout=SYNTHETIC_CARD_V1, declared_coverage=declared
        )
        assert result.outcome == "imported"
        assert transactions(conn) == 2
        conn.close()


class TestBusyDatabase:
    """A lost lock must leave nothing behind, and a retry must complete the work."""

    @pytest.fixture(autouse=True)
    def run_row(self, conn):
        conn.execute("INSERT INTO import_run (id) VALUES ('run')")

    @pytest.fixture
    def overlap(self, conn, card, tmp_path):
        card("a.csv", cafe(), declared=JANUARY)
        path = tmp_path / "b.csv"
        path.write_text(CARD_HEADER + cafe() + "\n" + cafe("01/20/2026", "2.00") + "\n", encoding="utf-8")
        return path

    def attempt(self, db_path, path, declared=None):
        """Import with almost no patience. The caller closes the returned connection."""
        blocked = connect(db_path)
        blocked.execute("PRAGMA busy_timeout = 50")
        return blocked, pipeline._import_file(
            blocked, "run", path, "acct", SYNTHETIC_CARD_V1, declared
        )

    def assert_retry_completes(self, conn, path):
        (retried,) = import_files(
            conn, [path], account_id="acct", layout=SYNTHETIC_CARD_V1,
            declared_coverage=declare_complete(*JANUARY),
        )
        assert (retried.outcome, retried.consolidated_records) == ("imported", 1)
        assert transactions(conn) == 2
        assert is_current(conn, "acct", DEFAULT_RULES)

    def test_a_blocked_write_lock_fails_cleanly(self, conn, db_path, overlap):
        before = dump(conn)
        conn.execute("BEGIN IMMEDIATE")
        blocked, result = self.attempt(db_path, overlap, declare_complete(*JANUARY))
        conn.execute("COMMIT")

        assert (result.outcome, result.failure_code) == ("failed", "database_busy")
        assert dump(conn) == before
        blocked.close()
        self.assert_retry_completes(conn, overlap)

    def test_a_commit_blocked_after_reconciliation_leaves_nothing(self, conn, db_path, overlap):
        """All the matching work is done here, and still none of it may survive."""
        before = dump(conn)
        reader = connect(db_path, read_only=True)
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()

        blocked, result = self.attempt(db_path, overlap, declare_complete(*JANUARY))

        assert (result.outcome, result.failure_code) == ("failed", "database_busy")
        assert not blocked.in_transaction
        reader.execute("ROLLBACK")
        reader.close()
        blocked.close()

        assert dump(conn) == before
        self.assert_retry_completes(conn, overlap)

    def test_a_blocked_catch_up_on_a_repeat_import_stays_retryable(
        self, conn, db_path, card, tmp_path
    ):
        card("a.csv", cafe())
        conn.execute("DELETE FROM account_reconciliation")
        before = dump(conn)
        reader = connect(db_path, read_only=True)
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()

        blocked, result = self.attempt(db_path, tmp_path / "a.csv")
        reader.execute("ROLLBACK")
        reader.close()
        blocked.close()

        assert (result.outcome, result.failure_code) == ("failed", "database_busy")
        assert dump(conn) == before
        assert not is_current(conn, "acct", DEFAULT_RULES)

        (retried,) = import_files(conn, [tmp_path / "a.csv"], account_id="acct", layout=SYNTHETIC_CARD_V1)
        assert (retried.outcome, retried.reconciled) == ("already_imported", True)
        assert is_current(conn, "acct", DEFAULT_RULES)


class TestStoredInterpretation:
    def test_interpretation_is_stored_at_import(self, conn, checking):
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        assert conn.execute(
            """SELECT layout_id, parser_version, external_id_namespace, external_id_guarantee,
                      pending_in_transaction_basis, pending_in_posting_basis
               FROM document_interpretation"""
        ).fetchall() == [
            ("synthetic_checking_v1", "1", "synthetic_checking_v1", "stable_unique", 1, 0)
        ]

    def test_a_changed_layout_definition_is_refused(self, conn, checking, tmp_path):
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        before = dump(conn)
        weakened = replace(SYNTHETIC_CHECKING_V1, external_id_guarantee="stable")
        path = tmp_path / "b.csv"
        path.write_text(CHECKING_HEADER + "S-2,,2026-01-11,X,-1.00,\n", encoding="utf-8")

        (result,) = import_files(conn, [path], account_id="acct", layout=weakened)

        assert (result.outcome, result.failure_code) == ("failed", "layout_definition_changed")
        assert dump(conn) == before

    def test_stored_meaning_wins_over_current_python(self, conn, checking, monkeypatch):
        """Reconciliation must not read layouts, so editing one cannot reinterpret history."""
        checking("a.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        checking("b.csv", "S-1,,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        monkeypatch.setattr(pipeline, "SYNTHETIC_CHECKING_V1", None, raising=False)
        conn.execute("BEGIN IMMEDIATE")
        reconcile_account(conn, "acct")
        conn.execute("COMMIT")
        assert transactions(conn) == 1


class TestRuleVersions:
    wide = replace(DEFAULT_RULES, date_window_days=9)

    def test_an_account_is_current_only_for_the_configuration_used(self, conn, card):
        card("a.csv", cafe())
        assert is_current(conn, "acct", DEFAULT_RULES)
        assert not is_current(conn, "acct", self.wide)

    def test_an_override_does_not_leave_the_account_marked_current(self, conn, card, tmp_path):
        path = tmp_path / "a.csv"
        path.write_text(CARD_HEADER + cafe() + "\n", encoding="utf-8")
        import_files(conn, [path], account_id="acct", layout=SYNTHETIC_CARD_V1, rules=self.wide)

        assert not is_current(conn, "acct", DEFAULT_RULES)
        fingerprint, stored = conn.execute(
            "SELECT rules_fingerprint, rules_json FROM account_reconciliation"
        ).fetchone()
        assert fingerprint == self.wide.fingerprint()
        assert json.loads(stored)["settings"]["date_window_days"] == 9

    def test_returning_to_the_default_rules_re_derives_the_account(self, conn, card, tmp_path):
        rows = {"a.csv": cafe("01/01/2026"), "b.csv": cafe("01/09/2026")}
        paths = []
        for name, row in rows.items():
            path = tmp_path / name
            path.write_text(CARD_HEADER + row + "\n", encoding="utf-8")
            paths.append(path)
        import_files(conn, paths, account_id="acct", layout=SYNTHETIC_CARD_V1, rules=self.wide)
        assert len(open_items(conn)) == 1

        (result,) = import_files(conn, paths[:1], account_id="acct", layout=SYNTHETIC_CARD_V1)

        assert (result.outcome, result.reconciled) == ("already_imported", True)
        assert open_items(conn) == []
        assert is_current(conn, "acct", DEFAULT_RULES)


class TestExistingAccounts:
    def test_a_repeat_import_reconciles_an_account_once(self, conn, account, tmp_path, monkeypatch):
        first = tmp_path / "a.csv"
        second = tmp_path / "b.csv"
        first.write_text(CARD_HEADER + cafe() + "\n", encoding="utf-8")
        second.write_text(CARD_HEADER + cafe() + "\n" + cafe("01/20/2026", "2.00") + "\n", encoding="utf-8")
        declared = declare_complete(*JANUARY)

        with monkeypatch.context() as patch:
            patch.setattr(pipeline, "reconcile_account", lambda *args, **kwargs: ReconcileResult(None, 0))
            for path in (first, second):
                import_files(conn, [path], account_id="acct", layout=SYNTHETIC_CARD_V1,
                             declared_coverage=declared)
        assert transactions(conn) == 3
        assert not is_current(conn, "acct", DEFAULT_RULES)

        (result,) = import_files(conn, [first], account_id="acct", layout=SYNTHETIC_CARD_V1)
        assert (result.outcome, result.reconciled) == ("already_imported", True)
        assert transactions(conn) == 2
        settled = dump(conn)

        (again,) = import_files(conn, [first], account_id="acct", layout=SYNTHETIC_CARD_V1)
        assert again.reconciled is False
        assert dump(conn) == settled

    def test_a_version_two_ledger_upgrades_and_reconciles(self, tmp_path):
        old = tmp_path / "old_migrations"
        old.mkdir()
        for name in ("0001_initial.sql", "0002_block_replace.sql"):
            shutil.copy(MIGRATIONS_DIR / name, old / name)
        path = tmp_path / "old.db"
        create_database(path, old)
        conn = connect(path)
        content = (CARD_HEADER + cafe() + "\n").encode("utf-8")
        seed_version_two(conn, content)

        migrate(conn)

        meaning = conn.execute(
            """SELECT layout_id, parser_version, external_id_guarantee, pending_in_posting_basis
               FROM document_interpretation ORDER BY source_document_id"""
        ).fetchall()
        assert meaning == [("synthetic_card_v1", "1", "none", 0)] * 2
        assert conn.execute(
            """SELECT source_record_id, original_transaction_id FROM source_record_origin
               ORDER BY 1"""
        ).fetchall() == [("r1", "t1"), ("r2", "t2")]

        file = tmp_path / "a.csv"
        file.write_bytes(content)
        (result,) = import_files(conn, [file], account_id="acct", layout=SYNTHETIC_CARD_V1)
        assert (result.outcome, result.reconciled) == ("already_imported", True)
        assert transactions(conn) == 1
        conn.close()


    def version_three_ledger(self, tmp_path):
        old = tmp_path / "old_migrations"
        old.mkdir()
        for migration in load_migrations()[:3]:
            shutil.copy(migration.path, old / migration.path.name)
        path = tmp_path / "old.db"
        create_database(path, old)
        conn = connect(path)
        seed_version_two(conn, (CARD_HEADER + cafe() + "\n").encode("utf-8"))
        return conn

    def test_the_backfill_records_the_only_source_of_a_transaction(self, tmp_path):
        conn = self.version_three_ledger(tmp_path)
        migrate(conn)
        assert dict(conn.execute("SELECT id, primary_source_record_id FROM ledger_transaction")) == {
            "t1": "r1", "t2": "r2",
        }
        conn.close()

    def test_the_backfill_does_not_guess_the_primary_of_a_merged_transaction(self, tmp_path):
        conn = self.version_three_ledger(tmp_path)
        conn.execute("UPDATE transaction_source SET transaction_id = 't1' WHERE transaction_id = 't2'")
        conn.execute("DELETE FROM ledger_transaction WHERE id = 't2'")

        migrate(conn)

        assert conn.execute(
            "SELECT id, primary_source_record_id FROM ledger_transaction"
        ).fetchall() == [("t1", None)]
        conn.close()

    def test_the_backfill_keeps_the_meaning_of_checking_documents(self, tmp_path):
        old = tmp_path / "old_migrations"
        old.mkdir()
        for name in ("0001_initial.sql", "0002_block_replace.sql"):
            shutil.copy(MIGRATIONS_DIR / name, old / name)
        path = tmp_path / "old.db"
        create_database(path, old)
        conn = connect(path)
        seed_version_two(conn, b"synthetic", layout_id="synthetic_checking_v1")

        migrate(conn)

        assert set(conn.execute(
            """SELECT layout_id, external_id_namespace, external_id_guarantee,
                      pending_in_transaction_basis, pending_in_posting_basis
               FROM document_interpretation"""
        ).fetchall()) == {
            ("synthetic_checking_v1", "synthetic_checking_v1", "stable_unique", 1, 0)
        }
        conn.close()

    def test_the_backfill_gives_an_unknown_layout_no_guarantee(self, tmp_path):
        old = tmp_path / "old_migrations"
        old.mkdir()
        for name in ("0001_initial.sql", "0002_block_replace.sql"):
            shutil.copy(MIGRATIONS_DIR / name, old / name)
        path = tmp_path / "old.db"
        create_database(path, old)
        conn = connect(path)
        seed_version_two(conn, b"synthetic", layout_id="some_other_layout")

        migrate(conn)

        assert set(conn.execute(
            """SELECT external_id_namespace, external_id_guarantee,
                      pending_in_transaction_basis, pending_in_posting_basis
               FROM document_interpretation"""
        ).fetchall()) == {(None, "none", None, None)}
        conn.close()


class TestUpgradeWorkflow:
    def old_ledger(self, tmp_path):
        old = tmp_path / "old_migrations"
        old.mkdir()
        for name in ("0001_initial.sql", "0002_block_replace.sql"):
            shutil.copy(MIGRATIONS_DIR / name, old / name)
        path = tmp_path / "old.db"
        create_database(path, old)
        conn = connect(path)
        seed_version_two(conn, (CARD_HEADER + cafe() + "\n").encode("utf-8"))
        conn.close()
        return path

    def test_migration_changes_schema_and_reconciliation_changes_grouping(self, tmp_path, capsys):
        path = self.old_ledger(tmp_path)
        db = str(path)

        assert main(["totals", "--db", db]) == 2
        assert "migrate --db" in capsys.readouterr().err

        assert main(["migrate", "--db", db]) == 0
        conn = connect(path)
        assert transactions(conn) == 2, "migration must not change grouping"
        assert conn.execute("SELECT COUNT(*) FROM account_reconciliation").fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM transaction_link_history").fetchone() == (0,)
        conn.close()
        capsys.readouterr()

        assert main(["totals", "--db", db]) == 0
        assert "1 accounts have not been reconciled" in capsys.readouterr().out

        assert main(["reconcile", "--db", db]) == 0
        conn = connect(path)
        assert transactions(conn) == 1
        assert is_current(conn, "acct", DEFAULT_RULES)
        conn.close()
        capsys.readouterr()

        assert main(["totals", "--db", db]) == 0
        assert "have not been reconciled" not in capsys.readouterr().out

    @pytest.mark.parametrize(
        "broken",
        [
            "CREATE TABLE half_done (id TEXT) STRICT; INSERT INTO half_done VALUES ('x');"
            "INSERT INTO account (id) VALUES ('missing required columns');",
            "UPDATE ledger_transaction SET amount_cents = 0; SELECT no_such_function();",
        ],
    )
    def test_a_failed_migration_step_leaves_no_trace(self, tmp_path, broken):
        path = self.old_ledger(tmp_path)
        folder = tmp_path / "next_migrations"
        folder.mkdir()
        for migration in load_migrations():
            shutil.copy(migration.path, folder / migration.path.name)
        latest = len(load_migrations())
        conn = connect(path)
        migrate(conn)
        before = dump(conn)
        tables = conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()

        (folder / f"{latest + 1:04d}_broken.sql").write_text(broken, encoding="utf-8")
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)

        assert schema_version(conn) == latest
        assert dump(conn) == before
        assert conn.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall() == tables

        (folder / f"{latest + 1:04d}_broken.sql").write_text(
            "CREATE TABLE repaired (id TEXT) STRICT;", encoding="utf-8"
        )
        assert migrate(conn, folder) == latest + 1
        conn.close()

    def test_a_failed_upgrade_leaves_earlier_steps_applied_and_can_resume(self, tmp_path):
        path = self.old_ledger(tmp_path)
        folder = tmp_path / "next_migrations"
        folder.mkdir()
        migrations = load_migrations()
        shutil.copy(migrations[2].path, folder / migrations[2].path.name)
        for migration in migrations[:2]:
            shutil.copy(migration.path, folder / migration.path.name)
        (folder / "0004_broken.sql").write_text("SELECT no_such_function();", encoding="utf-8")
        conn = connect(path)

        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)

        assert schema_version(conn) == 3
        assert conn.execute("SELECT COUNT(*) FROM document_interpretation").fetchone() == (2,)
        assert migrate(conn) == len(migrations)
        conn.close()


class TestCurrentness:
    """An account is current only with current rules and complete primary sources."""

    content = (CARD_HEADER + cafe() + "\n").encode("utf-8")

    def merged_at_version_three(self, tmp_path):
        """A ledger merged and marked current at version 3, then upgraded through 0004."""
        migrations = load_migrations()
        folders = {}
        for versions in (2, 3):
            folders[versions] = tmp_path / f"migrations_{versions}"
            folders[versions].mkdir()
            for migration in migrations[:versions]:
                shutil.copy(migration.path, folders[versions] / migration.path.name)

        path = tmp_path / "old.db"
        create_database(path, folders[2])
        conn = connect(path)
        seed_version_two(conn, self.content)
        migrate(conn, folders[3])

        conn.execute(
            """UPDATE transaction_source SET transaction_id = 't1', link_rule = 'exact_coverage_pair'
               WHERE transaction_id = 't2'"""
        )
        conn.execute(
            "UPDATE transaction_source SET link_rule = 'exact_coverage_pair' WHERE transaction_id = 't1'"
        )
        conn.execute("DELETE FROM ledger_transaction WHERE id = 't2'")
        conn.execute(
            """INSERT INTO account_reconciliation (account_id, rules_version, rules_fingerprint,
                                                   rules_json)
               VALUES ('acct', 1, ?, ?)""",
            (DEFAULT_RULES.fingerprint(), DEFAULT_RULES.to_json()),
        )
        migrate(conn)
        return path, conn

    def missing_primary(self, conn):
        return conn.execute(
            "SELECT COUNT(*) FROM ledger_transaction WHERE primary_source_record_id IS NULL"
        ).fetchone()[0]

    def repeat(self, conn, tmp_path):
        file = tmp_path / "a.csv"
        file.write_bytes(self.content)
        (result,) = import_files(conn, [file], account_id="acct", layout=SYNTHETIC_CARD_V1)
        return result

    def test_an_upgraded_merge_without_a_primary_source_is_not_current(self, tmp_path):
        _, conn = self.merged_at_version_three(tmp_path)

        assert self.missing_primary(conn) == 1
        assert conn.execute(
            "SELECT rules_fingerprint FROM account_reconciliation"
        ).fetchone() == (DEFAULT_RULES.fingerprint(),)
        assert not is_current(conn, "acct", DEFAULT_RULES)
        assert stale_accounts(conn, DEFAULT_RULES) == ["acct"]
        conn.close()

    def test_totals_discloses_the_stale_account_without_changing_the_database(
        self, tmp_path, capsys
    ):
        path, conn = self.merged_at_version_three(tmp_path)
        conn.close()
        before = path.read_bytes()

        assert main(["totals", "--db", str(path)]) == 0

        out = capsys.readouterr().out
        assert "1 accounts have not been reconciled" in out
        assert "may not record a primary source" in out
        assert path.read_bytes() == before

    def test_a_repeat_import_catches_up_and_the_next_one_is_a_no_op(self, tmp_path):
        _, conn = self.merged_at_version_three(tmp_path)

        first = self.repeat(conn, tmp_path)

        assert (first.outcome, first.reconciled) == ("already_imported", True)
        assert self.missing_primary(conn) == 0
        assert transactions(conn) == 1
        assert is_current(conn, "acct", DEFAULT_RULES)
        settled = dump(conn)

        second = self.repeat(conn, tmp_path)

        assert (second.outcome, second.reconciled) == ("already_imported", False)
        assert dump(conn) == settled
        conn.close()

    def test_the_reconcile_command_also_catches_up(self, tmp_path, capsys):
        path, conn = self.merged_at_version_three(tmp_path)
        conn.close()

        assert main(["reconcile", "--db", str(path)]) == 0
        capsys.readouterr()
        assert main(["totals", "--db", str(path)]) == 0
        assert "have not been reconciled" not in capsys.readouterr().out

    def test_an_already_current_account_stays_current(self, conn, card, tmp_path):
        card("a.csv", cafe(), declared=JANUARY)
        card("b.csv", cafe(), declared=JANUARY)
        assert is_current(conn, "acct", DEFAULT_RULES)
        before = dump(conn)

        (result,) = import_files(
            conn, [tmp_path / "a.csv"], account_id="acct", layout=SYNTHETIC_CARD_V1
        )

        assert result.reconciled is False
        assert is_current(conn, "acct", DEFAULT_RULES)
        assert stale_accounts(conn, DEFAULT_RULES) == []
        assert dump(conn) == before

    def test_different_rules_alone_make_an_account_stale(self, conn, card):
        card("a.csv", cafe())
        other = replace(DEFAULT_RULES, date_window_days=9)
        assert stale_accounts(conn, other) == ["acct"]
        assert stale_accounts(conn, DEFAULT_RULES) == []

    def test_a_missing_marker_alone_makes_an_account_stale(self, conn, card):
        card("a.csv", cafe())
        conn.execute("DELETE FROM account_reconciliation")
        assert stale_accounts(conn, DEFAULT_RULES) == ["acct"]

    def test_an_empty_account_is_never_stale(self, conn, account):
        assert is_current(conn, "acct", DEFAULT_RULES)
        assert stale_accounts(conn, DEFAULT_RULES) == []

    def test_an_account_with_only_unresolved_rows_is_not_permanently_stale(
        self, conn, card, tmp_path
    ):
        card("a.csv", "01/10/2026,SYNTHETIC CAFE,,")
        assert transactions(conn) == 0
        assert stale_accounts(conn, DEFAULT_RULES) == []

        (result,) = import_files(
            conn, [tmp_path / "a.csv"], account_id="acct", layout=SYNTHETIC_CARD_V1
        )
        assert result.reconciled is False

    def test_a_scoped_check_ignores_other_accounts(self, conn, card):
        card("a.csv", cafe(), account_id="other")
        conn.execute("DELETE FROM account_reconciliation")
        assert stale_accounts(conn, DEFAULT_RULES, "acct") == []
        assert stale_accounts(conn, DEFAULT_RULES, "other") == ["other"]


def seed_version_two(conn, content, layout_id="synthetic_card_v1"):
    """Two documents with the same row, as a ledger stood before reconciliation existed."""
    conn.execute(
        "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'credit_card')"
    )
    for suffix, data in (("1", content), ("2", content + b"\n")):
        digest = hashlib.sha256(data).hexdigest()
        document, record, entry = f"d{suffix}", f"r{suffix}", f"t{suffix}"
        conn.execute(
            """INSERT INTO source_document (id, content_sha256, file_name, byte_size, format,
                                            layout_id)
               VALUES (?, ?, 'x.csv', ?, 'csv', ?)""",
            (document, digest, len(data), layout_id),
        )
        conn.execute(
            """INSERT INTO document_coverage (source_document_id, account_id, coverage_kind,
                                              coverage_start, coverage_end, date_basis, evidence)
               VALUES (?, 'acct', 'complete', '2026-01-01', '2026-01-31', 'posting',
                       'user_declared')""",
            (document,),
        )
        conn.execute(
            """INSERT INTO source_record (id, source_document_id, account_id, record_index,
                                          raw_json, raw_fingerprint, occurrence)
               VALUES (?, ?, 'acct', 1, '[]', ?, 1)""",
            (record, document, "f" * 64),
        )
        conn.execute(
            """INSERT INTO record_parse (source_record_id, parser_version, status, posting_date,
                                         amount_cents, description, settlement_status)
               VALUES (?, '1', 'parsed', '2026-01-10', -500, 'SYNTHETIC CAFE', 'posted')""",
            (record,),
        )
        conn.execute(
            """INSERT INTO ledger_transaction (id, account_id, posting_date, amount_cents,
                                               description, settlement_status)
               VALUES (?, 'acct', '2026-01-10', -500, 'SYNTHETIC CAFE', 'posted')""",
            (entry,),
        )
        conn.execute(
            """INSERT INTO transaction_source (transaction_id, source_record_id,
                                               source_document_id, account_id, link_rule)
               VALUES (?, ?, ?, 'acct', 'new_record')""",
            (entry, record, document),
        )


def test_a_failed_reconcile_does_not_mark_the_account_current(conn, card, tmp_path, monkeypatch):
    card("a.csv", cafe())
    conn.execute("DELETE FROM account_reconciliation")
    path = tmp_path / "b.csv"
    path.write_text(CARD_HEADER + cafe() + "\n" + cafe("01/20/2026", "1.00") + "\n", encoding="utf-8")
    monkeypatch.setattr(apply, "_write_marker", lambda *args: (_ for _ in ()).throw(sqlite3.Error()))

    (result,) = import_files(conn, [path], account_id="acct", layout=SYNTHETIC_CARD_V1)

    assert result.outcome == "failed"
    assert conn.execute("SELECT COUNT(*) FROM account_reconciliation").fetchone() == (0,)
