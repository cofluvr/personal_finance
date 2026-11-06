"""Import run summaries. See decisions.md D-036 for each count and which ones reconcile."""

import sqlite3
from dataclasses import dataclass


def final_transactions(conn: sqlite3.Connection, document_ids: list[str]) -> int:
    """Distinct live transactions that these documents' valid records now belong to."""
    marks = ",".join("?" * len(document_ids))
    return conn.execute(
        f"""SELECT COUNT(DISTINCT transaction_id) FROM transaction_source
            WHERE source_document_id IN ({marks})""",
        document_ids,
    ).fetchone()[0]


def consolidated_records(conn: sqlite3.Connection, document_ids: list[str]) -> int:
    """Valid records whose live transaction also has a record from another document."""
    marks = ",".join("?" * len(document_ids))
    return conn.execute(
        f"""SELECT COUNT(*) FROM transaction_source link
            WHERE link.source_document_id IN ({marks})
              AND EXISTS (SELECT 1 FROM transaction_source other
                          WHERE other.transaction_id = link.transaction_id
                            AND other.source_document_id <> link.source_document_id)""",
        document_ids,
    ).fetchone()[0]


@dataclass(frozen=True)
class RunSummary:
    files_attempted: int
    files_imported: int
    files_already_imported: int
    files_failed: int
    rows_read: int
    valid_records: int
    unresolved_records: int
    final_transactions: int
    consolidated_records: int
    net_transactions: int
    memberships_changed: int
    failed_rows_attempted: int
    failed_files_without_row_count: int


def summarize_run(conn: sqlite3.Connection, results: list) -> RunSummary:
    """Add up a run's file results, reading final-state counts after its last file."""
    imported = [result for result in results if result.outcome == "imported"]
    failed = [result for result in results if result.outcome == "failed"]
    completed = [result for result in results if result.outcome != "failed"]
    documents = [result.source_document_id for result in imported]
    return RunSummary(
        files_attempted=len(results),
        files_imported=len(imported),
        files_already_imported=len(completed) - len(imported),
        files_failed=len(failed),
        rows_read=sum(result.rows_read for result in imported),
        valid_records=sum(result.valid_records for result in imported),
        unresolved_records=sum(result.unresolved_records for result in imported),
        final_transactions=final_transactions(conn, documents),
        consolidated_records=consolidated_records(conn, documents),
        net_transactions=sum(result.net_transactions for result in completed),
        memberships_changed=sum(result.memberships_changed for result in completed),
        failed_rows_attempted=sum(result.rows_attempted or 0 for result in failed),
        failed_files_without_row_count=sum(result.rows_attempted is None for result in failed),
    )
