import pytest

from personal_finance.ingest.coverage import UNKNOWN, Coverage, declare_complete, from_metadata
from personal_finance.ingest.errors import ImportFailure


def metadata(**overrides):
    values = {
        "coverage-kind": "complete",
        "coverage-start": "2026-01-01",
        "coverage-end": "2026-01-31",
        "coverage-basis": "posting",
    }
    values.update(overrides)
    return {key: value for key, value in values.items() if value is not None}


def test_no_metadata_is_unknown():
    assert from_metadata({}) is UNKNOWN


def test_complete_metadata():
    assert from_metadata(metadata()) == Coverage(
        "complete", "2026-01-01", "2026-01-31", "posting", "document_metadata"
    )


def test_a_declaration_is_identified_as_user_supplied():
    declared = declare_complete("2026-01-01", "2026-01-31", "transaction")
    assert declared == Coverage("complete", "2026-01-01", "2026-01-31", "transaction", "user_declared")


def test_a_single_day_interval_is_allowed():
    assert declare_complete("2026-01-01", "2026-01-01", "posting").kind == "complete"


def test_partial_metadata_may_have_only_a_start():
    coverage = from_metadata({"coverage-kind": "partial", "coverage-start": "2026-01-01"})
    assert coverage == Coverage("partial", "2026-01-01", None, None, "document_metadata")


@pytest.mark.parametrize(
    "values",
    [
        metadata(**{"coverage-start": None}),
        metadata(**{"coverage-end": None}),
        metadata(**{"coverage-basis": None}),
        metadata(**{"coverage-kind": "mostly"}),
        metadata(**{"coverage-kind": None}),
        metadata(**{"coverage-kind": "unknown"}),
        metadata(**{"coverage-basis": "statement"}),
        metadata(**{"coverage-start": "2026-02-30"}),
        metadata(**{"coverage-start": "01/01/2026"}),
        metadata(**{"coverage-start": "20260101"}),
        metadata(**{"coverage-start": "2026-02-01"}),
    ],
)
def test_incomplete_or_inconsistent_metadata_fails(values):
    with pytest.raises(ImportFailure) as caught:
        from_metadata(values)
    assert caught.value.code == "invalid_coverage_metadata"


@pytest.mark.parametrize(
    "values",
    [
        ("2026-01-31", "2026-01-01", "posting"),
        ("2026-01-01", "2026-13-01", "posting"),
        ("2026-01-01", "2026-01-31", "statement"),
        ("", "2026-01-31", "posting"),
        ("2026-01-01", "", "posting"),
        ("2026-01-01", "2026-01-31", ""),
    ],
)
def test_invalid_declarations_fail(values):
    with pytest.raises(ImportFailure) as caught:
        declare_complete(*values)
    assert caught.value.code == "invalid_coverage_declaration"
