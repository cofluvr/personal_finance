"""Flags rows in one document that may be one event. See decisions.md D-021.

This never merges anything. Cross-document matching is a separate step.
"""

from collections import defaultdict
from datetime import date

from personal_finance.ingest.layouts import ParsedRow

PENDING_POSTED_WINDOW_DAYS = 3
RULE_SAME_DOCUMENT_PENDING_POSTED = "same_document_pending_posted"


def find_candidate_groups(rows: list[tuple[str, ParsedRow]]) -> list[tuple[str, list[str]]]:
    """Return (rule, transaction IDs) for each group of possible duplicates."""
    return _repeated_external_ids(rows) + _pending_and_posted(rows)


def _repeated_external_ids(rows):
    by_id = defaultdict(list)
    for transaction_id, row in rows:
        if row.external_id is not None:
            by_id[row.external_id].append(transaction_id)
    return [
        ("same_document_repeated_external_id", members)
        for members in by_id.values()
        if len(members) > 1
    ]


def _pending_and_posted(rows):
    by_event = defaultdict(list)
    for item in rows:
        row = item[1]
        by_event[row.amount_cents, (row.description or "").casefold()].append(item)

    groups = []
    for items in by_event.values():
        pending = [item for item in items if item[1].settlement_status == "pending"]
        posted = [item for item in items if item[1].settlement_status == "posted"]
        members = {
            item[0]
            for left in pending
            for right in posted
            if _days_apart(left[1], right[1]) <= PENDING_POSTED_WINDOW_DAYS
            for item in (left, right)
        }
        if members:
            groups.append((RULE_SAME_DOCUMENT_PENDING_POSTED, sorted(members)))
    return groups


def _days_apart(left: ParsedRow, right: ParsedRow) -> int:
    first = date.fromisoformat(left.transaction_date or left.posting_date)
    second = date.fromisoformat(right.transaction_date or right.posting_date)
    return abs((first - second).days)
