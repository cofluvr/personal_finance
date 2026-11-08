"""What one stored resolution of an unresolved record holds, and what undoing it would regroup
(D-050).

Everything here reads the ledger and nothing writes to it.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.rules import MatchingRules
from personal_finance.reconcile.supersession import STATE_ACTIVE, STATE_UNDONE
from personal_finance.reports.decision_evidence import BoundRecord
from personal_finance.reports.undo_items import items_left_by_undo

# Bump whenever the material below changes, so an old token can never appear current.
RESOLUTION_REVISION_VERSION = 1


@dataclass(frozen=True)
class StoredResolution:
    resolution_id: str
    account_id: str
    account_name: str
    # completed or dismissed.
    kind: str
    # What a completion supplied: amount, transaction date, posting date and description, each
    # None where nothing was supplied. All None for a dismissal.
    completed_values: tuple
    record: BoundRecord
    # The unresolved item it closed. A later undo raises a new one.
    target_issue_id: str
    created_at: str
    state: str
    undone_at: str | None


@dataclass(frozen=True)
class ResolutionUndoOutlook:
    revision: str
    transactions_now: int
    transactions_after: int


def list_resolutions(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    """IDs, kinds, states and record positions only, so that routine output holds no values."""
    return [
        (resolution_id, account_name, created_at, STATE_UNDONE if undone else STATE_ACTIVE, kind,
         file_name, row)
        for resolution_id, account_name, created_at, undone, kind, file_name, row in conn.execute(
            """SELECT resolution.id, account.display_name, resolution.created_at,
                      EXISTS (SELECT 1 FROM record_resolution_event undone
                              WHERE undone.resolution_id = resolution.id
                                AND undone.event = 'undone'),
                      resolution.kind, document.file_name, record.record_index
               FROM record_resolution resolution
               JOIN account ON account.id = resolution.account_id
               JOIN source_record record ON record.id = resolution.source_record_id
               JOIN source_document document ON document.id = record.source_document_id
               WHERE :account IS NULL OR resolution.account_id = :account
               ORDER BY resolution.created_at, resolution.id""",
            {"account": account_id},
        )
    ]


def load_resolution(conn: sqlite3.Connection, resolution_id: str) -> StoredResolution | None:
    row = conn.execute(
        """SELECT resolution.account_id, account.display_name, resolution.kind,
                  resolution.completed_amount_cents, resolution.completed_transaction_date,
                  resolution.completed_posting_date, resolution.completed_description,
                  record.id, document.content_sha256, document.file_name, record.record_index,
                  link.transaction_id, resolution.target_issue_id, resolution.created_at,
                  undone.created_at
           FROM record_resolution resolution
           JOIN account ON account.id = resolution.account_id
           JOIN source_record record ON record.id = resolution.source_record_id
           JOIN source_document document ON document.id = record.source_document_id
           LEFT JOIN transaction_source link ON link.source_record_id = record.id
           LEFT JOIN record_resolution_event undone
               ON undone.resolution_id = resolution.id AND undone.event = 'undone'
           WHERE resolution.id = ?""",
        (resolution_id,),
    ).fetchone()
    if row is None:
        return None
    (account_id, account_name, kind, *rest) = row
    completed, bound, (target, created_at, undone_at) = rest[:4], rest[4:9], rest[9:]
    return StoredResolution(
        resolution_id, account_id, account_name, kind, tuple(completed), BoundRecord(*bound),
        target, created_at, STATE_UNDONE if undone_at else STATE_ACTIVE, undone_at,
    )


def binding_entries(
    conn: sqlite3.Connection, record_id: str
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    """Decisions, corrections, classifications, transfer matches and one-sided transfers binding a
    record that are not undone, active or superseded, which a completion's undo must wait for
    (D-050, D-053, D-054, D-055)."""
    decisions = [row[0] for row in conn.execute(
        """SELECT DISTINCT pair.decision_id FROM decision_constraint pair
           WHERE ? IN (pair.left_record_id, pair.right_record_id)
             AND NOT EXISTS (SELECT 1 FROM decision_event undone
                             WHERE undone.decision_id = pair.decision_id
                               AND undone.event = 'undone')
           ORDER BY pair.decision_id""",
        (record_id,),
    )]
    corrections = [row[0] for row in conn.execute(
        """SELECT DISTINCT bound.correction_id FROM value_correction_record bound
           WHERE bound.source_record_id = ?
             AND NOT EXISTS (SELECT 1 FROM value_correction_event undone
                             WHERE undone.correction_id = bound.correction_id
                               AND undone.event = 'undone')
           ORDER BY bound.correction_id""",
        (record_id,),
    )]
    classifications = [row[0] for row in conn.execute(
        """SELECT DISTINCT bound.classification_id FROM type_classification_record bound
           WHERE bound.source_record_id = ?
             AND NOT EXISTS (SELECT 1 FROM type_classification_event undone
                             WHERE undone.classification_id = bound.classification_id
                               AND undone.event = 'undone')
           ORDER BY bound.classification_id""",
        (record_id,),
    )]
    matches = [row[0] for row in conn.execute(
        """SELECT DISTINCT bound.match_id FROM transfer_match_record bound
           WHERE bound.source_record_id = ?
             AND NOT EXISTS (SELECT 1 FROM transfer_match_event undone
                             WHERE undone.match_id = bound.match_id AND undone.event = 'undone')
           ORDER BY bound.match_id""",
        (record_id,),
    )]
    one_sided = [row[0] for row in conn.execute(
        """SELECT DISTINCT bound.one_sided_transfer_id FROM one_sided_transfer_record bound
           WHERE bound.source_record_id = ?
             AND NOT EXISTS (SELECT 1 FROM one_sided_transfer_event undone
                             WHERE undone.one_sided_transfer_id = bound.one_sided_transfer_id
                               AND undone.event = 'undone')
           ORDER BY bound.one_sided_transfer_id""",
        (record_id,),
    )]
    return decisions, corrections, classifications, matches, one_sided


def resolution_undo_outlook(
    conn: sqlite3.Connection, resolution: StoredResolution, rules: MatchingRules
) -> ResolutionUndoOutlook:
    """The undo token, and the transaction counts either side of an undo (D-050).

    It covers the review items an undo would leave, for its record and the records whose items it
    changes. Only an active resolution has a token, and its kind, values and record never change,
    so none of them is covered.
    """
    left = items_left_by_undo(conn, resolution.account_id, rules,
                              frozenset({resolution.record.record_id}),
                              without_resolution=resolution.resolution_id)
    return ResolutionUndoOutlook(f"u{RESOLUTION_REVISION_VERSION}-{left.digest}",
                                 left.transactions_now, left.transactions_after)
