"""What undoing a resolution or a coverage declaration would leave, for its undo token (D-050,
D-051).

Everything here reads the ledger and nothing writes to it.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.apply import load_constraints, load_evidence
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.rules import MatchingRules


@dataclass(frozen=True)
class ItemsLeftByUndo:
    digest: str
    transactions_now: int
    transactions_after: int


def items_left_by_undo(
    conn: sqlite3.Connection,
    account_id: str,
    rules: MatchingRules,
    seed_record_ids: frozenset[str] = frozenset(),
    without_resolution: str | None = None,
    without_declaration: str | None = None,
) -> ItemsLeftByUndo:
    """The review items derivation would give after the undo, for the records whose items differ
    with and without the entry undone, and seed_record_ids.

    That is all such an undo does. An item's members are its transactions' records, so the items
    also give their grouping. A rules change reaches the digest through derivation once reconciled,
    and is refused before. Evidence that cannot affect the undo leaves it unchanged.
    """
    documents, records, unresolved, _ = load_evidence(conn, account_id)
    documents_after, records_after, unresolved_after, _ = load_evidence(
        conn, account_id, without_resolution, without_declaration
    )
    constraints = load_constraints(conn, account_id)
    now = derive(documents, records, unresolved, rules, constraints)
    after = derive(documents_after, records_after, unresolved_after, rules, constraints)

    keys = _record_keys(conn, account_id)
    scope = set(seed_record_ids)
    for changed in set(now.items) ^ set(after.items):
        scope.update(record for member in changed.members for record in member)

    def keyed(record_ids):
        return sorted(keys[record_id] for record_id in record_ids)

    material = {
        "items": sorted(
            [item.rule, sorted(map(keyed, item.members)), list(item.reasons),
             item.date_start, item.date_end]
            for item in after.items
            if scope.intersection(record for member in item.members for record in member)
        ),
    }
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return ItemsLeftByUndo(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                           len(now.groups), len(after.groups))


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
