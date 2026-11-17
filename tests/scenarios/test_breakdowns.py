"""A loan payment's interest and fees stated by a person, end to end, using synthetic data only
(LC1 to LC3, D-071 points 7 and 8). Migration 0031 is test_breakdown_migration.py."""

import re
import tempfile
from pathlib import Path

import pytest
from test_decisions import CAFE, FIRST_HALF
from test_loans import LoanLedger
from test_review_show import LEDGER_TABLES
from test_supersession import holding

from personal_finance.reconcile.breakdowns import (
    ABOVE_THE_PAYMENT,
    ALREADY_BROKEN_DOWN,
    AMOUNT_INVALID,
    BREAKDOWN_ALONE_UNSETTLED,
    BREAKDOWN_SUPERSEDED,
    BREAKDOWN_UNCHANGED,
    NOT_A_LOAN_PAYMENT,
    STALE_BREAKDOWN_REVISION,
)
from personal_finance.reconcile.decisions import LEAVES_BREAKDOWN_UNSETTLED
from personal_finance.reconcile.statements import STALE_TRANSACTION_REVISION
from personal_finance.reports import (
    breakdown_evidence,
    correction_evidence,
    decision_evidence,
    review_evidence,
)

BREAKDOWN_TOKEN = r"lb1-[0-9a-f]{16}"


class BreakdownLedger(LoanLedger):
    def break_down(self, transaction, interest, fees=None, revision=None, account="A",
                   supersedes=None, supersedes_revision=None):
        words = ["review", "breakdown", transaction, "--account", account, "--interest",
                 interest, "--revision", revision or self.transaction_revision(transaction)]
        if fees is not None:
            words += ["--fees", fees]
        if supersedes:
            words += ["--supersedes", supersedes, "--supersedes-revision",
                      supersedes_revision or self.breakdown_revision(supersedes)]
        return self.run(*words)

    def break_down_ok(self, transaction, interest, fees=None, **options):
        code, out, err = self.break_down(transaction, interest, fees, **options)
        assert (code, err) == (0, ""), err
        return re.search(r"Breakdown (\S+) recorded", out)[1]

    def breakdown_revision(self, breakdown):
        out = self.run("review", "breakdown-show", breakdown)[1]
        return re.search(rf"Revision: ({BREAKDOWN_TOKEN})", out)[1]

    def undo_breakdown(self, breakdown, revision=None, account="A"):
        return self.run("review", "breakdown-undo", breakdown, "--account", account,
                        "--revision", revision or self.breakdown_revision(breakdown))

    def everything(self):
        return self.dump(LEDGER_TABLES)

    def refused_with(self, attempt, message):
        before = self.everything()
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert self.everything() == before

    def shown(self):
        return [self.run(*words)[1] for words in (("totals",), ("report", "monthly"),
                                                   ("report", "household"))]


def loan_payment(ledger, name="p1.csv", day="2026-03-05", amount="-1500.00", confirm=True):
    transaction = ledger.pay(name, day, amount=amount, text="SYNTHETIC MORTGAGE CO",
                             financial_type="loan_payment")
    if confirm:
        code, _, err = ledger.one_sided(transaction, "Mortgage")
        assert code == 0, err
    return transaction


@pytest.fixture
def ledger(tmp_path, capsys):
    ledger = BreakdownLedger(tmp_path, capsys)
    ledger.add_typed_account("Mortgage", "loan")
    ledger.payment = loan_payment(ledger)
    return ledger


def figure(out, label):
    return re.search(rf"^  {label}: (\d+) transactions, (\S+)$", out, re.MULTILINE).groups()


class TestBreakdown:  # LC1
    def test_it_is_recorded_and_shown(self, ledger):
        breakdown = ledger.break_down_ok(ledger.payment, "57.25", "15.00")
        shown = ledger.run("review", "transaction", "show", ledger.payment)[1]
        assert "  Principal and interest:\n" in shown
        assert f"Breakdown {breakdown}: interest 57.25, fees 15.00" in shown
        assert f"Breakdown {breakdown}: active, interest 57.25, fees 15.00" in ledger.run(
            "review", "breakdowns")[1]

    def test_refusals(self, ledger):
        refuse = ledger.refused_with
        refuse(lambda: ledger.break_down(ledger.payment, "1500.01"),
               ABOVE_THE_PAYMENT.format(stated="1500.01", amount="1500.00"))
        refuse(lambda: ledger.break_down(ledger.payment, "1000.00", "500.01"),
               ABOVE_THE_PAYMENT.format(stated="1500.01", amount="1500.00"))
        refuse(lambda: ledger.break_down(ledger.payment, "0.00"), AMOUNT_INVALID)
        refuse(lambda: ledger.break_down(ledger.payment, "-5.00"), AMOUNT_INVALID)
        refuse(lambda: ledger.break_down(ledger.payment, "10.00", "-5.00"), AMOUNT_INVALID)
        refuse(lambda: ledger.break_down(ledger.payment, "5", revision="t12-0000000000000000"),
               STALE_TRANSACTION_REVISION)
        unconfirmed = loan_payment(ledger, "p2.csv", "2026-04-05", confirm=False)
        refuse(lambda: ledger.break_down(unconfirmed, "5.00"), NOT_A_LOAN_PAYMENT)
        purchase = ledger.pay("b1.csv", "2026-03-06", amount="-20.00")
        refuse(lambda: ledger.break_down(purchase, "5.00"), NOT_A_LOAN_PAYMENT)
        # A plain transfer confirmed to the loan is not a loan payment either.
        moved = ledger.pay("m1.csv", "2026-03-08", amount="-200.00", text="SYNTHETIC MOVE",
                           financial_type="transfer")
        assert ledger.one_sided(moved, "Mortgage")[0] == 0
        refuse(lambda: ledger.break_down(moved, "5.00"), NOT_A_LOAN_PAYMENT)

    def test_the_whole_payment_may_be_interest(self, ledger):
        ledger.break_down_ok(ledger.payment, "1500.00")

    def test_chains_and_undo(self, ledger):
        first = ledger.break_down_ok(ledger.payment, "57.25")
        ledger.refused_with(lambda: ledger.break_down(ledger.payment, "60.00"),
                            ALREADY_BROKEN_DOWN.format(breakdown=first))
        ledger.refused_with(lambda: ledger.break_down(ledger.payment, "57.25", supersedes=first),
                            BREAKDOWN_UNCHANGED)
        second = ledger.break_down_ok(ledger.payment, "60.00", supersedes=first)
        ledger.refused_with(lambda: ledger.undo_breakdown(first, "lb1-0000000000000000"),
                            BREAKDOWN_SUPERSEDED.format(newer=second))
        ledger.refused_with(lambda: ledger.undo_breakdown(second, "lb1-0000000000000000"),
                            STALE_BREAKDOWN_REVISION)
        code, out, _ = ledger.undo_breakdown(second)
        assert code == 0 and f"Breakdown {first}, which it superseded, applies again" in out

    def test_a_payment_no_longer_confirmed_holds_it_as_not_fitting(self, ledger):
        breakdown = ledger.break_down_ok(ledger.payment, "57.25")
        token = ledger.breakdown_revision(breakdown)
        statement = re.search(r"One-sided transfer ([0-9a-f-]+),", ledger.run(
            "review", "transaction", "show", ledger.payment)[1])[1]
        assert ledger.undo_one_sided(statement)[0] == 0
        listed = ledger.run("review", "breakdowns")[1]
        assert "no breakdown applies, it no longer fits" in listed
        # lb1 covers the outcome, which has changed.
        assert ledger.breakdown_revision(breakdown) != token
        ledger.refused_with(lambda: ledger.break_down(ledger.payment, "60.00"),
                            BREAKDOWN_ALONE_UNSETTLED.format(breakdowns=breakdown))

    def test_a_smaller_corrected_amount_stops_it_fitting(self, ledger):
        ledger.break_down_ok(ledger.payment, "1000.00")
        correction = ledger.correct_ok(ledger.payment, "amount", "-900.00")
        assert "no breakdown applies, it no longer fits" in ledger.run("review", "breakdowns")[1]
        assert ledger.undo_correction(correction)[0] == 0
        assert "Transaction" not in ledger.run("review", "breakdowns")[1].split("Breakdowns:")[1]

    def test_separating_a_breakdown_s_records_refuses(self, ledger):
        ledger.card("a.csv", CAFE, extra=FIRST_HALF)
        ledger.classify_ok(holding(ledger, "a.csv"), "loan_payment")
        ledger.card("b.csv", CAFE, extra=FIRST_HALF)
        (transaction,) = ledger.merges()
        assert ledger.one_sided(transaction, "Mortgage")[0] == 0
        ledger.break_down_ok(transaction, "1.00")
        records = ledger.records(transaction)
        before = ledger.everything()
        code, _, err = ledger.separate(transaction, [records["a.csv"]], [records["b.csv"]])
        assert code == 2 and LEAVES_BREAKDOWN_UNSETTLED in err
        assert ledger.everything() == before


class TestTotals:  # LC2
    def test_interest_and_fees_move_from_transfers_to_spending_exactly(self, ledger):
        before = ledger.run("totals")[1]
        assert re.search(r"Spending: 0 transactions, 0.00", before)
        ledger.break_down_ok(ledger.payment, "57.25", "15.00")
        after = ledger.run("totals")[1]
        assert "  Spending: 1 transactions, 72.25" in after
        assert "    loan interest and fees within loan payments: 1 transactions, 72.25" in after
        assert re.search(r"Interest and financial fees: 1 transactions, 72.25", after)
        assert "  Confirmed transfers: 1 transactions, 1427.75 out and 0.00 in" in after
        assert ("Loan payments a breakdown divides, counted in spending and in confirmed "
                "transfers: 1") in after
        # The groups still add to net account movement: 1,427.75 + 72.25 out.
        assert "-1500.00" in after.split("Income and spending")[0]

    def test_the_loan_warning_is_withdrawn_only_where_a_breakdown_applies(self, ledger):
        loan_payment(ledger, "p2.csv", "2026-04-05")
        out = ledger.run("totals")[1]
        assert "2 loan payments, 3000.00, go to a loan whose interest" in out
        ledger.break_down_ok(ledger.payment, "57.25")
        out = ledger.run("totals")[1]
        assert "1 loan payments, 1500.00, go to a loan whose interest" in out

    def test_monthly_and_household_move_the_same(self, ledger):
        ledger.break_down_ok(ledger.payment, "57.25")
        monthly = ledger.run("report", "monthly")[1]
        assert "    loan interest and fees within loan payments: 1 transactions, 57.25" in monthly
        household = ledger.run("report", "household")[1]
        assert re.search(r"^  loan interest and fees within loan payments, out +57\.25",
                         household, re.MULTILINE)

    def test_members_parts_add_to_the_whole(self, ledger):
        for name in ("Alex", "Bea"):
            assert ledger.run("household", "member", "add", name)[0] == 0
        show = ledger.run("household", "share", "show")[1]
        assert ledger.run("household", "share", "set", "--part", "Alex=33.33", "--part",
                          "Bea=66.67", "--revision",
                          re.search(r"Revision: (h1-\S+)", show)[1])[0] == 0
        show = ledger.run("household", "account", "show", "--account", "A")[1]
        assert ledger.run("household", "account", "set", "--account", "A", "--shared",
                          "--revision", re.search(r"Revision: (a1-\S+)", show)[1])[0] == 0
        ledger.break_down_ok(ledger.payment, "0.05")
        row = re.search(r"^  loan interest and fees within loan payments, out +(.+)$",
                        ledger.run("report", "household")[1], re.MULTILINE)[1].split()
        alex, bea, unattributed, household = (int(cell.replace(".", "")) for cell in row)
        assert alex + bea + unattributed == household == 5
        assert (alex, bea) == (2, 3)


class TestWithout:  # LC3, G6 point 4
    def test_undo_restores_every_report_and_token(self, ledger):
        before = (ledger.shown(), ledger.transaction_revision(ledger.payment))
        breakdown = ledger.break_down_ok(ledger.payment, "57.25")
        assert ledger.shown() != before[0]
        assert ledger.undo_breakdown(breakdown)[0] == 0
        assert (ledger.shown(), ledger.transaction_revision(ledger.payment)) == before

    def test_the_versions_are_pinned(self):
        assert review_evidence.REVISION_VERSION == 14
        assert review_evidence.TRANSACTION_REVISION_VERSION == 12
        assert decision_evidence.DECISION_REVISION_VERSION == 11
        assert correction_evidence.CORRECTION_REVISION_VERSION == 7
        assert breakdown_evidence.BREAKDOWN_REVISION_VERSION == 1

    def test_a_breakdown_moves_the_transaction_and_correction_tokens(self, ledger):
        correction = ledger.correct_ok(ledger.payment, "amount", "-1600.00")
        before = (ledger.transaction_revision(ledger.payment),
                  ledger.correction_revision(correction))
        breakdown = ledger.break_down_ok(ledger.payment, "57.25")
        after = (ledger.transaction_revision(ledger.payment),
                 ledger.correction_revision(correction))
        assert all(new != old for new, old in zip(after, before))
        assert ledger.undo_breakdown(breakdown)[0] == 0
        assert (ledger.transaction_revision(ledger.payment),
                ledger.correction_revision(correction)) == before

    def test_the_breakdown_token_is_the_same_in_any_ledger_holding_the_same(self, capsys):
        tokens = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as folder:
                built = BreakdownLedger(Path(folder), capsys)
                built.add_typed_account("Mortgage", "loan")
                payment = loan_payment(built)
                tokens.append(built.breakdown_revision(built.break_down_ok(payment, "57.25")))
        assert tokens[0] == tokens[1]

    def test_another_loan_s_breakdowns_are_not_its_own(self, ledger):
        ledger.add_typed_account("Auto", "loan")
        ledger.add_terms_ok("Mortgage")
        ledger.add_terms_ok("Auto", rate="3.5", payment="300.00")
        ledger.break_down_ok(ledger.payment, "57.25")
        auto = ledger.loans_shown().split("Loan Auto (loan)")[1].split("Loan Mortgage")[0]
        assert "Interest and fees paid" not in auto

    def test_the_loan_report_reads_interest_paid_and_moves_no_balance(self, ledger):
        ledger.add_terms_ok("Mortgage")
        ledger.observe("Mortgage", "2026-03-01", "100000.00", option="--owed")
        before = ledger.loans_shown()
        ledger.break_down_ok(ledger.payment, "57.25")
        after = ledger.loans_shown()
        assert "Interest and fees paid, actual, as breakdowns state them: 1, 57.25" in after
        assert [line for line in after.splitlines() if "Interest and fees paid" not in line] == (
            before.splitlines())
