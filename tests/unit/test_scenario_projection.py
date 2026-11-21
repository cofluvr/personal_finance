"""The pure monthly projection (XB1 to XB3, D-074 points 3 and 4), on plans built by hand. Every
expected figure below is worked out by hand, to the cent, in the comments beside it."""

from dataclasses import replace
from datetime import date

import pytest

from personal_finance.planning import projection
from personal_finance.planning.funds import FundTerms
from personal_finance.planning.loans import LoanTerms, project as loan_project
from personal_finance.planning.projection import (
    Plan,
    ProjectedFund,
    ProjectedLoan,
    Stream,
    StreamTerms,
    level_payment_cents,
    project,
)
from personal_finance.planning.schedules import Cadence
from personal_finance.planning.scenarios import ScenarioInput

AS_OF = date(2026, 3, 1)
SALARY = Stream("salary", "Pay", (StreamTerms("2026-01-15", Cadence("monthly", 15), "2026-01-15",
                                              500_000),), False, "monthly:15")
RENT = Stream("rent", "Rent", (StreamTerms("2026-01-05", Cadence("monthly", 5), "2026-01-05",
                                           120_000),), False, "monthly:5")
PLAN = Plan("2026-03-01", 10_000_000, 0, 100_000, 5_000_000, salary=(SALARY,),
            obligations=(RENT,), budget=(("2026-01", 150_000),))


def scenario_input(kind, amount_cents, from_date, input_id="in", **fields):
    defaults = {"to_date": None, "cadence": "once", "anchor": None, "replaces_kind": None,
                "replaces_id": None, "uncertain": False, "gross": False,
                "take_home_basis_points": None}
    return ScenarioInput(input_id, "sc", kind, amount_cents, from_date,
                         **{**defaults, **fields})


HOME = scenario_input("home_purchase", 30_000_000, "2026-06-10", down_payment_cents=6_000_000,
                      closing_costs_cents=600_000, ownership_costs_cents=40_000,
                      loan_rate_millionths=6_000_000, loan_months=360)


class TestByHand:  # XB3
    def test_the_level_payment(self):
        # 240,000.00 at 6% over 360 months: 24,000,000 × 0.005 × 1.005^360 ÷ (1.005^360 − 1)
        # = 143,892.126... cents, rounded up to 1,438.93.
        assert level_payment_cents(24_000_000, 6_000_000, 360) == 143_893
        # At no interest, the principal over the months, rounded up.
        assert level_payment_cents(100_000, 0, 3) == 33_334

    def test_twelve_months_with_a_home_purchase(self):
        months = project(PLAN, (HOME,), AS_OF, 12).months
        assert [month.month for month in months] == [
            "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09",
            "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]
        # March to May: 5,000.00 pay on the 15th, less 1,200.00 rent on the 5th and the
        # 1,500.00 target: 2,300.00 a month. June also pays the down payment and closing costs,
        # 66,000.00. From July: 2,300.00 less the 1,438.93 payment and 400.00 ownership costs on
        # the 10th, 461.07.
        assert [month.cash_flow_cents for month in months] == [
            230_000, 230_000, 230_000, -6_370_000, *[46_107] * 8]
        # From 100,000.00: 102,300.00, 104,600.00, 106,900.00, 43,200.00, then 461.07 more a
        # month.
        assert [month.liquidity_cents for month in months] == [
            10_230_000, 10_460_000, 10_690_000, 4_320_000, 4_366_107, 4_412_214, 4_458_321,
            4_504_428, 4_550_535, 4_596_642, 4_642_749, 4_688_856]
        # The loan from 240,000.00, interest balance ÷ 200 half-even: 1,200.00, then
        # 1,198.80535 to 1,198.81, 1,197.60475 to 1,197.60, 1,196.3981 to 1,196.40, 1,195.18545
        # to 1,195.19, 1,193.96675 to 1,193.97, 1,192.74195 to 1,192.74, 1,191.511 to 1,191.51,
        # each taken from the 1,438.93 payment.
        assert [month.debt_cents for month in months] == [
            0, 0, 0, 24_000_000, 23_976_107, 23_952_095, 23_927_962, 23_903_709, 23_879_335,
            23_854_839, 23_830_220, 23_805_478]
        assert [month.loan_payments_cents for month in months] == [0] * 4 + [143_893] * 8
        assert [month.obligations_cents for month in months] == [
            120_000, 120_000, 120_000, 6_720_000, *[160_000] * 8]
        # Net worth from 50,000.00: the change in cash less the change in debt, the home apart.
        assert [month.net_worth_cents for month in months][:5] == [
            5_230_000, 5_460_000, 5_690_000, 5_000_000 + 4_320_000 - 10_000_000 - 24_000_000,
            5_000_000 + 4_366_107 - 10_000_000 - 23_976_107]
        assert [month.scenario_assets_cents for month in months] == [0] * 3 + [30_000_000] * 9

    def test_the_allowances(self):
        months = project(PLAN, (HOME,), AS_OF, 12).months
        # March counts as_of, 31 days: 1,500.00 ÷ 31 = 48.38 and × 7 ÷ 31 = 338.70. April has
        # 30: 50.00 and 350.00. Liquidity is far above both.
        assert (months[0].daily_allowance_cents, months[0].weekly_allowance_cents) == (4_838,
                                                                                      33_870)
        assert (months[1].daily_allowance_cents, months[1].weekly_allowance_cents) == (5_000,
                                                                                      35_000)

    def test_the_baseline_by_hand(self):
        months = project(PLAN, (), AS_OF, 12).months
        assert [month.cash_flow_cents for month in months] == [230_000] * 12
        assert months[-1].liquidity_cents == 10_000_000 + 12 * 230_000
        assert all(month.debt_cents == 0 and month.scenario_assets_cents == 0
                   for month in months)

    def test_as_of_s_month_counts_only_what_falls_after_it(self):
        on_payday = replace(PLAN, budget=(("2026-01", 150_000),), start_month_spent_cents=40_000)
        first = project(on_payday, (), date(2026, 3, 15), 1).months[0]
        # Pay on the 15th and rent on the 5th are in the balance already; 1,100.00 of the target
        # is left.
        assert (first.income_cents, first.obligations_cents, first.discretionary_cents) == (
            0, 0, 110_000)


class TestPure:  # XB1, point 3
    def test_no_inputs_is_the_baseline_exactly(self):
        assert project(PLAN, (), AS_OF, 24) == project(PLAN, (), AS_OF, 24)

    def test_the_horizon_is_1_to_120_months(self):
        assert len(project(PLAN, (), AS_OF, 120).months) == 120
        for months in (0, 121):
            with pytest.raises(ValueError):
                project(PLAN, (), AS_OF, months)

    def test_replacing_a_salary_counts_only_the_new_amount_in_range(self):
        raise_ = scenario_input("income", 600_000, "2026-05-01", to_date="2026-08-31",
                                cadence="monthly:15", replaces_kind="income_source",
                                replaces_id="salary")
        income = [month.income_cents for month in project(PLAN, (raise_,), AS_OF, 8).months]
        assert income == [500_000, 500_000, 600_000, 600_000, 600_000, 600_000, 500_000,
                          500_000]

    def test_a_look_alike_addition_counts_twice_and_is_flagged(self):
        again = scenario_input("expense", 120_500, "2026-04-01", cadence="monthly:5")
        result = project(PLAN, (again,), AS_OF, 3)
        assert [month.obligations_cents for month in result.months] == [120_000, 240_500,
                                                                         240_500]
        assert result.look_alikes == {"in": ("rent",)}
        # Beyond 1% it is not a look-alike.
        apart = replace(again, amount_cents=121_201)
        assert project(PLAN, (apart,), AS_OF, 3).look_alikes == {}
        # Nor on another cadence, or once the stream has not started by its end.
        assert project(PLAN, (replace(again, cadence="monthly:6"),), AS_OF, 3).look_alikes == {}
        early = replace(again, from_date="2025-01-01", to_date="2025-12-31")
        assert project(PLAN, (early,), AS_OF, 3).look_alikes == {}

    def test_a_replacement_is_never_a_look_alike(self):
        replacing = scenario_input("expense", 120_000, "2026-04-01", cadence="monthly:5",
                                   replaces_kind="recurring_obligation", replaces_id="rent")
        assert project(PLAN, (replacing,), AS_OF, 3).look_alikes == {}

    def test_gross_income_is_received_at_its_take_home_share(self):
        gross = scenario_input("income", 100_001, "2026-04-01", cadence="monthly:20",
                               gross=True, take_home_basis_points=7_250)
        # 1,000.01 × 72.5% = 725.00725, rounded down once.
        assert project(PLAN, (gross,), AS_OF, 2).months[1].income_cents == 500_000 + 72_500


TERMS = LoanTerms("terms", "loan", "Car", "loan", 5, None, (("2026-01-01", 4_800_000),),
                  (("2026-01-01", 30_000),))
CAR = ProjectedLoan(TERMS, 1_000_000, "2026-02-20")


class TestLoans:  # point 3: M15's amortization
    def test_balances_follow_m15_s_projection(self):
        plan = replace(PLAN, loans=(CAR,))
        rows = loan_project(TERMS, 1_000_000, "2026-02-20", months=24).months
        months = project(plan, (), AS_OF, 24).months
        # One due date a month from 5 March, so each month ends at M15's balance.
        assert [month.debt_cents for month in months] == [
            row.balance_cents for row in rows][:24]
        assert months[0].loan_payments_cents == 30_000

    def test_a_payment_an_obligation_covers_is_not_counted_twice(self):
        plan = replace(PLAN, loans=(replace(CAR, payment_is_cash=False),))
        first = project(plan, (), AS_OF, 1).months[0]
        assert first.loan_payments_cents == 0 and first.debt_cents < 1_000_000

    def test_a_payoff_pays_down_its_loan_on_its_date(self):
        plan = replace(PLAN, loans=(CAR,))
        payoff = scenario_input("loan_payoff", 2_000_000, "2026-04-20", loan_terms_id="terms")
        months = project(plan, (payoff,), AS_OF, 3).months
        # It pays no more than is owed, and the loan is paid off on that date.
        assert months[1].debt_cents == 0
        baseline = project(plan, (), AS_OF, 3).months
        assert months[1].obligations_cents - baseline[1].obligations_cents == \
            baseline[0].debt_cents - 30_000 + projection.monthly_interest(
                baseline[0].debt_cents, 4_800_000)

    def test_a_payoff_of_a_loan_not_projected_is_named(self):
        payoff = scenario_input("loan_payoff", 100, "2026-04-20", loan_terms_id="elsewhere")
        result = project(PLAN, (payoff,), AS_OF, 2)
        assert result.missing == ("loan payoff in: its loan has no balance observed, so it is "
                                  "left out",)
        assert result.months == project(PLAN, (), AS_OF, 2).months

    def test_borrowing_brings_its_proceeds_and_a_level_payment(self):
        borrow = scenario_input("borrowing", 1_200_000, "2026-04-03", loan_rate_millionths=0,
                                loan_months=12)
        months = project(PLAN, (borrow,), AS_OF, 3).months
        assert months[1].income_cents == 500_000 + 1_200_000
        assert months[2].loan_payments_cents == 100_000
        assert months[2].debt_cents == 1_100_000


GOAL = ProjectedFund("goal", "Car", "goal", (FundTerms("2026-01-01", "target_by",
                                                       amount_cents=120_000,
                                                       by_month="2026-06"),), 0)


class TestFunds:  # point 3: required saving, completion and unmet goals
    def test_a_target_goal_completes_in_its_last_month(self):
        result = project(replace(PLAN, funds=(GOAL,)), (), AS_OF, 6)
        (goal,) = result.goals
        # 1,200.00 over March to June: 300.00 a month.
        assert goal.required_monthly_cents == 30_000
        assert goal.completion_month == "2026-06" and not goal.unmet
        assert [month.funds_cents for month in result.months] == [30_000] * 4 + [0, 0]

    def test_without_liquidity_a_goal_goes_unmet(self):
        poor = replace(PLAN, liquid_estimate_cents=0, funds=(GOAL,),
                       salary=(replace(SALARY, terms=(replace(SALARY.terms[0],
                                                              amount_cents=270_000),)),))
        result = project(poor, (), AS_OF, 6)
        # 2,700.00 − 1,200.00 − 1,500.00 leaves nothing above the protected 1,000.00.
        assert result.goals[0].unmet and result.goals[0].completion_month is None
        assert result.unmet_goals == ("Car",)
        assert result.shortfall_months == tuple(month.month for month in result.months)

    def test_a_reserve_pays_its_target_on_its_due_date(self):
        reserve = ProjectedFund("reserve", "Insurance", "reserve", (FundTerms(
            "2026-01-01", "due", amount_cents=60_000, due_date="2026-04-10"),), 0)
        result = project(replace(PLAN, funds=(reserve,)), (), AS_OF, 3)
        assert [month.funds_cents for month in result.months] == [30_000, 30_000, 0]
        assert result.goals[0].held_cents == 0 and not result.goals[0].unmet

    def test_an_annual_expense_replacing_a_reserve_pauses_it_over_its_range(self):
        reserve = ProjectedFund("reserve", "Insurance", "reserve", (FundTerms(
            "2026-01-01", "recurring", amount_cents=120_000, cadence=Cadence("annual", 10),
            anchor="2026-12-10"),), 0)
        replacing = scenario_input("annual_expense", 150_000, "2026-03-01",
                                   to_date="2026-12-31", cadence="annual:12-10",
                                   replaces_kind="fund", replaces_id="reserve")
        months = project(replace(PLAN, funds=(reserve,)), (replacing,), AS_OF, 10).months
        assert all(month.funds_cents == 0 for month in months)
        assert months[-1].obligations_cents == 120_000 + 150_000


class TestDisclosed:  # XB2
    def test_missing_inputs_and_assumptions_are_listed(self):
        result = project(replace(PLAN, budget=(), missing=("no checking buffer is set",)), (),
                         AS_OF, 3)
        assert result.missing == ("no checking buffer is set",
                                  "no budget plan in effect for 3 months, from 2026-03: "
                                  "discretionary spending projects at 0")
        assert "discretionary spending at the budget target in full, never underspent" in \
            result.assumptions

    def test_discretionary_projects_at_the_target(self):
        months = project(PLAN, (), AS_OF, 3).months
        assert [month.discretionary_cents for month in months] == [150_000] * 3
