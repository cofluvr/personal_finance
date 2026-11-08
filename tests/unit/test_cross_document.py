"""The derivation as a pure function, using synthetic records only."""

from dataclasses import replace
from datetime import date, timedelta

from personal_finance.reconcile.cross_document import (
    PRIMARY_CRITERIA,
    Document,
    Record,
    UnresolvedRecord,
    deciding_criterion,
    derive,
    primary_rank,
)
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

    def test_a_record_with_a_description_is_preferred(self):
        result = outcome(
            self.documents,
            [row("1", "a", external_id="X", description=None), row("2", "b", external_id="X")],
        )
        assert result.groups[0].primary_record_id == "2"

    def test_the_deciding_criterion_is_the_first_that_differs(self):
        def rank(status="posted", transaction="2026-01-09", posting="2026-01-10", text="X", row=1,
                 completed=False):
            return primary_rank(status, transaction, posting, text, "a" * 64, row,
                                completed_by_hand=completed)

        assert deciding_criterion(rank(), rank(completed=True)) == PRIMARY_CRITERIA[0]
        assert deciding_criterion(rank(), rank(status="unknown")) == PRIMARY_CRITERIA[1]
        assert deciding_criterion(rank(), rank(posting=None)) == PRIMARY_CRITERIA[2]
        assert deciding_criterion(rank(), rank(text=None)) == PRIMARY_CRITERIA[3]
        assert deciding_criterion(rank(), rank(row=2)) == PRIMARY_CRITERIA[4]
        # A record read from the source wins even over a posted, fuller record completed by hand.
        assert rank(status="pending", posting=None, text=None) < rank(completed=True)

    def test_the_choice_does_not_depend_on_input_order(self):
        rows = [row("1", "a", external_id="X"), row("2", "b", external_id="X")]
        forward = outcome(self.documents, rows).groups[0].primary_record_id
        backward = outcome(list(reversed(self.documents)), list(reversed(rows)))
        assert backward.groups[0].primary_record_id == forward == "1"


def declared(name, start="2026-01-01", end="2026-01-31", basis="posting", **fields):
    fields.setdefault("id_guarantee", "none")
    return doc(
        name,
        coverage_kind="complete",
        coverage_start=start,
        coverage_end=end,
        date_basis=basis,
        evidence="user_declared",
        **fields,
    )


def metadata(name, start="2026-01-01", end="2026-01-31", basis="posting", **fields):
    fields.setdefault("id_guarantee", "none")
    return doc(
        name,
        coverage_kind="complete",
        coverage_start=start,
        coverage_end=end,
        date_basis=basis,
        evidence="document_metadata",
        **fields,
    )


class TestExactPairing:
    def test_a_match_inside_two_complete_claims_is_confident(self):
        result = outcome([declared("a"), declared("b")], [row("1", "a"), row("2", "b")])
        assert merged(result) == {("1", "2")}

    def test_two_rows_against_three_give_exactly_three_transactions(self):
        rows = [row(f"a{i}", "a", i) for i in (1, 2)] + [row(f"b{i}", "b", i) for i in (1, 2, 3)]
        result = outcome([declared("a"), declared("b")], rows)
        assert len(result.groups) == 3
        assert merged(result) == {("a1", "b1"), ("a2", "b2")}

    def test_each_transaction_holds_at_most_one_row_per_document(self):
        rows = [row(f"{name}{i}", name, i) for name in "abc" for i in (1, 2)]
        result = outcome([declared(name) for name in "abc"], rows)
        by_record = {record.id: record for record in rows}
        for group in result.groups:
            sources = [by_record[record_id].document_id for record_id in group.record_ids]
            assert len(sources) == len(set(sources))
        assert len(result.groups) == 2

    def test_a_user_declared_end_date_is_confident_on_a_multi_day_overlap(self):
        documents = [declared("a", "2026-01-01", "2026-01-31"), declared("b", "2026-01-15", "2026-01-31")]
        rows = [row("1", "a", posting_date="2026-01-31"), row("2", "b", posting_date="2026-01-31")]
        assert merged(outcome(documents, rows)) == {("1", "2")}

    def test_a_declared_interval_needs_no_generation_date(self):
        documents = [declared("a", generated_on=None), declared("b", generated_on="2026-01-31")]
        rows = [row("1", "a", posting_date="2026-01-31"), row("2", "b", posting_date="2026-01-31")]
        assert merged(outcome(documents, rows)) == {("1", "2")}

    def test_a_single_day_overlap_is_never_confident_without_an_id(self):
        documents = [declared("a", "2026-01-01", "2026-01-10"), declared("b", "2026-01-10", "2026-01-20")]
        assert merged(outcome(documents, [row("1", "a"), row("2", "b")])) == set()

    def test_a_single_day_claim_on_both_sides_is_not_confident(self):
        documents = [declared("a", "2026-01-10", "2026-01-10"), declared("b", "2026-01-10", "2026-01-10")]
        assert merged(outcome(documents, [row("1", "a"), row("2", "b")])) == set()

    def test_metadata_end_date_without_a_generation_date_is_not_confident(self):
        rows = [row("1", "a", posting_date="2026-01-31"), row("2", "b", posting_date="2026-01-31")]
        assert merged(outcome([metadata("a"), metadata("b")], rows)) == set()

    def test_metadata_end_date_generated_that_day_is_not_confident(self):
        documents = [metadata("a", generated_on="2026-01-31"), metadata("b", generated_on="2026-02-02")]
        rows = [row("1", "a", posting_date="2026-01-31"), row("2", "b", posting_date="2026-01-31")]
        assert merged(outcome(documents, rows)) == set()

    def test_metadata_end_date_is_confident_once_generation_shows_it_passed(self):
        documents = [metadata("a", generated_on="2026-02-01"), metadata("b", generated_on="2026-02-02")]
        rows = [row("1", "a", posting_date="2026-01-31"), row("2", "b", posting_date="2026-01-31")]
        assert merged(outcome(documents, rows)) == {("1", "2")}

    def test_dates_after_a_metadata_generation_date_do_not_establish_coverage(self):
        documents = [metadata("a", generated_on="2026-01-20"), declared("b")]
        for day, expected in (("2026-01-19", {("1", "2")}), ("2026-01-20", set()), ("2026-01-25", set())):
            rows = [row("1", "a", posting_date=day), row("2", "b", posting_date=day)]
            assert merged(outcome(documents, rows)) == expected

    def test_the_restriction_does_not_reach_a_user_declaration(self):
        documents = [declared("a", generated_on="2026-01-20"), declared("b")]
        rows = [row("1", "a", posting_date="2026-01-25"), row("2", "b", posting_date="2026-01-25")]
        assert merged(outcome(documents, rows)) == {("1", "2")}

    def test_an_effective_overlap_of_one_day_is_a_single_day_overlap(self):
        documents = [metadata("a", "2026-01-01", "2026-01-11"), declared("b", "2026-01-10", "2026-01-20")]
        assert merged(outcome(documents, [row("1", "a"), row("2", "b")])) == set()

    def test_unknown_and_partial_coverage_are_not_confident(self):
        partial = doc("b", coverage_kind="partial", id_guarantee="none")
        for other in (partial, doc("b", id_guarantee="none")):
            assert merged(outcome([declared("a"), other], [row("1", "a"), row("2", "b")])) == set()

    def test_a_dated_partial_claim_is_not_confident(self):
        partial = doc(
            "b", coverage_kind="partial", coverage_start="2026-01-01", coverage_end="2026-01-31",
            date_basis="posting", evidence="document_metadata", id_guarantee="none",
        )
        result = outcome([declared("a"), partial], [row("1", "a"), row("2", "b")])
        assert merged(result) == set()
        assert result.items[0].reasons == ("coverage_partial",)

    def test_a_row_before_a_claim_starts_is_not_confident(self):
        documents = [declared("a"), declared("b", "2026-01-05", "2026-01-31")]
        rows = [row("1", "a", posting_date="2026-01-02"), row("2", "b", posting_date="2026-01-02")]
        assert merged(outcome(documents, rows)) == set()

    def test_different_date_bases_are_not_confident(self):
        documents = [declared("a"), declared("b", basis="transaction")]
        rows = [row(name, name, transaction_date="2026-01-10") for name in "ab"]
        assert merged(outcome(documents, rows)) == set()

    def test_a_row_outside_either_claim_is_not_confident(self):
        documents = [declared("a"), declared("b", "2026-01-01", "2026-01-05")]
        assert merged(outcome(documents, [row("1", "a"), row("2", "b")])) == set()

    def test_a_row_without_a_date_on_the_basis_is_not_confident(self):
        documents = [declared("a", basis="transaction"), declared("b", basis="transaction")]
        assert merged(outcome(documents, [row("1", "a"), row("2", "b")])) == set()

    def test_pending_rows_need_a_claim_that_includes_them(self):
        pending = {"settlement_status": "pending", "transaction_date": "2026-01-10", "posting_date": None}
        rows = [row("1", "a", **pending), row("2", "b", **pending)]
        covered = [declared(name, basis="transaction", pending_covered=True) for name in "ab"]
        excluded = [declared(name, basis="transaction") for name in "ab"]
        assert merged(outcome(covered, rows)) == {("1", "2")}
        assert merged(outcome(excluded, rows)) == set()

    def test_unknown_status_can_pair_with_posted_on_coverage_evidence(self):
        rows = [row("1", "a", settlement_status="unknown"), row("2", "b")]
        result = outcome([declared("a"), declared("b")], rows)
        assert merged(result) == {("1", "2")}
        assert result.groups[0].primary_record_id == "2"

    def test_a_blank_description_never_pairs(self):
        rows = [row("1", "a", description=None), row("2", "b", description=None)]
        assert merged(outcome([declared("a"), declared("b")], rows)) == set()

    def test_a_reliable_id_row_never_pairs_with_an_id_less_row(self):
        documents = [declared("a", id_guarantee="stable_unique"), declared("b")]
        rows = [row("1", "a", external_id="X"), row("2", "b")]
        assert merged(outcome(documents, rows)) == set()

    def test_an_unreliable_id_is_ignored_for_pairing(self):
        rows = [row("1", "a", external_id="X"), row("2", "b", external_id="Y")]
        assert merged(outcome([declared("a"), declared("b")], rows)) == {("1", "2")}


class TestUnresolvedRows:
    documents = [declared("a"), declared("b")]
    rows = [row("1", "a"), row("2", "b")]

    def assert_blocks(self, expected, **fields):
        blocker = UnresolvedRecord("a", **fields)
        assert (merged(outcome(self.documents, self.rows, [blocker])) == set()) is expected

    def test_a_row_with_nothing_known_blocks(self):
        self.assert_blocks(True)

    def test_a_row_on_that_date_with_no_amount_blocks(self):
        self.assert_blocks(True, posting_date="2026-01-10", description="SYNTHETIC CAFE")

    def test_a_row_on_another_date_does_not_block(self):
        self.assert_blocks(False, posting_date="2026-01-11")

    def test_a_row_with_a_different_amount_does_not_block(self):
        self.assert_blocks(False, posting_date="2026-01-10", amount_cents=-999)

    def test_a_row_for_another_merchant_does_not_block(self):
        self.assert_blocks(False, posting_date="2026-01-10", description="SYNTHETIC GROCER")

    def test_a_row_with_an_unknown_date_but_matching_amount_blocks(self):
        self.assert_blocks(True, amount_cents=-500, description="SYNTHETIC CAFE")

    def test_a_row_in_an_uninvolved_document_does_not_block(self):
        blocker = UnresolvedRecord("c")
        documents = self.documents + [declared("c")]
        assert merged(outcome(documents, self.rows, [blocker])) == {("1", "2")}

    def test_a_reliable_id_match_ignores_unresolved_rows(self):
        documents = [doc("a"), doc("b")]
        rows = [row("1", "a", external_id="X"), row("2", "b", external_id="X")]
        assert merged(outcome(documents, rows, [UnresolvedRecord("a")])) == {("1", "2")}


def days_from(start, count):
    first = date.fromisoformat(start)
    return [(first + timedelta(days=offset)).isoformat() for offset in range(count)]


def plain(name, **fields):
    return doc(name, id_guarantee="none", **fields)


def shares_an_item(result, left, right):
    return any(
        {(left,), (right,)} <= set(item.members) for item in result.items
    )


class TestCandidates:
    documents = [plain("a"), plain("b")]

    def test_no_counterpart_means_no_candidate(self):
        assert outcome(self.documents, [row("1", "a")]).items == ()

    def test_same_date_and_amount_with_different_merchants_is_no_candidate(self):
        rows = [row("1", "a"), row("2", "b", description="SYNTHETIC GROCER")]
        assert outcome(self.documents, rows).items == ()

    def test_a_blank_description_is_no_evidence(self):
        rows = [row("1", "a", description=None), row("2", "b", description=None)]
        assert outcome(self.documents, rows).items == ()

    def test_a_different_amount_or_direction_is_no_candidate(self):
        assert outcome(self.documents, [row("1", "a"), row("2", "b", amount=-501)]).items == ()
        assert outcome(self.documents, [row("1", "a"), row("2", "b", amount=500)]).items == ()

    def test_a_similar_description_within_the_window_is_flagged_and_never_merged(self):
        rows = [
            row("1", "a", description="SQ *SYNTHETIC CAFE #1042"),
            row("2", "b", posting_date="2026-01-13"),
        ]
        result = outcome(self.documents, rows)
        assert merged(result) == set()
        assert result.items[0].rule == "cross_document_candidates"
        assert result.items[0].reasons == ("similar_description",)

    def test_the_window_boundary_is_inclusive_and_configurable(self):
        inside = [row("1", "a"), row("2", "b", posting_date="2026-01-13")]
        outside = [row("1", "a"), row("2", "b", posting_date="2026-01-14")]
        assert outcome(self.documents, inside).items
        assert not outcome(self.documents, outside).items
        wider = replace(DEFAULT_RULES, date_window_days=4)
        assert outcome(self.documents, outside, rules=wider).items

    def test_rows_in_one_document_are_not_candidates_for_each_other(self):
        assert outcome(self.documents, [row("1", "a", 1), row("2", "a", 2)]).items == ()

    def test_identical_rows_form_one_group_with_the_coverage_reason(self):
        rows = [row(f"a{i}", "a", i) for i in (1, 2)] + [row(f"b{i}", "b", i) for i in (1, 2, 3)]
        result = outcome([plain("a"), declared("b")], rows)
        assert merged(result) == set()
        assert len(result.items) == 1
        assert len(result.items[0].members) == 5
        assert result.items[0].reasons == ("coverage_unknown",)

    def test_the_extra_row_of_a_justified_pairing_is_not_flagged(self):
        rows = [row(f"a{i}", "a", i) for i in (1, 2)] + [row(f"b{i}", "b", i) for i in (1, 2, 3)]
        assert outcome([declared("a"), declared("b")], rows).items == ()

    def test_a_third_uncovered_document_is_flagged_against_merged_rows(self):
        documents = [declared("a"), declared("b"), plain("c")]
        result = outcome(documents, [row("1", "a"), row("2", "b"), row("3", "c")])
        assert merged(result) == {("1", "2")}
        assert flagged(result) == {frozenset({("1", "2"), ("3",)})}

    def test_different_ids_in_a_guaranteed_namespace_are_never_candidates(self):
        documents = [doc("a"), doc("b")]
        rows = [row("1", "a", external_id="X"), row("2", "b", external_id="Y")]
        assert outcome(documents, rows).items == ()

    def test_different_ids_without_the_uniqueness_guarantee_prove_nothing(self):
        documents = [doc("a", id_guarantee="stable"), doc("b", id_guarantee="stable")]
        rows = [row("1", "a", external_id="X"), row("2", "b", external_id="Y")]
        assert outcome(documents, rows).items

    def test_an_id_bearing_row_against_an_id_less_row_can_only_be_a_candidate(self):
        documents = [doc("a"), plain("b")]
        result = outcome(documents, [row("1", "a", external_id="X"), row("2", "b")])
        assert merged(result) == set()
        assert result.items

    def test_similarity_never_merges_even_under_complete_coverage(self):
        rows = [row("1", "a", description="SQ *SYNTHETIC CAFE"), row("2", "b")]
        result = outcome([declared("a"), declared("b")], rows)
        assert merged(result) == set()
        assert result.items


class TestRepeatedPurchases:
    documents = [plain("a"), plain("b")]

    def test_a_same_date_counterpart_does_not_hide_a_near_date_one(self):
        rows = [
            row("a1", "a", posting_date="2026-01-05"),
            row("b1", "b", 1, posting_date="2026-01-05"),
            row("b2", "b", 2, posting_date="2026-01-06"),
        ]
        result = outcome(self.documents, rows)
        assert shares_an_item(result, "a1", "b1")
        assert shares_an_item(result, "a1", "b2")

    def test_a_posting_lag_keeps_every_row_in_one_group(self):
        rows = [
            row("a1", "a", 1, posting_date="2026-01-05"),
            row("a2", "a", 2, posting_date="2026-01-06"),
            row("b1", "b", 1, posting_date="2026-01-06"),
            row("b2", "b", 2, posting_date="2026-01-07"),
        ]
        result = outcome(self.documents, rows)
        assert len(result.items) == 1
        assert len(result.items[0].members) == 4

    def test_a_short_run_stays_one_item(self):
        rows = [row(f"{n}{i}", n, i, posting_date=d) for n in "ab" for i, d in enumerate(days_from("2026-01-05", 14), 1)]
        assert len(outcome(self.documents, rows).items) == 1

    def test_daily_purchases_stay_visible_in_bounded_items(self):
        days = days_from("2026-01-01", 30)
        rows = [row(f"{n}{i}", n, i, posting_date=d) for n in "ab" for i, d in enumerate(days, 1)]
        result = outcome(self.documents, rows)

        covered = {member for item in result.items for member in item.members}
        assert len(covered) == 60
        assert 1 < len(result.items) <= 4
        window = DEFAULT_RULES.max_group_span_days + DEFAULT_RULES.date_window_days
        for item in result.items:
            span = date.fromisoformat(item.date_end) - date.fromisoformat(item.date_start)
            assert span.days + 1 <= window

    def test_every_linked_pair_shares_an_item_across_block_edges(self):
        days = days_from("2026-01-01", 40)
        rows = [row(f"{n}{i}", n, i, posting_date=d) for n in "ab" for i, d in enumerate(days, 1)]
        result = outcome(self.documents, rows)
        for left in range(1, 41):
            for right in range(1, 41):
                if abs(left - right) <= DEFAULT_RULES.date_window_days:
                    assert shares_an_item(result, f"a{left}", f"b{right}"), (left, right)

    def test_a_block_edge_follows_the_calendar_not_the_data(self):
        """Ordinals divide into fixed blocks, so adding rows cannot move an edge."""
        span = DEFAULT_RULES.max_group_span_days
        edge = (date.fromisoformat("2026-01-01").toordinal() // span + 1) * span
        day = date.fromordinal(edge)
        days = [(day + timedelta(days=offset)).isoformat() for offset in range(-16, 16)]
        rows = [row(f"{n}{i}", n, i, posting_date=d) for n in "ab" for i, d in enumerate(days, 1)]
        result = outcome(self.documents, rows)

        before = (day - timedelta(days=1)).isoformat()
        assert any(item.date_start == day.isoformat() for item in result.items)
        assert any(item.date_start <= before <= item.date_end and day.isoformat() <= item.date_end
                   for item in result.items)

    def test_rows_near_a_block_edge_sit_in_two_overlapping_items(self):
        days = days_from("2026-01-01", 40)
        rows = [row(f"{n}{i}", n, i, posting_date=d) for n in "ab" for i, d in enumerate(days, 1)]
        result = outcome(self.documents, rows)
        memberships = [member for item in result.items for member in item.members]
        assert len(memberships) > len(set(memberships)) == 80

    def test_dense_rows_do_no_pairwise_work(self):
        days = days_from("2026-01-01", 200)
        rows = [
            row(f"{n}{d}{k}", n, 1000 * position + k, posting_date=d)
            for n in "ab"
            for position, d in enumerate(days)
            for k in range(5)
        ]
        result = outcome(self.documents, rows)
        assert result.candidate_steps <= 3 * len(rows)
