"""What the household share and an account's attribution reach now, and their tokens (D-065).

Everything here reads the ledger and nothing writes to it. A token covers what its command shows,
so one made before a change of share, default, account currency or the evidence they reach is
refused. Names stand in for IDs, which say only where something is stored.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from personal_finance.reconcile.apply import stale_accounts
from personal_finance.reconcile.household_effects import (
    NO_SHARE,
    SHARED,
    AccountDefault,
    AttributedTransaction,
    Household,
    Share,
    attributed_transactions,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports.category_rule_evidence import digest, record_keys
from personal_finance.reports.totals import GroupTotal

# Bump whenever the material below changes, so an old token can never appear current.
SHARE_REVISION_VERSION = 1
ATTRIBUTION_REVISION_VERSION = 1


@dataclass(frozen=True)
class Reach:
    """Transactions a share or a default reaches, and what they hold by member now."""

    revision: str
    reached: GroupTotal
    # Each member's parts in member order, under what applies now. Empty where nothing does.
    by_member: tuple[tuple[str, GroupTotal], ...]
    # Accounts reached that are not current, by name.
    stale_accounts: tuple[str, ...]


def default_words(household: Household, default: AccountDefault | None) -> str | None:
    if default is None:
        return None
    return SHARED if default.member_id is None else household.name_of(default.member_id)


def share_material(household: Household, share: Share | None):
    if share is None:
        return None
    return [[household.name_of(member_id), weight] for member_id, weight in share.parts]


def share_reach(conn: sqlite3.Connection, household: Household) -> Reach:
    """Every transaction the share reaches, whether or not one is active, and the h1 token: those
    an account's default or a person's allocation attributes shared."""
    names = account_names(conn)
    reached = [entry for entry in attributed_transactions(conn, household)
               if entry.attribution.kind == SHARED or entry.attribution.reason == NO_SHARE]
    shared_accounts = {account_id for account_id, default in household.defaults.items()
                       if default.member_id is None}
    shared_accounts.update(entry.account_id for entry in reached)
    material = {
        "share": share_material(household, household.share),
        "defaults": sorted([names[account_id], default_words(household, default)]
                           for account_id, default in household.defaults.items()),
    }
    return _reach(conn, household, reached, shared_accounts, material,
                  f"h{SHARE_REVISION_VERSION}")


def account_reach(conn: sqlite3.Connection, household: Household, account_id: str) -> Reach:
    """Every transaction of one account its default reaches, and the a1 token. A person's
    allocation comes first, so a transaction one reaches is not the default's."""
    reached = [entry for entry in attributed_transactions(conn, household, account_id)
               if not entry.attribution.by_allocation]
    material = {
        "account": account_names(conn)[account_id],
        "default": default_words(household, household.defaults.get(account_id)),
        "share": share_material(household, household.share),
    }
    return _reach(conn, household, reached, {account_id}, material,
                  f"a{ATTRIBUTION_REVISION_VERSION}")


def _reach(conn, household, reached: list[AttributedTransaction], account_ids, material,
           prefix) -> Reach:
    names = account_names(conn)
    stale = tuple(sorted(names[account_id] for account_id in stale_accounts(conn, DEFAULT_RULES)
                         if account_id in account_ids))
    keys = record_keys(conn, [entry.transaction_id for entry in reached])
    material["stale"] = list(stale)
    material["reaches"] = sorted([keys[entry.transaction_id], entry.amount_cents]
                                 for entry in reached)
    total, by_member = GroupTotal(), defaultdict(GroupTotal)
    for entry in reached:
        total = total.adding(entry.amount_cents)
        for member_id, cents in entry.attribution.parts:
            by_member[member_id] = by_member[member_id].adding(cents)
    return Reach(
        f"{prefix}-{digest(material)}", total,
        tuple((member.name, by_member[member.member_id]) for member in household.members
              if member.member_id in by_member),
        stale,
    )


def account_names(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT id, display_name FROM account"))
