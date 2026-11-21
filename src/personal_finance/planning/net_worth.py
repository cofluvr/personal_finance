"""Net worth from balance observations, and the links that keep an aggregate loan and its
subaccounts from counting twice (D-071 points 1 and 2).

Each account is valued at its latest balance observation on or before as_of (D-057), in the
ledger's sign convention, so what is owed is negative. An account with none is not valued, never
zero. A link puts a loan subaccount under an aggregate loan account, one level deep, one aggregate
each, written under one write lock with its al1 token, changing no ledger table (G1). Nothing here
reads the clock: as_of is always an argument (G7).
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date

from personal_finance.planning.entries import in_one_write, refuse_unless_revision
from personal_finance.planning.funds import Observation, latest_observation
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reports.category_rule_evidence import digest

# Bump whenever the material below changes, so an old token can never appear current.
LINK_REVISION_VERSION = 1

LINK = "link"
UNLINK = "unlink"
# Valuations further apart than this, or older than this at as_of, are disclosed (point 1).
MIXED_DATE_DAYS = 31

NOT_A_LOAN = "{account} is not a loan account: only loans link. Nothing was changed."
LINK_TO_ITSELF = "an account cannot be its own aggregate. Nothing was changed."
AGGREGATE_IS_SUBACCOUNT = (
    "{account} is itself a subaccount of {aggregate}: links are one level deep. Nothing was "
    "changed."
)
SUBACCOUNT_IS_AGGREGATE = (
    "{account} is the aggregate of {subaccounts}: links are one level deep. Nothing was changed."
)
ALREADY_LINKED = (
    "{account} is a subaccount of {aggregate} already, and has one aggregate. Unlink it first. "
    "Nothing was changed."
)
NOT_LINKED = "{account} is not a subaccount of any aggregate. Nothing was changed."
STALE_LINK_REVISION = (
    "this revision does not match the aggregate's links and observations as they are now. "
    "Nothing was changed. Run account links and check it again."
)

# How an account counts toward net worth.
COUNTED = "counted"
NOT_VALUED = "not valued"
# A subaccount whose aggregate's own observation is counted instead.
AGGREGATE_VALUED = "not counted: aggregate valued"
# A subaccount observed while its aggregate is not, and another subaccount is not: the debt cannot
# be counted whole, so none of it is.
AGGREGATE_NOT_VALUED = "not counted: aggregate not valued"
# An aggregate whose subaccounts are counted instead.
SUBACCOUNTS_VALUED = "not counted: subaccounts valued"


@dataclass(frozen=True)
class Link:
    link_id: str
    subaccount_id: str
    aggregate_id: str


@dataclass(frozen=True)
class Valuation:
    account_id: str
    name: str
    account_type: str
    observation: Observation | None
    how: str

    @property
    def counted_cents(self) -> int:
        return self.observation.balance_cents if self.how == COUNTED else 0


def load_links(conn: sqlite3.Connection) -> tuple[Link, ...]:
    """Every active link, by subaccount."""
    return tuple(Link(*row) for row in conn.execute(
        """SELECT link.id, link.subaccount_id, link.aggregate_id FROM account_link link
           WHERE NOT EXISTS (SELECT 1 FROM account_link_event undone
                             WHERE undone.link_id = link.id AND undone.event = 'undone')
           ORDER BY link.subaccount_id"""))


def counting(observations: dict[str, Observation | None], links) -> dict[str, str]:
    """How each account counts (point 2), pure. Accounts no link reaches count where valued. For
    each aggregate: when every subaccount is observed on or after the aggregate's latest
    observation, the subaccounts count and the aggregate does not; otherwise the aggregate counts
    and its subaccounts do not; an aggregate with no observation counts its subaccounts if all are
    valued, and is otherwise not valued with them. Never both."""
    how = {account: COUNTED if observed is not None else NOT_VALUED
           for account, observed in observations.items()}
    subaccounts_of = {}
    for link in links:
        subaccounts_of.setdefault(link.aggregate_id, []).append(link.subaccount_id)
    for aggregate, subaccounts in subaccounts_of.items():
        own = observations[aggregate]
        parts = [observations[subaccount] for subaccount in subaccounts]
        all_valued = all(part is not None for part in parts)
        if all_valued and (own is None or all(part.observed_on >= own.observed_on
                                              for part in parts)):
            how[aggregate] = SUBACCOUNTS_VALUED
            continue
        for subaccount in subaccounts:
            if own is not None:
                how[subaccount] = AGGREGATE_VALUED
            elif observations[subaccount] is not None:
                how[subaccount] = AGGREGATE_NOT_VALUED
        if own is None:
            how[aggregate] = NOT_VALUED
    return how


def valuations(conn: sqlite3.Connection, as_of: str) -> tuple[Valuation, ...]:
    """Every account's valuation as of a date, by name."""
    accounts = conn.execute(
        "SELECT id, display_name, account_type FROM account ORDER BY display_name").fetchall()
    observations = {account_id: latest_observation(conn, account_id, as_of)
                    for account_id, _, _ in accounts}
    how = counting(observations, load_links(conn))
    return tuple(Valuation(account_id, name, account_type, observations[account_id],
                           how[account_id])
                 for account_id, name, account_type in accounts)


def mixed_dates(valued, as_of: str) -> tuple[str, ...]:
    """The counted accounts behind the mixed-date warning: every one, when the counted
    valuations span more than 31 days, else those observed more than 31 days before as_of."""
    counted = [valuation for valuation in valued if valuation.how == COUNTED]
    if not counted:
        return ()
    days = [date.fromisoformat(valuation.observation.observed_on) for valuation in counted]
    if (max(days) - min(days)).days > MIXED_DATE_DAYS:
        return tuple(valuation.name for valuation in counted)
    today = date.fromisoformat(as_of)
    return tuple(valuation.name for valuation, day in zip(counted, days, strict=True)
                 if (today - day).days > MIXED_DATE_DAYS)


# Tokens and writes.

def link_revision(conn: sqlite3.Connection, operation: str, aggregate_id: str,
                  subaccount_id: str | None = None) -> str:
    """al1 covers the operation, the aggregate and, to unlink, the subaccount, and the latest
    observation of the aggregate and of each account linked to it, which names its active links
    (D-071 point 8). The subaccount typed to link is checked under the write lock."""
    linked = sorted(link.subaccount_id for link in load_links(conn)
                    if link.aggregate_id == aggregate_id)
    observed = {}
    for account_id in (aggregate_id, *linked):
        found = latest_observation(conn, account_id, "9999-12-31")
        observed[account_id] = None if found is None else [found.observed_on,
                                                            found.balance_cents]
    material = {"operation": operation, "aggregate": aggregate_id, "observations": observed}
    if subaccount_id is not None:
        material["subaccount"] = subaccount_id
    return f"al{LINK_REVISION_VERSION}-{digest(material)}"


def account_row(conn, account_id):
    return conn.execute("SELECT display_name, account_type FROM account WHERE id = ?",
                        (account_id,)).fetchone()


def link_account(conn: sqlite3.Connection, subaccount_id: str, aggregate_id: str,
                 revision: str) -> str:
    """Link a loan subaccount under an aggregate loan account, or refuse and change nothing."""
    return in_one_write(conn, lambda: _link(conn, subaccount_id, aggregate_id, revision))


def _link(conn, subaccount_id, aggregate_id, revision) -> str:
    names = {}
    for account_id in (subaccount_id, aggregate_id):
        name, account_type = account_row(conn, account_id)
        names[account_id] = name
        if account_type != "loan":
            raise DecisionRefused(NOT_A_LOAN.format(account=name))
    if subaccount_id == aggregate_id:
        raise DecisionRefused(LINK_TO_ITSELF)
    links = load_links(conn)
    aggregate_of = {link.subaccount_id: link.aggregate_id for link in links}
    if aggregate_id in aggregate_of:
        raise DecisionRefused(AGGREGATE_IS_SUBACCOUNT.format(
            account=names[aggregate_id], aggregate=account_row(conn,
                                                               aggregate_of[aggregate_id])[0]))
    if subaccount_id in aggregate_of:
        raise DecisionRefused(ALREADY_LINKED.format(
            account=names[subaccount_id],
            aggregate=account_row(conn, aggregate_of[subaccount_id])[0]))
    under = sorted(account_row(conn, link.subaccount_id)[0] for link in links
                   if link.aggregate_id == subaccount_id)
    if under:
        raise DecisionRefused(SUBACCOUNT_IS_AGGREGATE.format(account=names[subaccount_id],
                                                             subaccounts=", ".join(under)))
    refuse_unless_revision(link_revision(conn, LINK, aggregate_id), revision,
                           STALE_LINK_REVISION)
    link_id = str(uuid.uuid4())
    conn.execute("INSERT INTO account_link (id, subaccount_id, aggregate_id) VALUES (?, ?, ?)",
                 (link_id, subaccount_id, aggregate_id))
    conn.execute("INSERT INTO account_link_event (link_id, event) VALUES (?, 'made')", (link_id,))
    return link_id


def unlink_account(conn: sqlite3.Connection, subaccount_id: str, revision: str) -> Link:
    """Stop a subaccount's link applying, keeping it on record, or refuse and change nothing."""
    return in_one_write(conn, lambda: _unlink(conn, subaccount_id, revision))


def _unlink(conn, subaccount_id, revision) -> Link:
    link = next((link for link in load_links(conn) if link.subaccount_id == subaccount_id), None)
    if link is None:
        raise DecisionRefused(NOT_LINKED.format(account=account_row(conn, subaccount_id)[0]))
    refuse_unless_revision(link_revision(conn, UNLINK, link.aggregate_id, subaccount_id),
                           revision, STALE_LINK_REVISION)
    conn.execute("INSERT INTO account_link_event (link_id, event) VALUES (?, 'undone')",
                 (link.link_id,))
    return link
