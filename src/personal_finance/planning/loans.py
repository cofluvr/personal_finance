"""Loan terms with dated rate and payment periods, projections and payoff orders (D-071 points 4
to 6).

A loan's or card's terms hold a due day, optional remaining months as the lender states them,
rate periods (an APR in millionths of a percent, G8) and, for a loan, payment periods: a graduated
schedule is a sequence of these. The amount due on a due date is the payment period in effect that
day, and the rate for a month the period in effect on its first day. Writes run under one write
lock with the lt1 token and change no ledger table (G1).

Projections and payoff orders are pure, in Decimal with 28 digits, interest quantized to cents
half-even once a month (point 5). Every figure they give is a projection, not lender-exact.
Nothing here reads the clock (G7).
"""

import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from personal_finance.planning.entries import (
    in_one_write,
    parsed_amount,
    parsed_date,
    refuse_unless_revision,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reports.category_rule_evidence import digest

# Bump whenever the material below changes, so an old token can never appear current.
LOAN_REVISION_VERSION = 1

ADD = "add"
RATE = "rate"
PAYMENT = "payment"
UNDO = "undo"
PLAN = "plan"

AVALANCHE = "avalanche"
SNOWBALL = "snowball"
CUSTOM = "custom"
ORDERS = (AVALANCHE, SNOWBALL)

HORIZON_MONTHS = 600
MILLIONTHS_IN_WHOLE = 100_000_000
PROJECTION_LABEL = "projection, not lender-exact"
ASSUMPTIONS = (
    "Start: the latest balance observation on or before the date, a confirmed balance",
    "Interest each month: balance × APR ÷ 12, in Decimal, quantized to cents half-even once a "
    "month, at the rate in effect on the month's first day",
    "Payment: the scheduled payment in effect on each due date, plus any extra assumed",
    "Not modelled: fees, late charges, daily accrual, payment allocation order and "
    "capitalization",
    "Negative amortization: interest above the payment is flagged, and the loan never pays off "
    "within the horizon",
    f"Horizon: at most {HORIZON_MONTHS} months",
)

_RATE = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,6})?")

TERMS_ACCOUNT = "{account} is not a loan or a card: only they take loan terms. Nothing was changed."
TERMS_EXIST = (
    "{account} has loan terms already. Change them with loan rate or loan payment, or undo them "
    "first. Nothing was changed."
)
NO_TERMS = "{account} has no loan terms. Run loan terms add first. Nothing was changed."
PAYMENT_ON_CARD = (
    "a card takes a rate only, for interest projection: it has no scheduled payment. Nothing was "
    "changed."
)
PAYMENT_REQUIRED = "a loan's terms need --payment, the scheduled payment. Nothing was changed."
RATE_INVALID = (
    "--rate must be an APR from 0 to 100 percent with at most six decimals, such as 6.875. "
    "Nothing was changed."
)
PAYMENT_INVALID = "--payment must be an amount above zero, such as 1500.00. Nothing was changed."
EXTRA_INVALID = "--extra must be an amount above zero, such as 200.00. Nothing was changed."
DUE_DAY_INVALID = (
    "--due-day must be a day from 1 to 28: a later day is not clamped to a month's end. Nothing "
    "was changed."
)
REMAINING_INVALID = "--remaining-months must be a whole number from 1 to 600. Nothing was changed."
PERIOD_TAKEN = (
    "a {kind} period already starts on {day}. Choose another day. Nothing was changed."
)
PERIOD_BEFORE_TERMS = (
    "--effective-from must be no earlier than the terms' first period, from {day}. Nothing was "
    "changed."
)
ORDER_INVALID = (
    "--order must be avalanche, snowball or custom:A,B,... naming each loan with terms once. "
    "Nothing was changed."
)
ORDER_ACCOUNT = (
    "{account} cannot be in a payoff order: only a loan with loan terms can. Nothing was "
    "changed."
)
EXTRA_FUND_INVALID = (
    "--extra-from-fund must name an active goal: its planned contribution is the debt goal's "
    "amount (D-070 point 4). Nothing was changed."
)
EXTRA_TWICE = "give --extra or --extra-from-fund, not both. Nothing was changed."
STALE_LOAN_REVISION = (
    "this revision does not match the loan terms as they are now. Nothing was changed. Run loan "
    "terms show and check them again."
)
STALE_PLAN_REVISION = (
    "this revision does not match the payoff plan as it is now. Nothing was changed. Run report "
    "loans and check it again."
)


# The model.

@dataclass(frozen=True)
class LoanTerms:
    terms_id: str
    account_id: str
    account_name: str
    account_type: str
    due_day: int
    remaining_months: int | None
    # (effective_from, millionths) and (effective_from, cents), oldest first.
    rates: tuple[tuple[str, int], ...]
    payments: tuple[tuple[str, int], ...]

    def rate_on(self, day: str) -> int | None:
        """The rate period in effect on a day, or None before the first."""
        found = [rate for start, rate in self.rates if start <= day]
        return found[-1] if found else None

    def payment_on(self, day: str) -> int:
        """The payment period in effect on a day, else 0."""
        found = [payment for start, payment in self.payments if start <= day]
        return found[-1] if found else 0

    @property
    def first_day(self) -> str:
        return min(start for start, _ in (*self.rates, *self.payments))


@dataclass(frozen=True)
class PayoffPlan:
    plan_id: str
    order_kind: str
    # Account IDs, for a custom order.
    custom_order: tuple[str, ...]
    extra_cents: int | None
    extra_fund_id: str | None


def load_loan_terms(conn: sqlite3.Connection) -> dict[str, LoanTerms]:
    """Every account's active terms, by account ID."""
    found = {}
    for terms_id, account_id, name, account_type, due_day, remaining in conn.execute(
            """SELECT terms.id, terms.account_id, account.display_name, account.account_type,
                      terms.due_day, terms.remaining_months
               FROM loan_terms terms JOIN account ON account.id = terms.account_id
               WHERE NOT EXISTS (SELECT 1 FROM loan_terms_event undone
                                 WHERE undone.terms_id = terms.id AND undone.event = 'undone')
               ORDER BY account.display_name"""):
        rates = tuple(conn.execute(
            "SELECT effective_from, rate_millionths FROM loan_rate_period WHERE terms_id = ? "
            "ORDER BY effective_from", (terms_id,)))
        payments = tuple(conn.execute(
            "SELECT effective_from, payment_cents FROM loan_payment_period WHERE terms_id = ? "
            "ORDER BY effective_from", (terms_id,)))
        found[account_id] = LoanTerms(terms_id, account_id, name, account_type, due_day,
                                      remaining, rates, payments)
    return found


def active_plan(conn: sqlite3.Connection) -> PayoffPlan | None:
    row = conn.execute(
        """SELECT plan.id, plan.order_kind, plan.custom_order, plan.extra_cents,
                  plan.extra_fund_id
           FROM payoff_plan plan JOIN payoff_plan_event made ON made.plan_id = plan.id
           ORDER BY made.id DESC LIMIT 1""").fetchone()
    if row is None:
        return None
    plan_id, kind, custom, extra, fund = row
    return PayoffPlan(plan_id, kind, tuple(custom.split(",")) if custom else (), extra, fund)


# Parsing.

def parsed_rate(text: str) -> int:
    """An APR as typed, in millionths of a percent."""
    if not _RATE.fullmatch(text):
        raise DecisionRefused(RATE_INVALID)
    whole, _, fraction = text.partition(".")
    millionths = int(whole) * 1_000_000 + int((fraction + "000000")[:6])
    if millionths > MILLIONTHS_IN_WHOLE:
        raise DecisionRefused(RATE_INVALID)
    return millionths


def format_rate(millionths: int) -> str:
    whole, fraction = divmod(millionths, 1_000_000)
    return f"{whole}.{fraction:06d}".rstrip("0").rstrip(".") + "%"


def parsed_due_day(text: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 28:
        raise DecisionRefused(DUE_DAY_INVALID)
    return int(text)


# Tokens.

def terms_revision(operation: str, account_id: str, terms: LoanTerms | None) -> str:
    """lt1 covers the operation, the account, and its active terms: due day, remaining months
    and every rate and payment period (D-071 point 8)."""
    material = {"operation": operation, "account_id": account_id,
                "terms": None if terms is None else {
                    "due_day": terms.due_day, "remaining_months": terms.remaining_months,
                    "rates": [list(rate) for rate in terms.rates],
                    "payments": [list(payment) for payment in terms.payments]}}
    return f"lt{LOAN_REVISION_VERSION}-{digest(material)}"


def plan_revision(plan: PayoffPlan | None) -> str:
    """lt1 over the payoff plan as it applies now."""
    material = {"operation": PLAN, "plan": None if plan is None else [
        plan.order_kind, list(plan.custom_order), plan.extra_cents, plan.extra_fund_id]}
    return f"lt{LOAN_REVISION_VERSION}-{digest(material)}"


# Writes.

def account_kind(conn, account_id) -> tuple[str, str]:
    return conn.execute("SELECT display_name, account_type FROM account WHERE id = ?",
                        (account_id,)).fetchone()


@dataclass(frozen=True)
class TermsRequest:
    rate: str
    due_day: str
    effective_from: str
    payment: str | None = None
    remaining_months: str | None = None


def add_terms(conn: sqlite3.Connection, account_id: str, request: TermsRequest,
              revision: str) -> str:
    """Record an account's loan terms, or refuse and change nothing."""
    return in_one_write(conn, lambda: _add_terms(conn, account_id, request, revision))


def _add_terms(conn, account_id, request, revision) -> str:
    name, account_type = account_kind(conn, account_id)
    if account_type not in ("loan", "credit_card"):
        raise DecisionRefused(TERMS_ACCOUNT.format(account=name))
    existing = load_loan_terms(conn).get(account_id)
    if existing is not None:
        raise DecisionRefused(TERMS_EXIST.format(account=name))
    if account_type == "credit_card" and request.payment is not None:
        raise DecisionRefused(PAYMENT_ON_CARD)
    if account_type == "loan" and request.payment is None:
        raise DecisionRefused(PAYMENT_REQUIRED)
    rate = parsed_rate(request.rate)
    due_day = parsed_due_day(request.due_day)
    effective_from = parsed_date(request.effective_from, "--effective-from")
    payment = None if request.payment is None else parsed_amount(request.payment,
                                                                 PAYMENT_INVALID, least=1)
    remaining = request.remaining_months
    if remaining is not None:
        if not remaining.isdigit() or not 1 <= int(remaining) <= HORIZON_MONTHS:
            raise DecisionRefused(REMAINING_INVALID)
        remaining = int(remaining)
    refuse_unless_revision(terms_revision(ADD, account_id, None), revision, STALE_LOAN_REVISION)
    terms_id = str(uuid.uuid4())
    conn.execute("INSERT INTO loan_terms (id, account_id, due_day, remaining_months) "
                 "VALUES (?, ?, ?, ?)", (terms_id, account_id, due_day, remaining))
    conn.execute("INSERT INTO loan_rate_period (terms_id, effective_from, rate_millionths) "
                 "VALUES (?, ?, ?)", (terms_id, effective_from, rate))
    if payment is not None:
        conn.execute("INSERT INTO loan_payment_period (terms_id, effective_from, payment_cents) "
                     "VALUES (?, ?, ?)", (terms_id, effective_from, payment))
    conn.execute("INSERT INTO loan_terms_event (terms_id, event) VALUES (?, 'made')", (terms_id,))
    return terms_id


def add_period(conn: sqlite3.Connection, account_id: str, kind: str, value: str,
               effective_from: str, revision: str) -> int:
    """Add a rate or payment period from a date, a new step of the schedule (point 4)."""
    return in_one_write(conn, lambda: _add_period(conn, account_id, kind, value, effective_from,
                                                  revision))


def _add_period(conn, account_id, kind, value, effective_from, revision) -> int:
    name, account_type = account_kind(conn, account_id)
    terms = load_loan_terms(conn).get(account_id)
    if terms is None:
        raise DecisionRefused(NO_TERMS.format(account=name))
    if kind == PAYMENT and account_type != "loan":
        raise DecisionRefused(PAYMENT_ON_CARD)
    cents = (parsed_rate(value) if kind == RATE
             else parsed_amount(value, PAYMENT_INVALID, least=1))
    effective_from = parsed_date(effective_from, "--effective-from")
    if effective_from < terms.first_day:
        raise DecisionRefused(PERIOD_BEFORE_TERMS.format(day=terms.first_day))
    periods = terms.rates if kind == RATE else terms.payments
    if any(start == effective_from for start, _ in periods):
        raise DecisionRefused(PERIOD_TAKEN.format(kind=kind, day=effective_from))
    refuse_unless_revision(terms_revision(kind, account_id, terms), revision, STALE_LOAN_REVISION)
    table, column = (("loan_rate_period", "rate_millionths") if kind == RATE
                     else ("loan_payment_period", "payment_cents"))
    conn.execute(f"INSERT INTO {table} (terms_id, effective_from, {column}) VALUES (?, ?, ?)",
                 (terms.terms_id, effective_from, cents))
    return cents


def undo_terms(conn: sqlite3.Connection, account_id: str, revision: str) -> LoanTerms:
    return in_one_write(conn, lambda: _undo_terms(conn, account_id, revision))


def _undo_terms(conn, account_id, revision) -> LoanTerms:
    terms = load_loan_terms(conn).get(account_id)
    if terms is None:
        raise DecisionRefused(NO_TERMS.format(account=account_kind(conn, account_id)[0]))
    refuse_unless_revision(terms_revision(UNDO, account_id, terms), revision, STALE_LOAN_REVISION)
    conn.execute("INSERT INTO loan_terms_event (terms_id, event) VALUES (?, 'undone')",
                 (terms.terms_id,))
    return terms


def checked_order(conn: sqlite3.Connection, text: str, find_account) -> tuple[str, tuple]:
    """An order as typed: avalanche, snowball, or custom:A,B,... naming each loan with terms."""
    if text in ORDERS:
        return text, ()
    if not text.startswith("custom:") or not text[7:]:
        raise DecisionRefused(ORDER_INVALID)
    loans = {account_id for account_id, terms in load_loan_terms(conn).items()
             if terms.account_type == "loan"}
    named = []
    for typed in text[7:].split(","):
        account_id = find_account(conn, typed)
        if account_id not in loans:
            raise DecisionRefused(ORDER_ACCOUNT.format(account=typed))
        named.append(account_id)
    if len(set(named)) != len(named) or set(named) != loans:
        raise DecisionRefused(ORDER_INVALID)
    return CUSTOM, tuple(named)


def set_plan(conn: sqlite3.Connection, order: str, extra: str | None, extra_fund_id: str | None,
             revision: str, find_account) -> str:
    """Replace the payoff plan, or refuse and change nothing."""
    return in_one_write(conn, lambda: _set_plan(conn, order, extra, extra_fund_id, revision,
                                                find_account))


def _set_plan(conn, order, extra, extra_fund_id, revision, find_account) -> str:
    kind, custom = checked_order(conn, order, find_account)
    if extra is not None and extra_fund_id is not None:
        raise DecisionRefused(EXTRA_TWICE)
    extra_cents = None if extra is None else parsed_amount(extra, EXTRA_INVALID, least=1)
    if extra_fund_id is not None and conn.execute(
            """SELECT 1 FROM fund WHERE id = ? AND kind = 'goal' AND NOT EXISTS (
                   SELECT 1 FROM fund_event undone
                   WHERE undone.fund_id = fund.id AND undone.event = 'undone')""",
            (extra_fund_id,)).fetchone() is None:
        raise DecisionRefused(EXTRA_FUND_INVALID)
    refuse_unless_revision(plan_revision(active_plan(conn)), revision, STALE_PLAN_REVISION)
    plan_id = str(uuid.uuid4())
    conn.execute("INSERT INTO payoff_plan (id, order_kind, custom_order, extra_cents, "
                 "extra_fund_id) VALUES (?, ?, ?, ?, ?)",
                 (plan_id, kind, ",".join(custom) or None, extra_cents, extra_fund_id))
    conn.execute("INSERT INTO payoff_plan_event (plan_id, event) VALUES (?, 'made')", (plan_id,))
    return plan_id


# Due dates and the schedule (point 6).

def month_add(day: date, months: int) -> tuple[int, int]:
    index = day.year * 12 + day.month - 1 + months
    return index // 12, index % 12 + 1


def due_dates_between(due_day: int, after: date, through: date) -> list[date]:
    """Due dates after one day through another, both by the due day of each month."""
    found = []
    year, month = after.year, after.month
    while True:
        due = date(year, month, due_day)
        if due > through:
            return found
        if due > after:
            found.append(due)
        year, month = month_add(due, 1)


def next_due_date(due_day: int, after: date) -> date:
    year, month = after.year, after.month
    due = date(year, month, due_day)
    if due > after:
        return due
    year, month = month_add(due, 1)
    return date(year, month, due_day)


ON_SCHEDULE = "on_schedule"
SHORT = "short"
EXTRA = "extra"
MISSED = "missed"
UPCOMING = "upcoming"


def period_state(due_cents: int, paid_cents: int, due: date, as_of: date) -> str:
    """Actual against schedule for one due period (point 6)."""
    if paid_cents == due_cents:
        return ON_SCHEDULE
    if paid_cents > due_cents:
        return EXTRA
    if due >= as_of:
        return UPCOMING
    return MISSED if paid_cents == 0 else SHORT


# Projection (point 5), pure.

def monthly_interest(balance_cents: int, rate_millionths: int) -> int:
    """balance × APR ÷ 12, quantized to cents half-even, in a 28-digit Decimal context."""
    with localcontext() as context:
        context.prec = 28
        # The context's divide, never the / operator, so no float can stand in (G8).
        exact = context.divide(Decimal(balance_cents) * Decimal(rate_millionths),
                               Decimal(MILLIONTHS_IN_WHOLE * 12))
        return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True)
class ProjectedMonth:
    due: str
    rate_millionths: int
    payment_cents: int
    interest_cents: int
    principal_cents: int
    balance_cents: int
    negative_amortization: bool


@dataclass(frozen=True)
class Projection:
    start: str
    start_balance_cents: int
    months: tuple[ProjectedMonth, ...]
    paid_off: str | None

    @property
    def total_interest_cents(self) -> int:
        return sum(month.interest_cents for month in self.months)

    @property
    def negative_amortization(self) -> bool:
        return any(month.negative_amortization for month in self.months)


def project(terms: LoanTerms, owed_cents: int, observed_on: str, extra_cents: int = 0,
            months: int = HORIZON_MONTHS) -> Projection:
    """Month by month from the first due date after the observation: interest at the rate in
    effect on the month's first day, then the payment in effect on the due date plus the extra,
    the last payment no more than what is owed. Stops when paid off, or after months, at most
    the horizon."""
    months = min(months, HORIZON_MONTHS)
    balance = owed_cents
    rows = []
    due = date.fromisoformat(observed_on)
    paid_off = None
    for _ in range(months):
        if balance <= 0:
            break
        due = next_due_date(terms.due_day, due)
        rate = terms.rate_on(due.replace(day=1).isoformat())
        rate = terms.rates[0][1] if rate is None else rate
        interest = monthly_interest(balance, rate)
        scheduled = terms.payment_on(due.isoformat()) + extra_cents
        payment = min(scheduled, balance + interest)
        balance = balance + interest - payment
        rows.append(ProjectedMonth(due.isoformat(), rate, payment, interest, payment - interest,
                                   balance, interest > scheduled))
        if balance == 0:
            paid_off = due.isoformat()
    return Projection(observed_on, owed_cents, tuple(rows), paid_off)


# Payoff orders (point 6), pure.

@dataclass(frozen=True)
class DebtAtStart:
    terms: LoanTerms
    owed_cents: int
    rate_millionths: int


@dataclass
class PayoffOutcome:
    order: str
    # Account IDs in the order paid toward.
    sequence: tuple[str, ...]
    # Each account's payoff due date, None beyond the horizon, and its total interest.
    payoff_by_account: dict[str, str | None] = field(default_factory=dict)
    interest_by_account: dict[str, int] = field(default_factory=dict)
    months_to_debt_free: int | None = None


def ordered(debts, order: str, custom: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Avalanche: highest rate first, ties to the larger balance, then the account name.
    Snowball: smallest balance first, ties to the higher rate, then the name. Custom: as stated."""
    if order == AVALANCHE:
        key = lambda debt: (-debt.rate_millionths, -debt.owed_cents, debt.terms.account_name)
    elif order == SNOWBALL:
        key = lambda debt: (debt.owed_cents, -debt.rate_millionths, debt.terms.account_name)
    else:
        return custom
    return tuple(debt.terms.account_id for debt in sorted(debts, key=key))


def payoff(debts, order: str, extra_cents: int, start: date,
           custom: tuple[str, ...] = ()) -> PayoffOutcome:
    """Each month from the one after start, the budget is every loan's scheduled payment in
    effect, paid off or not, plus the extra. Each unpaid loan takes its scheduled payment, no
    more than it owes, and what is left goes to the first unpaid loan in the order, then the
    next, so a paid-off loan's payment rolls over."""
    sequence = ordered(debts, order, custom)
    by_id = {debt.terms.account_id: debt for debt in debts}
    owed = {account_id: by_id[account_id].owed_cents for account_id in sequence}
    outcome = PayoffOutcome(order, sequence, {account_id: None for account_id in sequence},
                            {account_id: 0 for account_id in sequence})
    for step in range(1, HORIZON_MONTHS + 1):
        if all(balance <= 0 for balance in owed.values()):
            break
        year, month = month_add(start, step)
        budget = extra_cents
        dues = {}
        for account_id in sequence:
            terms = by_id[account_id].terms
            due = date(year, month, terms.due_day)
            dues[account_id] = due
            budget += terms.payment_on(due.isoformat())
        for account_id in sequence:
            if owed[account_id] <= 0:
                continue
            terms = by_id[account_id].terms
            rate = terms.rate_on(dues[account_id].replace(day=1).isoformat())
            interest = monthly_interest(owed[account_id], rate or 0)
            owed[account_id] += interest
            outcome.interest_by_account[account_id] += interest
            payment = min(terms.payment_on(dues[account_id].isoformat()), owed[account_id],
                          budget)
            owed[account_id] -= payment
            budget -= payment
        for account_id in sequence:
            if budget <= 0:
                break
            if owed[account_id] > 0:
                payment = min(budget, owed[account_id])
                owed[account_id] -= payment
                budget -= payment
        for account_id in sequence:
            if owed[account_id] <= 0 and outcome.payoff_by_account[account_id] is None:
                outcome.payoff_by_account[account_id] = dues[account_id].isoformat()
        if all(balance <= 0 for balance in owed.values()):
            outcome.months_to_debt_free = step
            break
    return outcome
