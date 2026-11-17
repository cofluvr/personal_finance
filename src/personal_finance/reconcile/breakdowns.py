"""Writing loan payment breakdowns stated by a person on one transaction. See D-071 point 7.

Every command checks everything under one write lock and either commits with the ledger's
breakdowns rewritten or changes nothing. The checks and writes are reconcile/statements.py's,
shared with the other stated kinds. A breakdown moves no record and changes no amount or type: it
divides a confirmed loan payment between principal, and interest and fees.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.money import MoneyParseError, format_cents, parse_cents
from personal_finance.reconcile.breakdown_effects import (
    BREAKDOWN_STATEMENTS,
    canonical,
    confirmed_loan_payments,
    fits,
    parsed,
    write_breakdown_effects,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.statements import (
    StatementKind,
    StatementRefusals,
    make_statement,
    undo_statement,
)
from personal_finance.reports.breakdown_evidence import breakdown_undo_outlook

AMOUNT_INVALID = (
    "--interest and --fees must be amounts of zero or more, such as 57.25, and not both zero. "
    "Nothing was changed."
)
NOT_A_LOAN_PAYMENT = (
    "this transaction is not a confirmed loan payment: only money out typed loan_payment, that a "
    "transfer confirms into a loan account, takes a breakdown. Nothing was changed."
)
ABOVE_THE_PAYMENT = (
    "interest and fees of {stated} are more than the payment's {amount}. Nothing was changed."
)
BREAKDOWN_UNCHANGED = "this transaction already has this breakdown. Nothing was changed."
ALREADY_BROKEN_DOWN = (
    "breakdown {breakdown} already applies to this transaction. Nothing was changed. To replace "
    "it, inspect it with review breakdown-show, then break it down again naming it with "
    "--supersedes."
)
BREAKDOWN_UNSETTLED = (
    "breakdowns {breakdowns} bind this transaction, and they disagree, lost their basis, no "
    "longer fit or are several, so none applies. Nothing was changed. Undo all but one of them "
    "first, one at a time."
)
BREAKDOWN_ALONE_UNSETTLED = (
    "breakdown {breakdowns} binds this transaction, but lost its basis or no longer fits, so it "
    "does not apply. Nothing was changed. Undo it, or what changed the transaction, first."
)
BREAKDOWN_NOT_FOUND = "breakdown not found. Run review breakdowns."
BREAKDOWN_WRONG_ACCOUNT = "this breakdown belongs to another account. Nothing was changed."
BREAKDOWN_NOT_ACTIVE = "this breakdown has already been undone. Nothing was changed."
BREAKDOWN_SUPERSEDED = (
    "this breakdown is superseded by breakdown {newer}, so it does not apply now. Nothing was "
    "changed. Undo that breakdown instead, which restores this one."
)
BREAKDOWN_SUPERSEDED_IN_CHAIN = (
    "this breakdown is superseded by breakdown {newer}, which is superseded in turn, so it does "
    "not apply now. Nothing was changed. Only the newest breakdown of the chain, {newest}, can be "
    "undone or superseded, and each undo restores the one before it."
)
BREAKDOWN_SUPERSEDES_NOT_HERE = (
    "the breakdown named with --supersedes does not apply to this transaction. Nothing was "
    "changed."
)
STALE_BREAKDOWN_REVISION = (
    "this revision does not match the breakdown's current evidence. Nothing was changed. Run "
    "review breakdown-show and check again."
)


@dataclass(frozen=True)
class BreakdownMade:
    breakdown_id: str
    breakdown: str
    bound_record_count: int


@dataclass(frozen=True)
class BreakdownUndone:
    restored: str | None
    newly_unsettled_transactions: int


BREAKDOWNS = StatementKind(
    BREAKDOWN_STATEMENTS,
    StatementRefusals(
        unsettled=lambda ids: (BREAKDOWN_UNSETTLED if ", " in ids
                               else BREAKDOWN_ALONE_UNSETTLED).format(breakdowns=ids),
        already_applies=lambda applying: ALREADY_BROKEN_DOWN.format(breakdown=applying),
        unchanged=BREAKDOWN_UNCHANGED,
        supersedes_not_here=BREAKDOWN_SUPERSEDES_NOT_HERE,
        not_found=BREAKDOWN_NOT_FOUND,
        wrong_account=BREAKDOWN_WRONG_ACCOUNT,
        not_active=BREAKDOWN_NOT_ACTIVE,
        superseded=lambda newer: BREAKDOWN_SUPERSEDED.format(newer=newer),
        superseded_in_chain=lambda newer, newest: BREAKDOWN_SUPERSEDED_IN_CHAIN.format(
            newer=newer, newest=newest),
        stale_revision=STALE_BREAKDOWN_REVISION,
    ),
    lambda conn, breakdown: breakdown_undo_outlook(conn, breakdown).revision,
    lambda conn, _: write_breakdown_effects(conn),
)


def checked_value(interest: str, fees: str | None) -> str:
    """The canonical value of the interest and fees typed: amounts of zero or more, not both
    zero."""
    try:
        interest_cents = parse_cents(interest)
        fees_cents = 0 if fees is None else parse_cents(fees)
    except MoneyParseError:
        raise DecisionRefused(AMOUNT_INVALID) from None
    if (interest_cents is None or fees_cents is None or interest_cents < 0 or fees_cents < 0
            or interest_cents + fees_cents == 0):
        raise DecisionRefused(AMOUNT_INVALID)
    return canonical(interest_cents, fees_cents)


def break_down(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    interest: str,
    fees: str | None = None,
    rules: MatchingRules = DEFAULT_RULES,
    supersedes: str | None = None,
    supersedes_revision: str | None = None,
) -> BreakdownMade:
    """Record a loan payment's interest and fees, binding every record it holds now, as a
    categorization does (D-063, D-071 point 7)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _break_down(conn, account_id, transaction_id, revision, interest, fees, rules,
                             supersedes, supersedes_revision)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _break_down(conn, account_id, transaction_id, revision, interest, fees, rules, supersedes,
                supersedes_revision) -> BreakdownMade:
    try:
        value, refusal = checked_value(interest, fees), None
    except DecisionRefused as refused:
        value, refusal = None, refused

    def refuse_unknown_value():
        if refusal is not None:
            raise refusal

    def refuse_misfit():
        payments = confirmed_loan_payments(conn, account_id)
        if transaction_id not in payments:
            raise DecisionRefused(NOT_A_LOAN_PAYMENT)
        if not fits(payments, transaction_id, value):
            interest_cents, fees_cents = parsed(value)
            raise DecisionRefused(ABOVE_THE_PAYMENT.format(
                stated=format_cents(interest_cents + fees_cents),
                amount=format_cents(abs(payments[transaction_id]))))

    breakdown_id, bound_record_count = make_statement(
        conn, BREAKDOWNS, account_id, transaction_id, revision, value, rules, supersedes,
        supersedes_revision, refuse_unknown_value=refuse_unknown_value,
        refuse_misfit=refuse_misfit,
    )
    return BreakdownMade(breakdown_id, value, bound_record_count)


def undo_breakdown(conn: sqlite3.Connection, account_id: str, breakdown_id: str, revision: str,
                   rules: MatchingRules = DEFAULT_RULES) -> BreakdownUndone:
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = BreakdownUndone(*undo_statement(conn, BREAKDOWNS, account_id, breakdown_id,
                                                 revision, rules))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result
