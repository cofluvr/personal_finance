"""Funds stated by a person (D-070 points 1 to 4): goals, the emergency fund, reserves and the tax
reserve, each with dated terms; assignments of an account's observed balance to a fund; and one
priority list. Each write runs under one write lock with its fu1 or fa1 token, and changes no
ledger table (G1). Nothing is ever assigned automatically (point 3).

The required amount of each kind is a pure function here, in integer cents, every division
rounded up, since a required amount rounds toward protection (G8). Nothing here reads the clock:
as_of is always an argument (G7). The figures that need income or obligations are gathered in
reports/fund_standing.py.
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from personal_finance.money import format_cents
from personal_finance.planning.entries import (
    checked_cadence,
    in_one_write,
    parsed_amount,
    parsed_date,
    refuse_if_closed_month,
    refuse_unless_current,
    refuse_unless_revision,
)
from personal_finance.planning.schedules import Cadence, cadence_dates, on_cadence
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.household_effects import parse_percent
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reports.category_rule_evidence import digest

# Bump whenever the material below changes, so an old token can never appear current.
FUND_REVISION_VERSION = 1
ASSIGNMENT_REVISION_VERSION = 1

GOAL = "goal"
EMERGENCY = "emergency"
RESERVE = "reserve"
TAX = "tax"
KINDS = (GOAL, EMERGENCY, RESERVE, TAX)
# The kinds the priority list orders. The tax reserve is protected first, never by priority.
PRIORITY_KINDS = (GOAL, EMERGENCY, RESERVE)
# One of each of these at a time: "the emergency fund" and "the tax reserve".
ONE_ACTIVE_KINDS = (EMERGENCY, TAX)

MONTHLY = "monthly"
PERCENT = "percent"
TARGET_BY = "target_by"
MINIMUM = "minimum"
MONTHS = "months"
DUE = "due"
RECURRING = "recurring"

ADD = "add"
TERMS = "terms"
UNDO = "undo"
PRIORITY = "priority"
ASSIGN = "assign"
UNASSIGN = "unassign"

# States of a fund as of a date.
FUNDED = "funded"
UNDERFUNDED = "underfunded"
IN_PROGRESS = "in_progress"
NOT_STARTED = "not_started"

# Accounts that can hold money for a fund (point 2). A card or loan owes, and retirement stays
# apart from fund priority (point 3).
ASSIGNABLE_ACCOUNT_TYPES = ("checking", "savings", "investment")
# An observation older than this at as_of keeps its assignments, marked provisional (point 2).
STALE_OBSERVATION_DAYS = 31
# A fund's ID while it is only previewed.
PROPOSED_FUND_ID = "proposed"

NAME_BLANK = "a fund needs a name that is not blank. Nothing was changed."
NAME_TAKEN = "fund {fund} is active and has this name already. Nothing was changed."
KIND_UNKNOWN = "--kind must be goal, emergency, reserve or tax. Nothing was changed."
ONE_ACTIVE = (
    "fund {fund} is the active {kind} fund already, and there is one at a time. Undo it first. "
    "Nothing was changed."
)
TERMS_FOR_KIND = {
    GOAL: ("a goal takes exactly one of --monthly AMOUNT, --percent-of-income PCT, or --target "
           "AMOUNT with --by YYYY-MM, and nothing else. Nothing was changed."),
    EMERGENCY: ("the emergency fund takes exactly one of --minimum AMOUNT or --months N, and "
                "nothing else. Nothing was changed."),
    RESERVE: ("a reserve takes --target AMOUNT with exactly one of --due DATE or --cadence, "
              "--anchor going with an every-N-months cadence only, and nothing else. Nothing "
              "was changed."),
    TAX: "the tax reserve takes --percent PCT, and nothing else. Nothing was changed.",
}
AMOUNT_INVALID = "{option} must be an amount above zero, such as 500.00. Nothing was changed."
PERCENT_INVALID = (
    "{option} must be a percentage above 0 and at most 100, with at most two decimals, such as "
    "12.5. Nothing was changed."
)
MONTHS_INVALID = "--months must be a whole number from 1 to 120. Nothing was changed."
BY_INVALID = "--by must be a month written YYYY-MM. Nothing was changed."
BY_BEFORE_START = (
    "--by must be no earlier than the month of --effective-from. Nothing was changed."
)
DUE_BEFORE_START = "--due must be no earlier than --effective-from. Nothing was changed."
CADENCE_FOR_RESERVE = (
    "a reserve's --cadence is annual:MM-DD, or every:N-months:D with --anchor. Nothing was "
    "changed."
)
ANCHOR_OFF_CADENCE = (
    "--anchor must be one of the cadence's own due dates. Nothing was changed."
)
CLOSED_MONTH = (
    "--effective-from falls in a month before --as-of's, which is closed. Nothing was changed."
)
TERMS_NOT_LATER = (
    "--effective-from must be later than every terms row of this fund, the latest from "
    "{latest}. Nothing was changed."
)
FUND_NOT_FOUND = "fund not found. Run funds. Nothing was changed."
FUND_NOT_ACTIVE = "this fund has already been undone. Nothing was changed."
UNDO_ASSIGNED = (
    "this fund holds assignments on {accounts}. Release each with fund unassign first. Nothing "
    "was changed."
)
PRIORITY_KIND = (
    "fund {fund} is the tax reserve, which is protected first and never ordered by priority. "
    "Nothing was changed."
)
PRIORITY_REPEATED = "fund {fund} is named twice. Name each fund once. Nothing was changed."
ACCOUNT_NOT_ASSIGNABLE = (
    "a {account_type} account cannot hold a fund's money: only checking, savings and investment "
    "accounts can. Nothing was changed."
)
NO_OBSERVATION = (
    "this account has no balance observation on or before {as_of}, so it can hold no "
    "assignment. Run balance record first. Nothing was changed."
)
ALREADY_ASSIGNED = (
    "this fund holds an assignment on this account already. Release it with fund unassign, then "
    "assign the new amount. Nothing was changed."
)
NOT_ASSIGNED = "this fund holds no assignment on this account. Nothing was changed."
BEYOND_OBSERVATION = (
    "assigning {amount} would put {total} of this account's balance in funds, beyond its "
    "observed balance of {balance} on {observed_on}. At most {unassigned} is unassigned. Nothing "
    "was changed."
)
STALE_FUND_PREVIEW = (
    "this revision does not match the fund as previewed now. Nothing was changed. Run fund "
    "preview with the same options and check it again."
)
STALE_FUND_REVISION = (
    "this revision does not match the fund as it is now. Nothing was changed. Run fund show and "
    "check it again."
)
STALE_PRIORITY_REVISION = (
    "this revision does not match the priority list as it is now. Nothing was changed. Run funds "
    "and check it again."
)
STALE_ASSIGNMENT_REVISION = (
    "this revision does not match the account's balance and assignments as they are now. "
    "Nothing was changed. Run fund show and check it again."
)


# The model.

@dataclass(frozen=True)
class FundTerms:
    effective_from: str
    shape: str
    amount_cents: int | None = None
    basis_points: int | None = None
    by_month: str | None = None
    month_count: int | None = None
    due_date: str | None = None
    cadence: Cadence | None = None
    anchor: str | None = None


@dataclass(frozen=True)
class Fund:
    fund_id: str
    name: str
    kind: str
    # Oldest first.
    terms: tuple[FundTerms, ...]
    created_at: str | None = None
    undone_at: str | None = None

    @property
    def applies(self) -> bool:
        return self.undone_at is None

    @property
    def state(self) -> str:
        return "undone" if self.undone_at else "active"

    def terms_on(self, on: str) -> FundTerms | None:
        """The terms in effect on a date, or None before the first."""
        starting = [terms for terms in self.terms if terms.effective_from <= on]
        return starting[-1] if starting else None


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    fund_id: str
    account_id: str
    amount_cents: int
    created_at: str
    undone_at: str | None = None

    @property
    def applies(self) -> bool:
        return self.undone_at is None


@dataclass(frozen=True)
class Observation:
    observed_on: str
    balance_cents: int


@dataclass(frozen=True)
class AccountHolding:
    """What an account holds for funds as of a date: its latest observation then, and its active
    assignments."""

    account_id: str
    account_name: str
    account_type: str
    as_of: str
    observation: Observation | None
    # (fund ID, cents) of each active assignment, by fund ID.
    assignments: tuple[tuple[str, int], ...]

    @property
    def assigned_cents(self) -> int:
        return sum(cents for _, cents in self.assignments)

    @property
    def unassigned_cents(self) -> int | None:
        if self.observation is None:
            return None
        return self.observation.balance_cents - self.assigned_cents

    @property
    def over_assigned_cents(self) -> int:
        """How far the assignments exceed the balance observed, never absorbed (point 2). With no
        observation, every assigned cent is unbacked."""
        if self.observation is None:
            return self.assigned_cents
        return max(0, self.assigned_cents - self.observation.balance_cents)

    @property
    def provisional(self) -> bool:
        return self.observation is not None and (
            date.fromisoformat(self.as_of) - date.fromisoformat(self.observation.observed_on)
        ).days > STALE_OBSERVATION_DAYS


def load_funds(conn: sqlite3.Connection) -> tuple[Fund, ...]:
    """Every fund on record with its terms, in the order made."""
    terms_by_fund = {}
    for (fund_id, effective_from, shape, amount, basis_points, by_month, month_count, due_date,
         cadence, first_day, interval_months, anchor) in conn.execute(
            """SELECT fund_id, effective_from, shape, amount_cents, basis_points, by_month,
                      month_count, due_date, cadence, first_day, interval_months, anchor
               FROM fund_terms ORDER BY fund_id, effective_from"""):
        stated_cadence = None if cadence is None else Cadence(
            cadence, first_day, interval_months=interval_months)
        terms_by_fund.setdefault(fund_id, []).append(FundTerms(
            effective_from, shape, amount, basis_points, by_month, month_count, due_date,
            stated_cadence, anchor))
    return tuple(
        Fund(fund_id, name, kind, tuple(terms_by_fund.get(fund_id, ())), created_at, undone_at)
        for fund_id, name, kind, created_at, undone_at in conn.execute(
            """SELECT fund.id, fund.name, fund.kind, fund.created_at, undone.created_at
               FROM fund LEFT JOIN fund_event undone
                   ON undone.fund_id = fund.id AND undone.event = 'undone'
               ORDER BY fund.created_at, fund.id"""))


def load_assignments(conn: sqlite3.Connection) -> tuple[Assignment, ...]:
    """Every assignment on record, in the order made."""
    return tuple(Assignment(*row) for row in conn.execute(
        """SELECT assignment.id, assignment.fund_id, assignment.account_id,
                  assignment.amount_cents, assignment.created_at, undone.created_at
           FROM fund_assignment assignment
           LEFT JOIN fund_assignment_event undone
               ON undone.assignment_id = assignment.id AND undone.event = 'undone'
           ORDER BY assignment.created_at, assignment.id"""))


def latest_observation(conn: sqlite3.Connection, account_id: str,
                       as_of: str) -> Observation | None:
    """The account's latest active balance observation on or before as_of (D-057)."""
    row = conn.execute(
        """SELECT observation.observed_on, observation.balance_cents
           FROM balance_observation observation
           WHERE observation.account_id = ? AND observation.observed_on <= ?
             AND NOT EXISTS (SELECT 1 FROM balance_observation_event undone
                             WHERE undone.balance_observation_id = observation.id
                               AND undone.event = 'undone')
           ORDER BY observation.observed_on DESC LIMIT 1""", (account_id, as_of)).fetchone()
    return None if row is None else Observation(*row)


def account_holding(conn: sqlite3.Connection, account_id: str, as_of: str,
                    assignments=None) -> AccountHolding:
    name, account_type = conn.execute(
        "SELECT display_name, account_type FROM account WHERE id = ?", (account_id,)).fetchone()
    assignments = load_assignments(conn) if assignments is None else assignments
    held = tuple(sorted((assignment.fund_id, assignment.amount_cents)
                        for assignment in assignments
                        if assignment.applies and assignment.account_id == account_id))
    return AccountHolding(account_id, name, account_type, as_of,
                          latest_observation(conn, account_id, as_of), held)


def account_holdings(conn: sqlite3.Connection, as_of: str) -> tuple[AccountHolding, ...]:
    """Every account that can hold a fund's money, and any other holding an assignment, by
    name."""
    assignments = load_assignments(conn)
    assigned = {assignment.account_id for assignment in assignments if assignment.applies}
    accounts = [account_id for account_id, account_type in conn.execute(
        "SELECT id, account_type FROM account ORDER BY display_name")
        if account_type in ASSIGNABLE_ACCOUNT_TYPES or account_id in assigned]
    return tuple(account_holding(conn, account_id, as_of, assignments) for account_id in accounts)


def active_priority(conn: sqlite3.Connection) -> tuple[str, ...]:
    """The fund IDs of the list made last, in order, skipping any fund undone since."""
    row = conn.execute("SELECT list_id FROM fund_priority_event ORDER BY id DESC LIMIT 1"
                       ).fetchone()
    if row is None:
        return ()
    return tuple(fund_id for (fund_id,) in conn.execute(
        """SELECT priority.fund_id FROM fund_priority priority
           WHERE priority.list_id = ? AND NOT EXISTS (
               SELECT 1 FROM fund_event undone
               WHERE undone.fund_id = priority.fund_id AND undone.event = 'undone')
           ORDER BY priority.position""", (row[0],)))


# Required amounts (point 1), pure.

def ceiling_division(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def month_index(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def months_left_including(as_of_month: str, last_month: str) -> int:
    """Months from as_of's month through last_month, both included. Zero or less once it has
    passed."""
    return month_index(last_month) - month_index(as_of_month) + 1


def next_due_date(terms: FundTerms, as_of: str) -> str:
    """A recurring reserve's next due date on or after as_of."""
    start = date.fromisoformat(as_of)
    span = 31 * (terms.cadence.months_between + 1)
    return cadence_dates(terms.cadence, date.fromisoformat(terms.anchor), start,
                         start + timedelta(days=span))[0].isoformat()


@dataclass(frozen=True)
class Standing:
    """A fund's figures as of a date. A goal and a reserve need a planned contribution each
    month. The emergency fund and the tax reserve need an amount held."""

    state: str
    assigned_cents: int
    # A month's planned contribution (goal, reserve), or None.
    planned_contribution_cents: int | None = None
    # The amount to hold (emergency, tax), or None.
    required_held_cents: int | None = None
    # What is still to assign: a target's outstanding amount, or the held amount's shortfall.
    outstanding_cents: int | None = None
    # A target's last month, or a reserve's next due date, and the months left including it.
    due: str | None = None
    months_left: int | None = None


def target_standing(target_cents: int, assigned_cents: int, as_of_month: str, last_month: str,
                    due: str) -> Standing:
    """ceil((target − assigned) ÷ months left, including the last month). With no month left
    and anything outstanding, all of it is needed now and the fund is underfunded."""
    outstanding = max(0, target_cents - assigned_cents)
    months_left = months_left_including(as_of_month, last_month)
    if outstanding == 0:
        return Standing(FUNDED, assigned_cents, 0, None, 0, due, max(0, months_left))
    if months_left < 1:
        return Standing(UNDERFUNDED, assigned_cents, outstanding, None, outstanding, due, 0)
    return Standing(IN_PROGRESS, assigned_cents, ceiling_division(outstanding, months_left),
                    None, outstanding, due, months_left)


def held_standing(required_cents: int, assigned_cents: int) -> Standing:
    shortfall = max(0, required_cents - assigned_cents)
    return Standing(UNDERFUNDED if shortfall else FUNDED, assigned_cents, None, required_cents,
                    shortfall)


@dataclass(frozen=True)
class StandingInputs:
    """What the formulas read beyond the fund and its assignments, all as of one date."""

    as_of: str
    # Baseline income planned in as_of's month (M12), for a percentage goal.
    baseline_income_cents: int = 0
    # Fixed commitments planned in as_of's month, non-monthly ones spread (M12).
    monthly_fixed_commitments_cents: int = 0
    # The tax reserve's accrual through as_of. Payments and releases arrive with M14.2.
    tax_accrued_cents: int = 0
    tax_paid_cents: int = 0
    tax_released_cents: int = 0


def fund_standing(fund: Fund, assigned_cents: int, inputs: StandingInputs) -> Standing:
    """Each kind's required amount by point 1's formula, rounded up (G8)."""
    terms = fund.terms_on(inputs.as_of)
    if terms is None:
        return Standing(NOT_STARTED, assigned_cents)
    as_of_month = inputs.as_of[:7]
    if terms.shape == MONTHLY:
        return Standing(IN_PROGRESS, assigned_cents, terms.amount_cents)
    if terms.shape == PERCENT and fund.kind == GOAL:
        return Standing(IN_PROGRESS, assigned_cents, ceiling_division(
            inputs.baseline_income_cents * terms.basis_points, 10_000))
    if terms.shape == TARGET_BY:
        return target_standing(terms.amount_cents, assigned_cents, as_of_month, terms.by_month,
                               terms.by_month)
    if terms.shape == DUE:
        return target_standing(terms.amount_cents, assigned_cents, as_of_month,
                               terms.due_date[:7], terms.due_date)
    if terms.shape == RECURRING:
        due = next_due_date(terms, inputs.as_of)
        return target_standing(terms.amount_cents, assigned_cents, as_of_month, due[:7], due)
    if terms.shape == MINIMUM:
        return held_standing(terms.amount_cents, assigned_cents)
    if terms.shape == MONTHS:
        return held_standing(terms.month_count * inputs.monthly_fixed_commitments_cents,
                             assigned_cents)
    if terms.shape == PERCENT and fund.kind == TAX:
        return held_standing(max(0, inputs.tax_accrued_cents - inputs.tax_paid_cents
                                 - inputs.tax_released_cents), assigned_cents)
    raise ValueError(f"no formula for a {fund.kind} fund's {terms.shape} terms")


def assigned_to_fund(assignments, fund_id: str) -> int:
    return sum(assignment.amount_cents for assignment in assignments
               if assignment.applies and assignment.fund_id == fund_id)


# Terms as typed.

@dataclass(frozen=True)
class TermsOptions:
    """The terms options as typed, any of which may be absent."""

    monthly: str | None = None
    percent_of_income: str | None = None
    target: str | None = None
    by: str | None = None
    minimum: str | None = None
    months: str | None = None
    due: str | None = None
    cadence: str | None = None
    anchor: str | None = None
    percent: str | None = None

    def given(self) -> frozenset[str]:
        return frozenset(name for name, value in vars(self).items() if value is not None)


# Which options each shape takes, by kind.
SHAPES = {
    GOAL: ((MONTHLY, {"monthly"}), (PERCENT, {"percent_of_income"}),
           (TARGET_BY, {"target", "by"})),
    EMERGENCY: ((MINIMUM, {"minimum"}), (MONTHS, {"months"})),
    RESERVE: ((DUE, {"target", "due"}), (RECURRING, {"target", "cadence"}),
              (RECURRING, {"target", "cadence", "anchor"})),
    TAX: ((PERCENT, {"percent"}),),
}


def parsed_percent(text: str, option: str) -> int:
    basis_points = parse_percent(text)
    if basis_points is None or not 1 <= basis_points <= 10_000:
        raise DecisionRefused(PERCENT_INVALID.format(option=option))
    return basis_points


def parsed_by_month(text: str) -> str:
    if (len(text) != 7 or text[4] != "-" or not (text[:4] + text[5:]).isdigit()
            or not "01" <= text[5:] <= "12" or text[:4] == "0000"):
        raise DecisionRefused(BY_INVALID)
    return text


def first_on_or_after(cadence: Cadence, month: int, effective_from: str) -> str:
    """An annual cadence's first date on or after effective_from, which fixes its anchor."""
    start = date.fromisoformat(effective_from)
    for year in (start.year, start.year + 1):
        anchor = date(year, month, 1)
        found = cadence_dates(cadence, anchor, max(start, anchor),
                              date(year, month, 1) + timedelta(days=31))
        if found:
            return found[0].isoformat()
    raise ValueError("an annual cadence always falls within two years")


def checked_terms(kind: str, options: TermsOptions, effective_from: str) -> FundTerms:
    """The terms typed for a kind, every value checked."""
    given = options.given()
    shape = next((shape for shape, names in SHAPES[kind] if names == given), None)
    if shape is None:
        raise DecisionRefused(TERMS_FOR_KIND[kind])
    if shape == MONTHLY:
        return FundTerms(effective_from, shape, amount_cents=checked_amount(options.monthly,
                                                                           "--monthly"))
    if shape == PERCENT:
        if kind == GOAL:
            return FundTerms(effective_from, shape, basis_points=parsed_percent(
                options.percent_of_income, "--percent-of-income"))
        return FundTerms(effective_from, shape,
                         basis_points=parsed_percent(options.percent, "--percent"))
    if shape == MINIMUM:
        return FundTerms(effective_from, shape,
                         amount_cents=checked_amount(options.minimum, "--minimum"))
    if shape == MONTHS:
        if not options.months.isdigit() or not 1 <= int(options.months) <= 120:
            raise DecisionRefused(MONTHS_INVALID)
        return FundTerms(effective_from, shape, month_count=int(options.months))
    target = checked_amount(options.target, "--target")
    if shape == TARGET_BY:
        by_month = parsed_by_month(options.by)
        if by_month < effective_from[:7]:
            raise DecisionRefused(BY_BEFORE_START)
        return FundTerms(effective_from, shape, amount_cents=target, by_month=by_month)
    if shape == DUE:
        due = parsed_date(options.due, "--due")
        if due < effective_from:
            raise DecisionRefused(DUE_BEFORE_START)
        return FundTerms(effective_from, shape, amount_cents=target, due_date=due)
    stated = checked_cadence(options.cadence)
    cadence = stated.cadence
    if cadence.name == "annual" and options.anchor is None:
        anchor = first_on_or_after(cadence, stated.month, effective_from)
    elif cadence.name == "every_months" and options.anchor is not None:
        anchor = parsed_date(options.anchor, "--anchor")
        if not on_cadence(cadence, date.fromisoformat(anchor)):
            raise DecisionRefused(ANCHOR_OFF_CADENCE)
    else:
        raise DecisionRefused(CADENCE_FOR_RESERVE)
    return FundTerms(effective_from, shape, amount_cents=target, cadence=cadence, anchor=anchor)


def checked_amount(text: str, option: str) -> int:
    return parsed_amount(text, AMOUNT_INVALID.format(option=option), least=1)


# Tokens.

def terms_material(terms: FundTerms) -> dict:
    cadence = terms.cadence
    return {"effective_from": terms.effective_from, "shape": terms.shape,
            "amount_cents": terms.amount_cents, "basis_points": terms.basis_points,
            "by_month": terms.by_month, "month_count": terms.month_count,
            "due_date": terms.due_date,
            "cadence": None if cadence is None else [cadence.name, cadence.first_day,
                                                     cadence.interval_months],
            "anchor": terms.anchor}


def fund_revision(operation: str, fund: Fund) -> str:
    """fu1 covers the operation, the fund's ID once recorded, its name, kind and every terms
    row (D-070 point 7)."""
    material = {"operation": operation, "name": fund.name, "kind": fund.kind,
                "terms": [terms_material(terms) for terms in fund.terms]}
    if fund.fund_id != PROPOSED_FUND_ID:
        material["fund_id"] = fund.fund_id
    return f"fu{FUND_REVISION_VERSION}-{digest(material)}"


def priority_revision(priority: tuple[str, ...]) -> str:
    """fu1 over the priority list as it applies now."""
    return f"fu{FUND_REVISION_VERSION}-" + digest({"operation": PRIORITY,
                                                    "priority": list(priority)})


def assignment_operation(holding: AccountHolding, fund_id: str) -> str:
    """The one operation valid now: a fund holding an assignment on the account can only
    release it, and one holding none can only assign."""
    return UNASSIGN if any(held == fund_id for held, _ in holding.assignments) else ASSIGN


def assignment_revision(holding: AccountHolding, fund_id: str, fund_assignments) -> str:
    """fa1 covers the operation valid now, the fund and account, the account's observation as
    of the date, its active assignments, and the fund's (D-070 point 7). The amount typed is
    checked against the observation under the write lock."""
    observation = holding.observation
    material = {
        "operation": assignment_operation(holding, fund_id),
        "fund_id": fund_id,
        "account_id": holding.account_id,
        "observation": None if observation is None else [observation.observed_on,
                                                         observation.balance_cents],
        "account_assignments": [list(held) for held in holding.assignments],
        "fund_assignments": sorted([assignment.account_id, assignment.amount_cents]
                                   for assignment in fund_assignments
                                   if assignment.applies and assignment.fund_id == fund_id),
    }
    return f"fa{ASSIGNMENT_REVISION_VERSION}-{digest(material)}"


# Writes.

@dataclass(frozen=True)
class FundRequest:
    name: str
    kind: str
    options: TermsOptions
    effective_from: str | None = None


def find_fund(funds, fund_id: str) -> Fund:
    fund = next((fund for fund in funds if fund.fund_id == fund_id), None)
    if fund is None:
        raise DecisionRefused(FUND_NOT_FOUND)
    return fund


def find_active_fund(funds, fund_id: str) -> Fund:
    fund = find_fund(funds, fund_id)
    if not fund.applies:
        raise DecisionRefused(FUND_NOT_ACTIVE)
    return fund


def checked_fund(conn: sqlite3.Connection, request: FundRequest, as_of: str) -> Fund:
    """A fund as typed, refused for anything it gets wrong. Nothing is written."""
    as_of = parsed_date(as_of, "--as-of")
    if not request.name.strip():
        raise DecisionRefused(NAME_BLANK)
    if request.kind not in KINDS:
        raise DecisionRefused(KIND_UNKNOWN)
    effective_from = (as_of if request.effective_from is None
                      else parsed_date(request.effective_from, "--effective-from"))
    refuse_if_closed_month(effective_from, as_of, CLOSED_MONTH)
    terms = checked_terms(request.kind, request.options, effective_from)
    for other in load_funds(conn):
        if not other.applies:
            continue
        if other.name == request.name:
            raise DecisionRefused(NAME_TAKEN.format(fund=other.fund_id))
        if other.kind == request.kind and request.kind in ONE_ACTIVE_KINDS:
            raise DecisionRefused(ONE_ACTIVE.format(fund=other.fund_id, kind=request.kind))
    return Fund(PROPOSED_FUND_ID, request.name, request.kind, (terms,))


def add_fund(conn: sqlite3.Connection, request: FundRequest, as_of: str, revision: str) -> str:
    """Record a fund whose preview is still current, or refuse and change nothing."""
    return in_one_write(conn, lambda: _add_fund(conn, request, as_of, revision))


def _add_fund(conn, request, as_of, revision) -> str:
    fund = checked_fund(conn, request, as_of)
    refuse_unless_revision(fund_revision(ADD, fund), revision, STALE_FUND_PREVIEW)
    fund_id = str(uuid.uuid4())
    conn.execute("INSERT INTO fund (id, name, kind) VALUES (?, ?, ?)",
                 (fund_id, fund.name, fund.kind))
    insert_terms(conn, fund_id, fund.terms[0])
    conn.execute("INSERT INTO fund_event (fund_id, event) VALUES (?, 'made')", (fund_id,))
    return fund_id


def insert_terms(conn: sqlite3.Connection, fund_id: str, terms: FundTerms) -> None:
    cadence = terms.cadence
    conn.execute(
        """INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents, basis_points,
                                   by_month, month_count, due_date, cadence, first_day,
                                   interval_months, anchor)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fund_id, terms.effective_from, terms.shape, terms.amount_cents, terms.basis_points,
         terms.by_month, terms.month_count, terms.due_date, cadence and cadence.name,
         cadence and cadence.first_day, cadence and cadence.interval_months, terms.anchor))


def change_terms(conn: sqlite3.Connection, fund_id: str, options: TermsOptions,
                 effective_from: str, as_of: str, revision: str) -> FundTerms:
    """Add a terms row taking over from effective_from, later than every row the fund has, in
    no closed month. Every value of the kind's terms is typed again."""
    return in_one_write(conn, lambda: _change_terms(conn, fund_id, options, effective_from,
                                                    as_of, revision))


def _change_terms(conn, fund_id, options, effective_from, as_of, revision) -> FundTerms:
    fund = find_active_fund(load_funds(conn), fund_id)
    effective_from = parsed_date(effective_from, "--effective-from")
    as_of = parsed_date(as_of, "--as-of")
    refuse_if_closed_month(effective_from, as_of, CLOSED_MONTH)
    latest = fund.terms[-1].effective_from
    if effective_from <= latest:
        raise DecisionRefused(TERMS_NOT_LATER.format(latest=latest))
    terms = checked_terms(fund.kind, options, effective_from)
    refuse_unless_revision(fund_revision(TERMS, fund), revision, STALE_FUND_REVISION)
    insert_terms(conn, fund.fund_id, terms)
    return terms


def undo_fund(conn: sqlite3.Connection, fund_id: str, revision: str) -> Fund:
    """Stop a fund applying, keeping it on record. A fund still holding money on an account is
    refused, so no assignment is left to a fund that no longer applies."""
    return in_one_write(conn, lambda: _undo_fund(conn, fund_id, revision))


def _undo_fund(conn, fund_id, revision) -> Fund:
    fund = find_active_fund(load_funds(conn), fund_id)
    held = sorted({name for (name,) in conn.execute(
        """SELECT account.display_name FROM fund_assignment assignment
           JOIN account ON account.id = assignment.account_id
           WHERE assignment.fund_id = ? AND NOT EXISTS (
               SELECT 1 FROM fund_assignment_event undone
               WHERE undone.assignment_id = assignment.id AND undone.event = 'undone')""",
        (fund_id,))})
    if held:
        raise DecisionRefused(UNDO_ASSIGNED.format(accounts=", ".join(held)))
    refuse_unless_revision(fund_revision(UNDO, fund), revision, STALE_FUND_REVISION)
    conn.execute("INSERT INTO fund_event (fund_id, event) VALUES (?, 'undone')", (fund_id,))
    return fund


def set_priority(conn: sqlite3.Connection, fund_ids, revision: str) -> str:
    """Replace the priority list, or refuse and change nothing. An empty list clears it."""
    return in_one_write(conn, lambda: _set_priority(conn, tuple(fund_ids), revision))


def _set_priority(conn, fund_ids, revision) -> str:
    funds = load_funds(conn)
    for position, fund_id in enumerate(fund_ids):
        fund = find_active_fund(funds, fund_id)
        if fund.kind not in PRIORITY_KINDS:
            raise DecisionRefused(PRIORITY_KIND.format(fund=fund_id))
        if fund_id in fund_ids[:position]:
            raise DecisionRefused(PRIORITY_REPEATED.format(fund=fund_id))
    refuse_unless_revision(priority_revision(active_priority(conn)), revision,
                           STALE_PRIORITY_REVISION)
    list_id = str(uuid.uuid4())
    conn.execute("INSERT INTO fund_priority_event (list_id, event) VALUES (?, 'made')",
                 (list_id,))
    conn.executemany("INSERT INTO fund_priority (list_id, position, fund_id) VALUES (?, ?, ?)",
                     [(list_id, position, fund_id)
                      for position, fund_id in enumerate(fund_ids, start=1)])
    return list_id


def refuse_unless_assignable(holding: AccountHolding) -> None:
    if holding.account_type not in ASSIGNABLE_ACCOUNT_TYPES:
        raise DecisionRefused(ACCOUNT_NOT_ASSIGNABLE.format(
            account_type=holding.account_type.replace("_", " ")))


def assign(conn: sqlite3.Connection, fund_id: str, account_id: str, amount: str, as_of: str,
           revision: str, rules: MatchingRules = DEFAULT_RULES) -> str:
    """Assign part of an account's observed balance to a fund, never beyond it (point 2's
    guard), or refuse and change nothing."""
    return in_one_write(conn, lambda: _assign(conn, fund_id, account_id, amount, as_of, revision,
                                              rules))


def _assign(conn, fund_id, account_id, amount, as_of, revision, rules) -> str:
    find_active_fund(load_funds(conn), fund_id)
    as_of = parsed_date(as_of, "--as-of")
    assignments = load_assignments(conn)
    holding = account_holding(conn, account_id, as_of, assignments)
    refuse_unless_assignable(holding)
    refuse_unless_current(conn, account_id, rules)
    cents = checked_amount(amount, "--amount")
    if assignment_operation(holding, fund_id) != ASSIGN:
        raise DecisionRefused(ALREADY_ASSIGNED)
    if holding.observation is None:
        raise DecisionRefused(NO_OBSERVATION.format(as_of=as_of))
    refuse_unless_revision(assignment_revision(holding, fund_id, assignments), revision,
                           STALE_ASSIGNMENT_REVISION)
    total = holding.assigned_cents + cents
    if total > holding.observation.balance_cents:
        raise DecisionRefused(BEYOND_OBSERVATION.format(
            amount=format_cents(cents), total=format_cents(total),
            balance=format_cents(holding.observation.balance_cents),
            observed_on=holding.observation.observed_on,
            unassigned=format_cents(max(0, holding.unassigned_cents))))
    assignment_id = str(uuid.uuid4())
    conn.execute("INSERT INTO fund_assignment (id, fund_id, account_id, amount_cents) "
                 "VALUES (?, ?, ?, ?)", (assignment_id, fund_id, account_id, cents))
    insert_assignment_event(conn, assignment_id, "made")
    return assignment_id


def insert_assignment_event(conn: sqlite3.Connection, assignment_id: str, event: str) -> None:
    conn.execute("INSERT INTO fund_assignment_event (assignment_id, event) VALUES (?, ?)",
                 (assignment_id, event))


def unassign(conn: sqlite3.Connection, fund_id: str, account_id: str, as_of: str, revision: str,
             rules: MatchingRules = DEFAULT_RULES) -> Assignment:
    """Release a fund's assignment on an account, keeping it on record."""
    return in_one_write(conn, lambda: _unassign(conn, fund_id, account_id, as_of, revision,
                                                rules))


def _unassign(conn, fund_id, account_id, as_of, revision, rules) -> Assignment:
    find_fund(load_funds(conn), fund_id)
    as_of = parsed_date(as_of, "--as-of")
    assignments = load_assignments(conn)
    holding = account_holding(conn, account_id, as_of, assignments)
    refuse_unless_current(conn, account_id, rules)
    active = next((assignment for assignment in assignments if assignment.applies
                   and assignment.fund_id == fund_id and assignment.account_id == account_id),
                  None)
    if active is None:
        raise DecisionRefused(NOT_ASSIGNED)
    refuse_unless_revision(assignment_revision(holding, fund_id, assignments), revision,
                           STALE_ASSIGNMENT_REVISION)
    insert_assignment_event(conn, active.assignment_id, "undone")
    return active
