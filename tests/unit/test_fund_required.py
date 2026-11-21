"""Each fund kind's required amount, by D-070 point 1's formula, computed by hand at a deadline
month, mid-term and past due, every division rounded up (GA2, G8), and the terms in effect chosen
by effective_from (G7)."""

import pytest

from personal_finance.planning.funds import (
    FUNDED,
    IN_PROGRESS,
    NOT_STARTED,
    UNDERFUNDED,
    Fund,
    FundTerms,
    StandingInputs,
    fund_standing,
    months_left_including,
)
from personal_finance.planning.schedules import Cadence
from personal_finance.reports.fund_standing import monthly_equivalent_cents


def goal(*terms):
    return Fund("g", "Goal", "goal", tuple(terms))


def standing(fund, assigned=0, as_of="2026-03-15", **inputs):
    return fund_standing(fund, assigned, StandingInputs(as_of, **inputs))


class TestGoals:
    def test_a_monthly_amount_each_month(self):
        result = standing(goal(FundTerms("2026-03-01", "monthly", amount_cents=50_000)), 999)
        assert (result.state, result.planned_contribution_cents) == (IN_PROGRESS, 50_000)

    @pytest.mark.parametrize("baseline, basis_points, required", [
        (520_000, 1_250, 65_000),
        # 500,001 × 10% is 50,000.1 cents: rounded up.
        (500_001, 1_000, 50_001),
        (0, 1_000, 0),
    ])
    def test_a_percentage_of_baseline_income_rounds_up(self, baseline, basis_points, required):
        fund = goal(FundTerms("2026-03-01", "percent", basis_points=basis_points))
        assert standing(fund, baseline_income_cents=baseline).planned_contribution_cents == required

    @pytest.mark.parametrize("as_of, assigned, state, required, outstanding, months_left", [
        # Mid-term: March to December is 10 months including both.
        ("2026-03-15", 0, IN_PROGRESS, 100_000, 1_000_000, 10),
        # 749,999 over 10 months is 74,999.9: rounded up.
        ("2026-03-15", 250_001, IN_PROGRESS, 75_000, 749_999, 10),
        # The deadline month: everything outstanding, still on time.
        ("2026-12-31", 400_000, IN_PROGRESS, 600_000, 600_000, 1),
        # Past due: all of it is needed now, and the fund is underfunded.
        ("2027-01-01", 400_000, UNDERFUNDED, 600_000, 600_000, 0),
        # Reached: nothing more, even past due.
        ("2027-01-01", 1_000_001, FUNDED, 0, 0, 0),
    ])
    def test_a_target_by_a_month(self, as_of, assigned, state, required, outstanding,
                                 months_left):
        fund = goal(FundTerms("2026-03-01", "target_by", amount_cents=1_000_000,
                              by_month="2026-12"))
        result = standing(fund, assigned, as_of)
        assert (result.state, result.planned_contribution_cents, result.outstanding_cents,
                result.months_left) == (state, required, outstanding, months_left)


class TestEmergency:
    @pytest.mark.parametrize("assigned, state, shortfall", [
        (100_000, UNDERFUNDED, 200_000), (300_000, FUNDED, 0), (300_001, FUNDED, 0)])
    def test_a_minimum(self, assigned, state, shortfall):
        fund = Fund("e", "Cushion", "emergency", (FundTerms("2026-03-01", "minimum",
                                                             amount_cents=300_000),))
        result = standing(fund, assigned)
        assert (result.state, result.required_held_cents, result.outstanding_cents) == (
            state, 300_000, shortfall)
        assert result.planned_contribution_cents is None

    def test_months_of_fixed_commitments(self):
        fund = Fund("e", "Cushion", "emergency", (FundTerms("2026-03-01", "months",
                                                             month_count=3),))
        result = standing(fund, 0, monthly_fixed_commitments_cents=85_001)
        assert (result.required_held_cents, result.outstanding_cents) == (255_003, 255_003)

    @pytest.mark.parametrize("cadence, amount, monthly", [
        (Cadence("monthly", 5), 8_500, 8_500),
        # 10,000 × 52 ÷ 12 is 43,333.3; × 26 ÷ 12 is 21,666.7: each rounded up.
        (Cadence("weekly"), 10_000, 43_334),
        (Cadence("biweekly"), 10_000, 21_667),
        (Cadence("semimonthly", 1, 15), 10_000, 20_000),
        (Cadence("quarterly", 5), 30_001, 10_001),
        (Cadence("annual", 5), 120_001, 10_001),
        (Cadence("every_months", 5, interval_months=6), 60_001, 10_001),
    ])
    def test_a_non_monthly_obligation_is_spread_rounding_up(self, cadence, amount, monthly):
        assert monthly_equivalent_cents(cadence, amount) == monthly


class TestReserves:
    def reserve(self, terms):
        return Fund("r", "Insurance", "reserve", (terms,))

    @pytest.mark.parametrize("as_of, assigned, state, required, months_left", [
        # March to September: 7 months. 120,000 ÷ 7 is 17,142.9: rounded up.
        ("2026-03-15", 0, IN_PROGRESS, 17_143, 7),
        ("2026-03-15", 60_000, IN_PROGRESS, 8_572, 7),
        # The due month, even after the due day: what is outstanding, on time.
        ("2026-09-20", 60_000, IN_PROGRESS, 60_000, 1),
        ("2026-10-01", 60_000, UNDERFUNDED, 60_000, 0),
        ("2026-10-01", 120_000, FUNDED, 0, 0),
    ])
    def test_a_due_date(self, as_of, assigned, state, required, months_left):
        fund = self.reserve(FundTerms("2026-03-01", "due", amount_cents=120_000,
                                      due_date="2026-09-01"))
        result = standing(fund, assigned, as_of)
        assert (result.state, result.planned_contribution_cents, result.months_left) == (
            state, required, months_left)

    @pytest.mark.parametrize("as_of, due, months_left", [
        ("2026-03-15", "2026-09-01", 7),
        # Due today: this month is the one left.
        ("2026-09-01", "2026-09-01", 1),
        # The day after: the next cycle, 13 months including both.
        ("2026-09-02", "2027-09-01", 13),
    ])
    def test_an_annual_recurrence(self, as_of, due, months_left):
        fund = self.reserve(FundTerms("2026-03-01", "recurring", amount_cents=130_000,
                                      cadence=Cadence("annual", 1), anchor="2026-09-01"))
        result = standing(fund, 0, as_of)
        assert (result.due, result.months_left) == (due, months_left)
        assert result.planned_contribution_cents == -(-130_000 // months_left)

    def test_every_n_months(self):
        fund = self.reserve(FundTerms("2026-03-01", "recurring", amount_cents=60_000,
                                      cadence=Cadence("every_months", 15, interval_months=6),
                                      anchor="2026-06-15"))
        result = standing(fund, 0, "2026-07-01")
        assert (result.due, result.months_left, result.planned_contribution_cents) == (
            "2026-12-15", 6, 10_000)


class TestTax:
    @pytest.mark.parametrize("accrued, paid, released, assigned, required, shortfall", [
        (100_000, 0, 0, 0, 100_000, 100_000),
        (100_000, 30_000, 0, 50_000, 70_000, 20_000),
        # Never below zero.
        (100_000, 30_000, 80_000, 0, 0, 0),
    ])
    def test_accrued_less_paid_and_released(self, accrued, paid, released, assigned, required,
                                            shortfall):
        fund = Fund("t", "Tax", "tax", (FundTerms("2026-01-01", "percent", basis_points=2_500),))
        result = standing(fund, assigned, tax_accrued_cents=accrued, tax_paid_cents=paid,
                          tax_released_cents=released)
        assert (result.required_held_cents, result.outstanding_cents) == (required, shortfall)


class TestTermsInEffect:  # G7
    fund = goal(FundTerms("2026-03-01", "monthly", amount_cents=50_000),
                FundTerms("2026-06-01", "monthly", amount_cents=70_000))

    @pytest.mark.parametrize("as_of, required", [
        ("2026-03-01", 50_000), ("2026-05-31", 50_000), ("2026-06-01", 70_000),
        ("2027-01-01", 70_000)])
    def test_the_latest_row_from_a_date_no_later(self, as_of, required):
        assert standing(self.fund, as_of=as_of).planned_contribution_cents == required

    def test_before_the_first_row_nothing_is_required(self):
        result = standing(self.fund, as_of="2026-02-28")
        assert (result.state, result.planned_contribution_cents) == (NOT_STARTED, None)


def test_months_left_includes_both_ends():
    assert months_left_including("2026-03", "2026-03") == 1
    assert months_left_including("2026-12", "2027-01") == 2
    assert months_left_including("2026-04", "2026-03") == 0
