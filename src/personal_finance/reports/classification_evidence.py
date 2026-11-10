"""What one stored classification binds, and what undoing it would change (D-053).

Everything here reads the ledger and nothing writes to it. It is reports/stated_evidence.py's,
shared with categories (D-063), in the words of financial types.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.classification_effects import (
    TYPE_STATEMENTS,
    effective_amount_by_transaction,
    effective_classifications,
    type_of_account,
)
from personal_finance.reports.stated_evidence import (
    StoredStatement,
    digest,
    list_statements,
    load_statement,
    undo_outlook,
)

# Bump whenever the material below changes, so an old token can never appear current.
CLASSIFICATION_REVISION_VERSION = 1


class StoredClassification(StoredStatement):
    """A stored statement of a financial type, named as one."""

    @property
    def classification_id(self) -> str:
        return self.statement_id

    @property
    def financial_type(self) -> str:
        return self.shown_value

    @property
    def supersedes_classification_id(self) -> str | None:
        return self.supersedes_id


@dataclass(frozen=True)
class ClassificationUndoOutlook:
    revision: str
    # For each transaction holding a bound record: its ID, and its outcome now and after, None
    # meaning that no classification binds it, so it is unclassified.
    state_by_transaction: tuple[tuple[str, str | None, str | None], ...]


def list_classifications(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    """IDs, types, states and counts only. A type is not financial data in itself (D-053)."""
    return list_statements(conn, TYPE_STATEMENTS, account_id)


def load_classification(
    conn: sqlite3.Connection, classification_id: str
) -> StoredClassification | None:
    statement = load_statement(conn, TYPE_STATEMENTS, classification_id)
    return None if statement is None else StoredClassification(**vars(statement))


def classification_undo_outlook(
    conn: sqlite3.Connection, classification: StoredStatement
) -> ClassificationUndoOutlook:
    """The undo token, and the outcome either side of an undo, as stated_evidence.undo_outlook
    gives them. A change of direction changes the outcomes, so it is not covered separately."""
    account_id = classification.account_id
    amounts = effective_amount_by_transaction(conn, account_id)
    account_type = type_of_account(conn, account_id)
    outlook = undo_outlook(
        conn, TYPE_STATEMENTS, classification,
        lambda active, membership: effective_classifications(active, membership, amounts,
                                                             account_type),
    )
    return ClassificationUndoOutlook(classification_revision(outlook.material),
                                     outlook.state_by_transaction)


def classification_revision(material: dict) -> str:
    return f"f{CLASSIFICATION_REVISION_VERSION}-{digest(material)}"
