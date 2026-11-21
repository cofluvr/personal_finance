"""Promoting a scenario's confirmed inputs into planning entries, and undoing it (D-074 point 6,
the M18.3 slice plan).

Promotion is explicit, atomic and reversible. Every confirmed input still counted becomes the
entries point 6 maps it to, through the same functions the planning commands call, in one
transaction under one write lock, or nothing does. sp1 covers the scenario with every input and
every entry it replaces with that entry's own token, so a plan changed since the comparison
refuses. An undo withdraws the terms rows it made, which every terms loader then leaves out, and
undoes each entry it made, refusing, and naming it, where anything made has changed since.
Promotion writes planning entries only (point 7): no ledger table changes.
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from personal_finance.money import format_cents
from personal_finance.planning import funds, income_sources, obligations
from personal_finance.planning.entries import in_one_write, refuse_unless_revision
from personal_finance.planning.funds import FundRequest, TermsOptions, fund_revision, load_funds
from personal_finance.planning.income_effects import (
    BASELINE_COUNT,
    SALARY,
    SIDE,
    load_sources,
    write_income_source_effects,
)
from personal_finance.planning.obligation_effects import (
    FIXED,
    load_obligations,
    write_obligation_effects,
)
from personal_finance.planning.scenarios import (
    ANNUAL_EXPENSE,
    BONUS,
    BORROWING,
    EXPENSE,
    FUND,
    HOME_PURCHASE,
    INCOME,
    LOAN_PAYOFF,
    OBLIGATION,
    PURCHASE,
    SCENARIO_NOT_ACTIVE,
    SOURCE,
    TARGET_CHANGED,
    Scenario,
    find_scenario,
    input_cadence,
    scenario_material,
)
from personal_finance.planning.schedules import (
    cadence_dates,
    cadence_spec,
    kept_terms,
    terms_in_effect,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reports.category_rule_evidence import digest
from personal_finance.reports.income_evidence import TERMS as SOURCE_TERMS
from personal_finance.reports.income_evidence import UNDO as SOURCE_UNDO
from personal_finance.reports.income_evidence import source_outlook
from personal_finance.reports.obligation_evidence import TERMS as OBLIGATION_TERMS
from personal_finance.reports.obligation_evidence import UNDO as OBLIGATION_UNDO
from personal_finance.reports.obligation_evidence import obligation_outlook

# Bump whenever the material below changes, so an old token can never appear current.
PROMOTION_REVISION_VERSION = 1

PROMOTE = "promote"
PROMOTION_UNDO = "promotion_undo"

# What a promotion makes, as scenario_promotion_entry names it.
SOURCE_TERMS_ROW = "income_source_terms"
OBLIGATION_TERMS_ROW = "recurring_obligation_terms"
FUND_TERMS_ROW = "fund_terms"
TERMS_TABLES = {SOURCE_TERMS_ROW: ("income_source_terms", "chain_id"),
                OBLIGATION_TERMS_ROW: ("recurring_obligation_terms", "chain_id"),
                FUND_TERMS_ROW: ("fund_terms", "fund_id")}

# Why an input is not promotable (point 6), each listed.
UNCERTAIN_INPUT = "uncertain inputs are never promoted"
TARGET_GONE = "target_changed: the entry it replaces no longer applies"
NEEDS_AN_ACCOUNT = "a borrowing or a home purchase needs an account that does not exist yet"
NO_LUMP_SUM = ("the payoff plan holds a monthly extra, not a one-time payment, so the payoff "
               "stays a scenario")
NO_ONE_TIME_INCOME = "no planning entry holds one-time income"
NO_ACCOUNT_GIVEN = "an additional income or expense needs --account and --match to be promoted"
NO_END_DATE = "a source, obligation or reserve has no end date, so an addition with --to stays"
ZERO_AMOUNT = "a source's or obligation's amount is above zero"

NOTHING_PROMOTABLE = (
    "nothing in this scenario is promotable: see the reasons scenario show lists. Nothing was "
    "changed."
)
PROMOTED_ALREADY = (
    "this scenario is promoted already. Undo its promotion first to promote it again. Nothing "
    "was changed."
)
NOT_PROMOTED = "this scenario has no promotion in effect. Nothing was changed."
WITHDRAWN_ROW_ON_DATE = (
    "an undone promotion's terms row holds {entry} from {date} already. Add the input again "
    "with another --from. Nothing was changed."
)
CHANGED_SINCE = (
    "{entry} has changed since the promotion made it: {change}. Undo or change it in the "
    "planning commands first. Nothing was changed."
)
STALE_PROMOTION_REVISION = (
    "this revision does not match the scenario and the plan as they are now. Nothing was "
    "changed. Run scenario show and check it again."
)


@dataclass(frozen=True)
class Planned:
    """One input and what promoting it does: the entry kind it makes, or why it cannot."""

    input_id: str
    makes: str | None
    reason: str | None = None

    @property
    def promotable(self) -> bool:
        return self.makes is not None


@dataclass(frozen=True)
class Promotion:
    promotion_id: str
    scenario_id: str
    # (entry kind, entry ID or None, terms row ID or None, input ID), in the order made.
    entries: tuple[tuple[str, str | None, int | None, str], ...]
    undone_at: str | None = None


def planned_for(scenario: Scenario) -> tuple[Planned, ...]:
    """What promoting each input not undone would do, by point 6's table."""
    found = []
    for input_ in scenario.inputs:
        if input_.undone_at:
            continue
        found.append(Planned(input_.input_id, *what_it_makes(input_)))
    return tuple(found)


def what_it_makes(input_) -> tuple[str | None, str | None]:
    if input_.state == TARGET_CHANGED:
        return None, TARGET_GONE
    if input_.uncertain:
        return None, UNCERTAIN_INPUT
    if input_.kind in (BORROWING, HOME_PURCHASE):
        return None, NEEDS_AN_ACCOUNT
    if input_.kind == LOAN_PAYOFF:
        return None, NO_LUMP_SUM
    if input_.kind == BONUS:
        return None, NO_ONE_TIME_INCOME
    if input_.replaces_id:
        if input_.kind in (INCOME, EXPENSE) and input_.take_home_cents == 0:
            return None, ZERO_AMOUNT
        return {SOURCE: SOURCE_TERMS_ROW, OBLIGATION: OBLIGATION_TERMS_ROW,
                FUND: FUND_TERMS_ROW}[input_.replaces_kind], None
    if input_.to_date is not None:
        return None, NO_END_DATE
    if input_.kind in (INCOME, EXPENSE):
        if input_.account_id is None:
            return None, NO_ACCOUNT_GIVEN
        if input_.take_home_cents == 0:
            return None, ZERO_AMOUNT
        return (SOURCE if input_.kind == INCOME else OBLIGATION), None
    if input_.kind in (PURCHASE, ANNUAL_EXPENSE):
        return FUND, None
    raise ValueError(f"no mapping for a {input_.kind} input")


# Loading.

def load_promotions(conn: sqlite3.Connection, scenario_id: str) -> tuple[Promotion, ...]:
    entries = {}
    for promotion_id, kind, entry_id, row_id, input_id in conn.execute(
            """SELECT entry.promotion_id, entry.entry_kind, entry.entry_id, entry.terms_row_id,
                      entry.input_id
               FROM scenario_promotion_entry entry ORDER BY entry.id"""):
        entries.setdefault(promotion_id, []).append((kind, entry_id, row_id, input_id))
    return tuple(
        Promotion(promotion_id, scenario_id, tuple(entries.get(promotion_id, ())), undone_at)
        for promotion_id, undone_at in conn.execute(
            """SELECT promotion.id, undone.created_at FROM scenario_promotion promotion
               LEFT JOIN scenario_promotion_event undone
                   ON undone.promotion_id = promotion.id AND undone.event = 'undone'
               WHERE promotion.scenario_id = ? ORDER BY promotion.created_at, promotion.id""",
            (scenario_id,)))


def active_promotion(conn: sqlite3.Connection, scenario_id: str) -> Promotion | None:
    return next((promotion for promotion in load_promotions(conn, scenario_id)
                 if promotion.undone_at is None), None)


# The token.

def entry_tokens(conn: sqlite3.Connection, scenario: Scenario) -> dict[str, str]:
    """Each entry a replacement names, with its own token for a new terms row."""
    sources = {source.source_id: source for source in load_sources(conn)}
    duties = {obligation.obligation_id: obligation for obligation in load_obligations(conn)}
    reserves = {fund.fund_id: fund for fund in load_funds(conn)}
    releases = funds.load_releases(conn)
    found = {}
    for input_ in scenario.inputs:
        if input_.undone_at or not input_.replaces_id or input_.state == TARGET_CHANGED:
            continue
        entry_id = input_.replaces_id
        if input_.replaces_kind == SOURCE:
            found[entry_id] = source_outlook(conn, sources[entry_id], SOURCE_TERMS).revision
        elif input_.replaces_kind == OBLIGATION:
            found[entry_id] = obligation_outlook(conn, duties[entry_id],
                                                 OBLIGATION_TERMS).revision
        else:
            found[entry_id] = fund_revision(funds.TERMS, reserves[entry_id], releases)
    return found


def promotion_revision(conn: sqlite3.Connection, scenario: Scenario) -> str:
    """sp1 for promoting: the scenario with every input and its state, and each replaced
    entry's own token (point 6)."""
    material = {"operation": PROMOTE, "scenario": scenario_material(scenario),
                "replaced": entry_tokens(conn, scenario)}
    return f"sp{PROMOTION_REVISION_VERSION}-{digest(material)}"


def promotion_undo_revision(scenario: Scenario, promotion: Promotion) -> str:
    """sp1 for undoing: the scenario, and the promotion with every entry it made."""
    material = {"operation": PROMOTION_UNDO, "scenario": scenario_material(scenario),
                "promotion_id": promotion.promotion_id,
                "entries": [list(entry) for entry in promotion.entries]}
    return f"sp{PROMOTION_REVISION_VERSION}-{digest(material)}"


# Promoting.

def first_date(input_) -> str:
    """A recurring input's first date on or after --from: a source's or obligation's anchor."""
    cadence, anchor = input_cadence(input_)
    start = date.fromisoformat(input_.from_date)
    return cadence_dates(cadence, anchor, start, start + timedelta(days=400))[0].isoformat()


def day_after(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def promote(conn: sqlite3.Connection, scenario_id: str, as_of: str, revision: str,
            rules: MatchingRules = DEFAULT_RULES) -> Promotion:
    """Every promotable input into its entries in one transaction, or refuse and change
    nothing."""
    return in_one_write(conn, lambda: _promote(conn, scenario_id, as_of, revision, rules))


def _promote(conn, scenario_id, as_of, revision, rules) -> Promotion:
    scenario = find_scenario(conn, scenario_id)
    if not scenario.applies:
        raise DecisionRefused(SCENARIO_NOT_ACTIVE)
    if active_promotion(conn, scenario_id):
        raise DecisionRefused(PROMOTED_ALREADY)
    refuse_unless_revision(promotion_revision(conn, scenario), revision,
                           STALE_PROMOTION_REVISION)
    planned = [each for each in planned_for(scenario) if each.promotable]
    if not planned:
        raise DecisionRefused(NOTHING_PROMOTABLE)
    promotion_id = str(uuid.uuid4())
    conn.execute("INSERT INTO scenario_promotion (id, scenario_id) VALUES (?, ?)",
                 (promotion_id, scenario_id))
    conn.execute("INSERT INTO scenario_promotion_event (promotion_id, event) VALUES (?, 'made')",
                 (promotion_id,))
    inputs = {input_.input_id: input_ for input_ in scenario.inputs}
    made = []
    for each in planned:
        input_ = inputs[each.input_id]
        for kind, entry_id, row_id in make(conn, scenario, input_, as_of, rules):
            conn.execute(
                """INSERT INTO scenario_promotion_entry (promotion_id, input_id, entry_kind,
                                                         entry_id, terms_row_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (promotion_id, input_.input_id, kind, entry_id, row_id))
            made.append((kind, entry_id, row_id, input_.input_id))
    return Promotion(promotion_id, scenario_id, tuple(made))


def make(conn, scenario, input_, as_of, rules) -> list[tuple[str, str | None, int | None]]:
    """The entries one input becomes, each made by its planning command's own function."""
    name = f"{scenario.name} {input_.input_id[:8]}"
    if input_.replaces_kind == SOURCE:
        return new_source_terms(conn, input_, as_of, rules)
    if input_.replaces_kind == OBLIGATION:
        return new_obligation_terms(conn, input_, as_of, rules)
    if input_.replaces_kind == FUND:
        return new_reserve_terms(conn, input_, as_of)
    if input_.kind == INCOME:
        cadence, _ = input_cadence(input_)
        request = income_sources.SourceRequest(
            input_.account_id, name, SALARY if cadence.name in BASELINE_COUNT else SIDE,
            input_.match_text, input_.cadence, first_date(input_),
            format_cents(input_.take_home_cents))
        outlook = income_sources.source_preview(conn, request)
        added = income_sources._add_source(conn, request, outlook.revision, rules)
        return [(SOURCE, added.source_id, None)]
    if input_.kind == EXPENSE:
        request = obligations.ObligationRequest(
            input_.account_id, name, input_.match_text, cadence=input_.cadence,
            anchor=first_date(input_), amount=format_cents(input_.amount_cents),
            obligation_class=FIXED)
        outlook = obligations.obligation_preview(conn, request)
        added = obligations._add_obligation(conn, request, outlook.revision, rules)
        return [(OBLIGATION, added.obligation_id, None)]
    if input_.kind == PURCHASE:
        options = TermsOptions(target=format_cents(input_.amount_cents), due=input_.from_date)
    else:
        options = TermsOptions(target=format_cents(input_.amount_cents), cadence=input_.cadence)
    request = FundRequest(name, funds.RESERVE, options)
    fund = funds.checked_fund(conn, request, as_of)
    fund_id = funds._add_fund(conn, request, as_of, fund_revision(funds.ADD, fund))
    return [(FUND, fund_id, None)]


def refuse_if_withdrawn_row(conn, kind: str, owner_id: str, effective_from: str,
                            entry: str) -> None:
    """A terms row withdrawn by an undone promotion keeps its date: UNIQUE holds it."""
    table, owner = TERMS_TABLES[kind]
    if conn.execute(f"SELECT 1 FROM {table} WHERE {owner} = ? AND effective_from = ? "
                    f"AND NOT {kept_terms(kind, table)}", (owner_id, effective_from)).fetchone():
        raise DecisionRefused(WITHDRAWN_ROW_ON_DATE.format(entry=entry, date=effective_from))


def row_id(conn, kind: str, owner_id: str, effective_from: str) -> int:
    table, owner = TERMS_TABLES[kind]
    (found,) = conn.execute(f"SELECT id FROM {table} WHERE {owner} = ? AND effective_from = ?",
                            (owner_id, effective_from)).fetchone()
    return found


def new_source_terms(conn, input_, as_of, rules):
    """A terms row on the replaced source from --from, and one from the day after --to giving
    back the terms then in effect."""
    source = next(source for source in load_sources(conn) if source.source_id == input_.replaces_id)
    rows = [(input_.from_date, format_cents(input_.take_home_cents), input_.cadence,
             first_date(input_))]
    if input_.to_date:
        before = terms_in_effect(source.terms, day_after(input_.to_date))
        rows.append((day_after(input_.to_date), format_cents(before.amount_cents),
                     cadence_spec(before.cadence, before.anchor), before.anchor))
    made = []
    for effective_from, amount, cadence, anchor in rows:
        refuse_if_withdrawn_row(conn, SOURCE_TERMS_ROW, source.chain_id, effective_from,
                                f"income source {source.source_id}")
        current = next(each for each in load_sources(conn) if each.source_id == source.source_id)
        income_sources._change_terms(conn, source.source_id, effective_from, amount, as_of,
                                     source_outlook(conn, current, SOURCE_TERMS).revision,
                                     cadence, anchor, rules)
        made.append((SOURCE_TERMS_ROW, None,
                     row_id(conn, SOURCE_TERMS_ROW, source.chain_id, effective_from)))
    return made


def new_obligation_terms(conn, input_, as_of, rules):
    """As new_source_terms, for an obligation, keeping its class."""
    duty = next(duty for duty in load_obligations(conn)
                if duty.obligation_id == input_.replaces_id)
    rows = [(input_.from_date, format_cents(input_.amount_cents), None, input_.cadence,
             first_date(input_))]
    if input_.to_date:
        before = terms_in_effect(duty.terms, day_after(input_.to_date))
        exact = before.low_cents == before.high_cents
        rows.append((day_after(input_.to_date),
                     format_cents(before.low_cents) if exact else None,
                     None if exact else f"{format_cents(before.low_cents)}.."
                                        f"{format_cents(before.high_cents)}",
                     cadence_spec(before.cadence, before.anchor), before.anchor))
    made = []
    for effective_from, amount, amount_range, cadence, anchor in rows:
        refuse_if_withdrawn_row(conn, OBLIGATION_TERMS_ROW, duty.chain_id, effective_from,
                                f"obligation {duty.obligation_id}")
        current = next(each for each in load_obligations(conn)
                       if each.obligation_id == duty.obligation_id)
        obligations._change_terms(
            conn, duty.obligation_id,
            obligations.TermsRequest(effective_from, as_of, amount, amount_range, cadence,
                                     anchor),
            obligation_outlook(conn, current, OBLIGATION_TERMS).revision, rules)
        made.append((OBLIGATION_TERMS_ROW, None,
                     row_id(conn, OBLIGATION_TERMS_ROW, duty.chain_id, effective_from)))
    return made


def reserve_options(terms) -> TermsOptions:
    """A reserve's terms typed again, as fund terms takes them."""
    if terms.shape == funds.DUE:
        return TermsOptions(target=format_cents(terms.amount_cents), due=terms.due_date)
    spec = cadence_spec(terms.cadence, terms.anchor)
    anchor = terms.anchor if terms.cadence.name == "every_months" else None
    return TermsOptions(target=format_cents(terms.amount_cents), cadence=spec, anchor=anchor)


def new_reserve_terms(conn, input_, as_of):
    """A reserve's new terms from --from, its target the annual amount, and its old terms
    again from the day after --to."""
    reserve = next(fund for fund in load_funds(conn) if fund.fund_id == input_.replaces_id)
    rows = [(input_.from_date, TermsOptions(target=format_cents(input_.amount_cents),
                                            cadence=input_.cadence))]
    if input_.to_date:
        rows.append((day_after(input_.to_date),
                     reserve_options(reserve.terms_on(day_after(input_.to_date)))))
    made = []
    for effective_from, options in rows:
        refuse_if_withdrawn_row(conn, FUND_TERMS_ROW, reserve.fund_id, effective_from,
                                f"fund {reserve.fund_id}")
        current = next(fund for fund in load_funds(conn) if fund.fund_id == reserve.fund_id)
        funds._change_terms(conn, reserve.fund_id, options, effective_from, as_of,
                            fund_revision(funds.TERMS, current, funds.load_releases(conn)))
        made.append((FUND_TERMS_ROW, None,
                     row_id(conn, FUND_TERMS_ROW, reserve.fund_id, effective_from)))
    return made


# Undoing.

def undo_promotion(conn: sqlite3.Connection, scenario_id: str, revision: str,
                   rules: MatchingRules = DEFAULT_RULES) -> Promotion:
    """Withdraw every terms row a promotion made and undo every entry, in one transaction, or
    refuse, naming the newer change, and change nothing."""
    return in_one_write(conn, lambda: _undo_promotion(conn, scenario_id, revision, rules))


def _undo_promotion(conn, scenario_id, revision, rules) -> Promotion:
    scenario = find_scenario(conn, scenario_id)
    promotion = active_promotion(conn, scenario_id)
    if promotion is None:
        raise DecisionRefused(NOT_PROMOTED)
    refuse_unless_revision(promotion_undo_revision(scenario, promotion), revision,
                           STALE_PROMOTION_REVISION)
    refuse_if_changed_since(conn, promotion)
    conn.execute("INSERT INTO scenario_promotion_event (promotion_id, event) "
                 "VALUES (?, 'undone')", (promotion.promotion_id,))
    write_income_source_effects(conn)
    write_obligation_effects(conn)
    for kind, entry_id, _, _ in promotion.entries:
        if kind == SOURCE:
            source = next(each for each in load_sources(conn) if each.source_id == entry_id)
            income_sources._undo_source(conn, entry_id,
                                        source_outlook(conn, source, SOURCE_UNDO).revision,
                                        rules)
        elif kind == OBLIGATION:
            duty = next(each for each in load_obligations(conn) if each.obligation_id == entry_id)
            obligations._undo_obligation(
                conn, entry_id, obligation_outlook(conn, duty, OBLIGATION_UNDO).revision, rules)
        elif kind == FUND:
            fund = next(each for each in load_funds(conn) if each.fund_id == entry_id)
            funds._undo_fund(conn, entry_id,
                             fund_revision(funds.UNDO, fund, funds.load_releases(conn)))
    return promotion


def refuse_if_changed_since(conn, promotion: Promotion) -> None:
    """Every entry made must be as the promotion left it: a source or obligation not undone or
    superseded, a fund not undone, and no terms row added after one it made."""
    made_rows = {(kind, row) for kind, _, row, _ in promotion.entries if row is not None}
    sources = {source.source_id: source for source in load_sources(conn)}
    duties = {duty.obligation_id: duty for duty in load_obligations(conn)}
    reserves = {fund.fund_id: fund for fund in load_funds(conn)}
    for kind, entry_id, row, _ in promotion.entries:
        if kind == SOURCE:
            refuse_unless_unchanged(sources[entry_id], f"income source {entry_id}")
        elif kind == OBLIGATION:
            refuse_unless_unchanged(duties[entry_id], f"obligation {entry_id}")
        elif kind == FUND and reserves[entry_id].undone_at:
            raise DecisionRefused(CHANGED_SINCE.format(entry=f"fund {entry_id}",
                                                       change="it is undone"))
        elif row is not None:
            table, owner = TERMS_TABLES[kind]
            (owner_id, effective_from) = conn.execute(
                f"SELECT {owner}, effective_from FROM {table} WHERE id = ?", (row,)).fetchone()
            for (later_id, later_from) in conn.execute(
                    f"SELECT id, effective_from FROM {table} terms WHERE {owner} = ? "
                    f"AND effective_from > ? AND {kept_terms(kind)} ORDER BY effective_from",
                    (owner_id, effective_from)):
                if (kind, later_id) not in made_rows:
                    raise DecisionRefused(CHANGED_SINCE.format(
                        entry=f"the terms of {owner_id}",
                        change=f"a later terms row from {later_from}"))


def refuse_unless_unchanged(entry, words: str) -> None:
    if entry.undone_at:
        raise DecisionRefused(CHANGED_SINCE.format(entry=words, change="it is undone"))
    if entry.superseded_by:
        raise DecisionRefused(CHANGED_SINCE.format(
            entry=words, change=f"it is superseded by {entry.superseded_by}"))
