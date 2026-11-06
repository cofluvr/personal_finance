"""Whole-file import behaviour, using only synthetic data."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from personal_finance.db.migrate import connect
from personal_finance.ingest import pipeline
from personal_finance.ingest.coverage import Coverage, declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.reports.totals import account_movement

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "synthetic"

CHECKING_HEADER = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
CARD_HEADER = "Date,Description,Debit,Credit\n"

LEDGER_TABLES = (
    "source_document",
    "document_coverage",
    "source_record",
    "record_parse",
    "ledger_transaction",
    "transaction_source",
    "review_issue",
    "review_issue_subject",
)


def counts(conn):
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in LEDGER_TABLES
    }


def assert_ledger_empty(conn):
    assert set(counts(conn).values()) == {0}


def orphan_transactions(conn):
    return conn.execute(
        """SELECT COUNT(*) FROM ledger_transaction entry
           WHERE NOT EXISTS (SELECT 1 FROM transaction_source link
                             WHERE link.transaction_id = entry.id)"""
    ).fetchone()[0]


@pytest.fixture
def account(conn):
    conn.execute(
        "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'Checking', 'checking')"
    )
    conn.execute(
        "INSERT INTO account (id, display_name, account_type) VALUES ('other', 'Other', 'checking')"
    )
    return "acct"


@pytest.fixture
def write(tmp_path):
    def write_file(name, text):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return write_file


def checking(conn, *paths, account_id="acct", declared=None):
    return import_files(
        conn,
        list(paths),
        account_id=account_id,
        layout=SYNTHETIC_CHECKING_V1,
        declared_coverage=declared,
    )


def card(conn, *paths, account_id="acct", declared=None):
    return import_files(
        conn, list(paths), account_id=account_id, layout=SYNTHETIC_CARD_V1, declared_coverage=declared
    )


def coverage_row(conn):
    return conn.execute(
        """SELECT coverage_kind, coverage_start, coverage_end, date_basis, evidence
           FROM document_coverage"""
    ).fetchone()


class TestSuccessfulImport:
    def test_checking_file(self, conn, account):
        (result,) = checking(conn, FIXTURES / "checking_jan_complete.csv")
        assert result.outcome == "imported"
        assert (result.rows_read, result.transactions_created, result.unresolved_records) == (4, 4, 0)

        movement = account_movement(conn)
        assert movement.inflow_cents == 250000
        assert movement.outflow_cents == 20905
        assert movement.net_cents == 229095
        assert movement.pending_transactions == 1

    def test_card_file(self, conn, account):
        (result,) = card(conn, FIXTURES / "card_jan_no_metadata.csv")
        assert result.transactions_created == 4

        movement = account_movement(conn)
        assert movement.inflow_cents == 3000
        assert movement.outflow_cents == 4300

    def test_identical_purchases_in_one_file_stay_distinct(self, conn, account):
        card(conn, FIXTURES / "card_jan_no_metadata.csv")
        rows = conn.execute(
            "SELECT COUNT(*) FROM ledger_transaction WHERE description = 'SYNTHETIC CAFE'"
        ).fetchone()
        assert rows == (2,)
        assert account_movement(conn).candidate_groups == 0

    def test_a_thousand_dimes_total_exactly(self, conn, account, write):
        rows = "".join(f"01/05/2026,SYNTHETIC DIME,0.10,\n" for _ in range(1000))
        card(conn, write("dimes.csv", CARD_HEADER + rows))
        assert account_movement(conn).outflow_cents == 10000

    def test_a_document_with_no_rows_is_recorded(self, conn, account, write):
        (result,) = card(conn, write("empty.csv", CARD_HEADER))
        assert result.outcome == "imported"
        assert result.rows_read == 0

    def test_failed_rows_do_not_fail_the_file(self, conn, account):
        (result,) = checking(conn, FIXTURES / "checking_problem_rows.csv")
        assert result.outcome == "imported"
        assert (result.rows_read, result.transactions_created, result.unresolved_records) == (6, 2, 4)


class TestMissingInformation:
    @pytest.fixture
    def imported(self, conn, account):
        checking(conn, FIXTURES / "checking_problem_rows.csv")
        return conn

    def test_unresolved_rows_create_no_transactions(self, imported):
        rows = imported.execute(
            "SELECT external_id FROM ledger_transaction ORDER BY external_id"
        ).fetchall()
        assert rows == [("SYN-2004",), ("SYN-2005",)]

    def test_unresolved_rows_are_queued_with_their_reasons(self, imported):
        rows = imported.execute(
            """SELECT record.record_index, parse.reason_code
               FROM record_parse parse
               JOIN source_record record ON record.id = parse.source_record_id
               WHERE parse.status = 'unresolved'
               ORDER BY record.record_index"""
        ).fetchall()
        assert rows == [
            (1, "missing_amount"),
            (2, "missing_date"),
            (3, "invalid_amount"),
            (6, "wrong_column_count"),
        ]

    def test_every_unresolved_row_is_an_open_review_item(self, imported):
        rows = imported.execute(
            """SELECT COUNT(*) FROM review_issue issue
               JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
               WHERE issue.kind = 'unresolved_record' AND issue.status = 'open'
                 AND subject.source_record_id IS NOT NULL"""
        ).fetchone()
        assert rows == (4,)

    def test_the_original_row_of_an_unresolved_record_is_kept(self, imported):
        raw = imported.execute(
            "SELECT raw_json FROM source_record WHERE record_index = 3"
        ).fetchone()[0]
        assert json.loads(raw) == [
            "SYN-2003", "2026-02-03", "2026-02-04", "SYNTHETIC GROCER", "-10.005", "POSTED"
        ]

    def test_a_blank_amount_is_null_not_zero(self, imported):
        row = imported.execute(
            """SELECT parse.amount_cents FROM record_parse parse
               JOIN source_record record ON record.id = parse.source_record_id
               WHERE record.record_index = 1"""
        ).fetchone()
        assert row == (None,)

    def test_zero_stays_zero_and_a_missing_date_stays_missing(self, imported):
        rows = imported.execute(
            """SELECT external_id, amount_cents, posting_date FROM ledger_transaction
               ORDER BY external_id"""
        ).fetchall()
        assert rows == [("SYN-2004", 0, "2026-02-06"), ("SYN-2005", -400, None)]

    def test_totals_disclose_unresolved_rows(self, imported):
        assert account_movement(imported).unresolved_records == 4


class TestCoverageIsNotExtraction:
    TEXT = (
        "# coverage-kind: complete\n# coverage-start: 2026-01-01\n# coverage-end: 2026-01-31\n"
        "# coverage-basis: transaction\n" + CHECKING_HEADER
        + "SYN-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED\n"
        + "SYN-2,2026-01-06,,SYNTHETIC B,,POSTED\n"
    )

    def test_complete_coverage_does_not_hide_unresolved_rows(self, conn, account, write):
        (result,) = checking(conn, write("x.csv", self.TEXT))
        assert result.coverage.kind == "complete"
        assert result.unresolved_records == 1
        assert account_movement(conn).unresolved_records == 1

    def test_complete_coverage_does_not_create_a_transaction_for_a_bad_row(self, conn, account, write):
        checking(conn, write("x.csv", self.TEXT))
        assert conn.execute("SELECT external_id FROM ledger_transaction").fetchall() == [("SYN-1",)]


class TestProvenance:
    def test_every_transaction_traces_to_its_source(self, conn, account):
        checking(conn, FIXTURES / "checking_jan_complete.csv")
        card(conn, FIXTURES / "card_jan_no_metadata.csv", account_id="other")

        assert orphan_transactions(conn) == 0
        rows = conn.execute(
            """SELECT entry.amount_cents, document.file_name, document.content_sha256,
                      record.record_index, record.raw_json, parse.parser_version, parse.amount_cents
               FROM ledger_transaction entry
               JOIN transaction_source link ON link.transaction_id = entry.id
               JOIN source_record record ON record.id = link.source_record_id
               JOIN source_document document ON document.id = record.source_document_id
               JOIN record_parse parse ON parse.source_record_id = record.id"""
        ).fetchall()
        assert len(rows) == 8
        assert all(row[0] == row[6] for row in rows)
        assert all(len(row[2]) == 64 for row in rows)

    def test_row_numbers_lead_back_to_the_original_cells(self, conn, account):
        checking(conn, FIXTURES / "checking_jan_complete.csv")
        row = conn.execute(
            """SELECT record.record_index, record.raw_json FROM ledger_transaction entry
               JOIN transaction_source link ON link.transaction_id = entry.id
               JOIN source_record record ON record.id = link.source_record_id
               WHERE entry.external_id = 'SYN-1002'"""
        ).fetchone()
        assert row[0] == 2
        assert json.loads(row[1]) == [
            "SYN-1002", "2026-01-05", "2026-01-06", "SYNTHETIC GROCER", "-82.15", "POSTED"
        ]

    def test_the_document_hash_matches_the_file(self, conn, account):
        import hashlib

        path = FIXTURES / "checking_jan_complete.csv"
        checking(conn, path)
        row = conn.execute("SELECT content_sha256, byte_size, file_name FROM source_document").fetchone()
        content = path.read_bytes()
        assert row == (hashlib.sha256(content).hexdigest(), len(content), path.name)

    def test_only_the_file_name_is_stored_not_its_folder(self, conn, account, tmp_path):
        folder = tmp_path / "private-folder-name"
        folder.mkdir()
        path = folder / "x.csv"
        path.write_text(CARD_HEADER)
        card(conn, path)
        assert conn.execute("SELECT file_name FROM source_document").fetchone() == ("x.csv",)

    def test_identical_rows_are_distinguished_by_occurrence(self, conn, account):
        card(conn, FIXTURES / "card_jan_no_metadata.csv")
        rows = conn.execute(
            "SELECT record_index, occurrence FROM source_record ORDER BY record_index"
        ).fetchall()
        assert rows == [(1, 1), (2, 2), (3, 1), (4, 1)]


class TestCoverage:
    def test_document_metadata_is_recorded(self, conn, account):
        (result,) = checking(conn, FIXTURES / "checking_jan_complete.csv")
        assert result.coverage.evidence == "document_metadata"
        assert coverage_row(conn) == (
            "complete", "2026-01-01", "2026-01-31", "posting", "document_metadata"
        )
        assert conn.execute("SELECT generated_on FROM source_document").fetchone() == ("2026-02-01",)

    def test_rows_never_become_coverage(self, conn, account):
        card(conn, FIXTURES / "card_jan_no_metadata.csv")
        assert coverage_row(conn) == ("unknown", None, None, None, None)

    def test_a_declaration_is_recorded_as_user_supplied(self, conn, account):
        declared = declare_complete("2026-01-01", "2026-01-31", "posting")
        card(conn, FIXTURES / "card_jan_no_metadata.csv", declared=declared)
        assert coverage_row(conn) == (
            "complete", "2026-01-01", "2026-01-31", "posting", "user_declared"
        )

    def test_a_declaration_may_cover_less_than_the_file(self, conn, account):
        declared = declare_complete("2026-01-05", "2026-01-05", "posting")
        (result,) = card(conn, FIXTURES / "card_jan_no_metadata.csv", declared=declared)
        assert result.transactions_created == 4

    def test_coverage_belongs_to_the_named_account(self, conn, account):
        card(conn, FIXTURES / "card_jan_no_metadata.csv", account_id="other")
        assert conn.execute("SELECT account_id FROM document_coverage").fetchone() == ("other",)

    def test_a_basis_the_layout_lacks_is_refused(self, conn, account):
        declared = declare_complete("2026-01-01", "2026-01-31", "transaction")
        (result,) = card(conn, FIXTURES / "card_jan_no_metadata.csv", declared=declared)
        assert result.failure_code == "coverage_basis_unavailable"
        assert_ledger_empty(conn)

    def test_a_declaration_cannot_replace_what_the_document_states(self, conn, account):
        declared = declare_complete("2026-01-01", "2026-01-15", "posting")
        (result,) = checking(conn, FIXTURES / "checking_jan_complete.csv", declared=declared)
        assert result.failure_code == "coverage_conflict"
        assert_ledger_empty(conn)

    def test_inconsistent_metadata_fails_the_file(self, conn, account, write):
        path = write("bad.csv", "# coverage-kind: complete\n" + CHECKING_HEADER)
        (result,) = checking(conn, path)
        assert result.failure_code == "invalid_coverage_metadata"
        assert_ledger_empty(conn)

    def test_an_invalid_generated_date_fails_the_file(self, conn, account, write):
        path = write("bad.csv", "# generated-on: soon\n" + CHECKING_HEADER)
        (result,) = checking(conn, path)
        assert result.failure_code == "invalid_coverage_metadata"
        assert_ledger_empty(conn)


class TestRepeatedImport:
    def test_identical_file_changes_nothing(self, conn, account):
        path = FIXTURES / "checking_jan_complete.csv"
        checking(conn, path)
        before = counts(conn), account_movement(conn)

        (result,) = checking(conn, path)

        assert result.outcome == "already_imported"
        assert (counts(conn), account_movement(conn)) == before

    def test_problem_rows_are_not_queued_twice(self, conn, account):
        path = FIXTURES / "checking_problem_rows.csv"
        checking(conn, path)
        checking(conn, path)
        assert account_movement(conn).unresolved_records == 4

    def test_identical_content_under_another_name_is_the_same_document(self, conn, account, write):
        path = FIXTURES / "card_jan_no_metadata.csv"
        card(conn, path)
        (result,) = card(conn, write("renamed.csv", path.read_text()))
        assert result.outcome == "already_imported"
        assert counts(conn)["source_document"] == 1

    def test_the_same_file_twice_in_one_run(self, conn, account):
        path = FIXTURES / "card_jan_no_metadata.csv"
        first, second = card(conn, path, path)
        assert (first.outcome, second.outcome) == ("imported", "already_imported")

    def test_each_attempt_is_recorded(self, conn, account):
        path = FIXTURES / "card_jan_no_metadata.csv"
        card(conn, path)
        card(conn, path)
        rows = conn.execute("SELECT outcome FROM import_attempt ORDER BY created_at").fetchall()
        assert rows == [("imported",), ("already_imported",)]

    def test_repeating_with_the_same_declaration_is_accepted(self, conn, account):
        declared = declare_complete("2026-01-01", "2026-01-31", "posting")
        path = FIXTURES / "card_jan_no_metadata.csv"
        card(conn, path, declared=declared)
        (result,) = card(conn, path, declared=declared)
        assert result.outcome == "already_imported"

    @pytest.mark.parametrize(
        "second",
        [
            declare_complete("2026-01-01", "2026-01-15", "posting"),
            Coverage("complete", "2026-01-01", "2026-01-31", "posting", "document_metadata"),
        ],
    )
    def test_a_different_declaration_is_refused(self, conn, account, second):
        path = FIXTURES / "card_jan_no_metadata.csv"
        card(conn, path, declared=declare_complete("2026-01-01", "2026-01-31", "posting"))
        before = counts(conn)

        (result,) = card(conn, path, declared=second)

        assert result.failure_code == "coverage_conflict"
        assert counts(conn) == before

    def test_a_late_declaration_on_unknown_coverage_is_refused(self, conn, account):
        path = FIXTURES / "card_jan_no_metadata.csv"
        card(conn, path)
        (result,) = card(conn, path, declared=declare_complete("2026-01-01", "2026-01-31", "posting"))
        assert result.failure_code == "coverage_conflict"
        assert coverage_row(conn)[0] == "unknown"

    def test_identical_content_for_another_account_is_refused(self, conn, account):
        path = FIXTURES / "card_jan_no_metadata.csv"
        card(conn, path)
        before = counts(conn)
        (result,) = card(conn, path, account_id="other")
        assert result.failure_code == "account_mismatch"
        assert counts(conn) == before

    def test_a_rejected_account_association_preserves_the_existing_import(self, conn, account):
        path = FIXTURES / "card_jan_no_metadata.csv"
        card(conn, path)
        owner_before = account_movement(conn, "acct")

        (result,) = card(conn, path, account_id="other")

        assert result.outcome == "failed"
        assert result.source_document_id is None
        assert account_movement(conn, "acct") == owner_before
        assert account_movement(conn, "other").transactions == 0
        assert conn.execute("SELECT account_id FROM document_coverage").fetchall() == [("acct",)]
        assert conn.execute(
            """SELECT outcome, failure_code, source_document_id FROM import_attempt
               WHERE outcome = 'failed'"""
        ).fetchall() == [("failed", "account_mismatch", None)]
        assert card(conn, path)[0].outcome == "already_imported"

    def test_identical_content_under_another_layout_is_refused(self, conn, account):
        path = FIXTURES / "card_jan_no_metadata.csv"
        card(conn, path)
        (result,) = checking(conn, path)
        assert result.failure_code == "layout_mismatch"


class TestFailedImport:
    def test_wrong_layout_fails_and_leaves_nothing(self, conn, account):
        (result,) = checking(conn, FIXTURES / "card_jan_no_metadata.csv")
        assert (result.outcome, result.failure_code) == ("failed", "header_mismatch")
        assert_ledger_empty(conn)

    def test_missing_file_fails_and_leaves_nothing(self, conn, account, tmp_path):
        (result,) = card(conn, tmp_path / "missing.csv")
        assert result.failure_code == "unreadable_file"
        assert_ledger_empty(conn)

    def test_a_folder_fails_and_leaves_nothing(self, conn, account, tmp_path):
        (result,) = card(conn, tmp_path)
        assert result.failure_code == "unreadable_file"

    def test_undecodable_file_fails(self, conn, account, tmp_path):
        path = tmp_path / "binary.csv"
        path.write_bytes(CARD_HEADER.encode() + b"\xff\xfe\x00\n")
        (result,) = card(conn, path)
        assert result.failure_code == "invalid_encoding"

    def test_failure_is_recorded_with_its_code(self, conn, account):
        checking(conn, FIXTURES / "card_jan_no_metadata.csv")
        row = conn.execute(
            "SELECT outcome, failure_code, source_document_id, content_sha256 FROM import_attempt"
        ).fetchone()
        assert row[:3] == ("failed", "header_mismatch", None)
        assert len(row[3]) == 64

    def test_a_bad_file_does_not_stop_the_others(self, conn, account, write):
        good_one = write("one.csv", CARD_HEADER + "01/05/2026,SYNTHETIC A,1.00,\n")
        bad = write("bad.csv", "not,the,right,header\n")
        good_two = write("two.csv", CARD_HEADER + "01/06/2026,SYNTHETIC B,2.00,\n")

        results = card(conn, good_one, bad, good_two)

        assert [result.outcome for result in results] == ["imported", "failed", "imported"]
        assert account_movement(conn).outflow_cents == 300

    def test_a_failed_file_can_be_imported_after_it_is_fixed(self, conn, account, write):
        path = write("x.csv", "wrong\n")
        assert card(conn, path)[0].outcome == "failed"
        path.write_text(CARD_HEADER + "01/05/2026,SYNTHETIC A,1.00,\n")
        assert card(conn, path)[0].outcome == "imported"

    @pytest.mark.parametrize(
        "target",
        [
            "_insert_record",
            "_insert_parse",
            "_insert_transaction",
            "_link",
            "_insert_candidate_issue",
            "_insert_attempt",
        ],
    )
    def test_a_failure_at_any_step_leaves_no_partial_data(self, conn, account, write, monkeypatch, target):
        rows = "SYN-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED\nSYN-1,2026-01-05,,SYNTHETIC B,-2.00,POSTED\n"
        path = write("x.csv", CHECKING_HEADER + rows)
        original = getattr(pipeline, target)
        calls = []

        def fail_on_last_needed_call(*args):
            calls.append(args)
            if len(calls) == (1 if target in ("_insert_candidate_issue", "_insert_attempt") else 2):
                raise RuntimeError("simulated failure")
            return original(*args)

        monkeypatch.setattr(pipeline, target, fail_on_last_needed_call)

        (result,) = checking(conn, path)

        assert result.failure_code == "internal_error"
        assert_ledger_empty(conn)
        assert not conn.in_transaction
        assert conn.execute("SELECT outcome FROM import_attempt").fetchall() == [("failed",)]

    def test_a_constraint_failure_mid_file_leaves_no_partial_data(self, conn, account, write, monkeypatch):
        path = write("x.csv", CARD_HEADER + "01/05/2026,SYNTHETIC A,1.00,\n01/06/2026,SYNTHETIC B,2.00,\n")
        original = pipeline._link
        calls = []

        def link_to_a_missing_record(conn_, transaction_id, record_id, document_id, account_id):
            calls.append(record_id)
            target = "missing" if len(calls) == 2 else record_id
            return original(conn_, transaction_id, target, document_id, account_id)

        monkeypatch.setattr(pipeline, "_link", link_to_a_missing_record)

        (result,) = card(conn, path)

        assert result.outcome == "failed"
        assert orphan_transactions(conn) == 0
        assert_ledger_empty(conn)

    def test_interrupting_an_import_rolls_back_and_stops(self, conn, account, write, monkeypatch):
        path = write("x.csv", CARD_HEADER + "01/05/2026,SYNTHETIC A,1.00,\n")

        def interrupt(*args):
            raise KeyboardInterrupt

        monkeypatch.setattr(pipeline, "_link", interrupt)
        with pytest.raises(KeyboardInterrupt):
            card(conn, path)
        assert not conn.in_transaction
        assert_ledger_empty(conn)

    def test_a_process_crash_mid_import_leaves_no_partial_data(self, db_path, conn, account, write):
        path = write("x.csv", CARD_HEADER + "01/05/2026,SYNTHETIC A,1.00,\n01/06/2026,SYNTHETIC B,2.00,\n")
        script = """
import os, sys
from pathlib import Path
from personal_finance.db.migrate import connect
from personal_finance.ingest import pipeline
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1

original = pipeline._link
calls = []
def crash_on_second_link(*args):
    calls.append(args)
    if len(calls) == 2:
        os._exit(9)
    return original(*args)
pipeline._link = crash_on_second_link
pipeline.import_files(connect(Path(sys.argv[1])), [Path(sys.argv[2])],
                      account_id="acct", layout=SYNTHETIC_CARD_V1)
"""
        process = subprocess.run(
            [sys.executable, "-c", script, str(db_path), str(path)],
            env={"PYTHONPATH": str(REPO / "src")},
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == 9, process.stderr

        assert_ledger_empty(conn)
        assert orphan_transactions(conn) == 0
        (result,) = card(conn, path)
        assert result.outcome == "imported"
        assert account_movement(conn).outflow_cents == 300


class TestRepresentationsWithinADocument:
    def test_a_repeated_external_id_stays_visible_and_counted(self, conn, account, write):
        rows = "SYN-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED\nSYN-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED\n"
        (result,) = checking(conn, write("x.csv", CHECKING_HEADER + rows))

        assert result.candidate_groups == 1
        movement = account_movement(conn)
        assert movement.transactions == 2
        assert movement.outflow_cents == 200
        assert (movement.candidate_groups, movement.transactions_in_candidate_groups) == (1, 2)

    def test_pending_and_posted_versions_stay_visible_and_counted(self, conn, account, write):
        rows = (
            "SYN-1,2026-01-05,,SYNTHETIC CAFE,-6.50,PENDING\n"
            "SYN-2,2026-01-05,2026-01-06,SYNTHETIC CAFE,-6.50,POSTED\n"
        )
        checking(conn, write("x.csv", CHECKING_HEADER + rows))

        rule = conn.execute("SELECT rule FROM review_issue").fetchone()
        assert rule == ("same_document_pending_posted",)
        assert account_movement(conn).transactions == 2

    def test_records_keep_their_own_status_for_later_reconciliation(self, conn, account, write):
        rows = (
            "SYN-1,2026-01-05,,SYNTHETIC CAFE,-6.50,PENDING\n"
            "SYN-2,2026-01-05,2026-01-06,SYNTHETIC CAFE,-6.50,POSTED\n"
        )
        checking(conn, write("x.csv", CHECKING_HEADER + rows))
        statuses = conn.execute(
            "SELECT settlement_status FROM record_parse ORDER BY settlement_status"
        ).fetchall()
        assert statuses == [("pending",), ("posted",)]


class TestConcurrentImports:
    def run_cli(self, db_path, layout, path):
        return subprocess.Popen(
            [sys.executable, "-m", "personal_finance", "import", "--db", str(db_path),
             "--account", "Checking", "--layout", layout, str(path)],
            env={"PYTHONPATH": str(REPO / "src")},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_simultaneous_imports_count_each_file_once(self, db_path, conn, account):
        one = FIXTURES / "checking_jan_complete.csv"
        two = FIXTURES / "card_jan_no_metadata.csv"
        workers = [
            self.run_cli(db_path, layout, path)
            for layout, path in [("synthetic_checking_v1", one), ("synthetic_card_v1", two)] * 4
        ]
        outcomes = [worker.communicate(timeout=60) + (worker.returncode,) for worker in workers]

        assert [code for _, _, code in outcomes] == [0] * 8, outcomes
        assert counts(conn)["source_document"] == 2
        assert counts(conn)["ledger_transaction"] == 8
        assert orphan_transactions(conn) == 0
        attempts = dict(
            conn.execute("SELECT outcome, COUNT(*) FROM import_attempt GROUP BY outcome").fetchall()
        )
        assert attempts == {"imported": 2, "already_imported": 6}
        movement = account_movement(conn)
        assert movement.inflow_cents == 253000
        assert movement.outflow_cents == 25205

    def test_an_import_blocked_by_another_writer_reports_busy(self, db_path, conn, account):
        path = FIXTURES / "card_jan_no_metadata.csv"
        blocked = connect(db_path)
        blocked.execute("PRAGMA busy_timeout = 50")
        run_id = "run"
        blocked.execute("INSERT INTO import_run (id) VALUES (?)", (run_id,))
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = pipeline._import_file(
                blocked, run_id, path, "acct", SYNTHETIC_CARD_V1, None
            )
        finally:
            conn.execute("ROLLBACK")
        blocked.close()

        assert result.failure_code == "database_busy"
        assert_ledger_empty(conn)

    def test_the_write_lock_is_held_before_checking_for_the_document(
        self, db_path, conn, account, monkeypatch
    ):
        """Otherwise two imports could both decide the file is new."""
        other = connect(db_path)
        other.execute("PRAGMA busy_timeout = 0")
        refused = []
        original = pipeline._import_content

        def try_to_write_from_elsewhere(*args):
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("BEGIN IMMEDIATE")
            refused.append(True)
            return original(*args)

        monkeypatch.setattr(pipeline, "_import_content", try_to_write_from_elsewhere)
        card(conn, FIXTURES / "card_jan_no_metadata.csv")
        other.close()
        assert refused == [True]


class TestDisclosureCounts:
    def resolve_all(self, conn):
        conn.execute(
            """UPDATE review_issue SET status = 'resolved',
                                       resolved_at = '2026-02-01T00:00:00.000Z'"""
        )

    def test_resolved_unresolved_records_are_no_longer_disclosed(self, conn, account):
        checking(conn, FIXTURES / "checking_problem_rows.csv")
        self.resolve_all(conn)
        assert account_movement(conn).unresolved_records == 0

    def test_resolved_candidate_groups_are_no_longer_disclosed(self, conn, account, write):
        rows = "SYN-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED\nSYN-1,2026-01-05,,SYNTHETIC A,-1.00,POSTED\n"
        checking(conn, write("x.csv", CHECKING_HEADER + rows))
        self.resolve_all(conn)
        movement = account_movement(conn)
        assert (movement.candidate_groups, movement.transactions_in_candidate_groups) == (0, 0)

    def test_counts_follow_the_requested_account(self, conn, account):
        checking(conn, FIXTURES / "checking_problem_rows.csv")
        assert account_movement(conn, "acct").unresolved_records == 4
        assert account_movement(conn, "other").unresolved_records == 0
