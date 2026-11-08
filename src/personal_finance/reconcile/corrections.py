"""Writing value corrections. See decisions.md D-049.

Every command checks everything under one write lock and either commits with the account's
corrected values rewritten or changes nothing. A correction moves no record, so nothing is
derived again. Refusals repeat no value they were given.
"""

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date

from personal_finance.money import MoneyParseError, parse_cents
from personal_finance.reconcile.apply import is_current
from personal_finance.reconcile.correction_effects import (
    CORRECTABLE_FIELDS,
    FIELD_APPLIED,
    load_active_corrections,
    unsettled_correction_fields,
    write_correction_effects,
)
from personal_finance.reconcile.decisions import STALE_ACCOUNT, DecisionRefused
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.supersession import STATE_ACTIVE, STATE_SUPERSEDED
from personal_finance.reports.correction_evidence import correction_undo_outlook, load_correction
from personal_finance.reports.review_evidence import load_merge_evidence, transaction_revision

FIELD_UNSUPPORTED = (
    "only amount, transaction_date, posting_date and description can be corrected. Settlement "
    "status and external IDs cannot. Nothing was changed."
)
AMOUNT_INVALID = (
    "the corrected amount is not an exact amount in dollars and cents. Nothing was changed."
)
DATE_INVALID = "the corrected date must be written YYYY-MM-DD. Nothing was changed."
DESCRIPTION_BLANK = (
    "the corrected description is blank, and a correction cannot clear a value. Nothing was "
    "changed."
)
TRANSACTION_NOT_FOUND = (
    "transaction not found. A later import or decision can retire one: run transactions"
)
TRANSACTION_WRONG_ACCOUNT = "this transaction belongs to another account. Nothing was changed."
STALE_TRANSACTION_REVISION = (
    "this revision does not match the transaction's current evidence. Nothing was changed. "
    "Run review transaction show and check the evidence again."
)
CHANGES_NOTHING = (
    "this value is what the transaction already shows for this field, so there is nothing to "
    "correct. Nothing was changed."
)
FIELD_ALREADY_CORRECTED = (
    "correction {correction} already applies to this field of this transaction. Nothing was "
    "changed. To replace it, inspect it with review correction show, then correct again naming "
    "it with --supersedes."
)
FIELD_UNSETTLED = (
    "corrections {corrections} bind this field of this transaction, and they disagree, lost "
    "their basis or are several, so the source value is used. Nothing was changed. Undo all but "
    "one of them first, one at a time."
)
CORRECTION_NOT_FOUND = "correction not found. Run review corrections."
CORRECTION_WRONG_ACCOUNT = "this correction belongs to another account. Nothing was changed."
CORRECTION_NOT_ACTIVE = "this correction has already been undone. Nothing was changed."
CORRECTION_SUPERSEDED = (
    "this correction is superseded by correction {newer}, so it does not apply now. Nothing was "
    "changed. Undo that correction instead, which restores this one."
)
CORRECTION_SUPERSEDED_IN_CHAIN = (
    "this correction is superseded by correction {newer}, which is superseded in turn, so it "
    "does not apply now. Nothing was changed. Only the newest correction of the chain, {newest}, "
    "can be undone or superseded, and each undo restores the one before it."
)
SUPERSEDES_OTHER_FIELD = (
    "the correction named with --supersedes corrects another field. Nothing was changed."
)
SUPERSEDES_NOT_HERE = (
    "the correction named with --supersedes does not apply to this transaction. Nothing was "
    "changed."
)
STALE_CORRECTION_REVISION = (
    "this revision does not match the correction's current evidence. Nothing was changed. Run "
    "review correction show and check again."
)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class CorrectionMade:
    correction_id: str
    field: str
    bound_record_count: int


@dataclass(frozen=True)
class CorrectionUndone:
    # The correction this one superseded, which applies again.
    restored: str | None
    # Fields of transactions that are left on their source value by this undo, and were not before.
    newly_unsettled_fields: int


def parsed_corrected_value(field: str, value_text: str) -> int | str:
    """The value as stored, or a refusal that does not repeat it."""
    if field not in CORRECTABLE_FIELDS:
        raise DecisionRefused(FIELD_UNSUPPORTED)
    return parsed_typed_value(field, value_text, AMOUNT_INVALID, DATE_INVALID, DESCRIPTION_BLANK)


def parsed_typed_value(field: str, value_text: str, amount_invalid: str, date_invalid: str,
                       description_blank: str) -> int | str:
    """A value a person typed for a field, as stored, or a refusal that does not repeat it.

    Shared by corrections (D-049) and completions (D-050), which word their refusals apart.
    """
    if field == "amount":
        try:
            cents = parse_cents(value_text)
        except MoneyParseError:
            raise DecisionRefused(amount_invalid) from None
        if cents is None:
            raise DecisionRefused(amount_invalid)
        return cents
    if field == "description":
        if not value_text.strip():
            raise DecisionRefused(description_blank)
        return value_text
    try:
        if not _ISO_DATE.fullmatch(value_text):
            raise ValueError
        date.fromisoformat(value_text)
    except ValueError:
        raise DecisionRefused(date_invalid) from None
    return value_text


def correct_value(
    conn: sqlite3.Connection,
    account_id: str,
    transaction_id: str,
    revision: str,
    field: str,
    value_text: str,
    rules: MatchingRules = DEFAULT_RULES,
    supersedes: str | None = None,
    supersedes_revision: str | None = None,
) -> CorrectionMade:
    """Record one field's corrected value for the event a transaction's records describe.

    It binds every record of the transaction now (D-049). supersedes names the one correction
    applying to that field there, with its undo token.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _correct(conn, account_id, transaction_id, revision, field, value_text, rules,
                          supersedes, supersedes_revision)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _correct(conn, account_id, transaction_id, revision, field, value_text, rules, supersedes,
             supersedes_revision) -> CorrectionMade:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    corrected_value = parsed_corrected_value(field, value_text)
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
        if superseded.field != field:
            raise DecisionRefused(SUPERSEDES_OTHER_FIELD)

    entry = merge.transaction
    record_ids = {record.record_id for record in entry.records}
    applying = [
        correction for correction in load_active_corrections(conn, account_id)
        if correction.field == field and correction.bound_record_ids & record_ids
    ]
    applying_ids = sorted(correction.correction_id for correction in applying)
    field_state = next(
        (correction.field_state for correction in entry.corrections if correction.field == field),
        None,
    )
    if len(applying) > 1 or (applying and field_state != FIELD_APPLIED):
        raise DecisionRefused(FIELD_UNSETTLED.format(corrections=", ".join(applying_ids)))
    if superseded is not None and superseded.correction_id not in applying_ids:
        raise DecisionRefused(SUPERSEDES_NOT_HERE)
    if applying and superseded is None:
        raise DecisionRefused(FIELD_ALREADY_CORRECTED.format(correction=applying_ids[0]))
    shown_now = applying[0].corrected_value if applying else _source_value(entry, field)
    if corrected_value == shown_now:
        raise DecisionRefused(CHANGES_NOTHING)

    correction_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO value_correction (id, account_id, field, corrected_amount_cents,
                                         corrected_text, target_transaction_id, target_revision,
                                         supersedes_correction_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (correction_id, account_id, field,
         corrected_value if field == "amount" else None,
         corrected_value if field != "amount" else None,
         transaction_id, revision, superseded and superseded.correction_id),
    )
    conn.executemany(
        "INSERT INTO value_correction_record (correction_id, source_record_id) VALUES (?, ?)",
        [(correction_id, record_id) for record_id in sorted(record_ids)],
    )
    _record_correction_event(conn, correction_id, "made")
    write_correction_effects(conn, account_id)
    return CorrectionMade(correction_id, field, len(record_ids))


def _source_value(entry, field):
    """The primary source's value for a field (D-030)."""
    return entry.amount_cents if field == "amount" else getattr(entry, field)


def _checked_for_replacing(conn, account_id, correction_id, revision):
    """A correction being superseded or undone, checked as D-043 checks a decision."""
    correction = load_correction(conn, correction_id)
    if correction is None:
        raise DecisionRefused(CORRECTION_NOT_FOUND)
    if correction.account_id != account_id:
        raise DecisionRefused(CORRECTION_WRONG_ACCOUNT)
    if correction.state == STATE_SUPERSEDED:
        if correction.newest_of_chain != correction.superseded_by:
            raise DecisionRefused(CORRECTION_SUPERSEDED_IN_CHAIN.format(
                newer=correction.superseded_by, newest=correction.newest_of_chain
            ))
        raise DecisionRefused(CORRECTION_SUPERSEDED.format(newer=correction.superseded_by))
    if correction.state != STATE_ACTIVE:
        raise DecisionRefused(CORRECTION_NOT_ACTIVE)
    if correction_undo_outlook(conn, correction).revision != revision:
        raise DecisionRefused(STALE_CORRECTION_REVISION)
    return correction


def undo_correction(
    conn: sqlite3.Connection,
    account_id: str,
    correction_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> CorrectionUndone:
    """Stop a correction applying, keeping it on record, and restore anything it superseded.

    Corrections constrain no identity, so this never refuses for contradiction. It says when it
    leaves a field on its source value (D-049).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _undo_correction(conn, account_id, correction_id, revision, rules)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _undo_correction(conn, account_id, correction_id, revision, rules) -> CorrectionUndone:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    correction = _checked_for_replacing(conn, account_id, correction_id, revision)
    unsettled_before = unsettled_correction_fields(conn, account_id)
    _record_correction_event(conn, correction_id, "undone")
    write_correction_effects(conn, account_id)
    newly_unsettled = unsettled_correction_fields(conn, account_id) - unsettled_before
    return CorrectionUndone(correction.supersedes_correction_id, len(newly_unsettled))


def _record_correction_event(conn, correction_id, event) -> None:
    conn.execute(
        "INSERT INTO value_correction_event (correction_id, event) VALUES (?, ?)",
        (correction_id, event),
    )
