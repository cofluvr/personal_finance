"""Superseding chains and new evidence on decided records, using synthetic data only (D-048)."""

import re

import pytest
import test_confirmations
from test_confirmations import confirm_ok, four_of_them, state_of
from test_decisions import Ledger, pair_up
from test_separations import SeparationLedger, merged_two

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
