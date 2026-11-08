"""What one stored correction binds, and what undoing it would change (D-049).

Everything here reads the ledger and nothing writes to it.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.apply import load_evidence
from personal_finance.reconcile.classification_effects import (
    effective_classifications,
    load_active_classifications,
    type_of_account,
)
from personal_finance.reconcile.correction_effects import (
    FIELD_APPLIED,
    correction_chain_states,
    effective_field_corrections,
    load_active_corrections,
    transaction_by_record_id,
)
from personal_finance.reconcile.supersession import successor_and_newest
from personal_finance.reports.decision_evidence import BoundRecord

# Bump whenever the material below changes, so an old token can never appear current. Version 2
# adds the classifications of an amount's transactions, left out where there are none (D-053).
CORRECTION_REVISION_VERSION = 2


@dataclass(frozen=True)
class StoredCorrection:
    correction_id: str
    account_id: str
    account_name: str
    field: str
    # Integer cents for an amount, text for the other fields.
    corrected_value: int | str
    # The transaction it was made on. A merge can retire it since.
    target_transaction_id: str
    created_at: str
    state: str
    undone_at: str | None
    bound_records: tuple[BoundRecord, ...]
    supersedes_correction_id: str | None
    # The correction replacing this one while it is superseded, and the newest of its chain.
    superseded_by: str | None
    newest_of_chain: str | None


@dataclass(frozen=True)
class CorrectionUndoOutlook:
    revision: str
    # For each transaction holding a bound record: its ID, and this field's state now and after,
    # None meaning the source value with no correction at all.
    field_state_by_transaction: tuple[tuple[str, str | None, str | None], ...]


def list_corrections(conn: sqlite3.Connection, account_id: str | None = None) -> list[tuple]:
    """IDs, fields, states and counts only, so that routine output holds no financial data."""
    rows = conn.execute(
        """SELECT correction.id, account.display_name, correction.created_at,
                  correction.account_id, correction.field,
                  (SELECT COUNT(*) FROM value_correction_record bound
                   WHERE bound.correction_id = correction.id)
           FROM value_correction correction
           JOIN account ON account.id = correction.account_id
           WHERE :account IS NULL OR correction.account_id = :account
           ORDER BY correction.created_at, correction.id""",
        {"account": account_id},
    ).fetchall()
    states_by_id = {}
    for account in {row[3] for row in rows}:
        states_by_id.update(correction_chain_states(conn, account)[0])
    return [
        (correction_id, account_name, created_at, states_by_id[correction_id], field, bound_count)
        for correction_id, account_name, created_at, _, field, bound_count in rows
    ]


def load_correction(conn: sqlite3.Connection, correction_id: str) -> StoredCorrection | None:
    row = conn.execute(
        """SELECT correction.account_id, account.display_name, correction.field,
                  correction.corrected_amount_cents, correction.corrected_text,
                  correction.target_transaction_id, correction.created_at, undone.created_at,
                  correction.supersedes_correction_id
           FROM value_correction correction
           JOIN account ON account.id = correction.account_id
           LEFT JOIN value_correction_event undone
               ON undone.correction_id = correction.id AND undone.event = 'undone'
           WHERE correction.id = ?""",
        (correction_id,),
    ).fetchone()
    if row is None:
        return None
    (account_id, account_name, field, corrected_amount_cents, corrected_text, target, created_at,
     undone_at, supersedes) = row

    bound_records = [
        BoundRecord(*bound)
        for bound in conn.execute(
            """SELECT record.id, document.content_sha256, document.file_name, record.record_index,
                      link.transaction_id
               FROM value_correction_record bound
               JOIN source_record record ON record.id = bound.source_record_id
               JOIN source_document document ON document.id = record.source_document_id
               LEFT JOIN transaction_source link ON link.source_record_id = record.id
               WHERE bound.correction_id = ?""",
            (correction_id,),
        )
    ]
    states_by_id, successor_by_superseded_id = correction_chain_states(conn, account_id)
    newer, newest = successor_and_newest(successor_by_superseded_id, correction_id)
    return StoredCorrection(
        correction_id, account_id, account_name, field,
        corrected_amount_cents if field == "amount" else corrected_text,
        target, created_at, states_by_id[correction_id], undone_at,
        tuple(sorted(bound_records, key=lambda record: (record.content_sha256, record.row))),
        supersedes, newer, newest,
    )


def correction_undo_outlook(
    conn: sqlite3.Connection, correction: StoredCorrection
) -> CorrectionUndoOutlook:
    """The undo token, and this field's state either side of an undo (D-049).

    Only an active correction has one, so its state is not covered. Covers its field and value, the transactions holding the records it binds,
    and this field's outcome there with and without it, with anything it superseded restored. The
    bound records and their documents are immutable, and another correction of the field reaching
    those transactions changes the outcomes, so neither is covered separately. Grouping is not
    recomputed: undoing a correction moves no record. An unrelated file leaves it unchanged.

    An amount's sign decides whether a classification fits (D-053), so for an amount it also
    covers the classifications of those transactions with and without it.
    """
    account_id = correction.account_id
    documents, records, _, _ = load_evidence(conn, account_id)
    document_by_id = {document.id: document for document in documents}
    key_by_record_id = {
        record.id: (document_by_id[record.document_id].content_sha256, record.row_index)
        for record in records
    }

    membership = transaction_by_record_id(conn, account_id)
    bound_record_ids = {record.record_id for record in correction.bound_records}
    holding_transactions = {membership[record_id] for record_id in bound_record_ids}
    records_by_transaction = {transaction: set() for transaction in holding_transactions}
    for record_id, transaction in membership.items():
        if transaction in records_by_transaction:
            records_by_transaction[transaction].add(record_id)

    with_it = load_active_corrections(conn, account_id)
    without_it = load_active_corrections(conn, account_id, correction.correction_id)
    effects_with_it = effective_field_corrections(with_it, membership)
    effects_without_it = effective_field_corrections(without_it, membership)

    def keyed(record_ids):
        return sorted(key_by_record_id[record_id] for record_id in record_ids)

    def effect_view(effects, transaction):
        effect = effects.get((transaction, correction.field))
        return None if effect is None else [effect.state, effect.applied_value]

    material = {
        "field": correction.field,
        "value": correction.corrected_value,
        "transactions": sorted(
            [keyed(records_by_transaction[transaction]),
             effect_view(effects_with_it, transaction),
             effect_view(effects_without_it, transaction)]
            for transaction in holding_transactions
        ),
    }
    if correction.field == "amount":
        classifications = load_active_classifications(conn, account_id)
        if any(membership[record_id] in holding_transactions
               for classification in classifications
               for record_id in classification.bound_record_ids):
            account_type = type_of_account(conn, account_id)
            source_amounts = dict(conn.execute(
                "SELECT id, amount_cents FROM ledger_transaction WHERE account_id = ?",
                (account_id,),
            ))

            def classification_view(effects):
                amounts = dict(source_amounts)
                for (transaction, field), effect in effects.items():
                    if field == "amount" and effect.state == FIELD_APPLIED:
                        amounts[transaction] = effect.applied_value
                outcomes = effective_classifications(classifications, membership, amounts,
                                                     account_type)
                return sorted(
                    [keyed(records_by_transaction[transaction]), outcomes[transaction].state,
                     outcomes[transaction].applied_value]
                    for transaction in holding_transactions if transaction in outcomes
                )

            material["classifications"] = {
                "with_correction": classification_view(effects_with_it),
                "without_correction": classification_view(effects_without_it),
            }
    field_state_by_transaction = tuple(sorted(
        (transaction,
         *(None if view is None else view[0]
           for view in (effect_view(effects_with_it, transaction),
                        effect_view(effects_without_it, transaction))))
        for transaction in holding_transactions
    ))
    return CorrectionUndoOutlook(correction_revision(material), field_state_by_transaction)


def correction_revision(material: dict) -> str:
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"c{CORRECTION_REVISION_VERSION}-{digest}"
