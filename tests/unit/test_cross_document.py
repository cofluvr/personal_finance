"""The derivation as a pure function, using synthetic records only."""

from personal_finance.reconcile.cross_document import Document, Record, derive
from personal_finance.reconcile.rules import DEFAULT_RULES


def doc(name, **fields):
    fields.setdefault("id_namespace", "bank")
    fields.setdefault("id_guarantee", "stable_unique")
    return Document(id=name, content_sha256=name.ljust(64, "0"), **fields)


def row(record_id, document, index=1, amount=-500, **fields):
    fields.setdefault("posting_date", "2026-01-10")
    fields.setdefault("description", "SYNTHETIC CAFE")
    fields.setdefault("settlement_status", "posted")
    return Record(record_id, document, index, amount, **fields)


def outcome(documents, records, unresolved=(), rules=DEFAULT_RULES):
    return derive(documents, records, list(unresolved), rules)


def merged(result):
    return {group.record_ids for group in result.groups if len(group.record_ids) > 1}


def flagged(result):
    return {frozenset(item.members) for item in result.items}


class TestReliableIds:
    documents = [doc("a"), doc("b"), doc("c")]

    def test_the_same_id_merges_without_any_coverage(self):
        result = outcome(
            self.documents, [row("1", "a", external_id="X"), row("2", "b", external_id="X")]
        )
        assert merged(result) == {("1", "2")}
        assert result.items == ()

    def test_a_different_description_does_not_conflict(self):
        result = outcome(
            self.documents,
            [
                row("1", "a", external_id="X", description="SYNTHETIC CAFE"),
                row("2", "b", external_id="X", description="UNRELATED WORDS"),
            ],
        )
        assert merged(result) == {("1", "2")}

    def test_a_conflicting_amount_is_flagged_and_never_merged(self):
        result = outcome(
            self.documents,
            [row("1", "a", external_id="X"), row("2", "b", external_id="X", amount=-600)],
        )
        assert merged(result) == set()
        assert flagged(result) == {frozenset({("1",), ("2",)})}
        assert result.items[0].rule == "cross_document_external_id"

    def test_two_agreeing_sources_stay_merged_beside_a_conflicting_one(self):
        result = outcome(
            self.documents,
            [
                row("1", "a", external_id="X"),
                row("2", "b", external_id="X"),
                row("3", "c", external_id="X", amount=-600),
            ],
        )
        assert merged(result) == {("1", "2")}
        assert flagged(result) == {frozenset({("1", "2"), ("3",)})}

    def test_a_date_present_on_both_must_agree(self):
        result = outcome(
            self.documents,
            [
                row("1", "a", external_id="X", posting_date="2026-01-10"),
                row("2", "b", external_id="X", posting_date="2026-01-11"),
            ],
        )
        assert merged(result) == set()

    def test_a_date_missing_from_one_record_is_compatible(self):
        result = outcome(
            self.documents,
            [
                row("1", "a", external_id="X", transaction_date="2026-01-09"),
                row("2", "b", external_id="X", transaction_date=None),
            ],
        )
        assert merged(result) == {("1", "2")}

    def test_pending_conflicts_with_posted_and_with_unknown(self):
        for status in ("posted", "unknown"):
            result = outcome(
                self.documents,
                [
                    row("1", "a", external_id="X", settlement_status="pending"),
                    row("2", "b", external_id="X", settlement_status=status),
                ],
            )
            assert merged(result) == set()

    def test_unknown_does_not_conflict_with_posted(self):
        result = outcome(
            self.documents,
            [
                row("1", "a", external_id="X", settlement_status="unknown"),
                row("2", "b", external_id="X", settlement_status="posted"),
            ],
        )
        assert merged(result) == {("1", "2")}
        assert result.groups[0].primary_record_id == "2"

    def test_an_id_repeated_within_a_document_blocks_that_documents_rows(self):
        result = outcome(
            self.documents,
            [
                row("1", "a", 1, external_id="X"),
                row("2", "a", 2, external_id="X"),
                row("3", "b", external_id="X"),
            ],
        )
        assert merged(result) == set()
        assert flagged(result) == {frozenset({("1",), ("2",), ("3",)})}
        assert result.items[0].reasons == ("external_id_repeated",)

    def test_a_repeat_in_one_document_alone_is_left_to_same_document_flags(self):
        result = outcome(
            self.documents, [row("1", "a", 1, external_id="X"), row("2", "a", 2, external_id="X")]
        )
        assert result.items == ()

    def test_incompatible_chains_stay_wholly_unmerged(self):
        """1 agrees with 2 and with 3, but 2 and 3 conflict: no choice is made."""
        result = outcome(
            self.documents,
            [
                row("1", "a", external_id="X", posting_date=None, transaction_date="2026-01-09",
                    settlement_status="unknown"),
                row("2", "b", external_id="X", transaction_date="2026-01-09", posting_date="2026-01-10"),
                row("3", "c", external_id="X", transaction_date="2026-01-09", posting_date="2026-01-11"),
            ],
        )
        assert merged(result) == set()
        assert flagged(result) == {frozenset({("1",), ("2",), ("3",)})}
        assert result.separation_reasons["1"] == "external_id_conflict"

    def test_ids_only_match_within_a_namespace(self):
        documents = [doc("a"), doc("b", id_namespace="other")]
        result = outcome(documents, [row("1", "a", external_id="X"), row("2", "b", external_id="X")])
        assert merged(result) == set()

    def test_unreliable_ids_never_match_by_themselves(self):
        documents = [doc("a", id_guarantee="none"), doc("b", id_guarantee="none")]
        result = outcome(documents, [row("1", "a", external_id="X"), row("2", "b", external_id="X")])
        assert merged(result) == set()


class TestPrimaryRecord:
    documents = [doc("a"), doc("b")]

    def test_a_record_with_more_dates_is_preferred(self):
        result = outcome(
            self.documents,
            [
                row("1", "a", external_id="X"),
                row("2", "b", external_id="X", transaction_date="2026-01-09"),
            ],
        )
        assert result.groups[0].primary_record_id == "2"

    def test_the_choice_does_not_depend_on_input_order(self):
        rows = [row("1", "a", external_id="X"), row("2", "b", external_id="X")]
        forward = outcome(self.documents, rows).groups[0].primary_record_id
        backward = outcome(list(reversed(self.documents)), list(reversed(rows)))
        assert backward.groups[0].primary_record_id == forward == "1"
