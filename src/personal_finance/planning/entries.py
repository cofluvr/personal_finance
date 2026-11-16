"""What every planning entry a person states shares (D-067 G2 to G4): one write lock per command,
the account's currency and the token checked in D-043's order, chains stepped back one link at a
time, and the inputs every entry parses the same way. Extracted at its second use, M12.2's
obligations after M12.1's income sources (principle 2).

An entry is any object with entry_id, undone_at and superseded_by. Each kind gives its own
refusals, so each says what it is about.
"""

import hmac
import sqlite3
from dataclasses import dataclass
from datetime import date

from personal_finance.money import MoneyParseError, parse_cents
from personal_finance.planning.schedules import CADENCE_INVALID, StatedCadence, parsed_cadence
from personal_finance.reconcile.apply import stale_accounts
from personal_finance.reconcile.decisions import STALE_ACCOUNT, DecisionRefused
from personal_finance.reconcile.rules import MatchingRules

DATE_INVALID = "{option} must be a date written YYYY-MM-DD. Nothing was changed."


@dataclass(frozen=True)
class ChainRefusals:
    """How one kind of entry says it is missing, undone or superseded."""

    not_found: str
    not_active: str
    # Formatted with newest, the ID of the newest entry of the chain.
    superseded: str


def in_one_write(conn: sqlite3.Connection, write):
    """D-043: one write lock, one commit, and nothing kept from a refusal or a failure."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = write()
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def refuse_unless_current(conn: sqlite3.Connection, account_id: str,
                          rules: MatchingRules) -> None:
    """The entry's account must be current (D-033), or nothing is decided."""
    if stale_accounts(conn, rules, account_id):
        raise DecisionRefused(STALE_ACCOUNT)


def refuse_unless_revision(revision_now: str, revision: str, message: str) -> None:
    """The token shown must be the token now, compared in constant time (G3 step 4)."""
    if not hmac.compare_digest(revision_now.encode(), revision.encode()):
        raise DecisionRefused(message)


def lookup_entry(entries, entry_id: str, refusals: ChainRefusals):
    entry = next((entry for entry in entries if entry.entry_id == entry_id), None)
    if entry is None:
        raise DecisionRefused(refusals.not_found)
    return entry


def refuse_unless_newest(entries, entry, refusals: ChainRefusals):
    """An undone entry is refused, and a superseded one names its chain's newest (G4)."""
    if entry.undone_at:
        raise DecisionRefused(refusals.not_active)
    if entry.superseded_by:
        newest = entry
        by_id = {other.entry_id: other for other in entries}
        while newest.superseded_by:
            newest = by_id[newest.superseded_by]
        raise DecisionRefused(refusals.superseded.format(newest=newest.entry_id))
    return entry


def find_newest(entries, entry_id: str, refusals: ChainRefusals):
    """The entry with this ID that is still the newest of its chain."""
    return refuse_unless_newest(entries, lookup_entry(entries, entry_id, refusals), refusals)


def parsed_date(text: str, option: str) -> str:
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        raise DecisionRefused(DATE_INVALID.format(option=option)) from None
    if parsed.isoformat() != text:
        raise DecisionRefused(DATE_INVALID.format(option=option))
    return text


def parsed_amount(text: str, message: str, *, least: int) -> int:
    try:
        cents = parse_cents(text)
    except MoneyParseError:
        raise DecisionRefused(message) from None
    if cents is None or cents < least:
        raise DecisionRefused(message)
    return cents


def checked_cadence(text: str) -> StatedCadence:
    stated = parsed_cadence(text)
    if stated is None:
        raise DecisionRefused(CADENCE_INVALID)
    return stated


def refuse_if_closed_month(effective_from: str, as_of: str, message: str) -> None:
    """A month before as_of's is closed (G7)."""
    if effective_from[:7] < as_of[:7]:
        raise DecisionRefused(message)
