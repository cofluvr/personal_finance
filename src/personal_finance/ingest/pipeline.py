"""Imports files into the ledger, one database transaction per file.

The write lock is held from the duplicate check to the commit, so concurrent
imports of one file cannot both succeed, and a failure leaves nothing behind. Each
row first becomes its own transaction, then the account is reconciled inside the
same database transaction. A real ledger also archives each new document's original, as the last
step before the commit, so no document is kept without it (D-058 point 5).
"""

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from personal_finance.db.originals import archive_original
from personal_finance.ingest import coverage as coverage_rules
from personal_finance.ingest.coverage import Coverage
from personal_finance.ingest.csv_reader import RawRecord, read_document
from personal_finance.ingest.errors import ImportFailure
from personal_finance.ingest.layouts import Layout, ParsedRow
from personal_finance.ingest.pdf_documents import read_pdf_document
from personal_finance.reconcile.apply import declared_coverage, is_current, reconcile_account
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.same_document import find_candidate_groups
from personal_finance.reports.import_summary import consolidated_records, final_transactions


@dataclass(frozen=True)
class FileResult:
    """One file's outcome, with counts as of its import (D-036).

    A count that does not apply to the outcome is None, never zero. rows_attempted is
    only for a failed file that was parsed and then rolled back.
    """

    file_name: str
    outcome: str
    failure_code: str | None = None
    source_document_id: str | None = None
    coverage: Coverage | None = None
    rows_read: int | None = None
    rows_attempted: int | None = None
    valid_records: int | None = None
    unresolved_records: int | None = None
    final_transactions: int | None = None
    consolidated_records: int | None = None
    open_review_groups: int | None = None
    net_transactions: int | None = None
    memberships_changed: int | None = None
    reconciled: bool = False


@dataclass
class _Progress:
    """What survives a rollback, so a failure can say how far the file got."""

    rows_attempted: int | None = None


def _new_id() -> str:
    return str(uuid.uuid4())


def import_files(
    conn: sqlite3.Connection,
    paths: list[Path],
    *,
    account_id: str,
    layout: Layout,
    declared_coverage: Coverage | None = None,
    rules: MatchingRules = DEFAULT_RULES,
    originals_folder: Path | None = None,
) -> list[FileResult]:
    """Import each file independently. One failure never stops the others. Given an originals
    folder, each new document's bytes are archived there before its import commits."""
    run_id = _new_id()
    conn.execute("INSERT INTO import_run (id) VALUES (?)", (run_id,))
    results = [
        _import_file(conn, run_id, path, account_id, layout, declared_coverage, rules,
                     originals_folder)
        for path in paths
    ]
    _write_if_possible(
        conn,
        "UPDATE import_run SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (run_id,),
    )
    return results


def _import_file(
    conn, run_id, path, account_id, layout, declared, rules=DEFAULT_RULES, originals_folder=None
) -> FileResult:
    digest = None
    progress = _Progress()
    try:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        conn.execute("BEGIN IMMEDIATE")
        before = _live_transactions(conn, account_id)
        result = _import_content(
            conn, run_id, path.name, content, digest, account_id, layout, declared, rules, progress
        )
        result = replace(result, net_transactions=_live_transactions(conn, account_id) - before)
        if originals_folder is not None and result.outcome == "imported":
            archive_original(originals_folder, content, digest)
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
    return FileResult(
        path.name, "failed", failure_code=code, rows_attempted=progress.rows_attempted
    )


def _rollback(conn) -> None:
    if conn.in_transaction:
        conn.execute("ROLLBACK")


def _write_if_possible(conn, statement, parameters) -> None:
    """Record bookkeeping unless the database is too busy. The caller still reports."""
    try:
        conn.execute(statement, parameters)
    except sqlite3.OperationalError:
        pass


def _live_transactions(conn, account_id) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM ledger_transaction WHERE account_id = ?", (account_id,)
    ).fetchone()[0]


def _import_content(
    conn, run_id, name, content, digest, account_id, layout, declared, rules, progress
) -> FileResult:
    _require_unchanged_definition(conn, layout)
    existing = conn.execute(
        "SELECT id, layout_id FROM source_document WHERE content_sha256 = ?", (digest,)
    ).fetchone()
    if existing is not None:
        return _repeat_import(
            conn, run_id, name, digest, existing, account_id, layout, declared, rules
        )

    _require_account_type(conn, account_id, layout)
    read = read_pdf_document if layout.file_format == "pdf" else read_document
    metadata, records = read(content, layout)
    progress.rows_attempted = len(records)
    _require_account_number(conn, account_id, layout, records)
    coverage = _resolve_coverage(metadata, layout, declared)
    generated_on = _generated_on(metadata)

    document_id = _new_id()
    conn.execute(
        """INSERT INTO source_document (id, content_sha256, file_name, byte_size, format,
                                        layout_id, generated_on)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (document_id, digest, name, len(content), layout.file_format, layout.layout_id,
         generated_on),
    )
    conn.execute(
        """INSERT INTO document_coverage (source_document_id, account_id, coverage_kind,
                                          coverage_start, coverage_end, date_basis, evidence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (document_id, account_id, coverage.kind, coverage.start, coverage.end,
         coverage.date_basis, coverage.evidence),
    )
    conn.execute(
        """INSERT INTO document_interpretation (source_document_id, layout_id, parser_version,
                                                external_id_namespace, external_id_guarantee,
                                                pending_in_transaction_basis,
                                                pending_in_posting_basis)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (document_id, layout.layout_id, layout.parser_version, *_interpretation(layout)),
    )

    transactions = []
    unresolved = 0
    for record in records:
        record_id = _insert_record(conn, document_id, account_id, record)
        parsed = _parse(record, layout)
        _insert_parse(conn, record_id, layout, parsed)
        if parsed.reason_code is None:
            transaction_id = _insert_transaction(conn, account_id, parsed, record_id)
            _link(conn, transaction_id, record_id, document_id, account_id)
            transactions.append((transaction_id, parsed))
        else:
            insert_unresolved_issue(conn, record_id, parsed.reason_code)
            unresolved += 1

    for rule, members in find_candidate_groups(transactions):
        _insert_candidate_issue(conn, document_id, rule, members)

    reconciliation = reconcile_account(conn, account_id, rules, trigger_document_id=document_id)

    _insert_attempt(conn, run_id, name, digest, "imported", document_id)
    return FileResult(
        name,
        "imported",
        source_document_id=document_id,
        coverage=coverage,
        rows_read=len(records),
        valid_records=len(transactions),
        unresolved_records=unresolved,
        final_transactions=final_transactions(conn, [document_id]),
        consolidated_records=consolidated_records(conn, [document_id]),
        open_review_groups=_open_groups_touching(conn, document_id),
        memberships_changed=reconciliation.moved_records,
        reconciled=True,
    )


def _repeat_import(
    conn, run_id, name, digest, existing, account_id, layout, declared, rules
) -> FileResult:
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

    # Compared with the coverage in effect, which a declaration since import can change (D-051).
    stored = Coverage(*row)
    declaration = declared_coverage(conn, account_id).get(document_id)
    if declaration is not None:
        stored = Coverage(declaration.kind, declaration.start, declaration.end,
                          declaration.date_basis, declaration.evidence)
    if declared is not None and declared != stored:
        raise ImportFailure("coverage_conflict")

    # Accounts imported before reconciliation, or under other rules, catch up here once.
    reconciled = not is_current(conn, account_id, rules)
    moved = 0
    if reconciled:
        moved = reconcile_account(
            conn, account_id, rules, trigger_document_id=document_id
        ).moved_records

    _insert_attempt(conn, run_id, name, digest, "already_imported", document_id)
    return FileResult(
        name,
        "already_imported",
        source_document_id=document_id,
        coverage=stored,
        memberships_changed=moved,
        reconciled=reconciled,
    )


def _interpretation(layout: Layout) -> tuple:
    """What this layout says its documents mean, in stored form."""
    pending = layout.pending_in_complete_coverage

    def stored(basis):
        return int(pending[basis]) if basis in pending else None

    return (
        layout.external_id_namespace,
        layout.external_id_guarantee,
        stored("transaction"),
        stored("posting"),
    )


def _require_unchanged_definition(conn, layout: Layout) -> None:
    """A layout's meaning never changes once used, so a difference is refused (D-026)."""
    stored = conn.execute(
        """SELECT DISTINCT external_id_namespace, external_id_guarantee,
                           pending_in_transaction_basis, pending_in_posting_basis
           FROM document_interpretation WHERE layout_id = ? AND parser_version = ?""",
        (layout.layout_id, layout.parser_version),
    ).fetchall()
    if any(row != _interpretation(layout) for row in stored):
        raise ImportFailure("layout_definition_changed")


def _open_groups_touching(conn, document_id) -> int:
    return conn.execute(
        """SELECT COUNT(DISTINCT issue.id)
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           JOIN transaction_source link ON link.transaction_id = subject.transaction_id
           WHERE issue.kind = 'possible_duplicate' AND issue.status = 'open'
             AND link.source_document_id = ?""",
        (document_id,),
    ).fetchone()[0]


def _require_account_number(conn, account_id, layout: Layout, records) -> None:
    """Every row of a layout naming its account must name this account's last four digits, so a
    file exported from another account fails rather than importing into this one (D-061)."""
    if layout.row_account_number is None:
        return
    (last4,) = conn.execute("SELECT last4 FROM account WHERE id = ?", (account_id,)).fetchone()
    if last4 is None:
        raise ImportFailure("account_number_unknown")
    for record in records:
        if len(record.cells) != len(layout.columns):
            continue
        named = layout.row_account_number(record.cells)
        if named is not None and named != last4:
            raise ImportFailure("account_number_mismatch")


def _require_account_type(conn, account_id, layout: Layout) -> None:
    """A layout for one kind of account refuses another, whose balance runs the other way."""
    if layout.account_types is None:
        return
    (account_type,) = conn.execute(
        "SELECT account_type FROM account WHERE id = ?", (account_id,)
    ).fetchone()
    if account_type not in layout.account_types:
        raise ImportFailure("account_type_mismatch")


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


def _insert_transaction(conn, account_id, parsed: ParsedRow, record_id) -> str:
    transaction_id = _new_id()
    conn.execute(
        """INSERT INTO ledger_transaction (id, account_id, external_id, transaction_date,
                                           posting_date, amount_cents, description,
                                           settlement_status, primary_source_record_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (transaction_id, account_id, parsed.external_id, parsed.transaction_date,
         parsed.posting_date, parsed.amount_cents, parsed.description, parsed.settlement_status,
         record_id),
    )
    return transaction_id


def _link(conn, transaction_id, record_id, document_id, account_id) -> None:
    conn.execute(
        """INSERT INTO transaction_source (transaction_id, source_record_id, source_document_id,
                                           account_id, link_rule)
           VALUES (?, ?, ?, ?, 'new_record')""",
        (transaction_id, record_id, document_id, account_id),
    )
    conn.execute(
        """INSERT INTO source_record_origin (source_record_id, original_transaction_id)
           VALUES (?, ?)""",
        (record_id, transaction_id),
    )


def insert_unresolved_issue(conn, record_id, reason_code) -> str:
    """Raise a record's unresolved item, at import or when its resolution is undone (D-050)."""
    issue_id = _new_id()
    conn.execute(
        "INSERT INTO review_issue (id, kind, rule) VALUES (?, 'unresolved_record', ?)",
        (issue_id, reason_code),
    )
    conn.execute(
        "INSERT INTO review_issue_subject (review_issue_id, source_record_id) VALUES (?, ?)",
        (issue_id, record_id),
    )
    return issue_id


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
