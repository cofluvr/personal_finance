"""The emergency fund's restoration: a dated monthly amount that safe-to-spend protects while the
fund is underfunded (D-072 points 2 and 4).

A later effective_from takes over, and undo steps back the newest active row (G2, G4). Each write
runs under one write lock with the fund's fu1 token for the operation `restoration` or
`restoration_undo`, which covers the fund and its active restorations, and changes no ledger table
(G1). The fund's other fu1 tokens are untouched, so every existing command reads as before.
"""

import sqlite3
import uuid
from dataclasses import dataclass

from personal_finance.planning.entries import (
    in_one_write,
    parsed_date,
    refuse_if_closed_month,
    refuse_unless_revision,
)
from personal_finance.planning.funds import (
    EMERGENCY,
    FUND_REVISION_VERSION,
    STALE_FUND_REVISION,
    checked_amount,
    find_active_fund,
    load_funds,
    terms_material,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reports.category_rule_evidence import digest

RESTORATION = "restoration"
RESTORATION_UNDO = "restoration_undo"

NOT_EMERGENCY = "only the emergency fund takes a restoration. Nothing was changed."
RESTORATION_CLOSED_MONTH = (
    "--effective-from is in a month before --as-of's, which is closed. Nothing was changed."
)
RESTORATION_NOT_LATER = (
    "--effective-from must be later than {latest}, the newest restoration's. Nothing was changed."
)
NO_RESTORATION = "this fund has no restoration to undo. Nothing was changed."


@dataclass(frozen=True)
class Restoration:
    restoration_id: str
    fund_id: str
    effective_from: str
    monthly_cents: int


def load_restorations(conn: sqlite3.Connection, fund_id: str) -> tuple[Restoration, ...]:
    """A fund's active restorations, oldest effective_from first."""
    return tuple(Restoration(*row) for row in conn.execute(
        """SELECT restoration.id, restoration.fund_id, restoration.effective_from,
                  restoration.monthly_cents
           FROM fund_restoration restoration
           WHERE restoration.fund_id = ? AND NOT EXISTS (
               SELECT 1 FROM fund_restoration_event undone
               WHERE undone.restoration_id = restoration.id AND undone.event = 'undone')
           ORDER BY restoration.effective_from""", (fund_id,)))


def restoration_on(restorations, on: str) -> Restoration | None:
    """The restoration in effect on a date, or None before the first."""
    starting = [restoration for restoration in restorations if restoration.effective_from <= on]
    return starting[-1] if starting else None


def restoration_revision(conn: sqlite3.Connection, operation: str, fund) -> str:
    """fu1 over the operation, the fund by ID, name, kind and terms, and its active
    restorations."""
    material = {"operation": operation, "fund_id": fund.fund_id, "name": fund.name,
                "kind": fund.kind, "terms": [terms_material(terms) for terms in fund.terms],
                "restorations": [[restoration.restoration_id, restoration.effective_from,
                                  restoration.monthly_cents]
                                 for restoration in load_restorations(conn, fund.fund_id)]}
    return f"fu{FUND_REVISION_VERSION}-{digest(material)}"


def emergency_fund(conn, fund_id):
    fund = find_active_fund(load_funds(conn), fund_id)
    if fund.kind != EMERGENCY:
        raise DecisionRefused(NOT_EMERGENCY)
    return fund


def set_restoration(conn: sqlite3.Connection, fund_id: str, monthly: str, effective_from: str,
                    as_of: str, revision: str) -> str:
    """Record a restoration taking over from effective_from, or refuse and change nothing."""
    return in_one_write(conn, lambda: _set(conn, fund_id, monthly, effective_from, as_of,
                                           revision))


def _set(conn, fund_id, monthly, effective_from, as_of, revision) -> str:
    fund = emergency_fund(conn, fund_id)
    as_of = parsed_date(as_of, "--as-of")
    effective_from = parsed_date(effective_from, "--effective-from")
    refuse_if_closed_month(effective_from, as_of, RESTORATION_CLOSED_MONTH)
    restorations = load_restorations(conn, fund_id)
    if restorations and effective_from <= restorations[-1].effective_from:
        raise DecisionRefused(RESTORATION_NOT_LATER.format(
            latest=restorations[-1].effective_from))
    cents = checked_amount(monthly, "--monthly")
    refuse_unless_revision(restoration_revision(conn, RESTORATION, fund), revision,
                           STALE_FUND_REVISION)
    restoration_id = str(uuid.uuid4())
    conn.execute("INSERT INTO fund_restoration (id, fund_id, effective_from, monthly_cents) "
                 "VALUES (?, ?, ?, ?)", (restoration_id, fund_id, effective_from, cents))
    insert_restoration_event(conn, restoration_id, "made")
    return restoration_id


def insert_restoration_event(conn: sqlite3.Connection, restoration_id: str, event: str) -> None:
    conn.execute("INSERT INTO fund_restoration_event (restoration_id, event) VALUES (?, ?)",
                 (restoration_id, event))


def undo_restoration(conn: sqlite3.Connection, fund_id: str, revision: str) -> Restoration:
    """Stop the newest active restoration applying, keeping it on record. The one before it, if
    any, applies again from its own date."""
    return in_one_write(conn, lambda: _undo(conn, fund_id, revision))


def _undo(conn, fund_id, revision) -> Restoration:
    fund = emergency_fund(conn, fund_id)
    restorations = load_restorations(conn, fund_id)
    if not restorations:
        raise DecisionRefused(NO_RESTORATION)
    refuse_unless_revision(restoration_revision(conn, RESTORATION_UNDO, fund), revision,
                           STALE_FUND_REVISION)
    insert_restoration_event(conn, restorations[-1].restoration_id, "undone")
    return restorations[-1]
