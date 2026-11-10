"""Writing allocations stated by a person on one transaction. See decisions.md D-065.

Every command checks everything under one write lock and either commits with the ledger's
allocations rewritten or changes nothing. The checks and writes are reconcile/statements.py's,
shared with types and categories (D-053, D-063). An allocation moves no record and changes no
amount, type, category or transfer, so only allocations are rewritten.
"""

import re
import sqlite3
from dataclasses import dataclass

from personal_finance.money import parse_cents
from personal_finance.reconcile.allocation_effects import (
    ALLOCATION_STATEMENTS,
    write_allocation_effects,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.household import (
    ATTRIBUTION_WITHOUT_SHARE,
    MEMBER_UNKNOWN,
    SHARE_MEMBER_REPEATED,
    checked_parts,
)
from personal_finance.reconcile.household_effects import (
    BY_AMOUNT,
    BY_MEMBER,
    BY_PERCENT,
    BY_SHARE,
    WHOLE_IN_BASIS_POINTS,
    canonical,
    effective_amounts,
    load_household,
    parsed,
)
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.statements import (
    StatementKind,
    StatementRefusals,
    make_statement,
    undo_statement,
)
from personal_finance.reports.allocation_evidence import allocation_undo_outlook

# A part by amount as typed: a magnitude in dollars, with at most two decimals.
_AMOUNT = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,2})?")

AMOUNT_PART_MALFORMED = (
    "each --amount must be NAME=AMOUNT, the amount above zero in dollars and cents, as M=12.50. "
    "Nothing was changed."
)
AMOUNTS_NOT_WHOLE = (
    "the amounts must sum to exactly the transaction's effective amount, as review transaction "
    "show gives it, ignoring its sign. Nothing was changed."
)
ALLOCATION_UNCHANGED = "this transaction already has this allocation. Nothing was changed."
ALREADY_ALLOCATED = (
    "allocation {allocation} already applies to this transaction. Nothing was changed. To replace "
    "it, inspect it with review allocation show, then allocate again naming it with --supersedes."
)
ALLOCATION_UNSETTLED = (
    "allocations {allocations} bind this transaction, and they disagree, lost their basis, no "
    "longer sum to its amount or are several, so it is unattributed. Nothing was changed. Undo all "
    "but one of them first, one at a time."
)
ALLOCATION_NOT_FOUND = "allocation not found. Run review allocations."
ALLOCATION_WRONG_ACCOUNT = "this allocation belongs to another account. Nothing was changed."
ALLOCATION_NOT_ACTIVE = "this allocation has already been undone. Nothing was changed."
ALLOCATION_SUPERSEDED = (
    "this allocation is superseded by allocation {newer}, so it does not apply now. Nothing was "
    "changed. Undo that allocation instead, which restores this one."
)
ALLOCATION_SUPERSEDED_IN_CHAIN = (
    "this allocation is superseded by allocation {newer}, which is superseded in turn, so it does "
    "not apply now. Nothing was changed. Only the newest allocation of the chain, {newest}, can be "
    "undone or superseded, and each undo restores the one before it."
)
ALLOCATION_SUPERSEDES_NOT_HERE = (
    "the allocation named with --supersedes does not apply to this transaction. Nothing was "
    "changed."
)
STALE_ALLOCATION_REVISION = (
    "this revision does not match the allocation's current evidence. Nothing was changed. Run "
    "review allocation show and check again."
)


@dataclass(frozen=True)
class AllocationMade:
    allocation_id: str
    # The canonical value stored.
    allocation: str
    bound_record_count: int


@dataclass(frozen=True)
class AllocationUndone:
    # The allocation this one superseded, which applies again.
    restored: str | None
    # Transactions this undo leaves unattributed for a disagreement, a changed basis or amounts no
    # longer summing, and that were not before.
    newly_unattributed_transactions: int


def write_parts(conn: sqlite3.Connection, allocation_id: str, value: str) -> None:
    """The parts the canonical value names, which the schema checks against it when made."""
    conn.executemany(
        "INSERT INTO allocation_statement_part (allocation_id, member_id, value) VALUES (?, ?, ?)",
        [(allocation_id, member_id, part) for member_id, part in parsed(value)[1]],
    )


ALLOCATIONS = StatementKind(
    ALLOCATION_STATEMENTS,
    StatementRefusals(
        unsettled=lambda ids: ALLOCATION_UNSETTLED.format(allocations=ids),
        already_applies=lambda applying: ALREADY_ALLOCATED.format(allocation=applying),
        unchanged=ALLOCATION_UNCHANGED,
        supersedes_not_here=ALLOCATION_SUPERSEDES_NOT_HERE,
        not_found=ALLOCATION_NOT_FOUND,
        wrong_account=ALLOCATION_WRONG_ACCOUNT,
        not_active=ALLOCATION_NOT_ACTIVE,
        superseded=lambda newer: ALLOCATION_SUPERSEDED.format(newer=newer),
        superseded_in_chain=lambda newer, newest: ALLOCATION_SUPERSEDED_IN_CHAIN.format(
            newer=newer, newest=newest),
        stale_revision=STALE_ALLOCATION_REVISION,
    ),
    lambda conn, allocation: allocation_undo_outlook(conn, allocation).revision,
    lambda conn, _: write_allocation_effects(conn),
    write_value=write_parts,
)


@dataclass(frozen=True)
class Stated:
    """What a person typed: one member, shared, percentages or amounts, each NAME=VALUE."""

    member: str | None = None
    shared: bool = False
    percents: tuple[str, ...] = ()
    amounts: tuple[str, ...] = ()


def checked_value(conn: sqlite3.Connection, stated: Stated) -> str:
    """The canonical value of what was typed, refused if it names an unknown member, malformed or
    repeated parts, one percentage, percentages not summing to 100.00, or shared with no share."""
    household = load_household(conn)
    if stated.member is not None:
        member = household.find_member(stated.member)
        if member is None:
            raise DecisionRefused(MEMBER_UNKNOWN)
        return canonical(BY_MEMBER, [(member.member_id, WHOLE_IN_BASIS_POINTS)])
    if stated.shared:
        if household.share is None:
            raise DecisionRefused(ATTRIBUTION_WITHOUT_SHARE)
        return canonical(BY_SHARE, [])
    if stated.percents:
        return canonical(BY_PERCENT, checked_parts(household, list(stated.percents)))
    parts = {}
    for typed in stated.amounts:
        name, separator, amount = typed.rpartition("=")
        if not separator or not _AMOUNT.fullmatch(amount):
            raise DecisionRefused(AMOUNT_PART_MALFORMED)
        cents = parse_cents(amount)
        if cents <= 0:
            raise DecisionRefused(AMOUNT_PART_MALFORMED)
        member = household.find_member(name)
        if member is None:
            raise DecisionRefused(MEMBER_UNKNOWN)
        if member.member_id in parts:
            raise DecisionRefused(SHARE_MEMBER_REPEATED)
        parts[member.member_id] = cents
    return canonical(BY_AMOUNT, parts.items())


def allocate_transaction(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    stated: Stated,
    rules: MatchingRules = DEFAULT_RULES,
    supersedes: str | None = None,
    supersedes_revision: str | None = None,
) -> AllocationMade:
    """Record who a transaction's effective amount belongs to, binding every record it holds now,
    as a categorization does (D-063, D-065). supersedes names the one allocation applying there,
    with its undo token."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _allocate(conn, account_id, transaction_id, revision, stated, rules, supersedes,
                           supersedes_revision)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _allocate(conn, account_id, transaction_id, revision, stated, rules, supersedes,
              supersedes_revision) -> AllocationMade:
    # Checked here, but refused only once the account is known to be current (D-043).
    try:
        value, refusal = checked_value(conn, stated), None
    except DecisionRefused as refused:
        value, refusal = None, refused

    def refuse_unknown_value():
        if refusal is not None:
            raise refusal

    def refuse_unless_summing():
        kind, parts = parsed(value)
        if kind != BY_AMOUNT:
            return
        ((_, _, amount_cents),) = effective_amounts(conn, transaction_ids=[transaction_id])
        if sum(part for _, part in parts) != abs(amount_cents):
            raise DecisionRefused(AMOUNTS_NOT_WHOLE)

    allocation_id, bound_record_count = make_statement(
        conn, ALLOCATIONS, account_id, transaction_id, revision, value, rules, supersedes,
        supersedes_revision, refuse_unknown_value=refuse_unknown_value,
        refuse_misfit=refuse_unless_summing,
    )
    return AllocationMade(allocation_id, value, bound_record_count)


def undo_allocation(
    conn: sqlite3.Connection,
    account_id: str,
    allocation_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> AllocationUndone:
    """Stop an allocation applying, keeping it on record, and restore anything it superseded. It
    never refuses for contradiction, and says when it leaves a transaction unattributed for a
    disagreement (D-049, D-065)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = AllocationUndone(*undo_statement(
            conn, ALLOCATIONS, account_id, allocation_id, revision, rules))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result
