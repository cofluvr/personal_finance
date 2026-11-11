"""Which allocation applies to which transaction. See decisions.md D-065.

An allocation is D-053's model applied to a value of several parts, through
reconcile/stated_fields.py. Its value is canonical text, the kind, a colon, then member=value parts
sorted by member ID, so two allocations agree exactly when their values are equal. Every
transaction can be allocated, whatever its type. An allocation by amount fits only while its parts
sum to the effective amount's magnitude, else it is amount_differs. Matching never reads anything
here. The outcome is written to the derived transaction_allocation table for the whole ledger,
after corrections, since amount_differs reads them.
"""

import sqlite3

from personal_finance.reconcile import stated_fields
from personal_finance.reconcile.correction_effects import ActiveCorrection, FieldCorrection
from personal_finance.reconcile.household_effects import BY_AMOUNT, effective_amounts, parsed
from personal_finance.reconcile.stated_fields import StatedField

# A single agreeing allocation by amount whose parts no longer sum to its transaction's effective
# amount, because a correction or its undo changed it. It stays on record and does not apply.
AMOUNT_DIFFERS = "amount_differs"

ALLOCATION_STATEMENTS = StatedField(
    field_name="allocation",
    statement_table="allocation_statement",
    value_column="allocation",
    shown_value_sql="statement.allocation",
    supersedes_column="supersedes_allocation_id",
    record_table="allocation_statement_record",
    event_table="allocation_statement_event",
    statement_column="allocation_id",
    derived_table="transaction_allocation",
    derived_value_column="allocation",
    misfit_state=AMOUNT_DIFFERS,
)


def fits_amount(value: str, amount_cents: int) -> bool:
    """Whether an allocation fits an effective amount: only one by amount can stop fitting."""
    kind, parts = parsed(value)
    return kind != BY_AMOUNT or sum(part for _, part in parts) == abs(amount_cents)


def load_active_allocations(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[ActiveCorrection, ...]:
    """Active allocations as corrections of the allocation field, whose value is the canonical
    one. treated_as_undone leaves one out, restoring anything it superseded."""
    return stated_fields.load_active(conn, ALLOCATION_STATEMENTS, account_id, treated_as_undone)


def effective_allocations(active_allocations, transaction_by_record_id,
                          amounts) -> dict[object, FieldCorrection]:
    """The state and applied allocation of every transaction an allocation reaches, keyed by
    transaction as transaction_by_record_id names it. amounts holds each transaction's effective
    amount, or is None to judge agreement alone, where a membership is only supposed."""
    return stated_fields.effective_values(
        ALLOCATION_STATEMENTS, active_allocations, transaction_by_record_id,
        lambda transaction, value: amounts is None or fits_amount(value, amounts[transaction]),
    )


def account_amounts(conn: sqlite3.Connection, account_id: str) -> dict[str, int]:
    """Each of the account's transactions' effective amount, corrections final."""
    return {transaction_id: cents
            for transaction_id, _, cents in effective_amounts(conn, account_id)}


def write_allocation_effects(conn: sqlite3.Connection) -> None:
    """Rewrite every allocated account's derived rows. The caller holds the transaction, and
    memberships and corrections must already be final. An account never allocated has no rows to
    rewrite."""
    for (account_id,) in conn.execute(
        "SELECT DISTINCT account_id FROM allocation_statement ORDER BY account_id"
    ).fetchall():
        amounts = account_amounts(conn, account_id)
        stated_fields.write_effects(conn, ALLOCATION_STATEMENTS, account_id,
                                    lambda transaction, value: fits_amount(value,
                                                                           amounts[transaction]))


def unsettled_allocations(conn: sqlite3.Connection, account_id: str) -> frozenset:
    """Transactions where allocations reach and none applies, as their records and the state."""
    return stated_fields.unsettled(conn, ALLOCATION_STATEMENTS, account_id)
