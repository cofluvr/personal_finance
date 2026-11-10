"""What one stored statement of a type or a category binds, and what undoing it would change (D-053,
D-063).

Everything here reads the ledger and nothing writes to it.
"""

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from personal_finance.reconcile import stated_fields
from personal_finance.reconcile.apply import load_evidence
from personal_finance.reconcile.correction_effects import FieldCorrection, transaction_by_record_id
from personal_finance.reconcile.stated_fields import StatedField
from personal_finance.reconcile.supersession import successor_and_newest
from personal_finance.reports.decision_evidence import BoundRecord


@dataclass(frozen=True)
class StoredStatement:
    statement_id: str
    account_id: str
    account_name: str
    # The value as shown to a person.
    shown_value: str
    # The transaction it was made on. A merge can retire it since.
    target_transaction_id: str
    created_at: str
    state: str
    undone_at: str | None
    bound_records: tuple[BoundRecord, ...]
    supersedes_id: str | None
    # The statement replacing this one while it is superseded, and the newest of its chain.
    superseded_by: str | None
    newest_of_chain: str | None


@dataclass(frozen=True)
class UndoOutlook:
    # The undo token's material, which the caller digests under its own prefix.
    material: dict
    # For each transaction holding a bound record: its ID, and its outcome now and after, None
    # meaning that no statement reaches it.
    state_by_transaction: tuple[tuple[str, str | None, str | None], ...]


# The outcome of every transaction active statements reach, under one membership, as
# stated_fields.effective_values gives it.
EffectsOf = Callable[[tuple, dict], dict[object, FieldCorrection]]


def list_statements(conn: sqlite3.Connection, stated: StatedField,
                    account_id: str | None = None) -> list[tuple]:
    """IDs, shown values, states and counts only."""
    rows = conn.execute(
        f"""SELECT statement.id, account.display_name, statement.created_at,
                   statement.account_id, {stated.shown_value_sql},
                   (SELECT COUNT(*) FROM {stated.record_table} bound
                    WHERE bound.{stated.statement_column} = statement.id)
            FROM {stated.statement_table} statement
            JOIN account ON account.id = statement.account_id
            WHERE :account IS NULL OR statement.account_id = :account
            ORDER BY statement.created_at, statement.id""",
        {"account": account_id},
    ).fetchall()
    states_by_id = {}
    for account in {row[3] for row in rows}:
        states_by_id.update(stated_fields.chain_states(conn, stated, account)[0])
    return [
        (statement_id, account_name, created_at, states_by_id[statement_id], shown_value,
         bound_count)
        for statement_id, account_name, created_at, _, shown_value, bound_count in rows
    ]


def load_statement(conn: sqlite3.Connection, stated: StatedField,
                   statement_id: str) -> StoredStatement | None:
    row = conn.execute(
        f"""SELECT statement.account_id, account.display_name, {stated.shown_value_sql},
                   statement.target_transaction_id, statement.created_at,
                   undone.created_at, statement.{stated.supersedes_column}
            FROM {stated.statement_table} statement
            JOIN account ON account.id = statement.account_id
            LEFT JOIN {stated.event_table} undone
                ON undone.{stated.statement_column} = statement.id AND undone.event = 'undone'
            WHERE statement.id = ?""",
        (statement_id,),
    ).fetchone()
    if row is None:
        return None
    account_id, account_name, shown_value, target, created_at, undone_at, supersedes = row

    bound_records = [
        BoundRecord(*bound)
        for bound in conn.execute(
            f"""SELECT record.id, document.content_sha256, document.file_name,
                       record.record_index, link.transaction_id
                FROM {stated.record_table} bound
                JOIN source_record record ON record.id = bound.source_record_id
                JOIN source_document document ON document.id = record.source_document_id
                LEFT JOIN transaction_source link ON link.source_record_id = record.id
                WHERE bound.{stated.statement_column} = ?""",
            (statement_id,),
        )
    ]
    states_by_id, successor_by_superseded_id = stated_fields.chain_states(conn, stated, account_id)
    newer, newest = successor_and_newest(successor_by_superseded_id, statement_id)
    return StoredStatement(
        statement_id, account_id, account_name, shown_value, target, created_at,
        states_by_id[statement_id], undone_at,
        tuple(sorted(bound_records, key=lambda record: (record.content_sha256, record.row))),
        supersedes, newer, newest,
    )


def undo_outlook(conn: sqlite3.Connection, stated: StatedField, statement: StoredStatement,
                 effects_of: EffectsOf) -> UndoOutlook:
    """The undo token's material, and the outcome either side of an undo, as for corrections
    (D-049).

    Only an active statement has one, so its state is not covered. Covers the transactions holding
    the records it binds, and their outcome with and without it, with anything it superseded
    restored. Its value and bound records never change, and another statement reaching those
    transactions, or a change in where its value fits, changes the outcomes, so none of them is
    covered separately. Undoing a statement moves no record and changes no amount. An unrelated
    file leaves it unchanged.
    """
    account_id = statement.account_id
    documents, records, _, _ = load_evidence(conn, account_id)
    document_by_id = {document.id: document for document in documents}
    key_by_record_id = {
        record.id: (document_by_id[record.document_id].content_sha256, record.row_index)
        for record in records
    }

    membership = transaction_by_record_id(conn, account_id)
    bound_record_ids = {record.record_id for record in statement.bound_records}
    holding_transactions = {membership[record_id] for record_id in bound_record_ids}
    records_by_transaction = {transaction: set() for transaction in holding_transactions}
    for record_id, transaction in membership.items():
        if transaction in records_by_transaction:
            records_by_transaction[transaction].add(record_id)

    effects_with_it = effects_of(stated_fields.load_active(conn, stated, account_id), membership)
    effects_without_it = effects_of(
        stated_fields.load_active(conn, stated, account_id, statement.statement_id), membership)

    def keyed(record_ids):
        return sorted(key_by_record_id[record_id] for record_id in record_ids)

    def effect_view(effects, transaction):
        effect = effects.get(transaction)
        return None if effect is None else [effect.state, effect.applied_value]

    material = {
        "transactions": sorted(
            [keyed(records_by_transaction[transaction]),
             effect_view(effects_with_it, transaction),
             effect_view(effects_without_it, transaction)]
            for transaction in holding_transactions
        ),
    }
    state_by_transaction = tuple(sorted(
        (transaction,
         *(None if view is None else view[0]
           for view in (effect_view(effects_with_it, transaction),
                        effect_view(effects_without_it, transaction))))
        for transaction in holding_transactions
    ))
    return UndoOutlook(material, state_by_transaction)


def digest(material: dict) -> str:
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
