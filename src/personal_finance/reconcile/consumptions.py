"""Writing fund consumptions stated by a person on one transaction. See D-070 point 5.

Every command checks everything under one write lock and either commits with the ledger's
consumptions rewritten or changes nothing. The checks and writes are reconcile/statements.py's,
shared with types, categories and allocations (D-053, D-063, D-065). A consumption moves no record
and changes no amount, type, category, allocation or transfer, so only consumptions are rewritten.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.category_effects import spending_transactions
from personal_finance.reconcile.consumption_effects import (
    CONSUMPTION_STATEMENTS,
    write_consumption_effects,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.statements import (
    StatementKind,
    StatementRefusals,
    make_statement,
    undo_statement,
)
from personal_finance.reports.consumption_evidence import consumption_undo_outlook

# The kinds a transaction can be paid from (point 5). The emergency fund is restored, never
# consumed, until M16.
CONSUMED_KINDS = ("goal", "reserve", "tax")

FUND_UNKNOWN = "fund not found, or undone. Run funds. Nothing was changed."
FUND_NOT_CONSUMED = (
    "fund {fund} is the emergency fund: only a goal, a reserve or the tax reserve pays for a "
    "transaction. Nothing was changed."
)
NOT_SPENDING_REFUSAL = (
    "this transaction is not spending: only a purchase, fee, interest or refund on which no "
    "transfer is confirmed is paid from a fund. Nothing was changed."
)
CONSUMPTION_UNCHANGED = "this transaction is already paid from this fund. Nothing was changed."
ALREADY_CONSUMED = (
    "consumption {consumption} already applies to this transaction. Nothing was changed. To "
    "replace it, inspect it with review consumption show, then consume again naming it with "
    "--supersedes."
)
CONSUMPTION_UNSETTLED = (
    "consumptions {consumptions} bind this transaction, and they disagree, lost their basis, are "
    "no longer on spending or are several, so it is paid from no fund. Nothing was changed. Undo "
    "all but one of them first, one at a time."
)
CONSUMPTION_ALONE_UNSETTLED = (
    "consumption {consumptions} binds this transaction, but lost its basis or is no longer on "
    "spending, so it is paid from no fund. Nothing was changed. Undo it, or what changed the "
    "transaction, first."
)
CONSUMPTION_NOT_FOUND = "consumption not found. Run review consumptions."
CONSUMPTION_WRONG_ACCOUNT = "this consumption belongs to another account. Nothing was changed."
CONSUMPTION_NOT_ACTIVE = "this consumption has already been undone. Nothing was changed."
CONSUMPTION_SUPERSEDED = (
    "this consumption is superseded by consumption {newer}, so it does not apply now. Nothing was "
    "changed. Undo that consumption instead, which restores this one."
)
CONSUMPTION_SUPERSEDED_IN_CHAIN = (
    "this consumption is superseded by consumption {newer}, which is superseded in turn, so it "
    "does not apply now. Nothing was changed. Only the newest consumption of the chain, {newest}, "
    "can be undone or superseded, and each undo restores the one before it."
)
CONSUMPTION_SUPERSEDES_NOT_HERE = (
    "the consumption named with --supersedes does not apply to this transaction. Nothing was "
    "changed."
)
STALE_CONSUMPTION_REVISION = (
    "this revision does not match the consumption's current evidence. Nothing was changed. Run "
    "review consumption show and check again."
)


@dataclass(frozen=True)
class ConsumptionMade:
    consumption_id: str
    fund_id: str
    bound_record_count: int


@dataclass(frozen=True)
class ConsumptionUndone:
    # The consumption this one superseded, which applies again.
    restored: str | None
    # Transactions this undo leaves paid from no fund for a disagreement, a changed basis or no
    # longer being spending, and that were not before.
    newly_unsettled_transactions: int


CONSUMPTIONS = StatementKind(
    CONSUMPTION_STATEMENTS,
    StatementRefusals(
        unsettled=lambda ids: (CONSUMPTION_UNSETTLED if ", " in ids
                               else CONSUMPTION_ALONE_UNSETTLED).format(consumptions=ids),
        already_applies=lambda applying: ALREADY_CONSUMED.format(consumption=applying),
        unchanged=CONSUMPTION_UNCHANGED,
        supersedes_not_here=CONSUMPTION_SUPERSEDES_NOT_HERE,
        not_found=CONSUMPTION_NOT_FOUND,
        wrong_account=CONSUMPTION_WRONG_ACCOUNT,
        not_active=CONSUMPTION_NOT_ACTIVE,
        superseded=lambda newer: CONSUMPTION_SUPERSEDED.format(newer=newer),
        superseded_in_chain=lambda newer, newest: CONSUMPTION_SUPERSEDED_IN_CHAIN.format(
            newer=newer, newest=newest),
        stale_revision=STALE_CONSUMPTION_REVISION,
    ),
    lambda conn, consumption: consumption_undo_outlook(conn, consumption).revision,
    lambda conn, _: write_consumption_effects(conn),
)


def checked_fund(conn: sqlite3.Connection, fund_id: str) -> str:
    """An active goal, reserve or tax reserve, by ID."""
    row = conn.execute(
        """SELECT fund.kind FROM fund WHERE fund.id = ? AND NOT EXISTS (
               SELECT 1 FROM fund_event undone
               WHERE undone.fund_id = fund.id AND undone.event = 'undone')""",
        (fund_id,)).fetchone()
    if row is None:
        raise DecisionRefused(FUND_UNKNOWN)
    if row[0] not in CONSUMED_KINDS:
        raise DecisionRefused(FUND_NOT_CONSUMED.format(fund=fund_id))
    return fund_id


def consume_transaction(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    fund_id: str,
    rules: MatchingRules = DEFAULT_RULES,
    supersedes: str | None = None,
    supersedes_revision: str | None = None,
) -> ConsumptionMade:
    """Record that a spending transaction is paid from a fund, binding every record it holds now,
    as a categorization does (D-063, D-070 point 5). supersedes names the one consumption applying
    there, with its undo token."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _consume(conn, account_id, transaction_id, revision, fund_id, rules, supersedes,
                          supersedes_revision)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _consume(conn, account_id, transaction_id, revision, fund_id, rules, supersedes,
             supersedes_revision) -> ConsumptionMade:
    def refuse_unknown_value():
        checked_fund(conn, fund_id)

    def refuse_unless_spending():
        if transaction_id not in spending_transactions(conn, account_id):
            raise DecisionRefused(NOT_SPENDING_REFUSAL)

    consumption_id, bound_record_count = make_statement(
        conn, CONSUMPTIONS, account_id, transaction_id, revision, fund_id, rules, supersedes,
        supersedes_revision, refuse_unknown_value=refuse_unknown_value,
        refuse_misfit=refuse_unless_spending,
    )
    return ConsumptionMade(consumption_id, fund_id, bound_record_count)


def undo_consumption(
    conn: sqlite3.Connection,
    account_id: str,
    consumption_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> ConsumptionUndone:
    """Stop a consumption applying, keeping it on record, and restore anything it superseded. It
    never refuses for contradiction, and says when it leaves a transaction paid from no fund for a
    disagreement (D-049, D-070)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = ConsumptionUndone(*undo_statement(
            conn, CONSUMPTIONS, account_id, consumption_id, revision, rules))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result
