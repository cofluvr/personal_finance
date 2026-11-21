"""Naming tags, and stating a transaction's tags. See D-073 point 5.

Every command checks everything under one write lock and either commits with the ledger's tags
rewritten or changes nothing. The checks and writes are reconcile/statements.py's, shared with the
other stated kinds. A tag statement moves no record and changes no amount, type, category or
total.
"""

import sqlite3
from dataclasses import dataclass

from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.statements import (
    StatementKind,
    StatementRefusals,
    make_statement,
    undo_statement,
)
from personal_finance.reconcile.tag_effects import TAG_STATEMENTS, canonical, write_tag_effects
from personal_finance.reports.tag_evidence import tagging_undo_outlook

TAG_NAME_INVALID = (
    "a tag's name must not be empty, start or end with a space, or hold a comma. Nothing was "
    "changed."
)
TAG_EXISTS = "this tag already exists. Names are compared exactly. Nothing was changed."
TAG_UNKNOWN = (
    "tag not found. Names are compared exactly: run tags, or add it with tag add. Nothing was "
    "changed."
)
TAGS_UNCHANGED = "this transaction already has these tags. Nothing was changed."
ALREADY_TAGGED = (
    "tag statement {statement} already applies to this transaction. Nothing was changed. To "
    "replace it, inspect it with review tagging show, then tag again naming it with --supersedes."
)
TAGS_UNSETTLED = (
    "tag statements {statements} bind this transaction, and they disagree, lost their basis or "
    "are several, so no tags apply. Nothing was changed. Undo all but one of them first, one at a "
    "time."
)
TAGS_ALONE_UNSETTLED = (
    "tag statement {statements} binds this transaction, but lost its basis, so no tags apply. "
    "Nothing was changed. Undo it first."
)
TAGGING_NOT_FOUND = "tag statement not found. Run review transaction show."
TAGGING_WRONG_ACCOUNT = "this tag statement belongs to another account. Nothing was changed."
TAGGING_NOT_ACTIVE = "this tag statement has already been undone. Nothing was changed."
TAGGING_SUPERSEDED = (
    "this tag statement is superseded by tag statement {newer}, so it does not apply now. "
    "Nothing was changed. Undo that one instead, which restores this one."
)
TAGGING_SUPERSEDED_IN_CHAIN = (
    "this tag statement is superseded by tag statement {newer}, which is superseded in turn, so "
    "it does not apply now. Nothing was changed. Only the newest of the chain, {newest}, can be "
    "undone or superseded, and each undo restores the one before it."
)
TAGGING_SUPERSEDES_NOT_HERE = (
    "the tag statement named with --supersedes does not apply to this transaction. Nothing was "
    "changed."
)
STALE_TAGGING_REVISION = (
    "this revision does not match the tag statement's current evidence. Nothing was changed. "
    "Run review tagging show and check again."
)


@dataclass(frozen=True)
class Tag:
    tag_id: int
    name: str


@dataclass(frozen=True)
class TaggingMade:
    tag_statement_id: str
    names: tuple[str, ...]
    bound_record_count: int


@dataclass(frozen=True)
class TaggingUndone:
    restored: str | None
    newly_unsettled_transactions: int


TAGGINGS = StatementKind(
    TAG_STATEMENTS,
    StatementRefusals(
        unsettled=lambda ids: (TAGS_UNSETTLED if ", " in ids
                               else TAGS_ALONE_UNSETTLED).format(statements=ids),
        already_applies=lambda applying: ALREADY_TAGGED.format(statement=applying),
        unchanged=TAGS_UNCHANGED,
        supersedes_not_here=TAGGING_SUPERSEDES_NOT_HERE,
        not_found=TAGGING_NOT_FOUND,
        wrong_account=TAGGING_WRONG_ACCOUNT,
        not_active=TAGGING_NOT_ACTIVE,
        superseded=lambda newer: TAGGING_SUPERSEDED.format(newer=newer),
        superseded_in_chain=lambda newer, newest: TAGGING_SUPERSEDED_IN_CHAIN.format(
            newer=newer, newest=newest),
        stale_revision=STALE_TAGGING_REVISION,
    ),
    lambda conn, statement: tagging_undo_outlook(conn, statement).revision,
    lambda conn, _: write_tag_effects(conn),
)


def list_tags(conn: sqlite3.Connection) -> list[Tag]:
    return [Tag(*row) for row in conn.execute("SELECT id, name FROM tag ORDER BY name, id")]


def find_tag(conn: sqlite3.Connection, name: str) -> Tag | None:
    row = conn.execute("SELECT id, name FROM tag WHERE name = ?", (name,)).fetchone()
    return row and Tag(*row)


def add_tag(conn: sqlite3.Connection, name: str) -> Tag:
    if not name or name != name.strip() or "," in name:
        raise DecisionRefused(TAG_NAME_INVALID)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if find_tag(conn, name) is not None:
            raise DecisionRefused(TAG_EXISTS)
        tag_id = conn.execute("INSERT INTO tag (name) VALUES (?)", (name,)).lastrowid
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return Tag(tag_id, name)


def tag_transaction(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    tag_names: tuple[str, ...],
    rules: MatchingRules = DEFAULT_RULES,
    supersedes: str | None = None,
    supersedes_revision: str | None = None,
) -> TaggingMade:
    """State a transaction's whole set of tags, empty for none, binding every record it holds
    now, as a categorization does (D-063, D-073 point 5)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        found = [find_tag(conn, name) for name in tag_names]

        def refuse_unknown_tag():
            if None in found:
                raise DecisionRefused(TAG_UNKNOWN)

        statement_id, bound_record_count = make_statement(
            conn, TAGGINGS, account_id, transaction_id, revision,
            None if None in found else canonical(tag.tag_id for tag in found), rules,
            supersedes, supersedes_revision, refuse_unknown_value=refuse_unknown_tag,
            refuse_misfit=lambda: None,
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return TaggingMade(statement_id, tuple(sorted({tag.name for tag in found})),
                       bound_record_count)


def undo_tagging(conn: sqlite3.Connection, account_id: str, statement_id: str, revision: str,
                 rules: MatchingRules = DEFAULT_RULES) -> TaggingUndone:
    """Stop a tag statement applying, keeping it on record, and restore anything it superseded."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = TaggingUndone(*undo_statement(conn, TAGGINGS, account_id, statement_id,
                                               revision, rules))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result
