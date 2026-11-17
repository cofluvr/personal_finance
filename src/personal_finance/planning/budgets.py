"""Budget plans stated by a person (D-069 points 2 and 6): from a month on, the household's
discretionary allowance, optionally split among members by exact amounts and capped by category,
until a later active plan takes over. Plans chain by D-048's rule (G4), and a closed month's plan
is never rewritten without --correct-closed-month (G7). Each write runs under one write lock with
its bp1 token, and changes no ledger table (G1).

The plan in effect for a month is the applying plan with the latest effective_from no later than
it. No two applying plans share a month, so the choice is never ambiguous: a second plan for a
month supersedes the first.
"""

import sqlite3
import uuid
from dataclasses import dataclass, replace

from personal_finance.money import format_cents
from personal_finance.planning.entries import (
    ChainRefusals,
    find_newest,
    in_one_write,
    parsed_amount,
    refuse_unless_revision,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reports.category_rule_evidence import digest

# Bump whenever the material below changes, so an old token can never appear current.
BUDGET_REVISION_VERSION = 1

SET = "set"
SUPERSEDE = "supersede"
UNDO = "undo"

# The ID a plan not yet recorded is known by in a preview's material.
PROPOSED_PLAN_ID = "proposed"

MONTH_INVALID = "--from must be a month written YYYY-MM. Nothing was changed."
ALLOWANCE_INVALID = (
    "--allowance must be an amount of zero or more, such as 1500.00. Nothing was changed."
)
PART_INVALID = (
    "{option} takes NAME=AMOUNT, an amount of zero or more, each name once. Nothing was changed."
)
MEMBER_UNKNOWN = "household member {name} not found. Run household members. Nothing was changed."
CATEGORY_UNKNOWN = "category {name} not found. Run category list. Nothing was changed."
MEMBERS_MISSING = (
    "a plan that divides the allowance gives every household member an amount, and {names} "
    "has none. Give 0 for a member with no part. Nothing was changed."
)
MEMBERS_NOT_SUMMING = (
    "the members' amounts add to {total}, not the allowance {allowance}: they must add to it "
    "exactly. Nothing was changed."
)
CLOSED_MONTH = (
    "this changes the plan of {month}, a month before today's, which is closed. Give "
    "--correct-closed-month to correct it, which every later report of that month discloses. "
    "Nothing was changed."
)
UNDO_CLOSED_MONTH = (
    "undoing this plan changes the plan of {month}, a month before today's, which is closed. "
    "Supersede it with --correct-closed-month instead, which every later report of that month "
    "discloses. Nothing was changed."
)
MONTH_TAKEN = (
    "budget plan {plan} applies from {month} already. Supersede it with --supersedes. Nothing "
    "was changed."
)
UNDO_MONTH_TAKEN = (
    "undoing this plan would make {restored}, which it superseded, apply from {month} beside "
    "{plan}. Undo or supersede {plan} first. Nothing was changed."
)
SUPERSEDES_PAIR = (
    "--supersedes and --supersedes-revision are given together. Nothing was changed."
)
STALE_SUPERSEDED_REVISION = (
    "--supersedes-revision does not match the plan it supersedes as it is now. Nothing was "
    "changed. Run budget show and check it again."
)
STALE_BUDGET_PREVIEW = (
    "this revision does not match the plan as previewed now. Nothing was changed. Run budget "
    "preview with the same options and check it again."
)
STALE_BUDGET_REVISION = (
    "this revision does not match the plan as it is now. Nothing was changed. Run budget show "
    "and check it again."
)
PLAN_REFUSALS = ChainRefusals(
    not_found="budget plan not found. Run budgets. Nothing was changed.",
    not_active="this budget plan has already been undone. Nothing was changed.",
    superseded=("this budget plan is superseded by {newest}, the newest of its chain, which is "
                "the one to change or undo. Nothing was changed."),
)


@dataclass(frozen=True)
class BudgetPlan:
    plan_id: str
    effective_from: str
    allowance_cents: int
    # (name, cents), by name.
    member_parts: tuple[tuple[str, int], ...] = ()
    category_allowances: tuple[tuple[str, int], ...] = ()
    supersedes_id: str | None = None
    corrected_closed_month: bool = False
    created_at: str | None = None
    undone_at: str | None = None
    superseded_by: str | None = None

    @property
    def entry_id(self) -> str:
        return self.plan_id

    @property
    def applies(self) -> bool:
        return self.undone_at is None and self.superseded_by is None

    @property
    def state(self) -> str:
        if self.undone_at:
            return "undone"
        return "superseded" if self.superseded_by else "active"

    @property
    def category_excess_cents(self) -> int:
        """How far the category allowances exceed the household's, shown as a warning, since
        categories overlap members (point 2)."""
        return max(0, sum(cents for _, cents in self.category_allowances) - self.allowance_cents)


@dataclass(frozen=True)
class PlanRequest:
    """A plan as typed on the command line."""

    effective_from: str
    allowance: str
    member_parts: tuple[str, ...] = ()
    category_allowances: tuple[str, ...] = ()
    supersedes: str | None = None
    supersedes_revision: str | None = None
    correct_closed_month: bool = False


@dataclass(frozen=True)
class CheckedPlan:
    """A plan as typed, every rule checked, with what it changes. Nothing is written."""

    plan: BudgetPlan
    member_ids: dict
    category_ids: dict
    superseded: BudgetPlan | None
    changed_months: tuple[tuple[str, str | None], ...]
    revision: str


def load_plans(conn: sqlite3.Connection) -> tuple[BudgetPlan, ...]:
    """Every plan on record, in the order made."""
    member_parts, category_allowances = {}, {}
    for plan_id, name, cents in conn.execute(
        """SELECT part.plan_id, member.name, part.amount_cents FROM budget_plan_member_part part
           JOIN household_member member ON member.id = part.member_id ORDER BY member.name"""):
        member_parts.setdefault(plan_id, []).append((name, cents))
    for plan_id, name, cents in conn.execute(
        """SELECT part.plan_id, category.name, part.amount_cents FROM budget_plan_category part
           JOIN category ON category.id = part.category_id ORDER BY category.name"""):
        category_allowances.setdefault(plan_id, []).append((name, cents))
    rows = conn.execute(
        """SELECT plan.id, plan.effective_from, plan.allowance_cents, plan.supersedes_id,
                  plan.corrected_closed_month, plan.created_at, undone.created_at
           FROM budget_plan plan
           LEFT JOIN budget_plan_event undone
               ON undone.plan_id = plan.id AND undone.event = 'undone'
           ORDER BY plan.created_at, plan.id""").fetchall()
    # Undo steps back one link: an undone plan no longer supersedes the one before it.
    superseded_by = {row[3]: row[0] for row in rows if row[3] and row[6] is None}
    return tuple(
        BudgetPlan(plan_id, effective_from, allowance, tuple(member_parts.get(plan_id, ())),
                   tuple(category_allowances.get(plan_id, ())), supersedes_id, bool(corrected),
                   created_at, undone_at, superseded_by.get(plan_id))
        for (plan_id, effective_from, allowance, supersedes_id, corrected, created_at,
             undone_at) in rows)


def plan_in_effect(plans, month: str) -> BudgetPlan | None:
    """The applying plan with the latest effective_from no later than month (point 2, BA4)."""
    candidates = [plan for plan in plans if plan.applies and plan.effective_from <= month]
    return max(candidates, key=lambda plan: plan.effective_from, default=None)


def changed_months(plans_before, plans_after) -> tuple[tuple[str, str | None], ...]:
    """The months whose plan in effect a change moves, as (first, end) ranges, end exclusive
    and None for every month on. A plan in effect changes only at a plan's effective_from."""
    boundaries = sorted({plan.effective_from for plan in (*plans_before, *plans_after)
                         if plan.applies})
    ranges = []
    for index, month in enumerate(boundaries):
        before, after = plan_in_effect(plans_before, month), plan_in_effect(plans_after, month)
        if (before and before.plan_id) == (after and after.plan_id):
            continue
        end = boundaries[index + 1] if index + 1 < len(boundaries) else None
        if ranges and ranges[-1][1] == month:
            ranges[-1] = (ranges[-1][0], end)
        else:
            ranges.append((month, end))
    return tuple(ranges)


def plan_material(plan: BudgetPlan) -> dict:
    return {"effective_from": plan.effective_from, "allowance_cents": plan.allowance_cents,
            "member_parts": [list(part) for part in plan.member_parts],
            "category_allowances": [list(part) for part in plan.category_allowances],
            "corrected_closed_month": plan.corrected_closed_month}


def plan_revision(operation: str, plan: BudgetPlan, months, superseded_revision=None) -> str:
    """bp1 covers the operation, the plan's full content (and its ID once recorded), the token of
    the plan it supersedes, and which months the change affects (D-069 point 6)."""
    material = {"operation": operation, "plan": plan_material(plan),
                "months": [list(months_range) for months_range in months]}
    if plan.plan_id != PROPOSED_PLAN_ID:
        material["plan_id"] = plan.plan_id
    if superseded_revision is not None:
        material["supersedes"] = superseded_revision
    return f"bp{BUDGET_REVISION_VERSION}-{digest(material)}"


def plans_after_undo(plans, plan: BudgetPlan) -> tuple[BudgetPlan, ...]:
    """The plans as they read once this one is undone: the plan it superseded applies again."""
    return tuple(replace(other, undone_at="undone") if other.plan_id == plan.plan_id
                 else replace(other, superseded_by=None) if other.plan_id == plan.supersedes_id
                 else other for other in plans)


def plans_after_supersede(plans, plan: BudgetPlan) -> tuple[BudgetPlan, ...]:
    """The plans as they read once this one is superseded, by a plan not counted here."""
    return tuple(replace(other, superseded_by=PROPOSED_PLAN_ID)
                 if other.plan_id == plan.plan_id else other for other in plans)


def supersede_revision(plans, plan: BudgetPlan) -> str:
    """The token budget show gives a plan for superseding it: the months it holds now."""
    return plan_revision(SUPERSEDE, plan, changed_months(plans, plans_after_supersede(plans, plan)))


def undo_revision(plans, plan: BudgetPlan) -> str:
    return plan_revision(UNDO, plan, changed_months(plans, plans_after_undo(plans, plan)))


def parsed_month(text: str) -> str:
    if (len(text) != 7 or text[4] != "-" or not (text[:4] + text[5:]).isdigit()
            or not "01" <= text[5:] <= "12" or text[:4] == "0000"):
        raise DecisionRefused(MONTH_INVALID)
    return text


def parsed_parts(conn, texts, option, table, unknown) -> tuple[tuple[str, int, int], ...]:
    """NAME=AMOUNT pairs as (name, ID, cents), by name, each name once."""
    found = {}
    for text in texts:
        name, separator, amount = text.rpartition("=")
        if not separator or not name or name in found:
            raise DecisionRefused(PART_INVALID.format(option=option))
        cents = parsed_amount(amount, PART_INVALID.format(option=option), least=0)
        row = conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise DecisionRefused(unknown.format(name=name))
        found[name] = (name, row[0], cents)
    return tuple(found[name] for name in sorted(found))


def refuse_unless_every_member(conn, member_parts) -> None:
    named = {name for name, _, _ in member_parts}
    missing = [name for (name,) in conn.execute(
        "SELECT name FROM household_member ORDER BY id") if name not in named]
    if member_parts and missing:
        raise DecisionRefused(MEMBERS_MISSING.format(names=", ".join(missing)))


def refuse_if_month_taken(plans_after) -> None:
    by_month = {}
    for plan in plans_after:
        if plan.applies and plan.effective_from in by_month:
            raise DecisionRefused(MONTH_TAKEN.format(plan=by_month[plan.effective_from].plan_id,
                                                     month=plan.effective_from))
        if plan.applies:
            by_month[plan.effective_from] = plan


def checked_plan(conn: sqlite3.Connection, request: PlanRequest, as_of_month: str) -> CheckedPlan:
    """A plan as typed, refused for anything it gets wrong. Nothing is written."""
    plans = load_plans(conn)
    if (request.supersedes is None) != (request.supersedes_revision is None):
        raise DecisionRefused(SUPERSEDES_PAIR)
    superseded = superseded_revision = None
    if request.supersedes is not None:
        superseded = find_newest(plans, request.supersedes, PLAN_REFUSALS)
        superseded_revision = supersede_revision(plans, superseded)
        refuse_unless_revision(superseded_revision, request.supersedes_revision,
                               STALE_SUPERSEDED_REVISION)
    effective_from = parsed_month(request.effective_from)
    allowance = parsed_amount(request.allowance, ALLOWANCE_INVALID, least=0)
    member_parts = parsed_parts(conn, request.member_parts, "--member", "household_member",
                                MEMBER_UNKNOWN)
    category_allowances = parsed_parts(conn, request.category_allowances, "--category",
                                       "category", CATEGORY_UNKNOWN)
    refuse_unless_every_member(conn, member_parts)
    members_total = sum(cents for _, _, cents in member_parts)
    if member_parts and members_total != allowance:
        raise DecisionRefused(MEMBERS_NOT_SUMMING.format(total=format_cents(members_total),
                                                         allowance=format_cents(allowance)))
    proposed = BudgetPlan(PROPOSED_PLAN_ID, effective_from, allowance,
                          tuple((name, cents) for name, _, cents in member_parts),
                          tuple((name, cents) for name, _, cents in category_allowances),
                          superseded and superseded.plan_id)
    plans_after = (*(plans if superseded is None else plans_after_supersede(plans, superseded)),
                   proposed)
    refuse_if_month_taken(plans_after)
    months = changed_months(plans, plans_after)
    corrects_closed_month = bool(months) and months[0][0] < as_of_month
    if corrects_closed_month and not request.correct_closed_month:
        raise DecisionRefused(CLOSED_MONTH.format(month=months[0][0]))
    proposed = replace(proposed, corrected_closed_month=corrects_closed_month)
    revision = plan_revision(SET, proposed, months, superseded_revision)
    return CheckedPlan(proposed, {name: member_id for name, member_id, _ in member_parts},
                       {name: category_id for name, category_id, _ in category_allowances},
                       superseded, months, revision)


def set_plan(conn: sqlite3.Connection, request: PlanRequest, as_of_month: str,
             revision: str) -> str:
    """Record a plan whose preview is still current, or refuse and change nothing."""
    return in_one_write(conn, lambda: _set_plan(conn, request, as_of_month, revision))


def _set_plan(conn, request, as_of_month, revision) -> str:
    checked = checked_plan(conn, request, as_of_month)
    refuse_unless_revision(checked.revision, revision, STALE_BUDGET_PREVIEW)
    plan_id = str(uuid.uuid4())
    plan = checked.plan
    conn.execute(
        """INSERT INTO budget_plan (id, effective_from, allowance_cents, supersedes_id,
                                    corrected_closed_month)
           VALUES (?, ?, ?, ?, ?)""",
        (plan_id, plan.effective_from, plan.allowance_cents, plan.supersedes_id,
         int(plan.corrected_closed_month)))
    insert_parts(conn, plan_id, checked)
    conn.execute("INSERT INTO budget_plan_event (plan_id, event) VALUES (?, 'made')", (plan_id,))
    return plan_id


def insert_parts(conn, plan_id: str, checked: CheckedPlan) -> None:
    conn.executemany(
        "INSERT INTO budget_plan_member_part (plan_id, member_id, amount_cents) VALUES (?, ?, ?)",
        [(plan_id, checked.member_ids[name], cents) for name, cents in checked.plan.member_parts])
    conn.executemany(
        "INSERT INTO budget_plan_category (plan_id, category_id, amount_cents) VALUES (?, ?, ?)",
        [(plan_id, checked.category_ids[name], cents)
         for name, cents in checked.plan.category_allowances])


def undo_plan(conn: sqlite3.Connection, plan_id: str, as_of_month: str,
              revision: str) -> BudgetPlan:
    """Stop the newest plan of a chain applying, keeping it on record. The one it superseded, if
    any, applies again (G4). An undo that would change a closed month is refused (G7)."""
    return in_one_write(conn, lambda: _undo_plan(conn, plan_id, as_of_month, revision))


def _undo_plan(conn, plan_id, as_of_month, revision) -> BudgetPlan:
    plans = load_plans(conn)
    plan = find_newest(plans, plan_id, PLAN_REFUSALS)
    plans_after = plans_after_undo(plans, plan)
    restored = next((other for other in plans_after if other.plan_id == plan.supersedes_id),
                    None)
    if restored is not None:
        clash = next((other for other in plans_after if other.applies
                      and other.plan_id != restored.plan_id
                      and other.effective_from == restored.effective_from), None)
        if clash is not None:
            raise DecisionRefused(UNDO_MONTH_TAKEN.format(
                restored=restored.plan_id, month=restored.effective_from, plan=clash.plan_id))
    months = changed_months(plans, plans_after)
    if months and months[0][0] < as_of_month:
        raise DecisionRefused(UNDO_CLOSED_MONTH.format(month=months[0][0]))
    refuse_unless_revision(undo_revision(plans, plan), revision, STALE_BUDGET_REVISION)
    conn.execute("INSERT INTO budget_plan_event (plan_id, event) VALUES (?, 'undone')",
                 (plan_id,))
    return plan
