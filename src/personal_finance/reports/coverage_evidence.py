"""One document's coverage: the claim at import, any declaration since, and their tokens (D-051).

Everything here reads the ledger and nothing writes to it. Coverage is not a financial value, so
what this loads may be shown in routine output.
"""

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass

from personal_finance.ingest.coverage import Coverage
from personal_finance.reconcile.apply import coverage_declaration_states, declared_coverage
from personal_finance.reconcile.rules import MatchingRules
from personal_finance.reports.undo_items import items_left_by_undo

# Bump whenever the material below changes, so an old token can never appear current.
DOCUMENT_COVERAGE_REVISION_VERSION = 1
DECLARATION_REVISION_VERSION = 1


@dataclass(frozen=True)
class DocumentCoverage:
    document_id: str
    account_id: str
    account_name: str
    file_name: str
    content_sha256: str
    layout_id: str
    # The claim made at import, which never changes (D-005).
    claimed: Coverage
    # What matching uses: the declaration in effect, else the claim.
    effective: Coverage
    # The declaration in effect, if any.
    declaration_id: str | None
    # Each date basis the stored interpretation offers a complete claim on, and whether pending
    # rows fall inside such a claim (D-026).
    pending_included_by_basis: tuple[tuple[str, bool], ...]

    @property
    def offered_bases(self) -> tuple[str, ...]:
        return tuple(basis for basis, _ in self.pending_included_by_basis)


@dataclass(frozen=True)
class StoredDeclaration:
    declaration_id: str
    account_id: str
    account_name: str
    document_id: str
    file_name: str
    declared: Coverage
    created_at: str
    state: str
    undone_at: str | None
    supersedes_declaration_id: str | None
    superseded_by: str | None
    newest_of_chain: str | None


@dataclass(frozen=True)
class DeclarationUndoOutlook:
    revision: str
    transactions_now: int
    transactions_after: int


def load_document_coverage(conn: sqlite3.Connection, document_id: str) -> DocumentCoverage | None:
    row = conn.execute(
        """SELECT coverage.account_id, account.display_name, document.file_name,
                  document.content_sha256, document.layout_id, coverage.coverage_kind,
                  coverage.coverage_start, coverage.coverage_end, coverage.date_basis,
                  coverage.evidence, meaning.pending_in_transaction_basis,
                  meaning.pending_in_posting_basis
           FROM document_coverage coverage
           JOIN source_document document ON document.id = coverage.source_document_id
           JOIN document_interpretation meaning ON meaning.source_document_id = document.id
           JOIN account ON account.id = coverage.account_id
           WHERE coverage.source_document_id = ?""",
        (document_id,),
    ).fetchone()
    if row is None:
        return None
    (account_id, account_name, file_name, digest, layout_id, *claim, pending_transaction,
     pending_posting) = row
    claimed = Coverage(*claim)
    declaration = declared_coverage(conn, account_id).get(document_id)
    effective = claimed if declaration is None else Coverage(
        declaration.kind, declaration.start, declaration.end, declaration.date_basis,
        declaration.evidence,
    )
    offered = tuple((basis, bool(pending)) for basis, pending in (("transaction", pending_transaction),
                                                                  ("posting", pending_posting))
                    if pending is not None)
    return DocumentCoverage(document_id, account_id, account_name, file_name, digest, layout_id,
                            claimed, effective, declaration and declaration.declaration_id,
                            offered)


def document_coverage_revision(document: DocumentCoverage) -> str:
    """The coverage token (D-051). The claim, the interpretation and the document never change,
    so the effective coverage is all a declaration can find changed since it was viewed."""
    text = json.dumps(asdict(document.effective), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"v{DOCUMENT_COVERAGE_REVISION_VERSION}-{digest}"


def list_declarations(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    rows = conn.execute(
        """SELECT declaration.id, account.display_name, declaration.created_at,
                  declaration.account_id, declaration.coverage_kind, document.file_name
           FROM coverage_declaration declaration
           JOIN account ON account.id = declaration.account_id
           JOIN source_document document ON document.id = declaration.source_document_id
           WHERE :account IS NULL OR declaration.account_id = :account
           ORDER BY declaration.created_at, declaration.id""",
        {"account": account_id},
    ).fetchall()
    states = {}
    for account in {row[3] for row in rows}:
        states.update(coverage_declaration_states(conn, account)[0])
    return [
        (declaration_id, account_name, created_at, states[declaration_id], kind, file_name)
        for declaration_id, account_name, created_at, _, kind, file_name in rows
    ]


def load_declaration(conn: sqlite3.Connection, declaration_id: str) -> StoredDeclaration | None:
    row = conn.execute(
        """SELECT declaration.account_id, account.display_name, declaration.source_document_id,
                  document.file_name, declaration.coverage_kind, declaration.coverage_start,
                  declaration.coverage_end, declaration.date_basis, declaration.created_at,
                  undone.created_at, declaration.supersedes_declaration_id
           FROM coverage_declaration declaration
           JOIN account ON account.id = declaration.account_id
           JOIN source_document document ON document.id = declaration.source_document_id
           LEFT JOIN coverage_declaration_event undone
               ON undone.declaration_id = declaration.id AND undone.event = 'undone'
           WHERE declaration.id = ?""",
        (declaration_id,),
    ).fetchone()
    if row is None:
        return None
    (account_id, account_name, document_id, file_name, kind, start, end, basis, created_at,
     undone_at, supersedes) = row
    states, successor_by_superseded_id = coverage_declaration_states(conn, account_id)
    newer = newest = successor_by_superseded_id.get(declaration_id)
    while newest in successor_by_superseded_id:
        newest = successor_by_superseded_id[newest]
    declared = Coverage(kind, start, end, basis, "user_declared" if kind == "complete" else None)
    return StoredDeclaration(declaration_id, account_id, account_name, document_id, file_name,
                             declared, created_at, states[declaration_id], undone_at, supersedes,
                             newer, newest)


def declaration_undo_outlook(
    conn: sqlite3.Connection, declaration: StoredDeclaration, rules: MatchingRules
) -> DeclarationUndoOutlook:
    """The undo token, and the transaction counts either side of an undo (D-051).

    It covers the review items an undo would leave, with any declaration this one superseded
    restored, for the records whose items it changes. Only an active declaration has a token, and
    what it declares never changes, so that is not covered.
    """
    left = items_left_by_undo(conn, declaration.account_id, rules,
                              without_declaration=declaration.declaration_id)
    return DeclarationUndoOutlook(f"k{DECLARATION_REVISION_VERSION}-{left.digest}",
                                  left.transactions_now, left.transactions_after)
