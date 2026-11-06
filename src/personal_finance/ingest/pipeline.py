"""Imports files into the ledger, one database transaction per file.

The write lock is held from the duplicate check to the commit, so concurrent
imports of one file cannot both succeed, and a failure leaves nothing behind.
Slice 3 adds cross-document matching. Until then every new row is a new
transaction.
"""

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from personal_finance.ingest import coverage as coverage_rules
from personal_finance.ingest.coverage import Coverage
from personal_finance.ingest.csv_reader import RawRecord, read_document
from personal_finance.ingest.errors import ImportFailure
from personal_finance.ingest.layouts import Layout, ParsedRow
from personal_finance.reconcile.same_document import find_candidate_groups


@dataclass(frozen=True)
class FileResult:
    file_name: str
    outcome: str
    failure_code: str | None = None
    source_document_id: str | None = None
    coverage: Coverage | None = None
    rows_read: int = 0
    transactions_created: int = 0
    unresolved_records: int = 0
    candidate_groups: int = 0


def _new_id() -> str:
    return str(uuid.uuid4())


def import_files(
    conn: sqlite3.Connection,
    paths: list[Path],
    *,
    account_id: str,
    layout: Layout,
    declared_coverage: Coverage | None = None,
) -> list[FileResult]:
    """Import each file independently. One failure never stops the others."""
    run_id = _new_id()
    conn.execute("INSERT INTO import_run (id) VALUES (?)", (run_id,))
    results = [
        _import_file(conn, run_id, path, account_id, layout, declared_coverage) for path in paths
    ]
    _write_if_possible(
        conn,
        "UPDATE import_run SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (run_id,),
    )
    return results


def _import_file(conn, run_id, path, account_id, layout, declared) -> FileResult:
    digest = None
    try:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        conn.execute("BEGIN IMMEDIATE")
        result = _import_content(
            conn, run_id, path.name, content, digest, account_id, layout, declared
        )
        conn.execute("COMMIT")
        return result
    except ImportFailure as failure:
        code = failure.code
    except OSError:
        code = "unreadable_file"
    except sqlite3.OperationalError as error:
        code = "database_busy" if "locked" in str(error) else "internal_error"
    except Exception:
        code = "internal_error"
    except BaseException:
        _rollback(conn)
        raise

    _rollback(conn)
    _write_if_possible(
        conn,
        """INSERT INTO import_attempt (id, import_run_id, file_name, content_sha256,
                                       outcome, failure_code)
           VALUES (?, ?, ?, ?, 'failed', ?)""",
        (_new_id(), run_id, path.name, digest, code),
    )
    return FileResult(path.name, "failed", failure_code=code)


def _rollback(conn) -> None:
    if conn.in_transaction:
        conn.execute("ROLLBACK")


def _write_if_possible(conn, statement, parameters) -> None:
    """Record bookkeeping unless the database is too busy. The caller still reports."""
    try:
        conn.execute(statement, parameters)
    except sqlite3.OperationalError:
        pass


def _import_content(conn, run_id, name, content, digest, account_id, layout, declared) -> FileResult:
    existing = conn.execute(
        "SELECT id, layout_id FROM source_document WHERE content_sha256 = ?", (digest,)
    ).fetchone()
    if existing is not None:
        return _repeat_import(conn, run_id, name, digest, existing, account_id, layout, declared)

    metadata, records = read_document(content, layout)
    coverage = _resolve_coverage(metadata, layout, declared)
    generated_on = _generated_on(metadata)

    document_id = _new_id()
    conn.execute(
        """INSERT INTO source_document (id, content_sha256, file_name, byte_size, format,
                                        layout_id, generated_on)
           VALUES (?, ?, ?, ?, 'csv', ?, ?)""",
        (document_id, digest, name, len(content), layout.layout_id, generated_on),
    )
    conn.execute(
        """INSERT INTO document_coverage (source_document_id, account_id, coverage_kind,
                                          coverage_start, coverage_end, date_basis, evidence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (document_id, account_id, coverage.kind, coverage.start, coverage.end,
         coverage.date_basis, coverage.evidence),
    )

    transactions = []
    unresolved = 0
    for record in records:
        record_id = _insert_record(conn, document_id, account_id, record)
        parsed = _parse(record, layout)
        _insert_parse(conn, record_id, layout, parsed)
        if parsed.reason_code is None:
            transaction_id = _insert_transaction(conn, account_id, parsed)
            _link(conn, transaction_id, record_id, document_id, account_id)
            transactions.append((transaction_id, parsed))
        else:
            _insert_unresolved_issue(conn, record_id, parsed.reason_code)
            unresolved += 1

    groups = find_candidate_groups(transactions)
    for rule, members in groups:
        _insert_candidate_issue(conn, document_id, rule, members)

    _insert_attempt(conn, run_id, name, digest, "imported", document_id)
    return FileResult(
        name,
        "imported",
        source_document_id=document_id,
        coverage=coverage,
        rows_read=len(records),
        transactions_created=len(transactions),
        unresolved_records=unresolved,
        candidate_groups=len(groups),
    )


def _repeat_import(conn, run_id, name, digest, existing, account_id, layout, declared) -> FileResult:
    document_id, layout_id = existing
    if layout_id != layout.layout_id:
        raise ImportFailure("layout_mismatch")

    row = conn.execute(
        """SELECT coverage_kind, coverage_start, coverage_end, date_basis, evidence
           FROM document_coverage WHERE source_document_id = ? AND account_id = ?""",
        (document_id, account_id),
    ).fetchone()
    if row is None:
        raise ImportFailure("account_mismatch")

    stored = Coverage(*row)
    if declared is not None and declared != stored:
        raise ImportFailure("coverage_conflict")

    _insert_attempt(conn, run_id, name, digest, "already_imported", document_id)
    return FileResult(name, "already_imported", source_document_id=document_id, coverage=stored)


def _resolve_coverage(metadata, layout, declared) -> Coverage:
    stated = coverage_rules.from_metadata(metadata)
    if declared is not None and stated != coverage_rules.UNKNOWN:
        raise ImportFailure("coverage_conflict")

    coverage = declared or stated
    if coverage.date_basis and coverage.date_basis not in layout.pending_in_complete_coverage:
        raise ImportFailure("coverage_basis_unavailable")
    return coverage


def _generated_on(metadata) -> str | None:
    text = metadata.get("generated-on")
    if text is None:
        return None
    try:
        return coverage_rules.parse_iso_date(text)
    except ValueError:
        raise ImportFailure("invalid_coverage_metadata") from None


def _parse(record: RawRecord, layout: Layout) -> ParsedRow:
    if len(record.cells) != len(layout.columns):
        return ParsedRow("wrong_column_count")
    return layout.parse_row(dict(zip(layout.columns, record.cells)))


def _insert_record(conn, document_id, account_id, record: RawRecord) -> str:
    record_id = _new_id()
    conn.execute(
        """INSERT INTO source_record (id, source_document_id, account_id, record_index,
                                      raw_json, raw_fingerprint, occurrence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (record_id, document_id, account_id, record.index, record.raw_json,
         record.fingerprint, record.occurrence),
    )
    return record_id


def _insert_parse(conn, record_id, layout, parsed: ParsedRow) -> None:
    conn.execute(
        """INSERT INTO record_parse (source_record_id, parser_version, status, reason_code,
                                     transaction_date, posting_date, amount_cents, description,
                                     external_id, settlement_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (record_id, layout.parser_version, "unresolved" if parsed.reason_code else "parsed",
         parsed.reason_code, parsed.transaction_date, parsed.posting_date, parsed.amount_cents,
         parsed.description, parsed.external_id, parsed.settlement_status),
    )


def _insert_transaction(conn, account_id, parsed: ParsedRow) -> str:
    transaction_id = _new_id()
    conn.execute(
        """INSERT INTO ledger_transaction (id, account_id, external_id, transaction_date,
                                           posting_date, amount_cents, description,
                                           settlement_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (transaction_id, account_id, parsed.external_id, parsed.transaction_date,
         parsed.posting_date, parsed.amount_cents, parsed.description, parsed.settlement_status),
    )
    return transaction_id


def _link(conn, transaction_id, record_id, document_id, account_id) -> None:
    conn.execute(
        """INSERT INTO transaction_source (transaction_id, source_record_id, source_document_id,
                                           account_id, link_rule)
           VALUES (?, ?, ?, ?, 'new_record')""",
        (transaction_id, record_id, document_id, account_id),
    )


def _insert_unresolved_issue(conn, record_id, reason_code) -> None:
    issue_id = _new_id()
    conn.execute(
        "INSERT INTO review_issue (id, kind, rule) VALUES (?, 'unresolved_record', ?)",
        (issue_id, reason_code),
    )
    conn.execute(
        "INSERT INTO review_issue_subject (review_issue_id, source_record_id) VALUES (?, ?)",
        (issue_id, record_id),
    )


def _insert_candidate_issue(conn, document_id, rule, members) -> None:
    issue_id = _new_id()
    conn.execute(
        """INSERT INTO review_issue (id, kind, rule, evidence_json)
           VALUES (?, 'possible_duplicate', ?, ?)""",
        (issue_id, rule, json.dumps({"source_document_id": document_id})),
    )
    conn.executemany(
        "INSERT INTO review_issue_subject (review_issue_id, transaction_id) VALUES (?, ?)",
        [(issue_id, member) for member in members],
    )


def _insert_attempt(conn, run_id, name, digest, outcome, document_id) -> None:
    conn.execute(
        """INSERT INTO import_attempt (id, import_run_id, file_name, content_sha256,
                                       outcome, source_document_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (_new_id(), run_id, name, digest, outcome, document_id),
    )
