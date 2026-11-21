"""The snapshot's content and envelope (D-075 points 1 to 3 and 6, the M19.1 slice plan).

Every section is built from the one connection given, which the caller holds in one read
transaction (point 4). Each figure is taken from the report its command prints, never computed
again. Left out by design (point 3): raw rows and cells, file names, hashes and paths, external
and record IDs, last4 and institution, source descriptions a correction replaces, and every
creation timestamp. Accounts are referenced by their index in the snapshot's account list.
"""

import sqlite3
from datetime import date, timedelta

from personal_finance.ingest.coverage import DATE_BASES
from personal_finance.planning.funds import latest_observation
from personal_finance.planning.loans import ASSUMPTIONS as LOAN_ASSUMPTIONS
from personal_finance.planning.loans import PROJECTION_LABEL, project
from personal_finance.planning.settings import household_timezone
from personal_finance.reconcile.coverage_in_effect import complete_coverage_by_basis
from personal_finance.reconcile.household_effects import (
    UNATTRIBUTED,
    attributed_transactions,
    load_household,
)
from personal_finance.reconcile.rules import DEFAULT_RULES, RULES_VERSION
from personal_finance.reports.budget_report import budget_report
from personal_finance.reports.fund_standing import funds_view
from personal_finance.reports.household import HOUSEHOLD_COLUMN, household_by_month
from personal_finance.reports.loan_report import loans_view
from personal_finance.reports.monthly import _transactions_with_unsettled_effects, monthly_report
from personal_finance.reports.net_worth_report import net_worth
from personal_finance.reports.safe_to_spend import last_covered_day, safe_to_spend
from personal_finance.snapshot.canonical import canonical_bytes, sha256_of

FORMAT = "commoncents-snapshot"
SCHEMA_VERSION = "1.0"
DEFAULT_WINDOW_DAYS = 90
LONGEST_WINDOW_DAYS = 366

ROUNDING = (
    "money is integer cents; rates are integers in millionths of a percent",
    "a spendable amount rounds down and a required amount up; loan interest rounds half-even "
    "once a month (G8)",
)
SAFE_TO_SPEND_ASSUMPTIONS = (
    "safe to spend is the lower of budget capacity and liquidity until the next paycheck "
    "(D-072 point 1)",
    "liquidity is each liquidity account's latest observation plus the activity after it, "
    "pending inflows left out (D-072 point 3)",
    "protected: tax reserve, bills and minimum debt payments, annual and irregular expenses, "
    "the checking buffer, emergency restoration, approved goals (D-072 point 4)",
)


def group(total) -> dict:
    return {"transactions": total.transactions, "out_cents": total.out_cents,
            "in_cents": total.in_cents}


def account_list(conn) -> list[tuple[str, str, str]]:
    """(ID, display name, type), by display name then ID: an account's index is its place."""
    return conn.execute("SELECT id, display_name, account_type FROM account "
                        "ORDER BY display_name, id").fetchall()


def build_content(conn: sqlite3.Connection, as_of: date,
                  window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """The snapshot as of a date, every section from this connection."""
    if not 1 <= window_days <= LONGEST_WINDOW_DAYS:
        raise ValueError("a window outside 1 to 366 days")
    text = as_of.isoformat()
    accounts = account_list(conn)
    index = {account_id: position for position, (account_id, _, _) in enumerate(accounts)}
    household = load_household(conn)
    members = {member.member_id: position for position, member in enumerate(household.members)}
    zone = household_timezone(conn)
    warnings = []
    first_day = (as_of - timedelta(days=window_days - 1)).isoformat()
    return {
        "cutoff": {"as_of": text, "accounts": freshness(conn, accounts, text)},
        "period": {"month": text[:7], "window_days": window_days, "window_first_day": first_day,
                   "window_last_day": text},
        "household": household_section(conn, household, members, index, zone),
        "accounts": [{"account_index": position, "display_name": name, "account_type": kind}
                     for position, (_, name, kind) in enumerate(accounts)],
        "months": months_section(conn, warnings),
        "budget": budget_section(conn, as_of, zone, warnings),
        "safe_to_spend": safe_to_spend_section(conn, as_of, zone, warnings),
        "funds": funds_section(conn, as_of, warnings),
        "loans": loans_section(conn, as_of, index),
        "net_worth": net_worth_section(conn, text, index),
        "transactions": transactions_section(conn, first_day, text, index, household, members),
        "warnings": sorted(warnings, key=lambda warning: (warning["kind"], warning["detail"])),
        "review": review_section(conn),
        "assumptions": [*LOAN_ASSUMPTIONS, *SAFE_TO_SPEND_ASSUMPTIONS, *ROUNDING,
                        f"matching rules version {RULES_VERSION}, fingerprint "
                        f"{DEFAULT_RULES.fingerprint()[:16]}"],
    }


def freshness(conn, accounts, as_of: str) -> list[dict]:
    """Per account: the last covered day of any kind, the last day each basis is complete
    through, the last import's UTC date, and the latest observation's date (D-072 point 7)."""
    found = []
    for position, (account_id, _, _) in enumerate(accounts):
        complete = complete_coverage_by_basis(conn, account_id)
        (imported,) = conn.execute(
            """SELECT MAX(document.imported_at) FROM source_document document
               WHERE EXISTS (SELECT 1 FROM source_record record
                             WHERE record.source_document_id = document.id
                               AND record.account_id = ?)""", (account_id,)).fetchone()
        observation = latest_observation(conn, account_id, as_of)
        found.append({
            "account_index": position,
            "last_covered_day": last_covered_day(conn, account_id),
            **{f"{basis}_complete_through": max(
                (end.isoformat() for _, end in complete.get(basis, ())), default=None)
               for basis in DATE_BASES},
            "last_import_date": imported[:10] if imported else None,
            "latest_observation_date": observation.observed_on if observation else None,
        })
    return found


def household_section(conn, household, members, index, zone) -> dict:
    share = household.share
    return {
        "timezone": None if zone is None else str(zone),
        "members": [{"member_index": position, "name": member.name}
                    for position, member in enumerate(household.members)],
        "share": None if share is None else [
            {"member_index": members[member_id], "basis_points": points}
            for member_id, points in share.parts],
        "account_defaults": sorted(
            ({"account_index": index[account_id],
              "member_index": None if default.member_id is None else members[default.member_id]}
             for account_id, default in household.defaults.items()),
            key=lambda default: default["account_index"]),
        "months": [
            {"month": month, "household": group(totals[HOUSEHOLD_COLUMN]),
             "members": [{"member_index": members[member_id], **group(totals[member_id])}
                         for member_id in sorted(members, key=members.get)
                         if member_id in totals],
             "unattributed": group(totals[UNATTRIBUTED]) if UNATTRIBUTED in totals
             else {"transactions": 0, "out_cents": 0, "in_cents": 0}}
            for month, totals in household_by_month(conn).items()],
    }


def months_section(conn, warnings) -> list[dict]:
    """report monthly's months over the full history: D-056's five groups and spending by
    category."""
    names = dict(conn.execute("SELECT id, name FROM category"))
    found = []
    for month in monthly_report(conn).months:
        groups = month.tally.result()
        found.append({
            "month": month.month, "transactions": month.transactions, "net_cents": month.net_cents,
            "income": group(groups.income), "spending": group(groups.spending),
            "confirmed_transfers": group(groups.confirmed_transfers),
            "unconfirmed_transfer_kinds": group(groups.unconfirmed_transfer_kinds),
            "unclassified": group(groups.unclassified),
            "spending_by_category": [{"category": None if category is None else names[category],
                                      **group(total)}
                                     for category, total in groups.spending_by_category],
        })
        if month.accounts_not_covered:
            warnings.append({"kind": "coverage_gap",
                             "detail": f"{month.month}: {len(month.accounts_not_covered)} "
                                       "accounts not covered"})
        unsettled = (month.transactions_with_unsettled_correction
                     + month.transactions_with_unsettled_classification
                     + month.transactions_with_unsettled_categorization
                     + month.transactions_with_unsettled_match
                     + month.transactions_with_unsettled_one_sided_transfer)
        if unsettled:
            warnings.append({"kind": "unsettled_statements",
                             "detail": f"{month.month}: {unsettled} unsettled statements"})
        if month.transactions_in_open_review_items:
            warnings.append({"kind": "possible_duplicates",
                             "detail": f"{month.month}: {month.transactions_in_open_review_items}"
                                       " transactions in open review items"})
    return found


def budget_section(conn, as_of: date, zone, warnings) -> dict | None:
    """M13's month for as_of: the target and the original and revised allowances."""
    if zone is None:
        warnings.append({"kind": "no_timezone",
                         "detail": "the household timezone is not set: budget pace and safe to "
                                   "spend are left out"})
        return None
    report = budget_report(conn, as_of.isoformat()[:7], as_of, None)
    if report.plan is None or report.pace is None:
        warnings.append({"kind": "no_budget_plan",
                         "detail": f"none in effect for {as_of.isoformat()[:7]}"})
        return None
    pace = report.pace
    return {"month": report.month, "target_cents": pace.target_cents,
            "actual_cents": pace.actual_cents,
            "remaining_capacity_cents": pace.remaining_capacity_cents,
            "original_daily_cents": pace.original_daily_cents,
            "revised_daily_cents": pace.revised_daily_cents,
            "revised_weekly_cents": pace.revised_weekly_cents,
            "days_remaining": pace.days_remaining}


def safe_to_spend_section(conn, as_of: date, zone, warnings) -> dict | None:
    """M16's figures, with the constraint that limits them and every provisional reason."""
    if zone is None:
        return None
    view = safe_to_spend(conn, as_of)
    for reason, details in view.reasons.items():
        warnings.append({"kind": "provisional", "detail": f"{reason}: {'; '.join(details)}"})
    return {"today_cents": view.today_cents, "week_cents": view.week_cents,
            "limiting": view.limiting,
            "liquid_cents": view.liquid_cents if view.liquidity_evaluated else None,
            "protected_cents": view.protected_cents,
            "budget_daily_cents": view.budget_daily_cents,
            "liquidity_daily_cents": view.liquidity_daily_cents,
            "horizon_last_day": view.horizon.last_day, "horizon_days": view.horizon.days,
            "next_paycheck": view.horizon.next_paycheck, "provisional": view.provisional,
            "reasons": [{"reason": reason, "details": list(details)}
                        for reason, details in view.reasons.items()]}


def funds_section(conn, as_of: date, warnings) -> list[dict]:
    """M14's funds as report funds shows them."""
    view = funds_view(conn, as_of)
    for holding in view.holdings:
        if holding.over_assigned_cents:
            warnings.append({"kind": "over_assigned",
                             "detail": f"{holding.account_name}: assignments exceed its balance"})
    found = []
    for fund_view in view.funds:
        fund, standing = fund_view.fund, fund_view.standing
        found.append({"name": fund.name, "kind": fund.kind, "state": fund.state,
                      "standing": standing.state, "assigned_cents": standing.assigned_cents,
                      "planned_contribution_cents": standing.planned_contribution_cents,
                      "required_held_cents": standing.required_held_cents,
                      "outstanding_cents": standing.outstanding_cents, "due": standing.due,
                      "months_left": standing.months_left})
    return found


def loans_section(conn, as_of: date, index) -> list[dict]:
    """M15's loans: observed balances, actual against schedule, and projections labelled."""
    found = []
    for loan in loans_view(conn, as_of).loans:
        terms = loan.terms
        projection = None
        if loan.observed is not None:
            observed_on, owed = loan.observed
            projected = project(terms, owed, observed_on)
            projection = {"label": PROJECTION_LABEL, "paid_off": projected.paid_off,
                          "months": len(projected.months),
                          "total_interest_cents": projected.total_interest_cents}
        found.append({
            "account_index": index[terms.account_id],
            "observed_on": loan.observed[0] if loan.observed else None,
            "owed_cents": loan.observed[1] if loan.observed else None,
            "due_periods": [{"due": period.due, "due_cents": period.due_cents,
                             "paid_cents": period.paid_cents, "state": period.state}
                            for period in loan.periods],
            "projection": projection})
    return found


def net_worth_section(conn, as_of: str, index) -> dict:
    worth = net_worth(conn, as_of)
    return {
        "as_of": as_of, "total_cents": worth.total_cents,
        "accounts": [{"account_index": index[valuation.account_id], "how": valuation.how,
                      "observed_on": valuation.observation and valuation.observation.observed_on,
                      "balance_cents": valuation.observation
                      and valuation.observation.balance_cents,
                      "counted_cents": valuation.counted_cents}
                     for valuation in sorted(worth.valued,
                                             key=lambda each: index[each.account_id])],
    }


WINDOW_TRANSACTIONS = """
    SELECT entry.id, entry.account_id,
           COALESCE(fixed_transaction_date.corrected_text, entry.transaction_date),
           COALESCE(fixed_posting_date.corrected_text, entry.posting_date),
           COALESCE(fixed_amount.corrected_amount_cents, entry.amount_cents),
           entry.settlement_status,
           COALESCE(fixed_description.corrected_text, entry.description),
           kind.financial_type,
           (SELECT name FROM category WHERE category.id = COALESCE(by_person.category_id,
                                                                   by_rules.category_id)),
           CASE WHEN by_person.category_id IS NOT NULL THEN 'person'
                WHEN by_rules.category_id IS NOT NULL THEN 'rules' END,
           tagged.tags,
           COALESCE(fixed_transaction_date.corrected_text, entry.transaction_date,
                    fixed_posting_date.corrected_text, entry.posting_date) AS shown_date
    FROM ledger_transaction entry
    LEFT JOIN transaction_correction fixed_amount
        ON fixed_amount.transaction_id = entry.id AND fixed_amount.field = 'amount'
       AND fixed_amount.state = 'applied'
    LEFT JOIN transaction_correction fixed_transaction_date
        ON fixed_transaction_date.transaction_id = entry.id
       AND fixed_transaction_date.field = 'transaction_date'
       AND fixed_transaction_date.state = 'applied'
    LEFT JOIN transaction_correction fixed_posting_date
        ON fixed_posting_date.transaction_id = entry.id
       AND fixed_posting_date.field = 'posting_date' AND fixed_posting_date.state = 'applied'
    LEFT JOIN transaction_correction fixed_description
        ON fixed_description.transaction_id = entry.id
       AND fixed_description.field = 'description' AND fixed_description.state = 'applied'
    LEFT JOIN transaction_classification kind
        ON kind.transaction_id = entry.id AND kind.state = 'applied'
    LEFT JOIN transaction_category by_person
        ON by_person.transaction_id = entry.id AND by_person.state = 'applied'
    LEFT JOIN transaction_rule_category by_rules
        ON by_rules.transaction_id = entry.id AND by_rules.state = 'applied'
    LEFT JOIN transaction_tag tagged
        ON tagged.transaction_id = entry.id AND tagged.state = 'applied'
    WHERE shown_date BETWEEN :first AND :last
    ORDER BY shown_date, entry.id"""


def transactions_section(conn, first_day: str, last_day: str, index, household,
                         members) -> list[dict]:
    """The window's transactions with their effective values (D-049), as pf transactions and
    the export show them, each with its member parts and unsettled flags."""
    tag_names = dict(conn.execute("SELECT id, name FROM tag"))
    rows = conn.execute(WINDOW_TRANSACTIONS, {"first": first_day, "last": last_day}).fetchall()
    ids = [row[0] for row in rows]
    parts = {entry.transaction_id: entry.attribution.parts
             for entry in attributed_transactions(conn, household, transaction_ids=ids)}
    unsettled = _transactions_with_unsettled_effects(conn)
    flags = ("correction", "classification", "categorization", "match", "one_sided")
    found = []
    for (transaction_id, account_id, transaction_date, posting_date, cents, status, description,
         financial_type, category, category_source, tags, shown_date) in rows:
        found.append({
            "transaction_id": transaction_id, "account_index": index[account_id],
            "date": shown_date, "transaction_date": transaction_date,
            "posting_date": posting_date, "amount_cents": cents, "status": status,
            "description": description, "financial_type": financial_type,
            "category": category, "category_source": category_source,
            "tags": sorted(tag_names[int(tag)] for tag in tags.split(",")) if tags else [],
            "member_parts": [{"member_index": members[member_id], "amount_cents": part}
                             for member_id, part in parts.get(transaction_id, ())],
            "unsettled": [flag for flag in flags if transaction_id in unsettled[flag]],
        })
    return found


def review_section(conn) -> dict:
    counts = dict(conn.execute("SELECT kind, COUNT(*) FROM review_issue WHERE status = 'open' "
                               "GROUP BY kind"))
    return {"possible_duplicate": counts.get("possible_duplicate", 0),
            "unresolved_record": counts.get("unresolved_record", 0)}


def envelope(content: dict, snapshot_id: str, generated_at: str) -> dict:
    return {"format": FORMAT, "schema_version": SCHEMA_VERSION, "snapshot_id": snapshot_id,
            "generated_at": generated_at, "content_sha256": sha256_of(content),
            "content": content}


def build_snapshot(conn: sqlite3.Connection, as_of: date, window_days: int, snapshot_id: str,
                   generated_at: str) -> bytes:
    """The snapshot's bytes: the same ledger state, as_of, window, ID and time give the same
    bytes (point 1)."""
    return canonical_bytes(envelope(build_content(conn, as_of, window_days), snapshot_id,
                                    generated_at))
