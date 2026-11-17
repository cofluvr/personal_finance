"""Fund consumption and the tax reserve's payments and releases, end to end, using synthetic data
only (GB1 to GB4, D-070 points 5 to 7, D-067 G3 to G6). The portions by hand are in
tests/unit/test_fund_consumed.py, and migration 0028 in test_consumption_migration.py."""

import re
import tempfile
from pathlib import Path

import pytest
from test_budget_report import ReportLedger
from test_decisions import CAFE, FIRST_HALF, Ledger
from test_funds import AS_OF, FundLedger
from test_review_show import LEDGER_TABLES
from test_separations import merged_two
from test_supersession import holding

from personal_finance.planning.funds import (
    RELEASE_AFTER_AS_OF,
    RELEASE_BEFORE_START,
    RELEASE_BEYOND_REQUIRED,
    RELEASE_CLOSED_MONTH,
    RELEASE_NOT_FOUND,
    RELEASE_NOT_TAX,
    STALE_FUND_REVISION,
    UNDO_CONSUMED,
)
from personal_finance.reconcile.consumptions import (
    ALREADY_CONSUMED,
    CONSUMPTION_ALONE_UNSETTLED,
    CONSUMPTION_NOT_ACTIVE,
    CONSUMPTION_SUPERSEDED,
    CONSUMPTION_UNCHANGED,
    CONSUMPTION_UNSETTLED,
    CONSUMPTION_WRONG_ACCOUNT,
    FUND_NOT_CONSUMED,
    FUND_UNKNOWN,
    NOT_SPENDING_REFUSAL,
    STALE_CONSUMPTION_REVISION,
)
from personal_finance.reconcile.decisions import LEAVES_CONSUMPTION_UNSETTLED, STALE_ACCOUNT
from personal_finance.reconcile.statements import (
    STALE_TRANSACTION_REVISION,
    TRANSACTION_WRONG_ACCOUNT,
)
from personal_finance.reports import (
    consumption_evidence,
    correction_evidence,
    decision_evidence,
    review_evidence,
)

CONSUMPTION_TOKEN = r"fc1-[0-9a-f]{16}"
TAX_LABEL = "a planning reserve, not a calculated tax liability"


class ConsumptionLedger(FundLedger, ReportLedger):
    def consume(self, transaction, fund, revision=None, account="A", supersedes=None,
                supersedes_revision=None):
        words = ["review", "consume", transaction, "--account", account, "--fund", fund,
                 "--revision", revision or self.transaction_revision(transaction)]
        if supersedes:
            words += ["--supersedes", supersedes, "--supersedes-revision",
                      supersedes_revision or self.consumption_revision(supersedes)]
        return self.run(*words)

    def consume_ok(self, transaction, fund, **options):
        code, out, err = self.consume(transaction, fund, **options)
        assert (code, err) == (0, ""), err
        return re.search(r"Consumption (\S+) recorded", out)[1]

    def consumption_show(self, consumption):
        code, out, err = self.run("review", "consumption", "show", consumption)
        assert code == 0, err
        return out

    def consumption_revision(self, consumption):
        return re.search(rf"Revision: ({CONSUMPTION_TOKEN})",
                         self.consumption_show(consumption))[1]

    def undo_consumption(self, consumption, revision=None, account="A"):
        return self.run("review", "consumption", "undo", consumption, "--account", account,
                        "--revision", revision or self.consumption_revision(consumption))

    def consumption_outcomes(self):
        """Each transaction a consumption reaches as its file names, state and fund name."""
        conn = self.conn()
        names = {}
        for transaction_id, name in conn.execute(
            """SELECT link.transaction_id, document.file_name FROM transaction_source link
               JOIN source_document document ON document.id = link.source_document_id"""
        ):
            names.setdefault(transaction_id, []).append(name)
        funds = dict(conn.execute("SELECT id, name FROM fund"))
        found = sorted(
            (tuple(sorted(names[transaction_id])), state, fund_id and funds[fund_id])
            for transaction_id, state, fund_id in conn.execute(
                "SELECT transaction_id, state, fund_id FROM transaction_fund_consumption"))
        conn.close()
        return found

    def everything(self):
        return self.dump(LEDGER_TABLES)

    def refused_with(self, attempt, message):
        """The attempt fails with exactly this message, and no table changes."""
        before = self.everything()
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert self.everything() == before

    def release(self, fund, amount, on, revision=None, as_of=AS_OF):
        return self.run("fund", "release", "--fund", fund, "--amount", amount, "--on", on,
                        "--as-of", as_of, "--revision",
                        revision or self.fund_token(fund, "Release"))

    def release_ok(self, fund, amount, on, **options):
        code, out, err = self.release(fund, amount, on, **options)
        assert (code, err) == (0, ""), err
        return re.search(r"Release (\S+) recorded", out)[1]

    def undo_release(self, fund, release, revision=None):
        return self.run("fund", "release-undo", release, "--fund", fund, "--revision",
                        revision or self.fund_token(fund, "Release undo"))

    def line(self, out, label):
        return next(line for line in out.splitlines() if line.strip().startswith(label)).strip()


@pytest.fixture
def ledger(tmp_path, capsys):
    """A savings account observed with 5,000.00, a plan for March, and a reserve of 1,200.00 due
    in September holding 600.00 of it."""
    ledger = ConsumptionLedger(tmp_path, capsys)
    ledger.set_plan_ok(allowance="1000.00", members=("Alex=600", "Bea=400"),
                       categories=("Dining=100",))
    ledger.add_typed_account("Savings", "savings")
    ledger.observe("Savings", "2026-03-01", "5000.00")
    ledger.reserve = ledger.add_fund_ok(name="Insurance", kind="reserve", target="1200.00",
                                        due="2026-09-01")
    ledger.assign_ok(ledger.reserve, "Savings", "600.00")
    return ledger


def purchase(ledger, name="r1.csv", day="2026-03-05", amount="-850.00",
             text="SYNTHETIC INSURER"):
    return ledger.pay(name, day, amount=amount, text=text)


class TestConsume:  # GB1
    def test_a_purchase_is_paid_from_a_reserve_and_shown(self, ledger):
        transaction = purchase(ledger)
        consumption = ledger.consume_ok(transaction, ledger.reserve)
        assert ledger.consumption_outcomes() == [(("r1.csv",), "applied", "Insurance")]
        shown = ledger.run("review", "transaction", "show", transaction)[1]
        assert "  Paid from:\n" in shown
        assert f"Consumption {consumption}: fund {ledger.reserve} (Insurance)" in shown
        listed = ledger.run("review", "consumptions")[1]
        assert f"Consumption {consumption}: active, fund Insurance, 1 records" in listed

    def test_a_goal_and_the_tax_reserve_can_pay_too(self, ledger):
        goal = ledger.add_fund_ok(name="Car", kind="goal", target="9000.00", by="2026-12")
        tax = ledger.add_fund_ok(name="Tax", kind="tax", percent="25")
        ledger.consume_ok(purchase(ledger, "g1.csv"), goal)
        ledger.consume_ok(purchase(ledger, "t1.csv", text="SYNTHETIC TREASURY"), tax)
        assert [state for _, state, _ in ledger.consumption_outcomes()] == ["applied", "applied"]

    def test_a_refund_can_be_consumed(self, ledger):
        refund = ledger.pay("f1.csv", "2026-03-06", amount="40.00", text="SYNTHETIC INSURER",
                            financial_type="refund")
        ledger.consume_ok(refund, ledger.reserve)
        assert ledger.consumption_outcomes() == [(("f1.csv",), "applied", "Insurance")]


class TestRefusals:  # GB1
    def test_a_stale_token(self, ledger):
        transaction = purchase(ledger)
        ledger.refused_with(lambda: ledger.consume(transaction, ledger.reserve,
                                                   revision="t12-0000000000000000"),
                            STALE_TRANSACTION_REVISION)

    def test_another_account_s_transaction(self, ledger):
        ledger.add_typed_account("B2", "checking")
        transaction = purchase(ledger)
        ledger.refused_with(lambda: ledger.consume(transaction, ledger.reserve, account="B2"),
                            TRANSACTION_WRONG_ACCOUNT)

    def test_a_transaction_not_in_spending(self, ledger):
        paycheck = ledger.deposit("p1.csv", "2026-03-02")
        ledger.refused_with(lambda: ledger.consume(paycheck, ledger.reserve),
                            NOT_SPENDING_REFUSAL)
        unclassified = ledger.pay("u1.csv", "2026-03-04", financial_type=None)
        ledger.refused_with(lambda: ledger.consume(unclassified, ledger.reserve),
                            NOT_SPENDING_REFUSAL)

    def test_an_unknown_or_undone_fund(self, ledger):
        transaction = purchase(ledger)
        ledger.refused_with(lambda: ledger.consume(transaction, "no-such-fund"), FUND_UNKNOWN)
        goal = ledger.add_fund_ok(name="Car", kind="goal")
        assert ledger.undo_fund(goal)[0] == 0
        ledger.refused_with(lambda: ledger.consume(transaction, goal), FUND_UNKNOWN)

    def test_the_emergency_fund(self, ledger):
        cushion = ledger.add_fund_ok(name="Cushion", kind="emergency", minimum="3000.00")
        transaction = purchase(ledger)
        ledger.refused_with(lambda: ledger.consume(transaction, cushion),
                            FUND_NOT_CONSUMED.format(fund=cushion))

    def test_the_account_is_checked_first(self, ledger):
        from test_household import make_stale
        transaction = purchase(ledger)
        make_stale(ledger)
        ledger.refused_with(lambda: ledger.consume(transaction, "no-such-fund",
                                                   revision="t12-0000000000000000"),
                            STALE_ACCOUNT)

    def test_again_and_the_same_fund_again(self, ledger):
        transaction = purchase(ledger)
        consumption = ledger.consume_ok(transaction, ledger.reserve)
        ledger.refused_with(lambda: ledger.consume(transaction, ledger.reserve),
                            ALREADY_CONSUMED.format(consumption=consumption))
        ledger.refused_with(lambda: ledger.consume(transaction, ledger.reserve,
                                                   supersedes=consumption),
                            CONSUMPTION_UNCHANGED)

    def test_a_fund_paying_for_a_transaction_cannot_be_undone(self, ledger):
        consumption = ledger.consume_ok(purchase(ledger), ledger.reserve)
        assert ledger.unassign(ledger.reserve, "Savings")[0] == 0
        ledger.refused_with(lambda: ledger.undo_fund(ledger.reserve),
                            UNDO_CONSUMED.format(consumptions=consumption))
        assert ledger.undo_consumption(consumption)[0] == 0
        assert ledger.undo_fund(ledger.reserve)[0] == 0


class TestChainsAndAgreement:  # GB1: CB2 and CB3 for consumptions
    def test_supersede_then_undo_steps_back(self, ledger):
        goal = ledger.add_fund_ok(name="Car", kind="goal")
        transaction = purchase(ledger)
        first = ledger.consume_ok(transaction, ledger.reserve)
        second = ledger.consume_ok(transaction, goal, supersedes=first)
        assert ledger.consumption_outcomes() == [(("r1.csv",), "applied", "Car")]
        ledger.refused_with(lambda: ledger.undo_consumption(first, "fc1-0000000000000000"),
                            CONSUMPTION_SUPERSEDED.format(newer=second))
        ledger.refused_with(lambda: ledger.undo_consumption(second, "fc1-0000000000000000"),
                            STALE_CONSUMPTION_REVISION)
        code, out, _ = ledger.undo_consumption(second)
        assert code == 0 and f"Consumption {first}, which it superseded, applies again" in out
        assert ledger.consumption_outcomes() == [(("r1.csv",), "applied", "Insurance")]
        assert ledger.undo_consumption(first)[0] == 0
        assert ledger.consumption_outcomes() == []
        ledger.refused_with(lambda: ledger.undo_consumption(first, "fc1-0000000000000000"),
                            CONSUMPTION_NOT_ACTIVE)

    def test_another_account_s_consumption(self, ledger):
        consumption = ledger.consume_ok(purchase(ledger), ledger.reserve)
        ledger.add_typed_account("B2", "checking")
        ledger.refused_with(lambda: ledger.undo_consumption(consumption, account="B2"),
                            CONSUMPTION_WRONG_ACCOUNT)

    def test_agreeing_consumptions_apply_once(self, ledger):
        transaction, records = merged_two(ledger)
        separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        for name in ("a.csv", "b.csv"):
            ledger.classify_ok(holding(ledger, name), "purchase")
            ledger.consume_ok(holding(ledger, name), ledger.reserve)
        code, out, err = Ledger.undo(ledger, separation)
        assert code == 0 and "paid from no fund" not in out, err
        assert ledger.consumption_outcomes() == [(("a.csv", "b.csv"), "applied", "Insurance")]

    def test_separating_a_consumption_s_records_refuses(self, ledger):
        ledger.card("a.csv", CAFE, extra=FIRST_HALF)
        ledger.classify_ok(holding(ledger, "a.csv"), "purchase")
        ledger.card("b.csv", CAFE, extra=FIRST_HALF)
        (transaction,) = ledger.merges()
        ledger.consume_ok(transaction, ledger.reserve)
        records = ledger.records(transaction)
        before = ledger.everything()
        code, _, err = ledger.separate(transaction, [records["a.csv"]], [records["b.csv"]])
        assert code == 2 and LEAVES_CONSUMPTION_UNSETTLED in err
        assert ledger.everything() == before

    def test_disagreeing_after_an_undone_separation_pays_from_no_fund(self, ledger):
        goal = ledger.add_fund_ok(name="Car", kind="goal")
        transaction, records = merged_two(ledger)
        separation = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
        for name in ("a.csv", "b.csv"):
            ledger.classify_ok(holding(ledger, name), "purchase")
        first = ledger.consume_ok(holding(ledger, "a.csv"), ledger.reserve)
        second = ledger.consume_ok(holding(ledger, "b.csv"), goal)
        # IncomeLedger's undo is an income source's: the decision undo is Ledger's.
        code, out, err = Ledger.undo(ledger, separation)
        assert code == 0, err
        assert "Transactions now paid from no fund, because consumptions disagree" in out
        assert ledger.consumption_outcomes() == [(("a.csv", "b.csv"), "conflict", None)]
        listed = ledger.run("review", "consumptions")[1]
        assert re.search(r"^Transaction \S+: paid from no fund, consumptions disagree", listed,
                         re.MULTILINE)
        ledger.refused_with(
            lambda: ledger.consume(holding(ledger, "a.csv"), goal),
            CONSUMPTION_UNSETTLED.format(consumptions=", ".join(sorted((first, second)))))

    def test_a_type_no_longer_spending_holds_it_as_not_spending(self, ledger):
        transaction = purchase(ledger)
        consumption = ledger.consume_ok(transaction, ledger.reserve)
        ledger.classify_ok(transaction, "transfer", supersedes=ledger.classification_of(
            transaction))
        assert ledger.consumption_outcomes() == [(("r1.csv",), "not_spending", None)]
        ledger.refused_with(lambda: ledger.consume(transaction, ledger.reserve),
                            CONSUMPTION_ALONE_UNSETTLED.format(consumptions=consumption))

    def test_an_automatic_split_changes_its_basis(self, ledger):
        ledger.checking("a.csv", "S-1,2026-03-09,,SYNTHETIC SHOP,-5.00,")
        ledger.checking("b.csv", "S-1,2026-03-09,2026-03-10,SYNTHETIC SHOP,-5.00,POSTED")
        (transaction,) = ledger.merges()
        ledger.classify_ok(transaction, "purchase")
        ledger.consume_ok(transaction, ledger.reserve)
        ledger.checking("c.csv", "S-1,2026-03-09,2026-03-11,SYNTHETIC SHOP,-5.00,POSTED")
        assert ("basis_changed" in {state for _, state, _ in ledger.consumption_outcomes()})


class TestNoDoubleCount:  # GB2
    def figures(self, ledger):
        budget = ledger.report()
        fund = ledger.fund_shown(ledger.reserve)
        return (ledger.run("totals")[1], ledger.run("report", "monthly")[1],
                ledger.figure(budget, "Discretionary spending, actual:"),
                ledger.figure(budget, "Spent against the target, actual:"),
                ledger.line(fund, "Assigned:"), budget, fund)

    def test_a_purchase_counts_once_and_leaves_discretionary_by_its_portion(self, ledger):
        transaction = purchase(ledger)
        before = self.figures(ledger)
        totals, monthly, discretionary, spent, assigned, budget, _ = before
        assert (discretionary, spent, assigned) == ("850.00", "850.00",
                                                    "Assigned: 600.00 (Savings 600.00)")
        consumption = ledger.consume_ok(transaction, ledger.reserve)
        after = self.figures(ledger)
        # totals and report monthly count it once, unchanged.
        assert after[:2] == (totals, monthly)
        # The portion is min(850.00, 600.00 assigned): 600.00 leaves discretionary actual, and
        # the excess 250.00 stays.
        assert after[2:5] == ("250.00", "250.00", "Assigned: 0.00 (Savings 0.00)")
        assert ledger.line(after[5], "Paid from reserves") == (
            "Paid from reserves, actual, apart from the target: 1, 600.00")
        assert "Paid from this fund: 600.00 in 1 transaction" in after[6]
        # The fund's need is unchanged: what it held went to the purchase.
        assert (ledger.line(after[6], "Outstanding:")
                == ledger.line(before[6], "Outstanding:"))
        assert ledger.undo_consumption(consumption)[0] == 0
        assert self.figures(ledger) == before

    def test_a_purchase_within_the_assignment_leaves_discretionary_entirely(self, ledger):
        purchase_id = purchase(ledger, amount="-200.00")
        ledger.consume_ok(purchase_id, ledger.reserve)
        budget = ledger.report()
        assert ledger.figure(budget, "Discretionary spending, actual:") == "0.00"
        assert ledger.line(budget, "Discretionary spending") == (
            "Discretionary spending, actual: 0, 0.00")
        assert "Assigned: 400.00 (Savings 400.00)" in ledger.fund_shown(ledger.reserve)

    def test_its_category_allowance_counts_only_the_excess(self, ledger):
        transaction = purchase(ledger, amount="-650.00", text="SYNTHETIC BISTRO")
        ledger.categorize_ok(transaction, "Dining")
        line = "Category Dining: allowance, planned 100.00, spent, actual"
        assert f"{line} 650.00" in ledger.report()
        ledger.consume_ok(transaction, ledger.reserve)
        assert f"{line} 50.00, budget pace 50.00 left" in ledger.report()

    def test_the_transaction_s_own_account_gives_first(self, ledger):
        ledger.observe("A", "2026-03-01", "1000.00")
        ledger.assign_ok(ledger.reserve, "A", "300.00")
        ledger.consume_ok(purchase(ledger, amount="-400.00"), ledger.reserve)
        assert "Assigned: 500.00 (A 0.00, Savings 500.00)" in ledger.fund_shown(ledger.reserve)

    def test_an_assignment_made_later_changes_no_portion(self, ledger):
        ledger.consume_ok(purchase(ledger), ledger.reserve)
        ledger.observe("A", "2026-03-01", "1000.00")
        ledger.assign_ok(ledger.reserve, "A", "500.00")
        budget = ledger.report()
        assert ledger.figure(budget, "Discretionary spending, actual:") == "250.00"
        assert "Assigned: 500.00 (A 500.00, Savings 0.00)" in ledger.fund_shown(ledger.reserve)

    def test_a_refund_consumed_restores_the_fund_and_reduces_the_portion(self, ledger):
        ledger.consume_ok(purchase(ledger), ledger.reserve)
        refund = ledger.pay("f1.csv", "2026-03-09", amount="100.00", text="SYNTHETIC INSURER",
                            financial_type="refund")
        unconsumed = ledger.report()
        assert ledger.figure(unconsumed, "Discretionary spending, actual:") == "150.00"
        ledger.consume_ok(refund, ledger.reserve)
        budget = ledger.report()
        assert ledger.figure(budget, "Discretionary spending, actual:") == "250.00"
        assert ledger.line(budget, "Paid from reserves") == (
            "Paid from reserves, actual, apart from the target: 2, 500.00")
        assert "Assigned: 100.00 (Savings 100.00)" in ledger.fund_shown(ledger.reserve)

    def test_a_member_s_part_rounds_toward_their_spending(self, ledger):
        ledger.share_and_default()
        ledger.consume_ok(purchase(ledger, amount="-0.03"), ledger.reserve)
        # The fund paid all 0.03: Alex's part of the spending is 0.02 by the share's remainder,
        # and of what was paid, 0.03 × 0.02 ÷ 0.03 = 0.02 exactly.
        alex = ledger.report("--member", "Alex")
        bea = ledger.report("--member", "Bea")
        paid = [ledger.figure(out, "Paid from reserves") for out in (alex, bea)]
        assert sorted(paid) == ["0.01", "0.02"]

    def test_a_recurring_reserve_s_cycle(self, ledger):
        renewal = ledger.add_fund_ok(name="Renewal", kind="reserve", target="500.00",
                                     cadence="annual:03-10", effective_from="2026-03-01")
        ledger.assign_ok(renewal, "Savings", "300.00")
        ledger.consume_ok(purchase(ledger, amount="-200.00"), renewal)
        # On the due day the purchase counts in the cycle ending then.
        due_day = ledger.fund_shown(renewal, "2026-03-10")
        assert "Paid from this fund: 200.00 in 1 transaction" in due_day
        assert "Outstanding: 200.00, due 2026-03-10" in due_day
        # After it, a new cycle starts with its target outstanding and the leftover carried.
        after = ledger.fund_shown(renewal, "2026-03-15")
        assert "Paid from this fund since" not in after
        assert "Assigned: 100.00 (Savings 100.00)" in after
        assert "Outstanding: 400.00, due 2027-03-10" in after


@pytest.fixture
def taxed(ledger):
    """A tax reserve at 25% from February, accruing 166.68 by the end of March."""
    for number, day in enumerate(("2026-01-10", "2026-02-10", "2026-03-10")):
        ledger.deposit(f"g{number}.csv", day, amount="333.33", text="SYNTHETIC GIG")
    ledger.add_ok(name="Gig", kind="side", match="synthetic gig", cadence="monthly:10",
                  anchor="2026-01-10", amount="333.33", tax_eligible=True)
    ledger.tax = ledger.add_fund_ok(name="Tax", kind="tax", percent="25",
                                    effective_from="2026-02-01", as_of="2026-02-01")
    return ledger


def tax_lines(out):
    return [line.strip() for line in out.splitlines()
            if "tax" in line.lower() or "reserve," in line]


class TestTaxReserve:  # GB3
    def test_payments_reduce_required_and_beyond_it_is_shown(self, taxed):
        payment = taxed.pay("t1.csv", "2026-03-12", amount="-100.00", text="SYNTHETIC TREASURY")
        taxed.consume_ok(payment, taxed.tax)
        shown = taxed.fund_shown(taxed.tax, "2026-03-31")
        assert ("accrued 166.68 from 2 received occurrences, paid 100.00, released 0.00"
                in shown)
        assert "Required held: 66.68" in shown
        taxed.consume_ok(taxed.pay("t2.csv", "2026-03-13", amount="-100.00",
                                   text="SYNTHETIC TREASURY"), taxed.tax)
        shown = taxed.fund_shown(taxed.tax, "2026-03-31")
        assert "Required held: 0.00" in shown
        assert f"Paid beyond the reserve, {TAX_LABEL}: 33.32" in shown
        # A payment beyond what it holds pays its whole amount: nothing was assigned to it.
        assert "Paid from this fund" not in shown

    def test_a_release_reduces_required_and_its_undo_restores_it(self, taxed):
        before = taxed.fund_shown(taxed.tax, "2026-03-31")
        evidence = taxed.evidence()
        release = taxed.release_ok(taxed.tax, "66.68", "2026-03-31", as_of="2026-03-31")
        assert taxed.evidence() == evidence  # G1: a planning write changes no ledger table
        shown = taxed.fund_shown(taxed.tax, "2026-03-31")
        assert "paid 0.00, released 66.68" in shown and "Required held: 100.00" in shown
        assert f"Release {release}: 66.68 on 2026-03-31, {TAX_LABEL}" in shown
        # Before its date it does not apply.
        assert "released 0.00" in taxed.fund_shown(taxed.tax, "2026-03-30")
        assert taxed.undo_release(taxed.tax, release)[0] == 0
        assert taxed.fund_shown(taxed.tax, "2026-03-31") == before

    def test_release_refusals(self, taxed):
        at = "2026-03-31"
        token = taxed.fund_token(taxed.tax, "Release")
        refuse = taxed.refused_with
        refuse(lambda: taxed.release(taxed.tax, "166.69", at, as_of=at),
               RELEASE_BEYOND_REQUIRED.format(amount="166.69", required="166.68", as_of=at))
        refuse(lambda: taxed.release(taxed.tax, "1.00", "2026-01-31", token, as_of=at),
               RELEASE_BEFORE_START.format(start="2026-02-01"))
        refuse(lambda: taxed.release(taxed.tax, "1.00", "2026-04-01", token, as_of=at),
               RELEASE_AFTER_AS_OF)
        refuse(lambda: taxed.release(taxed.tax, "1.00", "2026-02-27", token, as_of=at),
               RELEASE_CLOSED_MONTH)
        refuse(lambda: taxed.release(taxed.tax, "1.00", at, "fu1-0000000000000000", as_of=at),
               STALE_FUND_REVISION)
        refuse(lambda: taxed.release(taxed.reserve, "1.00", at, token, as_of=at),
               RELEASE_NOT_TAX)
        refuse(lambda: taxed.undo_release(taxed.tax, "no-such-release", token),
               RELEASE_NOT_FOUND)

    def test_a_release_moves_the_tax_reserve_s_tokens(self, taxed):
        tokens = [taxed.fund_token(taxed.tax, kind) for kind in ("Release", "Terms", "Undo")]
        release = taxed.release_ok(taxed.tax, "10.00", "2026-03-15")
        after = [taxed.fund_token(taxed.tax, kind) for kind in ("Release", "Terms", "Undo")]
        assert all(new != old for new, old in zip(after, tokens))
        assert taxed.undo_release(taxed.tax, release)[0] == 0
        assert [taxed.fund_token(taxed.tax, kind) for kind in ("Release", "Terms", "Undo")] == (
            tokens)

    def test_every_tax_figure_carries_its_label(self, taxed):
        taxed.release_ok(taxed.tax, "0.01", "2026-03-15")
        taxed.consume_ok(taxed.pay("t1.csv", "2026-03-12", amount="-300.00",
                                   text="SYNTHETIC TREASURY"), taxed.tax)
        for out in (taxed.fund_shown(taxed.tax, "2026-03-31"), taxed.funds_shown("2026-03-31")):
            for line in out.splitlines():
                if re.search(r"accrued|Paid beyond|^Release [0-9a-f-]{36}:", line.strip()):
                    assert TAX_LABEL in line, line


def every_token(ledger, item, transaction, decision, correction):
    # IncomeLedger's show is an income source's, so the item is shown here.
    item_revision = re.search(r"Revision: (r14-[0-9a-f]{16})",
                              ledger.run("review", "show", item)[1])[1]
    return (item_revision, ledger.transaction_revision(transaction),
            ledger.decision_revision(decision), ledger.correction_revision(correction))


@pytest.fixture
def decided(ledger):
    """A merged pair separated, the first a purchase with a corrected amount, and an open item
    beside them."""
    transaction, records = merged_two(ledger)
    decision = ledger.separate_ok(transaction, [records["a.csv"]], [records["b.csv"]])
    one = holding(ledger, "a.csv")
    ledger.classify_ok(one, "purchase")
    correction = ledger.correct_ok(one, "amount", "-7.00")
    ledger.card("c.csv", CAFE)
    open_item = ledger.items()[0]
    return open_item, one, decision, correction


class TestTokens:  # GB4
    def test_the_versions_are_pinned(self):
        assert review_evidence.REVISION_VERSION == 14
        assert review_evidence.TRANSACTION_REVISION_VERSION == 12
        assert decision_evidence.DECISION_REVISION_VERSION == 11
        assert correction_evidence.CORRECTION_REVISION_VERSION == 7
        assert consumption_evidence.CONSUMPTION_REVISION_VERSION == 1

    def test_funds_assignments_and_releases_change_no_shared_token(self, ledger, decided):
        before = every_token(ledger, *decided)
        goal = ledger.add_fund_ok(name="Car", kind="goal")
        ledger.assign_ok(goal, "Savings", "100.00")
        assert every_token(ledger, *decided) == before

    def test_a_consumption_reaching_them_changes_each_and_undo_restores_them(self, ledger,
                                                                              decided):
        _, one, _, _ = decided
        before = every_token(ledger, *decided)
        consumption = ledger.consume_ok(one, ledger.reserve)
        after = every_token(ledger, *decided)
        assert all(changed != unchanged for changed, unchanged in zip(after, before))
        assert ledger.undo_consumption(consumption)[0] == 0
        assert every_token(ledger, *decided) == before

    def test_the_consumption_token_is_the_same_in_any_ledger_holding_the_same(self, capsys):
        tokens = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as folder:
                built = ConsumptionLedger(Path(folder), capsys)
                built.card("a.csv", "01/10/2026,SYNTHETIC CAFE,6.50,")
                transaction = holding(built, "a.csv")
                built.classify_ok(transaction, "purchase")
                tax = built.add_fund_ok(name="Tax", kind="tax", percent="25")
                tokens.append(built.consumption_revision(built.consume_ok(transaction, tax)))
        # The fund's ID is random, so two ledgers differ only where it is named.
        assert tokens[0] != tokens[1]
        assert all(re.fullmatch(CONSUMPTION_TOKEN, token) for token in tokens)

    def test_the_token_covers_the_fund_and_the_outcome(self, ledger):
        transaction = purchase(ledger)
        consumption = ledger.consume_ok(transaction, ledger.reserve)
        token = ledger.consumption_revision(consumption)
        ledger.classify_ok(transaction, "transfer",
                           supersedes=ledger.classification_of(transaction))
        assert ledger.consumption_revision(consumption) != token

    def test_names_are_escaped(self, ledger):
        goal = ledger.add_fund_ok(name="Car\x1b[2J", kind="goal")
        transaction = purchase(ledger)
        consumption = ledger.consume_ok(transaction, goal)
        for out in (ledger.consumption_show(consumption), ledger.run("review", "consumptions")[1],
                    ledger.run("review", "transaction", "show", transaction)[1]):
            assert "\x1b" not in out

