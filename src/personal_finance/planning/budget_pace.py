"""Budget pace for one month, D-069 point 4's formulas exactly, in integer cents. Every allowance
rounds down (G8), so the revised daily allowance over the days remaining never adds to more than
the remaining capacity. Pure: as_of's day and the month's length are arguments (G7).

Every figure here is budget pace, never "safe to spend" (M16).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetPace:
    days_in_month: int
    # d, the day of the month as_of falls on, and R, the days remaining including today.
    day_of_month: int
    days_remaining: int
    target_cents: int
    actual_cents: int
    remaining_capacity_cents: int
    original_daily_cents: int
    revised_daily_cents: int
    revised_weekly_cents: int
    pace_to_date_cents: int
    # A − P: positive above pace, negative below.
    against_pace_cents: int
    # Original daily − revised daily, when positive, else None.
    reduction_per_day_cents: int | None
    # floor((A − P) ÷ original daily), only when A > P and original daily > 0, else None.
    equivalent_days: int | None


def budget_pace(target_cents: int, actual_cents: int, days_in_month: int,
                day_of_month: int) -> BudgetPace:
    """D-069 point 4, for as_of on day d of a month of N days."""
    if not 28 <= days_in_month <= 31 or not 1 <= day_of_month <= days_in_month:
        raise ValueError("a day outside its month")
    if target_cents < 0:
        raise ValueError("a negative target")
    days_remaining = days_in_month - day_of_month + 1
    capacity = target_cents - actual_cents
    original_daily = target_cents // days_in_month
    revised_daily = capacity // days_remaining if capacity > 0 else 0
    revised_weekly = capacity * min(7, days_remaining) // days_remaining if capacity > 0 else 0
    pace_to_date = target_cents * day_of_month // days_in_month
    against_pace = actual_cents - pace_to_date
    reduction = original_daily - revised_daily
    equivalent_days = (against_pace // original_daily
                       if against_pace > 0 and original_daily > 0 else None)
    return BudgetPace(days_in_month, day_of_month, days_remaining, target_cents, actual_cents,
                      capacity, original_daily, revised_daily, revised_weekly, pace_to_date,
                      against_pace, reduction if reduction > 0 else None, equivalent_days)
