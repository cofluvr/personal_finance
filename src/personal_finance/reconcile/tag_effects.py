"""Which tags apply to which transaction. See D-073 point 5.

A tag statement is D-063's model applied to a sixth stated kind, through
reconcile/stated_fields.py: a person states a transaction's whole set of tags, possibly empty.
Its value is canonical, the tag IDs ascending and joined by commas (D-065's multi-part value), so
two statements agree exactly when their values are equal. Tags fit any transaction, so a single
agreeing statement always applies. Tags enter no total, and matching never reads anything here.
The outcome is written for the whole ledger wherever categories are.
"""

import sqlite3

from personal_finance.reconcile import stated_fields
from personal_finance.reconcile.correction_effects import ActiveCorrection, FieldCorrection
from personal_finance.reconcile.stated_fields import StatedField

TAG_STATEMENTS = StatedField(
    field_name="tags",
    statement_table="tag_statement",
    value_column="tags",
    shown_value_sql="""COALESCE((SELECT group_concat(name, ', ') FROM (
                           SELECT tag.name FROM tag
                           WHERE ',' || statement.tags || ',' LIKE '%,' || tag.id || ',%'
                           ORDER BY tag.name)), 'none')""",
    supersedes_column="supersedes_tag_statement_id",
    record_table="tag_statement_record",
    event_table="tag_statement_event",
    statement_column="tag_statement_id",
    derived_table="transaction_tag",
    derived_value_column="tags",
    # Never reached: tags fit every transaction.
    misfit_state="basis_changed",
)


def canonical(tag_ids) -> str:
    return ",".join(str(tag_id) for tag_id in sorted(set(tag_ids)))


def tag_ids_of(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split(",")) if value else ()


def fits_every_transaction(transaction, value) -> bool:
    return True


def load_active_tag_statements(
    conn: sqlite3.Connection, account_id: str, treated_as_undone: str | None = None
) -> tuple[ActiveCorrection, ...]:
    return stated_fields.load_active(conn, TAG_STATEMENTS, account_id, treated_as_undone)


def effective_tags(active_statements, transaction_by_record_id) -> dict[object, FieldCorrection]:
    """The state and applied tags of every transaction a statement reaches."""
    return stated_fields.effective_values(TAG_STATEMENTS, active_statements,
                                          transaction_by_record_id, fits_every_transaction)


def write_tag_effects(conn: sqlite3.Connection) -> None:
    """Rewrite every tagged account's derived rows. The caller holds the transaction, and
    memberships must already be final."""
    for (account_id,) in conn.execute(
        "SELECT DISTINCT account_id FROM tag_statement ORDER BY account_id"
    ).fetchall():
        stated_fields.write_effects(conn, TAG_STATEMENTS, account_id, fits_every_transaction)


def unsettled_tags(conn: sqlite3.Connection, account_id: str) -> frozenset:
    return stated_fields.unsettled(conn, TAG_STATEMENTS, account_id)
