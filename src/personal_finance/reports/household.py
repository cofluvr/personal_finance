"""The household report: each transaction's effective amount by who it belongs to, in D-056's groups
(D-065 point 8).

Everything here reads the ledger and nothing writes to it. Each transaction is attributed as
reconcile/household_effects.py resolves it and counted by IncomeAndSpendingTally, as totals counts
it, so every column's groups follow D-056 and D-063 exactly. A member's column counts that member's
parts. Parts sum to their transaction's amount, so each row's members and unattributed add to the
household exactly, in amounts. Each transaction is in the month of its effective transaction date,
else its effective posting date, as report monthly places it.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from personal_finance.reconcile.category_effects import CONFIRMED_TRANSFER_SQL
from personal_finance.reconcile.household_effects import (
    ALLOCATED,
    PERSONAL,
    SHARED,
    UNATTRIBUTED,
    Household,
    attributed_transactions,
    load_household,
)
from personal_finance.reports.totals import GroupTotal, IncomeAndSpending, IncomeAndSpendingTally

SIDE_BY_SIDE = "side_by_side"
ONE_MEMBER = "member"
SHARED_ONLY = "shared"

HOUSEHOLD_COLUMN = "household"
WHOLE_COLUMN = "whole"


@dataclass(frozen=True)
class Column:
    heading: str
    groups: IncomeAndSpending


@dataclass(frozen=True)
class HouseholdReport:
    view: str
    household: Household
    columns: tuple[Column, ...]
    # Transactions in scope left unattributed, by why: no_default, no_share, or the state of
    # allocations that do not apply.
    unattributed_by_reason: tuple[tuple[str, GroupTotal], ...]
    # The account defaults in scope, as (account name, member ID or None for shared), and the
    # accounts in scope with none.
    defaults: tuple[tuple[str, int | None], ...]
    accounts_without_default: tuple[str, ...]
    # Transactions of the scope dated outside the months asked for.
    transactions_outside_range: int
    # For the shared view: transactions divided among more than one member, in scope.
    transactions_shown: int


def household_report(conn: sqlite3.Connection, account_id: str | None = None,
                     first_month: str | None = None, last_month: str | None = None,
                     member_id: int | None = None, shared_only: bool = False) -> HouseholdReport:
    """The side-by-side view, or one member's parts, or the transactions shared among members."""
    household = load_household(conn)
    facts = _facts(conn, account_id)
    view = ONE_MEMBER if member_id is not None else SHARED_ONLY if shared_only else SIDE_BY_SIDE
    tallies = defaultdict(IncomeAndSpendingTally)
    unattributed = defaultdict(GroupTotal)
    outside = shown = 0
    for entry in attributed_transactions(conn, household, account_id):
        month, financial_type, confirmed, category_id = facts[entry.transaction_id]
        if (first_month and month < first_month) or (last_month and month > last_month):
            outside += 1
            continue
        attribution = entry.attribution

        def add(column, cents):
            tallies[column].add(cents, financial_type, confirmed, category_id)

        if attribution.kind == UNATTRIBUTED:
            unattributed[attribution.reason] = unattributed[attribution.reason].adding(
                entry.amount_cents)
        if view == SIDE_BY_SIDE:
            add(HOUSEHOLD_COLUMN, entry.amount_cents)
            if attribution.kind == UNATTRIBUTED:
                add(UNATTRIBUTED, entry.amount_cents)
            for part_member, cents in attribution.parts:
                add(part_member, cents)
        elif view == ONE_MEMBER:
            for part_member, cents in attribution.parts:
                if part_member == member_id:
                    add(attribution.kind, cents)
                    add(HOUSEHOLD_COLUMN, cents)
        elif len(attribution.parts) > 1:
            shown += 1
            add(WHOLE_COLUMN, entry.amount_cents)
            for part_member, cents in attribution.parts:
                add(part_member, cents)

    names = {member.member_id: member.name for member in household.members}
    if view == SIDE_BY_SIDE:
        order = [*names, UNATTRIBUTED, HOUSEHOLD_COLUMN]
        headings = {**names, UNATTRIBUTED: UNATTRIBUTED, HOUSEHOLD_COLUMN: HOUSEHOLD_COLUMN}
    elif view == ONE_MEMBER:
        order = [PERSONAL, SHARED, ALLOCATED, HOUSEHOLD_COLUMN]
        headings = {PERSONAL: PERSONAL, SHARED: SHARED, ALLOCATED: ALLOCATED,
                    HOUSEHOLD_COLUMN: names[member_id]}
    else:
        order = [*names, WHOLE_COLUMN]
        headings = {**names, WHOLE_COLUMN: WHOLE_COLUMN}

    accounts = conn.execute(
        """SELECT id, display_name FROM account WHERE :account IS NULL OR id = :account
           ORDER BY display_name, id""", {"account": account_id}).fetchall()
    return HouseholdReport(
        view, household,
        tuple(Column(headings[column], tallies[column].result()) for column in order),
        tuple(sorted(unattributed.items())),
        tuple((name, household.defaults[account].member_id) for account, name in accounts
              if account in household.defaults),
        tuple(name for account, name in accounts if account not in household.defaults),
        outside, shown,
    )


def _facts(conn, account_id) -> dict[str, tuple]:
    """Each transaction's month, applied type, whether a transfer is confirmed there, and its
    category, as report monthly reads them."""
    return {
        transaction_id: ((transaction_date or posting_date)[:7], financial_type, confirmed,
                         category_id)
        for transaction_id, transaction_date, posting_date, financial_type, confirmed, category_id
        in conn.execute(
            f"""SELECT entry.id,
                       COALESCE(date_fix.corrected_text, entry.transaction_date),
                       COALESCE(posting_fix.corrected_text, entry.posting_date),
                       kind.financial_type, {CONFIRMED_TRANSFER_SQL},
                       COALESCE(categorized.category_id, by_rules.category_id)
                FROM ledger_transaction entry
                LEFT JOIN transaction_correction date_fix
                    ON date_fix.transaction_id = entry.id AND date_fix.field = 'transaction_date'
                   AND date_fix.state = 'applied'
                LEFT JOIN transaction_correction posting_fix
                    ON posting_fix.transaction_id = entry.id AND posting_fix.field = 'posting_date'
                   AND posting_fix.state = 'applied'
                LEFT JOIN transaction_classification kind ON kind.transaction_id = entry.id
                LEFT JOIN transaction_category categorized
                    ON categorized.transaction_id = entry.id AND categorized.state = 'applied'
                LEFT JOIN transaction_rule_category by_rules
                    ON by_rules.transaction_id = entry.id AND by_rules.state = 'applied'
                WHERE :account IS NULL OR entry.account_id = :account""",
            {"account": account_id},
        )
    }
