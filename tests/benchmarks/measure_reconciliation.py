"""Measures import and reconciliation cost on synthetic files (A39).

Not part of the test suite. Run from the repository root:

    PYTHONPATH=src:tests/benchmarks .venv/bin/python tests/benchmarks/measure_reconciliation.py
    (add --scale for the 100,000-transaction shape of M4.4, --scale --category-rules N for it
    with N category rules (D-064), --scale --household for it with household members, defaults
    and 5,000 allocations (D-065), --scale --recurring for it with 6 income sources and 60
    obligations (D-068), --scale --budget for that with three members, a plan with 12 category
    allowances and a month of 3,000 purchases (D-069), --scale --funds, --loans,
    --safe-to-spend, --ui, --scenarios, --snapshot, --sync or --everything for the later
    milestones' rows (G9), or rows per month such as 200 1000 4000)

The M2 and M3 one-off modes (--worst, --constrained, --confirmed, --separated, --superseded,
--corrected, --resolved, --declared, --pending, --classified, --transfers, --one-sided and
--income) were removed by D-082. Their figures stay in docs/benchmarks.md. To run one again,
check out this file from commit d0c0a1a.

Databases are created in a temporary folder and removed afterwards. Each timing covers
one import_files call: reading and parsing the file, writing records, reconciling the
account and committing. It excludes generating the data, writing the CSV file and
creating the database.

Provisional targets (D-034) apply only to the 24-file ordinary and dense fixtures at
4,000 rows a month, on the recorded machine. They are reported here and are deliberately
not test assertions, because wall-clock checks would make the suite flaky.
"""

import calendar
import contextlib
import io
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path

from synthetic_ledger import dense_rows, ordinary_rows, variant_rows, with_overlap

from personal_finance.db.migrate import connect, create_database
from personal_finance.cli import main as cli_main
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.money import format_cents
from personal_finance.reconcile import apply as apply_module
from personal_finance.reconcile import classifications as classifications_module
from personal_finance.reconcile.apply import load_evidence
from personal_finance.reconcile.balance_observations import record_observation
from personal_finance.reconcile.classification_effects import write_classification_effects
from personal_finance.reconcile.allocations import Stated, allocate_transaction, undo_allocation
from personal_finance.reconcile.category_rules import add_rule, checked_definition, undo_rule
from personal_finance.reconcile.household import (
    set_account_default,
    set_share,
    undo_account_default,
    undo_share,
)
from personal_finance.reconcile.household_effects import attributed_transactions, load_household
from personal_finance.reconcile.classifications import classify_transaction
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports.category_rule_evidence import (
    load_rule,
    reach_of_rules,
    rule_preview_outlook,
    rule_undo_outlook,
)
from personal_finance.reconcile.transfer_effects import write_transfer_effects
from personal_finance.reports.allocation_evidence import allocation_undo_outlook, load_allocation
from personal_finance.reports.balances import check_balances
from personal_finance.reports.household_evidence import account_reach, share_reach
from personal_finance.reports.monthly import monthly_report
from personal_finance.reports.review_evidence import load_merge_evidence, transaction_revision

SHAPES = {"ordinary": ordinary_rows, "dense": dense_rows, "variants": variant_rows}
TARGET_ONE_IMPORT_SECONDS = 10
TARGET_ALL_IMPORTS_SECONDS = 120


def measure(shape: str, months: int, rows_per_month: int) -> None:
    run(shape, with_overlap(SHAPES[shape](months, rows_per_month)))


def run(shape: str, files: list[str]) -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "ledger.db"
        create_database(path)
        conn = connect(path)
        conn.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'credit_card')"
        )


        import_seconds = []
        for number, content in enumerate(files):
            source = root / f"{number}.csv"
            source.write_text(content, encoding="utf-8")
            started = time.perf_counter()
            (result,) = import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
            import_seconds.append(time.perf_counter() - started)
            assert result.outcome == "imported", result

        documents, records, unresolved, _ = load_evidence(conn, "acct")
        started = time.perf_counter()
        derivation = derive(documents, records, unresolved, DEFAULT_RULES)
        derive_seconds = time.perf_counter() - started

        logical = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()[0]
        slowest = max(import_seconds)
        total = sum(import_seconds)
        within = slowest < TARGET_ONE_IMPORT_SECONDS and total < TARGET_ALL_IMPORTS_SECONDS
        print(
            f"{shape:12} records={len(records):7} transactions={logical:7} files={len(files):3} "
            f"first={import_seconds[0]:6.2f}s last={import_seconds[-1]:6.2f}s "
            f"slowest={slowest:6.2f}s all={total:7.2f}s derive={derive_seconds:5.2f}s "
            f"steps={derivation.candidate_steps:8} items={len(derivation.items):5} "
            f"within_targets={within}",
            flush=True,
        )
        conn.close()


def classify_directly(conn, account: str, classified: list[tuple[str, str, str]]) -> None:
    """Classifies each (transaction, record, type) of one account, inside the caller's
    transaction, and writes the account's classification outcomes."""
    start = conn.execute("SELECT COUNT(*) FROM type_classification").fetchone()[0]
    for number, (transaction_id, record_id, financial_type) in enumerate(classified, start):
        classification_id = f"f{number:06}"
        conn.execute(
            """INSERT INTO type_classification (id, account_id, financial_type,
                                                target_transaction_id, target_revision)
               VALUES (?, ?, ?, ?, 't7-0')""",
            (classification_id, account, financial_type, transaction_id),
        )
        conn.execute("INSERT INTO type_classification_record VALUES (?, ?)",
                     (classification_id, record_id))
        conn.execute("INSERT INTO type_classification_event (classification_id, event) "
                     "VALUES (?, 'made')", (classification_id,))
    write_classification_effects(conn, account)


SCALE_MONTHS = [f"{2022 + number // 12}-{1 + number % 12:02}" for number in range(60)]
SCALE_ACCOUNTS = (("checking", "Checking", "checking", "transaction"),
                  ("savings", "Savings", "savings", "transaction"),
                  ("card", "Card", "credit_card", "posting"),
                  ("loan", "Loan", "loan", "posting"))
# Each route: outflow account, inflow account, the outflow's type, and matches.
SCALE_ROUTES = (("checking", "savings", "transfer", 5000),
                ("checking", "card", "card_payment", 5000),
                ("savings", "loan", "loan_payment", 5000),
                ("savings", "card", "card_payment", 5000))
SCALE_ONE_SIDED = 2000
# Transactions in no transfer, per account: (count, money in, type or None).
SCALE_OTHERS = {
    "checking": ((3000, True, "income"), (6000, False, "purchase"), (4000, False, None)),
    "savings": ((2000, True, "income"), (8000, True, None)),
    "card": ((10000, False, "purchase"), (5000, False, None)),
    "loan": ((10000, False, "interest"), (10000, False, None)),
}


def scale_day(number: int, offset: int = 0) -> str:
    """A day spread over the 60 months, offset days later, so a late day can cross months."""
    month, day = SCALE_MONTHS[number % 60], 1 + (number // 60) % 28 + offset
    if day > 28:
        month = SCALE_MONTHS[min(number % 60 + 1, 59)]
        day -= 28
    return f"{month}-{day:02}"


def scale_ledger(root: Path):
    """100,000 transactions over 60 months in four accounts, imported as one file a month per
    account, each declaring complete coverage of its month: on the transaction basis for checking
    and savings, on the posting basis for the card and the loan. Then, written directly, 20,000
    applied matches, 2,000 one-sided transfers to an investment account with no documents, types
    on every matched outflow and on most other transactions, and an observed balance at the end of
    every month of every account, agreeing with the activity. Returns the connection and the
    ledger's path."""
    path = root / "ledger.db"
    create_database(path)
    conn = connect(path)
    for account, name, account_type, _ in SCALE_ACCOUNTS:
        conn.execute("INSERT INTO account (id, display_name, account_type) VALUES (?, ?, ?)",
                     (account, name, account_type))
    conn.execute("INSERT INTO account (id, display_name, account_type) "
                 "VALUES ('invest', 'Invest', 'investment')")

    rows = {account: [] for account, *_ in SCALE_ACCOUNTS}  # (external ID, day, cents, type)
    matches = []
    number = 0
    for outflow_account, inflow_account, financial_type, count in SCALE_ROUTES:
        for _ in range(count):
            cents = 100_000 + number
            # Inflows land three days later, so matches dated late in a month cross into the next.
            rows[outflow_account].append((f"M{number}O", scale_day(number), -cents,
                                          financial_type))
            rows[inflow_account].append((f"M{number}I", scale_day(number, 3), cents, None))
            matches.append((f"M{number}O", outflow_account, f"M{number}I", inflow_account))
            number += 1
    for statement in range(SCALE_ONE_SIDED):
        rows["checking"].append((f"O{statement}", scale_day(statement), -(300_000 + statement),
                                 "investment_contribution"))
    for account, groups in SCALE_OTHERS.items():
        for group, (count, money_in, financial_type) in enumerate(groups):
            for index in range(count):
                cents = 1 + (index * 7919 + group * 104_729) % 99_999
                rows[account].append((f"X{group}-{index}", scale_day(index + group * 17),
                                      cents if money_in else -cents, financial_type))
    assert sum(len(found) for found in rows.values()) == 100_000

    for account, _, _, basis in SCALE_ACCOUNTS:
        by_month = {month: [] for month in SCALE_MONTHS}
        for external_id, day, cents, _ in rows[account]:
            by_month[day[:7]].append(f"{external_id},{day},{day},SYNTHETIC {external_id},"
                                     f"{cents / 100:.2f},POSTED\n")
        for month, lines in by_month.items():
            source = root / f"{account}-{month}.csv"
            source.write_text(
                "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                + "".join(lines))
            last_day = f"{month}-{calendar.monthrange(int(month[:4]), int(month[5:]))[1]:02}"
            (result,) = import_files(conn, [source], account_id=account,
                                     layout=SYNTHETIC_CHECKING_V1,
                                     declared_coverage=declare_complete(f"{month}-01", last_day,
                                                                        basis))
            assert result.outcome == "imported", result

    # External IDs repeat across accounts, so each is looked up with its account.
    links = {
        (account, external_id): (transaction_id, record_id)
        for account, external_id, transaction_id, record_id in conn.execute(
            """SELECT entry.account_id, entry.external_id, link.transaction_id,
                      link.source_record_id
               FROM transaction_source link
               JOIN ledger_transaction entry ON entry.id = link.transaction_id""")
    }
    conn.execute("BEGIN")
    for account in rows:
        classify_directly(conn, account, [(*links[account, external_id], financial_type)
                                          for external_id, _, _, financial_type in rows[account]
                                          if financial_type])
    for number, (outflow_id, outflow_account, inflow_id, inflow_account) in enumerate(matches):
        match_id = f"m{number:06}"
        conn.execute("INSERT INTO transfer_match (id) VALUES (?)", (match_id,))
        for side, account, external_id in (("outflow", outflow_account, outflow_id),
                                           ("inflow", inflow_account, inflow_id)):
            transaction_id, record_id = links[account, external_id]
            conn.execute("INSERT INTO transfer_match_side VALUES (?, ?, ?, ?, 't7-0')",
                         (match_id, side, account, transaction_id))
            conn.execute("INSERT INTO transfer_match_record VALUES (?, ?, ?)",
                         (match_id, side, record_id))
        conn.execute("INSERT INTO transfer_match_event (match_id, event) VALUES (?, 'made')",
                     (match_id,))
    for statement in range(SCALE_ONE_SIDED):
        statement_id = f"o{statement:06}"
        transaction_id, record_id = links["checking", f"O{statement}"]
        conn.execute(
            """INSERT INTO one_sided_transfer (id, account_id, counterpart_account_id,
                                               target_transaction_id, target_revision)
               VALUES (?, 'checking', 'invest', ?, 't7-0')""",
            (statement_id, transaction_id),
        )
        conn.execute("INSERT INTO one_sided_transfer_record VALUES (?, ?)",
                     (statement_id, record_id))
        conn.execute("INSERT INTO one_sided_transfer_event (one_sided_transfer_id, event) "
                     "VALUES (?, 'made')", (statement_id,))
    write_transfer_effects(conn)
    conn.execute("COMMIT")

    for account, _, account_type, _ in SCALE_ACCOUNTS:
        balance = 0
        by_month = {month: 0 for month in SCALE_MONTHS}
        for _, day, cents, _ in rows[account]:
            by_month[day[:7]] += cents
        for month, cents in by_month.items():
            balance += cents
            last_day = f"{month}-{calendar.monthrange(int(month[:4]), int(month[5:]))[1]:02}"
            owed = account_type in ("credit_card", "loan")
            record_observation(conn, account, last_day,
                               format_cents(-balance if owed else balance), owed=owed)
    return conn, path


def timed_command(*words: str) -> float:
    """One CLI command's wall time, its output discarded, failing on a non-zero exit."""
    started = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        code = cli_main(list(words))
    seconds = time.perf_counter() - started
    assert code == 0, words
    return seconds


def counting_rewrites(module, rewritten: list, rewrite_seconds: list):
    """Replaces a module's write_transfer_effects with one recording how many match outcomes each
    call rewrites, so that a timing is known to include all of them, and how long it took."""
    def counted(connection):
        rewritten.append(connection.execute(
            "SELECT COUNT(*) FROM transfer_match_effect").fetchone()[0])
        started = time.perf_counter()
        write_transfer_effects(connection)
        rewrite_seconds.append(time.perf_counter() - started)
    module.write_transfer_effects = counted


def measure_scale() -> None:
    """Measures totals, report monthly, balance check, one classification and one import on the
    100,000-transaction shape, each apart, and prints the counts the shape reached (Z1, Z2).
    Targets are provisional, below two seconds for each report (PRD §20, D-034, D-057)."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path = scale_ledger(root)
        build_seconds = time.perf_counter() - started
        (transactions, months, accounts, applied_matches, matched_sides, one_sided_applied,
         classifications, coverage, observations, open_items) = conn.execute(
            """SELECT (SELECT COUNT(*) FROM ledger_transaction),
                      (SELECT COUNT(DISTINCT substr(COALESCE(transaction_date, posting_date), 1, 7))
                       FROM ledger_transaction),
                      (SELECT COUNT(DISTINCT account_id) FROM ledger_transaction),
                      (SELECT COUNT(*) FROM transfer_match_effect WHERE state = 'applied'),
                      (SELECT COUNT(*) FROM transfer_match_side),
                      (SELECT COUNT(*) FROM one_sided_transfer_effect WHERE state = 'applied'),
                      (SELECT COUNT(*) FROM transaction_classification WHERE state = 'applied'),
                      (SELECT COUNT(*) FROM document_coverage WHERE coverage_kind = 'complete'),
                      (SELECT COUNT(*) FROM balance_observation),
                      (SELECT COUNT(*) FROM review_issue WHERE status = 'open')"""
        ).fetchone()
        print(
            f"shape transactions={transactions} months={months} accounts={accounts} "
            f"applied_matches={applied_matches} matched_sides={matched_sides} "
            f"one_sided={one_sided_applied} classified={classifications} "
            f"complete_coverage={coverage} observations={observations} "
            f"open_review_items={open_items} build={build_seconds:.1f}s",
            flush=True,
        )
        # Z1: the shape reaches the counts it claims, and more matched sides than SQLite's
        # 32,766 variables, so that M4.1's queries are reached past their old limit.
        assert (transactions, months, accounts) == (100_000, 60, 4)
        assert applied_matches == 20_000 and matched_sides == 40_000 > 32_766
        assert one_sided_applied == SCALE_ONE_SIDED and open_items == 0
        conn.close()

        database = str(path)
        totals_seconds = timed_command("totals", "--db", database)
        monthly_seconds = timed_command("report", "monthly", "--db", database)
        check_seconds = timed_command("balance", "check", "--db", database, "--account",
                                      "Checking")
        conn = connect(path)
        report = monthly_report(conn)
        assert len(report.months) == 60
        assert sum(month.matched_sides_with_other_side_in_another_month
                   for month in report.months) > 0
        check = check_balances(conn, "checking")
        assert len(check.intervals) == 59
        # Checking declares transaction-basis coverage and the card posting-basis coverage, so
        # only the card's intervals are covered, and every interval agrees.
        assert all(interval.difference_cents == 0 and not interval.covered
                   for interval in check.intervals)
        assert all(interval.difference_cents == 0 and interval.covered
                   for interval in check_balances(conn, "card").intervals)

        # Named by its external ID, since generated IDs are random and a matched side, also
        # unclassified, would refuse a type that stops its match applying. X1-0 is an
        # unclassified savings inflow in no transfer.
        (unclassified,) = conn.execute(
            """SELECT entry.id FROM ledger_transaction entry
               WHERE entry.account_id = 'savings' AND entry.external_id = 'X1-0' AND NOT EXISTS (
                   SELECT 1 FROM transaction_classification kind
                   WHERE kind.transaction_id = entry.id)""").fetchone()
        rewritten, classify_rewrite_seconds = [], []
        counting_rewrites(classifications_module, rewritten, classify_rewrite_seconds)
        started = time.perf_counter()
        classify_transaction(conn, "savings", unclassified,
                             transaction_revision(load_merge_evidence(conn, unclassified)),
                             "income")
        classify_seconds = time.perf_counter() - started
        classifications_module.write_transfer_effects = write_transfer_effects
        assert rewritten == [20_000], rewritten

        later = root / "later.csv"
        later.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                         "LATER,2026-12-30,2026-12-30,SYNTHETIC LATER,-9.00,POSTED\n")
        rewritten, import_rewrite_seconds = [], []
        counting_rewrites(apply_module, rewritten, import_rewrite_seconds)
        started = time.perf_counter()
        (result,) = import_files(conn, [later], account_id="savings",
                                 layout=SYNTHETIC_CHECKING_V1)
        import_seconds = time.perf_counter() - started
        apply_module.write_transfer_effects = write_transfer_effects
        assert result.outcome == "imported" and rewritten == [20_000], (result, rewritten)
        print(
            f"totals={totals_seconds:7.3f}s report_monthly={monthly_seconds:7.3f}s "
            f"balance_check={check_seconds:7.3f}s one_classification={classify_seconds:7.3f}s "
            f"one_import={import_seconds:7.3f}s",
            flush=True,
        )
        print(
            f"of which rewriting 20,000 match outcomes: classification="
            f"{classify_rewrite_seconds[0]:7.3f}s import={import_rewrite_seconds[0]:7.3f}s",
            flush=True,
        )
        conn.close()


def scale_category_rules(count: int) -> list[tuple]:
    """count category rules over the shape's spending descriptions, SYNTHETIC X0-n on the card and
    loan and SYNTHETIC X1-n on checking, as (category ID, text, account, type, first date). Texts
    are number prefixes, so a shorter one reaches the transactions a longer one does, and their
    categories cycle, so some agree and some disagree. Every fifth is narrowed to an account, a
    type or a first date."""
    found = []
    for number in range(count):
        group, prefix = ("x1", 10 + number // 5) if number % 5 == 4 else ("x0", 10 + number)
        account = type_ = from_date = None
        if number % 5 == 1:
            account = "card"
        elif number % 5 == 2:
            type_ = "interest"
        elif number % 5 == 3:
            from_date = "2024-01-01"
        found.append((1 + number % 12, f"SYNTHETIC {group}-{prefix}", account, type_, from_date))
    return found


def measure_category_rules(count: int) -> None:
    """Rules on the 100,000-transaction shape: totals and report monthly, a rule's preview, add and
    undo, and one classification and one import, each of which rewrites every rule's outcome, with
    the counts the rules reach (D-064 point 9, RC4). Rules and a few person's categorizations are
    written directly. Stops, as point 9 says, if a preview or add costs more than twice the import
    of one row, or a report misses two seconds."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path = scale_ledger(root)
        conn.execute("BEGIN")
        for number, (category_id, text, account, type_, from_date) in enumerate(
                scale_category_rules(count)):
            rule_id = f"r{number:06}"
            conn.execute(
                """INSERT INTO category_rule (id, account_id, category_id, description_contains,
                                              normalization_version, financial_type, from_date)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (rule_id, account, category_id, text, type_, from_date))
            conn.execute("INSERT INTO category_rule_event (rule_id, event) VALUES (?, 'made')",
                         (rule_id,))
        # A person's categorization on 500 card purchases that rules reach, which comes first.
        for number, (transaction_id, record_id) in enumerate(conn.execute(
            """SELECT entry.id, entry.primary_source_record_id FROM ledger_transaction entry
               WHERE entry.account_id = 'card' AND entry.external_id LIKE 'X0-1%'
               ORDER BY entry.external_id LIMIT 500""").fetchall()):
            assignment_id = f"g{number:06}"
            conn.execute(
                """INSERT INTO category_assignment (id, account_id, category_id,
                                                    target_transaction_id, target_revision)
                   VALUES (?, 'card', 12, ?, 't8-0')""", (assignment_id, transaction_id))
            conn.execute("INSERT INTO category_assignment_record VALUES (?, ?)",
                         (assignment_id, record_id))
            conn.execute("INSERT INTO category_assignment_event (assignment_id, event) "
                         "VALUES (?, 'made')", (assignment_id,))
        rewrite_started = time.perf_counter()
        write_transfer_effects(conn)
        rewrite_seconds = time.perf_counter() - rewrite_started
        conn.execute("COMMIT")
        build_seconds = time.perf_counter() - started
        spending, applied, disagreeing, by_person, rules = conn.execute(
            """SELECT (SELECT COUNT(*) FROM transaction_classification
                       WHERE state = 'applied'
                         AND financial_type IN ('purchase', 'fee', 'interest', 'refund')),
                      (SELECT COUNT(*) FROM transaction_rule_category WHERE state = 'applied'),
                      (SELECT COUNT(*) FROM transaction_rule_category
                       WHERE state = 'rule_conflict'),
                      (SELECT COUNT(*) FROM transaction_category WHERE state = 'applied'),
                      (SELECT COUNT(*) FROM category_rule)"""
        ).fetchone()
        reach = reach_of_rules(conn)
        person_first = sum(1 for found in reach.values() if found.categorized_by_person)
        print(
            f"shape rules={rules} spending={spending} categorized_by_rules={applied} "
            f"rule_conflict={disagreeing} categorized_by_person={by_person} "
            f"rules_with_a_person_first={person_first} first_rewrite={rewrite_seconds:.3f}s "
            f"build={build_seconds:.1f}s",
            flush=True,
        )
        # The shape reaches the cost it claims: rules categorize thousands of transactions,
        # disagree on many, and yield to a person on some, and every rule is active.
        assert rules == count == len(reach)
        assert applied > 1_000 and disagreeing > 1_000 and by_person == 500 and person_first > 0
        conn.close()

        database = str(path)
        totals_seconds = timed_command("totals", "--db", database)
        monthly_seconds = timed_command("report", "monthly", "--db", database)
        rule_words = ["--category", "Food", "--description-contains", "synthetic x0-3"]
        preview_seconds = timed_command("category", "rule", "preview", "--db", database,
                                        *rule_words)
        conn = connect(path)
        definition = checked_definition(conn, "Food", "synthetic x0-3")
        revision = rule_preview_outlook(conn, definition).revision
        started = time.perf_counter()
        added = add_rule(conn, "Food", "synthetic x0-3", revision)
        add_seconds = time.perf_counter() - started
        assert added.outlook.changes, "the added rule must change something"
        undo_revision = rule_undo_outlook(conn, load_rule(conn, added.rule_id)).revision
        started = time.perf_counter()
        undone = undo_rule(conn, added.rule_id, undo_revision)
        undo_seconds = time.perf_counter() - started
        assert len(undone.changes) == len(added.outlook.changes)

        (unclassified,) = conn.execute(
            """SELECT entry.id FROM ledger_transaction entry
               WHERE entry.account_id = 'savings' AND entry.external_id = 'X1-0' AND NOT EXISTS (
                   SELECT 1 FROM transaction_classification kind
                   WHERE kind.transaction_id = entry.id)""").fetchone()
        started = time.perf_counter()
        classify_transaction(conn, "savings", unclassified,
                             transaction_revision(load_merge_evidence(conn, unclassified)),
                             "income")
        classify_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                         "LATER,2026-12-30,2026-12-30,SYNTHETIC X0-31,-9.00,POSTED\n")
        started = time.perf_counter()
        (result,) = import_files(conn, [later], account_id="savings",
                                 layout=SYNTHETIC_CHECKING_V1)
        import_seconds = time.perf_counter() - started
        assert result.outcome == "imported"
        conn.close()
        print(
            f"totals={totals_seconds:7.3f}s report_monthly={monthly_seconds:7.3f}s "
            f"rule_preview={preview_seconds:7.3f}s rule_add={add_seconds:7.3f}s "
            f"rule_undo={undo_seconds:7.3f}s one_classification={classify_seconds:7.3f}s "
            f"one_import={import_seconds:7.3f}s changed_by_the_rule={len(added.outlook.changes)}",
            flush=True,
        )
        stops = [name for name, seconds in (("preview", preview_seconds), ("add", add_seconds))
                 if seconds > 2 * import_seconds]
        stops += [name for name, seconds in (("totals", totals_seconds),
                                             ("report monthly", monthly_seconds)) if seconds > 2]
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


# Account defaults on the scale shape: the card and checking shared, savings and the loan personal.
SCALE_DEFAULTS = (("checking", None), ("card", None), ("savings", 1), ("loan", 2))
SCALE_ALLOCATIONS = 5_000


def scale_allocations(conn) -> dict[str, int]:
    """5,000 allocations on the shape, written directly: 4,800 of every kind in turn on the loan's
    and savings' transactions in no transfer, a second, disagreeing one on 100 of those, and 100 by
    amount whose parts sum to one cent more than their transaction. Returns how many of each were
    written."""
    targets = conn.execute(
        """SELECT entry.id, entry.account_id, entry.primary_source_record_id, entry.amount_cents
           FROM ledger_transaction entry
           WHERE entry.account_id IN ('savings', 'loan') AND entry.external_id LIKE 'X%'
           ORDER BY entry.account_id, entry.external_id""").fetchall()
    written = {"member": 0, "shared": 0, "percent": 0, "amount": 0, "conflict": 0,
               "amount_differs": 0}

    def allocate(number, transaction, account, record, value, parts):
        allocation_id = f"a{number:06}"
        conn.execute(
            """INSERT INTO allocation_statement (id, account_id, allocation,
                                                 target_transaction_id, target_revision)
               VALUES (?, ?, ?, ?, 't13-0')""", (allocation_id, account, value, transaction))
        conn.executemany("INSERT INTO allocation_statement_part VALUES (?, ?, ?)",
                         [(allocation_id, member, part) for member, part in parts])
        conn.execute("INSERT INTO allocation_statement_record VALUES (?, ?)",
                     (allocation_id, record))
        conn.execute("INSERT INTO allocation_statement_event (allocation_id, event) "
                     "VALUES (?, 'made')", (allocation_id,))

    number = 0
    kinds = ("member", "shared", "percent", "amount")
    for transaction, account, record, cents in targets[:SCALE_ALLOCATIONS - 200]:
        kind = kinds[number % 4]
        magnitude = abs(cents)
        parts = {"member": [(2, 10_000)], "shared": [], "percent": [(1, 3_000), (2, 7_000)],
                 "amount": [(1, magnitude // 3), (2, magnitude - magnitude // 3)]}[kind]
        # A third of one or two cents is none, so that part is left out.
        parts = [(member, part) for member, part in parts if part > 0]
        allocate(number, transaction, account, record,
                 f"{kind}:" + ",".join(f"{member}={part}" for member, part in parts), parts)
        written[kind] += 1
        number += 1
    for transaction, account, record, _ in targets[:100]:
        allocate(number, transaction, account, record, "member:1=10000", [(1, 10_000)])
        written["conflict"] += 1
        number += 1
    for transaction, account, record, cents in targets[SCALE_ALLOCATIONS - 200:
                                                       SCALE_ALLOCATIONS - 100]:
        allocate(number, transaction, account, record, f"amount:1={abs(cents) + 1}",
                 [(1, abs(cents) + 1)])
        written["amount_differs"] += 1
        number += 1
    return written


def measure_household() -> None:
    """Household allocations on the 100,000-transaction shape (D-065 point 9, HC5): totals and
    report monthly, report household in each view, one allocation and its undo, a default and a
    share set again, one classification and one import, with how many transactions each member,
    shared and unattributed hold. Stops, as point 9 says, if report household misses two seconds
    or an allocation costs more than twice the import of one row."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path = scale_ledger(root)
        conn.execute("BEGIN")
        for name in ("Michael", "M"):
            conn.execute("INSERT INTO household_member (name) VALUES (?)", (name,))
        conn.execute("INSERT INTO household_share (id) VALUES ('h0')")
        conn.execute("INSERT INTO household_share_part VALUES ('h0', 1, 5000), ('h0', 2, 5000)")
        conn.execute("INSERT INTO household_share_event (share_id, event) VALUES ('h0', 'made')")
        for account, member in SCALE_DEFAULTS:
            conn.execute("INSERT INTO account_attribution (id, account_id, member_id) "
                         "VALUES (?, ?, ?)", (f"d-{account}", account, member))
            conn.execute("INSERT INTO account_attribution_event (attribution_id, event) "
                         "VALUES (?, 'made')", (f"d-{account}",))
        written = scale_allocations(conn)
        rewrite_started = time.perf_counter()
        write_transfer_effects(conn)
        rewrite_seconds = time.perf_counter() - rewrite_started
        conn.execute("COMMIT")
        build_seconds = time.perf_counter() - started

        household = load_household(conn)
        held = {"Michael": 0, "M": 0, "shared": 0, "unattributed": 0}
        states = dict(conn.execute(
            "SELECT state, COUNT(*) FROM transaction_allocation GROUP BY state").fetchall())
        for entry in attributed_transactions(conn, household):
            attribution = entry.attribution
            if attribution.kind == "unattributed":
                held["unattributed"] += 1
            elif len(attribution.parts) > 1:
                held["shared"] += 1
            else:
                held[household.name_of(attribution.parts[0][0])] += 1
        print(f"shape allocations={sum(written.values())} written={written} "
              f"outcomes={states} held={held} first_rewrite={rewrite_seconds:.3f}s "
              f"build={build_seconds:.1f}s", flush=True)
        # The shape reaches the cost it claims: allocations of every kind apply, some disagree and
        # some no longer sum, and the share divides tens of thousands of transactions.
        assert sum(written.values()) == SCALE_ALLOCATIONS
        assert states == {"applied": 4_700, "conflict": 100, "amount_differs": 100}, states
        assert held["shared"] > 40_000 and held["Michael"] > 1_000 and held["M"] > 10_000
        assert held["unattributed"] == 200, held
        conn.close()

        database = str(path)
        totals_seconds = timed_command("totals", "--db", database)
        monthly_seconds = timed_command("report", "monthly", "--db", database)
        side_seconds = timed_command("report", "household", "--db", database)
        member_seconds = timed_command("report", "household", "--db", database, "--member", "M")
        shared_seconds = timed_command("report", "household", "--db", database, "--shared")

        conn = connect(path)
        (target,) = conn.execute(
            """SELECT entry.id FROM ledger_transaction entry
               WHERE entry.account_id = 'checking' AND entry.external_id = 'X0-0'""").fetchone()
        started = time.perf_counter()
        made = allocate_transaction(
            conn, "checking", target, transaction_revision(load_merge_evidence(conn, target)),
            Stated(percents=("Michael=40", "M=60")))
        allocate_seconds = time.perf_counter() - started
        undo_revision = allocation_undo_outlook(
            conn, load_allocation(conn, made.allocation_id)).revision
        started = time.perf_counter()
        undo_allocation(conn, "checking", made.allocation_id, undo_revision)
        undo_seconds = time.perf_counter() - started

        household = load_household(conn)
        started = time.perf_counter()
        undo_account_default(conn, "loan", account_reach(conn, household, "loan").revision)
        set_account_default(conn, "loan", "M",
                            account_reach(conn, load_household(conn), "loan").revision)
        default_seconds = time.perf_counter() - started
        started = time.perf_counter()
        undo_share(conn, share_reach(conn, load_household(conn)).revision)
        set_share(conn, ["Michael=50", "M=50"], share_reach(conn, load_household(conn)).revision)
        share_seconds = time.perf_counter() - started

        (unclassified,) = conn.execute(
            """SELECT entry.id FROM ledger_transaction entry
               WHERE entry.account_id = 'savings' AND entry.external_id = 'X1-0' AND NOT EXISTS (
                   SELECT 1 FROM transaction_classification kind
                   WHERE kind.transaction_id = entry.id)""").fetchone()
        started = time.perf_counter()
        classify_transaction(conn, "savings", unclassified,
                             transaction_revision(load_merge_evidence(conn, unclassified)),
                             "income")
        classify_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                         "LATER,2026-12-30,2026-12-30,SYNTHETIC LATER,-9.00,POSTED\n")
        started = time.perf_counter()
        (result,) = import_files(conn, [later], account_id="savings",
                                 layout=SYNTHETIC_CHECKING_V1)
        import_seconds = time.perf_counter() - started
        assert result.outcome == "imported"
        conn.close()
        print(
            f"totals={totals_seconds:7.3f}s report_monthly={monthly_seconds:7.3f}s "
            f"household={side_seconds:7.3f}s household_member={member_seconds:7.3f}s "
            f"household_shared={shared_seconds:7.3f}s",
            flush=True,
        )
        print(
            f"allocate={allocate_seconds:7.3f}s allocation_undo={undo_seconds:7.3f}s "
            f"account_undo_and_set={default_seconds:7.3f}s share_undo_and_set={share_seconds:7.3f}s "
            f"one_classification={classify_seconds:7.3f}s one_import={import_seconds:7.3f}s",
            flush=True,
        )
        stops = [name for name, seconds in (("allocate", allocate_seconds),
                                            ("allocation undo", undo_seconds))
                 if seconds > 2 * import_seconds]
        stops += [name for name, seconds in (("report household", side_seconds),
                                             ("report household --member", member_seconds),
                                             ("report household --shared", shared_seconds))
                  if seconds > 2]
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


# Income sources on the shape, D-068 point 9: two biweekly, two semimonthly and two side, each
# (name, text, cadence, first_day, second_day, interval, anchor, amount in cents, kind). Every
# 25th pay date goes unpaid, so missed is reached; biweekly months with a third date give extra.
RECURRING_SOURCES = (
    ("Pay A", "SYNTHETIC PAYROLL A", "biweekly", None, None, None, "2022-01-07", 250_000,
     "salary"),
    ("Pay B", "SYNTHETIC PAYROLL B", "biweekly", None, None, None, "2022-01-14", 230_000,
     "salary"),
    ("Pay C", "SYNTHETIC PAYROLL C", "semimonthly", 1, 15, None, "2022-01-01", 180_000, "salary"),
    ("Pay D", "SYNTHETIC PAYROLL D", "semimonthly", 15, 28, None, "2022-01-15", 160_000,
     "salary"),
    ("Gig E", "SYNTHETIC GIG E", "monthly", 20, None, None, "2022-01-20", 30_000, "side"),
    ("Gig F", "SYNTHETIC GIG F", "quarterly", 10, None, None, "2022-01-10", 90_000, "side"),
)
# 59 bills, each its own obligation, and one broad obligation that also reaches bills 00 to 09,
# so 600 payments are in obligation_conflict.
RECURRING_BILLS = 59
RECURRING_CONFLICTS = 600


def recurring_ledger(root: Path, side_tax_eligible: bool = False):
    """The scale ledger plus a checking account, Bills, holding the six sources' paychecks and
    the bills, one file a month with complete coverage, typed directly, then 6 sources and 60
    obligations written directly and derived once. side_tax_eligible makes the side sources
    tax-eligible (D-070's --funds row)."""
    from personal_finance.planning.schedules import Cadence, ScheduleTerms, scheduled_dates

    conn, path = scale_ledger(root)
    conn.execute("INSERT INTO account (id, display_name, account_type) "
                 "VALUES ('bills', 'Bills', 'checking')")
    rows = []  # (external ID, day, cents, type, description)
    unpaid = 0
    end = date(2026, 12, 31)
    for number, (_, text, cadence, first, second, interval, anchor, cents, _) in enumerate(
            RECURRING_SOURCES):
        terms = (ScheduleTerms(anchor, Cadence(cadence, first, second, interval), anchor),)
        for index, (nominal, _) in enumerate(scheduled_dates(terms, end)):
            if index % 25 == 24:
                unpaid += 1
                continue
            rows.append((f"S{number}-{index}", nominal.isoformat(), cents, "income", text))
    for bill in range(RECURRING_BILLS):
        day = 1 + bill % 28
        for month in SCALE_MONTHS:
            rows.append((f"B{bill}-{month}", f"{month}-{day:02}", -(5_000 + bill * 100),
                         "purchase", f"SYNTHETIC BILL {bill:02}"))
    by_month = {month: [] for month in SCALE_MONTHS}
    for external_id, day, cents, _, text in rows:
        by_month[day[:7]].append(f"{external_id},{day},{day},{text},{cents / 100:.2f},POSTED\n")
    for month, lines in by_month.items():
        source = root / f"bills-{month}.csv"
        source.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,"
                          "Status\n" + "".join(lines))
        last_day = f"{month}-{calendar.monthrange(int(month[:4]), int(month[5:]))[1]:02}"
        (result,) = import_files(conn, [source], account_id="bills", layout=SYNTHETIC_CHECKING_V1,
                                 declared_coverage=declare_complete(f"{month}-01", last_day,
                                                                    "transaction"))
        assert result.outcome == "imported", result
    links = {external_id: (transaction_id, record_id)
             for external_id, transaction_id, record_id in conn.execute(
                 """SELECT entry.external_id, link.transaction_id, link.source_record_id
                    FROM transaction_source link
                    JOIN ledger_transaction entry ON entry.id = link.transaction_id
                    WHERE entry.account_id = 'bills'""")}
    conn.execute("BEGIN")
    classify_directly(conn, "bills", [(*links[external_id], financial_type)
                                      for external_id, _, _, financial_type, _ in rows])
    for number, (name, text, cadence, first, second, interval, anchor, cents, kind) in enumerate(
            RECURRING_SOURCES):
        source_id = f"src{number}"
        conn.execute(
            """INSERT INTO income_source (id, account_id, name, kind, description_contains,
                                          normalization_version, tolerance_days,
                                          amount_tolerance_cents, tax_eligible, chain_id)
               VALUES (?, 'bills', ?, ?, ?, 1, 3, 0, ?, ?)""",
            (source_id, name, kind, text, int(side_tax_eligible and kind == "side"), source_id))
        conn.execute(
            """INSERT INTO income_source_terms (chain_id, effective_from, cadence, first_day,
                                                second_day, interval_months, anchor,
                                                amount_cents)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_id, anchor, cadence, first, second, interval, anchor, cents))
        conn.execute("INSERT INTO income_source_event (source_id, event) VALUES (?, 'made')",
                     (source_id,))
    obligations = [(f"Bill {bill:02}", f"SYNTHETIC BILL {bill:02}", 1 + bill % 28,
                    5_000 + bill * 100, 5_000 + bill * 100,
                    "fixed" if bill % 2 == 0 else "discretionary")
                   for bill in range(RECURRING_BILLS)]
    obligations.append(("Bills 0x", "SYNTHETIC BILL 0", 1, 5_000, 6_000, "discretionary"))
    for number, (name, text, day, low, high, obligation_class) in enumerate(obligations):
        obligation_id = f"ob{number}"
        conn.execute(
            """INSERT INTO recurring_obligation (id, account_id, name, description_contains,
                                                 normalization_version, tolerance_days,
                                                 chain_id)
               VALUES (?, 'bills', ?, ?, 1, 3, ?)""", (obligation_id, name, text, obligation_id))
        conn.execute(
            """INSERT INTO recurring_obligation_terms (chain_id, effective_from, cadence,
                                                       first_day, anchor, low_cents, high_cents,
                                                       obligation_class)
               VALUES (?, ?, 'monthly', ?, ?, ?, ?, ?)""",
            (obligation_id, f"2022-01-{day:02}", day, f"2022-01-{day:02}", low, high,
             obligation_class))
        conn.execute("INSERT INTO recurring_obligation_event (obligation_id, event) "
                     "VALUES (?, 'made')", (obligation_id,))
    write_transfer_effects(conn)
    conn.execute("COMMIT")
    return conn, path, unpaid


def measure_recurring() -> None:
    """Income sources and obligations on the 100,000-transaction shape (D-068 point 9, IC4):
    report income over every month and one month, both proposals, income add and obligation add,
    a one-row import and totals, with the counts of received, missed, extra and
    obligation_conflict. Stops, as G9 says, if a report or proposal misses two seconds or an add
    costs more than twice the import of one row."""
    from personal_finance.planning.income_sources import SourceRequest, add_source, source_preview
    from personal_finance.planning.obligations import (
        ObligationRequest,
        add_obligation,
        obligation_preview,
    )
    from personal_finance.reports.income_report import income_report

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, unpaid = recurring_ledger(root)
        build_seconds = time.perf_counter() - started
        states = dict(conn.execute(
            "SELECT state, COUNT(*) FROM transaction_income_source GROUP BY state").fetchall())
        obligation_states = dict(conn.execute(
            "SELECT state, COUNT(*) FROM transaction_obligation GROUP BY state").fetchall())
        report = income_report(conn, date(2026, 12, 31))
        missed = sum(part.missed for month in report.months for row in month.sources
                     for part in row.parts.values())
        extra = sum(row.parts["extra"].received.count for month in report.months
                    for row in month.sources if "extra" in row.parts)
        transactions = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()[0]
        print(f"shape transactions={transactions} sources={len(RECURRING_SOURCES)} "
              f"obligations={RECURRING_BILLS + 1} income={states} obligation={obligation_states} "
              f"missed={missed} extra={extra} build={build_seconds:.1f}s", flush=True)
        # The shape reaches the cost it claims: every source pays and misses, biweekly months
        # hold extra pay, and the broad obligation conflicts on ten bills' payments.
        assert transactions > 104_000
        assert states == {"received": sum(states.values())} and states["received"] > 500
        expected = sum(part.expected for month in report.months for row in month.sources
                       for part in row.parts.values())
        assert missed + expected == unpaid and missed > 0, (missed, expected, unpaid)
        assert extra > 10
        assert obligation_states["obligation_conflict"] == 2 * RECURRING_CONFLICTS
        assert obligation_states["paid"] == RECURRING_BILLS * 60 - RECURRING_CONFLICTS
        conn.close()

        database = str(path)
        totals_seconds = timed_command("totals", "--db", database)
        report_seconds = timed_command("report", "income", "--db", database, "--as-of",
                                       "2026-12-31")
        month_seconds = timed_command("report", "income", "--db", database, "--as-of",
                                      "2026-12-31", "--from", "2026-06", "--to", "2026-06")
        income_proposals_seconds = timed_command("income", "proposals", "--db", database)
        obligation_proposals_seconds = timed_command("obligation", "proposals", "--db",
                                                     database)

        conn = connect(path)
        request = SourceRequest("bills", "Pay G", "side", "synthetic gig e and more", "monthly:20",
                                "2022-01-20", "300.00")
        revision = source_preview(conn, request).revision
        started = time.perf_counter()
        add_source(conn, request, revision)
        income_add_seconds = time.perf_counter() - started
        request = ObligationRequest("bills", "Bill X", "synthetic bill 58 extra", None,
                                    "monthly:3", "2022-01-03", "62.00", None, "fixed")
        revision = obligation_preview(conn, request).revision
        started = time.perf_counter()
        add_obligation(conn, request, revision)
        obligation_add_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                         "LATER,2026-12-30,2026-12-30,SYNTHETIC LATER,-9.00,POSTED\n")
        started = time.perf_counter()
        (result,) = import_files(conn, [later], account_id="savings",
                                 layout=SYNTHETIC_CHECKING_V1)
        import_seconds = time.perf_counter() - started
        assert result.outcome == "imported"
        conn.close()
        print(f"totals={totals_seconds:7.3f}s report_income={report_seconds:7.3f}s "
              f"report_income_month={month_seconds:7.3f}s "
              f"income_proposals={income_proposals_seconds:7.3f}s "
              f"obligation_proposals={obligation_proposals_seconds:7.3f}s", flush=True)
        print(f"income_add={income_add_seconds:7.3f}s obligation_add={obligation_add_seconds:7.3f}s "
              f"one_import={import_seconds:7.3f}s", flush=True)
        stops = [name for name, seconds in (("income add", income_add_seconds),
                                            ("obligation add", obligation_add_seconds))
                 if seconds > 2 * import_seconds or seconds > 2]
        stops += [name for name, seconds in (("report income", report_seconds),
                                             ("report income, one month", month_seconds),
                                             ("income proposals", income_proposals_seconds),
                                             ("obligation proposals",
                                              obligation_proposals_seconds))
                  if seconds > 2]
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


BUDGET_MEMBERS = ("Ann", "Ben", "Cal")
BUDGET_STORES = "ABCDEFGHIJKL"
BUDGET_ROWS = 3_000
BUDGET_MONTH = "2026-06"


def measure_budget() -> None:
    """Budgets on M12's shape (D-069 point 7, BB6): three members, a plan with 12 category
    allowances, and a month holding 3,000 discretionary purchases on a shared account, each
    reached by one of 12 category rules. Times report budget for the household and each member,
    budget set and a one-row import. Stops, as G9 says, if a report misses two seconds or budget
    set costs more than twice the import of one row."""
    from personal_finance.planning.budgets import PlanRequest, checked_plan, set_plan
    from personal_finance.reports.budget_report import budget_report

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, _ = recurring_ledger(root)
        conn.execute("INSERT INTO account (id, display_name, account_type) "
                     "VALUES ('spend', 'Spend', 'checking')")
        lines = [f"Q{number},{BUDGET_MONTH}-{1 + number % 28:02},{BUDGET_MONTH}-"
                 f"{1 + number % 28:02},SYNTHETIC STORE {BUDGET_STORES[number % 12]},"
                 f"-{1 + number % 90}.{number % 100:02},POSTED\n" for number in range(BUDGET_ROWS)]
        source = root / "spend.csv"
        source.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,"
                          "Status\n" + "".join(lines))
        (result,) = import_files(conn, [source], account_id="spend", layout=SYNTHETIC_CHECKING_V1)
        assert result.outcome == "imported", result
        conn.execute("BEGIN")
        classify_directly(conn, "spend", [
            (transaction_id, record_id, "purchase") for transaction_id, record_id in conn.execute(
                """SELECT link.transaction_id, link.source_record_id FROM transaction_source link
                   JOIN ledger_transaction entry ON entry.id = link.transaction_id
                   WHERE entry.account_id = 'spend'""").fetchall()])
        for number, name in enumerate(BUDGET_MEMBERS, start=1):
            conn.execute("INSERT INTO household_member (id, name) VALUES (?, ?)", (number, name))
        conn.execute("INSERT INTO household_share (id) VALUES ('h0')")
        conn.execute("INSERT INTO household_share_part VALUES ('h0', 1, 3400), ('h0', 2, 3300), "
                     "('h0', 3, 3300)")
        conn.execute("INSERT INTO household_share_event (share_id, event) VALUES ('h0', 'made')")
        for account, member in (("checking", None), ("card", None), ("savings", 1),
                                ("loan", 2), ("bills", 3), ("spend", None)):
            conn.execute("INSERT INTO account_attribution (id, account_id, member_id) "
                         "VALUES (?, ?, ?)", (f"d-{account}", account, member))
            conn.execute("INSERT INTO account_attribution_event (attribution_id, event) "
                         "VALUES (?, 'made')", (f"d-{account}",))
        store_categories = []
        for letter in BUDGET_STORES:
            number = conn.execute("INSERT INTO category (name) VALUES (?)",
                                  (f"Store {letter}",)).lastrowid
            store_categories.append(number)
            conn.execute("""INSERT INTO category_rule (id, account_id, category_id,
                                                       description_contains,
                                                       normalization_version)
                            VALUES (?, 'spend', ?, ?, 1)""",
                         (f"rule-{letter}", number, f"synthetic store {letter.lower()}"))
            conn.execute("INSERT INTO category_rule_event (rule_id, event) VALUES (?, 'made')",
                         (f"rule-{letter}",))
        conn.execute("""INSERT INTO budget_plan (id, effective_from, allowance_cents,
                                                 corrected_closed_month)
                        VALUES ('plan0', '2022-01', 3000000, 0)""")
        conn.executemany("INSERT INTO budget_plan_member_part VALUES ('plan0', ?, 1000000)",
                         [(1,), (2,), (3,)])
        conn.executemany("INSERT INTO budget_plan_category VALUES ('plan0', ?, 100000)",
                         [(number,) for number in store_categories])
        conn.execute("INSERT INTO budget_plan_event (plan_id, event) VALUES ('plan0', 'made')")
        write_transfer_effects(conn)
        conn.execute("COMMIT")
        build_seconds = time.perf_counter() - started

        as_of = date(2026, 6, 20)
        household = budget_report(conn, BUDGET_MONTH, as_of, None)
        members = [budget_report(conn, BUDGET_MONTH, as_of, name) for name in BUDGET_MEMBERS]
        transactions = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()[0]
        print(f"shape transactions={transactions} members={len(BUDGET_MEMBERS)} "
              f"categories={len(household.categories)} "
              f"discretionary={household.discretionary.count} "
              f"members_discretionary={[member.discretionary.count for member in members]} "
              f"unattributed={members[0].unattributed.count} build={build_seconds:.1f}s",
              flush=True)
        # The shape reaches the cost it claims: the month holds the 3,000 purchases, every
        # category allowance is reached, and every member's view divides them.
        assert transactions > 107_000
        assert household.discretionary.count >= BUDGET_ROWS
        assert len(household.categories) == 12
        assert all(allowance.spent_cents > 0 for allowance in household.categories)
        assert all(member.discretionary.count >= BUDGET_ROWS for member in members)
        assert sum(member.actual_cents for member in members) + members[0].unattributed.cents \
            == household.actual_cents
        conn.close()

        database = str(path)
        words = ["report", "budget", "--db", database, "--month", BUDGET_MONTH, "--as-of",
                 as_of.isoformat()]
        household_seconds = timed_command(*words)
        member_seconds = [timed_command(*words, "--member", name) for name in BUDGET_MEMBERS]

        conn = connect(path)
        request = PlanRequest("2026-07", "30000.00",
                              tuple(f"{name}=10000.00" for name in BUDGET_MEMBERS),
                              tuple(f"Store {letter}=1000.00" for letter in BUDGET_STORES))
        revision = checked_plan(conn, request, "2026-06").revision
        started = time.perf_counter()
        set_plan(conn, request, "2026-06", revision)
        set_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                         "LATER,2026-12-30,2026-12-30,SYNTHETIC LATER,-9.00,POSTED\n")
        started = time.perf_counter()
        (result,) = import_files(conn, [later], account_id="savings",
                                 layout=SYNTHETIC_CHECKING_V1)
        import_seconds = time.perf_counter() - started
        assert result.outcome == "imported"
        conn.close()
        print(f"report_budget={household_seconds:7.3f}s report_budget_members="
              f"{','.join(f'{seconds:.3f}' for seconds in member_seconds)}s "
              f"budget_set={set_seconds:7.3f}s one_import={import_seconds:7.3f}s", flush=True)
        stops = [name for name, seconds in (("report budget", household_seconds),
                                            *(("report budget --member", seconds)
                                              for seconds in member_seconds))
                 if seconds > 2]
        if set_seconds > 2 * import_seconds or set_seconds > 2:
            stops.append("budget set")
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


FUNDS_ACCOUNTS = ("checking", "savings", "fund1", "fund2", "fund3", "fund4")
FUNDS_AS_OF = date(2026, 6, 20)


def measure_funds() -> None:
    """Funds on M12's shape (D-070 point 9, GC4): 20 funds of every kind, 6 accounts holding
    assignments (one over-assigned), 2,000 consumptions of the bills, and 60 months of
    tax-eligible side income. Times report funds, report budget, fund assign, review consume
    and a one-row import. Stops, as G9 says, if a report misses two seconds or a write costs
    more than twice the import of one row, or above two seconds."""
    from personal_finance.planning.funds import (
        account_holding,
        assign,
        assignment_revision,
        load_assignments,
    )
    from personal_finance.reconcile.consumptions import consume_transaction
    from personal_finance.reports.fund_report import funds_report
    from personal_finance.reports.review_evidence import load_merge_evidence, transaction_revision

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, _ = recurring_ledger(root, side_tax_eligible=True)
        conn.execute("BEGIN")
        for number in range(1, 5):
            conn.execute("INSERT INTO account (id, display_name, account_type) "
                         "VALUES (?, ?, 'savings')", (f"fund{number}", f"Fund {number}"))
        for number, account in enumerate(FUNDS_ACCOUNTS):
            # fund4 is observed below what is assigned to it, so it is over-assigned.
            balance = 50_000 if account == "fund4" else 5_000_000
            conn.execute("INSERT INTO balance_observation (id, account_id, observed_on, "
                         "balance_cents) VALUES (?, ?, '2026-06-01', ?)",
                         (f"obs{number}", account, balance))
            conn.execute("INSERT INTO balance_observation_event (balance_observation_id, event) "
                         "VALUES (?, 'made')", (f"obs{number}",))
        funds = [("e0", "emergency", "months", {"month_count": 3}),
                 ("x0", "tax", "percent", {"basis_points": 2500})]
        for number in range(9):
            shape = ("monthly", "percent", "target_by")[number % 3]
            terms = ({"amount_cents": 20_000}, {"basis_points": 500},
                     {"amount_cents": 1_000_000, "by_month": "2027-12"})[number % 3]
            funds.append((f"g{number}", "goal", shape, terms))
        for number in range(9):
            if number % 3 == 0:
                funds.append((f"r{number}", "reserve", "due",
                              {"amount_cents": 300_000, "due_date": "2026-12-01"}))
            else:
                funds.append((f"r{number}", "reserve", "recurring",
                              {"amount_cents": 150_000, "cadence": "annual",
                               "first_day": 1 + number, "anchor": f"2022-{number:02}-"
                                                                  f"{1 + number:02}"}))
        for fund_id, kind, shape, terms in funds:
            conn.execute("INSERT INTO fund (id, name, kind) VALUES (?, ?, ?)",
                         (fund_id, f"Fund {fund_id}", kind))
            columns = ", ".join(terms)
            conn.execute(f"INSERT INTO fund_terms (fund_id, effective_from, shape, {columns}) "
                         f"VALUES (?, '2022-01-01', ?, {', '.join('?' for _ in terms)})",
                         (fund_id, shape, *terms.values()))
            conn.execute("INSERT INTO fund_event (fund_id, event) VALUES (?, 'made')",
                         (fund_id,))
        for number, (fund_id, kind, _, _) in enumerate(funds):
            account = FUNDS_ACCOUNTS[number % len(FUNDS_ACCOUNTS)]
            conn.execute("INSERT INTO fund_assignment (id, fund_id, account_id, amount_cents, "
                         "created_at) VALUES (?, ?, ?, 100000, '2022-01-01T00:00:00.000Z')",
                         (f"a{number}", fund_id, account))
            conn.execute("INSERT INTO fund_assignment_event (assignment_id, event) "
                         "VALUES (?, 'made')", (f"a{number}",))
        # The emergency fund is never consumed, so its assignment on fund4, beyond fund4's
        # balance, keeps that account over-assigned whatever the consumptions take.
        conn.execute("INSERT INTO fund_assignment (id, fund_id, account_id, amount_cents, "
                     "created_at) VALUES ('over', 'e0', 'fund4', 300000, "
                     "'2022-01-01T00:00:00.000Z')")
        conn.execute("INSERT INTO fund_assignment_event (assignment_id, event) "
                     "VALUES ('over', 'made')")
        conn.execute("INSERT INTO fund_priority_event (list_id, event) VALUES ('p0', 'made')")
        conn.executemany("INSERT INTO fund_priority (list_id, position, fund_id) "
                         "VALUES ('p0', ?, ?)",
                         [(position, fund_id) for position, (fund_id, kind, _, _)
                          in enumerate((fund for fund in funds if fund[1] != "tax"), start=1)])
        bills = conn.execute(
            """SELECT link.transaction_id, link.source_record_id FROM transaction_source link
               JOIN ledger_transaction entry ON entry.id = link.transaction_id
               JOIN transaction_classification kind ON kind.transaction_id = entry.id
               WHERE entry.account_id = 'bills' AND kind.financial_type = 'purchase'
               ORDER BY entry.external_id""").fetchall()
        consumed = [fund for fund in funds if fund[1] != "emergency"]
        for number, (transaction_id, record_id) in enumerate(bills[:FUNDS_CONSUMPTIONS]):
            consumption_id = f"c{number}"
            conn.execute("INSERT INTO fund_consumption (id, account_id, fund_id, "
                         "target_transaction_id, target_revision) VALUES (?, 'bills', ?, ?, "
                         "'t13-0')", (consumption_id, consumed[number % len(consumed)][0],
                                      transaction_id))
            conn.execute("INSERT INTO fund_consumption_record (consumption_id, source_record_id) "
                         "VALUES (?, ?)", (consumption_id, record_id))
            conn.execute("INSERT INTO fund_consumption_event (consumption_id, event) "
                         "VALUES (?, 'made')", (consumption_id,))
        write_transfer_effects(conn)
        conn.execute("COMMIT")
        build_seconds = time.perf_counter() - started

        report = funds_report(conn, FUNDS_AS_OF)
        applied = conn.execute("SELECT COUNT(*) FROM transaction_fund_consumption "
                               "WHERE state = 'applied'").fetchone()[0]
        tax = next(view for view in report.view.funds if view.fund.kind == "tax")
        over = [holding for holding in report.view.holdings if holding.over_assigned_cents]
        holding_accounts = {holding.account_id for holding in report.view.holdings
                            if holding.assignments}
        print(f"shape funds={len(report.view.funds)} accounts_holding={len(holding_accounts)} "
              f"over_assigned={len(over)} consumptions={applied} "
              f"tax_occurrences={tax.tax_accrual.occurrences} build={build_seconds:.1f}s",
              flush=True)
        # The shape reaches the cost it claims.
        assert len(report.view.funds) == 20
        assert {fund.fund.kind for fund in report.view.funds} == {"goal", "emergency", "reserve",
                                                                  "tax"}
        assert holding_accounts == set(FUNDS_ACCOUNTS) and len(over) == 1
        assert applied == FUNDS_CONSUMPTIONS
        assert tax.tax_accrual.occurrences >= 60
        conn.close()

        database = str(path)
        as_of = FUNDS_AS_OF.isoformat()
        report_seconds = timed_command("report", "funds", "--db", database, "--as-of", as_of)
        budget_seconds = timed_command("report", "budget", "--db", database, "--month",
                                       as_of[:7], "--as-of", as_of)

        conn = connect(path)
        conn.execute("INSERT INTO fund (id, name, kind) VALUES ('late', 'Late', 'goal')")
        conn.execute("INSERT INTO fund_terms (fund_id, effective_from, shape, amount_cents) "
                     "VALUES ('late', '2026-06-01', 'monthly', 1000)")
        conn.execute("INSERT INTO fund_event (fund_id, event) VALUES ('late', 'made')")
        conn.commit()
        assignments = load_assignments(conn)
        revision = assignment_revision(account_holding(conn, "savings", as_of, assignments),
                                       "late", assignments)
        started = time.perf_counter()
        assign(conn, "late", "savings", "10.00", as_of, revision)
        assign_seconds = time.perf_counter() - started
        (transaction_id, _) = bills[FUNDS_CONSUMPTIONS]
        revision = transaction_revision(load_merge_evidence(conn, transaction_id))
        started = time.perf_counter()
        consume_transaction(conn, "bills", transaction_id, revision, "r0")
        consume_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                         "LATER,2026-12-30,2026-12-30,SYNTHETIC LATER,-9.00,POSTED\n")
        started = time.perf_counter()
        (result,) = import_files(conn, [later], account_id="savings",
                                 layout=SYNTHETIC_CHECKING_V1)
        import_seconds = time.perf_counter() - started
        assert result.outcome == "imported"
        conn.close()
        print(f"report_funds={report_seconds:7.3f}s report_budget={budget_seconds:7.3f}s "
              f"fund_assign={assign_seconds:7.3f}s review_consume={consume_seconds:7.3f}s "
              f"one_import={import_seconds:7.3f}s", flush=True)
        stops = [name for name, seconds in (("report funds", report_seconds),
                                            ("report budget", budget_seconds)) if seconds > 2]
        stops += [name for name, seconds in (("fund assign", assign_seconds),
                                             ("review consume", consume_seconds))
                  if seconds > 2 * import_seconds or seconds > 2]
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


SAFE_AS_OF_DATES = [date(2026, month, 3 + month) for month in range(1, 13)]


def safe_to_spend_ledger(root: Path):
    """--safe-to-spend's shape: --recurring's, with every input safe to spend reads, the
    household timezone and a buffer set. Returns the connection, the path, and the numbers of
    liquid accounts and funds."""
    conn, path, _ = recurring_ledger(root, side_tax_eligible=True)
    conn.execute("BEGIN")
    conn.execute("INSERT INTO ledger_setting (id, setting_key, value) "
                 "VALUES ('zone', 'household_timezone', 'America/Chicago')")
    conn.execute("INSERT INTO ledger_setting_event (setting_id, event) VALUES ('zone', 'made')")
    conn.execute("INSERT INTO ledger_setting (id, setting_key, value) "
                 "VALUES ('buffer', 'checking_buffer_cents', '50000')")
    conn.execute("INSERT INTO ledger_setting_event (setting_id, event) "
                 "VALUES ('buffer', 'made')")
    conn.execute("INSERT INTO budget_plan (id, effective_from, allowance_cents, "
                 "corrected_closed_month) VALUES ('plan', '2022-01', 300000, 0)")
    conn.execute("INSERT INTO budget_plan_event (plan_id, event) VALUES ('plan', 'made')")
    liquid = ("bills", "checking", "savings")
    for number, account in enumerate(liquid):
        conn.execute("INSERT INTO account_liquidity (id, account_id) VALUES (?, ?)",
                     (f"lq{number}", account))
        conn.execute("INSERT INTO account_liquidity_event (designation_id, event) "
                     "VALUES (?, 'made')", (f"lq{number}",))
        for month in range(1, 13):
            observation = f"sobs{number}-{month}"
            balance = 5_000_000 if month % 2 else 100_000
            conn.execute("INSERT INTO balance_observation (id, account_id, observed_on, "
                         "balance_cents) VALUES (?, ?, ?, ?)",
                         (observation, account, f"2026-{month:02}-01", balance))
            conn.execute("INSERT INTO balance_observation_event "
                         "(balance_observation_id, event) VALUES (?, 'made')",
                         (observation,))
    funds = (("tax", "tax", "percent", {"basis_points": 2500}),
             ("reserve", "reserve", "recurring",
              {"amount_cents": 120_000, "cadence": "annual", "first_day": 15,
               "anchor": "2022-03-15"}),
             ("rainy", "emergency", "minimum", {"amount_cents": 2_000_000}),
             ("goal", "goal", "monthly", {"amount_cents": 40_000}))
    for fund_id, kind, shape, terms in funds:
        conn.execute("INSERT INTO fund (id, name, kind) VALUES (?, ?, ?)",
                     (fund_id, f"Fund {fund_id}", kind))
        columns = ", ".join(terms)
        conn.execute(f"INSERT INTO fund_terms (fund_id, effective_from, shape, {columns}) "
                     f"VALUES (?, '2022-01-01', ?, {', '.join('?' for _ in terms)})",
                     (fund_id, shape, *terms.values()))
        conn.execute("INSERT INTO fund_event (fund_id, event) VALUES (?, 'made')",
                     (fund_id,))
        if kind != "tax":
            conn.execute("INSERT INTO fund_assignment (id, fund_id, account_id, "
                         "amount_cents, created_at) VALUES (?, ?, 'savings', 10000, "
                         "'2022-01-01T00:00:00.000Z')", (f"sa{fund_id}", fund_id))
            conn.execute("INSERT INTO fund_assignment_event (assignment_id, event) "
                         "VALUES (?, 'made')", (f"sa{fund_id}",))
    conn.execute("INSERT INTO fund_restoration (id, fund_id, effective_from, monthly_cents) "
                 "VALUES ('restore', 'rainy', '2022-01-01', 25000)")
    conn.execute("INSERT INTO fund_restoration_event (restoration_id, event) "
                 "VALUES ('restore', 'made')")
    for number in range(2):
        account = f"sloan{number}"
        conn.execute("INSERT INTO account (id, display_name, account_type) "
                     "VALUES (?, ?, 'loan')", (account, f"Safe loan {number}"))
        conn.execute("INSERT INTO loan_terms (id, account_id, due_day) VALUES (?, ?, ?)",
                     (f"st{number}", account, 5 + number * 10))
        conn.execute("INSERT INTO loan_terms_event (terms_id, event) VALUES (?, 'made')",
                     (f"st{number}",))
        conn.execute("INSERT INTO loan_rate_period (terms_id, effective_from, "
                     "rate_millionths) VALUES (?, '2022-01-01', 6875000)", (f"st{number}",))
        conn.execute("INSERT INTO loan_payment_period (terms_id, effective_from, "
                     "payment_cents) VALUES (?, '2022-01-01', ?)",
                     (f"st{number}", 150_000 + number))
    # Bill 00, on the 1st, covers the first loan.
    conn.execute("INSERT INTO obligation_coverage (id, obligation_id, loan_account_id) "
                 "VALUES ('cover', 'ob0', 'sloan0')")
    conn.execute("INSERT INTO obligation_coverage_event (coverage_id, event) "
                 "VALUES ('cover', 'made')")
    conn.execute("COMMIT")
    return conn, path, len(liquid), len(funds)


def measure_safe_to_spend() -> None:
    """Safe to spend on M12's shape (D-072 point 8, SB7): the --recurring shape's sources and
    bills, with a budget plan, a tax reserve, a reserve, an emergency fund restored monthly and a
    goal, 2 loans with terms (one covered by a bill), 3 liquidity accounts observed monthly, high
    in odd months and low in even ones, and a buffer. Times safe-to-spend and dashboard at 12
    as-of dates and reports the slowest. Asserts every protected row is reached and each
    constraint limits at some date. Stops, as G9 says, if either misses one second."""
    from personal_finance.reports.safe_to_spend import BUDGET, LIQUIDITY, ROWS, safe_to_spend

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, liquid_count, fund_count = safe_to_spend_ledger(root)
        build_seconds = time.perf_counter() - started

        rows_reached, limiting = set(), set()
        for as_of in SAFE_AS_OF_DATES:
            view = safe_to_spend(conn, as_of)
            rows_reached |= {item.row for item in view.items}
            limiting.add(view.limiting)
            assert not any(item.entry_kind == "loan" and item.entry_id == "sloan0"
                           for item in view.items)
            entries = [(item.entry_kind, item.entry_id) for item in view.items]
            assert len(entries) == len(set(entries))
        (transactions,) = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()
        print(f"shape transactions={transactions} liquid={liquid_count} funds={fund_count} "
              f"loans=2 rows_reached={len(rows_reached)} limiting={sorted(limiting)} "
              f"build={build_seconds:.1f}s", flush=True)
        # The shape reaches the cost it claims.
        assert transactions >= 100_000
        assert rows_reached == set(ROWS), set(ROWS) - rows_reached
        assert limiting == {BUDGET, LIQUIDITY}
        conn.close()

        database = str(path)
        slowest = {"safe-to-spend": (0.0, None), "dashboard": (0.0, None)}
        for as_of in SAFE_AS_OF_DATES:
            for command in slowest:
                seconds = timed_command(command, "--db", database, "--as-of", as_of.isoformat())
                if seconds > slowest[command][0]:
                    slowest[command] = (seconds, as_of.isoformat())
        print(" ".join(f"{command}={seconds:7.3f}s (as of {as_of})"
                       for command, (seconds, as_of) in slowest.items()), flush=True)
        stops = [command for command, (seconds, _) in slowest.items() if seconds > 1]
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


SCENARIO_AS_OF = date(2026, 7, 15)
# Ten templates cycled four to a scenario, so the 40 inputs hold every kind, replacements of a
# source, an obligation and a reserve, and a home purchase (D-074 point 8).
SCENARIO_TEMPLATES = (
    dict(kind="income", from_date="2026-08-01", amount="2600.00", cadence="biweekly",
         anchor="2026-08-07", replaces="src0"),
    dict(kind="expense", from_date="2026-08-01", amount="90.00", cadence="monthly:10",
         replaces="ob1"),
    dict(kind="annual_expense", from_date="2026-08-01", amount="1500.00", cadence="annual:03-15",
         replaces="reserve"),
    dict(kind="home_purchase", from_date="2026-09-10", price="300000.00",
         down_payment="60000.00", closing_costs="6000.00", loan_rate="6.5", loan_months="360",
         ownership_costs="450.00"),
    dict(kind="bonus", from_date="2026-12-15", amount="3000.00", confirmed=True),
    dict(kind="purchase", from_date="2026-10-01", amount="1800.00"),
    dict(kind="loan_payoff", from_date="2026-09-01", amount="5000.00", loan_account_id="sloan1"),
    dict(kind="borrowing", from_date="2026-09-01", amount="10000.00", loan_rate="9.5",
         loan_months="48"),
    dict(kind="income", from_date="2026-08-01", amount="400.00", cadence="monthly:20",
         account_id="bills", match="synthetic tutoring"),
    dict(kind="expense", from_date="2026-08-01", amount="45.00", cadence="monthly:25",
         account_id="bills", match="synthetic gym", uncertain=True),
)


def measure_scenarios() -> None:
    """Scenarios on --safe-to-spend's shape (D-074 point 8, XC2): 10 scenarios with 40 inputs of
    every kind. Times scenario compare at 24 months for each and at 120 for three, and promote
    and its undo for the first. Stops, as G9 says, if compare misses 2.0s at 24 months or 5.0s
    at 120."""
    from personal_finance.planning import scenarios
    from personal_finance.planning.promotions import (
        active_promotion,
        promotion_revision,
        promotion_undo_revision,
    )

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, _, _ = safe_to_spend_ledger(root)
        build_seconds = time.perf_counter() - started
        scenario_ids = []
        for number in range(10):
            scenario_id = scenarios.add_scenario(conn, f"Scenario {number}", number % 2 == 1)
            scenario_ids.append(scenario_id)
            for step in range(4):
                template = SCENARIO_TEMPLATES[(number * 4 + step) % len(SCENARIO_TEMPLATES)]
                scenario = scenarios.find_scenario(conn, scenario_id)
                scenarios.add_input(conn, scenario_id, scenarios.InputRequest(**template),
                                    scenarios.scenario_revision(scenario, scenarios.ADD_INPUT))
        kinds = {kind for (kind,) in conn.execute("SELECT kind FROM scenario_input")}
        (inputs,) = conn.execute("SELECT COUNT(*) FROM scenario_input").fetchone()
        (replacing,) = conn.execute(
            "SELECT COUNT(DISTINCT replaces_kind) FROM scenario_input").fetchone()
        (transactions,) = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()
        print(f"shape transactions={transactions} scenarios=10 inputs={inputs} "
              f"kinds={len(kinds)} replaced_kinds={replacing} build={build_seconds:.1f}s",
              flush=True)
        # The shape reaches the cost it claims.
        assert transactions >= 100_000 and inputs == 40
        assert kinds == set(scenarios.KINDS) and replacing == 3
        first = scenarios.find_scenario(conn, scenario_ids[0])
        promote_token = promotion_revision(conn, first)
        conn.close()

        database = str(path)
        as_of = SCENARIO_AS_OF.isoformat()
        # The first command after a long build runs slow: it is run and not counted.
        timed_command("scenario", "compare", scenario_ids[0], "--db", database, "--as-of", as_of)
        at_24 = [timed_command("scenario", "compare", scenario_id, "--db", database, "--as-of",
                               as_of) for scenario_id in scenario_ids]
        at_120 = [timed_command("scenario", "compare", scenario_id, "--db", database, "--as-of",
                                as_of, "--months", "120") for scenario_id in scenario_ids[:3]]
        promote_seconds = timed_command("scenario", "promote", scenario_ids[0], "--db", database,
                                        "--as-of", as_of, "--revision", promote_token)
        conn = connect(path)
        promotion = active_promotion(conn, scenario_ids[0])
        made = len(promotion.entries)
        undo_token = promotion_undo_revision(scenarios.find_scenario(conn, scenario_ids[0]),
                                             promotion)
        conn.close()
        undo_seconds = timed_command("scenario", "promotion", "undo", scenario_ids[0], "--db",
                                     database, "--revision", undo_token)
        print(f"compare 24 months: slowest={max(at_24):7.3f}s median="
              f"{sorted(at_24)[len(at_24) // 2]:7.3f}s; 120 months: slowest={max(at_120):7.3f}s; "
              f"promote={promote_seconds:7.3f}s making {made} entries; "
              f"promotion undo={undo_seconds:7.3f}s", flush=True)
        stops = [name for name, seconds, target in (("compare at 24", max(at_24), 2.0),
                                                     ("compare at 120", max(at_120), 5.0),
                                                     ("promote", promote_seconds, 2.0),
                                                     ("promotion undo", undo_seconds, 2.0))
                 if seconds > target]
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


SNAPSHOT_AS_OF = date(2026, 12, 20)


def measure_snapshot() -> None:
    """A snapshot on --safe-to-spend's shape (D-075, VB4): generation in one read transaction
    with a 90-day window, the file's size, and verify. The gated write is not timed: build/ is
    inside the git work tree, which the destination check refuses, and it is one fsynced write.
    Stops, as G9 says, if generation misses 5.0s or the file 5 MB."""
    from personal_finance.snapshot import files

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, _, _ = safe_to_spend_ledger(root)
        build_seconds = time.perf_counter() - started
        (transactions,) = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()
        (months,) = conn.execute(
            "SELECT COUNT(DISTINCT substr(COALESCE(transaction_date, posting_date), 1, 7)) "
            "FROM ledger_transaction").fetchone()
        conn.close()
        reader = connect(path, read_only=True)
        # The first read after a long build runs slow: it is run and not counted.
        files.build_in_one_read(reader, SNAPSHOT_AS_OF, 90,
                                "00000000-0000-4000-8000-000000000001",
                                "2026-12-20T12:00:00.000Z")
        started = time.perf_counter()
        data = files.build_in_one_read(reader, SNAPSHOT_AS_OF, 90,
                                       "00000000-0000-4000-8000-000000000002",
                                       "2026-12-20T12:00:00.000Z")
        generate_seconds = time.perf_counter() - started
        started = time.perf_counter()
        document = files.verified(data)
        verify_seconds = time.perf_counter() - started
        reader.close()
        window = len(document["content"]["transactions"])
        print(f"shape transactions={transactions} months={months} window_transactions={window} "
              f"build={build_seconds:.1f}s", flush=True)
        assert transactions >= 100_000 and months >= 60 and window >= 4_000
        megabytes = len(data) / 1_000_000
        print(f"generate={generate_seconds:7.3f}s size={len(data)} bytes ({megabytes:.2f} MB) "
              f"verify={verify_seconds:7.3f}s", flush=True)
        stops = [name for name, missed in (("generation", generate_seconds > 5.0),
                                           ("size", len(data) > 5_000_000)) if missed]
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


SYNC_DELIVERIES = 20


def measure_sync() -> None:
    """Pairing and delivery on --safe-to-spend's shape (D-076, YC2): a snapshot with a 366-day
    window, so it reaches the 5 MB D-076 names, then pairing and 20 deliveries to the reference
    client over real loopback TCP, each fetched, checked, installed and acknowledged. Times are
    round trips seen by the client, an upper bound on the server's share. Stops, as G9 says, if
    pairing misses 1.0s or a delivery 2.0s."""
    import socket
    import sqlite3
    import threading

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from sync_reference_client import ReferenceClient

    from personal_finance.snapshot import files
    from personal_finance.sync import devices, identity
    from personal_finance.sync.pairing import pairing_payload
    from personal_finance.sync.server import PAIR, SERVE, SyncServer, tls_context

    class LoopbackServer(SyncServer):
        @staticmethod
        def checked_address(address):
            assert address == "127.0.0.1"

    def threaded(server):
        thread = threading.Thread(target=server.run)
        thread.start()
        return thread

    def shared_connection(path):
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True, autocommit=True,
                               check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, _, _ = safe_to_spend_ledger(root)
        build_seconds = time.perf_counter() - started
        conn.close()
        sync_folder = identity.prepared_sync_folder(path)
        conn = shared_connection(path)
        made = devices.create_identity(conn, sync_folder)
        key_path, certificate_path = identity.checked_identity_files(made, sync_folder)
        context = tls_context(certificate_path, key_path)
        utc_now = lambda: datetime.now(timezone.utc)  # noqa: E731

        pairing = LoopbackServer("127.0.0.1", 0, context, conn, mode=PAIR, minutes=2,
                                 utc_now=utc_now, device_name="Benchmark")
        window = devices.open_window(conn, made, "127.0.0.1", pairing.server_port, utc_now())
        pairing.window_id = window.window_id
        thread = threaded(pairing)
        install = root / "phone"
        install.mkdir()
        client = ReferenceClient(
            install, lambda: socket.create_connection(("127.0.0.1", pairing.server_port)))
        started = time.perf_counter()
        assert client.pair(pairing_payload("127.0.0.1", pairing.server_port,
                                           made.certificate_sha256,
                                           window.pairing_secret)).status == 200
        pair_seconds = time.perf_counter() - started
        thread.join()
        pairing.server_close()

        reader = connect(path, read_only=True)
        files.build_in_one_read(reader, SNAPSHOT_AS_OF, 366,
                                "00000000-0000-4000-8000-000000000001",
                                "2026-12-20T12:00:00.000Z")
        started = time.perf_counter()
        data = files.build_in_one_read(reader, SNAPSHOT_AS_OF, 366,
                                       "00000000-0000-4000-8000-000000000002",
                                       "2026-12-20T12:00:00.000Z")
        generate_seconds = time.perf_counter() - started
        reader.close()
        serving = LoopbackServer("127.0.0.1", 0, context, conn, mode=SERVE, minutes=10,
                                 utc_now=utc_now, document=files.verified(data), snapshot=data)
        thread = threaded(serving)
        client.connect = lambda: socket.create_connection(("127.0.0.1", serving.server_port))
        client.port = serving.server_port
        fetches, syncs = [], []
        for _ in range(SYNC_DELIVERIES):
            started = time.perf_counter()
            assert client.fetch().status == 200
            fetches.append(time.perf_counter() - started)
            started = time.perf_counter()
            client.sync()
            syncs.append(time.perf_counter() - started)
        serving.finished = True
        thread.join()
        serving.server_close()
        conn.close()
        megabytes = len(data) / 1_000_000
        print(f"shape build={build_seconds:.1f}s snapshot={len(data)} bytes ({megabytes:.2f} MB), "
              f"366-day window, generated in {generate_seconds:.3f}s", flush=True)
        assert len(data) >= 5_000_000, "the shape does not reach D-076's 5 MB"
        print(f"pair={pair_seconds:7.3f}s", flush=True)
        print(f"fetch, {SYNC_DELIVERIES} round trips: median={sorted(fetches)[len(fetches) // 2]:.3f}s "
              f"max={max(fetches):.3f}s", flush=True)
        print(f"sync (fetch, check, install, acknowledge): median={sorted(syncs)[len(syncs) // 2]:.3f}s "
              f"max={max(syncs):.3f}s", flush=True)
        print(f"served={serving.counts['served']} acknowledged={serving.counts['acknowledged']} "
              f"refused={serving.counts['refused']}", flush=True)
        stops = [name for name, missed in (("pairing", pair_seconds > 1.0),
                                           ("delivery", max(fetches) > 2.0)) if missed]
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


EVERYTHING_READS = [
    ("totals",), ("report", "monthly"), ("report", "household"), ("report", "income"),
    ("report", "budget", "--month", "2026-12", "--as-of", "2026-12-20"),
    ("report", "funds", "--as-of", "2026-12-20"), ("report", "net-worth", "--as-of", "2026-12-20"),
    ("report", "loans", "--as-of", "2026-12-20"), ("safe-to-spend", "--as-of", "2026-12-20"),
    ("dashboard", "--as-of", "2026-12-20"), ("transactions",), ("review", "list"),
    ("funds", "--as-of", "2026-12-20"), ("obligations",), ("scenarios",), ("snapshots",),
    ("storage",),
]


def measure_everything() -> None:
    """Every read on --safe-to-spend's shape (D-077 point 3, ZB1), each timed once after one
    untimed run, with 10 scenarios added; then a full-scale backup, verify and restore, every
    read compared byte for byte between the ledger and its restored copy, and migration 0036
    timed on a copy set back to 35. Stops, as G9 says, if a report misses 2.0s."""
    import contextlib
    import io
    import shutil
    import sqlite3

    sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "scenarios"),
                    str(Path(__file__).resolve().parents[1])]
    from personal_finance.cli import main

    def run(*words):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(words))
        return code, out.getvalue(), err.getvalue()

    def placed(words, path):
        position = 2 if words[0] in ("report", "review") else 1
        return [*words[:position], "--db", str(path), *words[position:]]

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, _, _ = safe_to_spend_ledger(root)
        build_seconds = time.perf_counter() - started
        (transactions,) = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()
        (accounts,) = conn.execute("SELECT COUNT(*) FROM account").fetchone()
        conn.close()
        for number in range(10):
            assert run("scenario", "add", "--db", str(path), "--name", f"Scenario {number}")[0] == 0
        print(f"shape transactions={transactions} accounts={accounts} build={build_seconds:.1f}s",
              flush=True)
        assert transactions >= 100_000
        timings, outputs = {}, {}
        for words in EVERYTHING_READS:
            run(*placed(words, path))
            started = time.perf_counter()
            outputs[words] = run(*placed(words, path))
            timings[" ".join(words[:2])] = time.perf_counter() - started
            assert outputs[words][0] == 0, (words, outputs[words][2])
        for name, seconds in timings.items():
            print(f"{name:<24} {seconds:7.3f}s", flush=True)
        steps = {}
        for name, words in (("backup create", ["backup", "create", "--db", str(path), "--to",
                                               str(root / "backup")]),
                            ("backup verify", ["backup", "verify", "--from", str(root / "backup")]),
                            ("backup restore", ["backup", "restore", "--from",
                                                str(root / "backup"), "--to",
                                                str(root / "restored.db")])):
            started = time.perf_counter()
            code, _, err = run(*words)
            steps[name] = time.perf_counter() - started
            assert code == 0, (name, err)
        differing = [words for words in EVERYTHING_READS
                     if words != ("storage",)
                     and run(*placed(words, root / "restored.db")) != outputs[words]]
        set_back = root / "at-35.db"
        shutil.copy(path, set_back)
        back = sqlite3.connect(set_back, isolation_level=None)
        for table in ("sync_acknowledgement", "sync_delivery", "paired_device_event",
                      "paired_device", "pairing_window_event", "pairing_window",
                      "sync_identity_event", "sync_identity"):
            back.execute(f"DROP TABLE {table}")
        back.execute("PRAGMA user_version = 35")
        back.close()
        started = time.perf_counter()
        assert run("migrate", "--db", str(set_back))[0] == 0
        steps["migrate 35 to 36"] = time.perf_counter() - started
        for name, seconds in steps.items():
            print(f"{name:<24} {seconds:7.3f}s", flush=True)
        print(f"restored copy: {len(EVERYTHING_READS) - 1 - len(differing)} of "
              f"{len(EVERYTHING_READS) - 1} reads byte for byte the same; differing: {differing}",
              flush=True)
        stops = [name for name, seconds in timings.items() if seconds > 2.0]
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


FUNDS_CONSUMPTIONS = 2_000

LOANS_BREAKDOWNS = 5_000
LOANS_AS_OF = date(2026, 12, 20)
LOAN_MONTHS = [f"{2017 + number // 12}-{1 + number % 12:02}" for number in range(120)]


def measure_loans() -> None:
    """Loans on M12's shape (D-071 point 9, LC4): 8 loans (2 graduated with 6 steps each, 1
    aggregate with 3 subaccounts), 120 months of payments, 5,000 of them confirmed and broken
    down. Times report net-worth, report loans, loan payoff with all three orders, totals and
    review breakdown. Stops, as G9 says, if a report misses two seconds, if totals crosses 2.0s
    (D-071 point 9), or if review breakdown costs more than twice the import of one row."""
    from personal_finance.reconcile.breakdowns import break_down
    from personal_finance.reports.review_evidence import load_merge_evidence, transaction_revision

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, _ = recurring_ledger(root)
        loans = [f"loan{number}" for number in range(8)]
        conn.execute("INSERT INTO account (id, display_name, account_type) "
                     "VALUES ('payer', 'Payer', 'checking')")
        for loan in loans:
            conn.execute("INSERT INTO account (id, display_name, account_type) "
                         "VALUES (?, ?, 'loan')", (loan, loan.capitalize()))
        rows, cents_by_row = [], {}
        for number in range(LOANS_BREAKDOWNS + 1):
            month = LOAN_MONTHS[number % len(LOAN_MONTHS)]
            day = 1 + number % 28
            cents = 50_000 + number % 1_000
            rows.append(f"L{number},{month}-{day:02},{month}-{day:02},SYNTHETIC LOAN "
                        f"{number % 8},-{cents // 100}.{cents % 100:02},POSTED\n")
            cents_by_row[f"L{number}"] = cents
        source = root / "payer.csv"
        source.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,"
                          "Status\n" + "".join(rows))
        (result,) = import_files(conn, [source], account_id="payer", layout=SYNTHETIC_CHECKING_V1)
        assert result.outcome == "imported", result
        links = {external_id: (transaction_id, record_id)
                 for external_id, transaction_id, record_id in conn.execute(
                     """SELECT entry.external_id, link.transaction_id, link.source_record_id
                        FROM transaction_source link
                        JOIN ledger_transaction entry ON entry.id = link.transaction_id
                        WHERE entry.account_id = 'payer'""")}
        conn.execute("BEGIN")
        classify_directly(conn, "payer", [(*links[f"L{number}"], "loan_payment")
                                          for number in range(LOANS_BREAKDOWNS + 1)])
        for number in range(LOANS_BREAKDOWNS + 1):
            transaction_id, record_id = links[f"L{number}"]
            statement_id = f"ol{number:06}"
            conn.execute("""INSERT INTO one_sided_transfer (id, account_id, counterpart_account_id,
                                                         target_transaction_id, target_revision)
                            VALUES (?, 'payer', ?, ?, 't13-0')""",
                         (statement_id, loans[number % 8], transaction_id))
            conn.execute("INSERT INTO one_sided_transfer_record VALUES (?, ?)",
                         (statement_id, record_id))
            conn.execute("INSERT INTO one_sided_transfer_event (one_sided_transfer_id, event) "
                         "VALUES (?, 'made')", (statement_id,))
            if number == LOANS_BREAKDOWNS:
                continue  # left for the timed review breakdown
            breakdown_id = f"lb{number:06}"
            conn.execute("""INSERT INTO loan_payment_breakdown (id, account_id, breakdown,
                                                             target_transaction_id,
                                                             target_revision)
                            VALUES (?, 'payer', ?, ?, 't13-0')""",
                         (breakdown_id, f"{cents_by_row[f'L{number}'] // 5}:{number % 3 * 100}",
                          transaction_id))
            conn.execute("INSERT INTO loan_payment_breakdown_record VALUES (?, ?)",
                         (breakdown_id, record_id))
            conn.execute("INSERT INTO loan_payment_breakdown_event (breakdown_id, event) "
                         "VALUES (?, 'made')", (breakdown_id,))
        for number, loan in enumerate(loans):
            conn.execute("INSERT INTO loan_terms (id, account_id, due_day) VALUES (?, ?, ?)",
                         (f"t{number}", loan, 1 + number))
            conn.execute("INSERT INTO loan_terms_event (terms_id, event) VALUES (?, 'made')",
                         (f"t{number}",))
            steps = 6 if number < 2 else 1
            for step in range(steps):
                start = f"{2017 + step}-01-01"
                conn.execute("INSERT INTO loan_rate_period (terms_id, effective_from, "
                             "rate_millionths) VALUES (?, ?, ?)",
                             (f"t{number}", start, 3_000_000 + number * 500_000 + step * 10_000))
                conn.execute("INSERT INTO loan_payment_period (terms_id, effective_from, "
                             "payment_cents) VALUES (?, ?, ?)",
                             (f"t{number}", start, 40_000 + step * 2_000))
            conn.execute("INSERT INTO balance_observation (id, account_id, observed_on, "
                         "balance_cents) VALUES (?, ?, '2026-12-01', ?)",
                         (f"lo{number}", loan, -(5_000_000 + number * 1_000_000)))
            conn.execute("INSERT INTO balance_observation_event (balance_observation_id, event) "
                         "VALUES (?, 'made')", (f"lo{number}",))
        # loan7 is the aggregate of loan4 to loan6.
        for number, sub in enumerate(("loan4", "loan5", "loan6")):
            conn.execute("INSERT INTO account_link (id, subaccount_id, aggregate_id) "
                         "VALUES (?, ?, 'loan7')", (f"k{number}", sub))
            conn.execute("INSERT INTO account_link_event (link_id, event) VALUES (?, 'made')",
                         (f"k{number}",))
        conn.execute("INSERT INTO payoff_plan (id, order_kind, custom_order, extra_cents) "
                     "VALUES ('p0', 'custom', ?, 50000)", (",".join(reversed(loans)),))
        conn.execute("INSERT INTO payoff_plan_event (plan_id, event) VALUES ('p0', 'made')")
        write_transfer_effects(conn)
        conn.execute("COMMIT")
        build_seconds = time.perf_counter() - started

        applied = conn.execute("SELECT COUNT(*) FROM transaction_loan_breakdown "
                               "WHERE state = 'applied'").fetchone()[0]
        graduated = conn.execute("SELECT COUNT(*) FROM (SELECT terms_id FROM loan_payment_period "
                                 "GROUP BY terms_id HAVING COUNT(*) = 6)").fetchone()[0]
        transactions = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()[0]
        print(f"shape transactions={transactions} loans={len(loans)} graduated={graduated} "
              f"links=3 breakdowns={applied} build={build_seconds:.1f}s", flush=True)
        # The shape reaches the cost it claims.
        assert transactions > 107_000
        assert applied == LOANS_BREAKDOWNS and graduated == 2
        conn.close()

        database = str(path)
        as_of = LOANS_AS_OF.isoformat()
        net_worth_seconds = timed_command("report", "net-worth", "--db", database, "--as-of",
                                          as_of)
        loans_seconds = timed_command("report", "loans", "--db", database, "--as-of", as_of)
        payoff_seconds = timed_command("loan", "payoff", "--db", database, "--as-of", as_of)
        totals_seconds = timed_command("totals", "--db", database)

        conn = connect(path)
        transaction_id, _ = links[f"L{LOANS_BREAKDOWNS}"]
        revision = transaction_revision(load_merge_evidence(conn, transaction_id))
        started = time.perf_counter()
        break_down(conn, "payer", transaction_id, revision, "57.25")
        breakdown_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                         "LATER,2026-12-30,2026-12-30,SYNTHETIC LATER,-9.00,POSTED\n")
        started = time.perf_counter()
        (result,) = import_files(conn, [later], account_id="savings",
                                 layout=SYNTHETIC_CHECKING_V1)
        import_seconds = time.perf_counter() - started
        assert result.outcome == "imported"
        conn.close()
        print(f"report_net_worth={net_worth_seconds:7.3f}s report_loans={loans_seconds:7.3f}s "
              f"loan_payoff={payoff_seconds:7.3f}s totals={totals_seconds:7.3f}s "
              f"review_breakdown={breakdown_seconds:7.3f}s one_import={import_seconds:7.3f}s",
              flush=True)
        stops = [name for name, seconds in (("report net-worth", net_worth_seconds),
                                            ("report loans", loans_seconds),
                                            ("loan payoff", payoff_seconds),
                                            ("totals", totals_seconds)) if seconds > 2]
        if breakdown_seconds > 2 * import_seconds or breakdown_seconds > 2:
            stops.append("review breakdown")
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


UI_POST_COUNT = 50


def measure_ui() -> None:
    """The local UI on --safe-to-spend's shape (D-073 point 8, WD2): every page timed once each,
    after one warm-up request, as the real handler answers it over a socket pair, and 50
    sequential POST writes through the whole pipeline, timed per request, against the same CLI
    write. The writes are the checking buffer's undo and set, alternately: the shape holds no
    review item, and the buffer's two routes pass every pipeline step and the CLI's own command,
    as a review decision does. Stops, as G9 says, if a page misses 2.0s or a write's median is
    more than 0.1s above the CLI's."""
    import re
    import statistics

    sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "scenarios"),
                    str(Path(__file__).resolve().parents[1])]
    from local_ui_client import UiClient
    from test_local_ui_transaction_writes import all_post_forms
    from test_local_ui_writes import encoded

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        started = time.perf_counter()
        conn, path, _, _ = safe_to_spend_ledger(root)
        (transactions,) = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()
        (first,) = conn.execute("SELECT id FROM ledger_transaction ORDER BY id LIMIT 1").fetchone()
        conn.close()
        assert transactions >= 100_000
        print(f"shape transactions={transactions} build={time.perf_counter() - started:.1f}s",
              flush=True)
        as_of = SAFE_AS_OF_DATES[-1].isoformat()
        pages = ["/", "/monthly", "/household", f"/income?as_of={as_of}",
                 f"/budget?as_of={as_of}", f"/funds?as_of={as_of}", f"/net-worth?as_of={as_of}",
                 f"/dashboard?as_of={as_of}", "/documents", "/transactions",
                 "/transactions?search=synthetic&from=2026-01-01", "/review",
                 f"/transaction?id={first}", "/accounts", f"/obligations?as_of={as_of}",
                 "/settings", f"/visuals?as_of={as_of}"]
        client = UiClient(path)
        client.sign_in()
        try:
            assert client.get("/").status == 200
            timings = {}
            for page in pages:
                page_started = time.perf_counter()
                response = client.get(page)
                timings[page] = time.perf_counter() - page_started
                assert response.status == 200, (page, response.text[:300])
            for page, seconds in sorted(timings.items(), key=lambda item: -item[1]):
                print(f"page {page}: {seconds:.3f}s", flush=True)
            # What the visuals page costs, by the reports its rows come from (G9's attribution).
            from personal_finance.db.migrate import connect as open_read
            from personal_finance.reports import visuals as visual_rows

            reading = open_read(path, read_only=True)
            for name, call in (
                    ("monthly_report", lambda: visual_rows.monthly_report(reading)),
                    ("household_report", lambda: visual_rows.household_report(reading)),
                    ("budget_report", lambda: visual_rows.budget_report(
                        reading, as_of[:7], SAFE_AS_OF_DATES[-1], None)),
                    ("funds_view", lambda: visual_rows.funds_view(reading, SAFE_AS_OF_DATES[-1])),
                    ("net_worth", lambda: visual_rows.net_worth(reading, as_of))):
                part_started = time.perf_counter()
                call()
                print(f"visuals part {name}: {time.perf_counter() - part_started:.3f}s",
                      flush=True)
            reading.close()

            post_seconds = []
            for number in range(UI_POST_COUNT):
                forms = [form for form in all_post_forms(client.get("/settings").body)
                         if form["action"].startswith("/setting/buffer-")]
                (form,) = forms
                fields = form["fields"]
                if form["action"] == "/setting/buffer-set":
                    fields = {**fields, "buffer": f"{400 + number}.00"}
                body = encoded(fields)
                headers = [("Origin", client.server.origin), ("Sec-Fetch-Site", "same-origin"),
                           ("Sec-Fetch-Mode", "navigate"),
                           ("Content-Type", "application/x-www-form-urlencoded")]
                post_started = time.perf_counter()
                response = client.request("POST", form["action"], headers=headers, body=body)
                post_seconds.append(time.perf_counter() - post_started)
                assert response.status == 303, (response.status, re.findall(
                    r'<p class="notice">(.*?)</p>', response.text))
        finally:
            client.close()

        database = str(path)
        cli_seconds = []
        for number in range(10):
            shown = io.StringIO()
            with contextlib.redirect_stdout(shown):
                assert cli_main(["setting", "show", "--db", database]) == 0
            revision = re.search(r"Setting checking_buffer_cents: (.*)\n  Revision: (\S+)",
                                 shown.getvalue())
            words = (["setting", "set", "checking_buffer_cents", f"{500 + number}.00"]
                     if revision[1] == "not set" else ["setting", "undo",
                                                       "checking_buffer_cents"])
            cli_seconds.append(timed_command(*words, "--db", database, "--revision",
                                             revision[2]))
        post_median, cli_median = statistics.median(post_seconds), statistics.median(cli_seconds)
        print(f"posts={len(post_seconds)} median={post_median:.3f}s "
              f"p95={sorted(post_seconds)[int(0.95 * len(post_seconds)) - 1]:.3f}s "
              f"max={max(post_seconds):.3f}s; cli write median={cli_median:.3f}s", flush=True)
        slow_pages = [page for page, seconds in timings.items() if seconds > 2.0]
        stops = slow_pages + (["writes"] if post_median - cli_median > 0.1 else [])
        print("stopping rule: " + (f"MET by {', '.join(stops)}" if stops else "not met"),
              flush=True)


def main() -> None:
    if sys.argv[1:] == ["--scale"]:
        measure_scale()
        return
    if sys.argv[1:] == ["--scale", "--recurring"]:
        measure_recurring()
        return
    if sys.argv[1:] == ["--scale", "--budget"]:
        measure_budget()
        return
    if sys.argv[1:] == ["--scale", "--funds"]:
        measure_funds()
        return
    if sys.argv[1:] == ["--scale", "--loans"]:
        measure_loans()
        return
    if sys.argv[1:] == ["--scale", "--safe-to-spend"]:
        measure_safe_to_spend()
        return
    if sys.argv[1:] == ["--scale", "--snapshot"]:
        measure_snapshot()
        return
    if sys.argv[1:] == ["--scale", "--everything"]:
        measure_everything()
        return
    if sys.argv[1:] == ["--scale", "--sync"]:
        measure_sync()
        return
    if sys.argv[1:] == ["--scale", "--scenarios"]:
        measure_scenarios()
        return
    if sys.argv[1:] == ["--scale", "--ui"]:
        measure_ui()
        return
    if sys.argv[1:] == ["--scale", "--household"]:
        measure_household()
        return
    if sys.argv[1:2] == ["--scale"] and sys.argv[2:3] == ["--category-rules"]:
        measure_category_rules(int(sys.argv[3]))
        return
    sizes = [(24, 200), (24, 1000), (24, 4000)]
    if len(sys.argv) > 1:
        sizes = [(24, int(value)) for value in sys.argv[1:]]
    for shape in SHAPES:
        for months, rows_per_month in sizes:
            measure(shape, months, rows_per_month)


if __name__ == "__main__":
    main()
