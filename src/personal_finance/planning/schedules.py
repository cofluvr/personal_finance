"""Nominal dates of a dated schedule, pairing what happened with them, and fitting a cadence to
history. Shared by income sources and recurring obligations (D-068 points 2, 4 and 6), and later
by reserves and loans. Extracted at its second use (principle 2).

Everything here is a pure function of its arguments. Nothing reads the clock or the ledger.
"""

import calendar
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

WEEK_STEPS = {"weekly": 7, "biweekly": 14}
MONTH_STEPS = {"semimonthly": 1, "monthly": 1, "quarterly": 3, "annual": 12}

CADENCE_INVALID = (
    "--cadence must be weekly, biweekly, semimonthly:D1,D2 with D1 before D2, monthly:D, "
    "quarterly:D, annual:MM-DD or every:N-months:D, each day from 1 to 31 and N from 2. Nothing "
    "was changed."
)

# Proposals (D-068 point 4): the default date tolerance, the fewest dated items per cadence, at
# least 3 or 2 for quarterly and annual, and how many of the latest give the suggested amount.
PROPOSAL_TOLERANCE_DAYS = 3
FEWEST_ITEMS = {"weekly": 3, "biweekly": 3, "semimonthly": 3, "monthly": 3, "quarterly": 2,
                "annual": 2}
SUGGESTED_FROM = 6


@dataclass(frozen=True)
class Cadence:
    """weekly and biweekly count from the anchor. Every other cadence names its days, and the
    anchor fixes which months: every month, every third, the anchor's month, or every N."""

    name: str
    first_day: int | None = None
    second_day: int | None = None
    interval_months: int | None = None

    @property
    def months_between(self) -> int:
        return self.interval_months or MONTH_STEPS[self.name]


@dataclass(frozen=True)
class ScheduleTerms:
    """The dated part of any terms row: from when, on which cadence, fixed by which anchor."""

    effective_from: str
    cadence: Cadence
    anchor: str


@dataclass(frozen=True)
class StatedCadence:
    cadence: Cadence
    # For annual only: the month it names, which its anchor must fall in.
    month: int | None = None


def last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def month_dates(cadence: Cadence, year: int, month: int) -> list[date]:
    """The cadence's days in one month. A day beyond the month's end is its last day."""
    days = [cadence.first_day] + ([cadence.second_day] if cadence.second_day else [])
    return [date(year, month, min(day, last_day(year, month))) for day in days]


def cadence_dates(cadence: Cadence, anchor: date, start: date, end: date) -> list[date]:
    """The cadence's nominal dates from start through end, both included, fixed by anchor."""
    if start > end:
        return []
    if cadence.name in WEEK_STEPS:
        step = WEEK_STEPS[cadence.name]
        first = -((anchor - start).days // step)
        found = []
        nominal = anchor + timedelta(days=first * step)
        while nominal <= end:
            if nominal >= start:
                found.append(nominal)
            nominal += timedelta(days=step)
        return found
    step = cadence.months_between
    anchor_index = anchor.year * 12 + anchor.month - 1
    found = []
    for index in range(start.year * 12 + start.month - 1, end.year * 12 + end.month):
        if (index - anchor_index) % step == 0:
            year, month = divmod(index, 12)
            found.extend(nominal for nominal in month_dates(cadence, year, month + 1)
                         if start <= nominal <= end)
    return found


def on_cadence(cadence: Cadence, anchor: date) -> bool:
    """Whether the anchor is itself one of its cadence's nominal dates."""
    return cadence_dates(cadence, anchor, anchor, anchor) == [anchor]


def scheduled_dates(terms_rows, end: date) -> list:
    """Every nominal date from the first terms row's effective_from through end, each with the
    terms row in effect. Each row's own cadence and anchor give its dates, from its effective_from
    until the next row's. terms_rows are oldest first."""
    found = []
    for position, terms in enumerate(terms_rows):
        start = date.fromisoformat(terms.effective_from)
        until = end
        if position + 1 < len(terms_rows):
            until = min(end, date.fromisoformat(terms_rows[position + 1].effective_from)
                        - timedelta(days=1))
        found.extend((nominal, terms) for nominal in
                     cadence_dates(terms.cadence, date.fromisoformat(terms.anchor), start, until))
    return found


def terms_in_effect(terms_rows, on: str):
    """The terms row in effect on a date: the latest starting no later than it, else the first."""
    starting = [terms for terms in terms_rows if terms.effective_from <= on]
    return starting[-1] if starting else terms_rows[0]


def paired_with_dates(terms_rows, tolerance_days: int, dated_items) -> dict:
    """Each item paired one to one with a nominal date within the tolerance, by transaction ID, as
    (nominal date, terms row). Items have reporting_date and transaction_id. Pairs are taken
    greedily, nearest first, then the earlier nominal date, then the earlier item, then the
    transaction ID, so import order never decides (M12.1 slice plan point 6)."""
    if not dated_items:
        return {}
    latest = max(date.fromisoformat(item.reporting_date) for item in dated_items)
    dates = scheduled_dates(terms_rows, latest + timedelta(days=tolerance_days))
    candidates = []
    for item in dated_items:
        when = date.fromisoformat(item.reporting_date)
        for nominal, terms in dates:
            distance = abs((when - nominal).days)
            if distance <= tolerance_days:
                candidates.append((distance, nominal, item.reporting_date, item.transaction_id,
                                   terms))
    paired, taken = {}, set()
    for _, nominal, _, transaction_id, terms in sorted(candidates, key=lambda pair: pair[:4]):
        if transaction_id not in paired and nominal not in taken:
            paired[transaction_id] = (nominal, terms)
            taken.add(nominal)
    return paired


def dates_to_show(terms_rows, paid_dates, as_of: date) -> list:
    """Every nominal date up to a horizon past the latest paid one and as_of, each as (nominal
    date, terms row, shown). A show lists every one through as_of, any later one already paid,
    and the next one still to come. paid_dates are ISO dates. The ones not shown are kept, so a
    caller can count a date's place in its month."""
    latest = max([date.fromisoformat(nominal) for nominal in paid_dates] + [as_of])
    longest = max(1 if terms.cadence.name in WEEK_STEPS else terms.cadence.months_between
                  for terms in terms_rows)
    found, next_shown = [], False
    for nominal, terms in scheduled_dates(terms_rows, latest + timedelta(days=31 * (longest + 1))):
        upcoming = nominal > as_of and nominal.isoformat() not in paid_dates
        shown = not (upcoming and next_shown)
        next_shown = next_shown or upcoming
        found.append((nominal, terms, shown))
    return found


def unpaid_state(nominal: date, as_of: date, tolerance_days: int) -> str:
    """missed only once the tolerance has passed as_of, else expected."""
    return "missed" if as_of > nominal + timedelta(days=tolerance_days) else "expected"


# Cadences as a person types them.

_DAY = r"([1-9]|[12][0-9]|3[01])"
_CADENCES = (
    (re.compile(r"weekly"), lambda found: Cadence("weekly")),
    (re.compile(r"biweekly"), lambda found: Cadence("biweekly")),
    (re.compile(rf"semimonthly:{_DAY},{_DAY}"),
     lambda found: Cadence("semimonthly", int(found[1]), int(found[2]))),
    (re.compile(rf"monthly:{_DAY}"), lambda found: Cadence("monthly", int(found[1]))),
    (re.compile(rf"quarterly:{_DAY}"), lambda found: Cadence("quarterly", int(found[1]))),
    (re.compile(rf"every:([2-9]|[1-9][0-9])-months:{_DAY}"),
     lambda found: Cadence("every_months", int(found[2]), interval_months=int(found[1]))),
)
_ANNUAL = re.compile(r"annual:(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])")


def parsed_cadence(text: str) -> StatedCadence | None:
    """A cadence as typed, or None for text no cadence reads, which CADENCE_INVALID explains."""
    for pattern, build in _CADENCES:
        found = pattern.fullmatch(text)
        if found:
            cadence = build(found)
            if cadence.second_day is not None and cadence.second_day <= cadence.first_day:
                return None
            return StatedCadence(cadence)
    found = _ANNUAL.fullmatch(text)
    if found:
        return StatedCadence(Cadence("annual", int(found[2])), int(found[1]))
    return None


def cadence_spec(cadence: Cadence, anchor: str) -> str:
    """The cadence as a person types it."""
    if cadence.name == "semimonthly":
        return f"semimonthly:{cadence.first_day},{cadence.second_day}"
    if cadence.name in ("monthly", "quarterly"):
        return f"{cadence.name}:{cadence.first_day}"
    if cadence.name == "annual":
        return f"annual:{anchor[5:7]}-{cadence.first_day:02d}"
    if cadence.name == "every_months":
        return f"every:{cadence.interval_months}-months:{cadence.first_day}"
    return cadence.name


# Fitting a cadence to history, for proposals (D-068 point 4).

@dataclass(frozen=True)
class FittedCadence:
    cadence: Cadence
    # The nominal date the earliest item pairs with (M12.1 slice plan point J).
    anchor: str
    # The nominal date after the last item's.
    next_expected: str


def proposal_key(account_id: str, normalized: str, spec: str) -> str:
    """Stable across imports: the account, the normalized text and the cadence."""
    text = json.dumps([account_id, normalized, spec], separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def most_common_days(days, count: int) -> list[int]:
    """The count days of the month seen most often, ties to the earlier day, ascending."""
    ranked = sorted(Counter(days).items(), key=lambda pair: (-pair[1], pair[0]))
    return sorted(day for day, _ in ranked[:count])


def candidate_cadences(dates: list[date]) -> list[tuple[Cadence, date | None]]:
    """Each cadence worth trying, in a fixed order, with the anchor it would start at."""
    first = dates[0]
    days = [when.day for when in dates]
    found = [(Cadence("weekly"), first), (Cadence("biweekly"), first)]
    pair = most_common_days(days, 2)
    if len(pair) == 2:
        found.append((Cadence("semimonthly", pair[0], pair[1]), None))
    (day,) = most_common_days(days, 1)
    for name in ("monthly", "quarterly", "annual"):
        found.append((Cadence(name, day), None))
    return found


def probe_terms(cadence: Cadence, start: date, anchor: date) -> tuple[ScheduleTerms]:
    """A cadence's dates from start on, fixed by anchor."""
    return (ScheduleTerms(start.isoformat(), cadence, anchor.isoformat()),)


def fitted(dates: list[date], cadence: Cadence, anchor: date | None) -> date | None:
    """The anchor at which the i-th date falls within the tolerance of the i-th nominal date for
    every i, or None. A month-based cadence starts at its nominal date nearest the first date."""
    tolerance = timedelta(days=PROPOSAL_TOLERANCE_DAYS)
    if anchor is None:
        probe = probe_terms(cadence, dates[0] - timedelta(days=40), dates[0])
        nearby = [nominal for nominal, _ in scheduled_dates(probe, dates[0] + tolerance)
                  if nominal >= dates[0] - tolerance]
        if not nearby:
            return None
        anchor = min(nearby, key=lambda nominal: (abs((nominal - dates[0]).days), nominal))
    expected = [nominal for nominal, _ in
                scheduled_dates(probe_terms(cadence, anchor, anchor), dates[-1] + tolerance)]
    if len(expected) != len(dates):
        return None
    if any(abs((when - nominal).days) > PROPOSAL_TOLERANCE_DAYS
           for when, nominal in zip(dates, expected)):
        return None
    return anchor


def fitted_cadence(dates: list[date]) -> FittedCadence | None:
    """The first cadence, in candidate order, that dates fit pay date by pay date, or None. dates
    are ascending."""
    for cadence, anchor in candidate_cadences(dates):
        if len(dates) < FEWEST_ITEMS[cadence.name]:
            continue
        start = fitted(dates, cadence, anchor)
        if start is None:
            continue
        upcoming = scheduled_dates(probe_terms(cadence, start, start),
                                   dates[-1] + timedelta(days=400))[len(dates)][0]
        return FittedCadence(cadence, start.isoformat(), upcoming.isoformat())
    return None


def within_band(amounts) -> bool:
    """Every amount within 10% of the smallest (D-068 point 4)."""
    return max(amounts) * 100 <= min(amounts) * 110


def median_half_down(amounts: list[int]) -> int:
    ordered = sorted(amounts)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2
