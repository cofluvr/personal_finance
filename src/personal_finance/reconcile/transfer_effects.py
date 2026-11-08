"""Which transfer matches apply, and which pairs are candidates. See decisions.md D-054.

Each account derives alone, and matching never reads anything here. A match is stated by a person
over two transactions of two accounts, and its outcome is computed afterwards from both accounts'
memberships, effective amounts and applied types. It is written to the derived
transfer_match_effect table for the whole ledger, in the caller's database transaction, wherever
classifications are written.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from personal_finance.reconcile.classification_effects import PAID_ACCOUNT_TYPES_BY_TYPE

# The types a person states for a movement between their own accounts (D-054).
TRANSFER_TYPES = ("transfer", "card_payment", "loan_payment", "investment_contribution")
# How far apart the two sides' dates may be, on any date of either. A heuristic, as D-031's window
# is, and never stored, because candidates are not.
TRANSFER_DATE_WINDOW_DAYS = 5

OUTFLOW = "outflow"
INFLOW = "inflow"

MATCH_APPLIED = "applied"
MATCH_BASIS_CHANGED = "basis_changed"
MATCH_CONFLICT = "conflict"
MATCH_AMOUNTS_DIFFER = "amounts_differ"
MATCH_TYPE_DIFFERS = "type_differs"

# Why a pair is not a candidate, in the order checked.
PAIR_SAME_ACCOUNT = "same_account"
PAIR_ALREADY_MATCHED = "already_matched"
PAIR_AMOUNTS_DO_NOT_OFFSET = "amounts_do_not_offset"
PAIR_NO_TRANSFER_TYPE = "no_transfer_type"
PAIR_TYPE_DOES_NOT_FIT = "type_does_not_fit"
PAIR_DATES_TOO_FAR = "dates_too_far"


@dataclass(frozen=True)
class ActiveMatch:
    match_id: str
    outflow_record_ids: frozenset[str]
    inflow_record_ids: frozenset[str]


@dataclass(frozen=True)
class MatchEffect:
    state: str
    # The two transactions it joins while it applies, else None.
    outflow_transaction_id: str | None
    inflow_transaction_id: str | None


@dataclass(frozen=True)
class TransactionFacts:
    """What a match's outcome and a candidate read of one live transaction."""

    transaction_id: str
    account_id: str
    account_type: str
    # A corrected value where one applies, else the source value (D-049).
    amount_cents: int
    dates: tuple[date, ...]
    # The type that applies, None while unclassified (D-053).
    financial_type: str | None
    # Whether it holds a record bound by an active match.
    matched: bool


def types_fit_pair(financial_types, account_types) -> bool:
    """Every applied type is a transfer kind, and one other than transfer pays one of the two
    accounts: a card payment needs a credit card, and so on (D-054)."""
    for financial_type in financial_types:
        if financial_type is None:
            continue
        if financial_type not in TRANSFER_TYPES:
            return False
        paid = PAID_ACCOUNT_TYPES_BY_TYPE.get(financial_type)
        if paid is not None and not paid.intersection(account_types):
            return False
    return True


def pair_refusal(one: TransactionFacts, other: TransactionFacts) -> str | None:
    """Why two transactions are not a transfer candidate, or None if they are."""
    if one.account_id == other.account_id:
        return PAIR_SAME_ACCOUNT
    if one.matched or other.matched:
        return PAIR_ALREADY_MATCHED
    if one.amount_cents == 0 or one.amount_cents != -other.amount_cents:
        return PAIR_AMOUNTS_DO_NOT_OFFSET
    if not {one.financial_type, other.financial_type}.intersection(TRANSFER_TYPES):
        return PAIR_NO_TRANSFER_TYPE
    if not types_fit_pair((one.financial_type, other.financial_type),
                          (one.account_type, other.account_type)):
        return PAIR_TYPE_DOES_NOT_FIT
    if not any(abs((mine - theirs).days) <= TRANSFER_DATE_WINDOW_DAYS
               for mine in one.dates for theirs in other.dates):
        return PAIR_DATES_TOO_FAR
    return None


_ACTIVE_BOUND = """
    SELECT bound.match_id, bound.side, bound.source_record_id
    FROM transfer_match_record bound
    WHERE NOT EXISTS (SELECT 1 FROM transfer_match_event undone
                      WHERE undone.match_id = bound.match_id AND undone.event = 'undone')"""

_FACTS = """
    SELECT entry.id, entry.account_id, account.account_type,
           COALESCE(amount_fix.corrected_amount_cents, entry.amount_cents),
           COALESCE(transaction_date_fix.corrected_text, entry.transaction_date),
           COALESCE(posting_date_fix.corrected_text, entry.posting_date),
           kind.financial_type,
           EXISTS (SELECT 1 FROM transaction_source link
                   JOIN transfer_match_record bound ON bound.source_record_id = link.source_record_id
                   WHERE link.transaction_id = entry.id
                     AND NOT EXISTS (SELECT 1 FROM transfer_match_event undone
                                     WHERE undone.match_id = bound.match_id
                                       AND undone.event = 'undone'))
    FROM ledger_transaction entry
    JOIN account ON account.id = entry.account_id
    LEFT JOIN transaction_correction amount_fix
        ON amount_fix.transaction_id = entry.id AND amount_fix.field = 'amount'
       AND amount_fix.state = 'applied'
    LEFT JOIN transaction_correction transaction_date_fix
        ON transaction_date_fix.transaction_id = entry.id
       AND transaction_date_fix.field = 'transaction_date' AND transaction_date_fix.state = 'applied'
    LEFT JOIN transaction_correction posting_date_fix
        ON posting_date_fix.transaction_id = entry.id
       AND posting_date_fix.field = 'posting_date' AND posting_date_fix.state = 'applied'
    LEFT JOIN transaction_classification kind
        ON kind.transaction_id = entry.id AND kind.state = 'applied'"""


def _facts_of(row) -> TransactionFacts:
    transaction_id, account_id, account_type, amount, transaction_date, posting_date, kind, matched = row
    dates = tuple(date.fromisoformat(value) for value in {transaction_date, posting_date} if value)
    return TransactionFacts(transaction_id, account_id, account_type, amount, tuple(sorted(dates)),
                            kind, bool(matched))


def transaction_facts(conn: sqlite3.Connection, transaction_ids) -> dict[str, TransactionFacts]:
    """The facts of the named live transactions. Others are left out."""
    wanted = sorted(set(transaction_ids))
    if not wanted:
        return {}
    marks = ", ".join("?" for _ in wanted)
    return {facts.transaction_id: facts for facts in map(
        _facts_of, conn.execute(_FACTS + f" WHERE entry.id IN ({marks})", wanted))}


def load_active_matches(
    conn: sqlite3.Connection, treated_as_undone: str | None = None
) -> tuple[ActiveMatch, ...]:
    """Every active match of the ledger, with the records each side binds."""
    record_ids_by_match_and_side = defaultdict(set)
    for match_id, side, record_id in conn.execute(_ACTIVE_BOUND):
        if match_id != treated_as_undone:
            record_ids_by_match_and_side[match_id, side].add(record_id)
    return tuple(
        ActiveMatch(match_id, frozenset(record_ids_by_match_and_side[match_id, OUTFLOW]),
                    frozenset(record_ids_by_match_and_side[match_id, INFLOW]))
        for match_id in sorted({match_id for match_id, _ in record_ids_by_match_and_side})
    )


def effective_matches(active_matches, transaction_by_record_id,
                      facts_by_transaction) -> dict[str, MatchEffect]:
    """The outcome of every active match, keyed by match.

    A side's records must sit in one transaction, no transaction may hold records of two active
    matches, the amounts must still offset exactly with money leaving the outflow side, and every
    applied type must fit the pair. The first rule broken names the state (D-054).
    """
    holding_by_match = {}
    matches_by_transaction = defaultdict(set)
    for match in active_matches:
        sides = tuple({transaction_by_record_id.get(record) for record in record_ids}
                      for record_ids in (match.outflow_record_ids, match.inflow_record_ids))
        holding_by_match[match.match_id] = sides
        for transaction in set().union(*sides) - {None}:
            matches_by_transaction[transaction].add(match.match_id)

    outcome = {}
    for match_id, (outflow, inflow) in holding_by_match.items():
        if len(outflow) != 1 or len(inflow) != 1 or None in outflow | inflow:
            outcome[match_id] = MatchEffect(MATCH_BASIS_CHANGED, None, None)
            continue
        if any(len(matches_by_transaction[transaction]) > 1 for transaction in outflow | inflow):
            outcome[match_id] = MatchEffect(MATCH_CONFLICT, None, None)
            continue
        (outflow_id,), (inflow_id,) = outflow, inflow
        out_facts, in_facts = facts_by_transaction[outflow_id], facts_by_transaction[inflow_id]
        if out_facts.amount_cents >= 0 or out_facts.amount_cents != -in_facts.amount_cents:
            outcome[match_id] = MatchEffect(MATCH_AMOUNTS_DIFFER, None, None)
        elif not types_fit_pair((out_facts.financial_type, in_facts.financial_type),
                                (out_facts.account_type, in_facts.account_type)):
            outcome[match_id] = MatchEffect(MATCH_TYPE_DIFFERS, None, None)
        else:
            outcome[match_id] = MatchEffect(MATCH_APPLIED, outflow_id, inflow_id)
    return outcome


def bound_transaction_by_record_id(conn: sqlite3.Connection) -> dict[str, str]:
    """The transaction holding each record bound by any match."""
    return dict(conn.execute(
        """SELECT DISTINCT link.source_record_id, link.transaction_id
           FROM transfer_match_record bound
           JOIN transaction_source link ON link.source_record_id = bound.source_record_id"""
    ))


def current_match_effects(
    conn: sqlite3.Connection, treated_as_undone: str | None = None
) -> dict[str, MatchEffect]:
    membership = bound_transaction_by_record_id(conn)
    return effective_matches(load_active_matches(conn, treated_as_undone), membership,
                             transaction_facts(conn, membership.values()))


def write_transfer_effects(conn: sqlite3.Connection) -> None:
    """Rewrite the ledger's derived rows from current memberships, corrections and
    classifications. The caller holds the transaction, and all three must already be final."""
    effects = current_match_effects(conn)
    conn.execute("DELETE FROM transfer_match_effect")
    conn.executemany(
        """INSERT INTO transfer_match_effect (match_id, state, outflow_transaction_id,
                                              inflow_transaction_id)
           VALUES (?, ?, ?, ?)""",
        [(match_id, effect.state, effect.outflow_transaction_id, effect.inflow_transaction_id)
         for match_id, effect in sorted(effects.items())],
    )


def unsettled_matches(conn: sqlite3.Connection) -> frozenset:
    """Active matches that do not apply, with their state. Match IDs are stable, so they serve."""
    return frozenset(conn.execute(
        "SELECT match_id, state FROM transfer_match_effect WHERE state <> 'applied'"
    ))


@dataclass(frozen=True)
class TransferCandidate:
    outflow: TransactionFacts
    inflow: TransactionFacts


def transfer_candidates(conn: sqlite3.Connection,
                        account_id: str | None = None) -> list[TransferCandidate]:
    """Every candidate pair, or those with a side in one account, computed now and never stored.

    Pairs are found from transactions of a transfer kind, among transactions of the exactly
    opposite amount, so many equal amounts make this quadratic.
    """
    every = [_facts_of(row) for row in conn.execute(_FACTS)]
    by_amount = defaultdict(list)
    for facts in every:
        if not facts.matched and facts.amount_cents:
            by_amount[facts.amount_cents].append(facts)
    pairs = {}
    for facts in every:
        if facts.financial_type not in TRANSFER_TYPES or facts.matched:
            continue
        for other in by_amount.get(-facts.amount_cents, ()):
            if pair_refusal(facts, other) is None:
                outflow, inflow = (facts, other) if facts.amount_cents < 0 else (other, facts)
                pairs[outflow.transaction_id, inflow.transaction_id] = TransferCandidate(outflow,
                                                                                         inflow)
    return [
        candidate for _, candidate in sorted(pairs.items())
        if account_id is None or account_id in (candidate.outflow.account_id,
                                                candidate.inflow.account_id)
    ]
