"""A field with no source value that a person states on one transaction: its financial type (D-053)
or its category (D-063).

Both are stored the same way, as a statement anchored on the records of its transaction, those
records, and its made and undone events, with one derived row per transaction holding the outcome.
Both follow D-049's effective-value rule, shared with corrections, and D-048's chains. A
StatedField names one field's tables, and the caller supplies where a value fits. Matching never
reads anything here.
"""

import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from personal_finance.reconcile.correction_effects import (
    FIELD_APPLIED,
    ActiveCorrection,
    FieldCorrection,
    effective_field_corrections,
    transaction_by_record_id,
)
from personal_finance.reconcile.supersession import STATE_ACTIVE, supersession_chain_states


@dataclass(frozen=True)
class StatedField:
    # The field name under which statements share D-049's effective-value rule.
    field_name: str
    statement_table: str
    # The column holding the stated value, and an SQL expression over the statement, aliased
    # `statement`, giving the value as shown to a person.
    value_column: str
    shown_value_sql: str
    supersedes_column: str
    record_table: str
    event_table: str
    # The column naming the statement in its record and event tables.
    statement_column: str
    derived_table: str
    derived_value_column: str
    # The outcome of a single agreeing statement whose value no longer fits its transaction.
    misfit_state: str


# Whether a value fits a transaction, given the transaction as transaction_by_record_id names it.
Fits = Callable[[object, object], bool]


def chain_states(
    conn: sqlite3.Connection, stated: StatedField, account_id: str,
    treated_as_undone: str | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Each statement's state, and each superseded one's successor, under D-048's rule."""
    rows = conn.execute(
        f"""SELECT statement.id, statement.{stated.supersedes_column},
                   EXISTS (SELECT 1 FROM {stated.event_table} undone
                           WHERE undone.{stated.statement_column} = statement.id
                             AND undone.event = 'undone')
            FROM {stated.statement_table} statement WHERE statement.account_id = ?""",
        (account_id,),
    ).fetchall()
    return supersession_chain_states(rows, treated_as_undone)


def load_active(
    conn: sqlite3.Connection, stated: StatedField, account_id: str,
    treated_as_undone: str | None = None,
) -> tuple[ActiveCorrection, ...]:
    """Active statements as corrections of the field, whose value is the stated one and whose
    correction_id is the statement's ID. treated_as_undone leaves one out, restoring anything it
    superseded."""
    states_by_id, _ = chain_states(conn, stated, account_id, treated_as_undone)
    bound_record_ids_by_statement = defaultdict(set)
    for statement_id, record_id in conn.execute(
        f"""SELECT bound.{stated.statement_column}, bound.source_record_id
            FROM {stated.record_table} bound
            JOIN {stated.statement_table} statement
                ON statement.id = bound.{stated.statement_column}
            WHERE statement.account_id = ?""",
        (account_id,),
    ):
        bound_record_ids_by_statement[statement_id].add(record_id)
    return tuple(
        ActiveCorrection(statement_id, stated.field_name, value,
                         frozenset(bound_record_ids_by_statement[statement_id]))
        for statement_id, value in conn.execute(
            f"""SELECT id, {stated.value_column} FROM {stated.statement_table}
                WHERE account_id = ? ORDER BY id""",
            (account_id,),
        )
        if states_by_id[statement_id] == STATE_ACTIVE
    )


def effective_values(
    stated: StatedField, active_statements, transaction_by_record_id, fits: Fits,
) -> dict[object, FieldCorrection]:
    """The state and applied value of every transaction a statement reaches, keyed by transaction.

    As for effective_field_corrections, a transaction is whatever transaction_by_record_id maps
    records to. A single agreeing value that does not fit takes the field's misfit state.
    """
    outcome = {}
    for (transaction, _), effect in effective_field_corrections(
        active_statements, transaction_by_record_id
    ).items():
        if effect.state == FIELD_APPLIED and not fits(transaction, effect.applied_value):
            effect = FieldCorrection(stated.misfit_state, None, effect.correction_ids)
        outcome[transaction] = effect
    return outcome


def write_effects(conn: sqlite3.Connection, stated: StatedField, account_id: str,
                  fits: Fits) -> None:
    """Rewrite the account's derived rows from current memberships. The caller holds the
    transaction, and everything fits reads must already be final."""
    conn.execute(
        f"""DELETE FROM {stated.derived_table} WHERE transaction_id IN
                (SELECT id FROM ledger_transaction WHERE account_id = ?)""",
        (account_id,),
    )
    effects = effective_values(stated, load_active(conn, stated, account_id),
                               transaction_by_record_id(conn, account_id), fits)
    conn.executemany(
        f"""INSERT INTO {stated.derived_table}
                (transaction_id, state, {stated.derived_value_column})
            VALUES (?, ?, ?)""",
        [(transaction_id, effect.state, effect.applied_value)
         for transaction_id, effect in sorted(effects.items())],
    )


def unsettled(conn: sqlite3.Connection, stated: StatedField, account_id: str) -> frozenset:
    """Transactions where statements reach and none applies, as their records and the state, so
    that no transaction ID is needed."""
    rows = conn.execute(
        f"""SELECT derived.transaction_id, derived.state FROM {stated.derived_table} derived
            JOIN ledger_transaction entry ON entry.id = derived.transaction_id
            WHERE entry.account_id = ? AND derived.state <> 'applied'""",
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


def derived_state(conn: sqlite3.Connection, stated: StatedField, transaction_id: str) -> str | None:
    """The outcome on one transaction, or None where no statement reaches it."""
    row = conn.execute(
        f"SELECT state FROM {stated.derived_table} WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()
    return row and row[0]
