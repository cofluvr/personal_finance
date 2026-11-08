"""Writing financial types stated by a person. See decisions.md D-053.

Every command checks everything under one write lock and either commits with the account's
classifications rewritten or changes nothing. A classification moves no record and changes no
amount, so nothing is derived again.
"""

import sqlite3
import uuid
from dataclasses import dataclass

from personal_finance.reconcile.apply import is_current
from personal_finance.reconcile.classification_effects import (
    FINANCIAL_TYPES,
    UNCLASSIFIED,
    effective_amount_by_transaction,
    fits_direction,
    load_active_classifications,
    type_of_account,
    unsettled_classifications,
    write_classification_effects,
)
from personal_finance.reconcile.correction_effects import FIELD_APPLIED
from personal_finance.reconcile.decisions import STALE_ACCOUNT, DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.supersession import STATE_ACTIVE, STATE_SUPERSEDED
from personal_finance.reports.classification_evidence import (
    classification_undo_outlook,
    load_classification,
)
from personal_finance.reports.review_evidence import load_merge_evidence, transaction_revision

TYPE_UNKNOWN = (
    "the type must be one of " + ", ".join(FINANCIAL_TYPES) + ". A transaction is unclassified "
    "until one applies, and undoing its classification makes it unclassified again. Nothing was "
    "changed."
)
TYPE_AGAINST_DIRECTION = (
    "the type {financial_type} is money {direction}, and this transaction is money {other}. "
    "Nothing was changed. A transfer may be either, and a card, loan or investment payment may be "
    "money in on the account it pays."
)
TRANSACTION_NOT_FOUND = (
    "transaction not found. A later import or decision can retire one: run transactions"
)
TRANSACTION_WRONG_ACCOUNT = "this transaction belongs to another account. Nothing was changed."
STALE_TRANSACTION_REVISION = (
    "this revision does not match the transaction's current evidence. Nothing was changed. "
    "Run review transaction show and check the evidence again."
)
TYPE_UNCHANGED = "this transaction already has this type. Nothing was changed."
ALREADY_CLASSIFIED = (
    "classification {classification} already applies to this transaction. Nothing was changed. "
    "To replace it, inspect it with review classification show, then classify again naming it "
    "with --supersedes."
)
TYPE_UNSETTLED = (
    "classifications {classifications} bind this transaction, and they disagree, lost their basis, "
    "no longer fit its direction or are several, so it is unclassified. Nothing was changed. Undo "
    "all but one of them first, one at a time."
)
CLASSIFICATION_NOT_FOUND = "classification not found. Run review classifications."
CLASSIFICATION_WRONG_ACCOUNT = (
    "this classification belongs to another account. Nothing was changed."
)
CLASSIFICATION_NOT_ACTIVE = "this classification has already been undone. Nothing was changed."
CLASSIFICATION_SUPERSEDED = (
    "this classification is superseded by classification {newer}, so it does not apply now. "
    "Nothing was changed. Undo that classification instead, which restores this one."
)
CLASSIFICATION_SUPERSEDED_IN_CHAIN = (
    "this classification is superseded by classification {newer}, which is superseded in turn, so "
    "it does not apply now. Nothing was changed. Only the newest classification of the chain, "
    "{newest}, can be undone or superseded, and each undo restores the one before it."
)
SUPERSEDES_NOT_HERE = (
    "the classification named with --supersedes does not apply to this transaction. Nothing was "
    "changed."
)
STALE_CLASSIFICATION_REVISION = (
    "this revision does not match the classification's current evidence. Nothing was changed. "
    "Run review classification show and check again."
)


@dataclass(frozen=True)
class ClassificationMade:
    classification_id: str
    financial_type: str
    bound_record_count: int


@dataclass(frozen=True)
class ClassificationUndone:
    # The classification this one superseded, which applies again.
    restored: str | None
    # Transactions this undo leaves unclassified for a disagreement, a changed basis or direction,
    # and that were not before.
    newly_unclassified_transactions: int


def classify_transaction(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    financial_type: str,
    rules: MatchingRules = DEFAULT_RULES,
    supersedes: str | None = None,
    supersedes_revision: str | None = None,
) -> ClassificationMade:
    """Record the financial type of the event a transaction's records describe.

    It binds every record of the transaction now, as a correction does (D-049, D-053). supersedes
    names the one classification applying there, with its undo token.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _classify(conn, account_id, transaction_id, revision, financial_type, rules,
                           supersedes, supersedes_revision)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _classify(conn, account_id, transaction_id, revision, financial_type, rules, supersedes,
              supersedes_revision) -> ClassificationMade:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    if financial_type not in FINANCIAL_TYPES:
        raise DecisionRefused(TYPE_UNKNOWN)
    merge = load_merge_evidence(conn, transaction_id)
    if merge is None:
        raise DecisionRefused(TRANSACTION_NOT_FOUND)
    if merge.account_id != account_id:
        raise DecisionRefused(TRANSACTION_WRONG_ACCOUNT)
    if transaction_revision(merge) != revision:
        raise DecisionRefused(STALE_TRANSACTION_REVISION)
    superseded = None
    if supersedes:
        superseded = _checked_for_replacing(conn, account_id, supersedes, supersedes_revision)

    entry = merge.transaction
    record_ids = {record.record_id for record in entry.records}
    applying = [
        classification for classification in load_active_classifications(conn, account_id)
        if classification.bound_record_ids & record_ids
    ]
    applying_ids = sorted(classification.correction_id for classification in applying)
    state = entry.classifications[0].state if entry.classifications else None
    if len(applying) > 1 or (applying and state != FIELD_APPLIED):
        raise DecisionRefused(TYPE_UNSETTLED.format(classifications=", ".join(applying_ids)))
    if superseded is not None and superseded.classification_id not in applying_ids:
        raise DecisionRefused(SUPERSEDES_NOT_HERE)
    if applying and superseded is None:
        raise DecisionRefused(ALREADY_CLASSIFIED.format(classification=applying_ids[0]))
    shown_now = applying[0].corrected_value if applying else UNCLASSIFIED
    if financial_type == shown_now:
        raise DecisionRefused(TYPE_UNCHANGED)
    amount_cents = effective_amount_by_transaction(conn, account_id)[transaction_id]
    if not fits_direction(financial_type, amount_cents, type_of_account(conn, account_id)):
        direction, other = ("in", "out") if amount_cents < 0 else ("out", "in")
        raise DecisionRefused(TYPE_AGAINST_DIRECTION.format(
            financial_type=financial_type, direction=direction, other=other))

    classification_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO type_classification (id, account_id, financial_type,
                                            target_transaction_id, target_revision,
                                            supersedes_classification_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (classification_id, account_id, financial_type, transaction_id, revision,
         superseded and superseded.classification_id),
    )
    conn.executemany(
        """INSERT INTO type_classification_record (classification_id, source_record_id)
           VALUES (?, ?)""",
        [(classification_id, record_id) for record_id in sorted(record_ids)],
    )
    _record_classification_event(conn, classification_id, "made")
    write_classification_effects(conn, account_id)
    return ClassificationMade(classification_id, financial_type, len(record_ids))


def _checked_for_replacing(conn, account_id, classification_id, revision):
    """A classification being superseded or undone, checked as D-043 checks a decision."""
    classification = load_classification(conn, classification_id)
    if classification is None:
        raise DecisionRefused(CLASSIFICATION_NOT_FOUND)
    if classification.account_id != account_id:
        raise DecisionRefused(CLASSIFICATION_WRONG_ACCOUNT)
    if classification.state == STATE_SUPERSEDED:
        if classification.newest_of_chain != classification.superseded_by:
            raise DecisionRefused(CLASSIFICATION_SUPERSEDED_IN_CHAIN.format(
                newer=classification.superseded_by, newest=classification.newest_of_chain
            ))
        raise DecisionRefused(CLASSIFICATION_SUPERSEDED.format(newer=classification.superseded_by))
    if classification.state != STATE_ACTIVE:
        raise DecisionRefused(CLASSIFICATION_NOT_ACTIVE)
    if classification_undo_outlook(conn, classification).revision != revision:
        raise DecisionRefused(STALE_CLASSIFICATION_REVISION)
    return classification


def undo_classification(
    conn: sqlite3.Connection,
    account_id: str,
    classification_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> ClassificationUndone:
    """Stop a classification applying, keeping it on record, and restore anything it superseded.

    Classifications constrain no identity, so this never refuses for contradiction. It says when
    it leaves a transaction unclassified for a disagreement (D-049, D-053).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _undo_classification(conn, account_id, classification_id, revision, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _undo_classification(conn, account_id, classification_id, revision,
                         rules) -> ClassificationUndone:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    classification = _checked_for_replacing(conn, account_id, classification_id, revision)
    unsettled_before = unsettled_classifications(conn, account_id)
    _record_classification_event(conn, classification_id, "undone")
    write_classification_effects(conn, account_id)
    newly_unsettled = unsettled_classifications(conn, account_id) - unsettled_before
    return ClassificationUndone(classification.supersedes_classification_id, len(newly_unsettled))


def _record_classification_event(conn, classification_id, event) -> None:
    conn.execute(
        "INSERT INTO type_classification_event (classification_id, event) VALUES (?, ?)",
        (classification_id, event),
    )
