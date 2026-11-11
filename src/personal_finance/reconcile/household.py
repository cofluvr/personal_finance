"""Adding members, and setting or undoing the household share and an account's attribution. See
decisions.md D-065.

Every command checks everything under one write lock and either commits or changes nothing, in
D-043's order: every account reached is current, then the statement is valid, then its token. The
share and the defaults are resolved when read, so nothing derived is rewritten.
"""

import sqlite3
import uuid
from dataclasses import dataclass

from personal_finance.reconcile.decisions import STALE_ACCOUNT, DecisionRefused
from personal_finance.reconcile.household_effects import (
    RESERVED_MEMBER_NAMES,
    WHOLE_IN_BASIS_POINTS,
    Member,
    load_household,
    parse_percent,
)
from personal_finance.reports.household_evidence import Reach, account_reach, share_reach

MEMBER_NAME_BLANK = "a household member needs a name that is not blank. Nothing was changed."
MEMBER_NAME_RESERVED = (
    "shared and unattributed are what an attribution can be besides a member, so no member takes "
    "either name. Nothing was changed."
)
MEMBER_NAME_USED = "a household member of this name already exists. Nothing was changed."
MEMBER_UNKNOWN = "household member not found. Run household members. Nothing was changed."
SHARE_PART_MALFORMED = (
    "each --part must be NAME=PERCENT, the percent above zero with at most two decimals, as "
    "M=33.34. Nothing was changed."
)
SHARE_ONE_PART = "a household share needs two or more members. Nothing was changed."
SHARE_MEMBER_REPEATED = "a member is named in two parts. Nothing was changed."
SHARE_NOT_WHOLE = (
    "the parts must sum to exactly 100.00 percent. A third is typed 33.34, 33.33 and 33.33. "
    "Nothing was changed."
)
SHARE_ACTIVE = (
    "a household share is active already. To change it, undo it with household share undo, then "
    "set the new one. Nothing was changed."
)
SHARE_NOT_ACTIVE = "no household share is active. Nothing was changed."
STALE_SHARE_REVISION = (
    "this revision does not match the household share and what it reaches now. Nothing was "
    "changed. Run household share show and check it again."
)
ATTRIBUTION_ACTIVE = (
    "this account has a default already. To change it, undo it with household account undo, then "
    "set the new one. Nothing was changed."
)
ATTRIBUTION_NOT_ACTIVE = "this account has no default. Nothing was changed."
ATTRIBUTION_WITHOUT_SHARE = (
    "no household share is active, so shared would attribute nothing. Set one with household "
    "share set first. Nothing was changed."
)
STALE_ATTRIBUTION_REVISION = (
    "this revision does not match the account's default and what it reaches now. Nothing was "
    "changed. Run household account show and check it again."
)


@dataclass(frozen=True)
class Changed:
    """What a set or undo moved: its statement's ID, and what it reaches before and after."""

    statement_id: str
    before: Reach
    after: Reach


def _under_write_lock(conn: sqlite3.Connection, work, *arguments):
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = work(conn, *arguments)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def add_member(conn: sqlite3.Connection, name: str) -> Member:
    return _under_write_lock(conn, _add_member, name)


def _add_member(conn, name) -> Member:
    if not name.strip():
        raise DecisionRefused(MEMBER_NAME_BLANK)
    if name in RESERVED_MEMBER_NAMES:
        raise DecisionRefused(MEMBER_NAME_RESERVED)
    if load_household(conn).find_member(name) is not None:
        raise DecisionRefused(MEMBER_NAME_USED)
    member_id = conn.execute(
        "INSERT INTO household_member (name) VALUES (?) RETURNING id", (name,)).fetchone()[0]
    return Member(member_id, name)


def checked_parts(household, typed_parts: list[str]) -> list[tuple[int, int]]:
    """Typed NAME=PERCENT parts as (member ID, basis points) in member order, refused unless they
    name two or more known members once each, each above zero, summing to exactly 100.00."""
    parts = {}
    for typed in typed_parts:
        name, separator, percent = typed.rpartition("=")
        basis_points = parse_percent(percent)
        if not separator or basis_points is None or basis_points <= 0:
            raise DecisionRefused(SHARE_PART_MALFORMED)
        member = household.find_member(name)
        if member is None:
            raise DecisionRefused(MEMBER_UNKNOWN)
        if member.member_id in parts:
            raise DecisionRefused(SHARE_MEMBER_REPEATED)
        parts[member.member_id] = basis_points
    if len(parts) < 2:
        raise DecisionRefused(SHARE_ONE_PART)
    if sum(parts.values()) != WHOLE_IN_BASIS_POINTS:
        raise DecisionRefused(SHARE_NOT_WHOLE)
    return sorted(parts.items())


def _refuse_unless_current(reach: Reach) -> None:
    """Every account reached must be current (D-033), or nothing is decided."""
    if reach.stale_accounts:
        raise DecisionRefused(STALE_ACCOUNT)


def set_share(conn: sqlite3.Connection, typed_parts: list[str], revision: str) -> Changed:
    return _under_write_lock(conn, _set_share, typed_parts, revision)


def _set_share(conn, typed_parts, revision) -> Changed:
    household = load_household(conn)
    before = share_reach(conn, household)
    _refuse_unless_current(before)
    parts = checked_parts(household, typed_parts)
    if household.share is not None:
        raise DecisionRefused(SHARE_ACTIVE)
    if before.revision != revision:
        raise DecisionRefused(STALE_SHARE_REVISION)
    share_id = str(uuid.uuid4())
    conn.execute("INSERT INTO household_share (id) VALUES (?)", (share_id,))
    conn.executemany(
        "INSERT INTO household_share_part (share_id, member_id, basis_points) VALUES (?, ?, ?)",
        [(share_id, member_id, weight) for member_id, weight in parts])
    conn.execute("INSERT INTO household_share_event (share_id, event) VALUES (?, 'made')",
                 (share_id,))
    return Changed(share_id, before, share_reach(conn, load_household(conn)))


def undo_share(conn: sqlite3.Connection, revision: str) -> Changed:
    """Stop the active share applying, keeping it on record. Accounts attributed shared leave
    their transactions unattributed until a new share is set."""
    return _under_write_lock(conn, _undo_share, revision)


def _undo_share(conn, revision) -> Changed:
    household = load_household(conn)
    before = share_reach(conn, household)
    _refuse_unless_current(before)
    if household.share is None:
        raise DecisionRefused(SHARE_NOT_ACTIVE)
    if before.revision != revision:
        raise DecisionRefused(STALE_SHARE_REVISION)
    conn.execute("INSERT INTO household_share_event (share_id, event) VALUES (?, 'undone')",
                 (household.share.share_id,))
    return Changed(household.share.share_id, before, share_reach(conn, load_household(conn)))


def set_account_default(conn: sqlite3.Connection, account_id: str, member_name: str | None,
                        revision: str) -> Changed:
    """Attribute an account's transactions to one member, or to shared where member_name is
    None."""
    return _under_write_lock(conn, _set_account_default, account_id, member_name, revision)


def _set_account_default(conn, account_id, member_name, revision) -> Changed:
    household = load_household(conn)
    before = account_reach(conn, household, account_id)
    _refuse_unless_current(before)
    member_id = None
    if member_name is not None:
        member = household.find_member(member_name)
        if member is None:
            raise DecisionRefused(MEMBER_UNKNOWN)
        member_id = member.member_id
    elif household.share is None:
        raise DecisionRefused(ATTRIBUTION_WITHOUT_SHARE)
    if account_id in household.defaults:
        raise DecisionRefused(ATTRIBUTION_ACTIVE)
    if before.revision != revision:
        raise DecisionRefused(STALE_ATTRIBUTION_REVISION)
    attribution_id = str(uuid.uuid4())
    conn.execute("INSERT INTO account_attribution (id, account_id, member_id) VALUES (?, ?, ?)",
                 (attribution_id, account_id, member_id))
    conn.execute(
        "INSERT INTO account_attribution_event (attribution_id, event) VALUES (?, 'made')",
        (attribution_id,))
    return Changed(attribution_id, before, account_reach(conn, load_household(conn), account_id))


def undo_account_default(conn: sqlite3.Connection, account_id: str, revision: str) -> Changed:
    """Stop an account's default applying, keeping it on record."""
    return _under_write_lock(conn, _undo_account_default, account_id, revision)


def _undo_account_default(conn, account_id, revision) -> Changed:
    household = load_household(conn)
    before = account_reach(conn, household, account_id)
    _refuse_unless_current(before)
    default = household.defaults.get(account_id)
    if default is None:
        raise DecisionRefused(ATTRIBUTION_NOT_ACTIVE)
    if before.revision != revision:
        raise DecisionRefused(STALE_ATTRIBUTION_REVISION)
    conn.execute(
        "INSERT INTO account_attribution_event (attribution_id, event) VALUES (?, 'undone')",
        (default.attribution_id,))
    return Changed(default.attribution_id, before,
                   account_reach(conn, load_household(conn), account_id))

