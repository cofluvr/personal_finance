"""One pure monthly projection of the plan, run for the baseline and for a scenario (D-074 points
3 and 4, the M18.2 slice plan).

project(plan, inputs, as_of, months) reads nothing and stores nothing: the baseline is
project(plan, (), ...) and a scenario project(plan, its counted inputs, ...), so a scenario with
no inputs gives the baseline exactly. Every figure is integer cents. Allowances round down and
required amounts up (G8), loan interest is M15's, half-even once a month.

Each month, from as_of's: salary by its sources' nominal dates; fixed obligations at their
planned amounts; discretionary spending at the budget target in full (in as_of's month, what is
left of it); the tax reserve's accrual on eligible income; loan payments by schedule; then fund
contributions in priority order, as far as liquidity above the protected amount allows. A flow
dated on or before as_of is already in the starting balance, so as_of's month counts only what
falls after it. A replacement removes its entry's effect over its range only, and adds its own.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal, localcontext

from personal_finance.planning.funds import (
    DUE,
    EMERGENCY,
    GOAL,
    MINIMUM,
    MONTHLY,
    MONTHS,
    PERCENT,
    RECURRING,
    RESERVE,
    TARGET_BY,
    FundTerms,
    ceiling_division,
    months_left_including,
)
from personal_finance.planning.loans import MILLIONTHS_IN_WHOLE, LoanTerms, monthly_interest
from personal_finance.planning.schedules import Cadence, cadence_dates, last_day, scheduled_dates
from personal_finance.planning.scenarios import (
    ANNUAL_EXPENSE,
    BONUS,
    BORROWING,
    EXPENSE,
    HOME_PURCHASE,
    INCOME,
    LOAN_PAYOFF,
    ONCE,
    PURCHASE,
    ScenarioInput,
    input_cadence,
)

DEFAULT_MONTHS = 24
LONGEST_MONTHS = 120

ASSUMPTIONS = (
    "monthly, from as_of's month; a flow dated on or before as_of is in the starting balance",
    "salary by its sources' nominal dates, extra paychecks included as cash",
    "side income only from confirmed scenario inputs: side sources are left out",
    "fixed obligations at their planned amounts, a range's high",
    "discretionary spending at the budget target in full, never underspent",
    "discretionary obligations are within the budget target, so not counted again",
    "tax reserve accrual on tax-eligible salary, rounded up",
    "fund contributions in priority order, each rounded up, as far as liquidity above the "
    "protected amount allows",
    "a reserve pays its target from the fund on its due date",
    "loan interest at the rate in effect, balance × APR ÷ 12, half-even to the cent each month",
    "a loan payment covered by an obligation is counted once, as the obligation",
    "a scenario loan's payment is the level payment over its months, rounded up",
    "uncertain inputs are left out unless the scenario includes them",
    "no inflation, market returns or tax calculation",
)


@dataclass(frozen=True)
class StreamTerms:
    effective_from: str
    cadence: Cadence
    anchor: str
    amount_cents: int


@dataclass(frozen=True)
class Stream:
    """A dated baseline entry: a salary source or a fixed obligation."""

    entry_id: str
    name: str
    # Oldest first, as scheduled_dates reads them.
    terms: tuple[StreamTerms, ...]
    tax_eligible: bool = False
    # The cadence in effect at as_of as typed, for look-alikes.
    cadence_spec: str = ""


@dataclass(frozen=True)
class ProjectedFund:
    fund_id: str
    name: str
    kind: str
    terms: tuple[FundTerms, ...]
    held_cents: int
    # The emergency fund's restorations as (effective_from, monthly cents), oldest first.
    restorations: tuple[tuple[str, int], ...] = ()

    def terms_on(self, on: str) -> FundTerms | None:
        starting = [terms for terms in self.terms if terms.effective_from <= on]
        return starting[-1] if starting else None

    def restoration_on(self, on: str) -> int:
        starting = [cents for start, cents in self.restorations if start <= on]
        return starting[-1] if starting else 0


@dataclass(frozen=True)
class ProjectedLoan:
    terms: LoanTerms
    owed_cents: int
    observed_on: str
    # False where an obligation covers the payment, which then counts as the obligation.
    payment_is_cash: bool = True


@dataclass(frozen=True)
class Plan:
    """The active plan as of a date, read once, holding only plain values."""

    as_of: str
    # M16's estimate over the liquidity accounts, or None with none designated.
    liquid_estimate_cents: int | None
    # What funds hold on liquidity accounts, protected from spending.
    held_on_liquid_cents: int
    protected_cents: int
    # Actual net worth (D-071) at as_of, or None when nothing is valued.
    net_worth_cents: int | None
    salary: tuple[Stream, ...] = ()
    obligations: tuple[Stream, ...] = ()
    # Applying side sources and discretionary obligations, kept for look-alikes only.
    side_income: tuple[Stream, ...] = ()
    discretionary_obligations: tuple[Stream, ...] = ()
    # (first month, allowance cents), oldest first.
    budget: tuple[tuple[str, int], ...] = ()
    # What as_of's month has spent at its discretionary target by as_of.
    start_month_spent_cents: int = 0
    # Goals, reserves and the emergency fund in priority order.
    funds: tuple[ProjectedFund, ...] = ()
    tax: ProjectedFund | None = None
    monthly_fixed_commitments_cents: int = 0
    loans: tuple[ProjectedLoan, ...] = ()
    missing: tuple[str, ...] = ()

    def target_for(self, month: str) -> int | None:
        found = [cents for first, cents in self.budget if first <= month]
        return found[-1] if found else None


@dataclass(frozen=True)
class MonthFigures:
    month: str
    income_cents: int
    obligations_cents: int
    discretionary_cents: int
    loan_payments_cents: int
    funds_cents: int
    cash_flow_cents: int
    liquidity_cents: int
    daily_allowance_cents: int
    weekly_allowance_cents: int
    debt_cents: int
    net_worth_cents: int | None
    scenario_assets_cents: int
    shortfall: bool


@dataclass(frozen=True)
class GoalFigures:
    fund_id: str
    name: str
    kind: str
    target_cents: int | None
    deadline: str | None
    # What the first month needs, uncapped by liquidity.
    required_monthly_cents: int
    completion_month: str | None
    unmet: bool
    held_cents: int


@dataclass(frozen=True)
class LoanFigures:
    name: str
    balance_cents: int
    paid_off: str | None
    scenario: bool


@dataclass(frozen=True)
class Projection:
    as_of: str
    months: tuple[MonthFigures, ...]
    goals: tuple[GoalFigures, ...]
    loans: tuple[LoanFigures, ...]
    # Input ID to the baseline entries it looks like (point 4), counted as typed all the same.
    look_alikes: dict = field(default_factory=dict)
    assumptions: tuple[str, ...] = ASSUMPTIONS
    missing: tuple[str, ...] = ()

    @property
    def shortfall_months(self) -> tuple[str, ...]:
        return tuple(month.month for month in self.months if month.shortfall)

    @property
    def unmet_goals(self) -> tuple[str, ...]:
        return tuple(goal.name for goal in self.goals if goal.unmet)


# Dates.

def month_text(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def horizon(as_of: date, months: int) -> list[tuple[str, date, date]]:
    """Each month as (YYYY-MM, its first counted day, its last day). as_of's month counts from
    the day after as_of."""
    found = []
    index = as_of.year * 12 + as_of.month - 1
    for step in range(months):
        year, month = divmod(index + step, 12)
        month += 1
        first = as_of + timedelta(days=1) if step == 0 else date(year, month, 1)
        found.append((month_text(year, month), first, date(year, month, last_day(year, month))))
    return found


def overlaps(input_: ScenarioInput, day: date) -> bool:
    return input_.from_date <= day.isoformat() and (input_.to_date is None
                                                    or day.isoformat() <= input_.to_date)


# Loans, M15's month by month.

def level_payment_cents(principal_cents: int, rate_millionths: int, months: int) -> int:
    """P × r ÷ (1 − (1 + r)^−n), rounded up to the cent: a required amount (G8)."""
    if principal_cents <= 0:
        return 0
    if rate_millionths == 0:
        return ceiling_division(principal_cents, months)
    with localcontext() as context:
        context.prec = 28
        rate = context.divide(Decimal(rate_millionths), Decimal(MILLIONTHS_IN_WHOLE * 12))
        growth = context.power(context.add(Decimal(1), rate), months)
        exact = context.divide(context.multiply(Decimal(principal_cents),
                                                context.multiply(rate, growth)),
                               context.subtract(growth, Decimal(1)))
        return int(exact.quantize(Decimal(1), rounding=ROUND_CEILING))


@dataclass
class LoanState:
    name: str
    balance_cents: int
    due_day: int
    # The next due date not yet stepped.
    next_due: date
    rate_on: object
    payment_on: object
    payment_is_cash: bool
    scenario: bool
    terms_id: str | None = None
    paid_off: str | None = None

    def step(self) -> int:
        """One due date: interest, then the payment, the last no more than is owed. Returns the
        payment, nothing once paid off."""
        due = self.next_due
        if self.balance_cents <= 0:
            self.next_due = following_due(self.due_day, due)
            return 0
        interest = monthly_interest(self.balance_cents, self.rate_on(due))
        payment = min(self.payment_on(due), self.balance_cents + interest)
        self.balance_cents += interest - payment
        if self.balance_cents == 0 and self.paid_off is None:
            self.paid_off = due.isoformat()
        self.next_due = following_due(self.due_day, due)
        return payment

    def pay_off(self, amount_cents: int, on: date) -> int:
        """A one-time payment toward the balance, no more than is owed. Returns what it paid."""
        paid = min(amount_cents, max(0, self.balance_cents))
        self.balance_cents -= paid
        if self.balance_cents == 0 and self.paid_off is None:
            self.paid_off = on.isoformat()
        return paid


def following_due(due_day: int, after: date) -> date:
    year, month = divmod(after.year * 12 + after.month, 12)
    return date(year, month + 1, due_day)


def monthly_dates(starts: date, first: date, end: date) -> list[date]:
    """A monthly date from starts, on its day, falling from first through end."""
    found, on = [], starts
    while on <= end:
        if on >= first:
            found.append(on)
        on = following_due(starts.day, on)
    return found


def first_due_after(due_day: int, after: date) -> date:
    due = date(after.year, after.month, due_day)
    return due if due > after else following_due(due_day, due)


def baseline_loan(loan: ProjectedLoan) -> LoanState:
    terms = loan.terms

    def rate_on(due: date) -> int:
        rate = terms.rate_on(due.replace(day=1).isoformat())
        return terms.rates[0][1] if rate is None else rate

    return LoanState(terms.account_name, loan.owed_cents, terms.due_day,
                     first_due_after(terms.due_day, date.fromisoformat(loan.observed_on)),
                     rate_on, lambda due: terms.payment_on(due.isoformat()),
                     loan.payment_is_cash, False, terms.terms_id)


def scenario_loan(name: str, principal_cents: int, rate_millionths: int, months: int,
                  start: date) -> LoanState:
    payment = level_payment_cents(principal_cents, rate_millionths, months)
    due_day = min(start.day, 28)
    return LoanState(name, principal_cents, due_day, first_due_after(due_day, start),
                     lambda due: rate_millionths, lambda due: payment, True, True)


# Look-alikes (point 4).

def within_one_percent(amount_cents: int, planned_cents: int) -> bool:
    return abs(amount_cents - planned_cents) * 100 <= planned_cents


def look_alikes(plan: Plan, input_: ScenarioInput) -> tuple[str, ...]:
    """The baseline entries an additional input looks like: same kind and cadence, an amount
    within 1%, dates overlapping."""
    if input_.replaces_id is not None:
        return ()
    if input_.kind == INCOME:
        candidates = (*plan.salary, *plan.side_income)
    elif input_.kind == EXPENSE:
        candidates = (*plan.obligations, *plan.discretionary_obligations)
    elif input_.kind in (ANNUAL_EXPENSE, PURCHASE):
        return tuple(fund.fund_id for fund in plan.funds if reserve_looks_like(fund, input_))
    else:
        return ()
    found = []
    for stream in candidates:
        latest = stream.terms[-1]
        if (stream.cadence_spec == input_.cadence
                and within_one_percent(input_.take_home_cents, latest.amount_cents)
                and (input_.to_date is None or stream.terms[0].effective_from <= input_.to_date)):
            found.append(stream.entry_id)
    return tuple(found)


def reserve_looks_like(fund: ProjectedFund, input_: ScenarioInput) -> bool:
    if fund.kind != RESERVE:
        return False
    terms = fund.terms[-1]
    if not within_one_percent(input_.amount_cents, terms.amount_cents):
        return False
    if input_.kind == PURCHASE:
        return terms.shape == DUE and terms.due_date[:7] == input_.from_date[:7]
    return (terms.shape == RECURRING and terms.cadence.name == "annual"
            and input_.cadence == f"annual:{terms.anchor[5:7]}-{terms.cadence.first_day:02d}")


# Funds (D-070 point 1's formulas, taken month by month).

def fund_deadline(terms: FundTerms, on: date) -> str | None:
    """A target's last day: a goal's by-month's end, a reserve's due date or next due date."""
    if terms.shape == TARGET_BY:
        year, month = int(terms.by_month[:4]), int(terms.by_month[5:])
        return date(year, month, last_day(year, month)).isoformat()
    if terms.shape == DUE:
        return terms.due_date
    if terms.shape == RECURRING:
        span = 31 * (terms.cadence.months_between + 1)
        return cadence_dates(terms.cadence, date.fromisoformat(terms.anchor), on,
                             on + timedelta(days=span))[0].isoformat()
    return None


def fund_need(fund: ProjectedFund, terms: FundTerms | None, held: int, month: str, first: date,
              salary_cents: int, fixed_commitments_cents: int) -> int:
    """What a fund's terms ask of one month, given what it holds, rounded up (G8)."""
    if terms is None:
        return 0
    if terms.shape == MONTHLY:
        return terms.amount_cents
    if terms.shape == PERCENT and fund.kind == GOAL:
        return ceiling_division(salary_cents * terms.basis_points, 10_000)
    if terms.shape in (TARGET_BY, DUE, RECURRING):
        deadline = fund_deadline(terms, first)
        left = months_left_including(month, deadline[:7])
        outstanding = max(0, terms.amount_cents - held)
        return ceiling_division(outstanding, left) if left > 0 and outstanding else 0
    if terms.shape in (MINIMUM, MONTHS) and fund.kind == EMERGENCY:
        required = (terms.amount_cents if terms.shape == MINIMUM
                    else terms.month_count * fixed_commitments_cents)
        return min(fund.restoration_on(first.isoformat()), max(0, required - held))
    return 0


# The projection.

def project(plan: Plan, inputs: tuple[ScenarioInput, ...], as_of: date,
            months: int = DEFAULT_MONTHS) -> Projection:
    """The plan month by month with the given inputs counted as typed. Pure: the same plan,
    inputs, as_of and horizon always give the same projection."""
    if not 1 <= months <= LONGEST_MONTHS:
        raise ValueError("a horizon outside 1 to 120 months")
    replaced = {}
    for input_ in inputs:
        if input_.replaces_id:
            replaced.setdefault(input_.replaces_id, []).append(input_)

    def dated(stream: Stream, first: date, end: date) -> int:
        total = 0
        for nominal, terms in scheduled_dates(stream.terms, end):
            if nominal >= first and not any(overlaps(each, nominal)
                                            for each in replaced.get(stream.entry_id, ())):
                total += terms.amount_cents
        return total

    def input_dates(input_: ScenarioInput, first: date, end: date) -> list[date]:
        if input_.cadence == ONCE:
            on = date.fromisoformat(input_.from_date)
            return [on] if first <= on <= end else []
        cadence, anchor = input_cadence(input_)
        stop = end if input_.to_date is None else min(end, date.fromisoformat(input_.to_date))
        return cadence_dates(cadence, anchor, max(first, date.fromisoformat(input_.from_date)),
                             stop)

    loans = [baseline_loan(loan) for loan in plan.loans]
    loan_by_terms = {loan.terms.terms_id: state for loan, state in zip(plan.loans, loans)}
    for state in loans:
        while state.next_due <= as_of:
            state.step()
    debt_at_start = sum(state.balance_cents for state in loans)
    held = {fund.fund_id: fund.held_cents for fund in plan.funds}
    tax_held = plan.tax.held_cents if plan.tax else 0
    liquidity = (plan.liquid_estimate_cents or 0) - plan.held_on_liquid_cents
    liquid_total_at_start = liquidity + sum(held.values()) + tax_held
    completion = {}
    required_first = {}
    unmet = set()
    scenario_assets = 0
    ownership = []
    rows = []
    for step, (month, first, end) in enumerate(horizon(as_of, months)):
        salary = sum(dated(stream, first, end) for stream in plan.salary)
        eligible = sum(dated(stream, first, end) for stream in plan.salary
                       if stream.tax_eligible)
        income = salary
        obligations = sum(dated(stream, first, end) for stream in plan.obligations)
        loan_payments = 0
        lumps = {}
        for input_ in inputs:
            for on in input_dates(input_, first, end):
                if input_.kind in (INCOME, BONUS):
                    income += input_.take_home_cents
                elif input_.kind in (EXPENSE, ANNUAL_EXPENSE, PURCHASE):
                    obligations += input_.amount_cents
                elif input_.kind == HOME_PURCHASE:
                    obligations += input_.down_payment_cents + input_.closing_costs_cents
                    loans.append(scenario_loan(
                        f"home purchase {input_.input_id}",
                        input_.amount_cents - input_.down_payment_cents,
                        input_.loan_rate_millionths, input_.loan_months, on))
                    ownership.append((first_due_after(min(on.day, 28), on),
                                      input_.ownership_costs_cents))
                    scenario_assets += input_.amount_cents
                elif input_.kind == BORROWING:
                    income += input_.amount_cents
                    loans.append(scenario_loan(f"borrowing {input_.input_id}",
                                               input_.amount_cents, input_.loan_rate_millionths,
                                               input_.loan_months, on))
                elif input_.kind == LOAN_PAYOFF:
                    lumps.setdefault(input_.loan_terms_id, []).append((on, input_.amount_cents))
        for state in loans:
            pending = sorted(lumps.get(state.terms_id, ()))
            while state.next_due <= end or pending:
                if pending and (state.next_due > end or pending[0][0] < state.next_due):
                    paid_on, amount = pending.pop(0)
                    obligations += state.pay_off(amount, paid_on)
                    continue
                payment = state.step()
                if state.payment_is_cash:
                    loan_payments += payment
        for starts, cents in ownership:
            obligations += cents * len(monthly_dates(starts, first, end))
        target = plan.target_for(month)
        discretionary = 0 if target is None else (
            max(0, target - plan.start_month_spent_cents) if step == 0 else target)
        accrual = 0
        if plan.tax is not None:
            terms = plan.tax.terms_on(max(first, as_of).isoformat())
            if terms is not None:
                accrual = ceiling_division(eligible * terms.basis_points, 10_000)
        tax_held += accrual
        before_funds = liquidity + income - obligations - loan_payments - discretionary - accrual
        available = max(0, before_funds - plan.protected_cents)
        contributions = 0
        for fund in plan.funds:
            terms = fund.terms_on(max(first, as_of).isoformat())
            paused = any(input_.kind == ANNUAL_EXPENSE and input_.from_date[:7] <= month
                         and (input_.to_date is None or month <= input_.to_date[:7])
                         for input_ in replaced.get(fund.fund_id, ()))
            if paused:
                continue
            need = fund_need(fund, terms, held[fund.fund_id], month, first, salary,
                             plan.monthly_fixed_commitments_cents)
            if step == 0:
                required_first[fund.fund_id] = need
            given = min(need, available)
            available -= given
            contributions += given
            held[fund.fund_id] += given
            if terms is not None and terms.shape in (TARGET_BY, DUE) and \
                    held[fund.fund_id] >= terms.amount_cents:
                completion.setdefault(fund.fund_id, month)
            deadline = fund_deadline(terms, first) if terms else None
            if deadline and first.isoformat() <= deadline <= end.isoformat():
                if held[fund.fund_id] < terms.amount_cents:
                    unmet.add(fund.fund_id)
                if fund.kind == RESERVE:
                    held[fund.fund_id] -= min(held[fund.fund_id], terms.amount_cents)
        cash_flow = income - obligations - loan_payments - discretionary - accrual - contributions
        days = (end - first).days + 1 + (1 if step == 0 else 0)
        surplus = before_funds + discretionary - contributions - plan.protected_cents
        liquidity_daily = surplus // days if surplus > 0 else 0
        liquidity_weekly = surplus * min(7, days) // days if surplus > 0 else 0
        if target is None:
            daily, weekly = liquidity_daily, liquidity_weekly
        else:
            daily = min(discretionary // days, liquidity_daily)
            weekly = min(discretionary * min(7, days) // days, liquidity_weekly)
        liquidity += cash_flow
        debt = sum(state.balance_cents for state in loans)
        net_worth = None
        if plan.net_worth_cents is not None:
            liquid_total = liquidity + sum(held.values()) + tax_held
            net_worth = (plan.net_worth_cents + liquid_total - liquid_total_at_start
                         - (debt - debt_at_start))
        rows.append(MonthFigures(month, income, obligations, discretionary, loan_payments,
                                 accrual + contributions, cash_flow, liquidity, daily, weekly,
                                 debt, net_worth, scenario_assets,
                                 liquidity < plan.protected_cents))
    goals = []
    for fund in plan.funds:
        terms = fund.terms_on(as_of.isoformat()) or fund.terms[0]
        target = terms.amount_cents if terms.shape in (TARGET_BY, DUE, RECURRING) else None
        deadline = fund_deadline(terms, as_of) if target is not None else None
        goals.append(GoalFigures(fund.fund_id, fund.name, fund.kind, target, deadline,
                                 required_first.get(fund.fund_id, 0),
                                 completion.get(fund.fund_id), fund.fund_id in unmet,
                                 held[fund.fund_id]))
    without_target = [row.month for row in rows if plan.target_for(row.month) is None]
    missing = plan.missing + tuple(
        f"loan payoff {input_.input_id}: its loan has no balance observed, so it is left out"
        for input_ in inputs
        if input_.kind == LOAN_PAYOFF and input_.loan_terms_id not in loan_by_terms)
    if without_target:
        missing += (f"no budget plan in effect for {len(without_target)} months, from "
                    f"{without_target[0]}: discretionary spending projects at 0",)
    loan_rows = tuple(LoanFigures(state.name, state.balance_cents, state.paid_off, state.scenario)
                      for state in loans)
    return Projection(as_of.isoformat(), tuple(rows), tuple(goals), loan_rows,
                      {input_.input_id: found for input_ in inputs
                       if (found := look_alikes(plan, input_))},
                      ASSUMPTIONS, missing)
