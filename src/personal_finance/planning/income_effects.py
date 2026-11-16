"""Income sources: their nominal pay dates, the deposits each reaches, and what each deposit is
there. See decisions-m12-m21.md D-068 and its M12.1 slice plan.

A source binds no records. Its outcome is derived from the evidence held now, on every write, so
it reaches later imports in any order. A deposit is reached only when it is money in on the
source's account, in D-056's income group (typed income, no transfer confirmed), dated no earlier
than the first pay date less the date tolerance, and its normalized effective description contains
the source's normalized text. Two sources reaching one deposit leave it to neither. Nothing here
reads the clock: missed and expected are worked out only where an as-of date is given.
"""

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from personal_finance.planning.schedules import (  # noqa: F401, the schedules income reads
    Cadence,
    cadence_dates,
    dates_to_show,
    on_cadence,
    paired_with_dates,
    scheduled_dates,
    unpaid_state,
)
from personal_finance.reconcile.category_effects import CONFIRMED_TRANSFER_SQL
from personal_finance.reconcile.category_rule_effects import (
    NORMALIZATION_VERSION,
    UnknownNormalization,
    normalized_text,
)

SALARY = "salary"
SIDE = "side"

RECEIVED = "received"
AMOUNT_CHANGED = "amount_changed"
UNSCHEDULED = "unscheduled"
SOURCE_CONFLICT = "source_conflict"
MISSED = "missed"
EXPECTED = "expected"

BASELINE = "baseline"
EXTRA = "extra"

# Point 3: floor(occurrences per year / 12). Longer cadences are never salary.
BASELINE_COUNT = {"weekly": 4, "biweekly": 2, "semimonthly": 2, "monthly": 1}


@dataclass(frozen=True)
class Terms:
    effective_from: str
    cadence: Cadence
    anchor: str
    amount_cents: int


@dataclass(frozen=True)
class SourceDefinition:
    """What a source says, and never changes."""

    account_id: str
    name: str
    kind: str
    description_contains: str
    tolerance_days: int
    amount_tolerance_cents: int
    member_id: int | None
    tax_eligible: bool
    normalization_version: int = NORMALIZATION_VERSION


@dataclass(frozen=True)
class IncomeSource:
    source_id: str
    chain_id: str
    supersedes_id: str | None
    definition: SourceDefinition
    # The chain's terms, oldest first. The first starts at the first pay date.
    terms: tuple[Terms, ...]
    created_at: str | None = None
    undone_at: str | None = None
    # The active source superseding this one, if any.
    superseded_by: str | None = None

    @property
    def entry_id(self) -> str:
        return self.source_id

    @property
    def applies(self) -> bool:
        return self.undone_at is None and self.superseded_by is None

    @property
    def state(self) -> str:
        if self.undone_at:
            return "undone"
        return "superseded" if self.superseded_by else "active"

    @property
    def first_pay_date(self) -> date:
        return date.fromisoformat(self.terms[0].anchor)

    @property
    def earliest_reached(self) -> str:
        """No deposit dated before this is reached."""
        return (self.first_pay_date - timedelta(days=self.definition.tolerance_days)).isoformat()


@dataclass(frozen=True)
class DepositFacts:
    """Money in, as a source reads it: effective values, corrected where they apply."""

    transaction_id: str
    account_id: str
    amount_cents: int
    normalized_description: str | None
    # The effective transaction date, else the effective posting date, as a month is chosen.
    reporting_date: str
    # In D-056's income group. Otherwise unclassified, with no transfer confirmed.
    is_income: bool


@dataclass(frozen=True)
class DepositOutcome:
    transaction_id: str
    source_id: str
    state: str
    # The nominal pay date it pairs with, for received and amount_changed only.
    nominal_date: str | None


@dataclass(frozen=True)
class Occurrence:
    """One nominal pay date, as of a date."""

    nominal_date: str
    terms: Terms
    state: str
    # baseline or extra for salary, by its place in its month, else side.
    part: str
    deposit: DepositFacts | None


def nominal_dates(source: IncomeSource, end: date) -> list[tuple[date, Terms]]:
    """Every nominal pay date from the first pay date through end, each with the terms in effect.
    Each terms row's own cadence and anchor give its dates, from its effective_from until the next
    row's."""
    return scheduled_dates(source.terms, end)


def matches(source: IncomeSource, facts: DepositFacts) -> bool:
    """The text and account a source reaches, whatever the deposit's type or date."""
    return (facts.account_id == source.definition.account_id
            and facts.normalized_description is not None
            and normalized_text(source.definition.description_contains)
            in facts.normalized_description)


def reaches(source: IncomeSource, facts: DepositFacts) -> bool:
    return (facts.is_income and matches(source, facts)
            and facts.reporting_date >= source.earliest_reached)


def paired_deposits(source: IncomeSource, deposits) -> dict[str, tuple[date, Terms]]:
    """Each deposit paired one to one with a nominal date within the tolerance, by transaction
    ID. Pairs are taken greedily, nearest first, then the earlier nominal date, then the earlier
    deposit, then the transaction ID, so import order never decides."""
    return paired_with_dates(source.terms, source.definition.tolerance_days, deposits)


def source_outcomes(sources, facts_list) -> dict[tuple[str, str], DepositOutcome]:
    """The outcome on every deposit an applying source reaches, keyed by transaction and
    source."""
    reached = {source.source_id: [facts for facts in facts_list if reaches(source, facts)]
               for source in sources}
    holders = defaultdict(list)
    for source_id, deposits in reached.items():
        for facts in deposits:
            holders[facts.transaction_id].append(source_id)
    outcomes = {}
    for source in sources:
        alone = [facts for facts in reached[source.source_id]
                 if len(holders[facts.transaction_id]) == 1]
        paired = paired_deposits(source, alone)
        for facts in reached[source.source_id]:
            key = (facts.transaction_id, source.source_id)
            if len(holders[facts.transaction_id]) > 1:
                outcomes[key] = DepositOutcome(*key, SOURCE_CONFLICT, None)
            elif facts.transaction_id in paired:
                nominal, terms = paired[facts.transaction_id]
                within = (abs(facts.amount_cents - terms.amount_cents)
                          <= source.definition.amount_tolerance_cents)
                outcomes[key] = DepositOutcome(*key, RECEIVED if within else AMOUNT_CHANGED,
                                               nominal.isoformat())
            else:
                outcomes[key] = DepositOutcome(*key, UNSCHEDULED, None)
    return outcomes


def occurrences(source: IncomeSource, facts_list, outcomes, as_of: date) -> list[Occurrence]:
    """Every nominal pay date through as_of, any later one a deposit already paid, and the next
    one still to come. missed only once the tolerance has passed as_of."""
    by_id = {facts.transaction_id: facts for facts in facts_list}
    paid = {outcome.nominal_date: outcome for (_, source_id), outcome in outcomes.items()
            if source_id == source.source_id and outcome.nominal_date is not None}
    found, place_in_month = [], defaultdict(int)
    for nominal, terms, shown in dates_to_show(source.terms, paid, as_of):
        text = nominal.isoformat()
        place = place_in_month[text[:7]]
        place_in_month[text[:7]] += 1
        if not shown:
            continue
        if source.definition.kind == SALARY:
            part = BASELINE if place < BASELINE_COUNT[terms.cadence.name] else EXTRA
        else:
            part = SIDE
        if text in paid:
            found.append(Occurrence(text, terms, paid[text].state, part,
                                    by_id[paid[text].transaction_id]))
        else:
            found.append(Occurrence(text, terms, unpaid_state(
                nominal, as_of, source.definition.tolerance_days), part, None))
    return found


def load_sources(conn: sqlite3.Connection) -> tuple[IncomeSource, ...]:
    """Every source on record with its chain's terms, in the order made."""
    terms_by_chain = defaultdict(list)
    for (chain_id, effective_from, cadence, first_day, second_day, interval_months, anchor,
         amount_cents) in conn.execute(
        """SELECT chain_id, effective_from, cadence, first_day, second_day, interval_months,
                  anchor, amount_cents
           FROM income_source_terms ORDER BY chain_id, effective_from"""
    ):
        terms_by_chain[chain_id].append(Terms(
            effective_from, Cadence(cadence, first_day, second_day, interval_months), anchor,
            amount_cents))
    rows = conn.execute(
        """SELECT source.id, source.chain_id, source.supersedes_id, source.account_id,
                  source.name, source.kind, source.description_contains, source.tolerance_days,
                  source.amount_tolerance_cents, source.member_id, source.tax_eligible,
                  source.normalization_version, source.created_at, undone.created_at
           FROM income_source source
           LEFT JOIN income_source_event undone
               ON undone.source_id = source.id AND undone.event = 'undone'
           ORDER BY source.created_at, source.id"""
    ).fetchall()
    superseded_by = {row[2]: row[0] for row in rows if row[2] and row[13] is None}
    sources = []
    for (source_id, chain_id, supersedes_id, account_id, name, kind, text, tolerance_days,
         amount_tolerance, member_id, tax_eligible, version, created_at, undone_at) in rows:
        if version != NORMALIZATION_VERSION:
            raise UnknownNormalization(
                f"income source {source_id} uses normalization version {version}, which this "
                "code does not know"
            )
        sources.append(IncomeSource(
            source_id, chain_id, supersedes_id,
            SourceDefinition(account_id, name, kind, text, tolerance_days, amount_tolerance,
                             member_id, bool(tax_eligible), version),
            tuple(terms_by_chain[chain_id]), created_at, undone_at,
            superseded_by.get(source_id)))
    return tuple(sources)


def applying_sources(conn: sqlite3.Connection) -> tuple[IncomeSource, ...]:
    """The newest active source of every chain."""
    return tuple(source for source in load_sources(conn) if source.applies)


def load_deposit_facts(conn: sqlite3.Connection, account_ids) -> tuple[DepositFacts, ...]:
    """Every deposit of the accounts that is in D-056's income group or unclassified, with no
    transfer confirmed: the only money in a source can reach or list as a possible paycheck."""
    found = []
    for (transaction_id, account_id, amount_cents, description, reporting_date,
         financial_type) in conn.execute(
        f"""SELECT entry.id, entry.account_id,
                   COALESCE(amount_fix.corrected_amount_cents, entry.amount_cents),
                   COALESCE(description_fix.corrected_text, entry.description),
                   COALESCE(date_fix.corrected_text, entry.transaction_date,
                            posting_fix.corrected_text, entry.posting_date),
                   kind.financial_type
            FROM ledger_transaction entry
            LEFT JOIN transaction_classification kind
                ON kind.transaction_id = entry.id AND kind.state = 'applied'
            LEFT JOIN transaction_correction amount_fix
                ON amount_fix.transaction_id = entry.id AND amount_fix.field = 'amount'
               AND amount_fix.state = 'applied'
            LEFT JOIN transaction_correction description_fix
                ON description_fix.transaction_id = entry.id
               AND description_fix.field = 'description' AND description_fix.state = 'applied'
            LEFT JOIN transaction_correction date_fix
                ON date_fix.transaction_id = entry.id
               AND date_fix.field = 'transaction_date' AND date_fix.state = 'applied'
            LEFT JOIN transaction_correction posting_fix
                ON posting_fix.transaction_id = entry.id
               AND posting_fix.field = 'posting_date' AND posting_fix.state = 'applied'
            WHERE entry.account_id IN (SELECT value FROM json_each(?))
              AND (kind.financial_type IS NULL OR kind.financial_type = 'income')
              AND NOT ({CONFIRMED_TRANSFER_SQL})
            ORDER BY entry.id""",
        (json.dumps(sorted(account_ids)),),
    ):
        if amount_cents > 0:
            found.append(DepositFacts(
                transaction_id, account_id, amount_cents,
                None if description is None else normalized_text(description), reporting_date,
                financial_type == "income"))
    return tuple(found)


def write_income_source_effects(conn: sqlite3.Connection) -> None:
    """Rewrite every source's outcome. The caller holds the transaction, and types, transfer
    effects and corrections must already be final. A ledger with no applying source keeps no
    rows."""
    conn.execute("DELETE FROM transaction_income_source")
    sources = applying_sources(conn)
    if not sources:
        return
    facts = load_deposit_facts(conn, {source.definition.account_id for source in sources})
    conn.executemany(
        """INSERT INTO transaction_income_source (transaction_id, source_id, state, nominal_date)
           VALUES (?, ?, ?, ?)""",
        [(outcome.transaction_id, outcome.source_id, outcome.state, outcome.nominal_date)
         for _, outcome in sorted(source_outcomes(sources, facts).items())],
    )
