"""Decisions as an input to the derivation, using synthetic records only (D-042, D-044)."""

from dataclasses import replace
from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from personal_finance.reconcile.cross_document import (
    LINK_NEW,
    REASON_BASIS_CHANGED,
    REASON_WITHHELD,
    RULE_CANDIDATES,
    RULE_DECISION,
    RULE_EXTERNAL_ID,
    Constraint,
    Document,
    Record,
    _link_candidates,
    _undecided_parts,
    _Unit,
    derive,
    directly_linked,
)
from personal_finance.reconcile.rules import DEFAULT_RULES


def doc(name, start=None, end=None, **fields):
    if start:
        fields.update(coverage_kind="complete", coverage_start=start, coverage_end=end,
                      date_basis="posting", evidence="user_declared")
    return Document(id=name, content_sha256=name.ljust(64, "0"), **fields)


def row(record_id, document, index=1, amount=-650, day="2026-01-10", **fields):
    fields.setdefault("description", "SYNTHETIC CAFE")
    fields.setdefault("settlement_status", "posted")
    return Record(record_id, document, index, amount, posting_date=day, **fields)


def rejected(left, right, decision="d1"):
    return Constraint(decision, tuple(left), tuple(right))


def outcome(documents, records, *constraints, rules=DEFAULT_RULES):
    return derive(documents, records, [], rules, constraints)


def members(result, rule=None):
    return {
        frozenset(item.members) for item in result.items if rule is None or item.rule == rule
    }


def groups(result):
    return {group.record_ids for group in result.groups}


# Two documents overlap by a single day, so they do not merge, and a third spans both.
NARROW = [doc("a", "2026-01-01", "2026-01-10"), doc("b", "2026-01-10", "2026-01-20")]
WIDE = doc("c", "2026-01-01", "2026-01-20")


class TestCandidates:
    documents = [doc("a"), doc("b"), doc("c")]

    def test_no_constraints_changes_nothing(self):
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        assert outcome(self.documents, records) == derive(self.documents, records, [], DEFAULT_RULES)

    def test_a_rejected_pair_closes_a_two_member_item(self):
        records = [row("1", "a"), row("2", "b")]
        result = outcome(self.documents, records, rejected(["1"], ["2"]))
        assert result.items == ()
        assert groups(result) == {("1",), ("2",)}

    def test_all_members_stay_while_undecided_links_join_them(self):
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        result = outcome(self.documents, records, rejected(["1"], ["2"]))
        assert members(result) == {frozenset({("1",), ("2",), ("3",)})}

    def test_a_member_with_no_undecided_link_leaves_the_item(self):
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        result = outcome(
            self.documents, records, rejected(["1"], ["2"]), rejected(["1"], ["3"], "d2")
        )
        assert members(result) == {frozenset({("2",), ("3",)})}

    def test_every_pair_rejected_closes_the_item(self):
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        result = outcome(
            self.documents, records, rejected(["1"], ["2"]), rejected(["1"], ["3"]),
            rejected(["2"], ["3"]),
        )
        assert result.items == ()

    def test_a_chain_breaks_where_it_is_rejected(self):
        records = [
            row("1", "a", day="2026-01-01"),
            row("2", "b", day="2026-01-04"),
            row("3", "c", day="2026-01-07"),
        ]
        assert members(outcome(self.documents, records)) == {frozenset({("1",), ("2",), ("3",)})}
        result = outcome(self.documents, records, rejected(["1"], ["2"]))
        assert members(result) == {frozenset({("2",), ("3",)})}

    def test_records_sharing_a_document_are_not_linked_by_recomputing(self):
        records = [row("1", "a"), row("2", "a", 2), row("3", "b"), row("4", "c")]
        result = outcome(self.documents, records, rejected(["3"], ["4"]))
        assert members(result) == {frozenset({("1",), ("2",), ("3",), ("4",)})}
        result = outcome(
            self.documents, records, rejected(["3"], ["4"]), rejected(["1"], ["3"]),
            rejected(["2"], ["3"]),
        )
        assert members(result) == {frozenset({("1",), ("2",), ("4",)})}

    def test_a_new_record_is_an_ordinary_candidate_not_a_conflict(self):
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        result = outcome(self.documents, records, rejected(["1"], ["2"]))
        assert {item.rule for item in result.items} == {RULE_CANDIDATES}

    def test_an_untouched_group_is_not_recomputed(self):
        records = [row("1", "a"), row("2", "b"),
                   row("3", "a", 2, amount=-900), row("4", "b", 2, amount=-900)]
        result = outcome(self.documents, records, rejected(["1"], ["2"]))
        assert members(result) == {frozenset({("3",), ("4",)})}
        assert result.recomputed_pairs == 1

    def test_a_long_run_keeps_no_block_holding_only_a_decided_pair(self):
        rules = replace(DEFAULT_RULES, max_group_span_days=4, date_window_days=3)
        documents = [doc("a"), doc("b")]
        records = [row("1", "a", day="2026-01-01"), row("2", "b", day="2026-01-03"),
                   row("3", "a", 2, day="2026-01-05"), row("4", "b", 2, day="2026-01-07")]
        before = outcome(documents, records, rules=rules)
        result = outcome(documents, records, rejected(["1"], ["2"]), rules=rules)
        assert len(before.items) >= 1
        for item in result.items:
            assert {("1",), ("2",)} != set(item.members)


class TestWithholding:
    def test_the_whole_group_is_withheld(self):
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        assert groups(outcome([*NARROW, WIDE], records)) == {("1", "2", "3")}

        result = outcome([*NARROW, WIDE], records, rejected(["1"], ["2"]))
        assert groups(result) == {("1",), ("2",), ("3",)}
        assert {group.link_rule for group in result.groups} == {LINK_NEW}

    def test_the_conflict_replaces_the_candidate_item(self):
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        result = outcome([*NARROW, WIDE], records, rejected(["1"], ["2"]))
        assert [item.rule for item in result.items] == [RULE_DECISION]
        assert result.items[0].reasons == (REASON_WITHHELD,)
        assert set(result.items[0].members) == {("1",), ("2",), ("3",)}

    def test_a_candidate_reaching_other_records_stays_alongside_the_conflict(self):
        documents = [*NARROW, WIDE, doc("d")]
        records = [row("1", "a"), row("2", "b"), row("3", "c"), row("4", "d")]
        result = outcome(documents, records, rejected(["1"], ["2"]))
        assert members(result, RULE_DECISION) == {frozenset({("1",), ("2",), ("3",)})}
        assert members(result, RULE_CANDIDATES) == {frozenset({("1",), ("2",), ("3",), ("4",)})}

    def test_a_reliable_id_group_is_withheld_too(self):
        documents = [doc(name, id_namespace="bank", id_guarantee="stable_unique") for name in "abc"]
        records = [row(name, name, external_id="X") for name in "abc"]
        assert groups(outcome(documents, records)) == {("a", "b", "c")}

        result = outcome(documents, records, rejected(["a"], ["b"]))
        assert groups(result) == {("a",), ("b",), ("c",)}
        assert result.separation_reasons["a"] == REASON_WITHHELD
        assert [item.rule for item in result.items] == [RULE_DECISION]

    def test_an_id_conflict_shows_withheld_records_separately(self):
        documents = [doc(name, id_namespace="bank", id_guarantee="stable_unique") for name in "abcd"]
        records = [row("a", "a", external_id="X"), row("b", "b", external_id="X"),
                   row("c", "c", external_id="X"), row("d", "d", amount=-900, external_id="X")]
        result = outcome(documents, records, rejected(["a"], ["b"]))
        assert members(result, RULE_EXTERNAL_ID) == {
            frozenset({("a",), ("b",), ("c",), ("d",)})
        }

    def test_the_withholding_decision_is_named(self):
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        result = outcome(
            [*NARROW, WIDE], records, rejected(["1"], ["2"], "d2"), rejected(["2"], ["3"], "d1")
        )
        assert result.withheld_by == {"1": "d1", "2": "d1", "3": "d1"}

    def test_a_group_without_both_sides_is_not_withheld(self):
        records = [row("1", "a"), row("3", "c")]
        result = outcome([*NARROW, WIDE], records, rejected(["1"], ["2"]))
        assert groups(result) == {("1", "3")}
        assert result.items == ()

    def test_rows_in_other_slots_still_pair(self):
        documents = [*NARROW, WIDE]
        records = [row("1", "a"), row("2", "b"), row("3", "c"),
                   row("4", "a", 2), row("5", "c", 2)]
        result = outcome(documents, records, rejected(["1"], ["2"]))
        assert ("4", "5") in groups(result)


class TestBasisChanged:
    def test_a_divided_side_changes_the_basis_and_claims_no_withholding(self):
        documents = [doc("a"), doc("b"), doc("c")]
        records = [row("1", "a"), row("2", "b", amount=-900), row("3", "c")]
        result = outcome(documents, records, rejected(["1", "2"], ["3"]))
        conflicts = [item for item in result.items if item.rule == RULE_DECISION]
        assert [item.reasons for item in conflicts] == [(REASON_BASIS_CHANGED,)]
        assert set(conflicts[0].members) == {("1",), ("2",)}
        assert result.withheld_by == {}

    def test_an_intact_side_raises_nothing(self):
        documents = [doc("a"), doc("b"), doc("c")]
        records = [row("1", "a", external_id=None), row("3", "c")]
        result = outcome(documents, records, rejected(["1"], ["3"]))
        assert result.items == ()

    def test_a_side_that_gains_a_record_is_not_a_conflict(self):
        documents = [doc("a", "2026-01-01", "2026-01-20"), doc("b", "2026-01-01", "2026-01-20"),
                     doc("c")]
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        result = outcome(documents, records, rejected(["1"], ["3"]))
        assert groups(result) == {("1", "2"), ("3",)}
        assert result.items == ()

    def test_a_withheld_group_that_divides_a_side_carries_both_reasons(self):
        records = [row("1", "a"), row("2", "b"), row("3", "c")]
        result = outcome([*NARROW, WIDE], records, rejected(["1", "3"], ["2"]))
        assert [item.reasons for item in result.items] == [
            (REASON_WITHHELD, REASON_BASIS_CHANGED)
        ]
        assert groups(result) == {("1",), ("2",), ("3",)}

    def test_separate_conflicts_stay_separate(self):
        documents = [doc("a"), doc("b"), doc("c")]
        records = [row("1", "a"), row("2", "b", amount=-900),
                   row("3", "a", 2, amount=-111), row("4", "b", 2, amount=-222),
                   row("5", "c", amount=-333)]
        result = outcome(
            documents, records, rejected(["1", "2"], ["5"]), rejected(["3", "4"], ["5"], "d2")
        )
        assert len(members(result, RULE_DECISION)) == 2


class TestDirectLinks:
    documents = [doc("a"), doc("b")]

    def linked(self, left, right):
        return directly_linked([left], [right], self.documents, DEFAULT_RULES)

    def test_same_amount_date_window_and_similar_description(self):
        assert self.linked(row("1", "a"), row("2", "b", description="SYNTHETIC CAFE 1234"))

    def test_a_different_amount_is_not_linked(self):
        assert not self.linked(row("1", "a"), row("2", "b", amount=-651))

    def test_a_date_outside_the_window_is_not_linked(self):
        assert not self.linked(row("1", "a"), row("2", "b", day="2026-02-20"))

    def test_an_unrelated_description_is_not_linked(self):
        assert not self.linked(row("1", "a"), row("2", "b", description="OTHER PLACE"))

    def test_one_document_is_not_linked(self):
        assert not self.linked(row("1", "a"), row("2", "a", 2))

    def test_stable_unique_ids_in_one_namespace_are_not_linked(self):
        documents = [
            doc(name, id_namespace="bank", id_guarantee="stable_unique") for name in "ab"
        ]
        left = row("1", "a", external_id="X")
        right = row("2", "b", external_id="Y")
        assert not directly_linked([left], [right], documents, DEFAULT_RULES)


words = st.sampled_from(
    ["SYNTHETIC CAFE", "SYNTHETIC CAFE 1234", "SQ *SYNTHETIC CAFE", "SYNTHETIC BOOKS", "A", ""]
)
rows_strategy = st.lists(
    st.tuples(st.integers(0, 3), st.integers(0, 30), st.sampled_from([-650, -900]), words),
    min_size=2, max_size=12,
)


@settings(max_examples=200, deadline=None)
@given(rows_strategy)
def test_recomputed_links_match_union_find_components(rows):
    """S16: direct links found pair by pair give the components discovery found."""
    rules = replace(DEFAULT_RULES, max_group_span_days=10_000)
    documents = {name: doc(name) for name in "abcd"}
    start = date(2026, 1, 1)
    units = [
        _Unit.of(
            [Record(str(index), "abcd"[document], index, amount,
                    posting_date=(start + timedelta(days=offset)).isoformat(),
                    description=text, settlement_status="posted")],
            documents,
        )
        for index, (document, offset, amount, text) in enumerate(rows)
    ]
    joined, _ = _link_candidates(units, rules)
    expected = {
        frozenset(index for index in component)
        for component in joined.components() if len(component) > 1
    }
    found = set()
    for component in joined.components():
        if len(component) > 1:
            parts, _ = _undecided_parts(component, units, set(), rules)
            found.update(frozenset(units.index(unit) for unit in part) for part in parts)
    assert found == expected
