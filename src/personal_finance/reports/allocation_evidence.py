"""What one stored allocation binds, and what undoing it would change (D-065).

Everything here reads the ledger and nothing writes to it. It is reports/stated_evidence.py's,
shared with types and categories (D-053, D-063), in the words of allocations. Members are named,
since their IDs say only where they are stored.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.allocation_effects import (
    ALLOCATION_STATEMENTS,
    account_amounts,
    effective_allocations,
)
from personal_finance.reconcile.correction_effects import FieldCorrection
from personal_finance.reconcile.household_effects import named_value
from personal_finance.reports.stated_evidence import (
    StoredStatement,
    digest,
    list_statements,
    load_statement,
    undo_outlook,
)

# Bump whenever the material below changes, so an old token can never appear current.
ALLOCATION_REVISION_VERSION = 1


@dataclass(frozen=True)
class AllocationUndoOutlook:
    revision: str
    # For each transaction holding a bound record: its ID, and its outcome now and after, None
    # meaning that no allocation binds it, so the account's default applies.
    state_by_transaction: tuple[tuple[str, str | None, str | None], ...]


def list_allocations(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    """IDs, canonical values, states and counts only, no amount of a transaction."""
    return list_statements(conn, ALLOCATION_STATEMENTS, account_id)


def load_allocation(conn: sqlite3.Connection, allocation_id: str) -> StoredStatement | None:
    return load_statement(conn, ALLOCATION_STATEMENTS, allocation_id)


def allocation_undo_outlook(conn: sqlite3.Connection,
                            allocation: StoredStatement) -> AllocationUndoOutlook:
    """The s1 token, and the outcome either side of an undo, as stated_evidence.undo_outlook gives
    them. Each transaction's effective amount decides whether an allocation by amount still sums,
    so it changes the outcomes and is not covered separately."""
    names = member_names(conn)
    amounts = account_amounts(conn, allocation.account_id)

    def named_effects(active, membership):
        return {
            transaction: FieldCorrection(effect.state,
                                         effect.applied_value and named_value(names,
                                                                              effect.applied_value),
                                         effect.correction_ids)
            for transaction, effect in effective_allocations(active, membership, amounts).items()
        }

    outlook = undo_outlook(conn, ALLOCATION_STATEMENTS, allocation, named_effects)
    material = {**outlook.material, "allocation": named_value(names, allocation.shown_value)}
    return AllocationUndoOutlook(allocation_revision(material), outlook.state_by_transaction)


def allocation_revision(material: dict) -> str:
    return f"s{ALLOCATION_REVISION_VERSION}-{digest(material)}"


def member_names(conn: sqlite3.Connection) -> dict[int, str]:
    return dict(conn.execute("SELECT id, name FROM household_member"))
