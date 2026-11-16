"""Adding, superseding, re-terming and undoing recurring obligations, and dismissing proposals,
stated by a person. See decisions-m12-m21.md D-067 G2 to G4, D-068 point 5, and "How M12.2 was
implemented".

Every command checks everything under one write lock and either commits with the obligations'
outcomes rewritten or changes nothing, in D-043's order: the account is current, then what was
typed is valid, then its ob1 token. An obligation moves no record and changes no amount, type,
transfer, category or allocation, so only the obligations' outcomes are rewritten (G1).
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date

from personal_finance.planning.entries import (
    ChainRefusals,
    checked_cadence,
    find_newest,
    in_one_write,
    lookup_entry,
    parsed_amount,
    parsed_date,
    refuse_if_closed_month,
    refuse_unless_current,
    refuse_unless_newest,
    refuse_unless_revision,
)
from personal_finance.planning.obligation_effects import (
    CLASSES,
    ObligationDefinition,
    ObligationTerms,
    RecurringObligation,
    load_obligations,
    write_obligation_effects,
)
from personal_finance.planning.obligation_proposals import (
    Dismissal,
    ObligationProposal,
    find_any_proposal,
    find_proposal,
    load_dismissals,
)
from personal_finance.planning.schedules import on_cadence
from personal_finance.reconcile.category_rule_effects import normalized_text
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reports.obligation_evidence import (
    TERMS,
    UNDO,
    ObligationOutlook,
    dismiss_revision,
    obligation_outlook,
    preview_outlook,
    undo_dismissal_revision,
)

DEFAULT_TOLERANCE_DAYS = 3
LONGEST_TOLERANCE_DAYS = 7

NAME_BLANK = "an obligation needs a name that is not blank. Nothing was changed."
NAME_TAKEN = "obligation {obligation} is active and has this name already. Nothing was changed."
TEXT_BLANK = (
    "an obligation needs --match text that is not blank once spaces are collapsed. Nothing was "
    "changed."
)
SAME_MATCHER = (
    "obligation {obligation} is active on this account and matches exactly this text and "
    "category already, so the two would disagree on every payment. Nothing was changed."
)
CATEGORY_UNKNOWN = "category not found. Run category list. Nothing was changed."
CLASS_UNKNOWN = "--class must be fixed or discretionary. Nothing was changed."
TOLERANCE_DAYS_RANGE = "--tolerance-days must be a whole number from 0 to 7. Nothing was changed."
AMOUNT_INVALID = "--amount must be an amount above zero, such as 85.00. Nothing was changed."
RANGE_INVALID = (
    "--range must be LOW..HIGH, two amounts above zero with LOW no more than HIGH, such as "
    "60.00..140.00. Nothing was changed."
)
AMOUNT_OR_RANGE = "give --amount or --range, not both. Nothing was changed."
ANCHOR_OFF_CADENCE = (
    "--anchor must be one of the cadence's own due dates, a real due date. Nothing was changed."
)
TERMS_REQUIRED = (
    "a new obligation needs --cadence, --anchor, --amount or --range, and --class. Nothing was "
    "changed."
)
SUPERSEDE_TERMS_GIVEN = (
    "an obligation superseding another keeps its chain's terms, so --cadence, --anchor, "
    "--amount, --range and --class are not taken. Change them with obligation terms. Nothing was "
    "changed."
)
SUPERSEDE_ACCOUNT_DIFFERS = (
    "an obligation superseding another is on the same account. Nothing was changed."
)
PROPOSAL_NOT_FOUND = (
    "no such proposal for this account now. Run obligation proposals. Nothing was changed."
)
DISMISS_NOT_FOUND = (
    "no such proposal now: it may be dismissed already, reached by an obligation, or changed. "
    "Run obligation proposals. Nothing was changed."
)
DISMISSAL_NOT_FOUND = "dismissal not found. Run obligation dismissals. Nothing was changed."
DISMISSAL_NOT_ACTIVE = "this dismissal has already been undone. Nothing was changed."
OBLIGATION_REFUSALS = ChainRefusals(
    not_found="obligation not found. Run obligations. Nothing was changed.",
    not_active="this obligation has already been undone. Nothing was changed.",
    superseded=("this obligation is superseded by {newest}, the newest of its chain, which is "
                "the one to change or undo. Nothing was changed."),
)
TERMS_CLOSED_MONTH = (
    "--effective-from falls in a month before --as-of's, which is closed. Nothing was changed."
)
TERMS_NOT_LATER = (
    "--effective-from must be later than every terms row of this obligation, the latest from "
    "{latest}. Nothing was changed."
)
TERMS_CADENCE_PAIR = "--cadence and --anchor are given together or not at all. Nothing was changed."
STALE_OBLIGATION_PREVIEW = (
    "this revision does not match what the obligation would reach now. Nothing was changed. Run "
    "obligation preview with the same options and check it again."
)
STALE_OBLIGATION_REVISION = (
    "this revision does not match the obligation as it is now. Nothing was changed. Run "
    "obligation show and check it again."
)
STALE_DISMISS_REVISION = (
    "this revision does not match the proposal as it is now. Nothing was changed. Run "
    "obligation proposals and check it again."
)
STALE_DISMISSAL_REVISION = (
    "this revision does not match the dismissal as it is now. Nothing was changed. Run "
    "obligation dismissals and check it again."
)

@dataclass(frozen=True)
class ObligationRequest:
    """What a person typed for obligation preview and obligation add."""

    account_id: str
    name: str
    match: str
    category: str | None = None
    cadence: str | None = None
    anchor: str | None = None
    amount: str | None = None
    amount_range: str | None = None
    obligation_class: str | None = None
    tolerance_days: int = DEFAULT_TOLERANCE_DAYS
    from_proposal: str | None = None
    supersedes: str | None = None


@dataclass(frozen=True)
class CheckedObligation:
    obligation: RecurringObligation
    proposal: ObligationProposal | None
    superseded: RecurringObligation | None


@dataclass(frozen=True)
class ObligationAdded:
    obligation_id: str
    outlook: ObligationOutlook


def parsed_range(amount: str | None, amount_range: str | None) -> tuple[int, int]:
    """LOW and HIGH in cents from --amount, exact, or --range LOW..HIGH."""
    if (amount is None) == (amount_range is None):
        raise DecisionRefused(AMOUNT_OR_RANGE)
    if amount is not None:
        cents = parsed_amount(amount, AMOUNT_INVALID, least=1)
        return cents, cents
    low_text, separator, high_text = amount_range.partition("..")
    if not separator:
        raise DecisionRefused(RANGE_INVALID)
    low = parsed_amount(low_text, RANGE_INVALID, least=1)
    high = parsed_amount(high_text, RANGE_INVALID, least=1)
    if low > high:
        raise DecisionRefused(RANGE_INVALID)
    return low, high


def refuse_unless_class(obligation_class: str) -> str:
    if obligation_class not in CLASSES:
        raise DecisionRefused(CLASS_UNKNOWN)
    return obligation_class


def checked_terms(cadence_text: str, anchor_text: str, amount: str | None,
                  amount_range: str | None, obligation_class: str,
                  effective_from: str | None = None) -> ObligationTerms:
    stated = checked_cadence(cadence_text)
    anchor = parsed_date(anchor_text, "--anchor")
    when = date.fromisoformat(anchor)
    if not on_cadence(stated.cadence, when) or stated.month not in (None, when.month):
        raise DecisionRefused(ANCHOR_OFF_CADENCE)
    low, high = parsed_range(amount, amount_range)
    return ObligationTerms(effective_from or anchor, stated.cadence, anchor, low, high,
                           refuse_unless_class(obligation_class))


def category_id_named(conn: sqlite3.Connection, name: str | None) -> int | None:
    if name is None:
        return None
    row = conn.execute("SELECT id FROM category WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise DecisionRefused(CATEGORY_UNKNOWN)
    return row[0]


def checked_obligation(conn: sqlite3.Connection,
                       request: ObligationRequest) -> CheckedObligation:
    """An obligation as typed, refused for anything it gets wrong. Nothing is written."""
    obligations = load_obligations(conn)
    superseded = None
    terms_given = (request.cadence, request.anchor, request.amount, request.amount_range,
                   request.obligation_class)
    if request.supersedes is not None:
        superseded = find_newest(obligations, request.supersedes, OBLIGATION_REFUSALS)
        if superseded.definition.account_id != request.account_id:
            raise DecisionRefused(SUPERSEDE_ACCOUNT_DIFFERS)
        if terms_given != (None,) * 5:
            raise DecisionRefused(SUPERSEDE_TERMS_GIVEN)
    elif (None in (request.cadence, request.anchor, request.obligation_class)
          or (request.amount, request.amount_range) == (None, None)):
        raise DecisionRefused(TERMS_REQUIRED)
    if not request.name.strip():
        raise DecisionRefused(NAME_BLANK)
    if not normalized_text(request.match):
        raise DecisionRefused(TEXT_BLANK)
    category_id = category_id_named(conn, request.category)
    others = [obligation for obligation in obligations if obligation.undone_at is None
              and (superseded is None or obligation.chain_id != superseded.chain_id)]
    for other in others:
        if other.definition.name == request.name:
            raise DecisionRefused(NAME_TAKEN.format(obligation=other.obligation_id))
        if (other.applies and other.definition.account_id == request.account_id
                and normalized_text(other.definition.description_contains)
                == normalized_text(request.match)
                and other.definition.category_id == category_id):
            raise DecisionRefused(SAME_MATCHER.format(obligation=other.obligation_id))
    if not 0 <= request.tolerance_days <= LONGEST_TOLERANCE_DAYS:
        raise DecisionRefused(TOLERANCE_DAYS_RANGE)
    if superseded is None:
        terms = (checked_terms(request.cadence, request.anchor, request.amount,
                               request.amount_range, request.obligation_class),)
    else:
        terms = superseded.terms
    proposal = None
    if request.from_proposal is not None:
        proposal = find_proposal(conn, request.from_proposal, request.account_id)
        if proposal is None:
            raise DecisionRefused(PROPOSAL_NOT_FOUND)
    definition = ObligationDefinition(request.account_id, request.name, request.match,
                                      category_id, request.tolerance_days)
    chain_id = superseded.chain_id if superseded else "proposed"
    obligation = RecurringObligation("proposed", chain_id,
                                     superseded and superseded.obligation_id, definition, terms)
    return CheckedObligation(obligation, proposal, superseded)


def obligation_preview(conn: sqlite3.Connection, request: ObligationRequest) -> ObligationOutlook:
    checked = checked_obligation(conn, request)
    return preview_outlook(conn, checked.obligation, checked.proposal, checked.superseded)


def add_obligation(conn: sqlite3.Connection, request: ObligationRequest, revision: str,
                   rules: MatchingRules = DEFAULT_RULES) -> ObligationAdded:
    """Record an obligation, or one superseding another, whose preview is still current."""
    return in_one_write(conn, lambda: _add_obligation(conn, request, revision, rules))


def _add_obligation(conn, request, revision, rules) -> ObligationAdded:
    refuse_unless_current(conn, request.account_id, rules)
    checked = checked_obligation(conn, request)
    outlook = preview_outlook(conn, checked.obligation, checked.proposal, checked.superseded)
    refuse_unless_revision(outlook.revision, revision, STALE_OBLIGATION_PREVIEW)
    obligation_id = str(uuid.uuid4())
    definition = checked.obligation.definition
    superseded = checked.superseded
    conn.execute(
        """INSERT INTO recurring_obligation (id, account_id, name, description_contains,
                                             normalization_version, category_id, tolerance_days,
                                             supersedes_id, chain_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (obligation_id, definition.account_id, definition.name, definition.description_contains,
         definition.normalization_version, definition.category_id, definition.tolerance_days,
         superseded and superseded.obligation_id,
         superseded.chain_id if superseded else obligation_id),
    )
    if superseded is None:
        insert_terms(conn, obligation_id, checked.obligation.terms[0])
    conn.execute(
        "INSERT INTO recurring_obligation_event (obligation_id, event) VALUES (?, 'made')",
        (obligation_id,))
    write_obligation_effects(conn)
    return ObligationAdded(obligation_id, outlook)


def insert_terms(conn: sqlite3.Connection, chain_id: str, terms: ObligationTerms) -> None:
    cadence = terms.cadence
    conn.execute(
        """INSERT INTO recurring_obligation_terms (chain_id, effective_from, cadence, first_day,
                                                   second_day, interval_months, anchor,
                                                   low_cents, high_cents, obligation_class)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (chain_id, terms.effective_from, cadence.name, cadence.first_day, cadence.second_day,
         cadence.interval_months, terms.anchor, terms.low_cents, terms.high_cents,
         terms.obligation_class),
    )


@dataclass(frozen=True)
class TermsRequest:
    effective_from: str
    as_of: str
    amount: str | None = None
    amount_range: str | None = None
    cadence: str | None = None
    anchor: str | None = None
    obligation_class: str | None = None


def change_terms(conn: sqlite3.Connection, obligation_id: str, request: TermsRequest,
                 revision: str, rules: MatchingRules = DEFAULT_RULES) -> ObligationTerms:
    """Add a terms row taking over from effective_from, which falls in no closed month. What is
    not given keeps the latest row's value."""
    return in_one_write(conn, lambda: _change_terms(conn, obligation_id, request, revision,
                                                    rules))


def _change_terms(conn, obligation_id, request, revision, rules) -> ObligationTerms:
    obligations = load_obligations(conn)
    obligation = lookup_entry(obligations, obligation_id, OBLIGATION_REFUSALS)
    refuse_unless_current(conn, obligation.definition.account_id, rules)
    refuse_unless_newest(obligations, obligation, OBLIGATION_REFUSALS)
    effective_from = parsed_date(request.effective_from, "--effective-from")
    as_of = parsed_date(request.as_of, "--as-of")
    refuse_if_closed_month(effective_from, as_of, TERMS_CLOSED_MONTH)
    latest = obligation.terms[-1]
    if effective_from <= latest.effective_from:
        raise DecisionRefused(TERMS_NOT_LATER.format(latest=latest.effective_from))
    if (request.cadence is None) != (request.anchor is None):
        raise DecisionRefused(TERMS_CADENCE_PAIR)
    low, high = parsed_range(request.amount, request.amount_range)
    obligation_class = refuse_unless_class(request.obligation_class or latest.obligation_class)
    if request.cadence is None:
        terms = ObligationTerms(effective_from, latest.cadence, latest.anchor, low, high,
                                obligation_class)
    else:
        terms = checked_terms(request.cadence, request.anchor, request.amount,
                              request.amount_range, obligation_class, effective_from)
    refuse_unless_revision(obligation_outlook(conn, obligation, TERMS).revision, revision,
                           STALE_OBLIGATION_REVISION)
    insert_terms(conn, obligation.chain_id, terms)
    write_obligation_effects(conn)
    return terms


def undo_obligation(conn: sqlite3.Connection, obligation_id: str, revision: str,
                    rules: MatchingRules = DEFAULT_RULES) -> RecurringObligation:
    """Stop the newest obligation of a chain applying, keeping it on record. The one it
    superseded, if any, applies again (G4). Never refused for contradiction."""
    return in_one_write(conn, lambda: _undo_obligation(conn, obligation_id, revision, rules))


def _undo_obligation(conn, obligation_id, revision, rules) -> RecurringObligation:
    obligations = load_obligations(conn)
    obligation = lookup_entry(obligations, obligation_id, OBLIGATION_REFUSALS)
    refuse_unless_current(conn, obligation.definition.account_id, rules)
    refuse_unless_newest(obligations, obligation, OBLIGATION_REFUSALS)
    refuse_unless_revision(obligation_outlook(conn, obligation, UNDO).revision, revision,
                           STALE_OBLIGATION_REVISION)
    conn.execute(
        "INSERT INTO recurring_obligation_event (obligation_id, event) VALUES (?, 'undone')",
        (obligation_id,))
    write_obligation_effects(conn)
    return obligation


def dismiss_proposal(conn: sqlite3.Connection, proposal_key: str, revision: str,
                     rules: MatchingRules = DEFAULT_RULES) -> tuple[str, ObligationProposal]:
    """Withdraw a proposal shown now, by its key, until the dismissal is undone."""
    return in_one_write(conn, lambda: _dismiss_proposal(conn, proposal_key, revision, rules))


def _dismiss_proposal(conn, proposal_key, revision, rules):
    proposal = find_proposal(conn, proposal_key)
    if proposal is None:
        raise DecisionRefused(DISMISS_NOT_FOUND)
    refuse_unless_current(conn, proposal.account_id, rules)
    refuse_unless_revision(dismiss_revision(conn, proposal), revision, STALE_DISMISS_REVISION)
    dismissal_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO obligation_proposal_dismissal (id, account_id, proposal_key)
           VALUES (?, ?, ?)""", (dismissal_id, proposal.account_id, proposal.proposal_key))
    conn.execute(
        """INSERT INTO obligation_proposal_dismissal_event (dismissal_id, event)
           VALUES (?, 'made')""", (dismissal_id,))
    return dismissal_id, proposal


def find_dismissal(conn: sqlite3.Connection, dismissal_id: str) -> Dismissal:
    dismissal = next((dismissal for dismissal in load_dismissals(conn)
                      if dismissal.dismissal_id == dismissal_id), None)
    if dismissal is None:
        raise DecisionRefused(DISMISSAL_NOT_FOUND)
    return dismissal


def dismissal_revision(conn: sqlite3.Connection, dismissal: Dismissal) -> str:
    return undo_dismissal_revision(
        conn, dismissal, find_any_proposal(conn, dismissal.account_id, dismissal.proposal_key))


def undo_dismissal(conn: sqlite3.Connection, dismissal_id: str, revision: str,
                   rules: MatchingRules = DEFAULT_RULES) -> Dismissal:
    """Bring a dismissed proposal back, keeping the dismissal on record."""
    return in_one_write(conn, lambda: _undo_dismissal(conn, dismissal_id, revision, rules))


def _undo_dismissal(conn, dismissal_id, revision, rules) -> Dismissal:
    dismissal = find_dismissal(conn, dismissal_id)
    refuse_unless_current(conn, dismissal.account_id, rules)
    if dismissal.undone_at:
        raise DecisionRefused(DISMISSAL_NOT_ACTIVE)
    refuse_unless_revision(dismissal_revision(conn, dismissal), revision,
                           STALE_DISMISSAL_REVISION)
    conn.execute(
        """INSERT INTO obligation_proposal_dismissal_event (dismissal_id, event)
           VALUES (?, 'undone')""", (dismissal_id,))
    return dismissal
