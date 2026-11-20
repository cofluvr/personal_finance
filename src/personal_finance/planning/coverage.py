"""Coverage links, the explicit no-double-reservation rule, and the look-alikes they clear (D-072
point 2).

A link says one recurring obligation is the payment of a loan's schedule, or the purchase a
reserve saves for. It applies to the obligation's chain, so a supersession keeps it, and is undo
then set (G4). Each chain covers at most one thing, and each loan or reserve is covered by at most
one link, both checked under the write lock with the ob1 token's `covers` or `uncover` operation.
No ledger table changes (G1).

Without a link, a fixed obligation that looks like a loan's next payment or a reserve's next due
amount gives a possible double reservation. It is a warning only: nothing is ever linked for the
person. Nothing here reads the clock (G7).
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from personal_finance.planning.entries import (
    in_one_write,
    lookup_entry,
    refuse_unless_newest,
    refuse_unless_revision,
)
from personal_finance.planning.funds import (
    DUE,
    RESERVE,
    find_active_fund,
    load_funds,
    next_due_date,
)
from personal_finance.planning.loans import load_loan_terms
from personal_finance.planning.loans import next_due_date as next_loan_due_date
from personal_finance.planning.obligation_effects import FIXED, load_obligations
from personal_finance.planning.obligations import OBLIGATION_REFUSALS
from personal_finance.planning.schedules import scheduled_dates
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reports.obligation_evidence import obligation_material, revision_of

COVERS = "covers"
UNCOVER = "uncover"

LOAN = "loan"
FUND = "reserve"

# A look-alike's dates may differ by this many days, both edges included (point 2).
LOOK_ALIKE_DAYS = 3

NOT_A_SCHEDULED_LOAN = (
    "{account} is not a loan account with loan terms: only such a loan, with its scheduled "
    "payment, is covered. Nothing was changed."
)
NOT_A_RESERVE = "fund {fund} is not a reserve: only a reserve is covered. Nothing was changed."
CHAIN_COVERS_ALREADY = (
    "obligation {obligation} covers {target} already, and covers one thing. Uncover it first. "
    "Nothing was changed."
)
TARGET_COVERED_ALREADY = (
    "{target} is covered by obligation {obligation} already, and is covered once. Nothing was "
    "changed."
)
NOT_COVERING = (
    "obligation {obligation} covers nothing, so there is nothing to uncover. Nothing was changed."
)
STALE_COVERAGE_REVISION = (
    "this revision does not match the obligation and its coverage as they are now. Nothing was "
    "changed. Run obligation coverage and check it again."
)


@dataclass(frozen=True)
class Coverage:
    coverage_id: str
    obligation_id: str
    chain_id: str
    # Exactly one of these.
    loan_account_id: str | None
    fund_id: str | None

    @property
    def target(self) -> tuple[str, str]:
        return (LOAN, self.loan_account_id) if self.loan_account_id else (FUND, self.fund_id)


@dataclass(frozen=True)
class LookAlike:
    """An unlinked fixed obligation whose amount and date match a loan's or reserve's."""

    obligation_id: str
    target_kind: str
    target_id: str
    target_name: str
    amount_cents: int
    target_due: str
    obligation_due: str


def load_coverages(conn: sqlite3.Connection) -> tuple[Coverage, ...]:
    """Every active link, in the order made, with its obligation's chain."""
    return tuple(Coverage(*row) for row in conn.execute(
        """SELECT coverage.id, coverage.obligation_id, obligation.chain_id,
                  coverage.loan_account_id, coverage.fund_id
           FROM obligation_coverage coverage
           JOIN recurring_obligation obligation ON obligation.id = coverage.obligation_id
           WHERE NOT EXISTS (SELECT 1 FROM obligation_coverage_event undone
                             WHERE undone.coverage_id = coverage.id AND undone.event = 'undone')
           ORDER BY coverage.created_at, coverage.id"""))


def target_words(conn: sqlite3.Connection, kind: str, target_id: str) -> str:
    if kind == LOAN:
        name = conn.execute("SELECT display_name FROM account WHERE id = ?",
                            (target_id,)).fetchone()[0]
        return f"loan {name}"
    name = conn.execute("SELECT name FROM fund WHERE id = ?", (target_id,)).fetchone()[0]
    return f"reserve {name} ({target_id})"


def coverage_revision(conn: sqlite3.Connection, operation: str, obligation) -> str:
    """ob1 covers the operation, the obligation by what it says and its ID, and its chain's active
    link, if any. The target typed to cover is checked under the write lock."""
    link = next((coverage for coverage in load_coverages(conn)
                 if coverage.chain_id == obligation.chain_id), None)
    return revision_of({"operation": operation,
                        "obligation": obligation_material(conn, obligation),
                        "obligation_id": obligation.obligation_id,
                        "coverage": None if link is None else list(link.target)})


def cover(conn: sqlite3.Connection, obligation_id: str, *, loan_account_id: str | None = None,
          fund_id: str | None = None, revision: str) -> str:
    """Link an applying obligation to the loan or reserve it pays for, or refuse and change
    nothing. Exactly one of loan_account_id and fund_id."""
    if (loan_account_id is None) == (fund_id is None):
        raise ValueError("cover takes exactly one of a loan and a reserve")
    return in_one_write(conn, lambda: _cover(conn, obligation_id, loan_account_id, fund_id,
                                             revision))


def _cover(conn, obligation_id, loan_account_id, fund_id, revision) -> str:
    obligations = load_obligations(conn)
    obligation = refuse_unless_newest(
        obligations, lookup_entry(obligations, obligation_id, OBLIGATION_REFUSALS),
        OBLIGATION_REFUSALS)
    if loan_account_id is not None:
        terms = load_loan_terms(conn).get(loan_account_id)
        # A loan's terms always hold a payment period (PAYMENT_REQUIRED).
        if terms is None or terms.account_type != "loan":
            name = conn.execute("SELECT display_name FROM account WHERE id = ?",
                                (loan_account_id,)).fetchone()[0]
            raise DecisionRefused(NOT_A_SCHEDULED_LOAN.format(account=name))
        target = (LOAN, loan_account_id)
    else:
        fund = find_active_fund(load_funds(conn), fund_id)
        if fund.kind != RESERVE:
            raise DecisionRefused(NOT_A_RESERVE.format(fund=fund_id))
        target = (FUND, fund_id)
    coverages = load_coverages(conn)
    for coverage in coverages:
        if coverage.chain_id == obligation.chain_id:
            raise DecisionRefused(CHAIN_COVERS_ALREADY.format(
                obligation=obligation_id, target=target_words(conn, *coverage.target)))
        if coverage.target == target:
            raise DecisionRefused(TARGET_COVERED_ALREADY.format(
                target=target_words(conn, *target), obligation=coverage.obligation_id))
    refuse_unless_revision(coverage_revision(conn, COVERS, obligation), revision,
                           STALE_COVERAGE_REVISION)
    coverage_id = str(uuid.uuid4())
    conn.execute("INSERT INTO obligation_coverage (id, obligation_id, loan_account_id, fund_id) "
                 "VALUES (?, ?, ?, ?)", (coverage_id, obligation_id, loan_account_id, fund_id))
    insert_coverage_event(conn, coverage_id, "made")
    return coverage_id


def insert_coverage_event(conn: sqlite3.Connection, coverage_id: str, event: str) -> None:
    conn.execute("INSERT INTO obligation_coverage_event (coverage_id, event) VALUES (?, ?)",
                 (coverage_id, event))


def uncover(conn: sqlite3.Connection, obligation_id: str, revision: str) -> Coverage:
    """Stop the link of an obligation's chain applying, keeping it on record. The obligation may
    since have been undone, so an inert link can still be taken away."""
    return in_one_write(conn, lambda: _uncover(conn, obligation_id, revision))


def _uncover(conn, obligation_id, revision) -> Coverage:
    obligation = lookup_entry(load_obligations(conn), obligation_id, OBLIGATION_REFUSALS)
    link = next((coverage for coverage in load_coverages(conn)
                 if coverage.chain_id == obligation.chain_id), None)
    if link is None:
        raise DecisionRefused(NOT_COVERING.format(obligation=obligation_id))
    refuse_unless_revision(coverage_revision(conn, UNCOVER, obligation), revision,
                           STALE_COVERAGE_REVISION)
    insert_coverage_event(conn, link.coverage_id, "undone")
    return link


# Look-alikes (point 2), read-only.

def fixed_dates_near(obligation, due: date, amount_cents: int) -> list[date]:
    """The obligation's nominal dates within LOOK_ALIKE_DAYS of due, under fixed terms whose
    range holds the amount."""
    window = timedelta(days=LOOK_ALIKE_DAYS)
    return [nominal for nominal, terms in scheduled_dates(obligation.terms, due + window)
            if abs((nominal - due).days) <= LOOK_ALIKE_DAYS
            and terms.obligation_class == FIXED
            and terms.low_cents <= amount_cents <= terms.high_cents]


def scheduled_targets(conn: sqlite3.Connection,
                      as_of: date) -> list[tuple[str, str, str, int, date]]:
    """Every loan with a scheduled payment and every active reserve started by as_of, as (kind,
    ID, name, amount, next due date on or after as_of)."""
    found = []
    for account_id, terms in load_loan_terms(conn).items():
        if terms.account_type != "loan":
            continue
        due = next_loan_due_date(terms.due_day, as_of - timedelta(days=1))
        payment = terms.payment_on(due.isoformat())
        if payment:
            found.append((LOAN, account_id, terms.account_name, payment, due))
    for fund in load_funds(conn):
        if not fund.applies or fund.kind != RESERVE:
            continue
        terms = fund.terms_on(as_of.isoformat())
        if terms is None:
            continue  # not started by as_of, so nothing is due yet (D-070's not_started)
        due = terms.due_date if terms.shape == DUE else next_due_date(terms, as_of.isoformat())
        found.append((FUND, fund.fund_id, fund.name, terms.amount_cents, date.fromisoformat(due)))
    return found


def possible_double_reservations(conn: sqlite3.Connection, as_of: date) -> tuple[LookAlike, ...]:
    """Each pair of an unlinked applying obligation and an unlinked loan or reserve whose amount
    matches and whose dates are within LOOK_ALIKE_DAYS, by obligation then target."""
    coverages = load_coverages(conn)
    linked_chains = {coverage.chain_id for coverage in coverages}
    linked_targets = {coverage.target for coverage in coverages}
    targets = [target for target in scheduled_targets(conn, as_of)
               if target[:2] not in linked_targets]
    found = []
    for obligation in load_obligations(conn):
        if not obligation.applies or obligation.chain_id in linked_chains:
            continue
        for kind, target_id, name, amount, due in targets:
            for nominal in fixed_dates_near(obligation, due, amount):
                found.append(LookAlike(obligation.obligation_id, kind, target_id, name, amount,
                                       due.isoformat(), nominal.isoformat()))
    return tuple(sorted(found, key=lambda alike: (alike.obligation_id, alike.target_kind,
                                                  alike.target_id, alike.obligation_due)))
