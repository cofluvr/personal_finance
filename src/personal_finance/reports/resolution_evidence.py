"""What one stored resolution of an unresolved record holds, and what undoing it would regroup
(D-050).

Everything here reads the ledger and nothing writes to it.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.apply import load_constraints, load_evidence
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.rules import MatchingRules
from personal_finance.reconcile.supersession import STATE_ACTIVE, STATE_UNDONE
from personal_finance.reports.decision_evidence import BoundRecord, record_material

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


def binding_entries(conn: sqlite3.Connection, record_id: str) -> tuple[list[str], list[str]]:
    """Decisions and corrections binding a record that are not undone, active or superseded, which
    a completion's undo must wait for (D-050)."""
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
    return decisions, corrections


def resolution_undo_outlook(
    conn: sqlite3.Connection, resolution: StoredResolution, rules: MatchingRules
) -> ResolutionUndoOutlook:
    """The undo token, and the transaction counts either side of an undo (D-050).

    Like a decision's (D-045), it covers what derivation gives with and without this resolution,
    and the evidence of every record that differs between the two or is resolved by it. Evidence
    that cannot affect the undo leaves it unchanged, so an unrelated file does not force another
    inspection. Only an active resolution has one, so its state is not covered.
    """
    account_id = resolution.account_id
    documents, records, unresolved, _ = load_evidence(conn, account_id)
    _, records_after, unresolved_after, _ = load_evidence(conn, account_id, resolution.resolution_id)
    constraints = load_constraints(conn, account_id)
    now = derive(documents, records, unresolved, rules, constraints)
    after = derive(documents, records_after, unresolved_after, rules, constraints)

    keys = _record_keys(conn, account_id)
    scope = {resolution.record.record_id}
    for changed in set(now.groups) ^ set(after.groups):
        scope.update(changed.record_ids)
    for changed in set(now.items) ^ set(after.items):
        scope.update(record for member in changed.members for record in member)
    for result in (now, after):
        for group in result.groups:
            if scope.intersection(group.record_ids):
                scope.update(group.record_ids)

    def keyed(record_ids):
        return sorted(keys[record_id] for record_id in record_ids)

    def view(result, held):
        return {
            "groups": sorted(
                [keyed(group.record_ids), group.link_rule, keys[group.primary_record_id]]
                for group in result.groups if scope.intersection(group.record_ids)
            ),
            "items": sorted(
                [item.rule, sorted(map(keyed, item.members)), list(item.reasons),
                 item.date_start, item.date_end]
                for item in result.items
                if scope.intersection(record for member in item.members for record in member)
            ),
            "records": sorted(
                [keys[record.id], record_material(record)]
                for record in held if record.id in scope
            ),
        }

    material = {
        "kind": resolution.kind,
        "values": list(resolution.completed_values),
        "record": keys[resolution.record.record_id],
        "rules": rules.fingerprint(),
        "with_resolution": view(now, records),
        "without_resolution": view(after, records_after),
    }
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return ResolutionUndoOutlook(f"u{RESOLUTION_REVISION_VERSION}-{digest}", len(now.groups),
                                 len(after.groups))


def _record_keys(conn, account_id) -> dict[str, list]:
    """Every record of the account as document hash and row, never by generated ID."""
    return {
        record_id: [digest, index]
        for record_id, digest, index in conn.execute(
            """SELECT record.id, document.content_sha256, record.record_index
               FROM source_record record
               JOIN source_document document ON document.id = record.source_document_id
               WHERE record.account_id = ?""",
            (account_id,),
        )
    }
