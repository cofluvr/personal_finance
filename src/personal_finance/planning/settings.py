"""Ledger settings, keyed and append-only (D-069 point 1, G7): one active value per key, changed
by undo then set, each under one write lock with its st1 token. The household timezone is the
first key, an IANA name read with zoneinfo.

Nothing here reads the clock. The CLI alone turns the current UTC time into the household's day.
"""

import sqlite3
import uuid
import zoneinfo
from dataclasses import dataclass

from personal_finance.planning.entries import (
    in_one_write,
    parsed_amount,
    refuse_unless_revision,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reports.category_rule_evidence import digest

HOUSEHOLD_TIMEZONE = "household_timezone"
# One amount kept back across all liquidity accounts, stored as whole cents (D-072 point 2).
CHECKING_BUFFER = "checking_buffer_cents"

# Bump whenever the material below changes, so an old token can never appear current.
SETTING_REVISION_VERSION = 1

SET = "set"
UNDO = "undo"

KEY_UNKNOWN = "there is no setting {key}. Run setting show for the keys. Nothing was changed."
ZONE_UNKNOWN = (
    "{value} is not an IANA timezone this Mac knows. Give a name such as America/Chicago. "
    "Nothing was changed."
)
BUFFER_INVALID = (
    "{key} must be an amount above zero, such as 500.00. It is kept as whole cents. Nothing was "
    "changed."
)
ALREADY_SET = (
    "{key} is set already. Undo it with setting undo, then set it again. Nothing was changed."
)
NOT_SET = "{key} is not set, so there is nothing to undo. Nothing was changed."
STALE_SETTING_REVISION = (
    "this revision does not match the setting as it is now. Nothing was changed. Run setting "
    "show and check it again."
)


@dataclass(frozen=True)
class ActiveSetting:
    setting_id: str
    setting_key: str
    value: str
    created_at: str


def setting_keys(conn: sqlite3.Connection) -> list[str]:
    return [key for (key,) in conn.execute(
        "SELECT setting_key FROM ledger_setting_key ORDER BY setting_key")]


def active_setting(conn: sqlite3.Connection, key: str) -> ActiveSetting | None:
    """The key's value made and not undone. The writes below keep it to one."""
    row = conn.execute(
        """SELECT setting.id, setting.setting_key, setting.value, setting.created_at
           FROM ledger_setting setting
           WHERE setting.setting_key = ? AND NOT EXISTS (
               SELECT 1 FROM ledger_setting_event undone
               WHERE undone.setting_id = setting.id AND undone.event = 'undone')""",
        (key,)).fetchall()
    if len(row) > 1:
        raise RuntimeError(f"{key} has more than one active value")
    return ActiveSetting(*row[0]) if row else None


def setting_revision(conn: sqlite3.Connection, key: str) -> str:
    """st1 covers the operation valid now, the key and its active value (D-069 point 6). A key
    with no active value can only be set, and one with a value only undone."""
    active = active_setting(conn, key)
    operation = SET if active is None else UNDO
    return f"st{SETTING_REVISION_VERSION}-" + digest(
        {"operation": operation, "key": key, "value": active and active.value})


def household_timezone(conn: sqlite3.Connection) -> zoneinfo.ZoneInfo | None:
    active = active_setting(conn, HOUSEHOLD_TIMEZONE)
    return None if active is None else zoneinfo.ZoneInfo(active.value)


def refuse_unless_known_key(conn: sqlite3.Connection, key: str) -> None:
    if key not in setting_keys(conn):
        raise DecisionRefused(KEY_UNKNOWN.format(key=key))


def checked_value(key: str, value: str) -> str:
    """Each key's own check, and the value as stored. The timezone must be a name in this Mac's
    IANA database, which also refuses paths and names such as localtime that ZoneInfo alone would
    read. The buffer is typed as an amount and stored as its whole cents."""
    if key == HOUSEHOLD_TIMEZONE and value not in zoneinfo.available_timezones():
        raise DecisionRefused(ZONE_UNKNOWN.format(value=value))
    if key == CHECKING_BUFFER:
        return str(parsed_amount(value, BUFFER_INVALID.format(key=key), least=1))
    return value


def checking_buffer_cents(conn: sqlite3.Connection) -> int | None:
    """The buffer set, else None: safe-to-spend then keeps back 0 and says so."""
    active = active_setting(conn, CHECKING_BUFFER)
    return None if active is None else int(active.value)


def set_setting(conn: sqlite3.Connection, key: str, value: str, revision: str) -> str:
    """Set a key that has no active value, or refuse and change nothing."""
    return in_one_write(conn, lambda: _set_setting(conn, key, value, revision))


def _set_setting(conn, key, value, revision) -> str:
    refuse_unless_known_key(conn, key)
    value = checked_value(key, value)
    if active_setting(conn, key) is not None:
        raise DecisionRefused(ALREADY_SET.format(key=key))
    refuse_unless_revision(setting_revision(conn, key), revision, STALE_SETTING_REVISION)
    setting_id = str(uuid.uuid4())
    conn.execute("INSERT INTO ledger_setting (id, setting_key, value) VALUES (?, ?, ?)",
                 (setting_id, key, value))
    insert_setting_event(conn, setting_id, "made")
    return setting_id


def insert_setting_event(conn: sqlite3.Connection, setting_id: str, event: str) -> None:
    conn.execute("INSERT INTO ledger_setting_event (setting_id, event) VALUES (?, ?)",
                 (setting_id, event))


def undo_setting(conn: sqlite3.Connection, key: str, revision: str) -> ActiveSetting:
    """Stop a key's value applying, keeping it on record, or refuse and change nothing."""
    return in_one_write(conn, lambda: _undo_setting(conn, key, revision))


def _undo_setting(conn, key, revision) -> ActiveSetting:
    refuse_unless_known_key(conn, key)
    active = active_setting(conn, key)
    if active is None:
        raise DecisionRefused(NOT_SET.format(key=key))
    refuse_unless_revision(setting_revision(conn, key), revision, STALE_SETTING_REVISION)
    insert_setting_event(conn, active.setting_id, "undone")
    return active
