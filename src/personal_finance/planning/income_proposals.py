"""Income sources proposed from history, for a person to confirm. See decisions-m12-m21.md D-068
point 4 and its M12.1 slice plan.

Deterministic and never stored. Deposits in D-056's income group are grouped by account and
normalized description. A group is proposed when it has enough deposits, its dates fit one cadence
pay date by pay date from its first, each within the default tolerance, and its amounts lie within
a 10% band. A group any applying source reaches is withdrawn.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from personal_finance.planning.income_effects import DepositFacts, load_deposit_facts
from personal_finance.planning.schedules import (  # noqa: F401, cadence_spec is income's too
    SUGGESTED_FROM,
    Cadence,
    cadence_spec,
    fitted_cadence,
    median_half_down,
    proposal_key,
    within_band,
)


@dataclass(frozen=True)
class IncomeProposal:
    proposal_key: str
    account_id: str
    normalized_text: str
    cadence: Cadence
    # The nominal pay date the earliest deposit pairs with (point J).
    anchor: str
    last_seen: str
    next_expected: str
    suggested_amount_cents: int
    lowest_cents: int
    highest_cents: int
    deposits: tuple[DepositFacts, ...]


def proposal_for(account_id: str, normalized: str, deposits) -> IncomeProposal | None:
    deposits = sorted(deposits, key=lambda facts: (facts.reporting_date, facts.transaction_id))
    amounts = [facts.amount_cents for facts in deposits]
    if not within_band(amounts):
        return None
    fit = fitted_cadence([date.fromisoformat(facts.reporting_date) for facts in deposits])
    if fit is None:
        return None
    spec = cadence_spec(fit.cadence, fit.anchor)
    return IncomeProposal(
        proposal_key(account_id, normalized, spec), account_id, normalized, fit.cadence,
        fit.anchor, deposits[-1].reporting_date, fit.next_expected,
        median_half_down(amounts[-SUGGESTED_FROM:]), min(amounts), max(amounts),
        tuple(deposits))


def income_proposals(conn: sqlite3.Connection,
                     account_id: str | None = None) -> tuple[IncomeProposal, ...]:
    """Every proposal of the ledger, or of one account, by account and text."""
    if account_id is None:
        account_ids = [row[0] for row in conn.execute("SELECT id FROM account")]
    else:
        account_ids = [account_id]
    reached = {row[0] for row in conn.execute(
        "SELECT transaction_id FROM transaction_income_source")}
    groups = defaultdict(list)
    for facts in load_deposit_facts(conn, account_ids):
        if facts.is_income and facts.normalized_description:
            groups[(facts.account_id, facts.normalized_description)].append(facts)
    proposals = []
    for (group_account, normalized), deposits in sorted(groups.items()):
        if any(facts.transaction_id in reached for facts in deposits):
            continue
        proposal = proposal_for(group_account, normalized, deposits)
        if proposal is not None:
            proposals.append(proposal)
    return tuple(proposals)


def find_proposal(conn: sqlite3.Connection, account_id: str,
                  key: str) -> IncomeProposal | None:
    return next((proposal for proposal in income_proposals(conn, account_id)
                 if proposal.proposal_key == key), None)
