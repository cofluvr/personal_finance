"""The coverage in effect for an account: each document's declaration in effect, else its claim at
import (D-051), and the dates complete coverage vouches for (D-027).

Everything here reads the ledger and nothing writes to it. It sits apart from apply, which
derives accounts, so that transfer outcomes can read coverage without importing derivation.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from personal_finance.ingest.coverage import effective_end
from personal_finance.reconcile.supersession import STATE_ACTIVE, supersession_chain_states


@dataclass(frozen=True)
class DeclaredCoverage:
    """A person's coverage for one document, declared after import (D-051)."""

    declaration_id: str
    kind: str
    start: str | None
    end: str | None
    date_basis: str | None

    @property
    def evidence(self) -> str | None:
        return "user_declared" if self.kind == "complete" else None


def coverage_declaration_states(conn, account_id, treated_as_undone: str | None = None):
    """Each declaration's state, and each superseded one's successor, under D-048's rule."""
    rows = conn.execute(
        """SELECT declaration.id, declaration.supersedes_declaration_id,
                  EXISTS (SELECT 1 FROM coverage_declaration_event undone
                          WHERE undone.declaration_id = declaration.id
                            AND undone.event = 'undone')
           FROM coverage_declaration declaration WHERE declaration.account_id = ?""",
        (account_id,),
    ).fetchall()
    return supersession_chain_states(rows, treated_as_undone)


def declared_coverage(conn, account_id, treated_as_undone: str | None = None
                      ) -> dict[str, DeclaredCoverage]:
    """The declaration in effect for each document that has one. Each declaration supersedes the
    one in effect, so at most one per document is active (D-051)."""
    states, _ = coverage_declaration_states(conn, account_id, treated_as_undone)
    return {
        document_id: DeclaredCoverage(declaration_id, *values)
        for declaration_id, document_id, *values in conn.execute(
            """SELECT id, source_document_id, coverage_kind, coverage_start, coverage_end,
                      date_basis
               FROM coverage_declaration WHERE account_id = ?""",
            (account_id,),
        )
        if states[declaration_id] == STATE_ACTIVE
    }


def complete_coverage_by_basis(conn, account_id) -> dict[str, list[tuple[date, date]]]:
    """Each date basis's spans of complete coverage in effect, first and last day inclusive.

    A span ends where its claim can support matching (D-027), and a declaration replaces the claim
    at import (D-051). Spans are as stored, neither merged nor sorted.
    """
    declared = declared_coverage(conn, account_id)
    spans_by_basis = defaultdict(list)
    for document_id, kind, start, end, basis, evidence, generated_on in conn.execute(
        """SELECT coverage.source_document_id, coverage.coverage_kind, coverage.coverage_start,
                  coverage.coverage_end, coverage.date_basis, coverage.evidence,
                  document.generated_on
           FROM document_coverage coverage
           JOIN source_document document ON document.id = coverage.source_document_id
           WHERE coverage.account_id = ?""",
        (account_id,),
    ):
        declaration = declared.get(document_id)
        if declaration is not None:
            kind, start, end, basis, evidence = (declaration.kind, declaration.start,
                                                 declaration.end, declaration.date_basis,
                                                 declaration.evidence)
        if kind != "complete":
            continue
        last = effective_end(end, evidence, generated_on)
        if start <= last:
            spans_by_basis[basis].append((date.fromisoformat(start), date.fromisoformat(last)))
    return dict(spans_by_basis)
