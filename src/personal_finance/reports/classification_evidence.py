"""What one stored classification binds, and what undoing it would change (D-053).

Everything here reads the ledger and nothing writes to it.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.apply import load_evidence
from personal_finance.reconcile.classification_effects import (
    classification_chain_states,
    effective_amount_by_transaction,
    effective_classifications,
    load_active_classifications,
    type_of_account,
)
from personal_finance.reconcile.correction_effects import transaction_by_record_id
from personal_finance.reconcile.supersession import successor_and_newest
from personal_finance.reports.decision_evidence import BoundRecord

# Bump whenever the material below changes, so an old token can never appear current.
CLASSIFICATION_REVISION_VERSION = 1


@dataclass(frozen=True)
class StoredClassification:
    classification_id: str
    account_id: str
    account_name: str
    financial_type: str
    # The transaction it was made on. A merge can retire it since.
    target_transaction_id: str
    created_at: str
    state: str
    undone_at: str | None
    bound_records: tuple[BoundRecord, ...]
    supersedes_classification_id: str | None
    # The classification replacing this one while it is superseded, and the newest of its chain.
    superseded_by: str | None
    newest_of_chain: str | None


@dataclass(frozen=True)
class ClassificationUndoOutlook:
    revision: str
    # For each transaction holding a bound record: its ID, and its outcome now and after, None
    # meaning that no classification binds it, so it is unclassified.
    state_by_transaction: tuple[tuple[str, str | None, str | None], ...]


def list_classifications(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    """IDs, types, states and counts only. A type is not financial data in itself (D-053)."""
    rows = conn.execute(
        """SELECT classification.id, account.display_name, classification.created_at,
                  classification.account_id, classification.financial_type,
                  (SELECT COUNT(*) FROM type_classification_record bound
                   WHERE bound.classification_id = classification.id)
           FROM type_classification classification
           JOIN account ON account.id = classification.account_id
           WHERE :account IS NULL OR classification.account_id = :account
           ORDER BY classification.created_at, classification.id""",
        {"account": account_id},
    ).fetchall()
    states_by_id = {}
    for account in {row[3] for row in rows}:
        states_by_id.update(classification_chain_states(conn, account)[0])
    return [
        (classification_id, account_name, created_at, states_by_id[classification_id],
         financial_type, bound_count)
        for classification_id, account_name, created_at, _, financial_type, bound_count in rows
    ]


def load_classification(
    conn: sqlite3.Connection, classification_id: str
) -> StoredClassification | None:
    row = conn.execute(
        """SELECT classification.account_id, account.display_name, classification.financial_type,
                  classification.target_transaction_id, classification.created_at,
                  undone.created_at, classification.supersedes_classification_id
           FROM type_classification classification
           JOIN account ON account.id = classification.account_id
           LEFT JOIN type_classification_event undone
               ON undone.classification_id = classification.id AND undone.event = 'undone'
           WHERE classification.id = ?""",
        (classification_id,),
    ).fetchone()
    if row is None:
        return None
    account_id, account_name, financial_type, target, created_at, undone_at, supersedes = row

    bound_records = [
        BoundRecord(*bound)
        for bound in conn.execute(
            """SELECT record.id, document.content_sha256, document.file_name, record.record_index,
                      link.transaction_id
               FROM type_classification_record bound
               JOIN source_record record ON record.id = bound.source_record_id
               JOIN source_document document ON document.id = record.source_document_id
               LEFT JOIN transaction_source link ON link.source_record_id = record.id
               WHERE bound.classification_id = ?""",
            (classification_id,),
        )
    ]
    states_by_id, successor_by_superseded_id = classification_chain_states(conn, account_id)
    newer, newest = successor_and_newest(successor_by_superseded_id, classification_id)
    return StoredClassification(
        classification_id, account_id, account_name, financial_type, target, created_at,
        states_by_id[classification_id], undone_at,
        tuple(sorted(bound_records, key=lambda record: (record.content_sha256, record.row))),
        supersedes, newer, newest,
    )


def classification_undo_outlook(
    conn: sqlite3.Connection, classification: StoredClassification
) -> ClassificationUndoOutlook:
    """The undo token, and the outcome either side of an undo, as for corrections (D-049).

    Only an active classification has one, so its state is not covered. Covers the transactions
    holding the records it binds, and their outcome with and without it, with anything it
    superseded restored. Its type and bound records never change, and another classification
    reaching those transactions or a change of direction changes the outcomes, so none of them is
    covered separately. Undoing a classification moves no record and changes no amount. An unrelated file
    leaves it unchanged.
    """
    account_id = classification.account_id
    documents, records, _, _ = load_evidence(conn, account_id)
    document_by_id = {document.id: document for document in documents}
    key_by_record_id = {
        record.id: (document_by_id[record.document_id].content_sha256, record.row_index)
        for record in records
    }

    membership = transaction_by_record_id(conn, account_id)
    amounts = effective_amount_by_transaction(conn, account_id)
    account_type = type_of_account(conn, account_id)
    bound_record_ids = {record.record_id for record in classification.bound_records}
    holding_transactions = {membership[record_id] for record_id in bound_record_ids}
    records_by_transaction = {transaction: set() for transaction in holding_transactions}
    for record_id, transaction in membership.items():
        if transaction in records_by_transaction:
            records_by_transaction[transaction].add(record_id)

    effects_with_it = effective_classifications(
        load_active_classifications(conn, account_id), membership, amounts, account_type)
    effects_without_it = effective_classifications(
        load_active_classifications(conn, account_id, classification.classification_id),
        membership, amounts, account_type)

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
    return ClassificationUndoOutlook(classification_revision(material), state_by_transaction)


def classification_revision(material: dict) -> str:
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"f{CLASSIFICATION_REVISION_VERSION}-{digest}"
