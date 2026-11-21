"""Liquidity designations: the checking and savings accounts safe-to-spend may draw on (D-072
point 2).

A designation is undo then set, like M11's defaults (G4), written under one write lock with its
lq1 token, and changes no ledger table (G1). Nothing here reads the clock.
"""

import sqlite3
import uuid
from dataclasses import dataclass

from personal_finance.planning.entries import in_one_write, refuse_unless_revision
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reports.category_rule_evidence import digest

# Bump whenever the material below changes, so an old token can never appear current.
LIQUIDITY_REVISION_VERSION = 1

LIQUID_ACCOUNT_TYPES = ("checking", "savings")

SET = "set"
UNDO = "undo"

NOT_LIQUID_TYPE = (
    "{account} is not a checking or savings account: only they are designated liquid. Nothing "
    "was changed."
)
ALREADY_LIQUID = (
    "{account} is designated liquid already. Undo it first to change it. Nothing was changed."
)
NOT_DESIGNATED = (
    "{account} is not designated liquid, so there is nothing to undo. Nothing was changed."
)
STALE_LIQUIDITY_REVISION = (
    "this revision does not match the account's designation as it is now. Nothing was changed. "
    "Run account liquidity show and check it again."
)


@dataclass(frozen=True)
class Designation:
    designation_id: str
    account_id: str
    created_at: str


def load_designations(conn: sqlite3.Connection) -> dict[str, Designation]:
    """Every active designation, by account ID. The writes below keep one per account."""
    found = {}
    for designation_id, account_id, created_at in conn.execute(
            """SELECT designation.id, designation.account_id, designation.created_at
               FROM account_liquidity designation
               WHERE NOT EXISTS (SELECT 1 FROM account_liquidity_event undone
                                 WHERE undone.designation_id = designation.id
                                   AND undone.event = 'undone')"""):
        if account_id in found:
            raise RuntimeError(f"account {account_id} has more than one active designation")
        found[account_id] = Designation(designation_id, account_id, created_at)
    return found


def liquid_account_ids(conn: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(sorted(load_designations(conn)))


def liquidity_revision(conn: sqlite3.Connection, account_id: str) -> str:
    """lq1 covers the operation valid now, the account, its type and its active designation. An
    account with none can only be set, and one with a designation only undone."""
    designation = load_designations(conn).get(account_id)
    account_type = conn.execute("SELECT account_type FROM account WHERE id = ?",
                                (account_id,)).fetchone()[0]
    material = {"operation": SET if designation is None else UNDO, "account_id": account_id,
                "account_type": account_type,
                "designation": designation and designation.designation_id}
    return f"lq{LIQUIDITY_REVISION_VERSION}-{digest(material)}"


def account_named(conn, account_id) -> tuple[str, str]:
    return conn.execute("SELECT display_name, account_type FROM account WHERE id = ?",
                        (account_id,)).fetchone()


def designate(conn: sqlite3.Connection, account_id: str, revision: str) -> str:
    """Designate a checking or savings account liquid, or refuse and change nothing."""
    return in_one_write(conn, lambda: _designate(conn, account_id, revision))


def _designate(conn, account_id, revision) -> str:
    name, account_type = account_named(conn, account_id)
    if account_type not in LIQUID_ACCOUNT_TYPES:
        raise DecisionRefused(NOT_LIQUID_TYPE.format(account=name))
    if account_id in load_designations(conn):
        raise DecisionRefused(ALREADY_LIQUID.format(account=name))
    refuse_unless_revision(liquidity_revision(conn, account_id), revision,
                           STALE_LIQUIDITY_REVISION)
    designation_id = str(uuid.uuid4())
    conn.execute("INSERT INTO account_liquidity (id, account_id) VALUES (?, ?)",
                 (designation_id, account_id))
    insert_designation_event(conn, designation_id, "made")
    return designation_id


def insert_designation_event(conn: sqlite3.Connection, designation_id: str, event: str) -> None:
    conn.execute("INSERT INTO account_liquidity_event (designation_id, event) VALUES (?, ?)",
                 (designation_id, event))


def undo_designation(conn: sqlite3.Connection, account_id: str, revision: str) -> Designation:
    """Stop an account's designation applying, keeping it on record, or refuse and change
    nothing."""
    return in_one_write(conn, lambda: _undo(conn, account_id, revision))


def _undo(conn, account_id, revision) -> Designation:
    designation = load_designations(conn).get(account_id)
    if designation is None:
        raise DecisionRefused(NOT_DESIGNATED.format(account=account_named(conn, account_id)[0]))
    refuse_unless_revision(liquidity_revision(conn, account_id), revision,
                           STALE_LIQUIDITY_REVISION)
    insert_designation_event(conn, designation.designation_id, "undone")
    return designation
