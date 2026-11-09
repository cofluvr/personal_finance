"""Recording and undoing balance observations, as a person states them. See decisions.md D-057,
recommendations 2 and 3.

Each command runs under one write lock and either commits or changes nothing. An observation is
not transaction evidence, so neither command needs a current account, derives anything, or
reconciles an account for the person.
"""

import sqlite3
import uuid

from personal_finance.money import MAX_CENTS, MIN_CENTS
from personal_finance.reconcile.corrections import parsed_typed_value
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.supersession import STATE_ACTIVE
from personal_finance.reports.balances import (
    LIABILITY_ACCOUNT_TYPES,
    active_observations,
    load_observation,
    observation_revision,
)

ACCOUNT_NOT_FOUND = "account not found. Nothing was changed."
OWED_ON_AN_ASSET = (
    "--owed is for a credit card or loan, which owe money. State this account's balance with "
    "--balance. Nothing was changed."
)
BALANCE_ON_A_LIABILITY = (
    "a credit card or loan states what it owes: use --owed, positive for an amount owed and "
    "negative for a credit balance. Nothing was changed."
)
AMOUNT_INVALID = "the amount is not an exact amount of dollars and cents. Nothing was changed."
DATE_INVALID = "the date is not a valid date in the form YYYY-MM-DD. Nothing was changed."
DAY_ALREADY_OBSERVED = (
    "this account already has an active balance observation on {day}. Nothing was changed. Undo "
    "it first, with balance undo."
)
OBSERVATION_NOT_FOUND = "balance observation not found. Run balance list."
OBSERVATION_WRONG_ACCOUNT = (
    "this balance observation belongs to another account. Nothing was changed."
)
OBSERVATION_NOT_ACTIVE = "this balance observation has already been undone. Nothing was changed."
STALE_OBSERVATION_REVISION = (
    "this token does not match the balance observation and those either side of it now. Nothing "
    "was changed. Run balance list and check again."
)


def record_observation(
    conn: sqlite3.Connection,
    account_id: str,
    observed_on_text: str,
    amount_text: str,
    *,
    owed: bool,
) -> str:
    """Record a posted balance at the end of one day, returning the observation's ID.

    A credit card or loan states what it owes, stored negated in the ledger's sign convention, and
    every other account states its balance (D-003, D-057).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        observation_id = _record(conn, account_id, observed_on_text, amount_text, owed)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return observation_id


def _record(conn, account_id, observed_on_text, amount_text, owed) -> str:
    row = conn.execute("SELECT account_type FROM account WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        raise DecisionRefused(ACCOUNT_NOT_FOUND)
    is_liability = row[0] in LIABILITY_ACCOUNT_TYPES
    if owed and not is_liability:
        raise DecisionRefused(OWED_ON_AN_ASSET)
    if is_liability and not owed:
        raise DecisionRefused(BALANCE_ON_A_LIABILITY)
    # Only the amount and date fields are parsed, so no description refusal can arise.
    cents = parsed_typed_value("amount", amount_text, AMOUNT_INVALID, DATE_INVALID, AMOUNT_INVALID)
    observed_on = parsed_typed_value("posting_date", observed_on_text, AMOUNT_INVALID,
                                     DATE_INVALID, DATE_INVALID)
    balance_cents = -cents if owed else cents
    # Negating the lowest amount leaves the range of a SQLite INTEGER.
    if not MIN_CENTS <= balance_cents <= MAX_CENTS:
        raise DecisionRefused(AMOUNT_INVALID)
    if any(observation.observed_on == observed_on
           for observation in active_observations(conn, account_id)):
        raise DecisionRefused(DAY_ALREADY_OBSERVED.format(day=observed_on))

    observation_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO balance_observation (id, account_id, observed_on, balance_cents)
           VALUES (?, ?, ?, ?)""",
        (observation_id, account_id, observed_on, balance_cents),
    )
    _record_event(conn, observation_id, "made")
    return observation_id


def undo_observation(
    conn: sqlite3.Connection,
    account_id: str,
    observation_id: str,
    revision: str,
) -> None:
    """Stop an observation applying, keeping it on record. The intervals either side of it join
    into one, exactly as before it was recorded."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        _undo(conn, account_id, observation_id, revision)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _undo(conn, account_id, observation_id, revision) -> None:
    observation = load_observation(conn, observation_id)
    if observation is None:
        raise DecisionRefused(OBSERVATION_NOT_FOUND)
    if observation.account_id != account_id:
        raise DecisionRefused(OBSERVATION_WRONG_ACCOUNT)
    if observation.state != STATE_ACTIVE:
        raise DecisionRefused(OBSERVATION_NOT_ACTIVE)
    if observation_revision(conn, observation) != revision:
        raise DecisionRefused(STALE_OBSERVATION_REVISION)
    _record_event(conn, observation_id, "undone")


def _record_event(conn, observation_id, event) -> None:
    conn.execute(
        "INSERT INTO balance_observation_event (balance_observation_id, event) VALUES (?, ?)",
        (observation_id, event),
    )
