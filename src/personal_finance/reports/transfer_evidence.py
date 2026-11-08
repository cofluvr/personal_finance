"""What one stored transfer match binds, and its undo token (D-054).

Everything here reads the ledger and nothing writes to it.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.supersession import STATE_ACTIVE, STATE_UNDONE
from personal_finance.reconcile.transfer_effects import INFLOW, OUTFLOW
from personal_finance.reports.decision_evidence import BoundRecord
from personal_finance.reports.review_evidence import load_merge_evidence, transaction_revision

# Bump whenever the material below changes, so an old token can never appear current.
MATCH_REVISION_VERSION = 1


@dataclass(frozen=True)
class MatchSide:
    side: str
    account_id: str
    account_name: str
    # The transaction it was made on. A merge can retire it since.
    target_transaction_id: str
    bound_records: tuple[BoundRecord, ...]


@dataclass(frozen=True)
class StoredMatch:
    match_id: str
    created_at: str
    state: str
    undone_at: str | None
    # The outcome while active: applied, basis_changed, conflict, amounts_differ or type_differs.
    effect: str | None
    outflow: MatchSide
    inflow: MatchSide

    @property
    def account_ids(self) -> tuple[str, str]:
        return self.outflow.account_id, self.inflow.account_id

    @property
    def holding_transactions(self) -> tuple[str, ...]:
        """Every transaction holding a record either side binds."""
        return tuple(sorted({
            record.transaction_id for side in (self.outflow, self.inflow)
            for record in side.bound_records if record.transaction_id
        }))


def list_matches(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    """IDs, states, accounts and counts only, never amounts or descriptions (D-054)."""
    return conn.execute(
        """SELECT pair.id, CASE WHEN undone.id IS NULL THEN 'active' ELSE 'undone' END,
                  effect.state, outflow_account.display_name, inflow_account.display_name,
                  pair.created_at
           FROM transfer_match pair
           JOIN transfer_match_side outflow ON outflow.match_id = pair.id
                                           AND outflow.side = 'outflow'
           JOIN transfer_match_side inflow ON inflow.match_id = pair.id AND inflow.side = 'inflow'
           JOIN account outflow_account ON outflow_account.id = outflow.account_id
           JOIN account inflow_account ON inflow_account.id = inflow.account_id
           LEFT JOIN transfer_match_event undone
               ON undone.match_id = pair.id AND undone.event = 'undone'
           LEFT JOIN transfer_match_effect effect ON effect.match_id = pair.id
           WHERE :account IS NULL OR :account IN (outflow.account_id, inflow.account_id)
           ORDER BY pair.created_at, pair.id""",
        {"account": account_id},
    ).fetchall()


def load_match(conn: sqlite3.Connection, match_id: str) -> StoredMatch | None:
    row = conn.execute(
        """SELECT pair.created_at, undone.created_at, effect.state
           FROM transfer_match pair
           LEFT JOIN transfer_match_event undone
               ON undone.match_id = pair.id AND undone.event = 'undone'
           LEFT JOIN transfer_match_effect effect ON effect.match_id = pair.id
           WHERE pair.id = ?""",
        (match_id,),
    ).fetchone()
    if row is None:
        return None
    created_at, undone_at, effect = row
    sides = {}
    for side, account_id, account_name, target in conn.execute(
        """SELECT side.side, side.account_id, account.display_name, side.target_transaction_id
           FROM transfer_match_side side JOIN account ON account.id = side.account_id
           WHERE side.match_id = ?""",
        (match_id,),
    ):
        bound_records = [
            BoundRecord(*bound)
            for bound in conn.execute(
                """SELECT record.id, document.content_sha256, document.file_name,
                          record.record_index, link.transaction_id
                   FROM transfer_match_record bound
                   JOIN source_record record ON record.id = bound.source_record_id
                   JOIN source_document document ON document.id = record.source_document_id
                   LEFT JOIN transaction_source link ON link.source_record_id = record.id
                   WHERE bound.match_id = ? AND bound.side = ?""",
                (match_id, side),
            )
        ]
        sides[side] = MatchSide(
            side, account_id, account_name, target,
            tuple(sorted(bound_records, key=lambda record: (record.content_sha256, record.row))),
        )
    state = STATE_UNDONE if undone_at else STATE_ACTIVE
    return StoredMatch(match_id, created_at, state, undone_at,
                       effect if state == STATE_ACTIVE else None, sides[OUTFLOW], sides[INFLOW])


def match_revision(conn: sqlite3.Connection, match: StoredMatch) -> str:
    """The undo token: the outcome, and the transaction tokens of every transaction holding a
    record either side binds.

    Undoing a match moves no record and changes no amount or type, and a transaction token
    covers everything about each transaction, this match's outcome there included. So an unrelated
    file leaves it unchanged, and anything that changes what either side holds changes it.
    """
    material = {
        "effect": match.effect,
        "sides": {
            side.side: sorted(
                transaction_revision(load_merge_evidence(conn, transaction_id))
                for transaction_id in sorted({
                    record.transaction_id for record in side.bound_records if record.transaction_id
                })
            )
            for side in (match.outflow, match.inflow)
        },
    }
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"m{MATCH_REVISION_VERSION}-{digest}"
