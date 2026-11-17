"""What one stored loan payment breakdown binds, and what undoing it would change (D-071 points
7 and 8).

Everything here reads the ledger and nothing writes to it. It is reports/stated_evidence.py's,
shared with the other stated kinds, in the words of breakdowns.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.breakdown_effects import (
    BREAKDOWN_STATEMENTS,
    confirmed_loan_payments,
    effective_breakdowns,
)
from personal_finance.reports.stated_evidence import (
    StoredStatement,
    digest,
    list_statements,
    load_statement,
    undo_outlook,
)

# Bump whenever the material below changes, so an old token can never appear current.
BREAKDOWN_REVISION_VERSION = 1


@dataclass(frozen=True)
class BreakdownUndoOutlook:
    revision: str
    state_by_transaction: tuple[tuple[str, str | None, str | None], ...]


def list_breakdowns(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    return list_statements(conn, BREAKDOWN_STATEMENTS, account_id)


def load_breakdown(conn: sqlite3.Connection, breakdown_id: str) -> StoredStatement | None:
    return load_statement(conn, BREAKDOWN_STATEMENTS, breakdown_id)


def breakdown_undo_outlook(conn: sqlite3.Connection,
                           breakdown: StoredStatement) -> BreakdownUndoOutlook:
    """The lb1 token, as fc1: the transactions holding its bound records, and their outcome with
    and without it. Whether each is still a confirmed loan payment covering it changes the
    outcomes, so it is not covered separately."""
    payments = confirmed_loan_payments(conn, breakdown.account_id)
    outlook = undo_outlook(
        conn, BREAKDOWN_STATEMENTS, breakdown,
        lambda active, membership: effective_breakdowns(active, membership, payments))
    material = {**outlook.material, "breakdown": breakdown.shown_value}
    return BreakdownUndoOutlook(f"lb{BREAKDOWN_REVISION_VERSION}-{digest(material)}",
                                outlook.state_by_transaction)
