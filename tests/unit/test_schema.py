"""The database itself enforces the rules that protect the ledger."""

import json
import sqlite3

import pytest

SHA_A = "a" * 64
SHA_B = "b" * 64


def add_account(conn, account_id="acct-1", name="Synthetic Checking"):
    conn.execute(
        "INSERT INTO account (id, display_name, account_type) VALUES (?, ?, 'checking')",
        (account_id, name),
    )
    return account_id


def add_document(conn, document_id="doc-1", sha=SHA_A):
    conn.execute(
        """INSERT INTO source_document (id, content_sha256, file_name, byte_size, format, layout_id)
           VALUES (?, ?, 'synthetic.csv', 10, 'csv', 'synthetic_checking_v1')""",
        (document_id, sha),
    )
    return document_id


def add_record(conn, record_id, document_id, account_id, index=1, occurrence=1):
    conn.execute(
        """INSERT INTO source_record (id, source_document_id, account_id, record_index,
                                      raw_json, raw_fingerprint, occurrence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (record_id, document_id, account_id, index, json.dumps(["2026-01-05", "-1.00"]),
         "f" * 64, occurrence),
    )
    return record_id


def add_transaction(conn, transaction_id, account_id, amount=-100, date="2026-01-05"):
    conn.execute(
        """INSERT INTO ledger_transaction (id, account_id, posting_date, amount_cents)
           VALUES (?, ?, ?, ?)""",
        (transaction_id, account_id, date, amount),
    )
    return transaction_id


def link(conn, transaction_id, record_id, document_id, account_id):
    conn.execute(
        """INSERT INTO transaction_source (transaction_id, source_record_id,
                                           source_document_id, account_id, link_rule)
           VALUES (?, ?, ?, ?, 'test')""",
        (transaction_id, record_id, document_id, account_id),
    )


def add_coverage(conn, document_id, account_id, kind, start=None, end=None, basis=None, evidence=None):
    conn.execute(
        """INSERT INTO document_coverage (source_document_id, account_id, coverage_kind,
                                          coverage_start, coverage_end, date_basis, evidence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (document_id, account_id, kind, start, end, basis, evidence),
    )


@pytest.fixture
def ledger(conn):
    """One account, one document and one record, ready for linking."""
    account = add_account(conn)
    document = add_document(conn)
    add_record(conn, "rec-1", document, account)
    return conn


class TestAmounts:
    @pytest.mark.parametrize("value", [12.5, "12.34", "abc", None])
    def test_only_integer_cents_are_stored(self, ledger, value):
        with pytest.raises(sqlite3.IntegrityError):
            add_transaction(ledger, "txn-1", "acct-1", amount=value)

    def test_zero_is_a_valid_amount(self, ledger):
        add_transaction(ledger, "txn-1", "acct-1", amount=0)
        row = ledger.execute("SELECT amount_cents FROM ledger_transaction").fetchone()
        assert row == (0,)

    def test_large_sums_stay_exact(self, ledger):
        for number in range(1000):
            add_transaction(ledger, f"txn-{number}", "acct-1", amount=10)
        total = ledger.execute("SELECT SUM(amount_cents) FROM ledger_transaction").fetchone()[0]
        assert isinstance(total, int)
        assert total == 10_000

    def test_only_usd_is_accepted(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            ledger.execute(
                """INSERT INTO ledger_transaction (id, account_id, posting_date, amount_cents, currency)
                   VALUES ('txn-1', 'acct-1', '2026-01-05', 1, 'EUR')"""
            )


class TestDates:
    @pytest.mark.parametrize(
        "value", ["2026-02-30", "2026-13-01", "01/05/2026", "2026-1-5", "2026-01-05T10:00:00", ""]
    )
    def test_invalid_dates_are_rejected(self, ledger, value):
        with pytest.raises(sqlite3.IntegrityError):
            add_transaction(ledger, "txn-1", "acct-1", date=value)

    def test_leap_day_is_accepted(self, ledger):
        add_transaction(ledger, "txn-1", "acct-1", date="2028-02-29")

    def test_a_transaction_needs_at_least_one_date(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            add_transaction(ledger, "txn-1", "acct-1", date=None)

    def test_one_missing_date_stays_missing(self, ledger):
        add_transaction(ledger, "txn-1", "acct-1")
        row = ledger.execute("SELECT transaction_date FROM ledger_transaction").fetchone()
        assert row == (None,)


class TestRecordParse:
    def insert(self, conn, status, **values):
        columns = {"source_record_id": "rec-1", "parser_version": "v1", "status": status, **values}
        names = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        conn.execute(f"INSERT INTO record_parse ({names}) VALUES ({marks})", list(columns.values()))

    def test_parsed_record_needs_an_amount(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            self.insert(ledger, "parsed", posting_date="2026-01-05")

    def test_parsed_record_needs_a_date(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            self.insert(ledger, "parsed", amount_cents=100)

    def test_unresolved_record_needs_a_reason(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            self.insert(ledger, "unresolved")

    def test_parsed_record_cannot_carry_a_reason(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            self.insert(ledger, "parsed", amount_cents=1, posting_date="2026-01-05",
                        reason_code="missing_amount")

    def test_unresolved_record_keeps_missing_values_missing(self, ledger):
        self.insert(ledger, "unresolved", reason_code="missing_amount", posting_date="2026-01-05")
        row = ledger.execute("SELECT amount_cents FROM record_parse").fetchone()
        assert row == (None,)

    def test_a_new_parser_version_adds_a_row(self, ledger):
        self.insert(ledger, "unresolved", reason_code="missing_amount")
        self.insert(ledger, "parsed", parser_version="v2", amount_cents=1, posting_date="2026-01-05")
        assert ledger.execute("SELECT COUNT(*) FROM record_parse").fetchone() == (2,)

    def test_settlement_status_defaults_to_unknown_not_posted(self, ledger):
        self.insert(ledger, "parsed", amount_cents=1, posting_date="2026-01-05")
        row = ledger.execute("SELECT settlement_status FROM record_parse").fetchone()
        assert row == ("unknown",)


class TestCoverage:
    def test_complete_coverage_with_all_evidence(self, ledger):
        add_coverage(ledger, "doc-1", "acct-1", "complete", "2026-01-01", "2026-01-31",
                     "posting", "document_metadata")

    @pytest.mark.parametrize(
        ("start", "end", "basis", "evidence"),
        [
            (None, "2026-01-31", "posting", "document_metadata"),
            ("2026-01-01", None, "posting", "document_metadata"),
            ("2026-01-01", "2026-01-31", None, "document_metadata"),
            ("2026-01-01", "2026-01-31", "posting", None),
        ],
    )
    def test_complete_coverage_needs_every_field(self, ledger, start, end, basis, evidence):
        with pytest.raises(sqlite3.IntegrityError):
            add_coverage(ledger, "doc-1", "acct-1", "complete", start, end, basis, evidence)

    def test_unknown_coverage_cannot_claim_dates(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            add_coverage(ledger, "doc-1", "acct-1", "unknown", "2026-01-01", "2026-01-31")

    def test_inferred_is_not_an_accepted_evidence_type(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            add_coverage(ledger, "doc-1", "acct-1", "complete", "2026-01-01", "2026-01-31",
                         "posting", "inferred_from_rows")

    def test_coverage_cannot_end_before_it_starts(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            add_coverage(ledger, "doc-1", "acct-1", "complete", "2026-02-01", "2026-01-31",
                         "posting", "user_declared")

    def test_partial_coverage_may_have_only_a_start(self, ledger):
        add_coverage(ledger, "doc-1", "acct-1", "partial", start="2026-01-01")

    def test_coverage_is_recorded_per_account(self, ledger):
        add_account(ledger, "acct-2", "Synthetic Savings")
        add_coverage(ledger, "doc-1", "acct-1", "unknown")
        add_coverage(ledger, "doc-1", "acct-2", "partial", start="2026-01-01")
        assert ledger.execute("SELECT COUNT(*) FROM document_coverage").fetchone() == (2,)


class TestProvenanceLinks:
    def test_one_transaction_can_hold_records_from_different_documents(self, ledger):
        add_document(ledger, "doc-2", SHA_B)
        add_record(ledger, "rec-2", "doc-2", "acct-1")
        add_transaction(ledger, "txn-1", "acct-1")
        link(ledger, "txn-1", "rec-1", "doc-1", "acct-1")
        link(ledger, "txn-1", "rec-2", "doc-2", "acct-1")

    def test_one_record_per_document_per_transaction(self, ledger):
        add_record(ledger, "rec-2", "doc-1", "acct-1", index=2, occurrence=2)
        add_transaction(ledger, "txn-1", "acct-1")
        link(ledger, "txn-1", "rec-1", "doc-1", "acct-1")
        with pytest.raises(sqlite3.IntegrityError):
            link(ledger, "txn-1", "rec-2", "doc-1", "acct-1")

    def test_identical_rows_in_one_document_can_be_two_transactions(self, ledger):
        add_record(ledger, "rec-2", "doc-1", "acct-1", index=2, occurrence=2)
        add_transaction(ledger, "txn-1", "acct-1")
        add_transaction(ledger, "txn-2", "acct-1")
        link(ledger, "txn-1", "rec-1", "doc-1", "acct-1")
        link(ledger, "txn-2", "rec-2", "doc-1", "acct-1")

    def test_a_record_supports_only_one_transaction(self, ledger):
        add_transaction(ledger, "txn-1", "acct-1")
        add_transaction(ledger, "txn-2", "acct-1")
        link(ledger, "txn-1", "rec-1", "doc-1", "acct-1")
        with pytest.raises(sqlite3.IntegrityError):
            link(ledger, "txn-2", "rec-1", "doc-1", "acct-1")

    def test_a_link_cannot_cross_accounts(self, ledger):
        add_account(ledger, "acct-2", "Synthetic Savings")
        add_transaction(ledger, "txn-1", "acct-2")
        with pytest.raises(sqlite3.IntegrityError):
            link(ledger, "txn-1", "rec-1", "doc-1", "acct-2")
        with pytest.raises(sqlite3.IntegrityError):
            link(ledger, "txn-1", "rec-1", "doc-1", "acct-1")

    def test_a_link_cannot_misstate_its_document(self, ledger):
        add_document(ledger, "doc-2", SHA_B)
        add_transaction(ledger, "txn-1", "acct-1")
        with pytest.raises(sqlite3.IntegrityError):
            link(ledger, "txn-1", "rec-1", "doc-2", "acct-1")

    def test_a_record_with_no_known_account_cannot_be_linked(self, ledger):
        add_record(ledger, "rec-2", "doc-1", None, index=2, occurrence=2)
        add_transaction(ledger, "txn-1", "acct-1")
        with pytest.raises(sqlite3.IntegrityError):
            link(ledger, "txn-1", "rec-2", "doc-1", "acct-1")

    def test_linked_transaction_cannot_be_deleted(self, ledger):
        add_transaction(ledger, "txn-1", "acct-1")
        link(ledger, "txn-1", "rec-1", "doc-1", "acct-1")
        with pytest.raises(sqlite3.IntegrityError):
            ledger.execute("DELETE FROM ledger_transaction WHERE id = 'txn-1'")

    def test_same_external_id_can_exist_twice_for_review(self, ledger):
        for transaction_id, amount in (("txn-1", 100), ("txn-2", 200)):
            ledger.execute(
                """INSERT INTO ledger_transaction (id, account_id, external_id, posting_date, amount_cents)
                   VALUES (?, 'acct-1', 'SYN-1', '2026-01-05', ?)""",
                (transaction_id, amount),
            )


class TestDocuments:
    def test_identical_content_is_one_document(self, ledger):
        with pytest.raises(sqlite3.IntegrityError):
            add_document(ledger, "doc-2", SHA_A)

    def test_institution_and_last4_need_not_be_unique(self, conn):
        for account_id in ("acct-1", "acct-2"):
            conn.execute(
                """INSERT INTO account (id, display_name, institution, account_type, last4)
                   VALUES (?, ?, 'Synthetic Bank', 'checking', '1234')""",
                (account_id, account_id),
            )

    def test_failed_attempt_needs_a_failure_code(self, conn):
        conn.execute("INSERT INTO import_run (id) VALUES ('run-1')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO import_attempt (id, import_run_id, file_name, outcome)
                   VALUES ('att-1', 'run-1', 'x.csv', 'failed')"""
            )

    def test_failed_attempt_needs_no_document(self, conn):
        conn.execute("INSERT INTO import_run (id) VALUES ('run-1')")
        conn.execute(
            """INSERT INTO import_attempt (id, import_run_id, file_name, outcome, failure_code)
               VALUES ('att-1', 'run-1', 'x.csv', 'failed', 'unreadable_file')"""
        )


class TestImmutability:
    @pytest.mark.parametrize(
        "statement",
        [
            "UPDATE source_document SET file_name = 'changed.csv'",
            "DELETE FROM source_document",
            "UPDATE source_record SET raw_json = '[]'",
            "DELETE FROM source_record",
            "UPDATE record_parse SET amount_cents = 2",
            "DELETE FROM record_parse",
            "UPDATE document_coverage SET coverage_kind = 'partial'",
            "DELETE FROM document_coverage",
            "UPDATE account SET id = 'other'",
            "UPDATE ledger_transaction SET id = 'other'",
            "UPDATE ledger_transaction SET account_id = 'other'",
        ],
    )
    def test_protected_data_cannot_be_changed(self, ledger, statement):
        add_coverage(ledger, "doc-1", "acct-1", "unknown")
        add_transaction(ledger, "txn-1", "acct-1")
        ledger.execute(
            """INSERT INTO record_parse (source_record_id, parser_version, status,
                                         amount_cents, posting_date)
               VALUES ('rec-1', 'v1', 'parsed', 1, '2026-01-05')"""
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable|append-only"):
            ledger.execute(statement)

    def test_account_details_can_still_be_edited(self, ledger):
        ledger.execute("UPDATE account SET display_name = 'Renamed' WHERE id = 'acct-1'")


class TestReviewIssues:
    def add_issue(self, conn, issue_id="issue-1"):
        conn.execute(
            """INSERT INTO review_issue (id, kind, rule) VALUES (?, 'possible_duplicate', 'test')""",
            (issue_id,),
        )

    def test_issue_can_cover_a_whole_group(self, ledger):
        self.add_issue(ledger)
        for number in range(5):
            add_transaction(ledger, f"txn-{number}", "acct-1")
            ledger.execute(
                """INSERT INTO review_issue_subject (review_issue_id, transaction_id)
                   VALUES ('issue-1', ?)""",
                (f"txn-{number}",),
            )
        assert ledger.execute("SELECT COUNT(*) FROM review_issue_subject").fetchone() == (5,)

    def test_a_subject_is_exactly_one_of_transaction_or_record(self, ledger):
        self.add_issue(ledger)
        add_transaction(ledger, "txn-1", "acct-1")
        with pytest.raises(sqlite3.IntegrityError):
            ledger.execute(
                """INSERT INTO review_issue_subject (review_issue_id, transaction_id, source_record_id)
                   VALUES ('issue-1', 'txn-1', 'rec-1')"""
            )
        with pytest.raises(sqlite3.IntegrityError):
            ledger.execute("INSERT INTO review_issue_subject (review_issue_id) VALUES ('issue-1')")

    def test_new_issues_start_open(self, ledger):
        self.add_issue(ledger)
        assert ledger.execute("SELECT status FROM review_issue").fetchone() == ("open",)

    def test_resolved_issue_needs_a_resolution_time(self, ledger):
        self.add_issue(ledger)
        with pytest.raises(sqlite3.IntegrityError):
            ledger.execute("UPDATE review_issue SET status = 'resolved'")
