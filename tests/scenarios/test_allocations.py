"""Allocating one transaction among household members, end to end, using synthetic data only (HB1
to HB5, D-065)."""

import re
import sqlite3
from itertools import permutations

import pytest
from test_categorizations import disagreeing_after_undo as categories_disagreeing  # noqa: F401
from test_confirmations import confirm, confirm_ok
from test_correction_order import FILES
from test_decisions import (
    ALL_TABLES,
    ALLOCATION_TABLES,
    CATEGORIZATION_TABLES,
    CATEGORY_RULE_TABLES,
    CATEGORY_TABLES,
    HOUSEHOLD_TABLES,
    drop_allocation_tables,
    pair_up,
)
from test_household import ODD_ROW, HouseholdLedger
from test_separations import ID_ROW, merged_two
from test_supersession import holding
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version
from personal_finance.reconcile.allocations import (
    ALLOCATION_ALONE_UNSETTLED,
    ALLOCATION_NOT_ACTIVE,
    ALLOCATION_NOT_FOUND,
    ALLOCATION_SUPERSEDED,
    ALLOCATION_SUPERSEDED_IN_CHAIN,
    ALLOCATION_SUPERSEDES_NOT_HERE,
    ALLOCATION_UNCHANGED,
    ALLOCATION_UNSETTLED,
    ALLOCATION_WRONG_ACCOUNT,
    ALREADY_ALLOCATED,
    AMOUNT_PART_MALFORMED,
    AMOUNTS_NOT_WHOLE,
    PERCENT_ONE_PART,
    STALE_ALLOCATION_REVISION,
)
from personal_finance.reconcile.decisions import (
    LEAVES_ALLOCATION_UNSETTLED,
    LEAVES_CATEGORIZATION_UNSETTLED,
    STALE_ACCOUNT,
)
from personal_finance.reconcile.household import (
    ATTRIBUTION_WITHOUT_SHARE,
    MEMBER_UNKNOWN,
    SHARE_MEMBER_REPEATED,
    SHARE_NOT_WHOLE,
    SHARE_PART_MALFORMED,
)
from personal_finance.reconcile.statements import (
    STALE_TRANSACTION_REVISION,
    TRANSACTION_WRONG_ACCOUNT,
)
from personal_finance.reports import (
    allocation_evidence,
    correction_evidence,
    decision_evidence,
    review_evidence,
)

LEDGER_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                 *CATEGORY_RULE_TABLES, *HOUSEHOLD_TABLES, *ALLOCATION_TABLES)

CAFE = "01/10/2026,SYNTHETIC CAFE,6.50,"


class AllocationLedger(HouseholdLedger):
    def allocate(self, transaction, *how, revision=None, account="A", supersedes=None,
                 supersedes_revision=None):
        words = ["review", "allocate", transaction, "--account", account, "--revision",
                 revision or self.transaction_revision(transaction), *how]
        if supersedes:
            words += ["--supersedes", supersedes, "--supersedes-revision",
                      supersedes_revision or self.allocation_revision(supersedes)]
        return self.run(*words)

    def allocate_ok(self, transaction, *how, **options):
        code, out, err = self.allocate(transaction, *how, **options)
        assert (code, err) == (0, ""), err
        return re.search(r"Allocation (\S+) recorded", out)[1]

    def allocation_show(self, allocation):
        code, out, err = self.run("review", "allocation", "show", allocation)
        assert code == 0, err
        return out

    def allocation_revision(self, allocation):
        return re.search(r"Revision: (s1-[0-9a-f]{16})", self.allocation_show(allocation))[1]

    def allocation_state(self, allocation):
        return re.search(r"Status: (\S+)", self.allocation_show(allocation))[1]

    def undo_allocation(self, allocation, revision=None, account="A"):
        return self.run("review", "allocation", "undo", allocation, "--account", account,
                        "--revision", revision or self.allocation_revision(allocation))

    def allocation_outcomes(self):
        """Each transaction an allocation reaches as its file names, state and canonical value
        by member names."""
        conn = self.conn()
        names = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            names.setdefault(transaction_id, []).append(name)
        members = dict(conn.execute("SELECT id, name FROM household_member"))
        found = sorted(
            (tuple(sorted(names[transaction_id])), state,
             value and re.sub(r"(\d+)=", lambda match: f"{members[int(match[1])]}=", value))
            for transaction_id, state, value in conn.execute(
                "SELECT transaction_id, state, allocation FROM transaction_allocation")
        )
        conn.close()
        return found

    def everything(self):
        return self.dump(LEDGER_TABLES)


@pytest.fixture
def ledger(tmp_path, capsys):
    found = AllocationLedger(tmp_path, capsys)
    found.add_member_ok("Michael", "M")
    found.set_share_ok("Michael=50", "M=50")
    return found


def single(ledger, row=CAFE, name="a.csv"):
    ledger.card(name, row)
    return holding(ledger, name)


class TestAllocate:  # HB1, HB2
    @pytest.mark.parametrize(("how", "stored", "line"), [
        (("--member", "M"), "member:M=10000", "Household: M, by an allocation"),
        (("--shared",), "shared:",
         "Household: shared, by an allocation and the household share: Michael -3.25, M -3.25"),
        (("--percent", "M=60", "--percent", "Michael=40"), "percent:Michael=4000,M=6000",
         "Household: allocated, by an allocation: Michael -2.60, M -3.90"),
        (("--amount", "M=6", "--amount", "Michael=0.50"), "amount:Michael=50,M=600",
         "Household: allocated, by an allocation: Michael -0.50, M -6.00"),
    ])
    def test_each_kind_binds_and_applies(self, ledger, how, stored, line):
        transaction = single(ledger)
        code, out, err = ledger.allocate(transaction, *how)
        assert (code, err) == (0, "")
        assert re.fullmatch(rf"Allocation \S+ recorded: transaction {transaction} .*, binding 1 "
                            r"records\.\n  .*\n", out)
        assert ledger.allocation_outcomes() == [(("a.csv",), "applied", stored)]
        assert f"  {line}\n" in ledger.transaction_show(transaction)

    def test_it_comes_before_the_account_default(self, ledger):
        transaction = single(ledger)
        ledger.set_default_ok(member="Michael")
        ledger.allocate_ok(transaction, "--member", "M")
        assert ledger.household_line(transaction) == "M, by an allocation"

    def test_a_percentage_follows_a_corrected_amount(self, ledger):
        transaction = single(ledger, ODD_ROW)
        ledger.allocate_ok(transaction, "--percent", "Michael=50", "--percent", "M=50")
        ledger.correct_ok(transaction, "amount", "-10.01")
        assert ledger.household_line(transaction) == (
            "allocated, by an allocation: Michael -5.01, M -5.00")

    def test_amounts_sign_by_direction_and_a_refund_nets_to_zero(self, ledger):
        purchase = single(ledger, ODD_ROW)
        refund = single(ledger, "01/11/2026,SYNTHETIC CAFE,,6.51", "b.csv")
        ledger.allocate_ok(purchase, "--amount", "Michael=5", "--amount", "M=1.51")
        ledger.allocate_ok(refund, "--amount", "Michael=5", "--amount", "M=1.51")
        assert ledger.household_line(purchase) == (
            "allocated, by an allocation: Michael -5.00, M -1.51")
        assert ledger.household_line(refund) == "allocated, by an allocation: Michael 5.00, M 1.51"

    def test_every_type_can_be_allocated(self, ledger):
        transaction = single(ledger)
        ledger.classify_ok(transaction, "transfer")
        ledger.allocate_ok(transaction, "--member", "M")
        assert ledger.allocation_outcomes() == [(("a.csv",), "applied", "member:M=10000")]

    def test_parts_in_any_typed_order_store_one_value(self, ledger):
        one = single(ledger)
        two = single(ledger, "01/12/2026,SYNTHETIC SHOP,6.50,", "b.csv")
        ledger.allocate_ok(one, "--percent", "M=60", "--percent", "Michael=40")
        ledger.allocate_ok(two, "--percent", "Michael=40", "--percent", "M=60")
        values = {value for _, _, value in ledger.allocation_outcomes()}
        assert values == {"percent:Michael=4000,M=6000"}

    def test_the_default_and_the_share_reach_what_allocations_leave(self, ledger):
        one = single(ledger)
        single(ledger, "01/12/2026,SYNTHETIC SHOP,9.00,", "b.csv")
        ledger.set_default_ok(member="Michael")
        assert "The default reaches: 2 transactions, 15.50 out" in ledger.account_show()
        assert "The share reaches: 0 transactions" in ledger.share_show()
        ledger.allocate_ok(one, "--shared")
        assert "The default reaches: 1 transactions, 9.00 out" in ledger.account_show()
        assert "The share reaches: 1 transactions, 6.50 out" in ledger.share_show()
        assert "Accounts attributed shared: none" in ledger.share_show()

    def test_an_account_a_shared_allocation_reaches_must_be_current_for_the_share(self, ledger):
        from test_household import make_stale
        ledger.add_account("B", "credit_card")
        ledger.card("b.csv", CAFE, account="B")
        ledger.allocate_ok(holding(ledger, "b.csv"), "--shared", account="B")
        make_stale(ledger, "B")
        token = ledger.share_revision()
        before = ledger.everything()
        code, _, err = ledger.undo_share(token)
        assert (code, err) == (2, f"Error: {STALE_ACCOUNT}\n")
        assert ledger.everything() == before

    def test_it_changes_no_total_or_report(self, ledger):
        transaction = single(ledger)
        before = [ledger.run(*words) for words in (("totals",), ("report", "monthly"))]
        ledger.allocate_ok(transaction, "--member", "M")
        assert [ledger.run(*words) for words in (("totals",), ("report", "monthly"))] == before


class TestRefusals:  # HB1
    def refused(self, ledger, message, transaction, *how, revision=None, account="A"):
        before = ledger.everything()
        code, _, err = ledger.allocate(transaction, *how, revision=revision, account=account)
        assert (code, err) == (2, f"Error: {message}\n")
        assert ledger.everything() == before

    @pytest.mark.parametrize(("how", "message"), [
        (("--member", "Nobody"), MEMBER_UNKNOWN),
        (("--percent", "Michael=100"), PERCENT_ONE_PART),
        (("--percent", "Michael=50", "--percent", "M=49.99"), SHARE_NOT_WHOLE),
        (("--percent", "Michael=50", "--percent", "Nobody=50"), MEMBER_UNKNOWN),
        (("--percent", "Michael=50.005", "--percent", "M=49.995"), SHARE_PART_MALFORMED),
        (("--amount", "Michael=3", "--amount", "M=3"), AMOUNTS_NOT_WHOLE),
        (("--amount", "Michael=6.51"), AMOUNTS_NOT_WHOLE),
        (("--amount", "Michael=6.505"), AMOUNT_PART_MALFORMED),
        (("--amount", "Michael=-6.50"), AMOUNT_PART_MALFORMED),
        (("--amount", "Michael=$6.50"), AMOUNT_PART_MALFORMED),
        (("--amount", "Michael=0", "--amount", "M=6.50"), AMOUNT_PART_MALFORMED),
        (("--amount", "Michael"), AMOUNT_PART_MALFORMED),
        (("--amount", "Nobody=6.50"), MEMBER_UNKNOWN),
        (("--amount", "M=3.25", "--amount", "M=3.25"), SHARE_MEMBER_REPEATED),
    ])
    def test_a_value_that_does_not_fit(self, ledger, how, message):
        self.refused(ledger, message, single(ledger), *how)

    def test_shared_with_no_active_share(self, ledger):
        transaction = single(ledger)
        assert ledger.undo_share()[0] == 0
        self.refused(ledger, ATTRIBUTION_WITHOUT_SHARE, transaction, "--shared")

    def test_a_stale_token(self, ledger):
        transaction = single(ledger)
        token = ledger.transaction_revision(transaction)
        ledger.correct_ok(transaction, "description", "SYNTHETIC OTHER")
        self.refused(ledger, STALE_TRANSACTION_REVISION, transaction, "--member", "M",
                     revision=token)

    def test_another_account_s_transaction(self, ledger):
        ledger.add_account("B", "credit_card")
        transaction = single(ledger)
        self.refused(ledger, TRANSACTION_WRONG_ACCOUNT, transaction, "--member", "M",
                     account="B")

    def test_the_account_is_checked_first(self, ledger):
        from test_household import make_stale
        transaction = single(ledger)
        make_stale(ledger)
        self.refused(ledger, STALE_ACCOUNT, transaction, "--member", "Nobody",
                     revision="t10-0000000000000000")

    def test_the_same_allocation_again(self, ledger):
        transaction = single(ledger)
        allocation = ledger.allocate_ok(transaction, "--member", "M")
        self.refused(ledger, ALREADY_ALLOCATED.format(allocation=allocation), transaction,
                     "--member", "M")
        before = ledger.everything()
        code, _, err = ledger.allocate(transaction, "--member", "M", supersedes=allocation)
        assert (code, err) == (2, f"Error: {ALLOCATION_UNCHANGED}\n")
        assert ledger.everything() == before

    def test_one_kind_at_a_time(self, ledger, capsys):
        transaction = single(ledger)
        before = ledger.everything()
        with pytest.raises(SystemExit) as exit_info:
            ledger.allocate(transaction, "--member", "M", "--shared")
        assert exit_info.value.code == 2 and "not allowed with" in capsys.readouterr().err
        assert ledger.everything() == before


class TestSurvival:  # HB2
    def allocated(self, ledger):
        ledger.allocate_ok(single(ledger), "--percent", "Michael=30", "--percent", "M=70")
        return ledger.allocation_outcomes()

    def test_a_repeat_import(self, ledger):
        outcomes = self.allocated(ledger)
        ledger.load_path(ledger.folder / "a.csv")
        assert ledger.allocation_outcomes() == outcomes

    def test_reconcile(self, ledger):
        outcomes = self.allocated(ledger)
        assert ledger.run("reconcile")[0] == 0
        assert ledger.allocation_outcomes() == outcomes

    def test_a_re_export_that_merges_keeps_it_applied_and_binds_nothing_new(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        allocation = ledger.allocate_ok(holding(ledger, "a.csv"), "--member", "M")
        ledger.checking("b.csv", ID_ROW)
        assert ledger.count() == 1
        assert ledger.allocation_outcomes() == [(("a.csv", "b.csv"), "applied", "member:M=10000")]
        bound = ledger.allocation_show(allocation).split("Bound records:\n")[1]
        bound = bound.split("  Revision:")[0]
        assert "a.csv row 1" in bound and "b.csv" not in bound


def disagreeing_after_undo(ledger):
    """a and b merged, separated, allocated differently, and merged again by undoing the
    separation."""
    transaction, records = merged_two(ledger)
    separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
    first = ledger.allocate_ok(holding(ledger, "a.csv"), "--member", "M")
    second = ledger.allocate_ok(holding(ledger, "b.csv"), "--shared")
    code, out, err = ledger.undo(separation)
    assert code == 0, err
    return first, second, out


def refused_alone(ledger, allocation, transaction):
    """Allocating where one allocation alone leaves the transaction unattributed names it, and
    says to undo it rather than all but one."""
    before = ledger.everything()
    code, _, err = ledger.allocate(transaction, "--member", "Michael")
    assert (code, err) == (2, "Error: " + ALLOCATION_ALONE_UNSETTLED.format(
        allocations=allocation) + "\n")
    assert ledger.everything() == before


class TestSeveral:  # HB2, HB3
    def test_agreeing_allocations_apply_once(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.allocate_ok(one, "--shared")
        ledger.allocate_ok(two, "--shared")
        (item,) = ledger.items()
        confirm_ok(ledger, item, (one, two))
        assert ledger.allocation_outcomes() == [(("a.csv", "b.csv"), "applied", "shared:")]

    def test_shared_and_its_percentages_disagree(self, ledger):
        item, one, two = pair_up(ledger)
        ledger.allocate_ok(one, "--shared")
        ledger.allocate_ok(two, "--percent", "Michael=50", "--percent", "M=50")
        (item,) = ledger.items()
        before = ledger.everything()
        code, _, err = confirm(ledger, item, (one, two))
        assert code == 2 and LEAVES_ALLOCATION_UNSETTLED in err
        assert ledger.everything() == before

    def test_disagreeing_ones_leave_it_unattributed_never_the_default(self, ledger):
        ledger.set_default_ok(member="Michael")
        _, _, out = disagreeing_after_undo(ledger)
        assert "Transactions now unattributed, because allocations disagree" in out
        assert ledger.allocation_outcomes() == [(("a.csv", "b.csv"), "conflict", None)]
        assert ledger.household_line(holding(ledger, "a.csv")) == (
            "unattributed: allocations disagree. Undo all but one to settle it")
        listed = ledger.run("review", "allocations")[1]
        assert re.search(r"^Transaction \S+: allocations disagree", listed, re.MULTILINE)

    def test_a_disagreement_refuses_allocating_until_settled(self, ledger):
        first, second, _ = disagreeing_after_undo(ledger)
        transaction = holding(ledger, "a.csv")
        before = ledger.everything()
        code, _, err = ledger.allocate(transaction, "--member", "Michael")
        assert (code, err) == (2, "Error: " + ALLOCATION_UNSETTLED.format(
            allocations=", ".join(sorted((first, second)))) + "\n")
        assert ledger.everything() == before
        code, out, _ = ledger.undo_allocation(second)
        assert code == 0 and "now unattributed" not in out
        assert ledger.allocation_outcomes() == [(("a.csv", "b.csv"), "applied", "member:M=10000")]

    def test_an_automatic_split_leaves_every_part_unattributed(self, ledger):
        ledger.checking("a.csv", "S-1,2026-01-09,,SYNTHETIC CAFE,-5.00,")
        ledger.checking("b.csv", "S-1,2026-01-09,2026-01-10,SYNTHETIC CAFE,-5.00,POSTED")
        (transaction,) = ledger.merges()
        allocation = ledger.allocate_ok(transaction, "--member", "M")
        ledger.checking("c.csv", "S-1,2026-01-09,2026-01-11,SYNTHETIC CAFE,-5.00,POSTED")
        assert ledger.allocation_outcomes() == [(("a.csv",), "basis_changed", None),
                                                (("b.csv",), "basis_changed", None)]
        out = ledger.allocation_show(allocation)
        assert out.count("unattributed, basis changed now, unattributed after") == 0
        assert out.count("basis changed now") == 2
        refused_alone(ledger, allocation, holding(ledger, "a.csv"))

    def test_an_amount_correction_leaves_an_amount_allocation_unattributed(self, ledger):
        ledger.set_default_ok(member="Michael")
        transaction = single(ledger)
        allocation = ledger.allocate_ok(transaction, "--amount", "M=6.50")
        correction = ledger.correct_ok(transaction, "amount", "-7.00")
        assert ledger.allocation_outcomes() == [(("a.csv",), "amount_differs", None)]
        assert ledger.household_line(transaction) == (
            "unattributed: an allocation by amount no longer sums to its amount. Undo it, or what "
            "changed the amount")
        assert ledger.allocation_state(allocation) == "active"
        refused_alone(ledger, allocation, transaction)
        assert ledger.undo_correction(correction)[0] == 0
        assert ledger.allocation_outcomes() == [(("a.csv",), "applied", "amount:M=650")]


class TestDecisionCommands:  # HB3
    def test_separating_an_allocation_s_records_refuses_after_categories(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        ledger.checking("b.csv", ID_ROW)
        (transaction,) = ledger.merges()
        ledger.allocate_ok(transaction, "--member", "M")
        records = ledger.records(transaction)
        before = ledger.everything()
        code, _, err = ledger.separate(transaction, [records["a.csv"]], [records["b.csv"]])
        assert code == 2 and LEAVES_ALLOCATION_UNSETTLED in err
        assert ledger.everything() == before
        ledger.categorize_ok(transaction, "Food")
        before = ledger.everything()
        code, _, err = ledger.separate(transaction, [records["a.csv"]], [records["b.csv"]])
        assert code == 2 and LEAVES_CATEGORIZATION_UNSETTLED in err
        assert ledger.everything() == before

    def test_separating_records_an_allocation_does_not_bind_is_allowed(self, ledger):
        ledger.checking("a.csv", ID_ROW)
        ledger.allocate_ok(holding(ledger, "a.csv"), "--member", "M")
        ledger.checking("b.csv", ID_ROW)
        (transaction,) = ledger.merges()
        records = ledger.records(transaction)
        ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        assert ledger.allocation_outcomes() == [(("a.csv",), "applied", "member:M=10000")]

    def test_an_allocation_made_since_makes_the_decision_token_stale(self, ledger):
        from personal_finance.reconcile.decisions import STALE_DECISION_REVISION
        item, one, two = pair_up(ledger)
        decision = confirm_ok(ledger, item, (one, two))
        old = ledger.decision_revision(decision)
        ledger.allocate_ok(holding(ledger, "a.csv"), "--member", "M")
        before = ledger.everything()
        code, _, err = ledger.undo(decision, old)
        assert code == 2 and STALE_DECISION_REVISION in err
        assert ledger.everything() == before
        code, out, _ = ledger.undo(decision)
        assert code == 0
        assert "Transactions now unattributed, because allocations disagree" in out
        assert ledger.allocation_outcomes() == [(("a.csv",), "basis_changed", None),
                                                (("b.csv",), "basis_changed", None)]


def chain_of_three(ledger):
    transaction = single(ledger)
    first = ledger.allocate_ok(transaction, "--member", "M")
    second = ledger.allocate_ok(transaction, "--shared", supersedes=first)
    third = ledger.allocate_ok(transaction, "--amount", "Michael=6.50", supersedes=second)
    return transaction, first, second, third


class TestChains:  # HB3
    def test_only_the_newest_applies(self, ledger):
        _, first, second, third = chain_of_three(ledger)
        assert ledger.allocation_outcomes() == [(("a.csv",), "applied", "amount:Michael=650")]
        assert [ledger.allocation_state(each) for each in (first, second, third)] == [
            "superseded", "superseded", "active"]

    def test_undo_steps_back_one_link_at_a_time(self, ledger):
        _, first, second, third = chain_of_three(ledger)
        code, out, _ = ledger.undo_allocation(third)
        assert code == 0 and f"Allocation {second}, which it superseded, applies again." in out
        assert ledger.allocation_outcomes() == [(("a.csv",), "applied", "shared:")]
        assert ledger.undo_allocation(second)[0] == 0
        assert ledger.allocation_outcomes() == [(("a.csv",), "applied", "member:M=10000")]
        assert ledger.undo_allocation(first)[0] == 0
        assert ledger.allocation_outcomes() == []

    def test_undo_leaves_the_account_default(self, ledger):
        transaction = single(ledger)
        ledger.set_default_ok(member="Michael")
        allocation = ledger.allocate_ok(transaction, "--member", "M")
        assert ledger.undo_allocation(allocation)[0] == 0
        assert ledger.household_line(transaction) == "Michael, by the account's default"

    def test_a_superseded_one_names_the_newest_and_refuses(self, ledger):
        _, first, second, third = chain_of_three(ledger)
        before = ledger.everything()
        code, _, err = ledger.undo_allocation(second, "s1-0000000000000000")
        assert (code, err) == (2, "Error: " + ALLOCATION_SUPERSEDED.format(newer=third) + "\n")
        code, _, err = ledger.undo_allocation(first, "s1-0000000000000000")
        assert (code, err) == (2, "Error: " + ALLOCATION_SUPERSEDED_IN_CHAIN.format(
            newer=second, newest=third) + "\n")
        assert ledger.everything() == before

    def test_superseding_one_applying_elsewhere(self, ledger):
        one = single(ledger)
        two = single(ledger, "01/12/2026,SYNTHETIC SHOP,9.00,", "b.csv")
        elsewhere = ledger.allocate_ok(one, "--member", "M")
        before = ledger.everything()
        code, _, err = ledger.allocate(two, "--shared", supersedes=elsewhere)
        assert (code, err) == (2, f"Error: {ALLOCATION_SUPERSEDES_NOT_HERE}\n")
        assert ledger.everything() == before

    def test_a_superseding_allocation_in_conflict_refuses(self, ledger):
        first, second, _ = disagreeing_after_undo(ledger)
        before = ledger.everything()
        code, _, err = ledger.allocate(holding(ledger, "a.csv"), "--member", "Michael",
                                       supersedes=first)
        assert code == 2 and "they disagree" in err
        assert ledger.everything() == before


class TestUndo:  # HB3
    def test_a_stale_token(self, ledger):
        transaction = single(ledger)
        allocation = ledger.allocate_ok(transaction, "--amount", "M=6.50")
        token = ledger.allocation_revision(allocation)
        ledger.correct_ok(transaction, "amount", "-7.00")
        before = ledger.everything()
        code, _, err = ledger.undo_allocation(allocation, token)
        assert (code, err) == (2, f"Error: {STALE_ALLOCATION_REVISION}\n")
        assert ledger.everything() == before

    def test_an_undone_unknown_or_other_account_s_allocation(self, ledger):
        ledger.add_account("B", "credit_card")
        allocation = ledger.allocate_ok(single(ledger), "--member", "M")
        token = ledger.allocation_revision(allocation)
        for words, message in (
            ((allocation, token, "B"), ALLOCATION_WRONG_ACCOUNT),
            (("no-such", token, "A"), ALLOCATION_NOT_FOUND),
        ):
            before = ledger.everything()
            code, _, err = ledger.undo_allocation(words[0], words[1], account=words[2])
            assert (code, err) == (2, f"Error: {message}\n")
            assert ledger.everything() == before
        assert ledger.undo_allocation(allocation, token)[0] == 0
        before = ledger.everything()
        code, _, err = ledger.undo_allocation(allocation, token)
        assert (code, err) == (2, f"Error: {ALLOCATION_NOT_ACTIVE}\n")
        assert ledger.everything() == before

    def test_it_equals_a_ledger_built_without_it(self, tmp_path, capsys):
        found = []
        for name, allocated in (("with", True), ("without", False)):
            (tmp_path / name).mkdir()
            built = AllocationLedger(tmp_path / name, capsys)
            built.add_member_ok("Michael", "M")
            built.set_share_ok("Michael=50", "M=50")
            transaction = single(built)
            if allocated:
                allocation = built.allocate_ok(transaction, "--shared")
                assert built.undo_allocation(allocation)[0] == 0
            found.append((built.totals(), built.allocation_outcomes(),
                          built.transaction_revision(transaction)))
        assert found[0] == found[1]


class TestShown:  # HB2
    def test_the_lists_and_show_name_members_and_print_no_amounts(self, ledger):
        transaction = single(ledger)
        allocation = ledger.allocate_ok(transaction, "--amount", "Michael=2.50", "--amount",
                                        "M=4")
        code, out, _ = ledger.run("review", "allocations", "--account", "A")
        assert code == 0
        assert re.match(rf"Allocation {allocation}: active, by amount: Michael, M, 1 "
                        r"records, A, \S+\nAllocations: 1\nTo see what", out)
        shown = ledger.allocation_show(allocation)
        assert "  Allocation: by amount: Michael, M\n  Status: active\n" in shown
        assert f"  Transaction {transaction}: allocated now, by the account's default after" in (
            shown)
        for text in (shown, out):
            assert "2.50" not in text and "4.00" not in text and "6.50" not in text
            assert "CAFE" not in text

    def test_names_are_escaped(self, ledger):
        odd = "Odd\x1b[2J\nname"
        ledger.add_member_ok(odd)
        transaction = single(ledger)
        allocation = ledger.allocate_ok(transaction, "--member", odd)
        for shown in (ledger.run("review", "allocations")[1], ledger.allocation_show(allocation),
                      ledger.transaction_show(transaction)):
            assert "Odd\\x1b[2J\\nname" in shown and "\x1b" not in shown


def every_token(ledger, item, transaction, decision, correction):
    return (ledger.revision(item), ledger.transaction_revision(transaction),
            ledger.decision_revision(decision), ledger.correction_revision(correction))


@pytest.fixture
def decided(ledger):
    """A rejected pair, the first with a corrected amount, and an open item beside them."""
    item, one, two = pair_up(ledger)
    decision = ledger.reject_ok(item, (one, two))
    correction = ledger.correct_ok(one, "amount", "-7.00")
    ledger.card("c.csv", CAFE)
    (open_item,) = ledger.items()
    return open_item, one, decision, correction


class TestTokens:  # HB4
    def test_the_versions_are_pinned(self):
        assert review_evidence.REVISION_VERSION == 12
        assert review_evidence.TRANSACTION_REVISION_VERSION == 10
        assert decision_evidence.DECISION_REVISION_VERSION == 9
        assert correction_evidence.CORRECTION_REVISION_VERSION == 5
        assert allocation_evidence.ALLOCATION_REVISION_VERSION == 1

    def test_members_shares_and_defaults_change_no_token(self, ledger, decided):
        before = every_token(ledger, *decided)
        ledger.add_member_ok("K")
        ledger.set_default_ok(member="K")
        assert ledger.undo_share()[0] == 0
        assert every_token(ledger, *decided) == before

    def test_an_allocation_reaching_them_changes_each_and_undo_restores_them(self, ledger,
                                                                              decided):
        _, one, _, _ = decided
        before = every_token(ledger, *decided)
        allocation = ledger.allocate_ok(one, "--amount", "M=7")
        after = every_token(ledger, *decided)
        assert all(changed != unchanged for changed, unchanged in zip(after, before))
        assert ledger.undo_allocation(allocation)[0] == 0
        assert every_token(ledger, *decided) == before

    def test_the_allocation_token_is_the_same_in_any_ledger_holding_the_same(self, tmp_path,
                                                                            capsys):
        tokens = []
        for name in ("one", "two"):
            (tmp_path / name).mkdir()
            built = AllocationLedger(tmp_path / name, capsys)
            built.add_member_ok("Michael", "M")
            allocation = built.allocate_ok(single(built), "--percent", "Michael=10", "--percent",
                                           "M=90")
            tokens.append(built.allocation_revision(allocation))
        assert tokens[0] == tokens[1]
        assert tokens[0] == PINNED_ALLOCATION_REVISION

    def test_an_amount_correction_s_token_covers_an_allocation(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "amount", "-6.00")
        token = ledger.correction_revision(correction)
        ledger.allocate_ok(transaction, "--member", "M")
        assert ledger.correction_revision(correction) != token

    def test_a_description_correction_s_token_does_not(self, ledger):
        transaction = single(ledger)
        correction = ledger.correct_ok(transaction, "description", "SYNTHETIC OTHER")
        token = ledger.correction_revision(correction)
        ledger.allocate_ok(transaction, "--member", "M")
        assert ledger.correction_revision(correction) == token


# Computed when M11.2 was built, as a regression pin: 10/90 on a.csv's 6.50 purchase.
PINNED_ALLOCATION_REVISION = "s1-234884301b84ab20"


def outcome(ledger):
    """Everything but revisions, which cover the bound records and so differ by design."""
    view = ledger.view()
    del view["revisions"]
    return view, ledger.allocation_outcomes()


def bound_files(ledger, allocation):
    conn = ledger.conn()
    found = sorted(row[0] for row in conn.execute(
        """SELECT document.file_name FROM allocation_statement_record bound
           JOIN source_record record ON record.id = bound.source_record_id
           JOIN source_document document ON document.id = record.source_document_id
           WHERE bound.allocation_id = ?""",
        (allocation,),
    ))
    conn.close()
    return found


def built(folder, capsys, order, point):
    """Imports in this order, allocating a's event 30/70 after the first point imports."""
    folder.mkdir()
    ledger = AllocationLedger(folder, capsys)
    ledger.add_member_ok("Michael", "M")
    allocation = None
    for position, name in enumerate(order, start=1):
        layout, content = FILES[name]
        path = folder / name
        path.write_text(content)
        ledger.load_path(path, layout=layout)
        if position == point:
            allocation = ledger.allocate_ok(holding(ledger, "a.csv"), "--percent", "Michael=30",
                                            "--percent", "M=70")
    return ledger, allocation


def test_every_valid_point_of_every_order_gives_the_same_outcome(tmp_path, capsys):  # HB4
    reference = None
    compared = 0
    for order in permutations(FILES):
        first_valid = order.index("a.csv") + 1
        for point in range(first_valid, len(order) + 1):
            ledger, allocation = built(tmp_path / f"case{compared}", capsys, order, point)
            found = outcome(ledger)
            reference = reference or found
            assert found == reference, (order, point)
            b_before = order.index("b.csv") + 1 <= point
            expected = ["a.csv", "b.csv"] if b_before else ["a.csv"]
            assert bound_files(ledger, allocation) == expected, (order, point)
            compared += 1
    assert compared == 60
    assert reference[1] == [(("a.csv", "b.csv"), "applied", "percent:Michael=3000,M=7000")]


VERSION_22_TABLES = (*ALL_TABLES, "account", *CATEGORY_TABLES, *CATEGORIZATION_TABLES,
                     *CATEGORY_RULE_TABLES, *HOUSEHOLD_TABLES)
SHOWN_BEFORE_AND_AFTER = [("totals",), ("report", "monthly"), ("transactions",),
                          ("household", "members"), ("household", "share", "show"),
                          ("household", "account", "show", "--account", "A")]


def shown_now(ledger):
    return [ledger.run(*words) for words in (
        *SHOWN_BEFORE_AND_AFTER, ("review", "transaction", "show", holding(ledger, "a.csv")))]


@pytest.fixture
def populated(tmp_path, capsys):
    """Card A shared by default between two members, set back to 22, with what was shown."""
    ledger = AllocationLedger(tmp_path, capsys)
    ledger.add_member_ok("Michael", "M")
    ledger.set_share_ok("Michael=50", "M=50")
    single(ledger)
    ledger.set_default_ok()
    ledger.shown_before = shown_now(ledger)
    conn = connect(ledger.path)
    drop_allocation_tables(conn)
    conn.execute("PRAGMA user_version = 22")
    conn.close()
    return ledger


class TestMigration:  # HB5
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_22_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "twenty-three", 23)) == 23
        for table in ALLOCATION_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_22_TABLES) == before
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert shown_now(populated) == populated.shown_before

    def test_a_ledger_at_22_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("review", "allocations")
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("review", "allocations")[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 23)
        newest = load_migrations()[22].path
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_22_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 22
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(ALLOCATION_TABLES)
        conn.close()
        assert populated.dump(VERSION_22_TABLES) == before


@pytest.fixture
def history(ledger):
    """A chain of three allocations, the newest undone."""
    _, _, _, third = chain_of_three(ledger)
    assert ledger.undo_allocation(third)[0] == 0
    return ledger


class TestAppendOnly:  # HB5
    @pytest.mark.parametrize("statement", [
        "UPDATE allocation_statement SET allocation = allocation",
        "DELETE FROM allocation_statement",
        "INSERT INTO allocation_statement SELECT * FROM allocation_statement",
        "UPDATE allocation_statement_part SET value = value",
        "DELETE FROM allocation_statement_part",
        "INSERT INTO allocation_statement_part SELECT * FROM allocation_statement_part",
        "UPDATE allocation_statement_record SET source_record_id = source_record_id",
        "DELETE FROM allocation_statement_record",
        "INSERT INTO allocation_statement_record SELECT * FROM allocation_statement_record",
        "UPDATE allocation_statement_event SET event = event",
        "DELETE FROM allocation_statement_event",
        "INSERT INTO allocation_statement_event (allocation_id, event) "
        "SELECT allocation_id, event FROM allocation_statement_event",
    ])
    def test_history_refuses_change(self, history, statement):
        before = history.everything()
        conn = history.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert history.everything() == before

    def statement(self, conn, allocation_id, value, parts, account="A"):
        conn.execute(
            """INSERT INTO allocation_statement (id, account_id, allocation, target_transaction_id,
                                                 target_revision)
               SELECT ?, id, ?, 't', 'r' FROM account WHERE display_name = ?""",
            (allocation_id, value, account))
        conn.executemany("INSERT INTO allocation_statement_part VALUES (?, ?, ?)",
                         [(allocation_id, member, part) for member, part in parts])

    def made(self, conn, allocation_id):
        conn.execute("INSERT INTO allocation_statement_event (allocation_id, event) "
                     "VALUES (?, 'made')", (allocation_id,))

    @pytest.mark.parametrize(("value", "parts"), [
        ("percent:1=5000,2=4999", [(1, 5000), (2, 4999)]),
        ("percent:2=5000,1=5000", [(1, 5000), (2, 5000)]),
        ("percent:1=10000", [(1, 10000)]),
        ("member:1=5000", [(1, 5000)]),
        ("shared:", [(1, 10000)]),
        ("amount:", []),
        ("amount:1=650,2=1", [(1, 650)]),
    ])
    def test_the_schema_refuses_parts_not_matching_the_value(self, ledger, value, parts):
        conn = ledger.conn()
        self.statement(conn, "bad", value, parts)
        with pytest.raises(sqlite3.IntegrityError):
            self.made(conn, "bad")
        self.statement(conn, "control", "percent:1=5000,2=5000", [(2, 5000), (1, 5000)])
        self.made(conn, "control")
        conn.close()

    @pytest.mark.parametrize("value", ["split:1=10000", "member", "", "shared:1=1"])
    def test_the_schema_refuses_an_unknown_kind(self, ledger, value):
        conn = ledger.conn()
        with pytest.raises(sqlite3.IntegrityError):
            self.statement(conn, "bad", value, [])
        self.statement(conn, "control", "shared:", [])
        self.made(conn, "control")
        conn.close()

    def test_the_schema_refuses_a_part_once_made(self, history):
        conn = history.conn()
        # The shared one has no parts, so only the trigger on a made allocation can refuse this.
        (made,) = conn.execute(
            "SELECT id FROM allocation_statement WHERE allocation = 'shared:'").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO allocation_statement_part VALUES (?, 2, 1)", (made,))
        self.statement(conn, "control", "member:2=10000", [(2, 10000)])
        conn.close()

    def test_an_allocation_supersedes_only_its_own_account(self, history):
        history.add_account("B", "credit_card")
        conn = history.conn()
        (newest,) = conn.execute(
            "SELECT id FROM allocation_statement ORDER BY created_at DESC LIMIT 1").fetchone()
        for allocation_id, account in (("other", "B"), ("control", "A")):
            insert = """INSERT INTO allocation_statement (id, account_id, allocation,
                                                          target_transaction_id, target_revision,
                                                          supersedes_allocation_id)
                        SELECT ?, id, 'shared:', 't', 'r', ? FROM account WHERE display_name = ?"""
            if account == "B":
                with pytest.raises(sqlite3.IntegrityError):
                    conn.execute(insert, (allocation_id, newest, account))
            else:
                conn.execute(insert, (allocation_id, newest, account))
        conn.close()

    def test_a_derived_row_holds_a_value_only_while_applied(self, history):
        conn = history.conn()
        (transaction,) = conn.execute("SELECT id FROM ledger_transaction").fetchone()
        conn.execute("DELETE FROM transaction_allocation")
        for state, value in (("applied", None), ("conflict", "shared:"),
                             ("amount_differs", "shared:"), ("unattributed", None)):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO transaction_allocation VALUES (?, ?, ?)",
                             (transaction, state, value))
        conn.execute("INSERT INTO transaction_allocation VALUES (?, 'applied', 'shared:')",
                     (transaction,))
        conn.close()
