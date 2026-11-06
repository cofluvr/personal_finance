from personal_finance.ingest.layouts import ParsedRow
from personal_finance.reconcile.same_document import find_candidate_groups


def row(status="posted", amount=-650, description="SYNTHETIC CAFE", day="2026-01-05", external_id=None):
    return ParsedRow(
        transaction_date=day,
        amount_cents=amount,
        description=description,
        external_id=external_id,
        settlement_status=status,
    )


def test_identical_rows_of_the_same_status_are_not_flagged():
    assert find_candidate_groups([("a", row()), ("b", row())]) == []


def test_a_repeated_external_id_is_flagged():
    rows = [("a", row(external_id="X")), ("b", row(external_id="X", amount=-100)), ("c", row())]
    assert find_candidate_groups(rows) == [("same_document_repeated_external_id", ["a", "b"])]


def test_pending_and_posted_versions_are_flagged():
    rows = [("a", row("pending")), ("b", row("posted", day="2026-01-08"))]
    assert find_candidate_groups(rows) == [("same_document_pending_posted", ["a", "b"])]


def test_description_case_does_not_hide_a_candidate():
    rows = [("a", row("pending", description="Synthetic Cafe")), ("b", row())]
    assert find_candidate_groups(rows) == [("same_document_pending_posted", ["a", "b"])]


def test_pending_and_posted_too_far_apart_are_not_flagged():
    rows = [("a", row("pending")), ("b", row("posted", day="2026-01-09"))]
    assert find_candidate_groups(rows) == []


def test_different_amounts_are_not_flagged():
    assert find_candidate_groups([("a", row("pending")), ("b", row(amount=-700))]) == []


def test_unknown_status_is_not_treated_as_pending_or_posted():
    assert find_candidate_groups([("a", row("unknown")), ("b", row("posted"))]) == []


def test_only_rows_near_each_other_join_the_group():
    rows = [("a", row("pending")), ("b", row("posted")), ("c", row("posted", day="2026-03-01"))]
    assert find_candidate_groups(rows) == [("same_document_pending_posted", ["a", "b"])]
