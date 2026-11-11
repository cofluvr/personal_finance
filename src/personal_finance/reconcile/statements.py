"""Making and undoing a statement of a type, a category or an allocation on one transaction (D-053,
D-063, D-065).

The caller holds the write lock and commits or rolls back. Every check runs before anything is
written, in D-043's order: the account is current, then the value is known, then account,
transaction and revision together. A statement moves no record and changes no amount, so nothing
is derived again: only the derived outcomes are rewritten.
"""

import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from personal_finance.reconcile import stated_fields
from personal_finance.reconcile.apply import is_current
from personal_finance.reconcile.correction_effects import FIELD_APPLIED
from personal_finance.reconcile.decisions import STALE_ACCOUNT, DecisionRefused
from personal_finance.reconcile.rules import MatchingRules
from personal_finance.reconcile.stated_fields import StatedField
from personal_finance.reconcile.supersession import STATE_ACTIVE, STATE_SUPERSEDED
from personal_finance.reports.review_evidence import load_merge_evidence, transaction_revision
from personal_finance.reports.stated_evidence import StoredStatement, load_statement

TRANSACTION_NOT_FOUND = (
    "transaction not found. A later import or decision can retire one: run transactions"
)
TRANSACTION_WRONG_ACCOUNT = "this transaction belongs to another account. Nothing was changed."
STALE_TRANSACTION_REVISION = (
    "this revision does not match the transaction's current evidence. Nothing was changed. "
    "Run review transaction show and check the evidence again."
)


@dataclass(frozen=True)
class StatementRefusals:
    """What a refusal says, in the words of one field."""

    # Given the IDs of the statements reaching the transaction, joined.
    unsettled: Callable[[str], str]
    # Given the ID of the statement applying there.
    already_applies: Callable[[str], str]
    unchanged: str
    supersedes_not_here: str
    not_found: str
    wrong_account: str
    not_active: str
    # Given the ID superseding it, and for a chain the newest too.
    superseded: Callable[[str], str]
    superseded_in_chain: Callable[[str, str], str]
    stale_revision: str


@dataclass(frozen=True)
class StatementKind:
    stated: StatedField
    refusals: StatementRefusals
    # The undo token of an active statement.
    undo_revision: Callable[[sqlite3.Connection, StoredStatement], str]
    # Rewrites the derived outcomes once the statement or its undo is written.
    rewrite_effects: Callable[[sqlite3.Connection, str], None]
    # Writes what the stored value names beyond its own column, given the new statement's ID and
    # the value, before its 'made' event: an allocation's parts (D-065).
    write_value: Callable[[sqlite3.Connection, str, object], None] | None = None


def make_statement(
    conn: sqlite3.Connection, kind: StatementKind, account_id: str, transaction_id: str,
    revision: str, value, rules: MatchingRules, supersedes: str | None,
    supersedes_revision: str | None, *, refuse_unknown_value: Callable[[], None],
    refuse_misfit: Callable[[], None],
) -> tuple[str, int]:
    """Record a value stated on a transaction, binding every record it holds now (D-049).

    refuse_unknown_value runs once the account is known to be current, and refuse_misfit last,
    once the value is known to change something. Returns the statement's ID and how many records
    it binds.
    """
    stated, refusals = kind.stated, kind.refusals
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    refuse_unknown_value()
    merge = load_merge_evidence(conn, transaction_id)
    if merge is None:
        raise DecisionRefused(TRANSACTION_NOT_FOUND)
    if merge.account_id != account_id:
        raise DecisionRefused(TRANSACTION_WRONG_ACCOUNT)
    if transaction_revision(merge) != revision:
        raise DecisionRefused(STALE_TRANSACTION_REVISION)
    superseded = None
    if supersedes:
        superseded = checked_for_replacing(conn, kind, account_id, supersedes, supersedes_revision)

    record_ids = {record.record_id for record in merge.transaction.records}
    applying = [
        statement for statement in stated_fields.load_active(conn, stated, account_id)
        if statement.bound_record_ids & record_ids
    ]
    applying_ids = sorted(statement.correction_id for statement in applying)
    state = stated_fields.derived_state(conn, stated, transaction_id)
    if len(applying) > 1 or (applying and state != FIELD_APPLIED):
        raise DecisionRefused(refusals.unsettled(", ".join(applying_ids)))
    if superseded is not None and superseded.statement_id not in applying_ids:
        raise DecisionRefused(refusals.supersedes_not_here)
    if applying and superseded is None:
        raise DecisionRefused(refusals.already_applies(applying_ids[0]))
    if applying and applying[0].corrected_value == value:
        raise DecisionRefused(refusals.unchanged)
    refuse_misfit()

    statement_id = str(uuid.uuid4())
    conn.execute(
        f"""INSERT INTO {stated.statement_table} (id, account_id, {stated.value_column},
                                                  target_transaction_id, target_revision,
                                                  {stated.supersedes_column})
            VALUES (?, ?, ?, ?, ?, ?)""",
        (statement_id, account_id, value, transaction_id, revision,
         superseded and superseded.statement_id),
    )
    conn.executemany(
        f"""INSERT INTO {stated.record_table} ({stated.statement_column}, source_record_id)
            VALUES (?, ?)""",
        [(statement_id, record_id) for record_id in sorted(record_ids)],
    )
    if kind.write_value is not None:
        kind.write_value(conn, statement_id, value)
    _record_event(conn, stated, statement_id, "made")
    kind.rewrite_effects(conn, account_id)
    return statement_id, len(record_ids)


def checked_for_replacing(conn, kind: StatementKind, account_id, statement_id,
                          revision) -> StoredStatement:
    """A statement being superseded or undone, checked as D-043 checks a decision."""
    refusals = kind.refusals
    statement = load_statement(conn, kind.stated, statement_id)
    if statement is None:
        raise DecisionRefused(refusals.not_found)
    if statement.account_id != account_id:
        raise DecisionRefused(refusals.wrong_account)
    if statement.state == STATE_SUPERSEDED:
        if statement.newest_of_chain != statement.superseded_by:
            raise DecisionRefused(refusals.superseded_in_chain(statement.superseded_by,
                                                               statement.newest_of_chain))
        raise DecisionRefused(refusals.superseded(statement.superseded_by))
    if statement.state != STATE_ACTIVE:
        raise DecisionRefused(refusals.not_active)
    if kind.undo_revision(conn, statement) != revision:
        raise DecisionRefused(refusals.stale_revision)
    return statement


def undo_statement(conn: sqlite3.Connection, kind: StatementKind, account_id: str,
                   statement_id: str, revision: str, rules: MatchingRules) -> tuple[str | None, int]:
    """Stop a statement applying, keeping it on record, and restore anything it superseded.

    Statements constrain no identity, so this never refuses for contradiction. Returns the
    statement restored, and how many transactions it leaves where statements reach and none
    applies that were not before (D-049).
    """
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    statement = checked_for_replacing(conn, kind, account_id, statement_id, revision)
    unsettled_before = stated_fields.unsettled(conn, kind.stated, account_id)
    _record_event(conn, kind.stated, statement_id, "undone")
    kind.rewrite_effects(conn, account_id)
    newly_unsettled = stated_fields.unsettled(conn, kind.stated, account_id) - unsettled_before
    return statement.supersedes_id, len(newly_unsettled)


def _record_event(conn, stated: StatedField, statement_id, event) -> None:
    conn.execute(
        f"INSERT INTO {stated.event_table} ({stated.statement_column}, event) VALUES (?, ?)",
        (statement_id, event),
    )
