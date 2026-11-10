"""What one stored categorization binds, and what undoing it would change (D-063).

Everything here reads the ledger and nothing writes to it. It is reports/stated_evidence.py's,
shared with financial types (D-053), in the words of categories.
"""

import sqlite3
from dataclasses import dataclass, replace

from personal_finance.reconcile.category_effects import (
    CATEGORY_STATEMENTS,
    effective_categorizations,
    spending_transactions,
)
from personal_finance.reconcile.category_rule_effects import (
    load_active_rules,
    load_spending_facts,
    rule_outcomes,
)
from personal_finance.reports.category_rule_evidence import record_keys
from personal_finance.reports.stated_evidence import (
    StoredStatement,
    digest,
    list_statements,
    load_statement,
    undo_outlook,
)

# Bump whenever the material below changes, so an old token can never appear current.
# Version 2 adds the category rules' outcome its transactions would take with no person's
# categorization, left out where no rule matches (D-064).
CATEGORIZATION_REVISION_VERSION = 2


@dataclass(frozen=True)
class CategorizationUndoOutlook:
    revision: str
    # For each transaction holding a bound record: its ID, and its outcome now and after, None
    # meaning that no categorization binds it, so it is uncategorized.
    state_by_transaction: tuple[tuple[str, str | None, str | None], ...]


def list_categorizations(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    """IDs, category names, states and counts only. A category name is the owner's label, as an
    account name is (D-063)."""
    return list_statements(conn, CATEGORY_STATEMENTS, account_id)


def load_categorization(conn: sqlite3.Connection, categorization_id: str) -> StoredStatement | None:
    return load_statement(conn, CATEGORY_STATEMENTS, categorization_id)


def categorization_undo_outlook(
    conn: sqlite3.Connection, categorization: StoredStatement
) -> CategorizationUndoOutlook:
    """The undo token, and the outcome either side of an undo, as stated_evidence.undo_outlook
    gives them. Whether a transaction is in spending changes the outcomes, so it is not covered
    separately."""
    spending = spending_transactions(conn, categorization.account_id)
    outlook = undo_outlook(
        conn, CATEGORY_STATEMENTS, categorization,
        lambda active, membership: effective_categorizations(active, membership, spending),
    )
    material = outlook.material
    holding = [transaction for transaction, _, _ in outlook.state_by_transaction]
    facts = [replace(facts, categorized_by_person=False)
             for facts in load_spending_facts(conn, holding)]
    by_rules = rule_outcomes(facts, load_active_rules(conn))
    if by_rules:
        name_by_category = dict(conn.execute("SELECT id, name FROM category"))
        keys = record_keys(conn, by_rules)
        material = {**material, "category_rules": sorted(
            [keys[transaction], outcome.state, name_by_category.get(outcome.category_id)]
            for transaction, outcome in by_rules.items()
        )}
    return CategorizationUndoOutlook(categorization_revision(material),
                                     outlook.state_by_transaction)


def categorization_revision(material: dict) -> str:
    return f"g{CATEGORIZATION_REVISION_VERSION}-{digest(material)}"
