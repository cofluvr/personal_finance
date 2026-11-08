"""The review revision covers all material evidence (D-040)."""

import re
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

import pytest

from personal_finance import cli
from personal_finance.reports.review_evidence import (
    IMMATERIAL_FIELDS,
    OMITTED_WHILE_EMPTY,
    REVISION_VERSION,
    DecidedPair,
    DecidedRecord,
    DocumentEvidence,
    ParsedValues,
    RecordEvidence,
    ReviewEvidence,
    TransactionEvidence,
    review_revision,
    rows_sharing_a_document,
)

SOURCE = Path(cli.__file__).parent / "reconcile" / "cross_document.py"


def record(row=1, digest="a" * 64):
    parsed = ParsedValues(
        "parsed", None, "2026-01-05", "2026-01-06", -650, "SYNTHETIC CAFE", "S-1", "posted"
    )
    return RecordEvidence(
        f"record-{row}", digest, "a.csv", row, ("S-1", "2026-01-05"), parsed, "new_record"
    )


def transaction(row=1):
    return TransactionEvidence(
        f"transaction-{row}", "2026-01-05", "2026-01-06", -650, "SYNTHETIC CAFE", "S-1", "posted",
        ("a" * 64, row), (record(row),),
    )


def document():
    return DocumentEvidence(
        "a" * 64, "a.csv", "synthetic_checking_v1", "1", "2026-02-01", "complete", "2026-01-01",
        "2026-01-31", "posting", "document_metadata", "2026-01-31", False, "namespace",
        "stable_unique",
    )


def decided():
    return DecidedPair(
        "decision", "different_event", (DecidedRecord("a" * 64, "a.csv", 1),), (DecidedRecord("a" * 64, "a.csv", 2),)
    )


def item():
    return ReviewEvidence(
        "issue", "possible_duplicate", "cross_document_candidates", "open",
        ("coverage_unknown",), "2026-01-05", "2026-01-06",
        (transaction(1), transaction(2)), (record(3),), (document(),), False, "account", "A",
        (decided(),),
    )


def changed(value):
    if isinstance(value, bool):
        return not value
    if value is None:
        return "changed"
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return value + "x"
    return (*value, "changed")


def variations(target, path=""):
    """Every leaf field of the evidence, each changed on its own."""
    for field in fields(target):
        value = getattr(target, field.name)
        name = f"{path}{field.name}"
        if is_dataclass(value):
            for leaf, inner in variations(value, f"{name}."):
                yield leaf, replace(target, **{field.name: inner})
        elif isinstance(value, tuple) and value and is_dataclass(value[0]):
            for leaf, inner in variations(value[0], f"{name}."):
                yield leaf, replace(target, **{field.name: (inner, *value[1:])})
        else:
            yield name, replace(target, **{field.name: changed(value)})


CASES = dict(variations(item()))


def test_the_walk_reaches_nested_evidence():
    assert {"reasons", "documents.effective_end", "transactions.amount_cents",
            "transactions.records.parsed.amount_cents", "unresolved.cells",
            "decided.decision_id"} <= set(CASES)


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_field_is_material_or_explicitly_exempt(name):
    same = name.rsplit(".", 1)[-1] in IMMATERIAL_FIELDS
    assert (review_revision(CASES[name]) == review_revision(item())) is same


def test_exempt_fields_are_identifiers_names_and_the_stale_warning_only():
    assert IMMATERIAL_FIELDS == {
        "issue_id", "transaction_id", "record_id", "file_name", "account_stale", "account_id",
        "account_name", "decision_id", "correction_id", "classification_id",
    }


def test_only_corrections_completions_declarations_and_classifications_are_left_out_while_empty():
    assert OMITTED_WHILE_EMPTY == {"corrections", "completion", "declared", "classifications"}


@pytest.mark.parametrize("field", ["transactions", "unresolved", "documents", "decided"])
def test_removing_a_member_changes_the_revision(field):
    fewer = replace(item(), **{field: getattr(item(), field)[1:]})
    assert review_revision(fewer) != review_revision(item())


def test_moving_a_record_between_transactions_changes_the_revision():
    first, second = item().transactions
    merged = replace(first, records=(*first.records, *second.records))
    assert review_revision(replace(item(), transactions=(merged, replace(second, records=())))) != (
        review_revision(item())
    )


def test_the_definition_is_pinned_so_a_change_must_bump_the_version():
    assert REVISION_VERSION == 7
    assert review_revision(item()) == "r7-8f8c8b328e5b7256"


def test_the_token_has_the_documented_form():
    assert re.fullmatch(r"r7-[0-9a-f]{16}", review_revision(item()))


def test_rows_sharing_a_document_ignores_documents_with_one_record():
    other = replace(item(), transactions=(transaction(1),), unresolved=(record(2, "b" * 64),))
    assert rows_sharing_a_document(other) == {}
    assert rows_sharing_a_document(item()) == {"a" * 64: (1, 2, 3)}


def test_every_reason_derive_can_give_has_an_explanation():
    text = SOURCE.read_text()
    reasons = set(re.findall(r'return "([a-z_]+)"', text))
    reasons |= set(re.findall(r'(?:add|\.update)\(\(?"([a-z_]+)"', text))
    reasons |= set(re.findall(r'^REASON_[A-Z_]+ = "([a-z_]+)"', text, re.MULTILINE))
    reasons |= {"similar_description", "external_id_conflict", "external_id_repeated"}
    reasons -= {"pending", "not_pending"}
    assert reasons <= set(cli.REASON_EXPLANATIONS)
    assert len(reasons) >= 10
