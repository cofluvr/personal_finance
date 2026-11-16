"""Adding, superseding, re-terming and undoing income sources stated by a person. See
decisions-m12-m21.md D-067 G2 to G4, D-068 and its M12.1 slice plan.

Every command checks everything under one write lock and either commits with the sources'
outcomes rewritten or changes nothing, in D-043's order: the source's account is current, then
what was typed is valid, then its in1 token. A source moves no record and changes no amount, type,
transfer, category or allocation, so only the sources' outcomes are rewritten (G1).
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date

from personal_finance.planning import entries
from personal_finance.planning.entries import (  # noqa: F401, parsed_date is income's too
    ChainRefusals,
    checked_cadence,
    in_one_write,
    parsed_amount,
    parsed_date,
    refuse_if_closed_month,
)
from personal_finance.planning.income_effects import (
    BASELINE_COUNT,
    SALARY,
    SIDE,
    Cadence,
    IncomeSource,
    SourceDefinition,
    Terms,
    load_sources,
    on_cadence,
    write_income_source_effects,
)
from personal_finance.planning.income_proposals import IncomeProposal, find_proposal
from personal_finance.planning.schedules import CADENCE_INVALID  # noqa: F401, income's too
from personal_finance.reconcile.category_rule_effects import normalized_text
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reports.income_evidence import (
    TERMS,
    UNDO,
    IncomeOutlook,
    preview_outlook,
    source_outlook,
)

KINDS = (SALARY, SIDE)
DEFAULT_TOLERANCE_DAYS = 3
LONGEST_TOLERANCE_DAYS = 7

NAME_BLANK = "an income source needs a name that is not blank. Nothing was changed."
NAME_TAKEN = "income source {source} is active and has this name already. Nothing was changed."
TEXT_BLANK = (
    "an income source needs --match text that is not blank once spaces are collapsed. Nothing "
    "was changed."
)
SAME_MATCHER = (
    "income source {source} is active on this account and matches exactly this text already, so "
    "the two would disagree on every deposit. Nothing was changed."
)
KIND_UNKNOWN = "--kind must be salary or side. Nothing was changed."
TOLERANCE_DAYS_RANGE = "--tolerance-days must be a whole number from 0 to 7. Nothing was changed."
AMOUNT_INVALID = "--amount must be an amount above zero, such as 2500.00. Nothing was changed."
AMOUNT_TOLERANCE_INVALID = (
    "--amount-tolerance must be an amount of zero or more, such as 25.00. Nothing was changed."
)
ANCHOR_OFF_CADENCE = (
    "--anchor must be one of the cadence's own pay dates, a real pay date. Nothing was changed."
)
SALARY_CADENCE = (
    "salary is paid weekly, biweekly, semimonthly or monthly. Use --kind side for a longer "
    "cadence. Nothing was changed."
)
MEMBER_UNKNOWN = "household member not found. Run household members. Nothing was changed."
TERMS_REQUIRED = "a new income source needs --cadence, --anchor and --amount. Nothing was changed."
SUPERSEDE_TERMS_GIVEN = (
    "a source superseding another keeps its chain's terms, so --cadence, --anchor and --amount "
    "are not taken. Change them with income terms. Nothing was changed."
)
SUPERSEDE_ACCOUNT_DIFFERS = (
    "a source superseding another is on the same account. Nothing was changed."
)
PROPOSAL_NOT_FOUND = (
    "no such proposal for this account now. Run income proposals. Nothing was changed."
)
SOURCE_NOT_FOUND = "income source not found. Run income sources. Nothing was changed."
SOURCE_NOT_ACTIVE = "this income source has already been undone. Nothing was changed."
SOURCE_SUPERSEDED = (
    "this income source is superseded by {newest}, the newest of its chain, which is the one to "
    "change or undo. Nothing was changed."
)
TERMS_CLOSED_MONTH = (
    "--effective-from falls in a month before --as-of's, which is closed. Nothing was changed."
)
TERMS_NOT_LATER = (
    "--effective-from must be later than every terms row of this source, the latest from "
    "{latest}. Nothing was changed."
)
TERMS_CADENCE_PAIR = "--cadence and --anchor are given together or not at all. Nothing was changed."
STALE_INCOME_PREVIEW = (
    "this revision does not match what the source would reach now. Nothing was changed. Run "
    "income preview with the same options and check it again."
)
STALE_INCOME_REVISION = (
    "this revision does not match the source as it is now. Nothing was changed. Run income "
    "source show and check it again."
)

@dataclass(frozen=True)
class SourceRequest:
    """What a person typed for income preview and income add."""

    account_id: str
    name: str
    kind: str
    match: str
    cadence: str | None = None
    anchor: str | None = None
    amount: str | None = None
    tolerance_days: int = DEFAULT_TOLERANCE_DAYS
    amount_tolerance: str | None = None
    member: str | None = None
    tax_eligible: bool = False
    from_proposal: str | None = None
    supersedes: str | None = None


@dataclass(frozen=True)
class CheckedSource:
    source: IncomeSource
    proposal: IncomeProposal | None
    superseded: IncomeSource | None


@dataclass(frozen=True)
class SourceAdded:
    source_id: str
    outlook: IncomeOutlook


def checked_terms(cadence_text: str, anchor_text: str, amount_text: str, kind: str,
                  effective_from: str | None = None) -> Terms:
    stated = checked_cadence(cadence_text)
    anchor = parsed_date(anchor_text, "--anchor")
    when = date.fromisoformat(anchor)
    if not on_cadence(stated.cadence, when) or stated.month not in (None, when.month):
        raise DecisionRefused(ANCHOR_OFF_CADENCE)
    refuse_unless_salary_cadence(kind, stated.cadence)
    amount = parsed_amount(amount_text, AMOUNT_INVALID, least=1)
    return Terms(effective_from or anchor, stated.cadence, anchor, amount)


def refuse_unless_salary_cadence(kind: str, cadence: Cadence) -> None:
    if kind == SALARY and cadence.name not in BASELINE_COUNT:
        raise DecisionRefused(SALARY_CADENCE)


SOURCE_REFUSALS = ChainRefusals(SOURCE_NOT_FOUND, SOURCE_NOT_ACTIVE, SOURCE_SUPERSEDED)


def find_source(sources, source_id: str) -> IncomeSource:
    """The source with this ID that is still the newest of its chain."""
    return entries.find_newest(sources, source_id, SOURCE_REFUSALS)


def lookup_source(sources, source_id: str) -> IncomeSource:
    return entries.lookup_entry(sources, source_id, SOURCE_REFUSALS)


def refuse_unless_newest(sources, source: IncomeSource) -> IncomeSource:
    return entries.refuse_unless_newest(sources, source, SOURCE_REFUSALS)


def checked_source(conn: sqlite3.Connection, request: SourceRequest) -> CheckedSource:
    """A source as typed, refused for anything it gets wrong. Nothing is written."""
    sources = load_sources(conn)
    superseded = None
    if request.supersedes is not None:
        superseded = find_source(sources, request.supersedes)
        if superseded.definition.account_id != request.account_id:
            raise DecisionRefused(SUPERSEDE_ACCOUNT_DIFFERS)
        if (request.cadence, request.anchor, request.amount) != (None, None, None):
            raise DecisionRefused(SUPERSEDE_TERMS_GIVEN)
    elif None in (request.cadence, request.anchor, request.amount):
        raise DecisionRefused(TERMS_REQUIRED)
    if not request.name.strip():
        raise DecisionRefused(NAME_BLANK)
    if request.kind not in KINDS:
        raise DecisionRefused(KIND_UNKNOWN)
    if not normalized_text(request.match):
        raise DecisionRefused(TEXT_BLANK)
    others = [source for source in sources if source.undone_at is None
              and (superseded is None or source.chain_id != superseded.chain_id)]
    for other in others:
        if other.definition.name == request.name:
            raise DecisionRefused(NAME_TAKEN.format(source=other.source_id))
        if (other.applies and other.definition.account_id == request.account_id
                and normalized_text(other.definition.description_contains)
                == normalized_text(request.match)):
            raise DecisionRefused(SAME_MATCHER.format(source=other.source_id))
    if not 0 <= request.tolerance_days <= LONGEST_TOLERANCE_DAYS:
        raise DecisionRefused(TOLERANCE_DAYS_RANGE)
    amount_tolerance = 0
    if request.amount_tolerance is not None:
        amount_tolerance = parsed_amount(request.amount_tolerance, AMOUNT_TOLERANCE_INVALID,
                                         least=0)
    member_id = None
    if request.member is not None:
        row = conn.execute("SELECT id FROM household_member WHERE name = ?",
                           (request.member,)).fetchone()
        if row is None:
            raise DecisionRefused(MEMBER_UNKNOWN)
        member_id = row[0]
    if superseded is None:
        terms = (checked_terms(request.cadence, request.anchor, request.amount, request.kind),)
    else:
        terms = superseded.terms
        for chain_terms in terms:
            refuse_unless_salary_cadence(request.kind, chain_terms.cadence)
    proposal = None
    if request.from_proposal is not None:
        proposal = find_proposal(conn, request.account_id, request.from_proposal)
        if proposal is None:
            raise DecisionRefused(PROPOSAL_NOT_FOUND)
    definition = SourceDefinition(request.account_id, request.name, request.kind, request.match,
                                  request.tolerance_days, amount_tolerance, member_id,
                                  request.tax_eligible)
    chain_id = superseded.chain_id if superseded else "proposed"
    source = IncomeSource("proposed", chain_id, superseded and superseded.source_id, definition,
                          terms)
    return CheckedSource(source, proposal, superseded)


def source_preview(conn: sqlite3.Connection, request: SourceRequest) -> IncomeOutlook:
    checked = checked_source(conn, request)
    return preview_outlook(conn, checked.source, checked.proposal, checked.superseded)


def refuse_unless_current(conn: sqlite3.Connection, account_id: str,
                          rules: MatchingRules) -> None:
    """The source's account must be current (D-033), or nothing is decided."""
    entries.refuse_unless_current(conn, account_id, rules)


def refuse_unless_revision(outlook: IncomeOutlook, revision: str, message: str) -> None:
    entries.refuse_unless_revision(outlook.revision, revision, message)


def add_source(conn: sqlite3.Connection, request: SourceRequest, revision: str,
               rules: MatchingRules = DEFAULT_RULES) -> SourceAdded:
    """Record a source, or one superseding another, whose preview is still current."""
    return in_one_write(conn, lambda: _add_source(conn, request, revision, rules))


def _add_source(conn, request, revision, rules) -> SourceAdded:
    refuse_unless_current(conn, request.account_id, rules)
    checked = checked_source(conn, request)
    outlook = preview_outlook(conn, checked.source, checked.proposal, checked.superseded)
    refuse_unless_revision(outlook, revision, STALE_INCOME_PREVIEW)
    source_id = str(uuid.uuid4())
    definition = checked.source.definition
    superseded = checked.superseded
    conn.execute(
        """INSERT INTO income_source (id, account_id, name, kind, description_contains,
                                      normalization_version, tolerance_days,
                                      amount_tolerance_cents, member_id, tax_eligible,
                                      supersedes_id, chain_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_id, definition.account_id, definition.name, definition.kind,
         definition.description_contains, definition.normalization_version,
         definition.tolerance_days, definition.amount_tolerance_cents, definition.member_id,
         int(definition.tax_eligible), superseded and superseded.source_id,
         superseded.chain_id if superseded else source_id),
    )
    if superseded is None:
        insert_terms(conn, source_id, checked.source.terms[0])
    conn.execute("INSERT INTO income_source_event (source_id, event) VALUES (?, 'made')",
                 (source_id,))
    write_income_source_effects(conn)
    return SourceAdded(source_id, outlook)


def insert_terms(conn: sqlite3.Connection, chain_id: str, terms: Terms) -> None:
    cadence = terms.cadence
    conn.execute(
        """INSERT INTO income_source_terms (chain_id, effective_from, cadence, first_day,
                                            second_day, interval_months, anchor, amount_cents)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (chain_id, terms.effective_from, cadence.name, cadence.first_day, cadence.second_day,
         cadence.interval_months, terms.anchor, terms.amount_cents),
    )


def change_terms(conn: sqlite3.Connection, source_id: str, effective_from: str, amount: str,
                 as_of: str, revision: str, cadence: str | None = None,
                 anchor: str | None = None, rules: MatchingRules = DEFAULT_RULES) -> Terms:
    """Add a terms row taking over from effective_from, which falls in no closed month."""
    return in_one_write(conn, lambda: _change_terms(conn, source_id, effective_from, amount,
                                                    as_of, revision, cadence, anchor, rules))


def _change_terms(conn, source_id, effective_from, amount, as_of, revision, cadence, anchor,
                  rules) -> Terms:
    sources = load_sources(conn)
    source = lookup_source(sources, source_id)
    refuse_unless_current(conn, source.definition.account_id, rules)
    refuse_unless_newest(sources, source)
    effective_from = parsed_date(effective_from, "--effective-from")
    as_of = parsed_date(as_of, "--as-of")
    refuse_if_closed_month(effective_from, as_of, TERMS_CLOSED_MONTH)
    latest = source.terms[-1]
    if effective_from <= latest.effective_from:
        raise DecisionRefused(TERMS_NOT_LATER.format(latest=latest.effective_from))
    if (cadence is None) != (anchor is None):
        raise DecisionRefused(TERMS_CADENCE_PAIR)
    if cadence is None:
        terms = Terms(effective_from, latest.cadence, latest.anchor,
                      parsed_amount(amount, AMOUNT_INVALID, least=1))
    else:
        terms = checked_terms(cadence, anchor, amount, source.definition.kind, effective_from)
    refuse_unless_revision(source_outlook(conn, source, TERMS), revision, STALE_INCOME_REVISION)
    insert_terms(conn, source.chain_id, terms)
    write_income_source_effects(conn)
    return terms


def undo_source(conn: sqlite3.Connection, source_id: str, revision: str,
                rules: MatchingRules = DEFAULT_RULES) -> IncomeSource:
    """Stop the newest source of a chain applying, keeping it on record. The one it superseded,
    if any, applies again (G4). Never refused for contradiction."""
    return in_one_write(conn, lambda: _undo_source(conn, source_id, revision, rules))


def _undo_source(conn, source_id, revision, rules) -> IncomeSource:
    sources = load_sources(conn)
    source = lookup_source(sources, source_id)
    refuse_unless_current(conn, source.definition.account_id, rules)
    refuse_unless_newest(sources, source)
    refuse_unless_revision(source_outlook(conn, source, UNDO), revision, STALE_INCOME_REVISION)
    conn.execute("INSERT INTO income_source_event (source_id, event) VALUES (?, 'undone')",
                 (source_id,))
    write_income_source_effects(conn)
    return source
