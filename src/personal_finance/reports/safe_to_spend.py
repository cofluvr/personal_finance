"""Safe to spend: budget capacity and near-term liquidity, kept apart, and the lower of the two
with the constraint that limits it (D-072 points 1 and 3 to 6). Shared-contract §6's calculation
details are those points.

Read-only. Every figure is in integer cents and every division rounds toward protection (G8): a
spendable amount down, a reserved amount up. Nothing here reads the clock: as_of is always an
argument, and months and assignment events are read in the household's zone (G7). It never calls
totals and never runs the transfer candidate search (point 7).
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from personal_finance.money import format_cents
from personal_finance.planning.coverage import LOAN, load_coverages, possible_double_reservations
from personal_finance.planning.fund_restorations import load_restorations, restoration_on
from personal_finance.planning.funds import (
    EMERGENCY,
    GOAL,
    PERCENT,
    RESERVE,
    TAX,
    Fund,
    StandingInputs,
    account_holdings,
    assigned_to_fund,
    fund_standing,
    latest_observation,
    load_assignments,
    load_funds,
    load_portions,
    reductions_as_of,
)
from personal_finance.planning.income_effects import (
    EXPECTED,
    SALARY,
    applying_sources,
    load_deposit_facts,
    nominal_dates,
    occurrences,
    source_outcomes,
)
from personal_finance.planning.liquidity import liquid_account_ids
from personal_finance.planning.loans import load_loan_terms
from personal_finance.planning.obligation_effects import FIXED, applying_obligations
from personal_finance.planning.schedules import scheduled_dates, unpaid_state
from personal_finance.planning.settings import checking_buffer_cents, household_timezone
from personal_finance.reconcile.coverage_in_effect import (
    complete_coverage_by_basis,
    declared_coverage,
    spans_cover_every_day,
)
from personal_finance.reports.budget_report import budget_report
from personal_finance.reports.fund_standing import (
    baseline_income_cents,
    consumed_in_cycle,
    tax_required_cents,
)
from personal_finance.reports.income_report import month_end
from personal_finance.reports.loan_report import schedule

# An observation older than this at as_of makes the figure provisional (point 3).
STALE_OBSERVATION_DAYS = 7
# A card with activity this recent and no payment obligation makes it provisional (point 5).
CARD_ACTIVITY_DAYS = 60

BUDGET = "budget"
LIQUIDITY = "liquidity"

# The protected rows, in PRD §12's order (point 4).
TAX_ROW = "Side-income tax reserve"
BILLS_ROW = "Required bills and minimum debt payments"
RESERVES_ROW = "Annual and irregular expenses"
BUFFER_ROW = "Minimum checking buffer"
EMERGENCY_ROW = "Emergency-fund restoration"
GOALS_ROW = "Approved savings and extra debt-payment goals"
ROWS = (TAX_ROW, BILLS_ROW, RESERVES_ROW, BUFFER_ROW, EMERGENCY_ROW, GOALS_ROW)

# Provisional reasons (point 6), each with what clears it.
CLEARS = {
    "no_salary_source": "a salary source is confirmed (income add)",
    "paycheck_expected_not_received": "the deposit arrives, or its tolerance passes and it is "
                                      "missed",
    "no_liquidity_accounts": "an account is designated (account liquidity set)",
    "stale_observation": "a balance is recorded within 7 days (balance record)",
    "activity_incomplete": "complete coverage spans the days after the observation",
    "unvalued_liquidity_account": "a balance is recorded for the account (balance record)",
    "possible_spending": "unclassified and unconfirmed transfer-kind money out is classified",
    "open_review_items": "no open review item touches a liquidity account's activity",
    "card_without_payment_obligation": "an obligation is added for the card's payment",
    "over_assigned": "assignments are released, or a higher balance is observed",
    "possible_double_reservation": "the pair is linked (obligation covers), or shown distinct",
    "no_budget_plan": "a budget plan is in effect for the month (budget set)",
}
REASONS = tuple(CLEARS)


@dataclass(frozen=True)
class Horizon:
    as_of: str
    # N, the next salary paycheck, or None with no salary source: then the horizon runs to month
    # end.
    next_paycheck: str | None
    next_paycheck_source: str | None
    last_day: str
    days: int


@dataclass(frozen=True)
class LiquidAccount:
    account_id: str
    name: str
    observed_on: str | None
    observed_cents: int | None
    activity_cents: int
    activity_count: int
    # Left out: pending inflows and inflows of unknown status.
    left_out_cents: int
    stale: bool
    incomplete: bool

    @property
    def estimated_cents(self) -> int | None:
        return None if self.observed_cents is None else self.observed_cents + self.activity_cents


@dataclass(frozen=True)
class ProtectedItem:
    """One protected amount, and the planning entry it comes from: no entry is in two rows."""

    row: str
    entry_kind: str
    entry_id: str
    name: str
    cents: int
    detail: str


@dataclass
class SafeToSpend:
    as_of: str
    horizon: Horizon
    accounts: tuple[LiquidAccount, ...]
    items: tuple[ProtectedItem, ...]
    # Budget: M13's revised household allowances, or None with no plan in effect.
    budget_daily_cents: int | None
    budget_weekly_cents: int | None
    buffer_set: bool
    restoration_set: bool
    reasons: dict = field(default_factory=dict)
    double_reservations: tuple = ()

    @property
    def liquidity_evaluated(self) -> bool:
        return bool(self.accounts)

    @property
    def liquid_cents(self) -> int:
        return sum(account.estimated_cents or 0 for account in self.accounts)

    def row_cents(self, row: str) -> int:
        return sum(item.cents for item in self.items if item.row == row)

    @property
    def protected_cents(self) -> int:
        return sum(item.cents for item in self.items)

    @property
    def surplus_cents(self) -> int:
        return self.liquid_cents - self.protected_cents

    @property
    def liquidity_daily_cents(self) -> int | None:
        if not self.liquidity_evaluated:
            return None
        surplus = self.surplus_cents
        return surplus // self.horizon.days if surplus > 0 else 0

    @property
    def liquidity_weekly_cents(self) -> int | None:
        if not self.liquidity_evaluated:
            return None
        surplus, days = self.surplus_cents, self.horizon.days
        return surplus * min(7, days) // days if surplus > 0 else 0

    def _lower(self, liquidity, budget) -> int | None:
        found = [figure for figure in (liquidity, budget) if figure is not None]
        return max(0, min(found)) if found else None

    @property
    def today_cents(self) -> int | None:
        return self._lower(self.liquidity_daily_cents, self.budget_daily_cents)

    @property
    def week_cents(self) -> int | None:
        return self._lower(self.liquidity_weekly_cents, self.budget_weekly_cents)

    @property
    def limiting(self) -> str | None:
        """budget only when it is strictly lower today, else liquidity: ties go to liquidity."""
        if self.liquidity_daily_cents is None:
            return None if self.budget_daily_cents is None else BUDGET
        if self.budget_daily_cents is not None and \
                self.budget_daily_cents < self.liquidity_daily_cents:
            return BUDGET
        return LIQUIDITY

    @property
    def largest_row(self) -> str | None:
        rows = [(self.row_cents(row), -position, row) for position, row in enumerate(ROWS)
                if self.row_cents(row)]
        return max(rows)[2] if rows else None

    def largest_item(self, row: str) -> ProtectedItem | None:
        items = [item for item in self.items if item.row == row]
        return max(items, key=lambda item: (item.cents, item.name, item.entry_id),
                   default=None)

    @property
    def provisional(self) -> bool:
        return bool(self.reasons)


def household_month(stamp: str, zone) -> str:
    """The month a stored UTC timestamp falls in, in the household's zone."""
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return moment.astimezone(zone).isoformat()[:7]


def add_reason(reasons: dict, reason: str, detail: str) -> None:
    reasons.setdefault(reason, [])
    if detail not in reasons[reason]:
        reasons[reason].append(detail)


# Point 1: the horizon.

def horizon_until_paycheck(conn: sqlite3.Connection, as_of: date, reasons: dict) -> Horizon:
    salaries = [source for source in applying_sources(conn) if source.definition.kind == SALARY]
    if not salaries:
        add_reason(reasons, "no_salary_source", "no salary source applies")
        last = month_end(as_of.isoformat()[:7])
        return Horizon(as_of.isoformat(), None, None, last.isoformat(),
                       (last - as_of).days + 1)
    deposits = load_deposit_facts(conn, {source.definition.account_id for source in salaries})
    outcomes = source_outcomes(salaries, deposits)
    found = []
    for source in salaries:
        span = 31 * (max(1 if terms.cadence.name in ("weekly", "biweekly")
                         else terms.cadence.months_between for terms in source.terms) + 1)
        after = [nominal for nominal, _ in nominal_dates(source, as_of + timedelta(days=span))
                 if nominal > as_of]
        if after:
            found.append((after[0], source.definition.name, source.source_id))
        for occurrence in occurrences(source, deposits, outcomes, as_of):
            if occurrence.nominal_date <= as_of.isoformat() and occurrence.state == EXPECTED:
                add_reason(reasons, "paycheck_expected_not_received",
                           f"{source.definition.name}, due {occurrence.nominal_date}")
    if not found:
        add_reason(reasons, "no_salary_source", "no salary source has a pay date to come")
        last = month_end(as_of.isoformat()[:7])
        return Horizon(as_of.isoformat(), None, None, last.isoformat(),
                       (last - as_of).days + 1)
    paycheck, name, _ = min(found)
    last = paycheck - timedelta(days=1)
    return Horizon(as_of.isoformat(), paycheck.isoformat(), name, last.isoformat(),
                   max(1, (paycheck - as_of).days))


# Point 3: the liquid balance.

ACTIVITY = """
    SELECT entry.id, COALESCE(amount_fix.corrected_amount_cents, entry.amount_cents),
           entry.settlement_status,
           COALESCE(date_fix.corrected_text, entry.transaction_date, posting_fix.corrected_text,
                    entry.posting_date) AS effective_date
    FROM ledger_transaction entry
    LEFT JOIN transaction_correction amount_fix
        ON amount_fix.transaction_id = entry.id AND amount_fix.field = 'amount'
       AND amount_fix.state = 'applied'
    LEFT JOIN transaction_correction date_fix
        ON date_fix.transaction_id = entry.id AND date_fix.field = 'transaction_date'
       AND date_fix.state = 'applied'
    LEFT JOIN transaction_correction posting_fix
        ON posting_fix.transaction_id = entry.id AND posting_fix.field = 'posting_date'
       AND posting_fix.state = 'applied'
    WHERE entry.account_id = ? AND effective_date > ? AND effective_date <= ?"""


def last_covered_day(conn: sqlite3.Connection, account_id: str) -> str | None:
    """The last day any of the account's documents covers, of any kind: each document's
    declaration in effect, else its claim at import (D-051)."""
    declared = declared_coverage(conn, account_id)
    ends = []
    for document_id, end in conn.execute(
            "SELECT source_document_id, coverage_end FROM document_coverage WHERE account_id = ?",
            (account_id,)):
        if document_id in declared:
            end = declared[document_id].end
        if end is not None:
            ends.append(end)
    return max(ends, default=None)


def activity_incomplete(conn: sqlite3.Connection, account_id: str, observed_on: str) -> bool:
    """Whether no one date basis's complete coverage spans every day from the observation's
    next day through the last day the account's documents cover."""
    last = last_covered_day(conn, account_id)
    first = date.fromisoformat(observed_on) + timedelta(days=1)
    if last is None or date.fromisoformat(last) < first:
        return False
    days = [first + timedelta(days=offset)
            for offset in range((date.fromisoformat(last) - first).days + 1)]
    return not any(spans_cover_every_day(days, spans)
                   for spans in complete_coverage_by_basis(conn, account_id).values())


def liquid_account(conn: sqlite3.Connection, account_id: str, as_of: date) -> LiquidAccount:
    (name,) = conn.execute("SELECT display_name FROM account WHERE id = ?",
                           (account_id,)).fetchone()
    observation = latest_observation(conn, account_id, as_of.isoformat())
    if observation is None:
        return LiquidAccount(account_id, name, None, None, 0, 0, 0, False, False)
    counted = left_out = count = 0
    for _, cents, status, _ in conn.execute(ACTIVITY, (account_id, observation.observed_on,
                                                       as_of.isoformat())):
        if cents > 0 and status != "posted":
            left_out += cents
            continue
        counted += cents
        count += 1
    stale = (as_of - date.fromisoformat(observation.observed_on)).days > STALE_OBSERVATION_DAYS
    return LiquidAccount(account_id, name, observation.observed_on, observation.balance_cents,
                         counted, count, left_out, stale,
                         activity_incomplete(conn, account_id, observation.observed_on))


# Point 4: the protected rows.

def obligation_items(conn, horizon: Horizon, as_of: date, reserve_chains) -> list[ProtectedItem]:
    """Each applying fixed obligation's unpaid planned amounts due in the horizon, an occurrence
    still within its tolerance before as_of included. A chain covering a reserve counts in row 3
    instead."""
    paid = {(obligation_id, nominal) for obligation_id, nominal in conn.execute(
        "SELECT obligation_id, nominal_date FROM transaction_obligation "
        "WHERE nominal_date IS NOT NULL")}
    last = date.fromisoformat(horizon.last_day)
    items = []
    for obligation in applying_obligations(conn):
        if obligation.chain_id in reserve_chains:
            continue
        due, dates = 0, []
        for nominal, terms in scheduled_dates(obligation.terms, last):
            if terms.obligation_class != FIXED:
                continue
            if (obligation.obligation_id, nominal.isoformat()) in paid:
                continue
            if nominal < as_of and unpaid_state(
                    nominal, as_of, obligation.definition.tolerance_days) != EXPECTED:
                continue
            due += terms.planned_cents
            dates.append(nominal.isoformat())
        if due:
            items.append(ProtectedItem(BILLS_ROW, "obligation", obligation.obligation_id,
                                       obligation.definition.name, due,
                                       "planned, due " + ", ".join(dates)))
    return items


def loan_items(conn, horizon: Horizon, as_of: date, covered_loans) -> list[ProtectedItem]:
    """Each loan's scheduled payment due in the horizon less what was paid toward it, unless an
    obligation covers the loan, which counts in its place."""
    items = []
    last = date.fromisoformat(horizon.last_day)
    for account_id, terms in load_loan_terms(conn).items():
        if terms.account_type != "loan" or account_id in covered_loans:
            continue
        due, dates = 0, []
        for period in schedule(conn, terms, last):
            if as_of.isoformat() <= period.due <= horizon.last_day:
                outstanding = max(0, period.due_cents - period.paid_cents)
                if outstanding:
                    due += outstanding
                    dates.append(period.due)
        if due:
            items.append(ProtectedItem(BILLS_ROW, "loan", account_id, terms.account_name, due,
                                       "reserved, scheduled payment due " + ", ".join(dates)))
    return items


@dataclass(frozen=True)
class FundFigures:
    """What safe-to-spend reads of one fund as of a date."""

    on_liquid_cents: int
    on_other_cents: int
    # The increase in its assignments over as_of's month so far, from assignment events.
    increase_this_month_cents: int
    # Its planned contribution for the month, from the assignments at the month's start.
    planned_this_month_cents: int | None
    underfunded: bool


def fund_figures(conn, fund: Fund, as_of: date, context) -> FundFigures:
    assignments, reduced, liquid, zone = context
    text, month = as_of.isoformat(), as_of.isoformat()[:7]
    on_liquid = on_other = increase = 0
    for assignment in assignments:
        if assignment.fund_id != fund.fund_id:
            continue
        if assignment.applies:
            held = assignment.amount_cents - reduced.get(assignment.assignment_id, 0)
            if assignment.account_id in liquid:
                on_liquid += held
            else:
                on_other += held
        if household_month(assignment.created_at, zone) == month:
            increase += assignment.amount_cents
        if assignment.undone_at and household_month(assignment.undone_at, zone) == month:
            increase -= assignment.amount_cents
    assigned_now = assigned_to_fund(assignments, fund.fund_id, reduced)
    consumed, _ = consumed_in_cycle(fund, load_portions(conn, assignments), text)
    terms = fund.terms_on(text)
    baseline = (baseline_income_cents(conn, as_of)
                if terms is not None and terms.shape == PERCENT and fund.kind == GOAL else 0)
    inputs = StandingInputs(text, baseline_income_cents=baseline, consumed_cents=consumed)
    planned = None
    if fund.kind in (GOAL, RESERVE):
        planned = fund_standing(fund, assigned_now - increase, inputs).planned_contribution_cents
    underfunded = False
    if fund.kind == EMERGENCY:
        underfunded = bool(fund_standing(fund, assigned_now, inputs).outstanding_cents)
    return FundFigures(on_liquid, on_other, increase, planned, underfunded)


def fund_items(conn, as_of: date, zone, liquid) -> list[ProtectedItem]:
    assignments = load_assignments(conn)
    reduced = reductions_as_of(load_portions(conn, assignments), as_of.isoformat())
    context = (assignments, reduced, set(liquid), zone)
    rows = {TAX: TAX_ROW, RESERVE: RESERVES_ROW, EMERGENCY: EMERGENCY_ROW, GOAL: GOALS_ROW}
    items = []
    for fund in load_funds(conn):
        if not fund.applies:
            continue
        figures = fund_figures(conn, fund, as_of, context)
        if fund.kind == TAX:
            cents = max(0, tax_required_cents(conn, fund, as_of.isoformat())
                        - figures.on_other_cents)
            detail = "reserved, required less what other accounts hold for it"
        elif fund.kind == EMERGENCY:
            restoration = restoration_on(load_restorations(conn, fund.fund_id), as_of.isoformat())
            if restoration is None:
                detail = ("reserved, assigned on liquidity accounts; no restoration stated, so "
                          "restoring it is recommended only")
                cents = figures.on_liquid_cents
            else:
                outstanding = (max(0, restoration.monthly_cents
                                   - max(0, figures.increase_this_month_cents))
                               if figures.underfunded else 0)
                cents = figures.on_liquid_cents + outstanding
                detail = (f"reserved, assigned on liquidity accounts plus restoration this month "
                          f"{format_cents(outstanding)}")
        else:
            outstanding = max(0, (figures.planned_this_month_cents or 0)
                              - figures.increase_this_month_cents)
            cents = figures.on_liquid_cents + outstanding
            detail = (f"reserved, assigned on liquidity accounts plus outstanding contribution "
                      f"this month {format_cents(outstanding)}")
        if cents:
            items.append(ProtectedItem(rows[fund.kind], "fund", fund.fund_id, fund.name, cents,
                                       detail))
    return items


# The checks behind the provisional reasons (point 6).

def open_items_on(conn, accounts) -> int:
    """Open review items with a subject transaction of a liquidity account dated after its
    observation, or an unresolved record of the account."""
    count = set()
    for account in accounts:
        after = account.observed_on or "0000-00-00"
        count |= {issue for (issue,) in conn.execute(
            """SELECT DISTINCT issue.id FROM review_issue issue
               JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
               LEFT JOIN ledger_transaction entry ON entry.id = subject.transaction_id
               LEFT JOIN source_record record ON record.id = subject.source_record_id
               WHERE issue.status = 'open'
                 AND ((entry.account_id = ? AND COALESCE(entry.transaction_date,
                                                         entry.posting_date) > ?)
                      OR (issue.kind = 'unresolved_record' AND record.account_id = ?))""",
            (account.account_id, after, account.account_id))}
    return len(count)


def cards_without_payment(conn, as_of: date) -> list[str]:
    """Cards with activity in the last 60 days and no applying fixed obligation naming them: on
    the card itself, or whose name or matcher holds the card's name, ignoring case."""
    obligations = applying_obligations(conn)
    since = (as_of - timedelta(days=CARD_ACTIVITY_DAYS)).isoformat()
    found = []
    for account_id, name in conn.execute(
            "SELECT id, display_name FROM account WHERE account_type = 'credit_card' "
            "ORDER BY display_name"):
        (active,) = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM ledger_transaction WHERE account_id = ? "
            "AND COALESCE(transaction_date, posting_date) > ? "
            "AND COALESCE(transaction_date, posting_date) <= ?)",
            (account_id, since, as_of.isoformat())).fetchone()
        if not active:
            continue
        lowered = name.lower()
        if not any(obligation.definition.account_id == account_id
                   or lowered in obligation.definition.name.lower()
                   or lowered in obligation.definition.description_contains.lower()
                   for obligation in obligations):
            found.append(name)
    return found


def safe_to_spend(conn: sqlite3.Connection, as_of: date) -> SafeToSpend:
    """Safe to spend as of a date. The household timezone must be set: the caller refuses
    without it (G7)."""
    zone = household_timezone(conn)
    if zone is None:
        raise ValueError("safe to spend needs the household timezone")
    reasons = {}
    horizon = horizon_until_paycheck(conn, as_of, reasons)

    liquid = liquid_account_ids(conn)
    accounts = tuple(liquid_account(conn, account_id, as_of) for account_id in liquid)
    if not accounts:
        add_reason(reasons, "no_liquidity_accounts", "no account is designated")
    for account in accounts:
        if account.observed_on is None:
            add_reason(reasons, "unvalued_liquidity_account", account.name)
            continue
        if account.stale:
            add_reason(reasons, "stale_observation",
                       f"{account.name} observed {account.observed_on}")
        if account.incomplete:
            add_reason(reasons, "activity_incomplete", account.name)

    coverages = load_coverages(conn)
    reserve_chains = {coverage.chain_id for coverage in coverages if coverage.fund_id}
    applying_chains = {obligation.chain_id for obligation in applying_obligations(conn)}
    covered_loans = {coverage.loan_account_id for coverage in coverages
                     if coverage.target[0] == LOAN and coverage.chain_id in applying_chains}
    items = [*fund_items(conn, as_of, zone, liquid),
             *obligation_items(conn, horizon, as_of, reserve_chains & applying_chains),
             *loan_items(conn, horizon, as_of, covered_loans)]
    buffer = checking_buffer_cents(conn)
    if buffer and accounts:
        items.append(ProtectedItem(BUFFER_ROW, "setting", "checking_buffer_cents",
                                   "checking buffer", buffer, "reserved, the setting"))
    items.sort(key=lambda item: (ROWS.index(item.row), item.name, item.entry_id))

    for holding in account_holdings(conn, as_of.isoformat()):
        if holding.account_id in liquid and holding.over_assigned_cents:
            add_reason(reasons, "over_assigned", holding.account_name)
    alikes = possible_double_reservations(conn, as_of)
    for alike in alikes:
        add_reason(reasons, "possible_double_reservation",
                   f"obligation {alike.obligation_id} and {alike.target_kind} "
                   f"{alike.target_name}")
    for name in cards_without_payment(conn, as_of):
        add_reason(reasons, "card_without_payment_obligation", name)
    open_count = open_items_on(conn, accounts)
    if open_count:
        add_reason(reasons, "open_review_items", f"{open_count} open on liquidity accounts")

    budget = budget_report(conn, as_of.isoformat()[:7], as_of, None)
    daily = weekly = None
    if budget.plan is None or budget.pace is None:
        add_reason(reasons, "no_budget_plan", f"none in effect for {as_of.isoformat()[:7]}")
    else:
        daily, weekly = budget.pace.revised_daily_cents, budget.pace.revised_weekly_cents
    if budget.unclassified.count or budget.transfer_kinds.count:
        add_reason(reasons, "possible_spending",
                   f"{budget.unclassified.count + budget.transfer_kinds.count} transactions "
                   "this month")
    restoration_set = any(load_restorations(conn, fund.fund_id) for fund in load_funds(conn)
                          if fund.applies and fund.kind == EMERGENCY)
    return SafeToSpend(as_of.isoformat(), horizon, accounts, tuple(items), daily, weekly,
                       buffer is not None, restoration_set,
                       {reason: reasons[reason] for reason in REASONS if reason in reasons},
                       alikes)
