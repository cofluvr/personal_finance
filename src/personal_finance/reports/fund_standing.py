"""Every fund's standing as of a date (D-070 points 1 to 3), for pf funds and pf fund show: the
inputs its formula reads from M12, its assignments by account, and the accounts' disclosures.

Read only. Every figure is planned, assigned or required, and labelled so where it is shown
(G1). Nothing here reads the clock: as_of is an argument (G7).
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from personal_finance.planning.funds import (
    GOAL,
    MONTHS,
    PERCENT,
    TAX,
    AccountHolding,
    Fund,
    Standing,
    StandingInputs,
    account_holdings,
    active_priority,
    assigned_to_fund,
    ceiling_division,
    cycle_start,
    fund_standing,
    load_assignments,
    load_funds,
    load_portions,
    load_releases,
    reductions_as_of,
)
from personal_finance.planning.income_effects import (
    BASELINE,
    RECEIVED,
    applying_sources,
    load_deposit_facts,
    source_outcomes,
)
from personal_finance.planning.obligation_effects import FIXED, applying_obligations
from personal_finance.reports.income_report import income_report, month_end

# How often each cadence falls in a year, as a fraction (D-070 point 1's emergency months). An
# every-N-months cadence falls 12 ÷ N times.
OCCURRENCES_PER_YEAR = {"weekly": 52, "biweekly": 26, "semimonthly": 24, "monthly": 12,
                        "quarterly": 4, "annual": 1}


def monthly_equivalent_cents(cadence, amount_cents: int) -> int:
    """ceil(amount × occurrences per year ÷ 12), a monthly obligation counting its amount."""
    if cadence.name == "every_months":
        return ceiling_division(amount_cents, cadence.interval_months)
    return ceiling_division(amount_cents * OCCURRENCES_PER_YEAR[cadence.name], 12)


def monthly_fixed_commitments_cents(conn: sqlite3.Connection, month: str) -> int:
    """The fixed commitments planned in a month: each applying obligation whose terms in effect
    at the month's end are fixed, at its planned amount (a range's HIGH), spread to a month."""
    last_day = month_end(month).isoformat()
    total = 0
    for obligation in applying_obligations(conn):
        starting = [terms for terms in obligation.terms if terms.effective_from <= last_day]
        if starting and starting[-1].obligation_class == FIXED:
            total += monthly_equivalent_cents(starting[-1].cadence, starting[-1].planned_cents)
    return total


def baseline_income_cents(conn: sqlite3.Connection, as_of: date) -> int:
    """M12's baseline income planned in as_of's month: never extra or side income."""
    month = as_of.isoformat()[:7]
    (report_month,) = income_report(conn, as_of, first_month=month, last_month=month).months
    return report_month.total(BASELINE, "planned")


@dataclass(frozen=True)
class TaxAccrual:
    cents: int
    occurrences: int


def tax_accrual(conn: sqlite3.Connection, fund: Fund, as_of: str) -> TaxAccrual:
    """For each received occurrence of a tax-eligible source dated from the fund's first
    effective_from through as_of, ceil(amount × bps ÷ 10,000) under the terms in effect that day
    (point 6), rounded toward protection."""
    sources = applying_sources(conn)
    eligible = {source.source_id for source in sources if source.definition.tax_eligible}
    if not eligible:
        return TaxAccrual(0, 0)
    deposits = load_deposit_facts(conn, {source.definition.account_id for source in sources})
    by_id = {facts.transaction_id: facts for facts in deposits}
    cents = occurrences = 0
    for (transaction_id, source_id), outcome in sorted(source_outcomes(sources, deposits).items()):
        received_on = by_id[transaction_id].reporting_date
        terms = fund.terms_on(received_on)
        if (source_id in eligible and outcome.state == RECEIVED and terms is not None
                and received_on <= as_of):
            cents += ceiling_division(by_id[transaction_id].amount_cents * terms.basis_points,
                                      10_000)
            occurrences += 1
    return TaxAccrual(cents, occurrences)


@dataclass(frozen=True)
class TaxPayments:
    """What the tax reserve paid through consumptions and released, through as_of (point 6)."""

    paid_cents: int
    payments: int
    released_cents: int
    releases: int


@dataclass(frozen=True)
class FundView:
    fund: Fund
    standing: Standing
    # (account name, cents) of each active assignment, by account name.
    assigned_by_account: tuple[tuple[str, int], ...]
    # Accounts whose assignments exceed their balance observed, and those observed long ago.
    not_backed_on: tuple[str, ...]
    provisional_on: tuple[str, ...]
    tax_accrual: TaxAccrual | None = None
    baseline_income_cents: int | None = None
    monthly_fixed_commitments_cents: int | None = None
    # What the fund paid in its cycle by as_of, and in how many transactions (point 5).
    consumed_cents: int = 0
    consumed_count: int = 0
    tax_payments: TaxPayments | None = None
    # A recurring reserve's previous due date, after which its cycle's consumptions count.
    consumed_since: str | None = None

    @property
    def paid_beyond_reserve_cents(self) -> int:
        """Payments beyond what the tax reserve accrued less its releases (point 6)."""
        if self.tax_accrual is None or self.tax_payments is None:
            return 0
        return max(0, self.tax_payments.paid_cents + self.tax_payments.released_cents
                   - self.tax_accrual.cents)


@dataclass(frozen=True)
class FundsView:
    as_of: str
    funds: tuple[FundView, ...]
    holdings: tuple[AccountHolding, ...]
    priority: tuple[str, ...]


def tax_payments(fund: Fund, portions, releases, as_of: str) -> TaxPayments:
    """The whole of each payment consumed against the tax reserve dated by as_of, a refund
    consumed against it reducing them, and its releases dated by as_of (D-070 point 6)."""
    paid = [portion.consumed.spent_cents for portion in portions
            if portion.consumed.fund_id == fund.fund_id
            and portion.consumed.effective_date <= as_of]
    released = [release.amount_cents for release in releases
                if release.fund_id == fund.fund_id and release.released_on <= as_of]
    return TaxPayments(sum(paid), len(paid), sum(released), len(released))


def consumed_in_cycle(fund: Fund, portions, as_of: str) -> tuple[int, int]:
    """What the fund paid in the cycle holding as_of, and in how many transactions."""
    start = cycle_start(fund, as_of)
    counted = [portion.consumed_cents for portion in portions
               if portion.consumed.fund_id == fund.fund_id
               and portion.consumed.effective_date <= as_of
               and (start is None or portion.consumed.effective_date > start)]
    return sum(counted), len(counted)


def tax_required_cents(conn: sqlite3.Connection, fund: Fund, as_of: str) -> int:
    """Accrued − paid − released through as_of, never below zero (point 6)."""
    payments = tax_payments(fund, load_portions(conn), load_releases(conn), as_of)
    return max(0, tax_accrual(conn, fund, as_of).cents - payments.paid_cents
               - payments.released_cents)


def funds_view(conn: sqlite3.Connection, as_of: date) -> FundsView:
    as_of_text = as_of.isoformat()
    funds = load_funds(conn)
    assignments = load_assignments(conn)
    portions = load_portions(conn, assignments)
    releases = load_releases(conn)
    reduced = reductions_as_of(portions, as_of_text)
    holdings = account_holdings(conn, as_of_text)
    by_account = {holding.account_id: holding for holding in holdings}
    # Read once, and only when a fund in effect needs them.
    baseline = fixed = None
    views = []
    for fund in funds:
        terms = fund.terms_on(as_of_text)
        shape = None if terms is None else terms.shape
        accrual = baseline_shown = fixed_shown = payments = None
        if shape == PERCENT and fund.kind == GOAL:
            baseline = baseline_income_cents(conn, as_of) if baseline is None else baseline
            baseline_shown = baseline
        elif shape == MONTHS:
            if fixed is None:
                fixed = monthly_fixed_commitments_cents(conn, as_of_text[:7])
            fixed_shown = fixed
        elif shape == PERCENT and fund.kind == TAX:
            accrual = tax_accrual(conn, fund, as_of_text)
            payments = tax_payments(fund, portions, releases, as_of_text)
        consumed, consumed_count = consumed_in_cycle(fund, portions, as_of_text)
        inputs = StandingInputs(as_of_text, baseline_income_cents=baseline_shown or 0,
                                monthly_fixed_commitments_cents=fixed_shown or 0,
                                consumed_cents=consumed,
                                tax_accrued_cents=0 if accrual is None else accrual.cents,
                                tax_paid_cents=0 if payments is None else payments.paid_cents,
                                tax_released_cents=(0 if payments is None
                                                    else payments.released_cents))
        held = [assignment for assignment in assignments
                if assignment.applies and assignment.fund_id == fund.fund_id]
        accounts = [by_account[assignment.account_id] for assignment in held]
        views.append(FundView(
            fund, fund_standing(fund, assigned_to_fund(assignments, fund.fund_id, reduced),
                                inputs),
            tuple(sorted((by_account[assignment.account_id].account_name,
                          assignment.amount_cents - reduced.get(assignment.assignment_id, 0))
                         for assignment in held)),
            tuple(sorted(holding.account_name for holding in accounts
                         if holding.over_assigned_cents)),
            tuple(sorted(holding.account_name for holding in accounts if holding.provisional)),
            accrual, baseline_shown, fixed_shown, consumed, consumed_count, payments,
            cycle_start(fund, as_of_text)))
    return FundsView(as_of_text, tuple(views), holdings, active_priority(conn))
