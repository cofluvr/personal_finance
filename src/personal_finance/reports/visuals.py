"""The eight visuals of PRD §18, as rows (D-073 point 6).

Each chart is drawn by the UI from exactly these rows, and printed as a table beneath it by the
same builder pf report visuals prints, so a chart's every mark is a table cell. Nothing here
computes a figure of its own: each row is a figure an existing report already gives.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from personal_finance.reports.balances import LIABILITY_ACCOUNT_TYPES, list_observations
from personal_finance.reports.budget_report import budget_report
from personal_finance.reports.fund_standing import funds_view
from personal_finance.reports.household import household_report
from personal_finance.reports.monthly import monthly_report
from personal_finance.reports.net_worth_report import net_worth
from personal_finance.reports.totals import combined

UNCATEGORIZED_LABEL = "uncategorized"


@dataclass(frozen=True)
class ChartRow:
    label: str
    # One value per series, in cents, signed as the report gives it.
    values: tuple[int, ...]
    # Words shown after the values, such as a valuation date.
    note: str = ""


@dataclass(frozen=True)
class Chart:
    title: str
    series: tuple[str, ...]
    rows: tuple[ChartRow, ...]
    # Said when there is nothing to draw, or what the figures leave out.
    notice: str = ""


def spent(group) -> int:
    """A group's spending, out less in, as a positive figure when money went out."""
    return group.out_cents - group.in_cents


def goal_progress(active_funds) -> Chart:
    """Each active fund's assigned and outstanding amounts, as the visuals and the dashboard
    draw them (D-083 point 3)."""
    return Chart("Goal progress", ("assigned", "outstanding"), tuple(
        ChartRow(fund_view.fund.name, (fund_view.standing.assigned_cents,
                                       fund_view.standing.outstanding_cents or 0))
        for fund_view in active_funds), "" if active_funds else "no fund is active")


def visuals(conn: sqlite3.Connection, as_of: date) -> tuple[Chart, ...]:
    month = as_of.isoformat()[:7]
    names = dict(conn.execute("SELECT id, name FROM category"))
    months = monthly_report(conn).months
    # Spending by category over every month, summed from the monthly report rather than computed
    # again (G9): every transaction is in exactly one month, so the sums are the whole ledger's.
    by_category = {}
    for month_report in months:
        for category_id, group in month_report.income_and_spending.spending_by_category:
            by_category.setdefault(category_id, []).append(group)
    categories = sorted(by_category, key=lambda category_id: (category_id is None,
                                                              category_id or 0))
    budget = budget_report(conn, month, as_of, None)
    funds = [fund_view for fund_view in funds_view(conn, as_of).funds if fund_view.fund.applies]
    household = household_report(conn)
    worth = net_worth(conn, as_of.isoformat())
    debts = [observation for observation in list_observations(conn)
             if observation.account_type in LIABILITY_ACCOUNT_TYPES and observation.state == "active"
             and observation.observed_on <= as_of.isoformat()]
    budget_rows = [] if budget.target_cents is None else [ChartRow("Target",
                                                                   (budget.target_cents,))]
    return (
        Chart("Spending by category", ("spent",), tuple(
            ChartRow(names.get(category_id, UNCATEGORIZED_LABEL),
                     (spent(combined(by_category[category_id])),))
            for category_id in categories),
            "" if categories else "no spending is categorized yet"),
        Chart("Spending over time", ("spent",), tuple(
            ChartRow(month_report.month, (spent(month_report.income_and_spending.spending),))
            for month_report in months)),
        Chart(f"Budget, {month}: target against actual", ("amount",), (
            *budget_rows, ChartRow("Actual", (budget.actual_cents,))),
            "" if budget_rows else "no plan in effect"),
        goal_progress(funds),
        Chart("Household comparison", ("spent",), tuple(
            ChartRow(column.heading, (spent(column.groups.spending),))
            for column in household.columns)),
        Chart("Income and spending", ("income", "spent"), tuple(
            ChartRow(month_report.month, (
                month_report.income_and_spending.income.in_cents
                - month_report.income_and_spending.income.out_cents,
                spent(month_report.income_and_spending.spending)))
            for month_report in months)),
        Chart("Debt history, as observed", ("owed",), tuple(
            ChartRow(f"{observation.account_name}, {observation.observed_on}",
                     (-observation.balance_cents,))
            for observation in sorted(debts, key=lambda each: (each.account_name,
                                                               each.observed_on))),
            "" if debts else "no card or loan balance is observed"),
        Chart(f"Net worth as of {as_of.isoformat()}, by account", ("balance",), tuple(
            ChartRow(valuation.name, (valuation.counted_cents,),
                     f"valued {valuation.observation.observed_on}")
            for valuation in worth.valued if valuation.how == "counted"),
            "" if any(valuation.how == "counted" for valuation in worth.valued)
            else "no account is valued"),
    )
