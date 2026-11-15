"""Income sources proposed from history, for a person to confirm. See decisions-m12-m21.md D-068
point 4 and its M12.1 slice plan.

Deterministic and never stored. Deposits in D-056's income group are grouped by account and
normalized description. A group is proposed when it has enough deposits, its dates fit one cadence
pay date by pay date from its first, each within the default tolerance, and its amounts lie within
a 10% band. A group any applying source reaches is withdrawn.
"""

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from personal_finance.planning.income_effects import (
    Cadence,
    DepositFacts,
    IncomeSource,
    SourceDefinition,
    Terms,
    load_deposit_facts,
    nominal_dates,
)

DEFAULT_TOLERANCE_DAYS = 3
# Point 4: at least 3 deposits, or 2 for the quarterly and annual cadences.
FEWEST_DEPOSITS = {"weekly": 3, "biweekly": 3, "semimonthly": 3, "monthly": 3, "quarterly": 2,
                   "annual": 2}
# The suggested amount is the median of the latest deposits, at most this many.
SUGGESTED_FROM = 6
# A source that is never stored, to generate a cadence's dates with.
PROBE_DEFINITION = SourceDefinition("probe", "probe", "side", "probe", DEFAULT_TOLERANCE_DAYS, 0,
                                    None, False)


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


def cadence_spec(cadence: Cadence, anchor: str) -> str:
    """The cadence as income add takes it."""
    if cadence.name == "semimonthly":
        return f"semimonthly:{cadence.first_day},{cadence.second_day}"
    if cadence.name in ("monthly", "quarterly"):
        return f"{cadence.name}:{cadence.first_day}"
    if cadence.name == "annual":
        return f"annual:{anchor[5:7]}-{cadence.first_day:02d}"
    if cadence.name == "every_months":
        return f"every:{cadence.interval_months}-months:{cadence.first_day}"
    return cadence.name


def proposal_key(account_id: str, normalized: str, spec: str) -> str:
    """Stable across imports: the account, the normalized text and the cadence."""
    text = json.dumps([account_id, normalized, spec], separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def most_common_days(days, count: int) -> list[int]:
    """The count days of the month seen most often, ties to the earlier day, ascending."""
    ranked = sorted(Counter(days).items(), key=lambda pair: (-pair[1], pair[0]))
    return sorted(day for day, _ in ranked[:count])


def candidate_cadences(dates: list[date]) -> list[tuple[Cadence, date]]:
    """Each cadence worth trying, in a fixed order, with the anchor it would start at."""
    first = dates[0]
    days = [when.day for when in dates]
    found = [(Cadence("weekly"), first), (Cadence("biweekly"), first)]
    pair = most_common_days(days, 2)
    if len(pair) == 2:
        found.append((Cadence("semimonthly", pair[0], pair[1]), None))
    (day,) = most_common_days(days, 1)
    for name in ("monthly", "quarterly", "annual"):
        found.append((Cadence(name, day), None))
    return found


def probe_source(cadence: Cadence, start: date, anchor: date) -> IncomeSource:
    """A cadence's dates from start on, fixed by anchor."""
    return IncomeSource("probe", "probe", None, PROBE_DEFINITION,
                        (Terms(start.isoformat(), cadence, anchor.isoformat(), 1),))


def fitted(dates: list[date], cadence: Cadence, anchor: date | None) -> date | None:
    """The anchor at which the i-th deposit falls within the tolerance of the i-th nominal date
    for every i, or None. A month-based cadence starts at its nominal date nearest the first
    deposit."""
    tolerance = timedelta(days=DEFAULT_TOLERANCE_DAYS)
    if anchor is None:
        probe = probe_source(cadence, dates[0] - timedelta(days=40), dates[0])
        nearby = [nominal for nominal, _ in nominal_dates(probe, dates[0] + tolerance)
                  if nominal >= dates[0] - tolerance]
        if not nearby:
            return None
        anchor = min(nearby, key=lambda nominal: (abs((nominal - dates[0]).days), nominal))
    source = probe_source(cadence, anchor, anchor)
    expected = [nominal for nominal, _ in nominal_dates(source, dates[-1] + tolerance)]
    if len(expected) != len(dates):
        return None
    if any(abs((when - nominal).days) > DEFAULT_TOLERANCE_DAYS
           for when, nominal in zip(dates, expected)):
        return None
    return anchor



def median_half_down(amounts: list[int]) -> int:
    ordered = sorted(amounts)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def proposal_for(account_id: str, normalized: str, deposits) -> IncomeProposal | None:
    deposits = sorted(deposits, key=lambda facts: (facts.reporting_date, facts.transaction_id))
    amounts = [facts.amount_cents for facts in deposits]
    if max(amounts) * 100 > min(amounts) * 110:
        return None
    dates = [date.fromisoformat(facts.reporting_date) for facts in deposits]
    for cadence, anchor in candidate_cadences(dates):
        if len(deposits) < FEWEST_DEPOSITS[cadence.name]:
            continue
        start = fitted(dates, cadence, anchor)
        if start is None:
            continue
        upcoming = nominal_dates(probe_source(cadence, start, start),
                                 dates[-1] + timedelta(days=400))[len(dates)][0]
        spec = cadence_spec(cadence, start.isoformat())
        return IncomeProposal(
            proposal_key(account_id, normalized, spec), account_id, normalized, cadence,
            start.isoformat(), deposits[-1].reporting_date, upcoming.isoformat(),
            median_half_down(amounts[-SUGGESTED_FROM:]), min(amounts), max(amounts),
            tuple(deposits))
    return None


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
