"""Writing categories stated by a person on spending. See decisions.md D-063.

Every command checks everything under one write lock and either commits with the ledger's
categorizations rewritten or changes nothing. The checks and writes are reconcile/statements.py's,
shared with financial types (D-053). A categorization moves no record and changes no amount, type
or transfer, so only categories are rewritten.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.categories import UNCATEGORIZED, find_category
from personal_finance.reconcile.category_effects import (
    CATEGORY_STATEMENTS,
    spending_transactions,
    write_category_effects,
)
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.statements import (
    StatementKind,
    StatementRefusals,
    make_statement,
    undo_statement,
)
from personal_finance.reports.categorization_evidence import categorization_undo_outlook

CATEGORY_UNKNOWN = (
    "category not found. Names are compared exactly: run category list, or add it with category "
    f"add. A transaction is {UNCATEGORIZED} until a category applies. Nothing was changed."
)
NOT_SPENDING_REFUSED = (
    "only spending takes a category: a purchase, fee, interest or refund on which no transfer is "
    "confirmed. Classify the transaction first. Nothing was changed."
)
CATEGORY_UNCHANGED = "this transaction already has this category. Nothing was changed."
ALREADY_CATEGORIZED = (
    "categorization {categorization} already applies to this transaction. Nothing was changed. "
    "To replace it, inspect it with review categorization show, then categorize again naming it "
    "with --supersedes."
)
CATEGORY_UNSETTLED = (
    "categorizations {categorizations} bind this transaction, and they disagree, lost their "
    "basis, are no longer on spending or are several, so it is uncategorized. Nothing was "
    "changed. Undo all but one of them first, one at a time."
)
CATEGORIZATION_NOT_FOUND = "categorization not found. Run review categorizations."
CATEGORIZATION_WRONG_ACCOUNT = (
    "this categorization belongs to another account. Nothing was changed."
)
CATEGORIZATION_NOT_ACTIVE = "this categorization has already been undone. Nothing was changed."
CATEGORIZATION_SUPERSEDED = (
    "this categorization is superseded by categorization {newer}, so it does not apply now. "
    "Nothing was changed. Undo that categorization instead, which restores this one."
)
CATEGORIZATION_SUPERSEDED_IN_CHAIN = (
    "this categorization is superseded by categorization {newer}, which is superseded in turn, "
    "so it does not apply now. Nothing was changed. Only the newest categorization of the chain, "
    "{newest}, can be undone or superseded, and each undo restores the one before it."
)
CATEGORIZATION_SUPERSEDES_NOT_HERE = (
    "the categorization named with --supersedes does not apply to this transaction. Nothing was "
    "changed."
)
STALE_CATEGORIZATION_REVISION = (
    "this revision does not match the categorization's current evidence. Nothing was changed. "
    "Run review categorization show and check again."
)


@dataclass(frozen=True)
class CategorizationMade:
    categorization_id: str
    category_name: str
    bound_record_count: int


@dataclass(frozen=True)
class CategorizationUndone:
    # The categorization this one superseded, which applies again.
    restored: str | None
    # Transactions this undo leaves uncategorized for a disagreement, a changed basis or because
    # they are no longer spending, and that were not before.
    newly_uncategorized_transactions: int


CATEGORIZATIONS = StatementKind(
    CATEGORY_STATEMENTS,
    StatementRefusals(
        unsettled=lambda ids: CATEGORY_UNSETTLED.format(categorizations=ids),
        already_applies=lambda applying: ALREADY_CATEGORIZED.format(categorization=applying),
        unchanged=CATEGORY_UNCHANGED,
        supersedes_not_here=CATEGORIZATION_SUPERSEDES_NOT_HERE,
        not_found=CATEGORIZATION_NOT_FOUND,
        wrong_account=CATEGORIZATION_WRONG_ACCOUNT,
        not_active=CATEGORIZATION_NOT_ACTIVE,
        superseded=lambda newer: CATEGORIZATION_SUPERSEDED.format(newer=newer),
        superseded_in_chain=lambda newer, newest: CATEGORIZATION_SUPERSEDED_IN_CHAIN.format(
            newer=newer, newest=newest),
        stale_revision=STALE_CATEGORIZATION_REVISION,
    ),
    lambda conn, categorization: categorization_undo_outlook(conn, categorization).revision,
    lambda conn, _: write_category_effects(conn),
)


def categorize_transaction(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    category_name: str,
    rules: MatchingRules = DEFAULT_RULES,
    supersedes: str | None = None,
    supersedes_revision: str | None = None,
) -> CategorizationMade:
    """Record the category of a spending transaction, binding every record it holds now, as a
    classification does (D-053, D-063). supersedes names the one categorization applying there,
    with its undo token."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _categorize(conn, account_id, transaction_id, revision, category_name, rules,
                             supersedes, supersedes_revision)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _categorize(conn, account_id, transaction_id, revision, category_name, rules, supersedes,
                supersedes_revision) -> CategorizationMade:
    category = find_category(conn, category_name)

    def refuse_unknown_category():
        if category is None:
            raise DecisionRefused(CATEGORY_UNKNOWN)

    def refuse_unless_spending():
        if transaction_id not in spending_transactions(conn, account_id):
            raise DecisionRefused(NOT_SPENDING_REFUSED)

    categorization_id, bound_record_count = make_statement(
        conn, CATEGORIZATIONS, account_id, transaction_id, revision,
        category and category.category_id, rules, supersedes, supersedes_revision,
        refuse_unknown_value=refuse_unknown_category, refuse_misfit=refuse_unless_spending,
    )
    return CategorizationMade(categorization_id, category.name, bound_record_count)


def undo_categorization(
    conn: sqlite3.Connection,
    account_id: str,
    categorization_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> CategorizationUndone:
    """Stop a categorization applying, keeping it on record, and restore anything it superseded.
    It never refuses for contradiction, and says when it leaves a transaction uncategorized for a
    disagreement (D-049, D-063)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = CategorizationUndone(*undo_statement(
            conn, CATEGORIZATIONS, account_id, categorization_id, revision, rules))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result
