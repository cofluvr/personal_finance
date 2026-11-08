"""Pending to posted, end to end, using synthetic data only (D-052)."""

import re

import pytest
from test_confirmations import confirm, confirm_ok
from test_coverage_declarations import CoverageLedger
from test_decisions import CHECKING_HEADER

from personal_finance.reconcile.decisions import GROUP_SHARES_DOCUMENT, SAME_DOCUMENT_GROUP

PENDING_WITH_ID = "S-1,2026-01-09,,SYNTHETIC CAFE,-20.00,PENDING"
POSTED_WITH_ID = "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,{amount},POSTED"
PENDING = ",2026-01-09,,SYNTHETIC CAFE,-20.00,PENDING"
POSTED = ",2026-01-09,2026-01-10,SYNTHETIC CAFE,{amount},POSTED"


class PendingLedger(CoverageLedger):
    def statuses(self):
        conn = self.conn()
        found = sorted(row[0] for row in conn.execute("SELECT settlement_status FROM ledger_transaction"))
        conn.close()
        return found

    def holding(self, name, status):
        conn = self.conn()
        (transaction,) = conn.execute(
            """SELECT link.transaction_id FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id
               JOIN record_parse parse ON parse.source_record_id = link.source_record_id
               WHERE document.file_name = ? AND parse.settlement_status = ?""",
            (name, status),
        ).fetchone()
        conn.close()
        return transaction


@pytest.fixture
def ledger(tmp_path, capsys):
    return PendingLedger(tmp_path, capsys)


class TestReliableIds:  # Q1, Q2, Q3
    def test_a_pending_and_a_posted_row_with_one_id_merge(self, ledger):
        ledger.checking("a.csv", PENDING_WITH_ID)
        ledger.checking("b.csv", POSTED_WITH_ID.format(amount="-20.00"))
        assert ledger.count() == 1 and ledger.net() == "-20.00"
        assert ledger.statuses() == ["posted"]
        assert ledger.items() == []

    def test_a_changed_amount_is_counted_once_at_the_posted_amount(self, ledger):
        ledger.checking("a.csv", PENDING_WITH_ID)
        ledger.checking("b.csv", POSTED_WITH_ID.format(amount="-24.00"))
        assert ledger.count() == 1 and ledger.net() == "-24.00"
        totals = ledger.totals()
        assert "Transactions posted at another amount than their pending row, such as with a tip: 1" in totals

    def test_a_different_transaction_date_or_direction_keeps_them_apart(self, ledger):
        ledger.checking("a.csv", PENDING_WITH_ID)
        ledger.checking("b.csv", "S-1,2026-01-08,2026-01-10,SYNTHETIC CAFE,-20.00,POSTED")
        assert ledger.count() == 2
        assert len(ledger.items("cross_document_external_id")) == 1
        ledger.checking("c.csv", "S-2,2026-01-09,,SYNTHETIC SHOP,-20.00,PENDING")
        ledger.checking("d.csv", "S-2,2026-01-09,2026-01-10,SYNTHETIC SHOP,20.00,POSTED")
        assert ledger.count() == 4


class TestWithoutIds:  # Q4, Q5, Q6
    def test_a_tip_raises_a_candidate_that_never_merges_by_itself(self, ledger):
        ledger.checking("a.csv", PENDING)
        ledger.checking("b.csv", POSTED.format(amount="-24.00"))
        assert ledger.count() == 2 and ledger.net() == "-44.00"
        (item,) = ledger.items("cross_document_candidates")
        shown = ledger.show(item)
        assert "pending_amount_changed:" in shown
        assert "possible-duplicate groups" in ledger.totals()

    def test_equal_amounts_are_an_ordinary_candidate(self, ledger):
        ledger.checking("a.csv", PENDING)
        ledger.checking("b.csv", POSTED.format(amount="-20.00"))
        (item,) = ledger.items("cross_document_candidates")
        shown = ledger.show(item)
        assert "similar_description:" in shown and "pending_amount_changed" not in shown

    def test_a_unit_holding_a_posted_row_is_not_pending(self, ledger):
        """A pending and a posted row merged under one ID are posted, so a posted lookalike at
        another amount is not raised as its posting (D-052)."""
        ledger.checking("a.csv", PENDING_WITH_ID)
        ledger.checking("b.csv", POSTED_WITH_ID.format(amount="-24.00"))
        ledger.checking("c.csv", POSTED.format(amount="-30.00"))
        assert ledger.items() == []

    def test_a_changed_description_still_raises_it(self, ledger):
        """Different texts in one description block, found through the block (D-032)."""
        ledger.checking("a.csv", ",2026-01-09,,SQ *SYNTHETIC CAFE,-20.00,PENDING")
        ledger.checking("b.csv", POSTED.format(amount="-24.00"))
        (item,) = ledger.items("cross_document_candidates")
        assert "pending_amount_changed:" in ledger.show(item)

    def test_confirming_counts_it_once_at_the_posted_amount_and_undo_restores_both(self, ledger):
        ledger.checking("a.csv", PENDING)
        ledger.checking("b.csv", POSTED.format(amount="-24.00"))
        (item,) = ledger.items("cross_document_candidates")
        decision = confirm_ok(ledger, item, tuple(ledger.transactions(item)))
        assert ledger.count() == 1 and ledger.net() == "-24.00"
        assert ledger.statuses() == ["posted"]
        assert ledger.undo(decision)[0] == 0
        assert ledger.count() == 2 and ledger.net() == "-44.00"

    @pytest.mark.parametrize("posted", [
        ",2026-01-09,2026-01-10,SYNTHETIC CAFE,24.00,POSTED",
        ",2026-01-09,2026-01-10,UNRELATED WORDS,-24.00,POSTED",
        ",2026-01-19,2026-01-20,SYNTHETIC CAFE,-24.00,POSTED",
        ",2026-01-09,2026-01-10,SYNTHETIC CAFE,-24.00,",
    ])
    def test_nothing_is_raised_without_every_condition(self, ledger, posted):
        ledger.checking("a.csv", PENDING)
        ledger.checking("b.csv", posted)
        assert ledger.items() == []


class TestSameDocument:  # Q7, Q8, Q12
    def flagged_pair(self, ledger):
        ledger.checking("a.csv", PENDING, POSTED.format(amount="-20.00"))
        (item,) = ledger.items("same_document_pending_posted")
        return item

    def test_confirming_joins_them_closes_the_item_and_undo_reopens_it(self, ledger):
        item = self.flagged_pair(ledger)
        assert ledger.count() == 2 and ledger.net() == "-40.00"
        decision = confirm_ok(ledger, item, tuple(ledger.transactions(item)))
        assert ledger.count() == 1 and ledger.net() == "-20.00"
        assert ledger.statuses() == ["posted"]
        assert ledger.items() == []
        assert ledger.link_rules() == ["confirmed_same_event", "confirmed_same_event"]
        assert ledger.undo(decision)[0] == 0
        assert ledger.count() == 2
        assert ledger.items("same_document_pending_posted") == [item]

    def test_only_one_group_of_one_pending_and_one_posted_row(self, ledger):
        ledger.checking("a.csv", PENDING, PENDING, POSTED.format(amount="-20.00"))
        (item,) = ledger.items("same_document_pending_posted")
        pending = sorted(transaction for transaction in ledger.transactions(item)
                         if transaction != ledger.holding("a.csv", "posted"))
        posted = ledger.holding("a.csv", "posted")
        before = ledger.dump()
        for groups in ([(pending[0], posted), (pending[1],)], [(pending[0],), (posted,)],
                       [tuple(pending)], [(*pending, posted)]):
            code, _, err = confirm(ledger, item, *groups)
            assert code == 2 and SAME_DOCUMENT_GROUP in err, (groups, err)
        assert ledger.dump() == before
        confirm_ok(ledger, item, (pending[0], posted))
        assert ledger.count() == 2

    def test_rows_of_one_document_at_another_amount_raise_nothing(self, ledger):
        ledger.checking("a.csv", PENDING, POSTED.format(amount="-24.00"))
        assert ledger.items() == []

    def test_a_merge_cannot_bring_a_second_row_of_a_confirmed_document(self, ledger):
        """A declaration makes a.csv's posted row an exact pair with b.csv's, which a confirmation
        joined to a.csv's pending row. The merge would put two rows of a.csv in one transaction
        that nobody confirmed together, so it is withheld (D-046, D-052)."""
        ledger.checking("a.csv", PENDING, ",2026-01-09,2026-01-10,SYNTHETIC CAFE,-24.00,POSTED")
        ledger.load_path(ledger.write("b.csv", CHECKING_HEADER, [POSTED.format(amount="-24.00")]),
                         "--declare-complete-coverage", "--coverage-start", "2026-01-01",
                         "--coverage-end", "2026-01-31", "--coverage-basis", "transaction",
                         layout="synthetic_checking_v1")
        (item,) = ledger.items("cross_document_candidates")
        confirm_ok(ledger, item, (ledger.holding("a.csv", "pending"), ledger.holding("b.csv", "posted")))
        ledger.declare_ok("a.csv", start="2026-01-01", end="2026-01-31", basis="transaction")
        conn = ledger.conn()
        largest = conn.execute(
            "SELECT MAX(held) FROM (SELECT COUNT(*) AS held FROM transaction_source GROUP BY transaction_id)"
        ).fetchone()[0]
        conn.close()
        assert largest == 2
        assert "Decision conflicts: 1" in ledger.totals()

    def test_a_posted_row_merged_with_another_file_is_refused_not_failed(self, ledger):
        ledger.checking("a.csv", PENDING, POSTED_WITH_ID.format(amount="-20.00"))
        ledger.checking("b.csv", POSTED_WITH_ID.format(amount="-20.00"))
        (item,) = ledger.items("same_document_pending_posted")
        code, _, err = confirm(ledger, item, tuple(ledger.transactions(item)))
        assert code == 2 and SAME_DOCUMENT_GROUP in err

    def test_automatic_matching_never_joins_rows_of_one_document(self, ledger):
        ledger.checking("a.csv", PENDING_WITH_ID, POSTED_WITH_ID.format(amount="-20.00"))
        assert ledger.count() == 2
        ledger.checking("b.csv", POSTED_WITH_ID.format(amount="-20.00"))
        assert ledger.count() == 3

    def test_a_candidate_group_still_cannot_hold_two_rows_of_one_document(self, ledger):
        ledger.checking("a.csv", PENDING, POSTED.format(amount="-20.00"))
        ledger.checking("b.csv", POSTED.format(amount="-20.00"))
        (item,) = ledger.items("cross_document_candidates")
        pending = ledger.holding("a.csv", "pending")
        posted = ledger.holding("a.csv", "posted")
        code, _, err = confirm(ledger, item, (pending, posted, ledger.holding("b.csv", "posted")))
        assert code == 2 and GROUP_SHARES_DOCUMENT in err


class TestUpgrade:  # Q10
    def test_accounts_are_stale_until_reconciled_under_version_2(self, ledger):
        ledger.checking("a.csv", PENDING_WITH_ID)
        ledger.checking("b.csv", POSTED_WITH_ID.format(amount="-24.00"))
        conn = ledger.conn()
        # The marker version 1 rules left, as on a ledger last reconciled before M2.9.
        conn.execute("UPDATE account_reconciliation SET rules_fingerprint = ?, rules_version = 1",
                     ("0df28441bc67a7bac8cd422a7a10e148b8b84e4fcaaa8e090db0507a9f0bf4f6",))
        conn.close()
        assert "have not been reconciled" in ledger.totals()
        assert ledger.run("reconcile")[0] == 0
        assert "have not been reconciled" not in ledger.totals()
        assert ledger.count() == 1


class TestDisclosures:  # Q11, Q15
    def test_stale_pending_is_disclosed_and_left_unchanged(self, ledger):
        ledger.checking("a.csv", ",2026-01-01,,SYNTHETIC CAFE,-20.00,PENDING",
                        ",2026-01-02,2026-01-03,SYNTHETIC SHOP,-4.00,POSTED",
                        ",2026-01-20,2026-01-21,SYNTHETIC GROCER,-9.00,POSTED")
        before = ledger.dump()
        totals = ledger.totals()
        assert "Pending transactions more than 10 days older than the account's latest date: 1" in totals
        assert ledger.dump() == before
        ledger.checking("b.csv", ",2026-01-12,,SYNTHETIC SHOP,-3.00,PENDING")
        assert "older than the account's latest date: 1" in ledger.totals()

    def test_the_new_lines_show_counts_only(self, ledger):
        ledger.checking("a.csv", PENDING_WITH_ID)
        out = ledger.checking("b.csv", POSTED_WITH_ID.format(amount="-24.00"))
        line = re.search(r"Transactions posted at another amount[^\n]*", out)[0]
        assert "24.00" not in line and "20.00" not in line and "CAFE" not in line
