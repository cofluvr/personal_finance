"""Which corrected values apply to which transactions. See decisions.md D-049.

Matching never reads anything here: derive() takes source evidence and decisions only. The
effective values are computed from memberships after derivation, and written to the derived
transaction_correction table in the caller's database transaction.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from personal_finance.reconcile.supersession import STATE_ACTIVE, supersession_chain_states

CORRECTABLE_FIELDS = ("amount", "transaction_date", "posting_date", "description")
# The ledger_transaction column holding each field's source value (D-030).
SOURCE_COLUMN_BY_FIELD = {
    "amount": "amount_cents",
    "transaction_date": "transaction_date",
    "posting_date": "posting_date",
    "description": "description",
}

FIELD_APPLIED = "applied"
FIELD_IN_CONFLICT = "conflict"
FIELD_BASIS_CHANGED = "basis_changed"


@dataclass(frozen=True)
class ActiveCorrection:
    correction_id: str
    field: str
    # Integer cents for an amount, text for the other fields.
    corrected_value: int | str
    bound_record_ids: frozenset[str]


@dataclass(frozen=True)
class FieldCorrection:
    """The outcome for one field of one transaction."""

    state: str
    # The value that applies, or None when the state leaves the source value in place.
    applied_value: int | str | None
    correction_ids: tuple[str, ...]


def correction_chain_states(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Each correction's state, and each superseded correction's successor, under D-048's rule."""
    rows = conn.execute(
        """SELECT correction.id, correction.supersedes_correction_id,
                  EXISTS (SELECT 1 FROM value_correction_event undone
                          WHERE undone.correction_id = correction.id
                            AND undone.event = 'undone')
           FROM value_correction correction WHERE correction.account_id = ?""",
        (account_id,),
    ).fetchall()
    return supersession_chain_states(rows, treated_as_undone)


def load_active_corrections(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[ActiveCorrection, ...]:
    """Active corrections with the records they bind. treated_as_undone leaves one out, restoring
    anything it superseded."""
    states_by_id, _ = correction_chain_states(conn, account_id, treated_as_undone)
    bound_record_ids_by_correction = defaultdict(set)
    for correction_id, record_id in conn.execute(
        """SELECT bound.correction_id, bound.source_record_id
           FROM value_correction_record bound
           JOIN value_correction correction ON correction.id = bound.correction_id
           WHERE correction.account_id = ?""",
        (account_id,),
    ):
        bound_record_ids_by_correction[correction_id].add(record_id)
    return tuple(
        ActiveCorrection(
            correction_id, field,
            corrected_amount_cents if field == "amount" else corrected_text,
            frozenset(bound_record_ids_by_correction[correction_id]),
        )
        for correction_id, field, corrected_amount_cents, corrected_text in conn.execute(
            """SELECT id, field, corrected_amount_cents, corrected_text FROM value_correction
               WHERE account_id = ? ORDER BY id""",
            (account_id,),
        )
        if states_by_id[correction_id] == STATE_ACTIVE
    )


def effective_field_corrections(
    active_corrections, transaction_by_record_id
) -> dict[tuple, FieldCorrection]:
    """The state and applied value of every corrected field, keyed by transaction and field.

    A transaction is whatever transaction_by_record_id maps records to, so this serves a stored
    ledger and a derivation alike. Several corrections of one field agree, disagree, or one of
    them binds records now in several transactions, and only the first applies a value (D-049).
    """
    holding_transactions_by_correction = {}
    corrections_by_transaction_and_field = defaultdict(list)
    for correction in active_corrections:
        holding = {transaction_by_record_id[record] for record in correction.bound_record_ids}
        holding_transactions_by_correction[correction.correction_id] = holding
        for transaction in holding:
            corrections_by_transaction_and_field[transaction, correction.field].append(correction)

    outcome = {}
    for key, corrections in corrections_by_transaction_and_field.items():
        correction_ids = tuple(sorted(correction.correction_id for correction in corrections))
        values = {correction.corrected_value for correction in corrections}
        if any(len(holding_transactions_by_correction[correction.correction_id]) > 1
               for correction in corrections):
            outcome[key] = FieldCorrection(FIELD_BASIS_CHANGED, None, correction_ids)
        elif len(values) > 1:
            outcome[key] = FieldCorrection(FIELD_IN_CONFLICT, None, correction_ids)
        else:
            outcome[key] = FieldCorrection(FIELD_APPLIED, next(iter(values)), correction_ids)
    return outcome


def transaction_by_record_id(conn: sqlite3.Connection, account_id: str) -> dict[str, str]:
    return dict(conn.execute(
        "SELECT source_record_id, transaction_id FROM transaction_source WHERE account_id = ?",
        (account_id,),
    ))


def write_correction_effects(conn: sqlite3.Connection, account_id: str) -> None:
    """Rewrite the account's derived rows from current memberships. The caller holds the
    transaction, and memberships must already be final."""
    effects = effective_field_corrections(
        load_active_corrections(conn, account_id), transaction_by_record_id(conn, account_id)
    )
    conn.execute(
        """DELETE FROM transaction_correction WHERE transaction_id IN
               (SELECT id FROM ledger_transaction WHERE account_id = ?)""",
        (account_id,),
    )
    conn.executemany(
        """INSERT INTO transaction_correction (transaction_id, field, state,
                                               corrected_amount_cents, corrected_text)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (transaction_id, field, effect.state,
             effect.applied_value if field == "amount" else None,
             effect.applied_value if field != "amount" else None)
            for (transaction_id, field), effect in sorted(effects.items())
        ],
    )


def unsettled_correction_fields(conn: sqlite3.Connection, account_id: str) -> frozenset:
    """Fields left on their source value because corrections disagree or lost their basis, as the
    records of their transaction, the field and the state, so that no transaction ID is needed."""
    records_by_transaction = defaultdict(set)
    for record_id, transaction_id in transaction_by_record_id(conn, account_id).items():
        records_by_transaction[transaction_id].add(record_id)
    return frozenset(
        (frozenset(records_by_transaction[transaction_id]), field, state)
        for transaction_id, field, state in conn.execute(
            """SELECT fix.transaction_id, fix.field, fix.state
               FROM transaction_correction fix
               JOIN ledger_transaction entry ON entry.id = fix.transaction_id
               WHERE entry.account_id = ? AND fix.state <> 'applied'""",
            (account_id,),
        )
    )
