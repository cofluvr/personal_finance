"""What an income source would reach, what one reaches now, and its in1 token (D-068 point 7, and
its M12.1 slice plan).

Everything here reads the ledger and nothing writes to it. A token covers the operation, the
source's definition and terms by what they say, names standing for IDs, and every deposit the
source reaches with its state, by record keys. Nothing it covers depends on today.
"""

import sqlite3
from dataclasses import dataclass, replace

from personal_finance.planning.income_effects import (
    DepositFacts,
    DepositOutcome,
    IncomeSource,
    applying_sources,
    load_deposit_facts,
    matches,
    reaches,
    source_outcomes,
)
from personal_finance.planning.income_proposals import IncomeProposal, cadence_spec
from personal_finance.reports.category_rule_evidence import digest, record_keys

# Bump whenever the material below changes, so an old token can never appear current.
INCOME_REVISION_VERSION = 1

# The ID a proposed source takes while it is previewed. Never stored.
PROPOSED_SOURCE_ID = "proposed"

ADD = "add"
SUPERSEDE = "supersede"
TERMS = "terms"
UNDO = "undo"


@dataclass(frozen=True)
class IncomeOutlook:
    revision: str
    # The source's outcome on every deposit it reaches, oldest first.
    reached: tuple[DepositOutcome, ...]
    # Every deposit of the outcomes and lists below, by transaction ID.
    facts: dict[str, DepositFacts]
    # Applying sources that reach a deposit in source_conflict here, by transaction ID.
    conflicting: dict[str, tuple[str, ...]]
    # Unclassified money in the source's text matches: never counted.
    possible_paychecks: tuple[DepositFacts, ...]
    # Income its text matches, dated before its first pay date less the tolerance.
    before_first_pay_date: tuple[DepositFacts, ...]


def source_material(conn: sqlite3.Connection, source: IncomeSource) -> dict:
    """A source by what it says, names standing for IDs."""
    definition = source.definition
    account = conn.execute("SELECT display_name FROM account WHERE id = ?",
                           (definition.account_id,)).fetchone()
    member = definition.member_id and conn.execute(
        "SELECT name FROM household_member WHERE id = ?", (definition.member_id,)).fetchone()
    return {
        "account": account and account[0],
        "name": definition.name,
        "kind": definition.kind,
        "description_contains": definition.description_contains,
        "normalization_version": definition.normalization_version,
        "tolerance_days": definition.tolerance_days,
        "amount_tolerance_cents": definition.amount_tolerance_cents,
        "member": member and member[0],
        "tax_eligible": definition.tax_eligible,
        "terms": [[terms.effective_from, cadence_spec(terms.cadence, terms.anchor), terms.anchor,
                   terms.amount_cents] for terms in source.terms],
    }


def proposal_material(conn: sqlite3.Connection, proposal: IncomeProposal) -> dict:
    keys = record_keys(conn, [facts.transaction_id for facts in proposal.deposits])
    return {
        "key": proposal.proposal_key,
        "normalized_text": proposal.normalized_text,
        "cadence": cadence_spec(proposal.cadence, proposal.anchor),
        "anchor": proposal.anchor,
        "last_seen": proposal.last_seen,
        "next_expected": proposal.next_expected,
        "suggested_amount_cents": proposal.suggested_amount_cents,
        "range": [proposal.lowest_cents, proposal.highest_cents],
        "deposits": sorted([keys[facts.transaction_id], facts.reporting_date, facts.amount_cents]
                           for facts in proposal.deposits),
    }


def _outlook(conn, sources, source, material, operation) -> IncomeOutlook:
    facts_list = load_deposit_facts(conn, {source.definition.account_id})
    by_id = {facts.transaction_id: facts for facts in facts_list}
    outcomes = source_outcomes(sources, facts_list)
    reached = tuple(sorted(
        (outcome for (_, source_id), outcome in outcomes.items()
         if source_id == source.source_id),
        key=lambda outcome: (by_id[outcome.transaction_id].reporting_date,
                             outcome.transaction_id)))
    conflicting = {}
    for outcome in reached:
        if outcome.state == "source_conflict":
            conflicting[outcome.transaction_id] = tuple(sorted(
                source_id for (transaction_id, source_id) in outcomes
                if transaction_id == outcome.transaction_id and source_id != source.source_id))
    keys = record_keys(conn, [outcome.transaction_id for outcome in reached])
    material["operation"] = operation
    material["reached"] = sorted([keys[outcome.transaction_id], outcome.state,
                                  outcome.nominal_date] for outcome in reached)
    return IncomeOutlook(
        f"in{INCOME_REVISION_VERSION}-{digest(material)}", reached, by_id,
        conflicting,
        tuple(facts for facts in facts_list if not facts.is_income and matches(source, facts)),
        tuple(facts for facts in facts_list if facts.is_income and matches(source, facts)
              and not reaches(source, facts)))


def preview_outlook(conn: sqlite3.Connection, proposed: IncomeSource,
                    proposal: IncomeProposal | None = None,
                    superseded: IncomeSource | None = None) -> IncomeOutlook:
    """What adding a source, or one superseding another, would reach, and its in1 token. With a
    proposal, the token covers its whole content too."""
    proposed = replace(proposed, source_id=PROPOSED_SOURCE_ID)
    others = [source for source in applying_sources(conn)
              if superseded is None or source.source_id != superseded.source_id]
    material = {"source": source_material(conn, proposed)}
    if proposal is not None:
        material["proposal"] = proposal_material(conn, proposal)
    if superseded is not None:
        material["supersedes"] = source_outlook(conn, superseded, SUPERSEDE).revision
    return _outlook(conn, (*others, proposed), proposed, material,
                    SUPERSEDE if superseded is not None else ADD)


def source_outlook(conn: sqlite3.Connection, source: IncomeSource,
                   operation: str) -> IncomeOutlook:
    """What an applying source reaches now, and the in1 token for one operation on it."""
    return _outlook(conn, applying_sources(conn), source,
                    {"source": source_material(conn, source), "source_id": source.source_id},
                    operation)
