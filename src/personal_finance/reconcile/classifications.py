"""Writing financial types stated by a person. See decisions.md D-053.

Every command checks everything under one write lock and either commits with the account's
classifications rewritten or changes nothing. A classification moves no record and changes no
amount, so nothing is derived again. The checks and writes are reconcile/statements.py's, shared
with categories (D-063).
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.classification_effects import (
    FINANCIAL_TYPES,
    TYPE_STATEMENTS,
    effective_amount_by_transaction,
    fits_direction,
    type_of_account,
    write_classification_effects,
)
from personal_finance.reconcile.decisions import LEAVES_TRANSFER_UNSETTLED, DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.statements import (
    STALE_TRANSACTION_REVISION,
    TRANSACTION_NOT_FOUND,
    TRANSACTION_WRONG_ACCOUNT,
    StatementKind,
    StatementRefusals,
    make_statement,
    undo_statement,
)
from personal_finance.reconcile.transfer_effects import (
    unsettled_transfers,
    write_transfer_effects,
)
from personal_finance.reports.classification_evidence import classification_undo_outlook

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
# One classification alone cannot disagree, so it lost its basis or no longer fits the direction.
TYPE_ALONE_UNSETTLED = (
    "classification {classifications} binds this transaction, but lost its basis or no longer "
    "fits its direction, so it is unclassified. Nothing was changed. Undo it, or what changed the "
    "direction, first."
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
    # Transfer matches this undo stops applying, and that applied before (D-054).
    newly_unsettled_matches: int


def _rewrite_effects(conn, account_id) -> None:
    write_classification_effects(conn, account_id)
    write_transfer_effects(conn)


CLASSIFICATIONS = StatementKind(
    TYPE_STATEMENTS,
    StatementRefusals(
        unsettled=lambda ids: (TYPE_UNSETTLED if ", " in ids
                               else TYPE_ALONE_UNSETTLED).format(classifications=ids),
        already_applies=lambda applying: ALREADY_CLASSIFIED.format(classification=applying),
        unchanged=TYPE_UNCHANGED,
        supersedes_not_here=SUPERSEDES_NOT_HERE,
        not_found=CLASSIFICATION_NOT_FOUND,
        wrong_account=CLASSIFICATION_WRONG_ACCOUNT,
        not_active=CLASSIFICATION_NOT_ACTIVE,
        superseded=lambda newer: CLASSIFICATION_SUPERSEDED.format(newer=newer),
        superseded_in_chain=lambda newer, newest: CLASSIFICATION_SUPERSEDED_IN_CHAIN.format(
            newer=newer, newest=newest),
        stale_revision=STALE_CLASSIFICATION_REVISION,
    ),
    lambda conn, classification: classification_undo_outlook(conn, classification).revision,
    _rewrite_effects,
)


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
    def refuse_unknown_type():
        if financial_type not in FINANCIAL_TYPES:
            raise DecisionRefused(TYPE_UNKNOWN)

    def refuse_against_direction():
        amount_cents = effective_amount_by_transaction(conn, account_id)[transaction_id]
        if not fits_direction(financial_type, amount_cents, type_of_account(conn, account_id)):
            direction, other = ("in", "out") if amount_cents < 0 else ("out", "in")
            raise DecisionRefused(TYPE_AGAINST_DIRECTION.format(
                financial_type=financial_type, direction=direction, other=other))

    unmatched_before = unsettled_transfers(conn)
    classification_id, bound_record_count = make_statement(
        conn, CLASSIFICATIONS, account_id, transaction_id, revision, financial_type, rules,
        supersedes, supersedes_revision, refuse_unknown_value=refuse_unknown_type,
        refuse_misfit=refuse_against_direction,
    )
    if unsettled_transfers(conn) - unmatched_before:
        raise DecisionRefused(LEAVES_TRANSFER_UNSETTLED)
    return ClassificationMade(classification_id, financial_type, bound_record_count)


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
        unmatched_before = unsettled_transfers(conn)
        restored, newly_unclassified = undo_statement(conn, CLASSIFICATIONS, account_id,
                                                      classification_id, revision, rules)
        result = ClassificationUndone(restored, newly_unclassified,
                                      len(unsettled_transfers(conn) - unmatched_before))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result
