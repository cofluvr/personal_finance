"""What one stored fund consumption binds, and what undoing it would change (D-070 points 5 and 7).

Everything here reads the ledger and nothing writes to it. It is reports/stated_evidence.py's,
shared with types, categories and allocations (D-053, D-063, D-065), in the words of funds.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.category_effects import spending_transactions
from personal_finance.reconcile.consumption_effects import (
    CONSUMPTION_STATEMENTS,
    effective_consumptions,
)
from personal_finance.reports.stated_evidence import (
    StoredStatement,
    digest,
    list_statements,
    load_statement,
    undo_outlook,
)

# Bump whenever the material below changes, so an old token can never appear current.
CONSUMPTION_REVISION_VERSION = 1


@dataclass(frozen=True)
class ConsumptionUndoOutlook:
    revision: str
    # For each transaction holding a bound record: its ID, and its outcome now and after, None
    # meaning that no consumption reaches it.
    state_by_transaction: tuple[tuple[str, str | None, str | None], ...]


def list_consumptions(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    """IDs, fund names, states and counts only, no amount of a transaction."""
    return list_statements(conn, CONSUMPTION_STATEMENTS, account_id)


def load_consumption(conn: sqlite3.Connection, consumption_id: str) -> StoredStatement | None:
    return load_statement(conn, CONSUMPTION_STATEMENTS, consumption_id)


def consumption_fund_id(conn: sqlite3.Connection, consumption_id: str) -> str:
    return conn.execute("SELECT fund_id FROM fund_consumption WHERE id = ?",
                        (consumption_id,)).fetchone()[0]


def consumption_undo_outlook(conn: sqlite3.Connection,
                             consumption: StoredStatement) -> ConsumptionUndoOutlook:
    """The fc1 token: its fund, the transactions holding its bound records, and their outcome
    with and without it (D-070 point 7), as stated_evidence.undo_outlook gives them. Whether each
    transaction is still in spending changes the outcomes, so it is not covered separately."""
    spending = spending_transactions(conn, consumption.account_id)
    outlook = undo_outlook(
        conn, CONSUMPTION_STATEMENTS, consumption,
        lambda active, membership: effective_consumptions(active, membership, spending))
    material = {**outlook.material,
                "fund": [consumption_fund_id(conn, consumption.statement_id),
                         consumption.shown_value]}
    return ConsumptionUndoOutlook(f"fc{CONSUMPTION_REVISION_VERSION}-{digest(material)}",
                                  outlook.state_by_transaction)
