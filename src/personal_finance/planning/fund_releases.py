"""Releasing part of the tax reserve found too large, and undoing a release (D-070 point 6, G4).

A release is an amount on a date. It reduces the reserve's required amount from that date, never
below zero, and is labelled a planning reserve wherever it is shown. Each write runs under one
write lock with the tax reserve's fu1 token, which covers its active releases, and changes no
ledger table (G1). Kept apart from planning/funds.py because the required amount it checks reads
the tax accrual in reports/fund_standing.py.
"""

import sqlite3
import uuid

from personal_finance.money import format_cents
from personal_finance.planning.entries import (
    in_one_write,
    parsed_date,
    refuse_if_closed_month,
    refuse_unless_revision,
)
from personal_finance.planning.funds import (
    RELEASE,
    RELEASE_AFTER_AS_OF,
    RELEASE_BEFORE_START,
    RELEASE_BEYOND_REQUIRED,
    RELEASE_CLOSED_MONTH,
    RELEASE_NOT_FOUND,
    RELEASE_NOT_TAX,
    RELEASE_OF_ANOTHER_FUND,
    RELEASE_UNDO,
    STALE_FUND_REVISION,
    TAX,
    checked_amount,
    find_active_fund,
    fund_revision,
    load_funds,
    load_releases,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reports.fund_standing import tax_required_cents


def release_tax_reserve(conn: sqlite3.Connection, fund_id: str, amount: str, released_on: str,
                        as_of: str, revision: str) -> str:
    """Record a release of the tax reserve, or refuse and change nothing."""
    return in_one_write(conn, lambda: _release(conn, fund_id, amount, released_on, as_of,
                                               revision))


def _release(conn, fund_id, amount, released_on, as_of, revision) -> str:
    fund = find_active_fund(load_funds(conn), fund_id)
    if fund.kind != TAX:
        raise DecisionRefused(RELEASE_NOT_TAX)
    as_of = parsed_date(as_of, "--as-of")
    released_on = parsed_date(released_on, "--on")
    if released_on < fund.terms[0].effective_from:
        raise DecisionRefused(RELEASE_BEFORE_START.format(start=fund.terms[0].effective_from))
    if released_on > as_of:
        raise DecisionRefused(RELEASE_AFTER_AS_OF)
    refuse_if_closed_month(released_on, as_of, RELEASE_CLOSED_MONTH)
    cents = checked_amount(amount, "--amount")
    refuse_unless_revision(fund_revision(RELEASE, fund, load_releases(conn)), revision,
                           STALE_FUND_REVISION)
    required = tax_required_cents(conn, fund, as_of)
    if cents > required:
        raise DecisionRefused(RELEASE_BEYOND_REQUIRED.format(
            amount=format_cents(cents), required=format_cents(required), as_of=as_of))
    release_id = str(uuid.uuid4())
    conn.execute("INSERT INTO tax_reserve_release (id, fund_id, amount_cents, released_on) "
                 "VALUES (?, ?, ?, ?)", (release_id, fund_id, cents, released_on))
    conn.execute("INSERT INTO tax_reserve_release_event (release_id, event) VALUES (?, 'made')",
                 (release_id,))
    return release_id


def undo_release(conn: sqlite3.Connection, fund_id: str, release_id: str, revision: str) -> None:
    """Stop a release applying, keeping it on record, or refuse and change nothing."""
    in_one_write(conn, lambda: _undo_release(conn, fund_id, release_id, revision))


def _undo_release(conn, fund_id, release_id, revision) -> None:
    fund = find_active_fund(load_funds(conn), fund_id)
    releases = load_releases(conn)
    release = next((release for release in releases if release.release_id == release_id), None)
    if release is None:
        raise DecisionRefused(RELEASE_NOT_FOUND)
    if release.fund_id != fund_id:
        raise DecisionRefused(RELEASE_OF_ANOTHER_FUND)
    refuse_unless_revision(fund_revision(RELEASE_UNDO, fund, releases), revision,
                           STALE_FUND_REVISION)
    conn.execute("INSERT INTO tax_reserve_release_event (release_id, event) VALUES (?, 'undone')",
                 (release_id,))
