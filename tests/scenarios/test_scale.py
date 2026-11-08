"""Candidate discovery on larger synthetic data (A39).

These check the amount of work, which is repeatable, rather than elapsed time. The
measured timings are in docs/benchmarks.md. The claims hold for these shapes only:
cost also depends on overlapping documents and on similar descriptions in one block.
"""

from datetime import date, timedelta

import pytest

from personal_finance.reconcile.cross_document import Document, Record, derive
from personal_finance.reconcile.rules import DEFAULT_RULES

DOCUMENTS = [Document(name, name.ljust(64, "0")) for name in ("a", "b", "c")]


def dense(rows_per_document):
    """One merchant and amount, ten rows a day, in three overlapping documents."""
    start = date(2024, 1, 1)
    return [
        Record(
            f"{document.id}{index}",
            document.id,
            index,
            -500,
            posting_date=(start + timedelta(days=index // 10)).isoformat(),
            description="SYNTHETIC CAFE",
            settlement_status="posted",
        )
        for document in DOCUMENTS
        for index in range(rows_per_document)
    ]


def ordinary(rows_per_document):
    """Mostly unrelated rows, with amounts and merchants that rarely repeat."""
    start = date(2024, 1, 1)
    return [
        Record(
            f"{document.id}{index}",
            document.id,
            index,
            -(100 + index * 7 % 9973),
            posting_date=(start + timedelta(days=index % 700)).isoformat(),
            description=f"SYNTHETIC MERCHANT{index % 400:04d}",
            settlement_status="posted",
        )
        for document in DOCUMENTS
        for index in range(rows_per_document)
    ]


@pytest.mark.parametrize("shape", [dense, ordinary])
def test_a39_work_grows_in_step_with_rows_for_these_shapes(shape):
    small = derive(DOCUMENTS, shape(4_000), [], DEFAULT_RULES).candidate_steps
    large = derive(DOCUMENTS, shape(8_000), [], DEFAULT_RULES).candidate_steps
    assert large <= 2.2 * max(small, 1)


def test_a39_dense_data_does_no_all_pairs_work():
    rows = dense(10_000)
    result = derive(DOCUMENTS, rows, [], DEFAULT_RULES)
    assert result.candidate_steps <= 5 * len(rows)


def test_a39_dense_groups_store_members_rather_than_pairs():
    rows = dense(10_000)
    result = derive(DOCUMENTS, rows, [], DEFAULT_RULES)

    memberships = sum(len(item.members) for item in result.items)
    distinct = {member for item in result.items for member in item.members}
    assert len(distinct) == len(rows)
    assert memberships <= 2 * len(rows)
