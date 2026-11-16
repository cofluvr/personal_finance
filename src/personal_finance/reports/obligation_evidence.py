"""What an obligation would reach, what one reaches now, and its ob1 token (D-068 point 7, and
"How M12.2 was implemented"). Also the ob1 tokens of a proposal's dismissal and its undo.

Everything here reads the ledger and nothing writes to it. A token covers the operation, the
obligation's definition and terms by what they say, names standing for IDs, and every payment it
reaches with its state and class, by record keys. Nothing it covers depends on today.
"""

import sqlite3
from dataclasses import dataclass, replace

from personal_finance.planning.obligation_effects import (
    OBLIGATION_CONFLICT,
    PaymentFacts,
    PaymentOutcome,
    RecurringObligation,
    applying_obligations,
    load_payment_facts,
    matches,
    obligation_outcomes,
)
from personal_finance.planning.obligation_proposals import Dismissal, ObligationProposal
from personal_finance.planning.schedules import cadence_spec
from personal_finance.reports.category_rule_evidence import digest, record_keys

# Bump whenever the material below changes, so an old token can never appear current.
OBLIGATION_REVISION_VERSION = 1

PROPOSED_OBLIGATION_ID = "proposed"

ADD = "add"
SUPERSEDE = "supersede"
TERMS = "terms"
UNDO = "undo"
DISMISS = "dismiss"
UNDO_DISMISSAL = "undo_dismissal"


@dataclass(frozen=True)
class ObligationOutlook:
    revision: str
    # The obligation's outcome on every payment it reaches, oldest first.
    reached: tuple[PaymentOutcome, ...]
    # Every payment of the account, by transaction ID.
    facts: dict[str, PaymentFacts]
    # Applying obligations that reach a payment in obligation_conflict here, by transaction ID.
    conflicting: dict[str, tuple[str, ...]]
    # Spending its account, text and category match, dated before its first due date less the
    # tolerance.
    before_first_due_date: tuple[PaymentFacts, ...]


def category_name(conn: sqlite3.Connection, category_id: int | None) -> str | None:
    if category_id is None:
        return None
    return conn.execute("SELECT name FROM category WHERE id = ?", (category_id,)).fetchone()[0]


def obligation_material(conn: sqlite3.Connection, obligation: RecurringObligation) -> dict:
    """An obligation by what it says, names standing for IDs."""
    definition = obligation.definition
    account = conn.execute("SELECT display_name FROM account WHERE id = ?",
                           (definition.account_id,)).fetchone()
    return {
        "account": account and account[0],
        "name": definition.name,
        "description_contains": definition.description_contains,
        "normalization_version": definition.normalization_version,
        "category": category_name(conn, definition.category_id),
        "tolerance_days": definition.tolerance_days,
        "terms": [[terms.effective_from, cadence_spec(terms.cadence, terms.anchor), terms.anchor,
                   terms.low_cents, terms.high_cents, terms.obligation_class]
                  for terms in obligation.terms],
    }


def proposal_material(conn: sqlite3.Connection, proposal: ObligationProposal) -> dict:
    keys = record_keys(conn, [facts.transaction_id for facts in proposal.payments])
    account = conn.execute("SELECT display_name FROM account WHERE id = ?",
                           (proposal.account_id,)).fetchone()
    return {
        "key": proposal.proposal_key,
        "account": account and account[0],
        "normalized_text": proposal.normalized_text,
        "cadence": cadence_spec(proposal.cadence, proposal.anchor),
        "anchor": proposal.anchor,
        "last_seen": proposal.last_seen,
        "next_expected": proposal.next_expected,
        "suggested_amount_cents": proposal.suggested_amount_cents,
        "range": [proposal.lowest_cents, proposal.highest_cents],
        "payments": sorted([keys[facts.transaction_id], facts.reporting_date, facts.amount_cents]
                           for facts in proposal.payments),
    }


def revision_of(material: dict) -> str:
    return f"ob{OBLIGATION_REVISION_VERSION}-{digest(material)}"


def _outlook(conn, obligations, obligation, material, operation) -> ObligationOutlook:
    facts_list = load_payment_facts(conn, {obligation.definition.account_id})
    by_id = {facts.transaction_id: facts for facts in facts_list}
    outcomes = obligation_outcomes(obligations, facts_list)
    reached = tuple(sorted(
        (outcome for (_, obligation_id), outcome in outcomes.items()
         if obligation_id == obligation.obligation_id),
        key=lambda outcome: (by_id[outcome.transaction_id].reporting_date,
                             outcome.transaction_id)))
    conflicting = {}
    for outcome in reached:
        if outcome.state == OBLIGATION_CONFLICT:
            conflicting[outcome.transaction_id] = tuple(sorted(
                obligation_id for (transaction_id, obligation_id) in outcomes
                if transaction_id == outcome.transaction_id
                and obligation_id != obligation.obligation_id))
    keys = record_keys(conn, [outcome.transaction_id for outcome in reached])
    material["operation"] = operation
    material["reached"] = sorted([keys[outcome.transaction_id], outcome.state,
                                  outcome.nominal_date, outcome.obligation_class]
                                 for outcome in reached)
    reached_ids = {outcome.transaction_id for outcome in reached}
    return ObligationOutlook(
        revision_of(material), reached, by_id, conflicting,
        tuple(facts for facts in facts_list if matches(obligation, facts)
              and facts.transaction_id not in reached_ids))


def preview_outlook(conn: sqlite3.Connection, proposed: RecurringObligation,
                    proposal: ObligationProposal | None = None,
                    superseded: RecurringObligation | None = None) -> ObligationOutlook:
    """What adding an obligation, or one superseding another, would reach, and its ob1 token.
    With a proposal, the token covers its whole content too."""
    proposed = replace(proposed, obligation_id=PROPOSED_OBLIGATION_ID)
    others = [obligation for obligation in applying_obligations(conn)
              if superseded is None or obligation.obligation_id != superseded.obligation_id]
    material = {"obligation": obligation_material(conn, proposed)}
    if proposal is not None:
        material["proposal"] = proposal_material(conn, proposal)
    if superseded is not None:
        material["supersedes"] = obligation_outlook(conn, superseded, SUPERSEDE).revision
    return _outlook(conn, (*others, proposed), proposed, material,
                    SUPERSEDE if superseded is not None else ADD)


def obligation_outlook(conn: sqlite3.Connection, obligation: RecurringObligation,
                       operation: str) -> ObligationOutlook:
    """What an applying obligation reaches now, and the ob1 token for one operation on it."""
    return _outlook(conn, applying_obligations(conn), obligation,
                    {"obligation": obligation_material(conn, obligation),
                     "obligation_id": obligation.obligation_id},
                    operation)


def dismiss_revision(conn: sqlite3.Connection, proposal: ObligationProposal) -> str:
    """The ob1 token for dismissing a proposal: its key and its whole group (point 7)."""
    return revision_of({"operation": DISMISS, "proposal": proposal_material(conn, proposal)})


def undo_dismissal_revision(conn: sqlite3.Connection, dismissal: Dismissal,
                            proposal: ObligationProposal | None) -> str:
    """The ob1 token for undoing a dismissal: the dismissal, and the proposal it would bring back
    now, if its group still fits a cadence."""
    account = conn.execute("SELECT display_name FROM account WHERE id = ?",
                           (dismissal.account_id,)).fetchone()
    return revision_of({
        "operation": UNDO_DISMISSAL, "dismissal_id": dismissal.dismissal_id,
        "account": account and account[0], "key": dismissal.proposal_key,
        "proposal": proposal and proposal_material(conn, proposal)})
