"""pf report funds (D-070 points 4 and 8, M14.3): every fund's standing, the month's extra and its
planned allocation down the priority list, and when each target is reached at the planned rate.

The month's extra is M12's extra paychecks received in as_of's month, plus side income received
then less the tax reserve's accrual on it, plus M13's unused capacity of the month before, the
latest closed one. It goes down the priority list, each fund taking up to its outstanding need,
and what is left is unallocated. Every figure here is planned: an allocation is never an
assignment and never a transfer (PRD §12). Read only. Nothing here reads the clock.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from personal_finance.planning.funds import (
    EMERGENCY,
    MONTHLY,
    PERCENT,
    TAX,
    ceiling_division,
    month_index,
)
from personal_finance.planning.income_effects import EXTRA, SIDE
from personal_finance.reports.budget_report import budget_report
from personal_finance.reports.fund_standing import FundsView, FundView, funds_view, tax_accrual
from personal_finance.reports.income_report import income_report

# What a fund's "reached" says where no month can be given.
REACHED = "reached"
NO_TARGET = "no target"
NOT_AT_PLANNED_RATE = "not at the planned rate"
NOT_STARTED = "not started"
HELD = "a held amount, no planned rate"


@dataclass(frozen=True)
class MonthExtra:
    month: str
    extra_paychecks_cents: int
    side_income_cents: int
    # The tax reserve's accrual on that side income, None with no tax reserve in effect.
    side_tax_accrual_cents: int | None
    closed_month: str
    # The closed month's unused capacity, None where no plan's target applies to it.
    unused_capacity_cents: int | None

    @property
    def total_cents(self) -> int:
        return (self.extra_paychecks_cents + self.side_income_cents
                - (self.side_tax_accrual_cents or 0) + (self.unused_capacity_cents or 0))


@dataclass(frozen=True)
class PlannedAllocation:
    fund_id: str
    name: str
    # Its outstanding need, None for a goal with no target, which takes nothing.
    need_cents: int | None
    allocated_cents: int


@dataclass(frozen=True)
class FundsReport:
    view: FundsView
    # Each active fund's month its target is reached at the planned rate, or the words why not.
    reached: dict[str, str]
    extra: MonthExtra
    allocations: tuple[PlannedAllocation, ...]
    unallocated_cents: int


def month_from_index(index: int) -> str:
    return f"{index // 12:04}-{index % 12 + 1:02}"


def reached_month(fund_view: FundView, as_of: str) -> str:
    """The month the planned contributions cover what is outstanding: as_of's month plus
    ceil(outstanding ÷ planned contribution) months, counting as_of's own."""
    standing = fund_view.standing
    terms = fund_view.fund.terms_on(as_of)
    if terms is None:
        return NOT_STARTED
    if fund_view.fund.kind not in (EMERGENCY, TAX) and terms.shape in (MONTHLY, PERCENT):
        return NO_TARGET
    if not standing.outstanding_cents:
        return REACHED
    if fund_view.fund.kind in (EMERGENCY, TAX):
        return HELD
    if not standing.planned_contribution_cents:
        return NOT_AT_PLANNED_RATE
    months = ceiling_division(standing.outstanding_cents, standing.planned_contribution_cents)
    return month_from_index(month_index(as_of[:7]) + months - 1)


def month_extra(conn: sqlite3.Connection, as_of: date, view: FundsView) -> MonthExtra:
    month = as_of.isoformat()[:7]
    (income_month,) = income_report(conn, as_of, first_month=month, last_month=month).months
    side = income_month.total(SIDE, "received")
    tax = next((fund_view.fund for fund_view in view.funds
                if fund_view.fund.kind == TAX and fund_view.fund.applies), None)
    accrual = None
    if tax is not None:
        accrual = tax_accrual(conn, tax, as_of.isoformat(), from_day=f"{month}-01",
                              side_only=True).cents
    closed = month_from_index(month_index(month) - 1)
    closed_report = budget_report(conn, closed, as_of, None)
    unused = None
    if closed_report.target_cents is not None:
        unused = max(0, closed_report.target_cents - closed_report.actual_cents)
    return MonthExtra(month, income_month.total(EXTRA, "received"), side, accrual, closed,
                      unused)


def allocate_down(priority, views_by_id, as_of: str, extra_cents: int):
    """Each fund in order takes up to its outstanding need, a goal with no target taking
    nothing. Returns the allocations and what is left."""
    left = extra_cents
    allocations = []
    for fund_id in priority:
        fund_view = views_by_id[fund_id]
        terms = fund_view.fund.terms_on(as_of)
        need = (None if terms is None or terms.shape in (MONTHLY, PERCENT)
                else fund_view.standing.outstanding_cents or 0)
        taken = min(left, need or 0)
        left -= taken
        allocations.append(PlannedAllocation(fund_id, fund_view.fund.name, need, taken))
    return tuple(allocations), left


def funds_report(conn: sqlite3.Connection, as_of: date) -> FundsReport:
    view = funds_view(conn, as_of)
    text = as_of.isoformat()
    reached = {fund_view.fund.fund_id: reached_month(fund_view, text)
               for fund_view in view.funds if fund_view.fund.applies}
    extra = month_extra(conn, as_of, view)
    views_by_id = {fund_view.fund.fund_id: fund_view for fund_view in view.funds}
    allocations, left = allocate_down(view.priority, views_by_id, text, extra.total_cents)
    return FundsReport(view, reached, extra, allocations, left)
