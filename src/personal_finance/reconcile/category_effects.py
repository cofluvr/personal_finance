"""Which category applies to which spending transaction. See decisions.md D-063.

A categorization is D-053's model applied to a second field, through reconcile/stated_fields.py.
Only spending takes a category: a transaction whose applied type counts as spending and on which
no transfer is confirmed, D-056's spending group. Matching never reads anything here. The outcome
is written to the derived transaction_category table for the whole ledger, after types and
transfers, since it reads both.
"""

import sqlite3

from personal_finance.reconcile import stated_fields
from personal_finance.reconcile.correction_effects import ActiveCorrection, FieldCorrection
from personal_finance.reconcile.stated_fields import StatedField

# Applied types counted as spending, a refund reducing it (PRD §9, D-056).
SPENDING_TYPES = ("purchase", "fee", "interest", "refund")

# Whether a transfer is confirmed on the transaction `entry`. An effect row names its transactions
# only while it applies, so naming one confirms it.
CONFIRMED_TRANSFER_SQL = """
    EXISTS (SELECT 1 FROM transfer_match_effect matched
            WHERE matched.outflow_transaction_id = entry.id)
    OR EXISTS (SELECT 1 FROM transfer_match_effect matched
               WHERE matched.inflow_transaction_id = entry.id)
    OR EXISTS (SELECT 1 FROM one_sided_transfer_effect one_sided
               WHERE one_sided.transaction_id = entry.id)"""

# A single agreeing categorization on a transaction no longer in spending, because its type
# changed or a transfer was confirmed there. It stays on record and does not apply.
NOT_SPENDING = "not_spending"

CATEGORY_STATEMENTS = StatedField(
    field_name="category",
    statement_table="category_assignment",
    value_column="category_id",
    shown_value_sql="(SELECT name FROM category WHERE category.id = statement.category_id)",
    supersedes_column="supersedes_assignment_id",
    record_table="category_assignment_record",
    event_table="category_assignment_event",
    statement_column="assignment_id",
    derived_table="transaction_category",
    derived_value_column="category_id",
    misfit_state=NOT_SPENDING,
)


def spending_transactions(conn: sqlite3.Connection, account_id: str) -> frozenset[str]:
    """The account's transactions in D-056's spending group, from the derived types and transfer
    effects, which must already be final."""
    marks = ", ".join("?" for _ in SPENDING_TYPES)
    return frozenset(row[0] for row in conn.execute(
        f"""SELECT entry.id FROM ledger_transaction entry
            JOIN transaction_classification kind ON kind.transaction_id = entry.id
            WHERE entry.account_id = ? AND kind.state = 'applied'
              AND kind.financial_type IN ({marks})
              AND NOT ({CONFIRMED_TRANSFER_SQL})""",
        (account_id, *SPENDING_TYPES),
    ))


def load_active_categorizations(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[ActiveCorrection, ...]:
    """Active categorizations as corrections of the category field, whose value is the category's
    ID. treated_as_undone leaves one out, restoring anything it superseded."""
    return stated_fields.load_active(conn, CATEGORY_STATEMENTS, account_id, treated_as_undone)


def effective_categorizations(active_categorizations, transaction_by_record_id,
                              spending) -> dict[object, FieldCorrection]:
    """The state and applied category of every transaction a categorization reaches, keyed by
    transaction as transaction_by_record_id names it. spending holds the transactions in spending,
    or None to judge agreement alone, where a membership is only supposed."""
    return stated_fields.effective_values(
        CATEGORY_STATEMENTS, active_categorizations, transaction_by_record_id,
        lambda transaction, _: spending is None or transaction in spending,
    )


def write_category_effects(conn: sqlite3.Connection) -> None:
    """Rewrite every categorized account's derived rows. The caller holds the transaction, and
    memberships, types and transfer effects must already be final. An account never categorized
    has no rows to rewrite."""
    for (account_id,) in conn.execute(
        "SELECT DISTINCT account_id FROM category_assignment ORDER BY account_id"
    ).fetchall():
        spending = spending_transactions(conn, account_id)
        stated_fields.write_effects(conn, CATEGORY_STATEMENTS, account_id,
                                    lambda transaction, _: transaction in spending)


def unsettled_categorizations(conn: sqlite3.Connection, account_id: str) -> frozenset:
    """Transactions where categorizations reach and none applies, as their records and the state."""
    return stated_fields.unsettled(conn, CATEGORY_STATEMENTS, account_id)
