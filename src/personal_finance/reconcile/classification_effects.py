"""Which financial type applies to which transaction. See decisions.md D-053.

A classification is a correction of a field with no source value, so D-049's effective-value rule
decides it, shared with corrections and with categories through reconcile/stated_fields.py rather
than copied. Matching never reads anything here. The outcome is computed from memberships and
effective amounts once derivation and corrections are written, and is written to the derived
transaction_classification table in the caller's database transaction.
"""

import sqlite3

from personal_finance.reconcile import stated_fields
from personal_finance.reconcile.correction_effects import ActiveCorrection, FieldCorrection
from personal_finance.reconcile.stated_fields import StatedField

FINANCIAL_TYPES = ("purchase", "refund", "income", "fee", "interest", "transfer", "card_payment",
                   "loan_payment", "investment_contribution")
# What every transaction is until a classification applies. Never stored.
UNCLASSIFIED = "unclassified"

MONEY_IN = "in"
MONEY_OUT = "out"
# The direction each type allows, None meaning either (D-053).
DIRECTION_BY_TYPE = {
    "purchase": MONEY_OUT,
    "refund": MONEY_IN,
    "income": MONEY_IN,
    "fee": MONEY_OUT,
    "interest": MONEY_OUT,
    "transfer": None,
    "card_payment": MONEY_OUT,
    "loan_payment": MONEY_OUT,
    "investment_contribution": MONEY_OUT,
}
# Types that also allow money in on the kind of account they pay, where the payment is received
# (D-054).
PAID_ACCOUNT_TYPES_BY_TYPE = {
    "card_payment": frozenset({"credit_card"}),
    "loan_payment": frozenset({"loan"}),
    "investment_contribution": frozenset({"investment", "retirement"}),
}

# The field name under which classifications share D-049's effective-value rule.
TYPE_FIELD = "financial_type"
# A single agreeing type whose transaction's effective amount now runs the other way, as after a
# correction of its sign, leaves the transaction unclassified like a disagreement.
TYPE_AGAINST_DIRECTION = "against_direction"

TYPE_STATEMENTS = StatedField(
    field_name=TYPE_FIELD,
    statement_table="type_classification",
    value_column="financial_type",
    shown_value_sql="statement.financial_type",
    supersedes_column="supersedes_classification_id",
    record_table="type_classification_record",
    event_table="type_classification_event",
    statement_column="classification_id",
    derived_table="transaction_classification",
    derived_value_column="financial_type",
    misfit_state=TYPE_AGAINST_DIRECTION,
)


def fits_direction(financial_type: str, amount_cents: int, account_type: str) -> bool:
    """A zero amount runs neither way, so it fits every type. A payment received on the account it
    pays is money in there (D-054)."""
    direction = DIRECTION_BY_TYPE[financial_type]
    if direction is None or amount_cents == 0:
        return True
    if account_type in PAID_ACCOUNT_TYPES_BY_TYPE.get(financial_type, ()):
        return True
    return (amount_cents > 0) == (direction == MONEY_IN)


def type_of_account(conn: sqlite3.Connection, account_id: str) -> str:
    return conn.execute("SELECT account_type FROM account WHERE id = ?", (account_id,)).fetchone()[0]


def classification_chain_states(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Each classification's state, and each superseded one's successor, under D-048's rule."""
    return stated_fields.chain_states(conn, TYPE_STATEMENTS, account_id, treated_as_undone)


def load_active_classifications(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[ActiveCorrection, ...]:
    """Active classifications as corrections of TYPE_FIELD, whose value is the type and whose
    correction_id is the classification's ID. treated_as_undone leaves one out, restoring anything
    it superseded."""
    return stated_fields.load_active(conn, TYPE_STATEMENTS, account_id, treated_as_undone)


def effective_classifications(
    active_classifications, transaction_by_record_id, effective_amount_by_transaction,
    account_type: str,
) -> dict[object, FieldCorrection]:
    """The state and applied type of every classified transaction of one account, keyed by
    transaction.

    As for effective_field_corrections, a transaction is whatever transaction_by_record_id maps
    records to, and effective_amount_by_transaction gives the amount totals use for each.
    """
    return stated_fields.effective_values(
        TYPE_STATEMENTS, active_classifications, transaction_by_record_id,
        lambda transaction, financial_type: fits_direction(
            financial_type, effective_amount_by_transaction[transaction], account_type),
    )


def effective_amount_by_transaction(conn: sqlite3.Connection, account_id: str) -> dict[str, int]:
    """A corrected amount where one applies, else the source value, as totals use (D-049)."""
    return dict(conn.execute(
        """SELECT entry.id, COALESCE(fix.corrected_amount_cents, entry.amount_cents)
           FROM ledger_transaction entry
           LEFT JOIN transaction_correction fix
               ON fix.transaction_id = entry.id AND fix.field = 'amount' AND fix.state = 'applied'
           WHERE entry.account_id = ?""",
        (account_id,),
    ))


def write_classification_effects(conn: sqlite3.Connection, account_id: str) -> None:
    """Rewrite the account's derived rows from current memberships and corrected amounts. The
    caller holds the transaction, and both must already be final."""
    amounts = effective_amount_by_transaction(conn, account_id)
    account_type = type_of_account(conn, account_id)
    stated_fields.write_effects(
        conn, TYPE_STATEMENTS, account_id,
        lambda transaction, financial_type: fits_direction(
            financial_type, amounts[transaction], account_type),
    )


def unsettled_classifications(conn: sqlite3.Connection, account_id: str) -> frozenset:
    """Transactions left unclassified because classifications disagree, lost their basis or no
    longer fit the direction, as their records and the state, so that no transaction ID is
    needed."""
    return stated_fields.unsettled(conn, TYPE_STATEMENTS, account_id)

