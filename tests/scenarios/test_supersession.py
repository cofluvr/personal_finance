"""Superseding chains and new evidence on decided records, using synthetic data only (D-048)."""

import re

import pytest
import test_confirmations
from test_confirmations import confirm_ok, four_of_them, state_of
from test_decisions import Ledger, pair_up
from test_separations import SeparationLedger, absorbed, merged_three, merged_two

from personal_finance.reconcile.apply import load_constraints
from personal_finance.reconcile.decisions import DECISION_SUPERSEDED, RESTORE_CONTRADICTS
from personal_finance.reports import decision_evidence


@pytest.fixture
def ledger(tmp_path, capsys):
    return SeparationLedger(tmp_path, capsys)


def by_file(ledger):
    return test_confirmations.TestConfirm.by_file(ledger)


def chain_of_three(ledger):
    """A rejects x≠y. B joins x and y, superseding A. C joins z to them, superseding B.

    w stays undecided, so an item holding the others stays open throughout. Returns the three
    decisions, oldest first.
    """
    item, x, y, z, _ = four_of_them(ledger)
    a = ledger.reject_ok(item, (x, y))
    b = confirm_ok(ledger, item, (x, y), (z,), supersedes=a)
    (item,) = ledger.items()
    files = by_file(ledger)
    # B's pairs between groups come first, so its same_event pair x=y is the third.
    c = confirm_ok(ledger, item, (files["a.csv"], files["c.csv"]), supersedes=b, keep=(3,))
    return a, b, c


def states(ledger, *decisions):
    return [state_of(ledger, decision) for decision in decisions]


def record_relations(ledger):
    """Every active stated relation between two records, by file name, in no particular order."""
    conn = ledger.conn()
    names = dict(conn.execute(
        """SELECT record.id, document.file_name FROM source_record record
           JOIN source_document document ON document.id = record.source_document_id"""
    ))
    (account,) = conn.execute("SELECT id FROM account WHERE display_name = 'A'").fetchone()
    found = {
        (constraint.relation, frozenset((names[left], names[right])))
        for constraint in load_constraints(conn, account)
        for left in constraint.left
        for right in constraint.right
    }
    conn.close()
    return found


class TestChains:  # N1, N2, N3
    def test_only_the_newest_of_a_chain_is_active(self, ledger):  # N1
        a, b, c = chain_of_three(ledger)
        assert states(ledger, a, b, c) == ["superseded", "superseded", "active"]
        out = ledger.run("review", "decisions")[1]
        assert f"Decision {a}: superseded, reject" in out
        assert f"Decision {b}: superseded, confirm" in out
        assert f"Decision {c}: active, confirm" in out
        assert ledger.together() == [["a.csv", "b.csv", "c.csv"], ["d.csv"]]

    def test_the_oldest_keeps_nothing_apart_once_superseded_twice(self, ledger):  # N1
        chain_of_three(ledger)
        relations = record_relations(ledger)
        assert ("different_event", frozenset({"a.csv", "b.csv"})) not in relations
        assert ("same_event", frozenset({"a.csv", "b.csv"})) in relations

    def test_decision_show_names_the_newest_of_the_chain(self, ledger):
        a, b, c = chain_of_three(ledger)
        oldest = ledger.run("review", "decision", "show", a)[1]
        assert f"Superseded by decision {b}." in oldest
        assert f"Newest of its chain: decision {c}" in oldest
        middle = ledger.run("review", "decision", "show", b)[1]
        assert f"Superseded by decision {c}." in middle
        assert "Newest of its chain" not in middle

    def test_undo_walks_back_one_link_at_a_time(self, ledger):  # N2
        a, b, c = chain_of_three(ledger)
        code, out, _ = ledger.undo(c)
        assert code == 0 and f"Decision {b}, which it superseded, applies again." in out
        assert states(ledger, a, b, c) == ["superseded", "active", "undone"]
        assert ledger.together() == [["a.csv", "b.csv"], ["c.csv"], ["d.csv"]]

        code, out, _ = ledger.undo(b)
        assert code == 0 and f"Decision {a}, which it superseded, applies again." in out
        assert states(ledger, a, b, c) == ["active", "undone", "undone"]
        assert ledger.count() == 4

    def test_each_step_refuses_to_restore_a_contradiction(self, ledger):  # N2
        a, b, c = chain_of_three(ledger)
        (item,) = ledger.items()
        later = confirm_ok(ledger, item, tuple(ledger.transactions(item)))
        before = ledger.dump()
        code, _, err = ledger.undo(c)
        assert code == 2 and RESTORE_CONTRADICTS.format(restored=b) in err
        assert ledger.dump() == before
        assert ledger.undo(later)[0] == 0
        assert ledger.undo(c)[0] == 0
        assert states(ledger, a, b, c) == ["superseded", "active", "undone"]

    def test_a_superseded_decision_names_the_newest_when_refused(self, ledger):  # N3
        a, b, c = chain_of_three(ledger)
        # A superseded decision shows no token, and the refusal comes before any token check.
        before = ledger.dump()
        code, _, err = ledger.undo(a, "d3-0000000000000000")
        assert code == 2
        assert f"superseded by decision {b}, which is superseded in turn" in err
        assert f"Only the newest decision of the chain, {c}, can be undone" in err
        code, _, err = ledger.undo(b, "d3-0000000000000000")
        assert code == 2 and DECISION_SUPERSEDED.format(newer=c) in err
        assert ledger.dump() == before

    def test_a_superseded_decision_cannot_be_superseded_again(self, ledger):  # N3
        a, b, c = chain_of_three(ledger)
        (item,) = ledger.items()
        before = ledger.dump()
        code, _, err = ledger.run(
            "review", "confirm", item, "--account", "A", "--revision", ledger.revision(item),
            "--group", *ledger.transactions(item), "--supersedes", a,
            "--supersedes-revision", "d3-0000000000000000",
        )
        assert code == 2 and f"Only the newest decision of the chain, {c}" in err
        assert ledger.dump() == before


class TestTokens:  # N14
    def test_the_version_is_pinned(self):
        assert decision_evidence.DECISION_REVISION_VERSION == 3

    def test_a_ledger_without_chains_keeps_its_digest(self, tmp_path, capsys):
        """d2-2a1e1dd2ac99de82 was computed for this ledger at 7551e18, before version 3."""
        ledger = Ledger(tmp_path, capsys)
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        assert ledger.decision_revision(decision) == "d3-2a1e1dd2ac99de82"

    def test_the_transaction_token_is_unchanged(self, ledger):
        """Computed for this ledger at 7551e18, before M2.5."""
        transaction, _ = merged_two(ledger)
        assert ledger.merge_revision(transaction) == "t1-4ae2352458f9c44c"

    def test_undoing_the_newest_previews_the_decision_before_it(self, ledger):
        _, b, c = chain_of_three(ledger)
        out = ledger.run("review", "decision", "show", c)[1]
        assert f"Restores decision {b}, which it superseded" in out
        assert re.search(r"Transactions: 2 now, 3 after", out)


def separate(ledger, transaction, *groups, supersedes=None, supersedes_revision=None, keep=(),
             revision=None):
    words = ["review", "separate", transaction, "--account", "A",
             "--revision", revision or ledger.merge_revision(transaction)]
    for group in groups:
        words += ["--group", *group]
    if supersedes:
        words += ["--supersedes", supersedes, "--supersedes-revision",
                  supersedes_revision or ledger.decision_revision(supersedes)]
    for number in keep:
        words += ["--keep", str(number)]
    return ledger.run(*words)


def separate_ok(ledger, transaction, *groups, **options):
    code, out, err = separate(ledger, transaction, *groups, **options)
    assert code == 0, err
    return re.search(r"Decision (\S+) recorded", out)[1]


def holding(ledger, name):
    """The transaction holding a file's only record."""
    conn = ledger.conn()
    (transaction,) = conn.execute(
        """SELECT link.transaction_id FROM transaction_source link
           JOIN source_document document ON document.id = link.source_document_id
           WHERE document.file_name = ?""",
        (name,),
    ).fetchone()
    conn.close()
    return transaction


def pair_numbers(ledger, decision, relation):
    """Pair numbers of one relation, read from review decision show and never assumed."""
    out = ledger.run("review", "decision", "show", decision)[1]
    return tuple(int(number) for number in re.findall(rf"^Pair (\d+) of \d+: {relation}$", out,
                                                      re.MULTILINE))


def confirmed_pair(ledger):
    """a and b, which never merge by themselves, confirmed as one event."""
    item, one, two = pair_up(ledger)
    decision = confirm_ok(ledger, item, (one, two))
    transaction = holding(ledger, "a.csv")
    return decision, transaction, ledger.records(transaction)


def confirmed_partition(ledger):
    """a and b confirmed as one event, and c as a different one, in one decision."""
    item, *_ = test_confirmations.three_of_them(ledger)
    files = by_file(ledger)
    decision = confirm_ok(ledger, item, (files["a.csv"], files["b.csv"]), (files["c.csv"],))
    transaction = holding(ledger, "a.csv")
    return decision, transaction, ledger.records(transaction)


def stored_pairs(ledger, decision, relation):
    conn = ledger.conn()
    found = sorted(conn.execute(
        """SELECT relation, left_record_id, right_record_id FROM decision_constraint
           WHERE decision_id = ? AND relation = ?""",
        (decision, relation),
    ).fetchall())
    conn.close()
    return found


class TestSeparatingAConfirmation:  # N4, N6
    def test_a_confirmed_core_can_be_split_by_superseding_it(self, ledger):  # N4
        old, transaction, records = confirmed_pair(ledger)
        assert "Net account movement: -6.50" in ledger.totals()
        before = ledger.dump()
        code, out, _ = separate(ledger, transaction, [records["a.csv"]], [records["b.csv"]],
                                supersedes=old)
        assert code == 0
        assert f"Supersedes decision {old}: 1 of its pairs contradicted, 0 kept." in out
        assert "Transactions: 1 before, 2 now." in out
        assert state_of(ledger, old) == "superseded"
        assert ledger.together() == [["a.csv"], ["b.csv"]]
        assert "Net account movement: -13.00" in ledger.totals()
        after = ledger.dump()
        for table in test_confirmations.SOURCE_TABLES:
            assert after[table] == before[table], table

    def test_every_other_pair_is_kept_record_for_record(self, ledger):  # N4
        old, transaction, records = confirmed_partition(ledger)
        apart = stored_pairs(ledger, old, "different_event")
        new = separate_ok(ledger, transaction, [records["a.csv"]], [records["b.csv"]],
                          supersedes=old, keep=pair_numbers(ledger, old, "different_event"))
        kept = [row for row in stored_pairs(ledger, new, "different_event")
                if {row[1], row[2]} != {records["a.csv"], records["b.csv"]}]
        assert kept == apart and len(kept) == 2
        assert stored_pairs(ledger, new, "same_event") == []
        assert ledger.together() == [["a.csv"], ["b.csv"], ["c.csv"]]
        assert ledger.items() == []

    def test_a_pair_neither_contradicted_nor_kept_is_refused(self, ledger):  # N5
        old, transaction, records = confirmed_partition(ledger)
        before = ledger.dump()
        code, _, err = separate(ledger, transaction, [records["a.csv"]], [records["b.csv"]],
                                supersedes=old)
        assert code == 2 and "neither contradicted by these groups nor kept" in err
        assert ledger.dump() == before

    def test_keeping_the_contradicted_pair_is_refused(self, ledger):  # N5
        old, transaction, records = confirmed_partition(ledger)
        before = ledger.dump()
        keep = (*pair_numbers(ledger, old, "different_event"),
                *pair_numbers(ledger, old, "same_event"))
        code, _, err = separate(ledger, transaction, [records["a.csv"]], [records["b.csv"]],
                                supersedes=old, keep=keep)
        assert code == 2 and "is contradicted by these groups, so it cannot be kept" in err
        assert ledger.dump() == before

    @pytest.mark.parametrize("stale", ["transaction", "decision"])
    def test_both_tokens_are_checked(self, ledger, stale):  # N5
        old, transaction, records = confirmed_pair(ledger)
        options = ({"revision": "t1-0000000000000000"} if stale == "transaction"
                   else {"supersedes_revision": "d3-0000000000000000"})
        before = ledger.dump()
        code, _, err = separate(ledger, transaction, [records["a.csv"]], [records["b.csv"]],
                                supersedes=old, **options)
        assert code == 2 and "revision does not match" in err
        assert ledger.dump() == before

    def test_splitting_another_decisions_core_is_refused(self, ledger):  # N5
        first, _, _ = confirmed_pair(ledger)
        ledger.card("c.csv", test_confirmations.CAFE)
        (item,) = ledger.items()
        second = confirm_ok(ledger, item, tuple(ledger.transactions(item)))
        transaction = holding(ledger, "a.csv")
        records = ledger.records(transaction)
        before = ledger.dump()
        code, _, err = separate(ledger, transaction, [records["a.csv"]],
                                [records["b.csv"], records["c.csv"]], supersedes=second)
        assert code == 2 and f"decision {first} confirmed as one event" in err
        assert "only the decision named with --supersedes" in err
        assert ledger.dump() == before
        # Splitting only the second decision's join is allowed.
        separate_ok(ledger, transaction, [records["a.csv"], records["b.csv"]],
                    [records["c.csv"]], supersedes=second)
        assert ledger.together() == [["a.csv", "b.csv"], ["c.csv"]]

    def test_superseding_what_it_does_not_split_is_refused(self, ledger):  # N5
        transaction, records = absorbed(ledger)
        (old,) = active_decisions(ledger)
        before = ledger.dump()
        code, _, err = separate(ledger, transaction, [records["a.csv"], records["b.csv"]],
                                [records["c.csv"]], supersedes=old)
        assert code == 2 and "contradict nothing in the decision named with --supersedes" in err
        assert ledger.dump() == before

    def test_an_undone_or_superseded_decision_is_refused(self, ledger):  # N5
        old, _, _ = confirmed_pair(ledger)
        token = ledger.decision_revision(old)
        assert ledger.undo(old)[0] == 0
        (item,) = ledger.items()
        newer = confirm_ok(ledger, item, tuple(ledger.transactions(item)))
        transaction = holding(ledger, "a.csv")
        records = ledger.records(transaction)
        before = ledger.dump()
        code, _, err = separate(ledger, transaction, [records["a.csv"]], [records["b.csv"]],
                                supersedes=old, supersedes_revision=token)
        assert code == 2 and "already been undone" in err
        assert ledger.dump() == before
        assert newer in active_decisions(ledger)

    def test_without_supersedes_the_core_is_still_refused(self, ledger):
        _, transaction, records = confirmed_pair(ledger)
        code, _, err = separate(ledger, transaction, [records["a.csv"]], [records["b.csv"]])
        assert code == 2 and "--supersedes" in err

    def test_undo_restores_the_confirmation(self, ledger):  # N6
        old, transaction, records = confirmed_pair(ledger)
        view = ledger.view()
        new = separate_ok(ledger, transaction, [records["a.csv"]], [records["b.csv"]],
                          supersedes=old)
        assert "Restores decision" in ledger.run("review", "decision", "show", new)[1]
        code, out, _ = ledger.undo(new)
        assert code == 0 and f"Decision {old}, which it superseded, applies again." in out
        assert state_of(ledger, old) == "active"
        restored = ledger.view()
        assert restored["constraints"] == view["constraints"]
        assert restored["movement"] == view["movement"]
        assert restored["transactions"] == view["transactions"]

    def test_undo_refuses_to_restore_a_contradiction(self, ledger):  # N6
        old, transaction, records = confirmed_pair(ledger)
        new = separate_ok(ledger, transaction, [records["a.csv"]], [records["b.csv"]],
                          supersedes=old)
        ledger.card("c.csv", test_confirmations.CAFE)
        (item,) = ledger.items()
        later = confirm_ok(ledger, item, (holding(ledger, "a.csv"), holding(ledger, "c.csv")),
                           (holding(ledger, "b.csv"),))
        before = ledger.dump()
        code, _, err = ledger.undo(new)
        assert code == 2 and RESTORE_CONTRADICTS.format(restored=old) in err
        assert ledger.dump() == before
        assert ledger.undo(later)[0] == 0
        assert ledger.undo(new)[0] == 0
        assert state_of(ledger, old) == "active"


class TestSeparatingASeparation:  # N7
    def test_a_kept_group_can_be_split_by_superseding_its_separation(self, ledger):
        transaction, records = merged_three(ledger)
        first = separate_ok(ledger, transaction, [records["a.csv"], records["b.csv"]],
                            [records["c.csv"]])
        kept = holding(ledger, "a.csv")
        code, _, err = separate(ledger, kept, [records["a.csv"]], [records["b.csv"]])
        assert code == 2 and "--supersedes" in err
        second = separate_ok(ledger, kept, [records["a.csv"]], [records["b.csv"]],
                             supersedes=first, keep=pair_numbers(ledger, first, "different_event"))
        assert ledger.together() == [["a.csv"], ["b.csv"], ["c.csv"]]
        assert states(ledger, first, second) == ["superseded", "active"]
        relations = record_relations(ledger)
        assert {relation for relation, _ in relations} == {"different_event"}
        assert len(relations) == 3


class TestRejectionsSupersedeNothing:  # N8
    def test_reject_takes_no_supersedes(self, ledger):
        item, one, two = pair_up(ledger)
        with pytest.raises(SystemExit) as raised:
            ledger.run("review", "reject", item, "--account", "A", "--revision",
                       ledger.revision(item), "--pair", one, two, "--supersedes", "x")
        assert raised.value.code == 2

    def test_a_separation_cannot_supersede_a_rejection(self, ledger):
        transaction, records = merged_three(ledger)
        ledger.card("d.csv", test_confirmations.CAFE)
        (item,) = ledger.items()
        rejection = ledger.reject_ok(item, tuple(ledger.transactions(item)))
        before = ledger.dump()
        code, _, err = separate(ledger, transaction, [records["a.csv"]],
                                [records["b.csv"], records["c.csv"]], supersedes=rejection)
        assert code == 2 and "contradict nothing" in err
        assert ledger.dump() == before


def active_decisions(ledger):
    out = ledger.run("review", "decisions")[1]
    return re.findall(r"^Decision (\S+): active,", out, re.MULTILINE)



def rejected_then_re_exported(ledger, name="again.csv"):
    """a and b rejected as different events, then a's row again in a file that does not merge."""
    item, one, two = pair_up(ledger)
    decision = ledger.reject_ok(item, (one, two))
    ledger.card(name, test_confirmations.CAFE)
    (again,) = ledger.items("cross_document_candidates")
    return decision, again


def alike_lines(out):
    if "Alike a decided record" not in out:
        return []
    section = out.split("Alike a decided record, and not bound by any decision:\n")[1]
    return re.findall(r"^  (\S+ row \d+ matches \S+ row \d+) in every parsed value, decided by "
                      r"(\S+)$", section, re.MULTILINE)


class TestNewEvidence:  # N9, N10
    def test_a_re_export_that_merges_is_kept_apart_with_its_record(self, ledger):  # N9
        item, one, two = pair_up(ledger)
        decision = ledger.reject_ok(item, (one, two))
        ledger.card("again.csv", test_confirmations.CAFE, extra=test_confirmations.FIRST_HALF)
        assert ledger.together() == [["a.csv", "again.csv"], ["b.csv"]]
        assert ledger.items() == []
        relations = record_relations(ledger)
        assert relations == {("different_event", frozenset({"a.csv", "b.csv"}))}
        assert active_decisions(ledger) == [decision]

    def test_a_re_export_that_does_not_merge_is_reviewed_again(self, ledger):  # N9
        decision, again = rejected_then_re_exported(ledger)
        assert len(ledger.transactions(again)) == 3
        assert record_relations(ledger) == {("different_event", frozenset({"a.csv", "b.csv"}))}
        # Listed by document hash, not file name.
        assert sorted(alike_lines(ledger.show(again))) == [
            ("again.csv row 1 matches a.csv row 1", decision),
            ("again.csv row 1 matches b.csv row 1", decision),
        ]

    def test_a_re_export_of_a_separated_id_is_a_conflict(self, ledger):  # N9, P7
        ledger.checking("a.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        (transaction,) = ledger.merges()
        records = ledger.records(transaction)
        decision = separate_ok(ledger, transaction, [records["a.csv"]], [records["b.csv"]])
        rows = len(ledger.dump()["decision_constraint"])
        ledger.checking("c.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        (conflict,) = ledger.items("decision_conflict")
        assert len(ledger.dump()["decision_constraint"]) == rows
        assert sorted(alike_lines(ledger.show(conflict))) == [
            ("c.csv row 1 matches a.csv row 1", decision),
            ("c.csv row 1 matches b.csv row 1", decision),
        ]

    def test_a_confirmation_on_the_new_item_binds_it(self, ledger):  # N10
        decision, again = rejected_then_re_exported(ledger)
        files = by_file(ledger)
        new = confirm_ok(ledger, again, (files["again.csv"], files["a.csv"]), (files["b.csv"],))
        assert ledger.together() == [["a.csv", "again.csv"], ["b.csv"]]
        assert ledger.items() == []
        relations = record_relations(ledger)
        assert ("same_event", frozenset({"a.csv", "again.csv"})) in relations
        assert ("different_event", frozenset({"again.csv", "b.csv"})) in relations
        assert set(active_decisions(ledger)) == {decision, new}


class TestAlikeListing:  # N11
    def test_it_binds_nothing_and_leaves_the_token_unchanged(self, ledger):
        rejected_then_re_exported(ledger)
        (again,) = ledger.items()
        before = ledger.dump()
        assert alike_lines(ledger.show(again))
        assert ledger.dump() == before
        # Computed for this ledger at b55e31b, before the listing existed.
        assert ledger.revision(again) == "r3-74d05de08ff20c6b"

    def test_records_a_decision_binds_are_not_listed(self, ledger):
        decision, again = rejected_then_re_exported(ledger)
        files = by_file(ledger)
        confirm_ok(ledger, again, (files["again.csv"], files["a.csv"]))
        assert all(not alike_lines(ledger.show(item)) for item in ledger.items())

    def test_a_record_differing_in_one_value_is_not_listed(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.reject_ok(item, (one, two))
        ledger.card("again.csv", "01/11/2026,SYNTHETIC CAFE,6.50,")
        (again,) = ledger.items("cross_document_candidates")
        assert alike_lines(ledger.show(again)) == []

    def test_file_names_are_escaped(self, ledger):
        """Older sections print file names as typed, a documented limitation, so only this one
        is checked."""
        _, again = rejected_then_re_exported(ledger, name="again\x1b[2J.csv")
        section = ledger.show(again).split("Alike a decided record")[1].split("Direct candidate")[0]
        assert "\x1b" not in section
        assert "matches a.csv row 1" in section
