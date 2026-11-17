"""D-069 point 4's formulas, every figure computed by hand (BB1), and rounding toward protection
over generated months and amounts (BB2, G8)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from personal_finance.planning.budget_pace import budget_pace

# (N, d, T, A) -> (R, C, original daily, revised daily, revised weekly, P, A - P, reduction,
# equivalent days), each worked by hand. T is 1000.00 throughout.
HAND_WORKED = [
    # 28 days: day 1 below, the middle exactly on pace, the last day over target.
    ((28, 1, 100000, 0), (28, 100000, 3571, 3571, 25000, 3571, -3571, None, None)),
    ((28, 14, 100000, 50000), (15, 50000, 3571, 3333, 23333, 50000, 0, 238, None)),
    ((28, 28, 100000, 120000), (1, -20000, 3571, 0, 0, 100000, 20000, 3571, 5)),
    # 30 days: day 1 at target, the middle below, near the end with fewer than seven days left,
    # and the last day a cent under.
    ((30, 1, 100000, 100000), (30, 0, 3333, 0, 0, 3333, 96667, 3333, 29)),
    ((30, 15, 100000, 20000), (16, 80000, 3333, 5000, 35000, 50000, -30000, None, None)),
    ((30, 27, 100000, 60000), (4, 40000, 3333, 10000, 40000, 90000, -30000, None, None)),
    ((30, 30, 100000, 99999), (1, 1, 3333, 1, 1, 100000, -1, 3332, None)),
    # 31 days: day 1 over target, the middle on pace, the last day at target.
    ((31, 1, 100000, 150000), (31, -50000, 3225, 0, 0, 3225, 146775, 3225, 45)),
    ((31, 16, 100000, 51612), (16, 48388, 3225, 3024, 21169, 51612, 0, 201, None)),
    ((31, 31, 100000, 100000), (1, 0, 3225, 0, 0, 100000, 0, 3225, None)),
]


@pytest.mark.parametrize("given_figures, expected", HAND_WORKED)
def test_each_formula_by_hand(given_figures, expected):  # BB1
    days, day, target, actual = given_figures
    pace = budget_pace(target, actual, days, day)
    assert (pace.days_remaining, pace.remaining_capacity_cents, pace.original_daily_cents,
            pace.revised_daily_cents, pace.revised_weekly_cents, pace.pace_to_date_cents,
            pace.against_pace_cents, pace.reduction_per_day_cents,
            pace.equivalent_days) == expected


def test_a_zero_target_has_no_equivalent_days():
    pace = budget_pace(0, 500, 30, 10)
    assert (pace.original_daily_cents, pace.equivalent_days, pace.remaining_capacity_cents) == (
        0, None, -500)


@pytest.mark.parametrize("figures", [(100, 0, 27, 1), (100, 0, 32, 1), (100, 0, 30, 0),
                                     (100, 0, 30, 31), (-1, 0, 30, 1)])
def test_a_day_outside_its_month_or_a_negative_target_is_refused(figures):
    with pytest.raises(ValueError):
        budget_pace(*figures)


months = st.integers(28, 31).flatmap(lambda days: st.tuples(st.just(days),
                                                            st.integers(1, days)))


@given(month=months, target=st.integers(0, 10**9), actual=st.integers(-10**9, 2 * 10**9))
def test_allowances_never_add_to_more_than_capacity(month, target, actual):  # BB2, G8
    days, day = month
    pace = budget_pace(target, actual, days, day)
    capacity = pace.remaining_capacity_cents
    assert pace.revised_daily_cents * pace.days_remaining <= max(capacity, 0)
    assert 0 <= pace.revised_weekly_cents <= max(capacity, 0)
    assert pace.revised_daily_cents * min(7, pace.days_remaining) <= pace.revised_weekly_cents
    assert pace.original_daily_cents * days <= target
    assert pace.pace_to_date_cents <= target
