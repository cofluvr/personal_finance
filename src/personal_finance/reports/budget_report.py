"""pf report budget (D-069 points 3 to 5, M13.2): one month's actual spending against its plan's
target, conservatively, with budget pace and revised allowances, for the household or one member.

- Actual discretionary is M12's discretionary spending in the month (D-057's date), pending
  included. Refunds reduce it.
- Possible spending is unclassified money out and unconfirmed transfer-kind money out (D-011),
  counted against capacity on lines of their own until classified.
- A member's actual is their parts of both, from M11's effective attributions. Unattributed
  amounts count against the household only, and mark every member's figures provisional.
- Category allowances compare a category's discretionary spending, its subcategories included,
  effective category first (D-064), against its cap.
- No input is actual income (point 5): M12's baseline income is shown as planned context only.

Read only. Nothing here reads the clock: as_of is an argument (G7). Never calls the transfer
candidate search (point 7).
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from personal_finance.planning.budget_pace import BudgetPace, budget_pace
from personal_finance.planning.budgets import BudgetPlan, load_plans, plan_in_effect
from personal_finance.planning.settings import household_timezone
from personal_finance.reconcile.category_effects import CONFIRMED_TRANSFER_SQL, SPENDING_TYPES
from personal_finance.reconcile.household_effects import (
    UNATTRIBUTED,
    attributed_transactions,
    load_household,
)
from personal_finance.reconcile.transfer_effects import TRANSFER_TYPES
from personal_finance.reports.income_report import income_report, month_end

FUTURE = "future"
CURRENT = "current"
CLOSED = "closed"

LARGEST_SHOWN = 5


@dataclass
class Spent:
    """A count and an amount spent, in cents: money out positive, a refund negative."""

    count: int = 0
    cents: int = 0

    def add(self, spent_cents: int) -> None:
        self.count += 1
        self.cents += spent_cents


@dataclass(frozen=True)
class SpendingItem:
    transaction_id: str
    effective_date: str
    description: str | None
    spent_cents: int


@dataclass(frozen=True)
class CategoryAllowance:
    name: str
    allowance_cents: int
    spent_cents: int


@dataclass
class BudgetMonth:
    month: str
    as_of: str
    state: str
    plan: BudgetPlan | None
    # The member viewed by name, else None for the household.
    member: str | None
    # T: the plan's allowance, or the member's part of it. None with no plan, or a member view of
    # a plan that does not divide the allowance.
    target_cents: int | None
    discretionary: Spent = field(default_factory=Spent)
    unclassified: Spent = field(default_factory=Spent)
    transfer_kinds: Spent = field(default_factory=Spent)
    # Of the three above, what is pending.
    pending: Spent = field(default_factory=Spent)
    # Member view: the household's discretionary and possible spending left unattributed.
    unattributed: Spent = field(default_factory=Spent)
    categories: tuple[CategoryAllowance, ...] = ()
    largest: tuple[SpendingItem, ...] = ()
    pace: BudgetPace | None = None
    fixed_planned_cents: int = 0
    fixed_actual: Spent = field(default_factory=Spent)
    baseline_income_planned_cents: int = 0
    corrected_after_close: bool = False

    @property
    def actual_cents(self) -> int:
        """A: actual discretionary plus possible spending."""
        return self.discretionary.cents + self.unclassified.cents + self.transfer_kinds.cents

    @property
    def provisional(self) -> bool:
        """Capacity rests on spending not yet classified, or not yet attributed."""
        return bool(self.unclassified.count or self.transfer_kinds.count
                    or (self.member is not None and self.unattributed.count))


def month_state(month: str, as_of: date) -> str:
    today = as_of.isoformat()[:7]
    return FUTURE if month > today else CURRENT if month == today else CLOSED


def month_facts(conn: sqlite3.Connection, month: str) -> list[tuple]:
    """Each transaction dated in the month (D-057's date): ID, effective amount, applied type,
    whether a transfer is confirmed there, effective category, whether a fixed obligation reaches
    it, settlement status, effective date and effective description."""
    return conn.execute(
        f"""SELECT entry.id, COALESCE(fix.corrected_amount_cents, entry.amount_cents),
                   kind.financial_type, {CONFIRMED_TRANSFER_SQL},
                   COALESCE(categorized.category_id, by_rules.category_id),
                   EXISTS (SELECT 1 FROM transaction_obligation derived
                           WHERE derived.transaction_id = entry.id
                             AND derived.obligation_class = 'fixed'),
                   entry.settlement_status,
                   COALESCE(date_fix.corrected_text, entry.transaction_date,
                            posting_fix.corrected_text, entry.posting_date) AS effective_date,
                   COALESCE(text_fix.corrected_text, entry.description)
            FROM ledger_transaction entry
            LEFT JOIN transaction_classification kind
                ON kind.transaction_id = entry.id AND kind.state = 'applied'
            LEFT JOIN transaction_correction fix
                ON fix.transaction_id = entry.id AND fix.field = 'amount' AND fix.state = 'applied'
            LEFT JOIN transaction_correction date_fix
                ON date_fix.transaction_id = entry.id
               AND date_fix.field = 'transaction_date' AND date_fix.state = 'applied'
            LEFT JOIN transaction_correction posting_fix
                ON posting_fix.transaction_id = entry.id
               AND posting_fix.field = 'posting_date' AND posting_fix.state = 'applied'
            LEFT JOIN transaction_correction text_fix
                ON text_fix.transaction_id = entry.id
               AND text_fix.field = 'description' AND text_fix.state = 'applied'
            LEFT JOIN transaction_category categorized
                ON categorized.transaction_id = entry.id AND categorized.state = 'applied'
            LEFT JOIN transaction_rule_category by_rules
                ON by_rules.transaction_id = entry.id AND by_rules.state = 'applied'
            WHERE substr(COALESCE(date_fix.corrected_text, entry.transaction_date,
                                  posting_fix.corrected_text, entry.posting_date), 1, 7) = ?
            ORDER BY entry.id""",
        (month,)).fetchall()


def corrected_after_close(plans, month: str, zone) -> bool:
    """Whether a plan made with --correct-closed-month changed this month after it closed: the
    plan is in effect for the month, or left it with none, and the month lies from the first
    month that plan or the one it superseded applied from, to before the month the plan was made
    in, in the household's zone (UTC with none set)."""
    by_id = {plan.plan_id: plan for plan in plans}
    in_effect = plan_in_effect(plans, month)
    for plan in plans:
        if not plan.corrected_closed_month or in_effect not in (None, plan):
            continue
        superseded = by_id.get(plan.supersedes_id)
        first = min(plan.effective_from, superseded.effective_from if superseded else "9999-12")
        made = datetime.fromisoformat(plan.created_at.replace("Z", "+00:00"))
        made_month = (made.astimezone(zone) if zone else made).isoformat()[:7]
        if first <= month < made_month:
            return True
    return False


def budget_report(conn: sqlite3.Connection, month: str, as_of: date,
                  member_name: str | None) -> BudgetMonth:
    """One month's budget, for the household or one member, as of a date."""
    plans = load_plans(conn)
    zone = household_timezone(conn)
    plan = plan_in_effect(plans, month)
    household = load_household(conn)
    member = None if member_name is None else household.find_member(member_name)
    if member_name is not None and member is None:
        raise LookupError(member_name)
    target = None
    if plan is not None:
        parts = dict(plan.member_parts)
        target = plan.allowance_cents if member is None else parts.get(member.name)
    state = month_state(month, as_of)
    report = BudgetMonth(month, as_of.isoformat(), state, plan, member_name, target)
    report.corrected_after_close = state == CLOSED and corrected_after_close(plans, month, zone)

    context = income_report(conn, as_of, None, month, month).months
    if context:
        report.baseline_income_planned_cents = context[0].total("baseline", "planned")
        report.fixed_planned_cents = context[0].classes["fixed"].due.cents
    if state == FUTURE:
        return report

    facts = month_facts(conn, month)
    counted = {}
    for (transaction_id, cents, financial_type, confirmed, _, is_fixed, status, _,
         _) in facts:
        if confirmed:
            continue
        if financial_type in SPENDING_TYPES:
            if is_fixed:
                report.fixed_actual.add(-cents)
            else:
                counted[transaction_id] = "discretionary"
        elif cents < 0 and financial_type in TRANSFER_TYPES:
            counted[transaction_id] = "transfer_kinds"
        elif cents < 0 and financial_type is None:
            counted[transaction_id] = "unclassified"

    shares = {transaction_id: None for transaction_id in counted}
    if member is not None:
        for entry in attributed_transactions(conn, household, None, list(counted)):
            shares[entry.transaction_id] = entry
    pending_ids = {row[0] for row in facts if row[6] == "pending"}
    for transaction_id, cents, *_ in facts:
        group = counted.get(transaction_id)
        if group is None:
            continue
        spent = -cents
        if member is not None:
            entry = shares[transaction_id]
            if entry.attribution.kind == UNATTRIBUTED:
                report.unattributed.add(spent)
                continue
            mine = [part for member_id, part in entry.attribution.parts
                    if member_id == member.member_id]
            if not mine:
                continue
            spent = -sum(mine)
        getattr(report, group).add(spent)
        if transaction_id in pending_ids:
            report.pending.add(spent)

    if member is None and plan is not None:
        report.categories = category_allowances(conn, plan, facts, counted)
    if target is not None:
        if state == CURRENT:
            report.pace = budget_pace(target, report.actual_cents, month_end(month).day,
                                      as_of.day)
        if target - report.actual_cents < 0:
            report.largest = tuple(sorted(
                (SpendingItem(row[0], row[7], row[8], -row[1]) for row in facts
                 if counted.get(row[0]) == "discretionary"),
                key=lambda item: (-item.spent_cents, item.effective_date,
                                  item.transaction_id))[:LARGEST_SHOWN])
    return report


def category_allowances(conn, plan: BudgetPlan, facts, counted) -> tuple[CategoryAllowance, ...]:
    """Each capped category's discretionary spending, its subcategories included."""
    names = {category_id: name for category_id, name in conn.execute(
        "SELECT id, name FROM category")}
    parent_of = dict(conn.execute("SELECT id, parent_id FROM category"))
    by_name = defaultdict(int)
    for transaction_id, cents, _, _, category_id, *_ in facts:
        if counted.get(transaction_id) != "discretionary" or category_id is None:
            continue
        by_name[names[category_id]] -= cents
        if parent_of[category_id] is not None:
            by_name[names[parent_of[category_id]]] -= cents
    return tuple(CategoryAllowance(name, cents, by_name[name])
                 for name, cents in plan.category_allowances)
