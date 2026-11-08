"""Resolving unresolved records: completing or dismissing one, and undoing that. See decisions.md
D-050.

Every command checks everything under one write lock and either commits with the account derived
again or changes nothing. Refusals repeat no value they were given.
"""

import sqlite3
import uuid
from dataclasses import dataclass

from personal_finance.ingest.pipeline import insert_unresolved_issue
from personal_finance.reconcile.apply import (
    RESOLUTION_COMPLETED,
    RESOLUTION_DISMISSED,
    is_current,
    reconcile_account,
)
from personal_finance.reconcile.correction_effects import unsettled_correction_fields
from personal_finance.reconcile.corrections import parsed_typed_value
from personal_finance.reconcile.decisions import (
    ITEM_NOT_FOUND,
    ITEM_WRONG_ACCOUNT,
    STALE_ACCOUNT,
    STALE_REVISION,
    DecisionRefused,
)
from personal_finance.reconcile.rules import DEFAULT_RULES, MatchingRules
from personal_finance.reconcile.supersession import STATE_ACTIVE
from personal_finance.reports.resolution_evidence import (
    binding_entries,
    load_resolution,
    resolution_undo_outlook,
)
from personal_finance.reports.review_evidence import load_review_evidence, review_revision
from personal_finance.reports.totals import account_movement

# The values a completion can supply, in the order records hold them.
COMPLETABLE_FIELDS = ("amount", "transaction_date", "posting_date", "description")

ITEM_NOT_UNRESOLVED = (
    "only unresolved-record items can be completed or dismissed. Nothing was changed."
)
AMOUNT_INVALID = (
    "the completed amount is not an exact amount in dollars and cents. Nothing was changed."
)
DATE_INVALID = "a completed date must be written YYYY-MM-DD. Nothing was changed."
DESCRIPTION_BLANK = (
    "the completed description is blank. Leave it out to keep it missing. Nothing was changed."
)
VALUE_ALREADY_READ = (
    "the {field} of this row was read from the source, and a completion only supplies what could "
    "not be read. Nothing was changed. To change a value that was read, complete the row, then "
    "use review correct."
)
NEEDS_AMOUNT = (
    "no amount could be read from this row, so a completion must supply one with --amount. "
    "Nothing was changed."
)
NEEDS_DATE = (
    "no date could be read from this row, so a completion must supply a transaction or posting "
    "date. Nothing was changed."
)
RESOLUTION_NOT_FOUND = "resolution not found. Run review resolutions."
RESOLUTION_WRONG_ACCOUNT = "this resolution belongs to another account. Nothing was changed."
RESOLUTION_NOT_ACTIVE = "this resolution has already been undone. Nothing was changed."
STALE_RESOLUTION_REVISION = (
    "this revision does not match the resolution's current evidence. Nothing was changed. Run "
    "review resolution show and check again."
)
COMPLETION_BOUND = (
    "the completed record is bound by {entries}, which are not undone. Nothing was changed. Undo "
    "them first, so that nothing binds a record that leaves the ledger."
)


@dataclass(frozen=True)
class Resolved:
    resolution_id: str
    kind: str
    # The transaction now holding a completed record. None for a dismissal.
    transaction_id: str | None
    supplied_fields: tuple[str, ...]
    transactions_before: int
    transactions_after: int
    moved_records: int
    newly_unsettled_correction_fields: int


@dataclass(frozen=True)
class ResolutionUndone:
    kind: str
    # The unresolved item raised again for the record.
    issue_id: str
    transactions_before: int
    transactions_after: int
    moved_records: int
    newly_unsettled_correction_fields: int


def complete_record(
    conn: sqlite3.Connection,
    account_id: str,
    item_id: str,
    revision: str,
    supplied_text_by_field: dict[str, str],
    rules: MatchingRules = DEFAULT_RULES,
) -> Resolved:
    """Supply what the parser could not read from an unresolved record, so that it becomes a
    transaction. Its typed values never make a match (D-050)."""
    return _in_transaction(conn, lambda: _resolve(
        conn, account_id, item_id, revision, RESOLUTION_COMPLETED, supplied_text_by_field, rules
    ))


def dismiss_record(
    conn: sqlite3.Connection,
    account_id: str,
    item_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> Resolved:
    """State that an unresolved record adds no transaction, so it no longer blocks matching."""
    return _in_transaction(conn, lambda: _resolve(
        conn, account_id, item_id, revision, RESOLUTION_DISMISSED, {}, rules
    ))


def _in_transaction(conn, work):
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = work()
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return result


def _resolve(conn, account_id, item_id, revision, kind, supplied_text_by_field, rules) -> Resolved:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    item = load_review_evidence(conn, item_id)
    if item is None:
        raise DecisionRefused(ITEM_NOT_FOUND)
    if item.account_id != account_id:
        raise DecisionRefused(ITEM_WRONG_ACCOUNT)
    if item.kind != "unresolved_record":
        raise DecisionRefused(ITEM_NOT_UNRESOLVED)
    if review_revision(item) != revision:
        raise DecisionRefused(STALE_REVISION)
    (record,) = item.unresolved
    supplied = _checked_completion(record.parsed, supplied_text_by_field) if (
        kind == RESOLUTION_COMPLETED) else (None,) * len(COMPLETABLE_FIELDS)

    before = account_movement(conn, account_id).transactions
    unsettled_before = unsettled_correction_fields(conn, account_id)
    resolution_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO record_resolution (id, account_id, source_record_id, kind,
                                          completed_amount_cents, completed_transaction_date,
                                          completed_posting_date, completed_description,
                                          target_issue_id, target_revision)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (resolution_id, account_id, record.record_id, kind, *supplied, item_id, revision),
    )
    _record_resolution_event(conn, resolution_id, "made")
    # Closing is removal (D-045). An undo raises a new item.
    conn.execute("DELETE FROM review_issue_subject WHERE review_issue_id = ?", (item_id,))
    conn.execute("DELETE FROM review_issue WHERE id = ?", (item_id,))
    result = reconcile_account(conn, account_id, rules)

    holder = conn.execute(
        "SELECT transaction_id FROM transaction_source WHERE source_record_id = ?",
        (record.record_id,),
    ).fetchone()
    return Resolved(
        resolution_id, kind, holder[0] if holder else None,
        tuple(field for field, value in zip(COMPLETABLE_FIELDS, supplied) if value is not None),
        before, account_movement(conn, account_id).transactions, result.moved_records,
        len(unsettled_correction_fields(conn, account_id) - unsettled_before),
    )


def _checked_completion(parsed, supplied_text_by_field) -> tuple:
    """The supplied values in COMPLETABLE_FIELDS order, None where nothing is supplied."""
    read = (parsed.amount_cents, parsed.transaction_date, parsed.posting_date, parsed.description)
    supplied = []
    for field, read_value in zip(COMPLETABLE_FIELDS, read):
        text = supplied_text_by_field.get(field)
        if text is None:
            supplied.append(None)
            continue
        if read_value is not None:
            raise DecisionRefused(VALUE_ALREADY_READ.format(field=field))
        supplied.append(
            parsed_typed_value(field, text, AMOUNT_INVALID, DATE_INVALID, DESCRIPTION_BLANK)
        )
    effective = [read_value if read_value is not None else value
                 for read_value, value in zip(read, supplied)]
    if effective[0] is None:
        raise DecisionRefused(NEEDS_AMOUNT)
    if effective[1] is None and effective[2] is None:
        raise DecisionRefused(NEEDS_DATE)
    return tuple(supplied)


def undo_resolution(
    conn: sqlite3.Connection,
    account_id: str,
    resolution_id: str,
    revision: str,
    rules: MatchingRules = DEFAULT_RULES,
) -> ResolutionUndone:
    """Re-derive from current evidence without this resolution, keeping it on record, and raise the
    record's unresolved item again. This is not a restored snapshot (D-043, D-050)."""
    return _in_transaction(conn, lambda: _undo(conn, account_id, resolution_id, revision, rules))


def _undo(conn, account_id, resolution_id, revision, rules) -> ResolutionUndone:
    if not is_current(conn, account_id, rules):
        raise DecisionRefused(STALE_ACCOUNT)
    resolution = load_resolution(conn, resolution_id)
    if resolution is None:
        raise DecisionRefused(RESOLUTION_NOT_FOUND)
    if resolution.account_id != account_id:
        raise DecisionRefused(RESOLUTION_WRONG_ACCOUNT)
    if resolution.state != STATE_ACTIVE:
        raise DecisionRefused(RESOLUTION_NOT_ACTIVE)
    if resolution_undo_outlook(conn, resolution, rules).revision != revision:
        raise DecisionRefused(STALE_RESOLUTION_REVISION)
    if resolution.kind == RESOLUTION_COMPLETED:
        decisions, corrections, classifications = binding_entries(
            conn, resolution.record.record_id)
        entries = [f"decision {entry}" for entry in decisions]
        entries += [f"correction {entry}" for entry in corrections]
        entries += [f"classification {entry}" for entry in classifications]
        if entries:
            raise DecisionRefused(COMPLETION_BOUND.format(entries=", ".join(entries)))

    before = account_movement(conn, account_id).transactions
    unsettled_before = unsettled_correction_fields(conn, account_id)
    _record_resolution_event(conn, resolution_id, "undone")
    (reason_code,) = conn.execute(
        """SELECT parse.reason_code FROM record_parse parse
           JOIN source_record record ON record.id = parse.source_record_id
           JOIN document_interpretation meaning
               ON meaning.source_document_id = record.source_document_id
              AND meaning.parser_version = parse.parser_version
           WHERE record.id = ?""",
        (resolution.record.record_id,),
    ).fetchone()
    issue_id = insert_unresolved_issue(conn, resolution.record.record_id, reason_code)
    result = reconcile_account(conn, account_id, rules)
    return ResolutionUndone(
        resolution.kind, issue_id, before, account_movement(conn, account_id).transactions,
        result.moved_records,
        len(unsettled_correction_fields(conn, account_id) - unsettled_before),
    )


def _record_resolution_event(conn, resolution_id, event) -> None:
    conn.execute(
        "INSERT INTO record_resolution_event (resolution_id, event) VALUES (?, ?)",
        (resolution_id, event),
    )
