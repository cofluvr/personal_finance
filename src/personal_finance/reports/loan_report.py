"""pf report loans, loan project and loan payoff (D-071 points 4 to 6, M15.2): each loan's terms,
its actual payments against its schedule, unconfirmed payments apart, projections from the latest
observation, and payoff orders side by side.

Read only. Every projected figure is labelled a projection, not lender-exact. Nothing here reads
the clock.
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from personal_finance.planning.funds import latest_observation
from personal_finance.reconcile.breakdown_effects import parsed
from personal_finance.planning.loans import (
    AVALANCHE,
    CUSTOM,
    SNOWBALL,
    DebtAtStart,
    LoanTerms,
    PayoffOutcome,
    active_plan,
    due_dates_between,
    load_loan_terms,
    next_due_date,
    payoff,
    period_state,
)

# Money confirmed into a loan account: a match's inflow there, or a one-sided transfer naming it,
# each dated by the transaction holding it.
CONFIRMED_PAYMENTS = """
    SELECT COALESCE(inflow.transaction_date, inflow.posting_date),
           COALESCE(fix.corrected_amount_cents, inflow.amount_cents)
    FROM transfer_match_effect matched
    JOIN ledger_transaction inflow ON inflow.id = matched.inflow_transaction_id
    LEFT JOIN transaction_correction fix
        ON fix.transaction_id = inflow.id AND fix.field = 'amount' AND fix.state = 'applied'
    WHERE inflow.account_id = :account
    UNION ALL
    SELECT COALESCE(outflow.transaction_date, outflow.posting_date),
           -COALESCE(fix.corrected_amount_cents, outflow.amount_cents)
    FROM one_sided_transfer_effect effect
    JOIN one_sided_transfer statement ON statement.id = effect.one_sided_transfer_id
    JOIN ledger_transaction outflow ON outflow.id = effect.transaction_id
    LEFT JOIN transaction_correction fix
        ON fix.transaction_id = outflow.id AND fix.field = 'amount' AND fix.state = 'applied'
    WHERE statement.counterpart_account_id = :account"""

# Money into a loan account no transfer confirms: listed apart, never counted.
UNCONFIRMED_ON_LOAN = """
    SELECT COUNT(*), COALESCE(SUM(entry.amount_cents), 0) FROM ledger_transaction entry
    WHERE entry.account_id = :account AND entry.amount_cents > 0
      AND COALESCE(entry.transaction_date, entry.posting_date) <= :as_of
      AND NOT EXISTS (SELECT 1 FROM transfer_match_effect matched
                      WHERE matched.inflow_transaction_id = entry.id)"""

# Loan payments typed so on any account, no transfer confirming where they went.
UNCONFIRMED_LOAN_PAYMENTS = """
    SELECT COUNT(*), COALESCE(SUM(-entry.amount_cents), 0) FROM ledger_transaction entry
    JOIN transaction_classification kind
        ON kind.transaction_id = entry.id AND kind.state = 'applied'
       AND kind.financial_type = 'loan_payment'
    WHERE entry.amount_cents < 0
      AND COALESCE(entry.transaction_date, entry.posting_date) <= :as_of
      AND NOT EXISTS (SELECT 1 FROM transfer_match_effect matched
                      WHERE matched.outflow_transaction_id = entry.id)
      AND NOT EXISTS (SELECT 1 FROM one_sided_transfer_effect effect
                      WHERE effect.transaction_id = entry.id)"""


# Applied breakdowns of payments confirmed into a loan: the interest and fees the lender stated
# (D-071 point 7). They never edit a balance.
BROKEN_DOWN_PAYMENTS = """
    SELECT divided.breakdown FROM transaction_loan_breakdown divided
    WHERE divided.state = 'applied' AND divided.transaction_id IN (
        SELECT matched.outflow_transaction_id FROM transfer_match_effect matched
        JOIN ledger_transaction inflow ON inflow.id = matched.inflow_transaction_id
        WHERE inflow.account_id = :account
        UNION
        SELECT effect.transaction_id FROM one_sided_transfer_effect effect
        JOIN one_sided_transfer statement ON statement.id = effect.one_sided_transfer_id
        WHERE statement.counterpart_account_id = :account)"""


@dataclass(frozen=True)
class DuePeriod:
    due: str
    due_cents: int
    paid_cents: int
    state: str


@dataclass(frozen=True)
class LoanView:
    terms: LoanTerms
    # The latest observation on or before as_of: (date, owed cents, positive for an amount owed).
    observed: tuple[str, int] | None
    periods: tuple[DuePeriod, ...]
    unconfirmed_count: int
    unconfirmed_cents: int
    # Payments into it a breakdown divides, and their interest and fees together.
    broken_down_count: int = 0
    broken_down_cents: int = 0


@dataclass(frozen=True)
class LoansView:
    as_of: str
    loans: tuple[LoanView, ...]
    unconfirmed_payments: tuple[int, int]


def schedule(conn: sqlite3.Connection, terms: LoanTerms, as_of: date) -> tuple[DuePeriod, ...]:
    """Every due period from the first payment period through the next due date after as_of.
    A period runs after the previous due date through this one."""
    if not terms.payments:
        return ()
    start = date.fromisoformat(terms.payments[0][0])
    # The first due date on or after the first payment period starts.
    first_due = next_due_date(terms.due_day, date.fromordinal(start.toordinal() - 1))
    dues = [first_due, *due_dates_between(terms.due_day, first_due,
                                          next_due_date(terms.due_day, as_of))]
    payments = sorted(conn.execute(CONFIRMED_PAYMENTS, {"account": terms.account_id}))
    periods = []
    previous = None
    for due in dues:
        due_text = due.isoformat()
        paid = sum(cents for day, cents in payments
                   if day is not None and day <= due_text and (previous is None or day > previous))
        amount = terms.payment_on(due_text)
        periods.append(DuePeriod(due_text, amount, paid, period_state(amount, paid, due, as_of)))
        previous = due_text
    return tuple(periods)


def owed_as_of(conn: sqlite3.Connection, account_id: str, as_of: str) -> tuple[str, int] | None:
    """The latest observation, as owed cents: positive for an amount owed."""
    found = latest_observation(conn, account_id, as_of)
    return None if found is None else (found.observed_on, -found.balance_cents)


def loans_view(conn: sqlite3.Connection, as_of: date) -> LoansView:
    text = as_of.isoformat()
    loans = []
    for terms in load_loan_terms(conn).values():
        count, cents = conn.execute(UNCONFIRMED_ON_LOAN,
                                    {"account": terms.account_id, "as_of": text}).fetchone()
        stated = [parsed(value) for (value,) in conn.execute(BROKEN_DOWN_PAYMENTS,
                                                              {"account": terms.account_id})]
        loans.append(LoanView(terms, owed_as_of(conn, terms.account_id, text),
                              schedule(conn, terms, as_of), count, cents, len(stated),
                              sum(interest + fees for interest, fees in stated)))
    return LoansView(text, tuple(loans),
                     tuple(conn.execute(UNCONFIRMED_LOAN_PAYMENTS, {"as_of": text}).fetchone()))


def debts_at(conn: sqlite3.Connection, as_of: str) -> tuple[DebtAtStart, ...]:
    """Each loan with terms and an observation by as_of, at its rate in effect then. A card is
    left out of payoff orders, and so is a loan with nothing owed."""
    found = []
    for terms in load_loan_terms(conn).values():
        observed = owed_as_of(conn, terms.account_id, as_of)
        if terms.account_type != "loan" or observed is None or observed[1] <= 0:
            continue
        rate = terms.rate_on(as_of)
        found.append(DebtAtStart(terms, observed[1], terms.rates[0][1] if rate is None else rate))
    return tuple(found)


def payoff_orders(conn: sqlite3.Connection, as_of: date, extra_cents: int,
                  order: str | None = None,
                  custom: tuple[str, ...] = ()) -> tuple[tuple[DebtAtStart, ...],
                                                         tuple[PayoffOutcome, ...]]:
    """Each order side by side: avalanche and snowball, and custom where one is named, or only
    the order asked for."""
    debts = debts_at(conn, as_of.isoformat())
    plan = active_plan(conn)
    if not custom and plan is not None and plan.order_kind == CUSTOM:
        custom = tuple(account for account in plan.custom_order
                       if account in {debt.terms.account_id for debt in debts})
    orders = [order] if order else [AVALANCHE, SNOWBALL, *([CUSTOM] if custom else [])]
    return debts, tuple(payoff(debts, name, extra_cents, as_of, custom) for name in orders)
