"""Tags and tag statements, end to end, using synthetic data only (WC1, D-073 point 5).

A tag statement is the sixth stated kind: a transaction's whole set of tags, possibly empty, on
D-063 and D-065's model. Tags enter no total.
"""

import re

import pytest
from test_decisions import CAFE, Ledger

from personal_finance.reconcile import decisions, tags

TAGGING_TOKEN = r"tg1-[0-9a-f]{16}"


class TagLedger(Ledger):
    def transaction_ids(self):
        out = self.run("transactions")[1]
        return re.findall(r"^([0-9a-f-]{36})  ", out, re.MULTILINE)

    def transaction_show(self, transaction):
        code, out, err = self.run("review", "transaction", "show", transaction)
        assert code == 0, err
        return out

    def transaction_revision(self, transaction):
        return re.search(r"^  Revision: (t13-[0-9a-f]{16})$", self.transaction_show(transaction),
                         re.MULTILINE)[1]

    def tag(self, transaction, names=None, revision=None, supersedes=None,
            supersedes_revision=None):
        words = ["review", "tag", transaction, "--account", "A", "--revision",
                 revision or self.transaction_revision(transaction)]
        words += ["--none"] if names is None else ["--tags", names]
        if supersedes:
            words += ["--supersedes", supersedes, "--supersedes-revision",
                      supersedes_revision or self.tagging_revision(supersedes)]
        return self.run(*words)

    def tag_ok(self, transaction, names=None, **options):
        code, out, err = self.tag(transaction, names, **options)
        assert code == 0, err
        return re.search(r"Tag statement (\S+) recorded", out)[1]

    def tagging_show(self, statement):
        code, out, err = self.run("review", "tagging", "show", statement)
        assert code == 0, err
        return out

    def tagging_revision(self, statement):
        return re.search(rf"Revision: ({TAGGING_TOKEN})", self.tagging_show(statement))[1]

    def refused(self, action, message):
        before = self.dump(("tag", "tag_statement", "tag_statement_record",
                            "tag_statement_event", "transaction_tag"))
        code, _, err = action()
        assert (code, err.strip()) == (2, f"Error: {message}")
        assert self.dump(("tag", "tag_statement", "tag_statement_record",
                          "tag_statement_event", "transaction_tag")) == before


@pytest.fixture
def ledger(tmp_path, capsys):
    """One purchase, and two tags."""
    found = TagLedger(tmp_path, capsys)
    found.card("a.csv", CAFE)
    for name in ("Trip", "Work & <b>"):
        assert found.run("tag", "add", name)[0] == 0
    (found.purchase,) = found.transaction_ids()
    return found


class TestTheList:  # WC1
    def test_tags_are_listed_by_name(self, ledger):
        assert ledger.run("tags")[1] == "Trip\nWork & <b>\nTags: 2\n"

    @pytest.mark.parametrize("name", ["", " Trip", "Trip ", "a,b"])
    def test_a_name_with_padding_or_a_comma_is_refused(self, ledger, name):
        ledger.refused(lambda: ledger.run("tag", "add", name), tags.TAG_NAME_INVALID)

    def test_a_name_is_added_once(self, ledger):
        ledger.refused(lambda: ledger.run("tag", "add", "Trip"), tags.TAG_EXISTS)


class TestStatements:  # WC1
    def test_a_first_statement_applies_and_shows(self, ledger):
        before = ledger.transaction_revision(ledger.purchase)
        statement = ledger.tag_ok(ledger.purchase, "Work & <b>,Trip")
        out = ledger.transaction_show(ledger.purchase)
        assert f"    Tag statement {statement}: Trip, Work & <b>, binding " in out
        assert "    Tags: these apply\n" in out
        assert ledger.transaction_revision(ledger.purchase) != before
        conn = ledger.conn()
        assert conn.execute("SELECT state, tags FROM transaction_tag").fetchall() == [
            ("applied", "1,2")]
        conn.close()

    def test_a_statement_of_none_applies_empty(self, ledger):
        ledger.tag_ok(ledger.purchase)
        conn = ledger.conn()
        assert conn.execute("SELECT state, tags FROM transaction_tag").fetchall() == [
            ("applied", "")]
        conn.close()
        assert "    Tag statement " in ledger.transaction_show(ledger.purchase)

    def test_an_unknown_tag_is_refused(self, ledger):
        ledger.refused(lambda: ledger.tag(ledger.purchase, "Trip,Nope"), tags.TAG_UNKNOWN)

    @pytest.mark.parametrize("names", ["Trip,", ",Trip", "Trip,,Work & <b>"])
    def test_an_empty_name_in_the_list_is_refused(self, ledger, names):
        code, _, err = ledger.tag(ledger.purchase, names)
        assert code == 2 and "none empty" in err

    def test_a_stale_revision_is_refused(self, ledger):
        before = ledger.dump(("tag_statement", "transaction_tag"))
        code, _, err = ledger.tag(ledger.purchase, "Trip", revision="t13-0000000000000000")
        assert code == 2 and "revision" in err and "Nothing was changed" in err
        assert ledger.dump(("tag_statement", "transaction_tag")) == before

    def test_the_same_tags_again_are_refused(self, ledger):
        statement = ledger.tag_ok(ledger.purchase, "Trip")
        ledger.refused(lambda: ledger.tag(ledger.purchase, "Trip", supersedes=statement),
                       tags.TAGS_UNCHANGED)

    def test_another_statement_needs_supersedes(self, ledger):
        statement = ledger.tag_ok(ledger.purchase, "Trip")
        ledger.refused(lambda: ledger.tag(ledger.purchase, "Work & <b>"),
                       tags.ALREADY_TAGGED.format(statement=statement))

    def test_a_superseding_statement_applies_and_its_undo_restores(self, ledger):
        first = ledger.tag_ok(ledger.purchase, "Trip")
        second = ledger.tag_ok(ledger.purchase, "Work & <b>", supersedes=first)
        assert "Work & <b>, binding" in ledger.transaction_show(ledger.purchase)
        code, out, err = ledger.run("review", "tagging", "undo", second, "--account", "A",
                                    "--revision", ledger.tagging_revision(second))
        assert code == 0, err
        assert f"Tag statement {first}, which it superseded, applies again." in out
        conn = ledger.conn()
        assert conn.execute("SELECT tags FROM transaction_tag").fetchall() == [("1",)]
        conn.close()

    def test_an_undo_with_a_stale_revision_is_refused(self, ledger):
        statement = ledger.tag_ok(ledger.purchase, "Trip")
        ledger.refused(lambda: ledger.run("review", "tagging", "undo", statement, "--account",
                                          "A", "--revision", "tg1-0000000000000000"),
                       tags.STALE_TAGGING_REVISION)

    def test_tags_enter_no_total(self, ledger):
        before = [ledger.run(*words) for words in (("totals",), ("report", "monthly"))]
        ledger.tag_ok(ledger.purchase, "Trip")
        assert [ledger.run(*words) for words in (("totals",), ("report", "monthly"))] == before


class TestTokens:  # WC1
    def test_tg1_is_the_same_in_any_ledger_holding_the_same(self, tmp_path, capsys):
        found = []
        for name in ("one", "two"):
            folder = tmp_path / name
            folder.mkdir()
            ledger = TagLedger(folder, capsys)
            ledger.card("a.csv", CAFE)
            assert ledger.run("tag", "add", "Trip")[0] == 0
            (purchase,) = ledger.transaction_ids()
            found.append(ledger.tagging_revision(ledger.tag_ok(purchase, "Trip")))
        assert found[0] == found[1] and re.fullmatch(TAGGING_TOKEN, found[0])

    def test_the_version_is_pinned(self):
        from personal_finance.reports import tag_evidence

        assert tag_evidence.TAGGING_REVISION_VERSION == 1


class TestDecisions:  # WC1, D-063's rule for decisions
    @pytest.fixture
    def pair(self, tmp_path, capsys):
        """The same purchase in two files, a possible duplicate, each tagged."""
        found = TagLedger(tmp_path, capsys)
        found.card("a.csv", CAFE)
        found.card("b.csv", CAFE)
        for name in ("Trip", "Work"):
            assert found.run("tag", "add", name)[0] == 0
        found.both = found.transaction_ids()
        assert len(found.both) == 2
        (found.item,) = found.items()
        return found

    def confirm(self, ledger):
        return ledger.run("review", "confirm", ledger.item, "--account", "A", "--revision",
                          ledger.revision(ledger.item), "--group", *ledger.both)

    def test_joining_disagreeing_tags_is_refused(self, pair):
        pair.tag_ok(pair.both[0], "Trip")
        pair.tag_ok(pair.both[1], "Work")
        code, _, err = self.confirm(pair)
        assert code == 2 and err.strip() == f"Error: {decisions.LEAVES_TAGGING_UNSETTLED}"

    def test_joining_agreeing_tags_is_the_control(self, pair):
        pair.tag_ok(pair.both[0], "Trip")
        pair.tag_ok(pair.both[1], "Trip")
        code, _, err = self.confirm(pair)
        assert code == 0, err
        conn = pair.conn()
        assert conn.execute("SELECT state, tags FROM transaction_tag").fetchall() == [
            ("applied", "1")]
        conn.close()

    def test_a_decision_token_covers_tags_in_scope(self, pair, tmp_path):
        code, out, err = self.confirm(pair)
        assert code == 0, err
        decision = re.search(r"Decision (\S+) recorded", out)[1]
        before = re.search(r"Revision: (d12-\S+)",
                           pair.run("review", "decision", "show", decision)[1])[1]
        (merged,) = pair.transaction_ids()
        pair.tag_ok(merged, "Trip")
        after = re.search(r"Revision: (d12-\S+)",
                          pair.run("review", "decision", "show", decision)[1])[1]
        assert before != after
