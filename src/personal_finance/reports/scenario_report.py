"""Scenarios as shown: the list, one scenario with its inputs and tokens, and the comparison of
its projection with the baseline's (D-074 points 3 to 5). The terminal and the pages render the
same lines (point 5). Read-only: the plan is read once, and the one pure projection runs for both
sides, so nothing is stored (PRD §15).
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from personal_finance.money import format_cents
from personal_finance.planning.coverage import load_coverages
from personal_finance.planning.fund_restorations import load_restorations
from personal_finance.planning.funds import (
    EMERGENCY,
    GOAL,
    RESERVE,
    TAX,
    account_holdings,
    active_priority,
    assigned_to_fund,
    load_assignments,
    load_funds,
    load_portions,
    reductions_as_of,
)
from personal_finance.planning.budgets import load_plans
from personal_finance.planning.income_effects import SALARY, applying_sources
from personal_finance.planning.liquidity import liquid_account_ids
from personal_finance.planning.loans import format_rate, load_loan_terms
from personal_finance.planning.net_worth import COUNTED
from personal_finance.planning.obligation_effects import FIXED, applying_obligations
from personal_finance.planning.promotions import (
    FUND_TERMS_ROW,
    OBLIGATION_TERMS_ROW,
    SOURCE_TERMS_ROW,
    active_promotion,
    planned_for,
    promotion_revision,
    promotion_undo_revision,
)
from personal_finance.planning.projection import (
    DEFAULT_MONTHS,
    Plan,
    ProjectedFund,
    ProjectedLoan,
    Projection,
    Stream,
    StreamTerms,
    project,
)
from personal_finance.planning.scenarios import (
    ACTIVE,
    ADD_INPUT,
    TARGET_CHANGED,
    UNDO_INPUT,
    UNDO_SCENARIO,
    Scenario,
    input_words,
    scenario_revision,
)
from personal_finance.planning.schedules import cadence_spec
from personal_finance.planning.settings import checking_buffer_cents
from personal_finance.reports.fund_standing import monthly_fixed_commitments_cents
from personal_finance.reports.loan_report import owed_as_of
from personal_finance.reports.net_worth_report import net_worth
from personal_finance.reports.report_text import ReportLines, shown
from personal_finance.reports.safe_to_spend import safe_to_spend

PROJECTION_LABEL = "projection, not a forecast"


# The plan, read once.

def stream_terms(rows, amount_of) -> tuple[StreamTerms, ...]:
    return tuple(StreamTerms(terms.effective_from, terms.cadence, terms.anchor, amount_of(terms))
                 for terms in rows)


def spec_on(rows, on: str) -> str:
    starting = [terms for terms in rows if terms.effective_from <= on] or [rows[0]]
    return cadence_spec(starting[-1].cadence, starting[-1].anchor)


def plan_for(conn: sqlite3.Connection, as_of: date) -> Plan:
    """The active plan as of a date, as plain values. The household timezone must be set: the
    starting balance is M16's estimate (G7)."""
    text = as_of.isoformat()
    missing = []
    spend = safe_to_spend(conn, as_of)
    liquid = set(liquid_account_ids(conn))
    if not spend.accounts:
        missing.append("no liquidity account is designated: the starting balance is 0")
    for account in spend.accounts:
        if account.observed_on is None:
            missing.append(f"liquidity account {shown(account.name)} has no balance observed")
    held_on_liquid = sum(holding.assigned_cents for holding in account_holdings(conn, text)
                         if holding.account_id in liquid)
    buffer = checking_buffer_cents(conn)
    if buffer is None:
        missing.append("no checking buffer is set: the protected amount is 0")
    worth = net_worth(conn, text)
    worth_cents = (worth.total_cents
                   if any(valuation.how == COUNTED for valuation in worth.valued) else None)
    if worth_cents is None:
        missing.append("no account is valued: net worth is not projected")

    salary, side = [], []
    for source in applying_sources(conn):
        stream = Stream(source.source_id, source.definition.name,
                        stream_terms(source.terms, lambda terms: terms.amount_cents),
                        source.definition.tax_eligible, spec_on(source.terms, text))
        (salary if source.definition.kind == SALARY else side).append(stream)
    coverages = load_coverages(conn)
    reserve_chains = {coverage.chain_id for coverage in coverages if coverage.fund_id}
    covered_loans = {coverage.loan_account_id for coverage in coverages
                     if coverage.loan_account_id}
    fixed, discretionary = [], []
    for obligation in applying_obligations(conn):
        if obligation.chain_id in reserve_chains:
            continue
        stream = Stream(obligation.obligation_id, obligation.definition.name,
                        stream_terms(obligation.terms, lambda terms: terms.planned_cents
                                     if terms.obligation_class == FIXED else 0),
                        False, spec_on(obligation.terms, text))
        latest = obligation.terms[-1]
        (fixed if latest.obligation_class == FIXED else discretionary).append(stream)

    budget = tuple(sorted((plan.effective_from, plan.allowance_cents)
                          for plan in load_plans(conn) if plan.applies))
    spent = 0
    if spend.budget is not None and spend.budget.pace is not None:
        spent = spend.budget.pace.actual_cents

    assignments = load_assignments(conn)
    reduced = reductions_as_of(load_portions(conn, assignments), text)
    funds = [fund for fund in load_funds(conn) if fund.applies]
    priority = list(active_priority(conn))
    order = sorted((fund for fund in funds if fund.kind in (GOAL, EMERGENCY, RESERVE)),
                   key=lambda fund: (fund.fund_id not in priority,
                                     priority.index(fund.fund_id) if fund.fund_id in priority
                                     else 0, fund.name, fund.fund_id))

    def projected(fund) -> ProjectedFund:
        restorations = tuple((each.effective_from, each.monthly_cents)
                             for each in load_restorations(conn, fund.fund_id))
        return ProjectedFund(fund.fund_id, fund.name, fund.kind, fund.terms,
                             assigned_to_fund(assignments, fund.fund_id, reduced), restorations)

    tax = next((projected(fund) for fund in funds if fund.kind == TAX), None)
    loans = []
    for terms in load_loan_terms(conn).values():
        observed = owed_as_of(conn, terms.account_id, text)
        if observed is None:
            missing.append(f"loan {shown(terms.account_name)} has no balance observed: not "
                           "projected")
            continue
        loans.append(ProjectedLoan(terms, observed[1], observed[0],
                                   terms.account_id not in covered_loans))
    return Plan(text, spend.liquid_cents if spend.accounts else None, held_on_liquid,
                buffer or 0, worth_cents, tuple(salary), tuple(fixed), tuple(side),
                tuple(discretionary), budget, spent, tuple(projected(fund) for fund in order),
                tax, monthly_fixed_commitments_cents(conn, text[:7]), tuple(loans),
                tuple(missing))


@dataclass(frozen=True)
class Comparison:
    scenario: Scenario
    months: int
    baseline: Projection
    projected: Projection


def compare(conn: sqlite3.Connection, scenario: Scenario, as_of: date,
            months: int = DEFAULT_MONTHS) -> Comparison:
    """The baseline and the scenario from one plan, read once."""
    plan = plan_for(conn, as_of)
    counted = tuple(input_ for input_ in scenario.inputs if scenario.counted(input_))
    return Comparison(scenario, months, project(plan, (), as_of, months),
                      project(plan, counted, as_of, months))


# Lines.

def amount(cents: int | None) -> str:
    return "missing" if cents is None else format_cents(cents)


def difference(baseline: int | None, scenario: int | None) -> str:
    if baseline is None or scenario is None:
        return "missing"
    change = scenario - baseline
    return ("+" if change > 0 else "") + format_cents(change)


def input_state_words(scenario: Scenario, input_) -> str:
    if input_.state == TARGET_CHANGED:
        return "target_changed, left out: the entry it replaces no longer applies"
    if input_.state != ACTIVE:
        return input_.state
    if scenario.counted(input_):
        return "counted"
    return "left out: uncertain"


def scenarios_lines(scenarios) -> ReportLines:
    out = ReportLines()
    out.add("Scenarios")
    if not scenarios:
        out.add("No scenarios. Add one with scenario add.")
    for scenario in scenarios:
        active = [input_ for input_ in scenario.inputs if not input_.undone_at]
        counted = [input_ for input_ in active if scenario.counted(input_)]
        out.add(f"Scenario {scenario.scenario_id}: {shown(scenario.name)}, {scenario.state}, "
                f"{len(counted)} of {len(active)} inputs counted, uncertain inputs "
                f"{'included' if scenario.include_uncertain else 'left out'}")
    return out


MAKES = {SOURCE_TERMS_ROW: "a new terms row on income source {entry}",
         OBLIGATION_TERMS_ROW: "a new terms row on obligation {entry}",
         FUND_TERMS_ROW: "a new terms row on reserve {entry}",
         "income_source": "a new income source", "recurring_obligation": "a new obligation",
         "fund": "a new reserve"}


def promotion_lines(conn: sqlite3.Connection, scenario: Scenario, out: ReportLines) -> None:
    """What promoting would make of each input, or why not, and the sp1 tokens (point 6)."""
    promotion = active_promotion(conn, scenario.scenario_id)
    out.add("Promotion:")
    if promotion is not None:
        out.add(f"  Promoted as {promotion.promotion_id}, making:")
        for kind, entry_id, row_id, input_id in promotion.entries:
            made = f"{kind} {entry_id}" if entry_id else f"{kind} row {row_id}"
            out.add(f"    {made}, from input {input_id}")
        out.add(f"Promotion undo revision: {promotion_undo_revision(scenario, promotion)}")
        return
    planned = planned_for(scenario)
    replaced = {input_.input_id: input_.replaces_id for input_ in scenario.inputs}
    if not planned:
        out.add("  nothing to promote")
    for each in planned:
        words = (MAKES[each.makes].format(entry=replaced[each.input_id]) if each.promotable
                 else f"not promotable: {each.reason}")
        out.add(f"  Input {each.input_id}: {'becomes ' if each.promotable else ''}{words}")
    if scenario.applies and any(each.promotable for each in planned):
        out.add(f"Promotion revision: {promotion_revision(conn, scenario)}")


def scenario_lines(conn: sqlite3.Connection, scenario: Scenario) -> ReportLines:
    out = ReportLines()
    out.add(f"Scenario {scenario.scenario_id}")
    out.add(f"  Name: {shown(scenario.name)}")
    out.add(f"  Status: {scenario.state}")
    out.add(f"  Uncertain inputs: {'included' if scenario.include_uncertain else 'left out'}")
    out.add("Inputs:")
    if not scenario.inputs:
        out.add("  none")
    for input_ in scenario.inputs:
        out.add(f"  Input {input_.input_id}: {input_state_words(scenario, input_)}: "
                f"{input_words(input_, format_cents, format_rate)}")
        if scenario.applies and not input_.undone_at:
            out.add(f"    Undo revision: "
                    f"{scenario_revision(scenario, UNDO_INPUT, input_.input_id)}")
    if scenario.applies:
        out.add(f"Input revision: {scenario_revision(scenario, ADD_INPUT)}")
        out.add(f"Undo revision: {scenario_revision(scenario, UNDO_SCENARIO)}")
    else:
        out.add("Undone. It stays on record and no longer applies.")
    promotion_lines(conn, scenario, out)
    return out


def monthly_section(out, title, comparison, figure) -> None:
    out.add(f"{title}: baseline | scenario | difference")
    for base, other in zip(comparison.baseline.months, comparison.projected.months):
        out.add(f"  {base.month}: {amount(figure(base))} | {amount(figure(other))} | "
                f"{difference(figure(base), figure(other))}")


def compare_lines(comparison: Comparison) -> ReportLines:
    scenario, baseline, projected = (comparison.scenario, comparison.baseline,
                                     comparison.projected)
    out = ReportLines()
    first = baseline.months[0].month
    out.add(f"Scenario {scenario.scenario_id}: {shown(scenario.name)}")
    out.add(f"  As of {baseline.as_of}, {comparison.months} months from {first}: "
            f"{PROJECTION_LABEL}")
    out.add(f"  Uncertain inputs: {'included' if scenario.include_uncertain else 'left out'}")
    out.add("Inputs:")
    active = [input_ for input_ in scenario.inputs if not input_.undone_at]
    if not active:
        out.add("  none: the scenario is the baseline")
    for input_ in active:
        out.add(f"  Input {input_.input_id}: {input_state_words(scenario, input_)}: "
                f"{input_words(input_, format_cents, format_rate)}")
        alike = projected.look_alikes.get(input_.input_id)
        if alike:
            out.add(f"    possibly_already_planned: looks like {', '.join(alike)}, counted as "
                    "typed")
    monthly_section(out, "Monthly cash flow", comparison, lambda month: month.cash_flow_cents)
    monthly_section(out, "Liquidity at month end", comparison,
                    lambda month: month.liquidity_cents)
    monthly_section(out, "Daily allowance", comparison,
                    lambda month: month.daily_allowance_cents)
    monthly_section(out, "Weekly allowance", comparison,
                    lambda month: month.weekly_allowance_cents)
    monthly_section(out, f"Debt at month end ({PROJECTION_LABEL})", comparison,
                    lambda month: month.debt_cents)
    monthly_section(out, f"Net worth at month end ({PROJECTION_LABEL}, scenario assets apart)",
                    comparison, lambda month: month.net_worth_cents)
    monthly_section(out, "Scenario assets at month end", comparison,
                    lambda month: month.scenario_assets_cents)
    out.add("Goals: baseline | scenario | difference")
    if not baseline.goals:
        out.add("  none")
    for base, other in zip(baseline.goals, projected.goals):
        target = (f", target {format_cents(base.target_cents)} by {base.deadline}"
                  if base.target_cents is not None else "")
        out.add(f"  Fund {base.fund_id}: {shown(base.name)}, {base.kind}{target}")
        out.add(f"    Required saving this month: {amount(base.required_monthly_cents)} | "
                f"{amount(other.required_monthly_cents)} | "
                f"{difference(base.required_monthly_cents, other.required_monthly_cents)}")
        out.add(f"    Completion month: {base.completion_month or 'none'} | "
                f"{other.completion_month or 'none'}")
        out.add(f"    Held at the horizon's end: {amount(base.held_cents)} | "
                f"{amount(other.held_cents)} | {difference(base.held_cents, other.held_cents)}")
    out.add(f"Loans at the horizon's end ({PROJECTION_LABEL}): baseline | scenario")
    base_loans = {loan.name: loan for loan in baseline.loans}
    if not projected.loans:
        out.add("  none")
    for loan in projected.loans:
        base = base_loans.get(loan.name)
        out.add(f"  {shown(loan.name)}{', a scenario loan' if loan.scenario else ''}: "
                f"{'none' if base is None else amount(base.balance_cents)} | "
                f"{amount(loan.balance_cents)}, paid off "
                f"{'none' if base is None else base.paid_off or 'beyond the horizon'} | "
                f"{loan.paid_off or 'beyond the horizon'}")
    out.add("Cash shortfalls, months ending below the protected amount:")
    out.add(f"  baseline: {', '.join(baseline.shortfall_months) or 'none'}")
    out.add(f"  scenario: {', '.join(projected.shortfall_months) or 'none'}")
    out.add("Unmet goals:")
    out.add(f"  baseline: {', '.join(shown(name) for name in baseline.unmet_goals) or 'none'}")
    out.add(f"  scenario: {', '.join(shown(name) for name in projected.unmet_goals) or 'none'}")
    out.add("Assumptions:")
    for assumption in projected.assumptions:
        out.add(f"  {assumption}")
    out.add("Missing inputs:")
    for missing in projected.missing or ("none",):
        out.add(f"  {missing}")
    return out
