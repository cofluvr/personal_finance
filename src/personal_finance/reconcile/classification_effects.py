"""Which financial type applies to which transaction. See decisions.md D-053.

A classification is a correction of a field with no source value, so D-049's effective-value rule
decides it, shared with corrections rather than copied. Matching never reads anything here. The
outcome is computed from memberships and effective amounts once derivation and corrections are
written, and is written to the derived transaction_classification table in the caller's database
transaction.
"""

import sqlite3
from collections import defaultdict

from personal_finance.reconcile.correction_effects import (
    FIELD_APPLIED,
    ActiveCorrection,
    FieldCorrection,
    effective_field_corrections,
    transaction_by_record_id,
)
from personal_finance.reconcile.supersession import STATE_ACTIVE, supersession_chain_states

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

# The field name under which classifications share D-049's effective-value rule.
TYPE_FIELD = "financial_type"
# A single agreeing type whose transaction's effective amount now runs the other way, as after a
# correction of its sign, leaves the transaction unclassified like a disagreement.
TYPE_AGAINST_DIRECTION = "against_direction"


def fits_direction(financial_type: str, amount_cents: int) -> bool:
    """A zero amount runs neither way, so it fits every type."""
    direction = DIRECTION_BY_TYPE[financial_type]
    if direction is None or amount_cents == 0:
        return True
    return (amount_cents > 0) == (direction == MONEY_IN)


def classification_chain_states(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Each classification's state, and each superseded one's successor, under D-048's rule."""
    rows = conn.execute(
        """SELECT classification.id, classification.supersedes_classification_id,
                  EXISTS (SELECT 1 FROM type_classification_event undone
                          WHERE undone.classification_id = classification.id
                            AND undone.event = 'undone')
           FROM type_classification classification WHERE classification.account_id = ?""",
        (account_id,),
    ).fetchall()
    return supersession_chain_states(rows, treated_as_undone)


def load_active_classifications(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[ActiveCorrection, ...]:
    """Active classifications as corrections of TYPE_FIELD, whose value is the type and whose
    correction_id is the classification's ID. treated_as_undone leaves one out, restoring anything
    it superseded."""
    states_by_id, _ = classification_chain_states(conn, account_id, treated_as_undone)
    bound_record_ids_by_classification = defaultdict(set)
    for classification_id, record_id in conn.execute(
        """SELECT bound.classification_id, bound.source_record_id
           FROM type_classification_record bound
           JOIN type_classification classification ON classification.id = bound.classification_id
           WHERE classification.account_id = ?""",
        (account_id,),
    ):
        bound_record_ids_by_classification[classification_id].add(record_id)
    return tuple(
        ActiveCorrection(classification_id, TYPE_FIELD, financial_type,
                         frozenset(bound_record_ids_by_classification[classification_id]))
        for classification_id, financial_type in conn.execute(
            """SELECT id, financial_type FROM type_classification
               WHERE account_id = ? ORDER BY id""",
            (account_id,),
        )
        if states_by_id[classification_id] == STATE_ACTIVE
    )


def effective_classifications(
    active_classifications, transaction_by_record_id, effective_amount_by_transaction
) -> dict[object, FieldCorrection]:
    """The state and applied type of every classified transaction, keyed by transaction.

    As for effective_field_corrections, a transaction is whatever transaction_by_record_id maps
    records to, and effective_amount_by_transaction gives the amount totals use for each.
    """
    outcome = {}
    for (transaction, _), effect in effective_field_corrections(
        active_classifications, transaction_by_record_id
    ).items():
        if effect.state == FIELD_APPLIED and not fits_direction(
            effect.applied_value, effective_amount_by_transaction[transaction]
        ):
            effect = FieldCorrection(TYPE_AGAINST_DIRECTION, None, effect.correction_ids)
        outcome[transaction] = effect
    return outcome


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
    conn.execute(
        """DELETE FROM transaction_classification WHERE transaction_id IN
               (SELECT id FROM ledger_transaction WHERE account_id = ?)""",
        (account_id,),
    )
    active_classifications = load_active_classifications(conn, account_id)
    if not active_classifications:
        return
    effects = effective_classifications(
        active_classifications, transaction_by_record_id(conn, account_id),
        effective_amount_by_transaction(conn, account_id),
    )
    conn.executemany(
        """INSERT INTO transaction_classification (transaction_id, state, financial_type)
           VALUES (?, ?, ?)""",
        [(transaction_id, effect.state, effect.applied_value)
         for transaction_id, effect in sorted(effects.items())],
    )


def unsettled_classifications(conn: sqlite3.Connection, account_id: str) -> frozenset:
    """Transactions left unclassified because classifications disagree, lost their basis or no
    longer fit the direction, as their records and the state, so that no transaction ID is
    needed."""
    rows = conn.execute(
        """SELECT kind.transaction_id, kind.state FROM transaction_classification kind
           JOIN ledger_transaction entry ON entry.id = kind.transaction_id
           WHERE entry.account_id = ? AND kind.state <> 'applied'""",
        (account_id,),
    ).fetchall()
    if not rows:
        return frozenset()
    records_by_transaction = defaultdict(set)
    for record_id, transaction_id in transaction_by_record_id(conn, account_id).items():
        records_by_transaction[transaction_id].add(record_id)
    return frozenset(
        (frozenset(records_by_transaction[transaction_id]), state)
        for transaction_id, state in rows
    )
