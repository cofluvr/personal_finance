"""Loan schedules, projections and payoff orders by hand (LB2, LB4 and LB5, D-071 points 4 to
6). The expected table was computed with exact fractions, rounded half-even per month."""

from datetime import date

import pytest

from personal_finance.planning.loans import (
    AVALANCHE,
    CUSTOM,
    EXTRA,
    MISSED,
    ON_SCHEDULE,
    SHORT,
    SNOWBALL,
    UPCOMING,
    DebtAtStart,
    LoanTerms,
    format_rate,
    monthly_interest,
    ordered,
    parsed_rate,
    payoff,
    period_state,
    project,
)


def terms(rates, payments=(), due_day=5, name="L", account="l"):
    return LoanTerms(f"t-{account}", account, name, "loan", due_day, None, tuple(rates),
                     tuple(payments))


GRADUATED = terms(rates=[("2026-01-01", 6_875_000), ("2026-07-01", 7_250_000)],
                  payments=[("2026-01-01", 50_000), ("2026-07-05", 52_000)])


class TestSchedule:  # LB2
    @pytest.mark.parametrize("day, expected", [
        ("2026-01-05", 50_000), ("2026-07-04", 50_000), ("2026-07-05", 52_000),
        ("2026-12-05", 52_000), ("2025-12-31", 0)])
    def test_the_amount_due_is_the_period_in_effect_that_day(self, day, expected):
        assert GRADUATED.payment_on(day) == expected

    def test_a_six_step_schedule_at_every_step(self):
        steps = [(f"2026-{month:02}-05", 10_000 * month) for month in range(1, 7)]
        stepped = terms(rates=[("2026-01-01", 1)], payments=steps)
        for month in range(1, 7):
            assert stepped.payment_on(f"2026-{month:02}-05") == 10_000 * month
            assert stepped.payment_on(f"2026-{month:02}-04") == 10_000 * (month - 1)

    def test_the_rate_for_a_month_is_the_period_on_its_first_day(self):
        assert GRADUATED.rate_on("2026-06-30") == 6_875_000
        assert GRADUATED.rate_on("2026-07-01") == 7_250_000

    @pytest.mark.parametrize("due, paid, as_of, state", [
        (100, 100, "2026-03-01", ON_SCHEDULE), (100, 60, "2026-03-01", SHORT),
        (100, 160, "2026-03-01", EXTRA), (100, 0, "2026-03-01", MISSED),
        (100, 0, "2026-02-05", UPCOMING), (100, 60, "2026-02-04", UPCOMING)])
    def test_each_state(self, due, paid, as_of, state):
        assert period_state(due, paid, date(2026, 2, 5), date.fromisoformat(as_of)) == state


class TestProjection:  # LB4
    def test_twelve_months_match_the_hand_computed_table(self):
        found = project(GRADUATED, 1_000_000, "2026-01-20", months=12)
        assert [(month.due, month.rate_millionths, month.payment_cents, month.interest_cents,
                 month.principal_cents, month.balance_cents) for month in found.months] == [
            ("2026-02-05", 6875000, 50000, 5729, 44271, 955729),
            ("2026-03-05", 6875000, 50000, 5476, 44524, 911205),
            ("2026-04-05", 6875000, 50000, 5220, 44780, 866425),
            ("2026-05-05", 6875000, 50000, 4964, 45036, 821389),
            ("2026-06-05", 6875000, 50000, 4706, 45294, 776095),
            ("2026-07-05", 7250000, 52000, 4689, 47311, 728784),
            ("2026-08-05", 7250000, 52000, 4403, 47597, 681187),
            ("2026-09-05", 7250000, 52000, 4116, 47884, 633303),
            ("2026-10-05", 7250000, 52000, 3826, 48174, 585129),
            ("2026-11-05", 7250000, 52000, 3535, 48465, 536664),
            ("2026-12-05", 7250000, 52000, 3242, 48758, 487906),
            ("2027-01-05", 7250000, 52000, 2948, 49052, 438854)]

    def test_interest_rounds_half_even(self):
        # 0.12 at 50% a year is 0.005 a month, to 0.00; 0.36 is 0.015, to 0.02.
        assert monthly_interest(12, 50_000_000) == 0
        assert monthly_interest(36, 50_000_000) == 2

    def test_the_last_payment_is_what_is_owed(self):
        found = project(GRADUATED, 60_000, "2026-01-20")
        assert found.paid_off == "2026-03-05"
        last = found.months[-1]
        assert last.balance_cents == 0 and last.payment_cents < 50_000

    def test_negative_amortization_is_flagged_and_never_pays_off(self):
        found = project(terms(rates=[("2026-01-01", 24_000_000)],
                              payments=[("2026-01-01", 1_000)]), 1_000_000, "2026-01-20")
        assert found.negative_amortization and found.paid_off is None
        assert len(found.months) == 600

    def test_the_horizon_stops_at_600_months(self):
        assert len(project(GRADUATED, 10**12, "2026-01-20", months=900).months) == 600

    def test_an_extra_pays_off_sooner(self):
        assert (project(GRADUATED, 1_000_000, "2026-01-20", 20_000).paid_off
                < project(GRADUATED, 1_000_000, "2026-01-20").paid_off)


def debt(account, owed, rate, payment, name=None):
    return DebtAtStart(terms(rates=[("2026-01-01", rate)], payments=[("2026-01-01", payment)],
                             name=name or account, account=account), owed, rate)


DEBTS = (debt("a", 500_000, 5_000_000, 20_000, "Auto"), debt("c", 200_000, 22_000_000, 10_000,
                                                              "Card loan"),
         debt("s", 1_500_000, 6_000_000, 30_000, "Student"))


class TestPayoffOrders:  # LB5
    def test_avalanche_and_snowball_orders_and_their_ties(self):
        assert ordered(DEBTS, AVALANCHE) == ("c", "s", "a")
        assert ordered(DEBTS, SNOWBALL) == ("c", "a", "s")
        tied = (debt("x", 100, 5, 1, "B"), debt("y", 100, 5, 1, "A"), debt("z", 200, 5, 1, "C"))
        assert ordered(tied, AVALANCHE) == ("z", "y", "x")
        assert ordered(tied, SNOWBALL) == ("y", "x", "z")
        assert ordered(DEBTS, CUSTOM, ("s", "a", "c")) == ("s", "a", "c")

    def test_the_extra_goes_to_the_first_unpaid_and_payments_roll_over(self):
        outcome = payoff(DEBTS, AVALANCHE, 50_000, date(2026, 1, 20))
        assert outcome.months_to_debt_free is not None
        paid = [outcome.payoff_by_account[account] for account in outcome.sequence]
        assert paid == sorted(paid)  # the card loan first, its payment then rolling on
        none = payoff(DEBTS, AVALANCHE, 0, date(2026, 1, 20))
        assert outcome.months_to_debt_free < none.months_to_debt_free
        assert sum(outcome.interest_by_account.values()) < sum(none.interest_by_account.values())

    def test_one_month_by_hand(self):
        one = (debt("a", 30_000, 12_000_000, 10_000), debt("b", 5_000, 12_000_000, 10_000))
        outcome = payoff(one, SNOWBALL, 0, date(2026, 1, 20))
        # February: interest 300 and 50; b owes 5,050 and takes it, a takes 10,000, and the
        # 4,950 left goes to a, which owes 30,300 − 14,950 = 15,350.
        assert outcome.payoff_by_account["b"] == "2026-02-05"
        assert outcome.interest_by_account["b"] == 50

    def test_it_is_deterministic(self):
        first = payoff(DEBTS, SNOWBALL, 12_345, date(2026, 1, 20))
        assert first == payoff(DEBTS, SNOWBALL, 12_345, date(2026, 1, 20))


def test_rates_parse_to_millionths_and_print_back():
    assert parsed_rate("6.875") == 6_875_000
    assert parsed_rate("100") == 100_000_000
    assert format_rate(6_875_000) == "6.875%"
    assert format_rate(0) == "0%"


def test_a_rate_step_within_a_month_starts_with_the_next_month():
    stepped = terms(rates=[("2026-01-01", 6_000_000), ("2026-07-03", 12_000_000)],
                    payments=[("2026-01-01", 50_000)])
    july, august = project(stepped, 1_000_000, "2026-06-20", months=2).months
    # July's first day is before the step, so July pays 6%: 5,000 on 1,000,000.
    assert (july.due, july.rate_millionths, july.interest_cents) == ("2026-07-05", 6_000_000, 5000)
    assert august.rate_millionths == 12_000_000


def test_snowball_ties_go_to_the_higher_rate():
    tied = (debt("x", 100, 5, 1, "A"), debt("y", 100, 9, 1, "B"))
    assert ordered(tied, SNOWBALL) == ("y", "x")


def test_a_paid_off_loan_s_payment_rolls_over_by_hand():
    # No interest. February: a takes 50.00 and is paid off, b takes 100.00 and the 50.00 left,
    # owing 250.00. March: the budget is still 200.00, so b owes 50.00, and pays off in April.
    small, large = (debt("a", 5_000, 0, 10_000, "A"), debt("b", 40_000, 0, 10_000, "B"))
    outcome = payoff((small, large), SNOWBALL, 0, date(2026, 1, 20))
    assert outcome.payoff_by_account == {"a": "2026-02-05", "b": "2026-04-05"}
    assert outcome.months_to_debt_free == 3
