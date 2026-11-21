"""Which loan payment breakdown applies to which transaction. See D-071 point 7.

A breakdown is D-053's model applied to a fifth field, through reconcile/stated_fields.py: a
person states a loan payment's interest and fees from the lender's statement, and the principal
is the remainder. Its value is canonical text, interest cents, a colon, then fees cents. It fits
only a confirmed loan payment, a transaction typed loan_payment whose money out an applied
transfer confirms into a loan account, and only while its interest and fees are no more than the
payment's effective amount; otherwise it holds as does_not_fit. Matching never reads anything
here. The outcome is written for the whole ledger after types, transfers and corrections, since
it reads all three.
"""

import sqlite3

from personal_finance.reconcile import stated_fields
from personal_finance.reconcile.correction_effects import ActiveCorrection, FieldCorrection
from personal_finance.reconcile.stated_fields import StatedField

DOES_NOT_FIT = "does_not_fit"

BREAKDOWN_STATEMENTS = StatedField(
    field_name="loan_breakdown",
    statement_table="loan_payment_breakdown",
    value_column="breakdown",
    shown_value_sql="statement.breakdown",
    supersedes_column="supersedes_breakdown_id",
    record_table="loan_payment_breakdown_record",
    event_table="loan_payment_breakdown_event",
    statement_column="breakdown_id",
    derived_table="transaction_loan_breakdown",
    derived_value_column="breakdown",
    misfit_state=DOES_NOT_FIT,
)


def canonical(interest_cents: int, fees_cents: int) -> str:
    return f"{interest_cents}:{fees_cents}"


def parsed(value: str) -> tuple[int, int]:
    """A breakdown's interest and fees, in cents."""
    interest, _, fees = value.partition(":")
    return int(interest), int(fees)


def confirmed_loan_payments(conn: sqlite3.Connection, account_id: str) -> dict[str, int]:
    """The account's confirmed loan payments and their effective amounts: money out typed
    loan_payment that an applied match or one-sided transfer confirms, which D-054's fit rule
    lets land only on a loan account. The types, transfer effects and corrections must already be
    final."""
    return dict(conn.execute(
        """SELECT entry.id, COALESCE(fix.corrected_amount_cents, entry.amount_cents)
           FROM ledger_transaction entry
           JOIN transaction_classification kind
               ON kind.transaction_id = entry.id AND kind.state = 'applied'
              AND kind.financial_type = 'loan_payment'
           LEFT JOIN transaction_correction fix
               ON fix.transaction_id = entry.id AND fix.field = 'amount' AND fix.state = 'applied'
           WHERE entry.account_id = ?
             AND (EXISTS (SELECT 1 FROM transfer_match_effect matched
                          WHERE matched.outflow_transaction_id = entry.id)
                  OR EXISTS (SELECT 1 FROM one_sided_transfer_effect effect
                             WHERE effect.transaction_id = entry.id))""",
        (account_id,)))


def fits(payments: dict[str, int], transaction, value: str) -> bool:
    """A breakdown fits a confirmed loan payment whose effective amount covers it."""
    if transaction not in payments:
        return False
    interest, fees = parsed(value)
    return interest + fees <= abs(payments[transaction])


def load_active_breakdowns(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[ActiveCorrection, ...]:
    return stated_fields.load_active(conn, BREAKDOWN_STATEMENTS, account_id, treated_as_undone)


def effective_breakdowns(active_breakdowns, transaction_by_record_id,
                         payments) -> dict[object, FieldCorrection]:
    """The state and applied breakdown of every transaction a breakdown reaches. payments holds
    the confirmed loan payments' amounts, or is None to judge agreement alone, where a membership
    is only supposed."""
    return stated_fields.effective_values(
        BREAKDOWN_STATEMENTS, active_breakdowns, transaction_by_record_id,
        lambda transaction, value: payments is None or fits(payments, transaction, value),
    )


def write_breakdown_effects(conn: sqlite3.Connection) -> None:
    """Rewrite every account's derived rows where breakdowns are stated. The caller holds the
    transaction, and memberships, types, transfers and corrections must already be final."""
    for (account_id,) in conn.execute(
        "SELECT DISTINCT account_id FROM loan_payment_breakdown ORDER BY account_id"
    ).fetchall():
        payments = confirmed_loan_payments(conn, account_id)
        stated_fields.write_effects(conn, BREAKDOWN_STATEMENTS, account_id,
                                    lambda transaction, value: fits(payments, transaction, value))


def unsettled_breakdowns(conn: sqlite3.Connection, account_id: str) -> frozenset:
    return stated_fields.unsettled(conn, BREAKDOWN_STATEMENTS, account_id)


def applied_breakdowns(conn: sqlite3.Connection,
                       account_id: str | None = None) -> dict[str, tuple[int, int]]:
    """Each transaction whose breakdown applies, and its interest and fees."""
    return {transaction_id: parsed(value) for transaction_id, value in conn.execute(
        """SELECT derived.transaction_id, derived.breakdown FROM transaction_loan_breakdown derived
           JOIN ledger_transaction entry ON entry.id = derived.transaction_id
           WHERE derived.state = 'applied' AND (:account IS NULL OR entry.account_id = :account)""",
        {"account": account_id})}
