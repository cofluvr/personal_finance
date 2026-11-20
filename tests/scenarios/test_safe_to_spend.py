"""Safe to spend and the dashboard, end to end, using synthetic data only (SB1 to SB7, D-072
points 1 and 3 to 7). Inputs are test_safe_to_spend_inputs.py."""

import re

import pytest
from local_ui_client import UiClient, page_text
from test_budget_plans import BudgetLedger
from test_local_ui import cli_output
from test_safe_to_spend_inputs import InputsLedger
from test_loans import paid
from test_supersession import holding

from personal_finance.cli import SAFE_TO_SPEND_TIMEZONE
from personal_finance.db.backups import logical_digest
from personal_finance.reconcile import transfer_effects
from personal_finance.reports import totals

AS_OF = "2026-05-04"
# Every figure line names one of these, so no planning figure goes unlabelled (G1).
LABELS = ("estimated", "reserved", "planned", "actual", "budget pace", "safe to spend",
          "observed")


class SafeLedger(InputsLedger, BudgetLedger):
    def safe(self, *words, as_of=AS_OF):
        code, out, err = self.run("safe-to-spend", "--as-of", as_of, *words)
        assert (code, err) == (0, ""), err
        return out

    def dashboard(self, as_of=AS_OF):
        code, out, err = self.run("dashboard", "--as-of", as_of)
        assert (code, err) == (0, ""), err
        return out

    def figures(self, as_of=AS_OF):
        """(today, this week) in cents, or None when not available."""
        found = re.search(r"today (\S+), this week (\S+)$", self.safe(as_of=as_of).splitlines()[0])
        return None if found is None else tuple(int(value.replace(".", "")) for value in
                                                found.groups())

    def reasons(self, as_of=AS_OF):
        return re.findall(r"^    (\w+): ", self.safe(as_of=as_of), re.MULTILINE)

    def line(self, start, as_of=AS_OF, *words):
        return next(line.strip() for line in self.safe(*words, as_of=as_of).splitlines()
                    if line.strip().startswith(start))

    def budget_plan_ok(self, **options):
        """BudgetLedger's plan, as LoanLedger's set_plan is the payoff plan."""
        code, out, err = BudgetLedger.set_plan(self, **options)
        assert (code, err) == (0, ""), err
        return re.search(r"Budget plan (\S+) recorded", out)[1]

    def ids_of(self):
        conn = self.conn()
        try:
            return dict(conn.execute("SELECT display_name, id FROM account"))
        finally:
            conn.close()

    def transaction_ids(self):
        conn = self.conn()
        try:
            return [row for (row,) in conn.execute("SELECT id FROM ledger_transaction")]
        finally:
            conn.close()

    def set_buffer(self, amount):
        assert self.run("setting", "set", "checking_buffer_cents", amount, "--revision",
                        self.setting_token("checking_buffer_cents"))[0] == 0


@pytest.fixture
def ledger(tmp_path, capsys):
    """The household in Chicago. Checking A liquid, observed at 5,000.00 on 1 May, with a
    100.00 purchase on 2 May declared complete. A biweekly salary paid on Fridays from 2 January,
    so the next paycheck is 8 May and the horizon 4 to 7 May, 4 days. Power, 85.00 fixed, due
    on the 5th, a mortgage of 1,500.00 due on the 5th, and a 1,500.00 May allowance."""
    ledger = SafeLedger(tmp_path, capsys)
    assert ledger.set_setting()[0] == 0
    ledger.salary = ledger.add_ok()
    ledger.observe("A", "2026-05-01", "5000.00")
    ledger.pay("shop.csv", "2026-05-02", amount="-100.00", text="SYNTHETIC SHOP")
    ledger.declare_ok("shop.csv", "complete", start="2026-05-02", end="2026-05-02",
                      basis="posting")
    ledger.liquid_ok("A")
    ledger.power = ledger.ob_add_ok()
    ledger.add_typed_account("Mortgage", "loan")
    ledger.add_terms_ok("Mortgage")
    ledger.budget_plan_ok(from_month="2026-05", allowance="1500.00", as_of=AS_OF)
    return ledger


def cents(text):
    return int(text.replace(".", ""))


def checking(ledger, name, *rows, account="A"):
    """Rows of the synthetic checking layout: (day, amount, status), unclassified."""
    lines = [f"{name[:-4]}{index},{day},{day},SYNTHETIC ROW {index},{amount},{status}"
             for index, (day, amount, status) in enumerate(rows)]
    ledger.load_path(ledger.write(name, "Transaction ID,Transaction Date,Posted Date,"
                                        "Description,Amount,Status\n", lines),
                     account=account, layout="synthetic_checking_v1")


class TestTheFigure:  # SB5, points 5 and 7
    def test_the_lower_of_the_two_named_budget(self, ledger):
        out = ledger.safe()
        # Budget: (1,500.00 − 100.00) over the 28 days from 4 May, and 7 of them. Liquidity:
        # 4,900.00 − 85.00 − 1,500.00 = 3,315.00 over 4 days.
        assert out.splitlines()[0] == ("Safe to spend as of 2026-05-04: today 50.00, this "
                                       "week 350.00")
        assert "Limiting constraint: budget" in out
        assert "Liquidity daily, safe to spend: 828.75, weekly 3315.00" in out
        assert "Budget daily, budget pace: 50.00, weekly 350.00" in out
        assert "Horizon: 2026-05-04 to 2026-05-07, 4 days, until the next paycheck on " \
               "2026-05-08 (Pay)" in out

    def test_a_tie_goes_to_liquidity(self, ledger):
        # 4,900.00 − 1,585.00 − 3,115.00 leaves 200.00 over 4 days: 50.00, the budget's daily.
        ledger.set_buffer("3115.00")
        out = ledger.safe()
        assert ("Limiting constraint: liquidity, largest protected row Minimum checking buffer, "
                "largest item checking buffer, reserved 3115.00") in out
        # This week: the lower of 200.00 over the 4 days and the budget's 350.00.
        assert ledger.figures() == (5000, 20000)

    def test_a_shortfall_shows_the_rows_and_safe_to_spend_0(self, ledger):
        ledger.set_buffer("4000.00")
        out = ledger.safe()
        assert ledger.figures() == (0, 0)
        assert ("Short by 685.00, estimated, before the next paycheck on 2026-05-08: Required "
                "bills and minimum debt payments, Minimum checking buffer. Safe to spend is "
                "0.00") in out
        assert " -" not in out.splitlines()[0]

    def test_no_timezone_refuses(self, tmp_path, capsys):
        bare = SafeLedger(tmp_path, capsys)
        for command in ("safe-to-spend", "dashboard"):
            code, _, err = bare.run(command, "--as-of", AS_OF)
            assert (code, err.strip()) == (2, f"Error: {SAFE_TO_SPEND_TIMEZONE}")

    def test_every_figure_is_labelled(self, ledger):
        ledger.set_buffer("400.00")
        for out in (ledger.safe("--explain"), ledger.dashboard()):
            for line in out.splitlines():
                if re.search(r"\d+\.\d\d", line):
                    assert any(label in line.lower() for label in LABELS), line


class TestHorizon:  # SB1, point 1
    @pytest.mark.parametrize("cadence, anchor, as_of, paycheck, days", [
        ("weekly", "2026-01-02", "2026-01-31", "2026-02-06", 6),
        ("biweekly", "2026-01-02", "2026-04-30", "2026-05-08", 8),
        ("semimonthly:15,31", "2026-01-15", "2026-02-28", "2026-03-15", 15),
        ("semimonthly:15,31", "2026-01-15", "2026-04-29", "2026-04-30", 1),
        # A payday on as_of is not the next one.
        ("biweekly", "2026-01-02", "2026-05-08", "2026-05-22", 14)])
    def test_the_next_paycheck(self, tmp_path, capsys, cadence, anchor, as_of, paycheck, days):
        ledger = SafeLedger(tmp_path, capsys)
        assert ledger.set_setting()[0] == 0
        ledger.add_ok(cadence=cadence, anchor=anchor)
        assert ledger.line("Horizon:", as_of).endswith(
            f"{days} {'day' if days == 1 else 'days'}, until the next paycheck on {paycheck} "
            "(Pay)")

    def test_an_unreceived_paycheck_within_its_tolerance(self, ledger):
        # Paid on 8 May, 3 days' tolerance: expected through 11 May, missed on 12 May.
        assert "paycheck_expected_not_received" in ledger.reasons("2026-05-11")
        assert "paycheck_expected_not_received" not in ledger.reasons("2026-05-12")
        ledger.deposit("pay.csv", "2026-05-08")
        assert "paycheck_expected_not_received" not in ledger.reasons("2026-05-11")

    def test_side_income_never_sets_it_and_no_salary_runs_to_month_end(self, tmp_path, capsys):
        ledger = SafeLedger(tmp_path, capsys)
        assert ledger.set_setting()[0] == 0
        ledger.add_ok(name="Gig", kind="side", match="synthetic gig", cadence="weekly")
        assert ledger.line("Horizon:").endswith(
            "28 days, to the month's end, with no salary pay date to come")
        assert "no_salary_source" in ledger.reasons()


class TestLiquidBalance:  # SB2, point 3
    def test_pending_outflows_in_pending_and_unknown_inflows_out(self, ledger):
        checking(ledger, "more.csv", ("2026-05-03", "-20.00", "PENDING"),
                 ("2026-05-03", "30.00", "PENDING"), ("2026-05-03", "40.00", ""),
                 ("2026-05-03", "-10.00", ""), ("2026-05-05", "-999.00", "POSTED"))
        out = ledger.safe("--explain")
        # 5,000.00 − 100.00 − 20.00 − 10.00. The row after as_of is not counted.
        assert ("Account A: estimated 4870.00 from 2026-05-01's observation 5000.00 and activity "
                "since, actual -130.00 (3)") in out
        assert "Left out, actual: pending or unknown-status inflows 70.00" in out
        assert "Liquid balance, estimated: 4870.00" in out

    @pytest.mark.parametrize("as_of, stale", [("2026-05-08", False), ("2026-05-09", True)])
    def test_stale_past_7_days(self, ledger, as_of, stale):
        assert ("stale_observation" in ledger.reasons(as_of)) is stale

    def test_activity_incomplete_at_its_edges(self, ledger):
        assert "activity_incomplete" not in ledger.reasons()
        ledger.pay("later.csv", "2026-05-04", amount="-1.00", text="SYNTHETIC LATER")
        ledger.declare_ok("later.csv", "complete", start="2026-05-04", end="2026-05-04",
                          basis="posting")
        # 3 May is not covered on the posting basis.
        assert "activity_incomplete" in ledger.reasons()
        ledger.pay("gap.csv", "2026-05-03", amount="-1.00", text="SYNTHETIC GAP")
        ledger.declare_ok("gap.csv", "complete", start="2026-05-03", end="2026-05-03",
                          basis="posting")
        assert "activity_incomplete" not in ledger.reasons()

    def test_an_unvalued_account_is_left_out_and_named(self, ledger):
        ledger.add_typed_account("S", "savings")
        ledger.liquid_ok("S")
        out = ledger.safe("--explain")
        assert "unvalued_liquidity_account: S" in out
        assert "Account S: not valued, no observation, left out" in out
        assert "Liquid balance, estimated: 4900.00" in out
        ledger.observe("S", "2026-05-03", "100.00")
        assert "unvalued_liquidity_account" not in ledger.reasons()


@pytest.fixture
def planned(ledger):
    """The ledger with savings S observed, a tax reserve at 25% of side income of 333.33 paid on
    5 April, a reserve of 1,200.00 due 10 June holding 200.00 on A, an emergency fund of 5,000.00
    holding 1,000.00 on A and restored at 250.00 a month, a goal of 300.00 a month holding 100.00
    on S, and a buffer of 500.00. Every assignment is made now, outside May."""
    ledger.add_typed_account("S", "savings")
    ledger.observe("S", "2026-04-30", "2000.00")
    ledger.deposit("gig.csv", "2026-04-05", amount="333.33", text="SYNTHETIC GIG")
    ledger.add_ok(name="Gig", kind="side", match="synthetic gig", cadence="monthly:5",
                  anchor="2026-04-05", amount="333.33", tax_eligible=True)
    ledger.tax = ledger.add_fund_ok(name="Tax", kind="tax", percent="25",
                                    effective_from="2026-04-01", as_of="2026-04-01")
    ledger.reserve = ledger.add_fund_ok(name="Insurance", kind="reserve", target="1200.00",
                                        due="2026-06-10", as_of=AS_OF)
    ledger.emergency = ledger.add_fund_ok(name="Rainy", kind="emergency", minimum="5000.00",
                                          as_of=AS_OF)
    ledger.goal = ledger.add_fund_ok(name="House", monthly="300.00", as_of=AS_OF)
    for fund, account, amount in ((ledger.reserve, "A", "200.00"),
                                  (ledger.emergency, "A", "1000.00"),
                                  (ledger.goal, "S", "100.00")):
        ledger.assign_ok(fund, account, amount, as_of=AS_OF)
    ledger.restore_ok(ledger.emergency, monthly="250.00", effective_from="2026-05-01")
    ledger.set_buffer("500.00")
    return ledger


def rows(out):
    return {row: cents(value) for row, value in
            re.findall(r"^  \d\. (.+), reserved: (\S+)$", out, re.MULTILINE)}


def items(out):
    return re.findall(r"^    (\w+) .+ \((\S+)\): (\S+), ", out, re.MULTILINE)


class TestProtected:  # SB3, point 4
    def test_each_row_by_hand(self, planned):
        out = planned.safe("--explain")
        assert rows(out) == {
            # ceil(333.33 × 25%).
            "Side-income tax reserve": 8334,
            # Power 85.00 and the mortgage's 1,500.00, both due 5 May.
            "Required bills and minimum debt payments": 158500,
            # 200.00 assigned on A, and ceil((1,200.00 − 200.00) ÷ 2 months) still to come.
            "Annual and irregular expenses": 70000,
            "Minimum checking buffer": 50000,
            # 1,000.00 on A, and May's 250.00 while it is short of 5,000.00.
            "Emergency-fund restoration": 125000,
            # 100.00 on S is not in the liquid balance: only May's 300.00 is protected.
            "Approved savings and extra debt-payment goals": 30000}
        assert "Protected, reserved: 4418.34" in out
        assert "Surplus, estimated: 481.66" in out
        # 481.66 over 4 days is 120.415: a spendable amount rounds down (G8).
        assert "Liquidity daily, safe to spend: 120.41, weekly 481.66" in out

    def test_the_tax_reserve_less_what_other_accounts_hold(self, planned):
        planned.assign_ok(planned.tax, "S", "50.00", as_of=AS_OF)
        assert rows(planned.safe("--explain"))["Side-income tax reserve"] == 3334

    def test_a_bill_or_loan_payment_made_is_not_reserved(self, ledger):
        bills = "Required bills and minimum debt payments"
        ledger.pay("power.csv", "2026-05-03")
        assert rows(ledger.safe("--explain"))[bills] == 150000
        paid(ledger, "loan.csv", "2026-05-03", "-1000.00")
        # 500.00 of the mortgage's 1,500.00 is still to pay on 5 May.
        assert rows(ledger.safe("--explain"))[bills] == 50000

    # Power, due 5 May with 3 days' tolerance, is reserved while expected, through 8 May. The
    # mortgage's 5 May payment, before as_of, is not in the horizon: a loan has no tolerance.
    @pytest.mark.parametrize("as_of, reserved", [("2026-05-07", 8500), ("2026-05-08", 8500),
                                                 ("2026-05-09", 0)])
    def test_a_bill_before_as_of_while_within_its_tolerance(self, ledger, as_of, reserved):
        assert rows(ledger.safe("--explain", as_of=as_of))[
            "Required bills and minimum debt payments"] == reserved

    def test_restoration_stops_once_the_fund_is_whole(self, planned):
        planned.observe("A", "2026-05-02", "7000.00")
        assert planned.unassign(planned.emergency, "A", as_of=AS_OF)[0] == 0
        planned.assign_ok(planned.emergency, "A", "5000.00", as_of=AS_OF)
        assert rows(planned.safe("--explain"))["Emergency-fund restoration"] == 500000

    @pytest.mark.parametrize("loan_linked", [False, True])
    @pytest.mark.parametrize("reserve_linked", [False, True])
    def test_no_entry_in_two_rows(self, planned, loan_linked, reserve_linked):
        # Look-alikes: a mortgage bill like the loan, and a reserve for tires due 6 May with its
        # bill, both in the horizon.
        bill = planned.ob_add_ok(name="Mortgage bill", match="synthetic lender",
                                 cadence="monthly:5", anchor="2026-01-05", amount="1500.00")
        tires = planned.add_fund_ok(name="Tires", kind="reserve", target="400.00",
                                    due="2026-05-06", as_of=AS_OF)
        tires_bill = planned.ob_add_ok(name="Tires bill", match="synthetic tires",
                                       cadence="annual:05-06", anchor="2026-05-06",
                                       amount="400.00")
        if loan_linked:
            planned.covers_ok(bill, "--loan", "Mortgage")
        if reserve_linked:
            planned.covers_ok(tires_bill, "--fund", tires)
        out = planned.safe("--explain")
        entries = [entry for _, entry, _ in items(out)]
        assert len(entries) == len(set(entries))
        found = {entry for _, entry, _ in items(out)}
        ids = planned.ids_of()
        assert (ids["Mortgage"] in found) is not loan_linked
        assert bill in found and tires in found
        assert (tires_bill in found) is not reserve_linked
        warned = "possible_double_reservation" in planned.reasons()
        assert warned is not (loan_linked and reserve_linked)
        # Each link takes its look-alike's amount out once: 1,500.00 and 400.00.
        expected = 441834 + 150000 + 40000 + 40000 - 150000 * loan_linked - 40000 * reserve_linked
        assert cents(re.search(r"Protected, reserved: (\S+)", out)[1]) == expected


class TestAssignedThisMonth:  # SB4, point 4
    def assigned(self, ledger, fund, amount_cents, created_at):
        conn = ledger.conn()
        (account,) = conn.execute("SELECT id FROM account WHERE display_name = 'A'").fetchone()
        assignment = f"m{created_at}"
        conn.execute("INSERT INTO fund_assignment (id, fund_id, account_id, amount_cents, "
                     "created_at) VALUES (?, ?, ?, ?, ?)",
                     (assignment, fund, account, amount_cents, created_at))
        conn.execute("INSERT INTO fund_assignment_event (assignment_id, event) VALUES (?, 'made')",
                     (assignment,))
        conn.close()

    def test_assigning_the_planned_amount_mid_month_changes_nothing(self, planned):
        before = rows(planned.safe("--explain"))
        # 2 May at 10 in the morning in Chicago.
        self.assigned(planned, planned.reserve, 50000, "2026-05-02T15:00:00.000Z")
        after = rows(planned.safe("--explain"))
        assert after == before
        assert "plus outstanding contribution this month 0.00" in planned.safe("--explain")

    def test_an_assignment_before_the_month_in_the_household_s_zone_counts_as_held(self,
                                                                                   planned):
        # 1 May at 04:00 UTC is 30 April at 23:00 in Chicago: held at the month's start, so the
        # plan is ceil((1,200.00 − 700.00) ÷ 2) = 250.00 still to come.
        self.assigned(planned, planned.reserve, 50000, "2026-05-01T04:00:00.000Z")
        assert rows(planned.safe("--explain"))["Annual and irregular expenses"] == 95000

    def test_part_of_the_plan_assigned_leaves_the_rest_outstanding(self, planned):
        self.assigned(planned, planned.reserve, 20000, "2026-05-02T15:00:00.000Z")
        # 400.00 held, and 500.00 − 200.00 of May's plan still to come.
        assert rows(planned.safe("--explain"))["Annual and irregular expenses"] == 70000

    def test_an_assignment_undone_this_month_is_owed_again(self, planned):
        self.assigned(planned, planned.reserve, 30000, "2026-04-20T15:00:00.000Z")
        conn = planned.conn()
        conn.execute("INSERT INTO fund_assignment_event (assignment_id, event, created_at) "
                     "VALUES ('m2026-04-20T15:00:00.000Z', 'undone', '2026-05-02T15:00:00.000Z')")
        conn.close()
        # 500.00 held at the month's start, so ceil(700.00 ÷ 2) = 350.00 planned, plus the
        # 300.00 taken back this month.
        assert rows(planned.safe("--explain"))["Annual and irregular expenses"] == 85000

    def test_more_than_planned_counts_as_assigned(self, planned):
        self.assigned(planned, planned.reserve, 80000, "2026-05-02T15:00:00.000Z")
        assert rows(planned.safe("--explain"))["Annual and irregular expenses"] == 100000


class TestReasons:  # SB5, point 6
    def test_each_is_produced_and_cleared_by_its_action(self, ledger):
        assert ledger.reasons() == []
        # possible_spending, until classified.
        checking(ledger, "odd.csv", ("2026-05-03", "-7.00", "POSTED"))
        assert ledger.reasons() == ["possible_spending"]
        ledger.classify_ok(holding(ledger, "odd.csv"), "purchase")
        assert ledger.reasons() == []
        # card_without_payment_obligation, until an obligation names the card.
        ledger.add_typed_account("Visa", "credit_card")
        ledger.card("visa.csv", "05/01/2026,SYNTHETIC CAFE,6.50,", account="Visa")
        assert "card_without_payment_obligation" in ledger.reasons()
        bill = ledger.ob_add_ok(name="Visa payment", match="synthetic card co",
                                cadence="monthly:20", anchor="2026-01-20", amount="300.00")
        assert "card_without_payment_obligation" not in ledger.reasons()
        assert ledger.ob_undo(bill)[0] == 0
        assert "card_without_payment_obligation" in ledger.reasons()
        ledger.ob_add_ok(name="Card bill", match="synthetic visa", cadence="monthly:20",
                         anchor="2026-01-20", amount="300.00")
        assert "card_without_payment_obligation" not in ledger.reasons()
        # over_assigned, until released.
        fund = ledger.add_fund_ok(name="House", monthly="10.00", as_of=AS_OF)
        ledger.assign_ok(fund, "A", "4000.00", as_of=AS_OF)
        ledger.observe("A", "2026-05-03", "3000.00")
        assert "over_assigned" in ledger.reasons()
        ledger.unassign(fund, "A", as_of=AS_OF)
        assert "over_assigned" not in ledger.reasons()
        # open_review_items, until resolved.
        ledger.card("u.csv", "05/03/2026,SYNTHETIC CAFE,,")
        assert "open_review_items" in ledger.reasons()
        (item,) = ledger.items()
        code, _, err = ledger.run("review", "dismiss", item, "--account", "A", "--revision",
                                  re.search(r"Revision: (r14-[0-9a-f]{16})",
                                            ledger.run("review", "show", item)[1])[1])
        assert code == 0, err
        assert "open_review_items" not in ledger.reasons()

    def test_with_nothing_stated(self, tmp_path, capsys):
        bare = SafeLedger(tmp_path, capsys)
        assert bare.set_setting()[0] == 0
        out = bare.safe()
        assert bare.reasons() == ["no_salary_source", "no_liquidity_accounts", "no_budget_plan"]
        assert out.splitlines()[0] == ("Safe to spend as of 2026-05-04, provisional: not "
                                       "available, neither constraint is evaluated")
        assert "Clears when a salary source is confirmed (income add)" in out

    def test_budget_only_and_liquidity_only(self, ledger):
        ledger.liquid_ok("A", operation="undo")
        assert "no_liquidity_accounts" in ledger.reasons()
        assert ledger.figures() == (5000, 35000)
        assert "Limiting constraint: budget" in ledger.safe()


class TestThirdPaycheck:  # SB6
    def test_the_extra_reaches_liquidity_only_as_money_received(self, tmp_path, capsys):
        ledger = SafeLedger(tmp_path, capsys)
        assert ledger.set_setting()[0] == 0
        # Paid 1, 15 and 29 May: the third is extra.
        ledger.add_ok(anchor="2026-05-01")
        ledger.observe("A", "2026-05-28", "3000.00")
        ledger.liquid_ok("A")
        ledger.budget_plan_ok(from_month="2026-05", allowance="1500.00", as_of="2026-05-30")
        ledger.power = ledger.ob_add_ok(cadence="monthly:10", anchor="2026-01-10")
        before = ledger.safe("--explain", as_of="2026-05-30")
        ledger.deposit("third.csv", "2026-05-29")
        after = ledger.safe("--explain", as_of="2026-05-30")
        assert "paycheck_expected_not_received" in before and "paycheck_expected" not in after
        for start in ("Budget daily", "Protected, reserved", "Horizon:"):
            assert [line for line in before.splitlines() if start in line] == \
                [line for line in after.splitlines() if start in line]
        assert "Liquid balance, estimated: 3000.00" in before
        assert "Liquid balance, estimated: 5500.00" in after


class TestReadOnly:  # SB7, point 7
    def test_it_writes_nothing_and_never_searches_for_candidates(self, planned, monkeypatch):
        conn = planned.conn()
        before = logical_digest(conn)
        conn.close()

        def refused(*arguments, **options):
            raise AssertionError("the transfer candidate search ran")

        monkeypatch.setattr(transfer_effects, "transfer_candidates", refused)
        monkeypatch.setattr(totals, "transfer_candidates", refused)
        planned.safe("--explain")
        planned.dashboard()
        conn = planned.conn()
        assert logical_digest(conn) == before
        conn.close()

    def test_the_page_equals_the_command(self, planned):
        client = UiClient(planned.path)
        client.sign_in()
        try:
            for as_of in (AS_OF, "2026-05-12"):
                assert page_text(client.get(f"/dashboard?as_of={as_of}").body) == cli_output(
                    planned.capsys, "dashboard", "--db", planned.db, "--as-of", as_of)
            assert client.get("/dashboard?as_of=nonsense").status == 400
            assert client.request("POST", "/dashboard").status in (403, 405)
        finally:
            client.close()

    def test_the_dashboard_s_parts(self, planned):
        out = planned.dashboard()
        assert out.startswith("Safe to spend as of 2026-05-04")
        for start in ("Budget pace, 2026-05: remaining capacity 1400.00",
                      "Funds: 4 active", "  Fund Rainy (emergency): underfunded",
                      "Net worth, observed:", "Income, 2026-05: baseline received, actual 0.00",
                      "Review: 0 open review items, 0 unconfirmed transfer kinds",
                      "  Account A: last covered day 2026-05-02, last import "):
            assert start in out, start


def test_the_page_asks_for_the_timezone(tmp_path, capsys):  # SB7, G7
    bare = SafeLedger(tmp_path, capsys)
    client = UiClient(bare.path)
    client.sign_in()
    try:
        page = client.get(f"/dashboard?as_of={AS_OF}")
        assert page.status == 200
        assert "safe to spend needs the household" in page.body.decode()
    finally:
        client.close()
