"""Household members, the household share, each account's attribution, and what they make of each
transaction's effective amount. See decisions.md D-065.

Nothing here writes. A person's allocation on the transaction comes first, as its derived outcome
gives it, then the account's default, else unattributed (point 3). The share and the account
defaults bind no records and are resolved when read, so no write rewrites a row per transaction.
Amounts are integer cents and weights integer basis points: no floating point anywhere (D-003).
"""

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from personal_finance.db.id_lists import ids_as_json_array

# What an attribution is besides a member. Never stored as a member, so no member takes either name.
SHARED = "shared"
UNATTRIBUTED = "unattributed"
RESERVED_MEMBER_NAMES = (SHARED, UNATTRIBUTED)

# The kinds of attribution: one member's whole amount, the share's parts, or parts a person typed.
PERSONAL = "personal"
ALLOCATED = "allocated"

# The kinds of allocation a person states, as stored before the colon of its canonical value.
BY_MEMBER = "member"
BY_SHARE = "shared"
BY_PERCENT = "percent"
BY_AMOUNT = "amount"

# Weights sum to exactly this: 100.00 percent.
WHOLE_IN_BASIS_POINTS = 10_000

# Why a transaction is unattributed while no person's statement reaches it.
NO_DEFAULT = "no_default"
NO_SHARE = "no_share"

# A percentage as typed: up to three digits, then at most two decimals.
_PERCENT = re.compile(r"(?P<whole>[0-9]{1,3})(?:\.(?P<fraction>[0-9]{1,2}))?")


def allocate_cents(amount_cents: int, basis_points: Sequence[int]) -> tuple[int, ...]:
    """Divide an amount by weights summing to 10,000, given in member order, by largest remainder.

    Each part takes floor(M × w / 10,000) of the magnitude M, then the cents left over, fewer than
    the parts, go one each to the largest remainders (M × w mod 10,000), ties to the earlier
    member. The sign is applied after, so a negated amount gives exactly the negated parts. The
    parts sum to the amount exactly, and each is within one cent of its exact share.
    """
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise TypeError("amounts must be integer cents")
    weights = tuple(basis_points)
    if not weights or any(isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0
                          for weight in weights):
        raise ValueError("weights must be integer basis points above zero")
    if sum(weights) != WHOLE_IN_BASIS_POINTS:
        raise ValueError("weights must sum to exactly 10000 basis points")
    magnitude = abs(amount_cents)
    parts = [magnitude * weight // WHOLE_IN_BASIS_POINTS for weight in weights]
    left_over = magnitude - sum(parts)
    by_remainder = sorted(range(len(weights)),
                          key=lambda index: (-(magnitude * weights[index] % WHOLE_IN_BASIS_POINTS),
                                             index))
    for index in by_remainder[:left_over]:
        parts[index] += 1
    return tuple(-part for part in parts) if amount_cents < 0 else tuple(parts)


def parse_percent(text: str) -> int | None:
    """A percentage typed with at most two decimals, as basis points, or None if it is not one."""
    match = _PERCENT.fullmatch(text)
    if match is None:
        return None
    return int(match["whole"]) * 100 + int((match["fraction"] or "0").ljust(2, "0"))


def format_percent(basis_points: int) -> str:
    whole, fraction = divmod(basis_points, 100)
    return f"{whole}.{fraction:02d}%"


@dataclass(frozen=True)
class Member:
    member_id: int
    name: str


@dataclass(frozen=True)
class Share:
    share_id: str
    # (member ID, basis points), in member order.
    parts: tuple[tuple[int, int], ...]
    created_at: str


@dataclass(frozen=True)
class AccountDefault:
    attribution_id: str
    account_id: str
    # None for shared.
    member_id: int | None
    created_at: str


@dataclass(frozen=True)
class Household:
    """Members in the order added, the active share and the active default of each account."""

    members: tuple[Member, ...]
    share: Share | None
    defaults: dict[str, AccountDefault]

    def name_of(self, member_id: int) -> str:
        return next(member.name for member in self.members if member.member_id == member_id)

    def find_member(self, name: str) -> Member | None:
        return next((member for member in self.members if member.name == name), None)


@dataclass(frozen=True)
class Attribution:
    """Who one transaction's effective amount belongs to."""

    # personal, shared, allocated or unattributed.
    kind: str
    # (member ID, cents) in member order, summing to the effective amount. Empty when unattributed.
    parts: tuple[tuple[int, int], ...]
    # Why it is unattributed: no_default, no_share, or the state of allocations that do not apply.
    # Else None.
    reason: str | None
    # Whether a person's allocation on the transaction decides it, rather than the account's
    # default.
    by_allocation: bool = False


def canonical(kind: str, parts) -> str:
    """An allocation's value: its kind, then (member ID, value) parts sorted by member ID, so two
    allocations agree exactly when their values are equal."""
    return f"{kind}:" + ",".join(f"{member_id}={value}" for member_id, value in sorted(parts))


def parsed(value: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """An allocation's kind and its (member ID, value) parts, in member order."""
    kind, _, parts = value.partition(":")
    return kind, tuple(
        (int(member_id), int(part_value))
        for member_id, _, part_value in (part.partition("=") for part in parts.split(",") if part)
    )


def named_value(names: dict[int, str], value: str) -> list:
    """An allocation's kind and parts by member name, in member order, for tokens and output."""
    kind, parts = parsed(value)
    return [kind, [[names[member_id], part] for member_id, part in parts]]


def load_household(conn: sqlite3.Connection) -> Household:
    members = tuple(Member(*row) for row in conn.execute(
        "SELECT id, name FROM household_member ORDER BY id"))
    return Household(members, load_active_share(conn), load_active_defaults(conn))


def load_active_share(conn: sqlite3.Connection) -> Share | None:
    row = conn.execute(
        """SELECT share.id, share.created_at FROM household_share share
           JOIN household_share_event made ON made.share_id = share.id AND made.event = 'made'
           WHERE NOT EXISTS (SELECT 1 FROM household_share_event undone
                             WHERE undone.share_id = share.id AND undone.event = 'undone')"""
    ).fetchone()
    if row is None:
        return None
    share_id, created_at = row
    parts = tuple(conn.execute(
        """SELECT member_id, basis_points FROM household_share_part
           WHERE share_id = ? ORDER BY member_id""", (share_id,)))
    return Share(share_id, parts, created_at)


def load_active_defaults(conn: sqlite3.Connection) -> dict[str, AccountDefault]:
    return {
        row[1]: AccountDefault(*row)
        for row in conn.execute(
            """SELECT attribution.id, attribution.account_id, attribution.member_id,
                      attribution.created_at
               FROM account_attribution attribution
               JOIN account_attribution_event made
                   ON made.attribution_id = attribution.id AND made.event = 'made'
               WHERE NOT EXISTS (SELECT 1 FROM account_attribution_event undone
                                 WHERE undone.attribution_id = attribution.id
                                   AND undone.event = 'undone')""")
    }


def attribution_by_default(household: Household, account_id: str,
                           amount_cents: int) -> Attribution:
    """What the account's default makes of an effective amount, unattributed by reason where it
    reaches nothing."""
    default = household.defaults.get(account_id)
    if default is None:
        return Attribution(UNATTRIBUTED, (), NO_DEFAULT)
    if default.member_id is not None:
        return Attribution(PERSONAL, ((default.member_id, amount_cents),), None)
    return attribution_by_share(household.share, amount_cents)


def attribution_by_share(share: Share | None, amount_cents: int,
                         by_allocation: bool = False) -> Attribution:
    if share is None:
        return Attribution(UNATTRIBUTED, (), NO_SHARE, by_allocation)
    member_ids = [member_id for member_id, _ in share.parts]
    cents = allocate_cents(amount_cents, [weight for _, weight in share.parts])
    return Attribution(SHARED, tuple(zip(member_ids, cents)), None, by_allocation)


def attribution_by_allocation(household: Household, value: str, amount_cents: int) -> Attribution:
    """What an applied allocation makes of an effective amount. Parts by amount are magnitudes,
    signed by the transaction's direction, and sum to it, or the allocation would not apply."""
    kind, parts = parsed(value)
    if kind == BY_SHARE:
        return attribution_by_share(household.share, amount_cents, by_allocation=True)
    if kind == BY_MEMBER:
        ((member_id, _),) = parts
        return Attribution(PERSONAL, ((member_id, amount_cents),), None, True)
    member_ids = [member_id for member_id, _ in parts]
    if kind == BY_PERCENT:
        cents = allocate_cents(amount_cents, [weight for _, weight in parts])
    else:
        cents = tuple(-part if amount_cents < 0 else part for _, part in parts)
    return Attribution(ALLOCATED, tuple(zip(member_ids, cents)), None, True)


@dataclass(frozen=True)
class AttributedTransaction:
    transaction_id: str
    account_id: str
    # Corrected where a correction applies, else the source value (D-049).
    amount_cents: int
    attribution: Attribution


def effective_amounts(conn: sqlite3.Connection, account_id: str | None = None,
                      transaction_ids=None) -> list[tuple[str, str, int]]:
    """Each transaction's ID, account and effective amount, in ID order, for the ledger, one
    account or the IDs given."""
    return conn.execute(
        """SELECT entry.id, entry.account_id,
                  COALESCE(fix.corrected_amount_cents, entry.amount_cents)
           FROM ledger_transaction entry
           LEFT JOIN transaction_correction fix
               ON fix.transaction_id = entry.id AND fix.field = 'amount' AND fix.state = 'applied'
           WHERE (:account IS NULL OR entry.account_id = :account)
             AND (:ids IS NULL OR entry.id IN (SELECT value FROM json_each(:ids)))
           ORDER BY entry.id""",
        {"account": account_id,
         "ids": None if transaction_ids is None else ids_as_json_array(transaction_ids)},
    ).fetchall()


def attributed_transactions(conn: sqlite3.Connection, household: Household,
                            account_id: str | None = None,
                            transaction_ids=None) -> list[AttributedTransaction]:
    """Each transaction's effective attribution: a person's applied allocation, else unattributed
    where allocations reach it and none applies, else the account's default, else unattributed."""
    allocated = {
        transaction_id: (state, value)
        for transaction_id, state, value in conn.execute(
            """SELECT derived.transaction_id, derived.state, derived.allocation
               FROM transaction_allocation derived
               JOIN ledger_transaction entry ON entry.id = derived.transaction_id
               WHERE (:account IS NULL OR entry.account_id = :account)
                 AND (:ids IS NULL OR entry.id IN (SELECT value FROM json_each(:ids)))""",
            {"account": account_id,
             "ids": None if transaction_ids is None else ids_as_json_array(transaction_ids)},
        )
    }
    found = []
    for transaction_id, account, cents in effective_amounts(conn, account_id, transaction_ids):
        if transaction_id not in allocated:
            attribution = attribution_by_default(household, account, cents)
        else:
            state, value = allocated[transaction_id]
            attribution = (Attribution(UNATTRIBUTED, (), state, True) if value is None
                           else attribution_by_allocation(household, value, cents))
        found.append(AttributedTransaction(transaction_id, account, cents, attribution))
    return found
