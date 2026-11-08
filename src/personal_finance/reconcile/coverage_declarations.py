"""Declaring a document's coverage after import, and undoing that. See decisions.md D-051.

Every command checks everything under one write lock and either commits with the account derived
again or changes nothing.
"""

import sqlite3
import uuid
from dataclasses import dataclass

from personal_finance.ingest.coverage import UNKNOWN, Coverage, declare_complete
from personal_finance.ingest.errors import ImportFailure
from personal_finance.reconcile.apply import is_current, reconcile_account
from personal_finance.reconcile.correction_effects import unsettled_correction_fields
from personal_finance.reconcile.decisions import STALE_ACCOUNT, DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.supersession import STATE_ACTIVE, STATE_SUPERSEDED
from personal_finance.reports.coverage_evidence import (
    declaration_undo_outlook,
    document_coverage_revision,
    load_declaration,
    load_document_coverage,
)
from personal_finance.reports.totals import account_movement

DOCUMENT_NOT_FOUND = "document not found. Run documents."
DOCUMENT_WRONG_ACCOUNT = "this document belongs to another account. Nothing was changed."
STALE_COVERAGE_REVISION = (
    "this revision does not match the document's current coverage. Nothing was changed. Run "
    "review coverage show and check again."
)
KIND_UNSUPPORTED = (
    "coverage can be declared complete, or unknown to withdraw a claim. Nothing was changed."
)
COVERAGE_INVALID = (
    "complete coverage needs a start date, an end date no earlier than it, both YYYY-MM-DD, and "
    "a date basis, transaction or posting. Unknown coverage takes none of them. Nothing was "
    "changed."
)
BASIS_UNAVAILABLE = (
    "this document's layout offers no complete coverage on that date basis. Nothing was changed."
)
METADATA_STATED = (
    "this document states its own coverage, and a person never claims more than a document "
    "states. It can only be withdrawn, with --coverage-kind unknown. Nothing was changed."
)
CHANGES_NOTHING = (
    "this is the document's coverage already, so there is nothing to declare. Nothing was changed."
)
DECLARATION_NOT_FOUND = "declaration not found. Run review coverage history."
DECLARATION_WRONG_ACCOUNT = "this declaration belongs to another account. Nothing was changed."
DECLARATION_NOT_ACTIVE = "this declaration has already been undone. Nothing was changed."
DECLARATION_SUPERSEDED = (
    "this declaration is superseded by declaration {newest}, the newest of its chain, so it does "
    "not apply now. Nothing was changed. Undo that one instead, which restores the one before it."
)
STALE_DECLARATION_REVISION = (
    "this revision does not match the declaration's current evidence. Nothing was changed. Run "
    "review coverage show and check again."
)


@dataclass(frozen=True)
class CoverageChanged:
    declaration_id: str
    # The declaration this one superseded or, on undo, restored. None if there is none.
    other_declaration_id: str | None
    transactions_before: int
    transactions_after: int
    moved_records: int
    newly_unsettled_correction_fields: int


def declare_coverage(
    conn: sqlite3.Connection,
    account_id: str,
    document_id: str,
    revision: str,
    kind: str,
    start: str | None = None,
    end: str | None = None,
    date_basis: str | None = None,
    rules: MatchingRules = DEFAULT_RULES,
) -> CoverageChanged:
    """Replace a document's effective coverage with a person's declaration, keeping the claim made
    at import and any declaration before on record."""
    return _in_transaction(conn, lambda: _declare(
        conn, account_id, document_id, revision, kind, start, end, date_basis, rules
    ))


def _in_transaction(conn, work):
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = work()
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _declare(conn, account_id, document_id, revision, kind, start, end, date_basis, rules):
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    document = load_document_coverage(conn, document_id)
    if document is None:
        raise DecisionRefused(DOCUMENT_NOT_FOUND)
    if document.account_id != account_id:
        raise DecisionRefused(DOCUMENT_WRONG_ACCOUNT)
    if document_coverage_revision(document) != revision:
        raise DecisionRefused(STALE_COVERAGE_REVISION)
    declared = _checked_coverage(kind, start, end, date_basis)
    if declared.kind == "complete" and declared.date_basis not in document.offered_bases:
        raise DecisionRefused(BASIS_UNAVAILABLE)
    if document.claimed.evidence == "document_metadata" and declared.kind != "unknown":
        raise DecisionRefused(METADATA_STATED)
    if declared == document.effective:
        raise DecisionRefused(CHANGES_NOTHING)

    return _rederived(conn, account_id, rules, lambda: _insert_declaration(
        conn, account_id, document, declared, revision
    ))


def _checked_coverage(kind, start, end, date_basis) -> Coverage:
    if kind == "unknown":
        if start or end or date_basis:
            raise DecisionRefused(COVERAGE_INVALID)
        return UNKNOWN
    if kind != "complete":
        raise DecisionRefused(KIND_UNSUPPORTED)
    try:
        return declare_complete(start, end, date_basis)
    except ImportFailure:
        raise DecisionRefused(COVERAGE_INVALID) from None


def _insert_declaration(conn, account_id, document, declared, revision):
    declaration_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO coverage_declaration (id, account_id, source_document_id, coverage_kind,
                                             coverage_start, coverage_end, date_basis,
                                             supersedes_declaration_id, target_revision)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (declaration_id, account_id, document.document_id, declared.kind, declared.start,
         declared.end, declared.date_basis, document.declaration_id, revision),
    )
    _record_declaration_event(conn, declaration_id, "made")
    return declaration_id, document.declaration_id


def _rederived(conn, account_id, rules, change) -> CoverageChanged:
    before = account_movement(conn, account_id).transactions
    unsettled_before = unsettled_correction_fields(conn, account_id)
    declaration_id, other = change()
    result = reconcile_account(conn, account_id, rules)
    return CoverageChanged(
        declaration_id, other, before, account_movement(conn, account_id).transactions,
        result.moved_records,
        len(unsettled_correction_fields(conn, account_id) - unsettled_before),
    )


def undo_declaration(
    conn: sqlite3.Connection,
    account_id: str,
    declaration_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> CoverageChanged:
    """Stop a declaration applying, keeping it on record, and restore the one it superseded or the
    claim at import. Re-derives from current evidence, never a snapshot."""
    return _in_transaction(conn, lambda: _undo(conn, account_id, declaration_id, revision, rules))


def _undo(conn, account_id, declaration_id, revision, rules) -> CoverageChanged:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    declaration = load_declaration(conn, declaration_id)
    if declaration is None:
        raise DecisionRefused(DECLARATION_NOT_FOUND)
    if declaration.account_id != account_id:
        raise DecisionRefused(DECLARATION_WRONG_ACCOUNT)
    if declaration.state == STATE_SUPERSEDED:
        raise DecisionRefused(DECLARATION_SUPERSEDED.format(newest=declaration.newest_of_chain))
    if declaration.state != STATE_ACTIVE:
        raise DecisionRefused(DECLARATION_NOT_ACTIVE)
    if declaration_undo_outlook(conn, declaration, rules).revision != revision:
        raise DecisionRefused(STALE_DECLARATION_REVISION)

    def undone():
        _record_declaration_event(conn, declaration_id, "undone")
        return declaration_id, declaration.supersedes_declaration_id

    return _rederived(conn, account_id, rules, undone)


def _record_declaration_event(conn, declaration_id, event) -> None:
    conn.execute(
        "INSERT INTO coverage_declaration_event (declaration_id, event) VALUES (?, ?)",
        (declaration_id, event),
    )
