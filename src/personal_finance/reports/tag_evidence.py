"""What one stored tag statement binds, and what undoing it would change (D-073 point 5).

Everything here reads the ledger and nothing writes to it. It is reports/stated_evidence.py's,
shared with the other stated kinds, in the words of tags.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.tag_effects import TAG_STATEMENTS, effective_tags
from personal_finance.reports.stated_evidence import (
    StoredStatement,
    digest,
    load_statement,
    undo_outlook,
)

# Bump whenever the material below changes, so an old token can never appear current.
TAGGING_REVISION_VERSION = 1


@dataclass(frozen=True)
class TaggingUndoOutlook:
    revision: str
    state_by_transaction: tuple[tuple[str, str | None, str | None], ...]


def load_tagging(conn: sqlite3.Connection, statement_id: str) -> StoredStatement | None:
    return load_statement(conn, TAG_STATEMENTS, statement_id)


def tagging_undo_outlook(conn: sqlite3.Connection,
                         statement: StoredStatement) -> TaggingUndoOutlook:
    """The tg1 token, as lb1: the transactions holding its bound records, and their outcome with
    and without it, the outcome holding the tag IDs, each naming one append-only tag."""
    outlook = undo_outlook(conn, TAG_STATEMENTS, statement,
                           lambda active, membership: effective_tags(active, membership))
    return TaggingUndoOutlook(f"tg{TAGGING_REVISION_VERSION}-{digest(outlook.material)}",
                              outlook.state_by_transaction)
