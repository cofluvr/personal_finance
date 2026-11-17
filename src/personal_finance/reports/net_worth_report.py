"""pf report net-worth (D-071 points 1 to 3, M15.1): each account valued from its latest balance
observation, net worth with its incompleteness and mixed-date warnings, retirement and investment
history, and by member through M11's account attribution.

Read only. Observations, never transaction totals (PRD §17). Nothing here reads the clock.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from personal_finance.planning.net_worth import (
    NOT_VALUED,
    Valuation,
    mixed_dates,
    valuations,
)
from personal_finance.reconcile.household_effects import (
    UNATTRIBUTED,
    attribution_by_default,
    load_household,
)

HISTORY_TYPES = ("retirement", "investment")


@dataclass(frozen=True)
class AccountHistory:
    account_id: str
    name: str
    account_type: str
    # (date, cents) of each active observation on or before as_of, oldest first.
    observations: tuple[tuple[str, int], ...]
    # (month, cents, count) of applied investment contributions into it, by month.
    contributions: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class MemberPart:
    name: str
    cents: int


@dataclass(frozen=True)
class NetWorth:
    as_of: str
    valued: tuple[Valuation, ...]
    total_cents: int
    not_valued: tuple[str, ...]
    mixed_dates: tuple[str, ...]
    histories: tuple[AccountHistory, ...]
    # With a member asked for: every member's part, then the unattributed part, adding exactly to
    # total_cents, and the member asked for.
    member: str | None = None
    parts: tuple[MemberPart, ...] = ()


def observation_history(conn: sqlite3.Connection, account_id: str, as_of: str):
    return tuple(conn.execute(
        """SELECT observation.observed_on, observation.balance_cents
           FROM balance_observation observation
           WHERE observation.account_id = ? AND observation.observed_on <= ?
             AND NOT EXISTS (SELECT 1 FROM balance_observation_event undone
                             WHERE undone.balance_observation_id = observation.id
                               AND undone.event = 'undone')
           ORDER BY observation.observed_on, observation.created_at""", (account_id, as_of)))


def contributions_into(conn: sqlite3.Connection, account_id: str, as_of: str):
    """Applied investment_contribution transfers into the account dated by as_of, by month of the
    money out: matches whose inflow is in the account, and one-sided transfers naming it."""
    found = defaultdict(lambda: [0, 0])
    for day, cents in conn.execute(
        """SELECT COALESCE(outflow.transaction_date, outflow.posting_date),
                  -COALESCE(fix.corrected_amount_cents, outflow.amount_cents)
           FROM ledger_transaction outflow
           JOIN transaction_classification kind
               ON kind.transaction_id = outflow.id AND kind.state = 'applied'
              AND kind.financial_type = 'investment_contribution'
           LEFT JOIN transaction_correction fix
               ON fix.transaction_id = outflow.id AND fix.field = 'amount' AND fix.state = 'applied'
           WHERE outflow.id IN (
               SELECT matched.outflow_transaction_id FROM transfer_match_effect matched
               JOIN ledger_transaction inflow ON inflow.id = matched.inflow_transaction_id
               WHERE inflow.account_id = :account
               UNION
               SELECT effect.transaction_id FROM one_sided_transfer_effect effect
               JOIN one_sided_transfer statement ON statement.id = effect.one_sided_transfer_id
               WHERE statement.counterpart_account_id = :account)""",
            {"account": account_id}):
        if day is not None and day <= as_of:
            found[day[:7]][0] += cents
            found[day[:7]][1] += 1
    return tuple((month, cents, count) for month, (cents, count) in sorted(found.items()))


def member_parts(conn: sqlite3.Connection, valued, member_name: str) -> tuple[MemberPart, ...]:
    """Each counted valuation divided by its account's attribution (point 3), shared by the
    share through allocate_cents: every member in order, then unattributed."""
    household = load_household(conn)
    if household.find_member(member_name) is None:
        raise LookupError(member_name)
    by_member = {member.member_id: 0 for member in household.members}
    unattributed = 0
    for valuation in valued:
        # An account not counted gives 0.00 (counted_cents), so no part.
        attribution = attribution_by_default(household, valuation.account_id,
                                             valuation.counted_cents)
        if attribution.kind == UNATTRIBUTED:
            unattributed += valuation.counted_cents
            continue
        for member_id, cents in attribution.parts:
            by_member[member_id] += cents
    return (*(MemberPart(household.name_of(member_id), cents)
              for member_id, cents in by_member.items()),
            MemberPart(UNATTRIBUTED, unattributed))


def net_worth(conn: sqlite3.Connection, as_of: str, member_name: str | None = None) -> NetWorth:
    valued = valuations(conn, as_of)
    histories = tuple(
        AccountHistory(valuation.account_id, valuation.name, valuation.account_type,
                       observation_history(conn, valuation.account_id, as_of),
                       contributions_into(conn, valuation.account_id, as_of))
        for valuation in valued if valuation.account_type in HISTORY_TYPES)
    parts = () if member_name is None else member_parts(conn, valued, member_name)
    return NetWorth(as_of, valued, sum(valuation.counted_cents for valuation in valued),
                    tuple(valuation.name for valuation in valued if valuation.how == NOT_VALUED),
                    mixed_dates(valued, as_of), histories, member_name, parts)
