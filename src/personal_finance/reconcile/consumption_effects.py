"""Which fund consumption applies to which spending transaction. See D-070 point 5.

A consumption is D-053's model applied to a fourth field, through reconcile/stated_fields.py: a
person states that a spending transaction is paid from a goal, a reserve or the tax reserve. Only
D-056's spending group takes one, as for a category, so a transaction whose type changes or on
which a transfer is confirmed holds it as not_spending. Matching never reads anything here. The
outcome is written to the derived transaction_fund_consumption table for the whole ledger, after
types and transfers, since it reads both. The amount consumed is not derived here: it turns on the
fund's assignments, and planning/funds.py computes it where it is read.
"""

import sqlite3

from personal_finance.reconcile import stated_fields
from personal_finance.reconcile.category_effects import NOT_SPENDING, spending_transactions
from personal_finance.reconcile.correction_effects import ActiveCorrection, FieldCorrection
from personal_finance.reconcile.stated_fields import StatedField

CONSUMPTION_STATEMENTS = StatedField(
    field_name="fund_consumption",
    statement_table="fund_consumption",
    value_column="fund_id",
    shown_value_sql="(SELECT name FROM fund WHERE fund.id = statement.fund_id)",
    supersedes_column="supersedes_consumption_id",
    record_table="fund_consumption_record",
    event_table="fund_consumption_event",
    statement_column="consumption_id",
    derived_table="transaction_fund_consumption",
    derived_value_column="fund_id",
    misfit_state=NOT_SPENDING,
)


def load_active_consumptions(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[ActiveCorrection, ...]:
    """Active consumptions as corrections of the consumption field, whose value is the fund's ID.
    treated_as_undone leaves one out, restoring anything it superseded."""
    return stated_fields.load_active(conn, CONSUMPTION_STATEMENTS, account_id, treated_as_undone)


def effective_consumptions(active_consumptions, transaction_by_record_id,
                           spending) -> dict[object, FieldCorrection]:
    """The state and applied fund of every transaction a consumption reaches, keyed by transaction
    as transaction_by_record_id names it. spending holds the transactions in spending, or None to
    judge agreement alone, where a membership is only supposed."""
    return stated_fields.effective_values(
        CONSUMPTION_STATEMENTS, active_consumptions, transaction_by_record_id,
        lambda transaction, _: spending is None or transaction in spending,
    )


def write_consumption_effects(conn: sqlite3.Connection) -> None:
    """Rewrite every consumed account's derived rows. The caller holds the transaction, and
    memberships, types and transfer effects must already be final. An account never consumed
    against has no rows to rewrite."""
    for (account_id,) in conn.execute(
        "SELECT DISTINCT account_id FROM fund_consumption ORDER BY account_id"
    ).fetchall():
        spending = spending_transactions(conn, account_id)
        stated_fields.write_effects(conn, CONSUMPTION_STATEMENTS, account_id,
                                    lambda transaction, _: transaction in spending)


def unsettled_consumptions(conn: sqlite3.Connection, account_id: str) -> frozenset:
    """Transactions where consumptions reach and none applies, as their records and the state."""
    return stated_fields.unsettled(conn, CONSUMPTION_STATEMENTS, account_id)
