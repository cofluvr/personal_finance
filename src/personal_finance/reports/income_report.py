"""pf report income (D-068 points 3 and 8, M12.3): by month, each income source's baseline, extra
and side income, obligations due and paid by class, possible paychecks, and disclosures.

A nominal date decides an occurrence's month, never the deposit's date (point 3). In each month a
salary's first baseline-count dates are baseline and any later ones extra. Baseline is planned:
the baseline count times the amount in effect on each date, never the deposits. Extra and side are
actual: what was received on extra and side dates. Obligations due are planned at each date's
planned amount, a range's HIGH (G8), and paid is actual. Disclosures are counted in the month of
the transaction. Nothing here reads the clock: missed and expected need as_of. Read only.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from personal_finance.planning.income_effects import (
    BASELINE,
    BASELINE_COUNT,
    EXTRA,
    SALARY,
    SIDE,
    applying_sources,
    load_deposit_facts,
    matches,
    source_outcomes,
)
from personal_finance.planning.obligation_effects import (
    CLASSES,
    applying_obligations,
    load_payment_facts,
    obligation_outcomes,
)
from personal_finance.planning.schedules import scheduled_dates, unpaid_state
from personal_finance.reports.monthly import months_between

@dataclass
class Tally:
    """A count and an amount in cents."""

    count: int = 0
    cents: int = 0

    def add(self, cents: int) -> None:
        self.count += 1
        self.cents += cents


@dataclass
class SourcePart:
    """One part of one source's month: baseline, extra or side."""

    planned: Tally = field(default_factory=Tally)
    received: Tally = field(default_factory=Tally)
    missed: int = 0
    expected: int = 0


@dataclass
class SourceMonth:
    source_id: str
    name: str
    kind: str
    account_id: str
    parts: dict[str, SourcePart] = field(default_factory=dict)

    def part(self, name: str) -> SourcePart:
        return self.parts.setdefault(name, SourcePart())


@dataclass
class ClassMonth:
    due: Tally = field(default_factory=Tally)
    paid: Tally = field(default_factory=Tally)
    missed: int = 0
    expected: int = 0


@dataclass
class IncomeMonth:
    month: str
    sources: list[SourceMonth] = field(default_factory=list)
    classes: dict[str, ClassMonth] = field(
        default_factory=lambda: {name: ClassMonth() for name in CLASSES})
    possible_paychecks: Tally = field(default_factory=Tally)
    disclosures: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def total(self, part: str, figure: str) -> int:
        return sum(getattr(source.parts[part], figure).cents for source in self.sources
                   if part in source.parts)


@dataclass(frozen=True)
class IncomeReport:
    as_of: str
    months: tuple[IncomeMonth, ...]


def report_months(conn, account_id, first_month, last_month, as_of: date,
                  anchors=()) -> list[str]:
    """--from and --to as given. Otherwise from the first month holding a transaction in scope or
    a source's or obligation's first date, else as_of's, through as_of's month, or the last month
    holding a transaction if later."""
    if first_month and last_month:
        return months_between(first_month, last_month)
    first, last = conn.execute(
        """SELECT MIN(substr(COALESCE(transaction_date, posting_date), 1, 7)),
                  MAX(substr(COALESCE(transaction_date, posting_date), 1, 7))
           FROM ledger_transaction WHERE :account IS NULL OR account_id = :account""",
        {"account": account_id}).fetchone()
    today = as_of.isoformat()[:7]
    first = first_month or min(filter(None, (first, today, *(anchor[:7] for anchor in anchors))))
    last = last_month or max(filter(None, (last, today)))
    return months_between(first, last) if first <= last else []


def month_end(month: str) -> date:
    year, number = int(month[:4]), int(month[5:])
    following = date(year + (number == 12), number % 12 + 1, 1)
    return date.fromordinal(following.toordinal() - 1)


def income_report(conn: sqlite3.Connection, as_of: date, account_id: str | None = None,
                  first_month: str | None = None, last_month: str | None = None) -> IncomeReport:
    every_source = applying_sources(conn)
    sources = [source for source in every_source
               if account_id in (None, source.definition.account_id)]
    every_obligation = applying_obligations(conn)
    obligations = [obligation for obligation in every_obligation
                   if account_id in (None, obligation.definition.account_id)]
    anchors = [entry.terms[0].anchor for entry in (*sources, *obligations)]
    months = report_months(conn, account_id, first_month, last_month, as_of, anchors)
    by_month = {month: IncomeMonth(month) for month in months}
    if not months:
        return IncomeReport(as_of.isoformat(), ())
    horizon = month_end(months[-1])
    deposits = load_deposit_facts(conn, {source.definition.account_id for source in every_source})
    deposit_by_id = {facts.transaction_id: facts for facts in deposits}
    outcomes = source_outcomes(every_source, deposits)
    for source in sources:
        paid = {outcome.nominal_date: outcome for (_, source_id), outcome in outcomes.items()
                if source_id == source.source_id and outcome.nominal_date is not None}
        place_in_month = defaultdict(int)
        rows = {}
        for nominal, terms in scheduled_dates(source.terms, horizon):
            text = nominal.isoformat()
            place = place_in_month[text[:7]]
            place_in_month[text[:7]] += 1
            if text[:7] not in by_month:
                continue
            if source.definition.kind == SALARY:
                part_name = BASELINE if place < BASELINE_COUNT[terms.cadence.name] else EXTRA
            else:
                part_name = SIDE
            row = rows.setdefault(text[:7], SourceMonth(
                source.source_id, source.definition.name, source.definition.kind,
                source.definition.account_id))
            part = row.part(part_name)
            if part_name == BASELINE:
                part.planned.add(terms.amount_cents)
            outcome = paid.get(text)
            if outcome is not None:
                part.received.add(deposit_by_id[outcome.transaction_id].amount_cents)
            elif unpaid_state(nominal, as_of, source.definition.tolerance_days) == "missed":
                part.missed += 1
            else:
                part.expected += 1
        for month, row in rows.items():
            by_month[month].sources.append(row)
    in_scope = {source.source_id for source in sources}
    for (transaction_id, source_id), outcome in sorted(outcomes.items()):
        month = deposit_by_id[transaction_id].reporting_date[:7]
        if source_id in in_scope and month in by_month and outcome.state != "received":
            by_month[month].disclosures[outcome.state] += 1
    for facts in deposits:
        month = facts.reporting_date[:7]
        if (month in by_month and not facts.is_income
                and any(matches(source, facts) for source in sources)):
            by_month[month].possible_paychecks.add(facts.amount_cents)

    payments = load_payment_facts(conn, {obligation.definition.account_id
                                         for obligation in every_obligation})
    payment_by_id = {facts.transaction_id: facts for facts in payments}
    paid_outcomes = obligation_outcomes(every_obligation, payments)
    for obligation in obligations:
        met = {outcome.nominal_date: outcome for (_, obligation_id), outcome
               in paid_outcomes.items()
               if obligation_id == obligation.obligation_id and outcome.nominal_date is not None}
        for nominal, terms in scheduled_dates(obligation.terms, horizon):
            text = nominal.isoformat()
            if text[:7] not in by_month:
                continue
            row = by_month[text[:7]].classes[terms.obligation_class]
            row.due.add(terms.planned_cents)
            outcome = met.get(text)
            if outcome is not None:
                row.paid.add(payment_by_id[outcome.transaction_id].paid_cents)
            elif unpaid_state(nominal, as_of, obligation.definition.tolerance_days) == "missed":
                row.missed += 1
            else:
                row.expected += 1
    in_scope = {obligation.obligation_id for obligation in obligations}
    for (transaction_id, obligation_id), outcome in sorted(paid_outcomes.items()):
        month = payment_by_id[transaction_id].reporting_date[:7]
        if obligation_id in in_scope and month in by_month and outcome.state != "paid":
            key = "unscheduled_payment" if outcome.state == "unscheduled" else outcome.state
            by_month[month].disclosures[key] += 1
    for month in by_month.values():
        month.sources.sort(key=lambda row: (row.name, row.source_id))
    return IncomeReport(as_of.isoformat(), tuple(by_month[month] for month in months))
