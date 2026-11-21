"""Recurring obligations: their nominal due dates, the spending each reaches, what each payment is
there, and fixed and discretionary spending. See decisions-m12-m21.md D-068 points 5 and 6, and
"How M12.2 was implemented".

An obligation binds no records. Its outcome is derived from the evidence held now, on every write,
so it reaches later imports in any order. A transaction is reached only when it is money out in
D-056's spending group on the obligation's account, dated no earlier than the first due date less
the date tolerance, its normalized effective description contains the obligation's normalized
text, and, where the obligation names a category, its effective category (a person's, else the
rules', D-064) is that one. Two obligations reaching one transaction leave it to neither, in
obligation_conflict, and it is then discretionary. Nothing here reads the clock.
"""

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from personal_finance.planning.schedules import (
    Cadence,
    dates_to_show,
    kept_terms,
    paired_with_dates,
    terms_in_effect,
    unpaid_state,
)
from personal_finance.reconcile.category_effects import CONFIRMED_TRANSFER_SQL, SPENDING_TYPES
from personal_finance.reconcile.category_rule_effects import (
    NORMALIZATION_VERSION,
    UnknownNormalization,
    normalized_text,
)

FIXED = "fixed"
DISCRETIONARY = "discretionary"
CLASSES = (FIXED, DISCRETIONARY)

PAID = "paid"
AMOUNT_OUT_OF_RANGE = "amount_out_of_range"
UNSCHEDULED = "unscheduled"
OBLIGATION_CONFLICT = "obligation_conflict"
MISSED = "missed"
EXPECTED = "expected"


@dataclass(frozen=True)
class ObligationTerms:
    effective_from: str
    cadence: Cadence
    anchor: str
    # The range a payment may fall in, LOW = HIGH for an exact amount, both above zero.
    low_cents: int
    high_cents: int
    obligation_class: str

    @property
    def planned_cents(self) -> int:
        """A range's planned amount is its HIGH, rounding toward protection (G8)."""
        return self.high_cents


@dataclass(frozen=True)
class ObligationDefinition:
    """What an obligation says, and never changes."""

    account_id: str
    name: str
    description_contains: str
    category_id: int | None
    tolerance_days: int
    normalization_version: int = NORMALIZATION_VERSION


@dataclass(frozen=True)
class RecurringObligation:
    obligation_id: str
    chain_id: str
    supersedes_id: str | None
    definition: ObligationDefinition
    # The chain's terms, oldest first. The first starts at the first due date.
    terms: tuple[ObligationTerms, ...]
    created_at: str | None = None
    undone_at: str | None = None
    superseded_by: str | None = None

    @property
    def entry_id(self) -> str:
        return self.obligation_id

    @property
    def applies(self) -> bool:
        return self.undone_at is None and self.superseded_by is None

    @property
    def state(self) -> str:
        if self.undone_at:
            return "undone"
        return "superseded" if self.superseded_by else "active"

    @property
    def earliest_reached(self) -> str:
        """No payment dated before this is reached."""
        first_due = date.fromisoformat(self.terms[0].anchor)
        return (first_due - timedelta(days=self.definition.tolerance_days)).isoformat()


@dataclass(frozen=True)
class PaymentFacts:
    """Money out in spending, as an obligation reads it: effective values, corrected where they
    apply."""

    transaction_id: str
    account_id: str
    # Negative: money out.
    amount_cents: int
    normalized_description: str | None
    reporting_date: str
    financial_type: str
    # A person's applied category, else the rules' applied one, else None (D-064).
    category_id: int | None

    @property
    def paid_cents(self) -> int:
        return -self.amount_cents


@dataclass(frozen=True)
class PaymentOutcome:
    transaction_id: str
    obligation_id: str
    state: str
    nominal_date: str | None
    # The class of the terms it is read under. None in obligation_conflict.
    obligation_class: str | None


@dataclass(frozen=True)
class DueOccurrence:
    """One nominal due date, as of a date."""

    nominal_date: str
    terms: ObligationTerms
    state: str
    payment: PaymentFacts | None


def matches(obligation: RecurringObligation, facts: PaymentFacts) -> bool:
    """The account, text and category an obligation reaches, whatever the payment's date."""
    definition = obligation.definition
    return (facts.account_id == definition.account_id
            and facts.normalized_description is not None
            and normalized_text(definition.description_contains) in facts.normalized_description
            and definition.category_id in (None, facts.category_id))


def reaches(obligation: RecurringObligation, facts: PaymentFacts) -> bool:
    return matches(obligation, facts) and facts.reporting_date >= obligation.earliest_reached


def obligation_outcomes(obligations, facts_list) -> dict[tuple[str, str], PaymentOutcome]:
    """The outcome on every payment an applying obligation reaches, keyed by transaction and
    obligation."""
    reached = {obligation.obligation_id: [facts for facts in facts_list
                                          if reaches(obligation, facts)]
               for obligation in obligations}
    holders = defaultdict(list)
    for obligation_id, payments in reached.items():
        for facts in payments:
            holders[facts.transaction_id].append(obligation_id)
    outcomes = {}
    for obligation in obligations:
        alone = [facts for facts in reached[obligation.obligation_id]
                 if len(holders[facts.transaction_id]) == 1]
        paired = paired_with_dates(obligation.terms, obligation.definition.tolerance_days, alone)
        for facts in reached[obligation.obligation_id]:
            key = (facts.transaction_id, obligation.obligation_id)
            if len(holders[facts.transaction_id]) > 1:
                outcomes[key] = PaymentOutcome(*key, OBLIGATION_CONFLICT, None, None)
            elif facts.transaction_id in paired:
                nominal, terms = paired[facts.transaction_id]
                within = terms.low_cents <= facts.paid_cents <= terms.high_cents
                outcomes[key] = PaymentOutcome(*key, PAID if within else AMOUNT_OUT_OF_RANGE,
                                               nominal.isoformat(), terms.obligation_class)
            else:
                terms = terms_in_effect(obligation.terms, facts.reporting_date)
                outcomes[key] = PaymentOutcome(*key, UNSCHEDULED, None, terms.obligation_class)
    return outcomes


def due_occurrences(obligation: RecurringObligation, facts_list, outcomes,
                    as_of: date) -> list[DueOccurrence]:
    """Every nominal due date through as_of, any later one a payment already met, and the next one
    still to come. missed only once the tolerance has passed as_of."""
    by_id = {facts.transaction_id: facts for facts in facts_list}
    paid = {outcome.nominal_date: outcome for (_, obligation_id), outcome in outcomes.items()
            if obligation_id == obligation.obligation_id and outcome.nominal_date is not None}
    found = []
    for nominal, terms, shown in dates_to_show(obligation.terms, paid, as_of):
        if not shown:
            continue
        text = nominal.isoformat()
        if text in paid:
            found.append(DueOccurrence(text, terms, paid[text].state,
                                       by_id[paid[text].transaction_id]))
        else:
            found.append(DueOccurrence(
                text, terms, unpaid_state(nominal, as_of, obligation.definition.tolerance_days),
                None))
    return found


def load_obligations(conn: sqlite3.Connection) -> tuple[RecurringObligation, ...]:
    """Every obligation on record with its chain's terms, in the order made."""
    terms_by_chain = defaultdict(list)
    for (chain_id, effective_from, cadence, first_day, second_day, interval_months, anchor,
         low_cents, high_cents, obligation_class) in conn.execute(
        """SELECT chain_id, effective_from, cadence, first_day, second_day, interval_months,
                  anchor, low_cents, high_cents, obligation_class
           FROM recurring_obligation_terms terms
           WHERE """ + kept_terms("recurring_obligation_terms") + """
           ORDER BY chain_id, effective_from"""
    ):
        terms_by_chain[chain_id].append(ObligationTerms(
            effective_from, Cadence(cadence, first_day, second_day, interval_months), anchor,
            low_cents, high_cents, obligation_class))
    rows = conn.execute(
        """SELECT obligation.id, obligation.chain_id, obligation.supersedes_id,
                  obligation.account_id, obligation.name, obligation.description_contains,
                  obligation.category_id, obligation.tolerance_days,
                  obligation.normalization_version, obligation.created_at, undone.created_at
           FROM recurring_obligation obligation
           LEFT JOIN recurring_obligation_event undone
               ON undone.obligation_id = obligation.id AND undone.event = 'undone'
           ORDER BY obligation.created_at, obligation.id"""
    ).fetchall()
    superseded_by = {row[2]: row[0] for row in rows if row[2] and row[10] is None}
    obligations = []
    for (obligation_id, chain_id, supersedes_id, account_id, name, text, category_id,
         tolerance_days, version, created_at, undone_at) in rows:
        if version != NORMALIZATION_VERSION:
            raise UnknownNormalization(
                f"obligation {obligation_id} uses normalization version {version}, which this "
                "code does not know"
            )
        obligations.append(RecurringObligation(
            obligation_id, chain_id, supersedes_id,
            ObligationDefinition(account_id, name, text, category_id, tolerance_days, version),
            tuple(terms_by_chain[chain_id]), created_at, undone_at,
            superseded_by.get(obligation_id)))
    return tuple(obligations)


def applying_obligations(conn: sqlite3.Connection) -> tuple[RecurringObligation, ...]:
    """The newest active obligation of every chain."""
    return tuple(obligation for obligation in load_obligations(conn) if obligation.applies)


def load_payment_facts(conn: sqlite3.Connection, account_ids) -> tuple[PaymentFacts, ...]:
    """Every transaction of the accounts that is money out in D-056's spending group: the only
    transactions an obligation can reach or a proposal can group."""
    marks = ", ".join("?" for _ in SPENDING_TYPES)
    found = []
    for (transaction_id, account_id, amount_cents, description, reporting_date, financial_type,
         category_id) in conn.execute(
        f"""SELECT entry.id, entry.account_id,
                   COALESCE(amount_fix.corrected_amount_cents, entry.amount_cents),
                   COALESCE(description_fix.corrected_text, entry.description),
                   COALESCE(date_fix.corrected_text, entry.transaction_date,
                            posting_fix.corrected_text, entry.posting_date),
                   kind.financial_type,
                   COALESCE(person.category_id, by_rules.category_id)
            FROM ledger_transaction entry
            JOIN transaction_classification kind
                ON kind.transaction_id = entry.id AND kind.state = 'applied'
               AND kind.financial_type IN ({marks})
            LEFT JOIN transaction_category person
                ON person.transaction_id = entry.id AND person.state = 'applied'
            LEFT JOIN transaction_rule_category by_rules
                ON by_rules.transaction_id = entry.id AND by_rules.state = 'applied'
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
              AND NOT ({CONFIRMED_TRANSFER_SQL})
            ORDER BY entry.id""",
        (*SPENDING_TYPES, json.dumps(sorted(account_ids))),
    ):
        if amount_cents < 0:
            found.append(PaymentFacts(
                transaction_id, account_id, amount_cents,
                None if description is None else normalized_text(description), reporting_date,
                financial_type, category_id))
    return tuple(found)


def write_obligation_effects(conn: sqlite3.Connection) -> None:
    """Rewrite every obligation's outcome. The caller holds the transaction, and types, transfer
    effects, corrections, categorizations and the rules' outcomes must already be final. A ledger
    with no applying obligation keeps no rows."""
    conn.execute("DELETE FROM transaction_obligation")
    obligations = applying_obligations(conn)
    if not obligations:
        return
    facts = load_payment_facts(conn, {obligation.definition.account_id
                                      for obligation in obligations})
    conn.executemany(
        """INSERT INTO transaction_obligation (transaction_id, obligation_id, state, nominal_date,
                                               obligation_class)
           VALUES (?, ?, ?, ?, ?)""",
        [(outcome.transaction_id, outcome.obligation_id, outcome.state, outcome.nominal_date,
          outcome.obligation_class)
         for _, outcome in sorted(obligation_outcomes(obligations, facts).items())],
    )
