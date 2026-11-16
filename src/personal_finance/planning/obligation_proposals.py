"""Recurring obligations proposed from history, for a person to confirm or dismiss. See
decisions-m12-m21.md D-068 points 4 and 5, and "How M12.2 was implemented".

Deterministic and never stored. Money out in D-056's spending group is grouped by account and
normalized description. A group is proposed when it has enough payments, its dates fit one cadence
due date by due date from its first, each within the default tolerance, and its amounts lie
within a 10% band. A group any applying obligation reaches is withdrawn, and so is one whose key a
person dismissed, until the dismissal is undone.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from personal_finance.planning.obligation_effects import PaymentFacts, load_payment_facts
from personal_finance.planning.schedules import (
    SUGGESTED_FROM,
    Cadence,
    cadence_spec,
    fitted_cadence,
    median_half_down,
    proposal_key,
    within_band,
)


@dataclass(frozen=True)
class ObligationProposal:
    proposal_key: str
    account_id: str
    normalized_text: str
    cadence: Cadence
    # The nominal due date the earliest payment pairs with.
    anchor: str
    last_seen: str
    next_expected: str
    # Amounts paid, as positive cents.
    suggested_amount_cents: int
    lowest_cents: int
    highest_cents: int
    payments: tuple[PaymentFacts, ...]

    @property
    def exact(self) -> bool:
        return self.lowest_cents == self.highest_cents


@dataclass(frozen=True)
class Dismissal:
    dismissal_id: str
    account_id: str
    proposal_key: str
    created_at: str
    undone_at: str | None

    @property
    def state(self) -> str:
        return "undone" if self.undone_at else "active"


def proposal_for(account_id: str, normalized: str, payments) -> ObligationProposal | None:
    payments = sorted(payments, key=lambda facts: (facts.reporting_date, facts.transaction_id))
    amounts = [facts.paid_cents for facts in payments]
    if not within_band(amounts):
        return None
    fit = fitted_cadence([date.fromisoformat(facts.reporting_date) for facts in payments])
    if fit is None:
        return None
    spec = cadence_spec(fit.cadence, fit.anchor)
    return ObligationProposal(
        proposal_key(account_id, normalized, spec), account_id, normalized, fit.cadence,
        fit.anchor, payments[-1].reporting_date, fit.next_expected,
        median_half_down(amounts[-SUGGESTED_FROM:]), min(amounts), max(amounts),
        tuple(payments))


def load_dismissals(conn: sqlite3.Connection) -> tuple[Dismissal, ...]:
    """Every dismissal on record, in the order made."""
    return tuple(Dismissal(*row) for row in conn.execute(
        """SELECT dismissal.id, dismissal.account_id, dismissal.proposal_key,
                  dismissal.created_at, undone.created_at
           FROM obligation_proposal_dismissal dismissal
           LEFT JOIN obligation_proposal_dismissal_event undone
               ON undone.dismissal_id = dismissal.id AND undone.event = 'undone'
           ORDER BY dismissal.created_at, dismissal.id"""))


def every_proposal(conn: sqlite3.Connection,
                   account_id: str | None = None) -> tuple[ObligationProposal, ...]:
    """Every group of the ledger, or of one account, that fits a cadence and that no applying
    obligation reaches, by account and text, dismissed or not."""
    if account_id is None:
        account_ids = [row[0] for row in conn.execute("SELECT id FROM account")]
    else:
        account_ids = [account_id]
    reached = {row[0] for row in conn.execute(
        "SELECT transaction_id FROM transaction_obligation")}
    groups = defaultdict(list)
    for facts in load_payment_facts(conn, account_ids):
        if facts.normalized_description:
            groups[(facts.account_id, facts.normalized_description)].append(facts)
    proposals = []
    for (group_account, normalized), payments in sorted(groups.items()):
        if any(facts.transaction_id in reached for facts in payments):
            continue
        proposal = proposal_for(group_account, normalized, payments)
        if proposal is not None:
            proposals.append(proposal)
    return tuple(proposals)


def obligation_proposals(conn: sqlite3.Connection,
                         account_id: str | None = None) -> tuple[ObligationProposal, ...]:
    """Every proposal of the ledger, or of one account, less those dismissed now."""
    dismissed = {(dismissal.account_id, dismissal.proposal_key)
                 for dismissal in load_dismissals(conn) if dismissal.undone_at is None}
    return tuple(proposal for proposal in every_proposal(conn, account_id)
                 if (proposal.account_id, proposal.proposal_key) not in dismissed)


def find_proposal(conn: sqlite3.Connection, key: str,
                  account_id: str | None = None) -> ObligationProposal | None:
    """The proposal with this key now, not dismissed."""
    return next((proposal for proposal in obligation_proposals(conn, account_id)
                 if proposal.proposal_key == key), None)


def find_any_proposal(conn: sqlite3.Connection, account_id: str,
                      key: str) -> ObligationProposal | None:
    """The proposal with this key on an account now, dismissed or not."""
    return next((proposal for proposal in every_proposal(conn, account_id)
                 if proposal.proposal_key == key), None)
