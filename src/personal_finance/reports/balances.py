"""Balance observations, their undo token, and statement reconciliation (D-057, recommendations 2
to 5).

Everything here reads the ledger and nothing writes to it. An observation is never transaction
evidence: nothing here is read by derivation, matching or any other token.
"""

import hashlib
import json
import sqlite3
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, timedelta

from personal_finance.reconcile.coverage_in_effect import (
    complete_coverage_by_basis,
    spans_cover_every_day,
)
from personal_finance.reconcile.supersession import STATE_ACTIVE, STATE_UNDONE

# Bump whenever the material below changes, so an old token can never appear current.
OBSERVATION_REVISION_VERSION = 1

# Accounts that owe money. Their observations are stated as an amount owed and stored negated, in
# the ledger's sign convention (D-003).
LIABILITY_ACCOUNT_TYPES = ("credit_card", "loan")


@dataclass(frozen=True)
class StoredObservation:
    observation_id: str
    account_id: str
    account_name: str
    account_type: str
    observed_on: str
    # In the ledger's sign convention: what a card or loan owes is negative.
    balance_cents: int
    created_at: str
    state: str
    undone_at: str | None

    @property
    def states_owed(self) -> bool:
        return self.account_type in LIABILITY_ACCOUNT_TYPES


_OBSERVATIONS = """
    SELECT observation.id, observation.account_id, account.display_name, account.account_type,
           observation.observed_on, observation.balance_cents, observation.created_at,
           undone.created_at
    FROM balance_observation observation
    JOIN account ON account.id = observation.account_id
    LEFT JOIN balance_observation_event undone
        ON undone.balance_observation_id = observation.id AND undone.event = 'undone'
"""


def _observation_of(row) -> StoredObservation:
    *values, undone_at = row
    return StoredObservation(*values, STATE_UNDONE if undone_at else STATE_ACTIVE, undone_at)


def list_observations(conn: sqlite3.Connection,
                      account_id: str | None = None) -> list[StoredObservation]:
    """Every observation, active or undone, by account, day and time made."""
    return [_observation_of(row) for row in conn.execute(
        _OBSERVATIONS + """ WHERE :account IS NULL OR observation.account_id = :account
                            ORDER BY account.display_name, observation.observed_on,
                                     observation.created_at, observation.id""",
        {"account": account_id},
    )]


def load_observation(conn: sqlite3.Connection, observation_id: str) -> StoredObservation | None:
    row = conn.execute(_OBSERVATIONS + " WHERE observation.id = ?", (observation_id,)).fetchone()
    return None if row is None else _observation_of(row)


def active_observations(conn: sqlite3.Connection, account_id: str) -> list[StoredObservation]:
    """The account's active observations, one per day, in day order."""
    return [observation for observation in list_observations(conn, account_id)
            if observation.state == STATE_ACTIVE]


def observation_revision(conn: sqlite3.Connection, observation: StoredObservation) -> str:
    """The undo token: the observation's day and balance, and those of the active observations
    either side of it, whose intervals undoing it joins into one.

    Undoing an observation changes nothing else, so neither transactions nor coverage reach it, and
    it needs no current account (D-057, recommendation 3). Days and amounts only, never generated
    IDs, so equal observations give equal tokens in two ledgers.
    """
    days = [(other.observed_on, other.balance_cents)
            for other in active_observations(conn, observation.account_id)
            if other.observation_id != observation.observation_id]
    position = bisect_left(days, (observation.observed_on,))
    material = {
        "observed": [observation.observed_on, observation.balance_cents],
        "earlier": list(days[position - 1]) if position > 0 else None,
        "later": list(days[position]) if position < len(days) else None,
    }
    text = json.dumps(material, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"b{OBSERVATION_REVISION_VERSION}-{digest}"


@dataclass
class Counted:
    transactions: int = 0
    cents: int = 0

    def add(self, cents: int) -> None:
        self.transactions += 1
        self.cents += cents


@dataclass
class BalanceInterval:
    """From the end of the opening observation's day through the end of the closing one's."""

    opening: StoredObservation
    closing: StoredObservation
    # Complete posting-basis coverage spans every day after the opening day through the closing day.
    covered: bool
    # Every transaction placed here but pending ones, which a posted balance leaves out.
    activity: Counted = field(default_factory=Counted)
    pending_left_out: Counted = field(default_factory=Counted)
    # Within the activity: transactions of unknown status, and those with no posting date, placed by
    # their transaction date.
    unknown_status: Counted = field(default_factory=Counted)
    without_posting_date: Counted = field(default_factory=Counted)
    open_review_items: set[str] = field(default_factory=set)
    transactions_in_open_review_items: int = 0

    @property
    def expected_closing_cents(self) -> int:
        return self.opening.balance_cents + self.activity.cents

    @property
    def difference_cents(self) -> int:
        """The observed closing balance less the expected one. Zero is agreement."""
        return self.closing.balance_cents - self.expected_closing_cents


@dataclass(frozen=True)
class BalanceCheck:
    observations: tuple[StoredObservation, ...]
    intervals: tuple[BalanceInterval, ...]
    # Rows of the account that are no transaction, so no interval counts them (D-050).
    unresolved_records: int


def check_balances(conn: sqlite3.Connection, account_id: str) -> BalanceCheck:
    """Compare each pair of consecutive active observations of one account (D-057,
    recommendation 4).

    A transaction is placed on its effective posting date, else its effective transaction date, and
    counted in the interval whose closing day is that date or the first after it. Effective amounts
    and dates are corrected values where they apply (D-049). Types, transfers and classifications do
    not enter it. Agreement is evidence only: nothing here declares coverage or changes a total.
    """
    observations = active_observations(conn, account_id)
    posting_spans = complete_coverage_by_basis(conn, account_id).get("posting", [])
    intervals = []
    for opening, closing in zip(observations, observations[1:]):
        first_day = date.fromisoformat(opening.observed_on) + timedelta(days=1)
        last_day = date.fromisoformat(closing.observed_on)
        days = (first_day + timedelta(days=offset)
                for offset in range((last_day - first_day).days + 1))
        intervals.append(BalanceInterval(opening, closing, spans_cover_every_day(days, posting_spans)))

    closing_days = [observation.observed_on for observation in observations]
    review_items_by_transaction = {}
    for transaction_id, item_id in conn.execute(
        """SELECT subject.transaction_id, issue.id
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           JOIN ledger_transaction entry ON entry.id = subject.transaction_id
           WHERE issue.status = 'open' AND entry.account_id = ?""",
        (account_id,),
    ):
        review_items_by_transaction.setdefault(transaction_id, set()).add(item_id)

    for transaction_id, cents, posting_date, transaction_date, status in conn.execute(
        """SELECT entry.id, COALESCE(amount_fix.corrected_amount_cents, entry.amount_cents),
                  COALESCE(posting_fix.corrected_text, entry.posting_date),
                  COALESCE(date_fix.corrected_text, entry.transaction_date),
                  entry.settlement_status
           FROM ledger_transaction entry
           LEFT JOIN transaction_correction amount_fix
               ON amount_fix.transaction_id = entry.id AND amount_fix.field = 'amount'
              AND amount_fix.state = 'applied'
           LEFT JOIN transaction_correction posting_fix
               ON posting_fix.transaction_id = entry.id AND posting_fix.field = 'posting_date'
              AND posting_fix.state = 'applied'
           LEFT JOIN transaction_correction date_fix
               ON date_fix.transaction_id = entry.id AND date_fix.field = 'transaction_date'
              AND date_fix.state = 'applied'
           WHERE entry.account_id = ?""",
        (account_id,),
    ):
        # Interval i runs after closing_days[i] through closing_days[i + 1].
        position = bisect_left(closing_days, posting_date or transaction_date)
        if not 0 < position < len(closing_days):
            continue
        interval = intervals[position - 1]
        if transaction_id in review_items_by_transaction:
            interval.open_review_items |= review_items_by_transaction[transaction_id]
            interval.transactions_in_open_review_items += 1
        if status == "pending":
            interval.pending_left_out.add(cents)
            continue
        interval.activity.add(cents)
        if status == "unknown":
            interval.unknown_status.add(cents)
        if posting_date is None:
            interval.without_posting_date.add(cents)

    (unresolved,) = conn.execute(
        """SELECT COUNT(*)
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           JOIN source_record record ON record.id = subject.source_record_id
           WHERE issue.kind = 'unresolved_record' AND issue.status = 'open'
             AND record.account_id = ?""",
        (account_id,),
    ).fetchone()
    return BalanceCheck(tuple(observations), tuple(intervals), unresolved)
