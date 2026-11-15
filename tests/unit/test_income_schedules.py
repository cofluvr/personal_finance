"""Income sources' nominal pay dates, pairing and baseline months, as pure functions (IA2, IA4,
D-068 points 2 and 3, and its M12.1 slice plan). Every expected date is worked out by hand."""

from datetime import date

import pytest

from personal_finance.planning.income_effects import (
    AMOUNT_CHANGED,
    BASELINE,
    EXPECTED,
    EXTRA,
    MISSED,
    RECEIVED,
    SIDE,
    SOURCE_CONFLICT,
    UNSCHEDULED,
    Cadence,
    DepositFacts,
    IncomeSource,
    SourceDefinition,
    Terms,
    cadence_dates,
    nominal_dates,
    occurrences,
    on_cadence,
    paired_deposits,
    source_outcomes,
)


def days(*texts):
    return [date.fromisoformat(text) for text in texts]


def between(cadence, anchor, start, end):
    return cadence_dates(cadence, date.fromisoformat(anchor), date.fromisoformat(start),
                         date.fromisoformat(end))


class TestNominalDates:  # IA2
    def test_weekly_counts_from_the_anchor_both_ways(self):
        assert between(Cadence("weekly"), "2026-01-14", "2026-01-01", "2026-01-31") == days(
            "2026-01-07", "2026-01-14", "2026-01-21", "2026-01-28")

    def test_biweekly_crosses_a_year(self):
        assert between(Cadence("biweekly"), "2025-12-26", "2025-12-01", "2026-01-31") == days(
            "2025-12-12", "2025-12-26", "2026-01-09", "2026-01-23")

    def test_monthly_on_the_31st_is_each_month_s_last_day(self):
        assert between(Cadence("monthly", 31), "2026-01-31", "2026-01-01", "2026-05-31") == days(
            "2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31")

    def test_a_leap_year_february(self):
        assert between(Cadence("monthly", 30), "2028-01-30", "2028-02-01", "2028-03-31") == days(
            "2028-02-29", "2028-03-30")
        assert between(Cadence("semimonthly", 15, 31), "2028-01-15", "2028-02-01",
                       "2028-02-29") == days("2028-02-15", "2028-02-29")

    def test_semimonthly_gives_both_days(self):
        assert between(Cadence("semimonthly", 1, 15), "2026-01-01", "2026-01-01",
                       "2026-02-28") == days("2026-01-01", "2026-01-15", "2026-02-01",
                                             "2026-02-15")

    def test_quarterly_takes_the_anchor_s_months(self):
        assert between(Cadence("quarterly", 15), "2026-02-15", "2026-01-01", "2026-12-31") == days(
            "2026-02-15", "2026-05-15", "2026-08-15", "2026-11-15")

    def test_annual_on_february_29th(self):
        assert between(Cadence("annual", 29), "2028-02-29", "2026-01-01", "2029-12-31") == days(
            "2026-02-28", "2027-02-28", "2028-02-29", "2029-02-28")

    def test_every_n_months(self):
        assert between(Cadence("every_months", 10, interval_months=5), "2026-03-10", "2026-01-01",
                       "2026-12-31") == days("2026-03-10", "2026-08-10")

    def test_nothing_between_a_start_after_the_end(self):
        assert between(Cadence("weekly"), "2026-01-01", "2026-02-01", "2026-01-31") == []

    @pytest.mark.parametrize(("cadence", "anchor", "fits"), [
        (Cadence("weekly"), "2026-01-03", True),
        (Cadence("monthly", 15), "2026-01-15", True),
        (Cadence("monthly", 15), "2026-01-16", False),
        (Cadence("monthly", 31), "2026-02-28", True),
        (Cadence("semimonthly", 1, 15), "2026-01-15", True),
        (Cadence("semimonthly", 1, 15), "2026-01-14", False),
        (Cadence("annual", 29), "2027-02-28", True),
    ])
    def test_an_anchor_is_on_its_cadence_or_not(self, cadence, anchor, fits):
        assert on_cadence(cadence, date.fromisoformat(anchor)) is fits


def source(*terms, kind="salary", tolerance=3, amount_tolerance=0, source_id="s"):
    return IncomeSource(source_id, source_id, None,
                        SourceDefinition("acct", "Pay", kind, "payroll", tolerance,
                                         amount_tolerance, None, False), tuple(terms))


def biweekly(anchor="2026-01-02", amount=250000, effective_from=None):
    return Terms(effective_from or anchor, Cadence("biweekly"), anchor, amount)


def deposit(transaction_id, when, amount=250000, text="synthetic payroll", is_income=True):
    return DepositFacts(transaction_id, "acct", amount, text, when, is_income)


class TestTerms:  # IA7
    def test_a_later_row_changes_only_dates_from_its_effective_date(self):
        raised = source(biweekly(), biweekly(anchor="2026-01-30", amount=260000,
                                             effective_from="2026-01-20"))
        found = [(nominal.isoformat(), terms.amount_cents)
                 for nominal, terms in nominal_dates(raised, date(2026, 2, 28))]
        assert found == [("2026-01-02", 250000), ("2026-01-16", 250000),
                         ("2026-01-30", 260000), ("2026-02-13", 260000), ("2026-02-27", 260000)]

    def test_a_new_cadence_takes_over_from_its_date(self):
        changed = source(biweekly(), Terms("2026-02-01", Cadence("semimonthly", 1, 15),
                                           "2026-02-01", 250000))
        assert [nominal for nominal, _ in nominal_dates(changed, date(2026, 3, 1))] == days(
            "2026-01-02", "2026-01-16", "2026-01-30", "2026-02-01", "2026-02-15", "2026-03-01")

    def test_nothing_before_the_first_pay_date(self):
        assert nominal_dates(source(biweekly()), date(2026, 1, 1)) == []


class TestPairing:  # IA4
    def test_nearest_first(self):
        paired = paired_deposits(source(biweekly()), [deposit("far", "2026-01-15"),
                                                      deposit("near", "2026-01-16")])
        assert {key: value[0].isoformat() for key, value in paired.items()} == {
            "near": "2026-01-16"}

    def test_equal_distance_goes_to_the_earlier_nominal_date(self):
        # 2026-01-09 is 7 days from both 01-02 and 01-16, so a tolerance of 7 reaches both.
        paired = paired_deposits(source(biweekly(), tolerance=7), [deposit("x", "2026-01-09")])
        assert paired["x"][0] == date(2026, 1, 2)

    def test_equal_distance_and_date_goes_to_the_earlier_deposit_then_the_id(self):
        paired = paired_deposits(source(biweekly()), [deposit("b", "2026-01-03"),
                                                      deposit("a", "2026-01-01"),
                                                      deposit("c", "2026-01-01")])
        assert {key: value[0].isoformat() for key, value in paired.items()} == {
            "a": "2026-01-02"}

    def test_the_order_given_never_decides(self):
        deposits = [deposit("a", "2026-01-01"), deposit("b", "2026-01-03"),
                    deposit("c", "2026-01-17"), deposit("d", "2026-01-15")]
        expected = paired_deposits(source(biweekly()), deposits)
        assert paired_deposits(source(biweekly()), deposits[::-1]) == expected


class TestOutcomes:  # IA3, IA4
    def test_each_state(self):
        facts = [deposit("on", "2026-01-02"), deposit("raised", "2026-01-16", amount=255000),
                 deposit("again", "2026-01-17"), deposit("typed", "2026-02-13", is_income=False)]
        outcomes = source_outcomes([source(biweekly())], facts)
        assert {key[0]: (outcome.state, outcome.nominal_date)
                for key, outcome in outcomes.items()} == {
            "on": (RECEIVED, "2026-01-02"), "raised": (AMOUNT_CHANGED, "2026-01-16"),
            "again": (UNSCHEDULED, None)}

    def test_the_amount_tolerance_is_inclusive(self):
        outcomes = source_outcomes([source(biweekly(), amount_tolerance=5000)],
                                   [deposit("x", "2026-01-02", amount=255000)])
        assert outcomes[("x", "s")].state == RECEIVED

    def test_two_sources_on_one_deposit_count_toward_neither(self):
        sources = [source(biweekly(), source_id="one"), source(biweekly(), source_id="two")]
        outcomes = source_outcomes(sources, [deposit("x", "2026-01-02")])
        assert {key: outcome.state for key, outcome in outcomes.items()} == {
            ("x", "one"): SOURCE_CONFLICT, ("x", "two"): SOURCE_CONFLICT}

    def test_a_deposit_before_the_first_pay_date_less_the_tolerance_is_not_reached(self):
        outcomes = source_outcomes([source(biweekly())], [deposit("early", "2025-12-29"),
                                                          deposit("edge", "2025-12-30")])
        assert set(outcomes) == {("edge", "s")}


class TestOccurrences:  # IA4, point 3
    def at(self, as_of, the_source, facts):
        outcomes = source_outcomes([the_source], facts)
        return [(found.nominal_date, found.state, found.part)
                for found in occurrences(the_source, facts, outcomes, date.fromisoformat(as_of))]

    def test_missed_only_once_the_tolerance_has_passed(self):
        assert self.at("2026-01-05", source(biweekly()), []) == [
            ("2026-01-02", EXPECTED, BASELINE), ("2026-01-16", EXPECTED, BASELINE)]
        assert self.at("2026-01-06", source(biweekly()), [])[0] == (
            "2026-01-02", MISSED, BASELINE)

    def test_2026_s_three_paycheck_months_for_a_friday_anchor(self):
        # 2026-01-02 is a Friday: Jan 2, 16 and 30, and Jul 3, 17 and 31, hold three each.
        found = self.at("2026-12-31", source(biweekly()), [])
        extra = [nominal for nominal, _, part in found if part == EXTRA]
        assert extra == ["2026-01-30", "2026-07-31"]
        assert sum(1 for nominal, _, part in found
                   if part == BASELINE and nominal < "2027") == 24
        # The next one still to come is listed too: 2026-01-02 plus 26 fortnights, 364 days.
        assert found[-1] == ("2027-01-01", EXPECTED, BASELINE)

    def test_an_early_payment_across_a_month_boundary_is_not_a_third(self):
        # The pay date 2026-05-01 paid on 04-30 keeps its month, May.
        monthly = source(Terms("2026-04-01", Cadence("monthly", 1), "2026-04-01", 100000))
        found = self.at("2026-05-31", monthly, [deposit("early", "2026-04-30", amount=100000)])
        assert ("2026-05-01", RECEIVED, BASELINE) in found
        assert ("2026-04-01", MISSED, BASELINE) in found

    def test_side_income_is_never_baseline(self):
        side = source(biweekly(), kind="side")
        assert {part for _, _, part in self.at("2026-03-01", side, [])} == {SIDE}

    def test_the_next_one_still_to_come_and_an_early_one_paid(self):
        found = self.at("2026-01-10", source(biweekly()), [deposit("x", "2026-01-30")])
        assert found == [("2026-01-02", MISSED, BASELINE), ("2026-01-16", EXPECTED, BASELINE),
                         ("2026-01-30", RECEIVED, EXTRA)]
