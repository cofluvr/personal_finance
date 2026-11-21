"""Loan terms, actual payments against the schedule, projections and payoff orders, end to end,
using synthetic data only (LB1, LB3 and the commands of LB4 and LB5, D-071 points 4 to 6). The
math by hand is tests/unit/test_loan_math.py, and migration 0030 test_loan_migration.py."""

import re

import pytest
from test_decisions import LOAN_TABLES
from test_net_worth import NetWorthLedger

from personal_finance.planning.loans import (
    DUE_DAY_INVALID,
    EXTRA_FUND_INVALID,
    NO_TERMS,
    ORDER_INVALID,
    PAYMENT_INVALID,
    PAYMENT_ON_CARD,
    PAYMENT_REQUIRED,
    PERIOD_TAKEN,
    PROJECTION_LABEL,
    RATE_INVALID,
    STALE_LOAN_REVISION,
    STALE_PLAN_REVISION,
    TERMS_ACCOUNT,
    TERMS_EXIST,
)

LOAN_TOKEN = r"lt1-[0-9a-f]{16}"
AS_OF = "2026-05-01"


class LoanLedger(NetWorthLedger):
    def terms_shown(self, account):
        code, out, err = self.run("loan", "terms", "show", "--account", account)
        assert (code, err) == (0, ""), err
        return out

    def loan_token(self, account, kind):
        return re.search(rf"^{kind} revision: ({LOAN_TOKEN})", self.terms_shown(account),
                         re.MULTILINE)[1]

    def add_terms(self, account, rate="6.875", payment="1500.00", due_day="5",
                  effective_from="2026-01-01", revision=None, extra=()):
        words = ["loan", "terms", "add", "--account", account, "--rate", rate, "--due-day",
                 due_day, "--effective-from", effective_from, *extra]
        if payment is not None:
            words += ["--payment", payment]
        return self.run(*words, "--revision", revision or self.loan_token(account, "Add"))

    def add_terms_ok(self, account, **options):
        code, _, err = self.add_terms(account, **options)
        assert (code, err) == (0, ""), err

    def period(self, kind, account, value, effective_from, revision=None):
        option = "--rate" if kind == "rate" else "--amount"
        return self.run("loan", kind, "--account", account, option, value, "--effective-from",
                        effective_from, "--revision",
                        revision or self.loan_token(account, kind.capitalize()))

    def loans_shown(self, as_of=AS_OF):
        code, out, err = self.run("report", "loans", "--as-of", as_of)
        assert (code, err) == (0, ""), err
        return out

    def plan_token(self):
        return re.search(rf"Plan revision: ({LOAN_TOKEN})", self.loans_shown())[1]

    def set_plan(self, *words, revision=None):
        return self.run("loan", "plan", "set", *words, "--revision",
                        revision or self.plan_token())

    def loan_tables(self):
        return self.dump(LOAN_TABLES)

    def refused(self, attempt, message):
        before = (self.loan_tables(), self.evidence())
        code, _, err = attempt()
        assert (code, err.strip()) == (2, f"Error: {message}"), err
        assert (self.loan_tables(), self.evidence()) == before


@pytest.fixture
def ledger(tmp_path, capsys):
    ledger = LoanLedger(tmp_path, capsys)
    ledger.add_typed_account("Mortgage", "loan")
    ledger.add_typed_account("Card", "credit_card")
    ledger.observe("Mortgage", "2026-01-20", "10000.00", option="--owed")
    return ledger


class TestTerms:  # LB1
    def test_terms_are_recorded_and_shown(self, ledger):
        ledger.add_terms_ok("Mortgage", extra=("--remaining-months", "240"))
        out = ledger.terms_shown("Mortgage")
        assert "Due day: 5. Remaining months: 240, as the lender states" in out
        assert "Rate from 2026-01-01: 6.875%" in out
        assert "Payment from 2026-01-01, scheduled: 1500.00" in out

    def test_a_card_takes_a_rate_only(self, ledger):
        ledger.refused(lambda: ledger.add_terms("Card"), PAYMENT_ON_CARD)
        ledger.add_terms_ok("Card", rate="24.99", payment=None)
        assert "No scheduled payment" in ledger.terms_shown("Card")
        ledger.refused(lambda: ledger.period("payment", "Card", "50.00", "2026-02-01",
                                             revision="lt1-0000000000000000"), PAYMENT_ON_CARD)

    @pytest.mark.parametrize("options, message", [
        ({"rate": "100.000001"}, RATE_INVALID), ({"rate": "-1"}, RATE_INVALID),
        ({"rate": "6.8755555"}, RATE_INVALID), ({"payment": "0.00"}, PAYMENT_INVALID),
        ({"payment": None}, PAYMENT_REQUIRED), ({"due_day": "29"}, DUE_DAY_INVALID),
        ({"due_day": "0"}, DUE_DAY_INVALID)])
    def test_what_was_typed(self, ledger, options, message):
        token = ledger.loan_token("Mortgage", "Add")
        ledger.refused(lambda: ledger.add_terms("Mortgage", revision=token, **options), message)

    def test_another_kind_of_account_and_terms_twice(self, ledger):
        ledger.refused(lambda: ledger.add_terms("A", revision="lt1-0000000000000000"),
                       TERMS_ACCOUNT.format(account="A"))
        ledger.add_terms_ok("Mortgage")
        ledger.refused(lambda: ledger.add_terms("Mortgage", revision="lt1-0000000000000000"),
                       TERMS_EXIST.format(account="Mortgage"))
        ledger.refused(lambda: ledger.period("rate", "Card", "5", "2026-02-01",
                                             revision="lt1-0000000000000000"),
                       NO_TERMS.format(account="Card"))

    def test_periods_and_a_stale_token_for_each_input(self, ledger):
        ledger.add_terms_ok("Mortgage")
        tokens = {kind: ledger.loan_token("Mortgage", kind) for kind in ("Rate", "Payment",
                                                                          "Undo")}
        assert ledger.period("payment", "Mortgage", "1600.00", "2027-01-05")[0] == 0
        for kind in ("Rate", "Payment", "Undo"):
            assert ledger.loan_token("Mortgage", kind) != tokens[kind]
        ledger.refused(lambda: ledger.period("rate", "Mortgage", "7", "2027-01-01",
                                             revision=tokens["Rate"]), STALE_LOAN_REVISION)
        ledger.refused(lambda: ledger.period("payment", "Mortgage", "1600.00", "2027-01-05"),
                       PERIOD_TAKEN.format(kind="payment", day="2027-01-05"))
        payment_token = ledger.loan_token("Mortgage", "Payment")
        assert ledger.period("rate", "Mortgage", "7.25", "2026-07-01")[0] == 0
        assert "Rate from 2026-07-01: 7.25%" in ledger.terms_shown("Mortgage")
        ledger.refused(lambda: ledger.period("payment", "Mortgage", "1700.00", "2027-06-05",
                                             revision=payment_token), STALE_LOAN_REVISION)
        code, _, err = ledger.run("loan", "terms", "undo", "--account", "Mortgage",
                                  "--revision", ledger.loan_token("Mortgage", "Undo"))
        assert (code, err) == (0, "")
        assert "No loan terms." in ledger.terms_shown("Mortgage")

    def test_terms_change_no_ledger_table_and_no_shared_token(self, ledger):
        before = (ledger.evidence(), ledger.run("totals")[1])
        ledger.add_terms_ok("Mortgage")
        assert (ledger.evidence(), ledger.run("totals")[1]) == before


def paid(ledger, name, day, amount, financial_type="loan_payment", confirm=True):
    transaction = ledger.pay(name, day, amount=amount, text="SYNTHETIC MORTGAGE CO",
                             financial_type=financial_type)
    if confirm:
        code, _, err = ledger.one_sided(transaction, "Mortgage")
        assert code == 0, err
    return transaction


class TestAgainstSchedule:  # LB3
    def test_each_state_from_confirmed_transfers_only(self, ledger):
        ledger.add_terms_ok("Mortgage")
        paid(ledger, "p1.csv", "2026-01-03", "-1500.00")
        paid(ledger, "p2.csv", "2026-02-04", "-1000.00")
        paid(ledger, "p4.csv", "2026-04-02", "-2000.00")
        paid(ledger, "u1.csv", "2026-03-04", "-1500.00", confirm=False)
        out = ledger.loans_shown()
        periods = re.findall(r"^  Due (\S+): due (\S+), scheduled, paid (\S+), actual, (\S+?)"
                             r"(?:, extra (\S+))?$", out, re.MULTILINE)
        assert periods == [("2026-01-05", "1500.00", "1500.00", "on_schedule", ""),
                           ("2026-02-05", "1500.00", "1000.00", "short", ""),
                           ("2026-03-05", "1500.00", "0.00", "missed", ""),
                           ("2026-04-05", "1500.00", "2000.00", "extra", "500.00"),
                           ("2026-05-05", "1500.00", "0.00", "upcoming", "")]
        assert ("Loan payments not confirmed to any loan, not counted until confirmed: 1, "
                "1500.00") in out

    def test_money_in_on_the_loan_unconfirmed_is_listed_apart(self, ledger):
        ledger.add_terms_ok("Mortgage")
        ledger.deposit("m1.csv", "2026-02-05", amount="1500.00", text="SYNTHETIC PAYMENT",
                       financial_type=None, account="Mortgage")
        out = ledger.loans_shown()
        assert "Money in not confirmed as a payment, not counted until confirmed: 1, 1500.00" in out
        assert "Due 2026-02-05: due 1500.00, scheduled, paid 0.00, actual, missed" in out


class TestProjectAndPayoff:  # LB4 and LB5 as the commands print them
    def test_a_projection_prints_every_assumption_and_label(self, ledger):
        ledger.add_terms_ok("Mortgage")
        code, out, err = ledger.run("loan", "project", "--account", "Mortgage", "--months", "3",
                                    "--as-of", AS_OF)
        assert (code, err) == (0, "")
        for assumption in ("Start:", "Interest each month", "Payment:", "Not modelled:",
                           "Negative amortization:", "Horizon: at most 600 months"):
            assert assumption in out
        months = [line for line in out.splitlines() if line.startswith("  Due ")]
        assert len(months) == 3
        assert all(PROJECTION_LABEL in line for line in months)
        assert "Not paid off within 3 months" in out

    def test_no_observation_means_no_projection(self, ledger):
        ledger.add_terms_ok("Card", rate="24.99", payment=None)
        code, out, _ = ledger.run("loan", "project", "--account", "Card", "--as-of", AS_OF)
        assert code == 0 and "No balance observation on or before 2026-05-01: no projection" in out

    def test_payoff_orders_side_by_side_with_the_plan_s_extra(self, ledger):
        ledger.add_typed_account("Auto", "loan")
        ledger.observe("Auto", "2026-04-20", "3000.00", option="--owed")
        ledger.add_terms_ok("Mortgage")
        ledger.add_terms_ok("Auto", rate="3.5", payment="300.00", due_day="10")
        assert ledger.set_plan("--order", "custom:Mortgage,Auto", "--extra", "250.00")[0] == 0
        code, out, err = ledger.run("loan", "payoff", "--as-of", AS_OF)
        assert (code, err) == (0, "")
        assert "plus extra 250.00, the payoff plan's" in out
        orders = re.findall(r"^Order (\S+): (.+)$", out, re.MULTILINE)
        assert orders == [("avalanche", "Mortgage, Auto"), ("snowball", "Auto, Mortgage"),
                          ("custom", "Mortgage, Auto")]
        assert all(PROJECTION_LABEL in line for line in out.splitlines()
                   if line.startswith("  Loan ") and "paid off" in line)

    def test_the_debt_goal_s_planned_contribution_is_the_extra(self, ledger):
        ledger.add_terms_ok("Mortgage")
        goal = ledger.add_fund_ok(name="Debt", kind="goal", monthly="400.00", as_of=AS_OF)
        assert ledger.set_plan("--order", "avalanche", "--extra-from-fund", goal)[0] == 0
        out = ledger.run("loan", "payoff", "--as-of", AS_OF)[1]
        assert "plus extra 400.00, goal Debt's planned contribution" in out

    def test_plan_refusals(self, ledger):
        ledger.add_terms_ok("Mortgage")
        token = ledger.plan_token()
        ledger.refused(lambda: ledger.set_plan("--order", "largest", revision=token),
                       ORDER_INVALID)
        ledger.refused(lambda: ledger.set_plan("--order", "custom:Mortgage,Mortgage",
                                               revision=token), ORDER_INVALID)
        ledger.refused(lambda: ledger.set_plan("--order", "avalanche", "--extra-from-fund",
                                               "nobody", revision=token), EXTRA_FUND_INVALID)
        assert ledger.set_plan("--order", "snowball")[0] == 0
        ledger.refused(lambda: ledger.set_plan("--order", "avalanche", revision=token),
                       STALE_PLAN_REVISION)
        # The token covers the order itself: one shown for snowball never sets over avalanche.
        snowball = ledger.plan_token()
        assert ledger.set_plan("--order", "avalanche", revision=snowball)[0] == 0
        ledger.refused(lambda: ledger.set_plan("--order", "snowball", revision=snowball),
                       STALE_PLAN_REVISION)
