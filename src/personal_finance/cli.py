"""Command line interface.

Output goes to the terminal only. Nothing here writes a log, and only the
commands that exist to show transactions print descriptions or raw rows (D-037).
"""

import argparse
import json
import sqlite3
import sys
import uuid
from pathlib import Path

from personal_finance.db.migrate import (
    MigrationError,
    connect,
    create_database,
    load_migrations,
    migrate,
    schema_version,
)
from personal_finance.ingest.coverage import DATE_BASES, declare_complete
from personal_finance.ingest.errors import ImportFailure
from personal_finance.ingest.layouts import LAYOUTS
from personal_finance.ingest.pipeline import import_files
from personal_finance.money import format_cents
from personal_finance.reconcile.apply import reconcile_account, stale_accounts
from personal_finance.reconcile.cross_document import (
    PRIMARY_CRITERIA,
    deciding_criterion,
    primary_rank,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports.import_summary import summarize_run
from personal_finance.reports.totals import account_movement

ACCOUNT_TYPES = ("checking", "savings", "credit_card", "loan", "investment", "retirement")

MATCHING_NOTICE = (
    "Files are compared within each account. Rows matched confidently are counted once. "
    "Other duplicates can go undetected, for example where descriptions differ."
)

BUSY_EXPLANATION = (
    "database is busy: another process is using the ledger. The step that failed changed "
    "nothing. Wait for that process to finish, then run this command again."
)

UNEXPECTED_ERROR = (
    "an unexpected problem stopped this command, so it may not have finished. Anything not "
    "yet committed was discarded. Details are not shown or saved, because they could contain "
    "financial data. Check the ledger with totals before running it again."
)

FAILURE_EXPLANATIONS = {
    "database_busy": (
        "Another process held the ledger, so this file was not imported and nothing from it "
        "was kept. Wait for that process to finish, then import the file again."
    ),
    "account_mismatch": (
        "This exact file is already imported for a different account, so it was not linked to "
        "the requested account. The existing import is unchanged."
    ),
    "layout_mismatch": (
        "This exact file is already imported under a different layout. "
        "The existing import is unchanged."
    ),
    "layout_definition_changed": (
        "This layout's definition differs from the one stored for earlier documents. "
        "Existing data is unchanged. A change of meaning needs a new layout version."
    ),
    "coverage_conflict": (
        "Coverage is fixed when a document is first imported, and a declaration cannot replace "
        "coverage the document states. Existing data is unchanged. Correcting coverage needs "
        "the history workflow planned for M2."
    ),
}


class CommandError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pf")
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name, parent=commands, *, handler, help):
        sub = parent.add_parser(name, help=help)
        sub.add_argument("--db", type=Path, required=True, help="path to the ledger database")
        sub.set_defaults(handler=handler)
        return sub

    command("init", handler=run_init, help="create a new ledger database")
    command("migrate", handler=run_migrate, help="upgrade a ledger to the current schema")

    account = commands.add_parser("account", help="manage accounts")
    account_commands = account.add_subparsers(dest="account_command", required=True)
    add = command("add", account_commands, handler=run_account_add, help="add an account")
    add.add_argument("--name", required=True)
    add.add_argument("--type", required=True, choices=ACCOUNT_TYPES)
    add.add_argument("--institution")
    add.add_argument("--last4")

    importer = command("import", handler=run_import, help="import files")
    importer.add_argument("--account", required=True, help="account name or ID")
    importer.add_argument("--layout", required=True, choices=sorted(LAYOUTS))
    importer.add_argument(
        "--declare-complete-coverage",
        action="store_true",
        help="state that this file holds every transaction for the account in the interval",
    )
    importer.add_argument("--coverage-start", help="first covered date, inclusive (YYYY-MM-DD)")
    importer.add_argument("--coverage-end", help="last covered date, inclusive (YYYY-MM-DD)")
    importer.add_argument("--coverage-basis", choices=DATE_BASES)
    importer.add_argument("files", nargs="+", type=Path, metavar="FILE")

    reconcile = command(
        "reconcile", handler=run_reconcile, help="re-derive accounts under the current rules"
    )
    reconcile.add_argument("--account", help="account name or ID (default: every account)")

    command("documents", handler=run_documents, help="list imported documents and their coverage")
    command("transactions", handler=run_transactions, help="list logical transactions")

    trace = command("trace", handler=run_trace, help="show where a transaction came from")
    trace.add_argument("transaction_id")

    review = commands.add_parser("review", help="inspect the review queue")
    review_commands = review.add_subparsers(dest="review_command", required=True)
    command("list", review_commands, handler=run_review_list, help="list open review items")

    totals = command("totals", handler=run_totals, help="show account movement")
    totals.add_argument("--account", help="account name or ID")
    return parser


def open_ledger(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a ledger on the current schema. Upgrading is only ever done by migrate."""
    if not path.is_file():
        raise CommandError(f"database not found: {path}")
    conn = connect(path, read_only=read_only)
    current, latest = schema_version(conn), len(load_migrations())
    if current < latest:
        raise CommandError(
            f"this ledger uses schema version {current} and this code needs {latest}. "
            f"Nothing was changed. Run: pf migrate --db {path}"
        )
    if current > latest:
        raise CommandError(
            f"this ledger uses schema version {current}, which is newer than this code "
            f"({latest}). Nothing was changed."
        )
    return conn


def find_account(conn, reference: str) -> str:
    row = conn.execute(
        "SELECT id FROM account WHERE id = ? OR display_name = ?", (reference, reference)
    ).fetchone()
    if row is None:
        raise CommandError(f"account not found: {reference}")
    return row[0]


def run_init(args) -> int:
    try:
        create_database(args.db)
    except FileExistsError:
        raise CommandError(f"refusing to overwrite existing file: {args.db}") from None
    print(f"Created {args.db}")
    return 0


def run_migrate(args) -> int:
    """Upgrade the schema and its metadata. Transaction grouping is left to reconcile."""
    if not args.db.is_file():
        raise CommandError(f"database not found: {args.db}")
    conn = connect(args.db)
    before = schema_version(conn)
    try:
        after = migrate(conn)
    except (MigrationError, sqlite3.Error) as error:
        if "locked" in str(error):
            raise
        raise CommandError(
            f"migration failed at schema version {schema_version(conn)}. The failed step left "
            "no changes, and steps before it stay applied. Run migrate again once the "
            "problem is fixed."
        ) from None

    if after == before:
        print(f"Already at schema version {after}.")
    else:
        print(f"Upgraded from schema version {before} to {after}.")
        print("Transaction grouping was not changed. Run reconcile to update it.")
    return 0


def run_account_add(args) -> int:
    conn = open_ledger(args.db)
    account_id = str(uuid.uuid4())
    try:
        conn.execute(
            """INSERT INTO account (id, display_name, institution, account_type, last4)
               VALUES (?, ?, ?, ?, ?)""",
            (account_id, args.name, args.institution, args.type, args.last4),
        )
    except sqlite3.IntegrityError:
        raise CommandError("account name is already used, or last4 is not four digits") from None
    print(f"Added account {args.name}: {account_id}")
    return 0


def declared_coverage(args):
    values = (args.coverage_start, args.coverage_end, args.coverage_basis)
    if not args.declare_complete_coverage:
        if any(values):
            raise CommandError("coverage options need --declare-complete-coverage")
        return None
    if not all(values):
        raise CommandError(
            "--declare-complete-coverage needs --coverage-start, --coverage-end and --coverage-basis"
        )
    if len(args.files) != 1:
        raise CommandError("a coverage declaration applies to exactly one file")
    try:
        return declare_complete(*values)
    except ImportFailure as failure:
        raise CommandError(failure.code) from None


def describe_coverage(coverage) -> str:
    if coverage.kind == "unknown":
        return "coverage unknown"
    span = f"{coverage.start or '?'} to {coverage.end or '?'}"
    return f"coverage {coverage.kind} {span}, {coverage.date_basis or 'no'} basis ({coverage.evidence})"


def run_import(args) -> int:
    declared = declared_coverage(args)
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    results = import_files(
        conn,
        args.files,
        account_id=account_id,
        layout=LAYOUTS[args.layout],
        declared_coverage=declared,
    )

    if len(results) > 1:
        print("Each file's counts describe the moment it was imported.")
    for result in results:
        print_file_result(result)

    summary = summarize_run(conn, results)
    print_run_summary(summary)
    print_account_state(account_movement(conn, account_id))
    return 1 if summary.files_failed else 0


def print_file_result(result) -> None:
    if result.outcome == "failed":
        print(f"{result.file_name}: failed ({result.failure_code})")
        if result.failure_code in FAILURE_EXPLANATIONS:
            print(f"  {FAILURE_EXPLANATIONS[result.failure_code]}")
        if result.rows_attempted is None:
            print("  Source rows: unavailable")
        else:
            print(f"  Source rows: {result.rows_attempted} read, then rolled back. None were kept.")
    elif result.outcome == "already_imported" and result.reconciled:
        print(f"{result.file_name}: already imported; account reconciled under current rules")
        print_ledger_effect(result.net_transactions, result.memberships_changed)
    elif result.outcome == "already_imported":
        print(f"{result.file_name}: already imported, nothing changed")
    else:
        print(f"{result.file_name}: imported; {describe_coverage(result.coverage)}")
        print_record_counts(result)
        print_ledger_effect(result.net_transactions, result.memberships_changed)
        print(f"  Open review groups touching this file: {result.open_review_groups}")


def print_record_counts(counts) -> None:
    print(
        f"  Source rows read: {counts.rows_read} "
        f"({counts.valid_records} valid, {counts.unresolved_records} unresolved)"
    )
    print(f"  Final logical transactions for those valid records: {counts.final_transactions}")
    print(f"  Confidently consolidated records: {counts.consolidated_records}")


def print_ledger_effect(net_transactions, memberships_changed) -> None:
    print(f"  Net change in live logical transactions: {net_transactions:+d}")
    print(f"  Source memberships changed: {memberships_changed}")


def print_run_summary(summary) -> None:
    print("Run summary:")
    print(
        f"  Files attempted: {summary.files_attempted} ({summary.files_imported} imported, "
        f"{summary.files_already_imported} already imported, {summary.files_failed} failed)"
    )
    if summary.files_imported:
        print_record_counts(summary)
    else:
        print("  Source rows: none, because no file was newly imported")
    print_ledger_effect(summary.net_transactions, summary.memberships_changed)
    if summary.failed_rows_attempted:
        print(
            f"  Failed files: {summary.failed_rows_attempted} rows read, then rolled back. "
            "None were kept."
        )
    if summary.failed_files_without_row_count:
        print(f"  Failed files with row counts unavailable: {summary.failed_files_without_row_count}")


def print_account_state(movement) -> None:
    print("This account after the run:")
    print(f"  {describe_open_groups(movement)}")
    print(f"  Unresolved records, not included in totals: {movement.unresolved_records}")


def describe_open_groups(movement) -> str:
    return (
        f"Open review groups: {movement.candidate_groups}, covering "
        f"{movement.transactions_in_candidate_groups} distinct affected transactions."
    )


def run_reconcile(args) -> int:
    conn = open_ledger(args.db)
    if args.account:
        accounts = [(find_account(conn, args.account),)]
    else:
        accounts = conn.execute("SELECT id FROM account ORDER BY display_name").fetchall()

    for (account_id,) in accounts:
        conn.execute("BEGIN IMMEDIATE")
        try:
            result = reconcile_account(conn, account_id)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        print(f"Account {account_id}: {result.moved_records} source records moved.")
        print(describe_open_groups(account_movement(conn, account_id)))
    return 0


def run_documents(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    rows = conn.execute(
        """SELECT document.file_name, document.layout_id, account.display_name,
                  coverage_kind, coverage_start, coverage_end, date_basis, evidence,
                  (SELECT COUNT(*) FROM source_record record
                   WHERE record.source_document_id = document.id),
                  CASE date_basis WHEN 'transaction' THEN pending_in_transaction_basis
                                  ELSE pending_in_posting_basis END
           FROM source_document document
           JOIN document_coverage coverage ON coverage.source_document_id = document.id
           JOIN document_interpretation meaning ON meaning.source_document_id = document.id
           JOIN account ON account.id = coverage.account_id
           ORDER BY document.imported_at, document.file_name"""
    ).fetchall()
    for name, layout_id, account, kind, start, end, basis, evidence, records, pending in rows:
        line = f"{name}: {records} records, account {account}, layout {layout_id}, "
        line += f"coverage {kind}"
        if kind != "unknown":
            line += f" {start or '?'} to {end or '?'}, {basis or 'no'} basis, evidence {evidence}"
        if kind == "complete":
            line += f", pending {'included' if pending else 'excluded'}"
        print(line)
    if not rows:
        print("No documents.")
    return 0


def run_transactions(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    rows = conn.execute(
        """SELECT id, COALESCE(transaction_date, posting_date), amount_cents,
                  settlement_status, description
           FROM ledger_transaction
           ORDER BY COALESCE(transaction_date, posting_date), id"""
    ).fetchall()
    for transaction_id, when, cents, status, description in rows:
        print(f"{transaction_id}  {when}  {format_cents(cents):>12}  {status:<8}  {description or ''}")
    if not rows:
        print("No transactions.")
    return 0


def run_trace(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    transaction = conn.execute(
        """SELECT transaction_date, posting_date, amount_cents, settlement_status, description,
                  primary_source_record_id
           FROM ledger_transaction WHERE id = ?""",
        (args.transaction_id,),
    ).fetchone()
    if transaction is None:
        return trace_retired(conn, args.transaction_id)

    transaction_date, posting_date, cents, status, description, primary_id = transaction
    print(f"Transaction {args.transaction_id}")
    print(f"  Transaction date: {transaction_date or 'missing'}")
    print(f"  Posting date: {posting_date or 'missing'}")
    print(f"  Amount: {format_cents(cents)}")
    print(f"  Status: {status}")
    print(f"  Description: {description or 'missing'}")

    sources = conn.execute(
        """SELECT document.file_name, document.content_sha256, document.layout_id,
                  record.id, record.record_index, record.raw_json, link.link_rule,
                  parse.settlement_status, origin.original_transaction_id,
                  parse.transaction_date, parse.posting_date, parse.description
           FROM transaction_source link
           JOIN source_record record ON record.id = link.source_record_id
           JOIN source_document document ON document.id = link.source_document_id
           JOIN document_interpretation meaning ON meaning.source_document_id = document.id
           JOIN record_parse parse ON parse.source_record_id = record.id
                                  AND parse.parser_version = meaning.parser_version
           LEFT JOIN source_record_origin origin ON origin.source_record_id = record.id
           WHERE link.transaction_id = ?
           ORDER BY document.imported_at""",
        (args.transaction_id,),
    ).fetchall()

    ranks = {
        source[3]: primary_rank(source[7], source[9], source[10], source[11], source[1], source[4])
        for source in sources
    }
    print("Current sources:")
    for (name, digest, layout_id, record_id, index, raw_json, rule, source_status, original,
         *_) in sources:
        print(f"Source {name}, row {index}")
        print(f"  Document SHA-256: {digest}")
        print(f"  Layout: {layout_id}")
        print(f"  Record: {record_id}")
        print(f"  Link rule: {rule}")
        print(f"  Role: {describe_role(record_id, primary_id, ranks)}")
        print(f"  Source status: {source_status}")
        print(f"  Original transaction: {original or 'unknown'}")
        print(f"  Original row: {json.loads(raw_json)}")

    if primary_id is None:
        print("Displayed values: source not recorded. Run reconcile to record it.")
    elif len(sources) > 1:
        print(f"Displayed values come from record {primary_id}, chosen by, in order:")
        for number, criterion in enumerate(PRIMARY_CRITERIA, start=1):
            print(f"  {number}. {criterion}")
    print_history(conn, args.transaction_id)
    return 0


def describe_role(record_id, primary_id, ranks) -> str:
    if primary_id is None:
        return "not recorded"
    if record_id == primary_id:
        return "primary, supplies the displayed values"
    return f"alternative, not selected on: {deciding_criterion(ranks[primary_id], ranks[record_id])}"


def print_history(conn, transaction_id) -> None:
    """Past moves into or out of a transaction. Membership above is what counts now."""
    moves = conn.execute(
        """SELECT history.created_at, history.action, history.reason,
                  history.source_record_id, history.from_transaction_id,
                  history.to_transaction_id
           FROM transaction_link_history history
           WHERE history.from_transaction_id = ?1 OR history.to_transaction_id = ?1
           ORDER BY history.id""",
        (transaction_id,),
    ).fetchall()
    if moves:
        print("Historical moves (not current membership):")
    for created_at, action, reason, record_id, source, target in moves:
        print(f"  {created_at} {action}: record {record_id} moved from {source} to {target} ({reason})")

    events = conn.execute(
        """SELECT created_at, event, reason, transaction_created_at
           FROM transaction_identity_history WHERE transaction_id = ? ORDER BY id""",
        (transaction_id,),
    ).fetchall()
    if events:
        print("Identity history:")
    # A revival with no retirement before it means the ID was retired before migration
    # 0004 kept timestamps, so this value is a fallback for the whole ID and is not exact.
    label = "first created"
    if events and events[0][1] == "revived":
        label = "first created approximately, from its link time, not an exact record:"
    for created_at, event, reason, original_created_at in events:
        print(f"  {created_at} {event} ({reason}), {label} {original_created_at}")


def trace_retired(conn, transaction_id) -> int:
    """A retired ID can lead to several transactions, so every one of them is listed."""
    holders = conn.execute(
        """SELECT DISTINCT link.transaction_id, link.source_record_id
           FROM transaction_source link
           WHERE link.source_record_id IN (
               SELECT source_record_id FROM transaction_link_history
               WHERE from_transaction_id = ?1 OR to_transaction_id = ?1
               UNION
               SELECT source_record_id FROM source_record_origin
               WHERE original_transaction_id = ?1)
           ORDER BY link.transaction_id, link.source_record_id""",
        (transaction_id,),
    ).fetchall()
    if not holders:
        raise CommandError("transaction not found")

    print(f"Transaction {transaction_id} is retired. Its records now belong to:")
    for current, record_id in holders:
        print(f"  Transaction {current}: record {record_id}")
    print_history(conn, transaction_id)
    return 0


def describe_evidence(evidence: str) -> str:
    """Reason codes and dates only, so that no description or amount is printed."""
    details = json.loads(evidence)
    if "reasons" not in details:
        return ""
    reasons = ", ".join(details["reasons"])
    return f", {details['date_start']} to {details['date_end']}, reasons: {reasons}"


def run_review_list(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    rows = conn.execute(
        """SELECT issue.id, issue.kind, issue.rule, issue.evidence_json,
                  COUNT(subject.transaction_id), MIN(document.file_name),
                  MIN(record.record_index)
           FROM review_issue issue
           JOIN review_issue_subject subject ON subject.review_issue_id = issue.id
           LEFT JOIN source_record record ON record.id = subject.source_record_id
           LEFT JOIN source_document document ON document.id = record.source_document_id
           WHERE issue.status = 'open'
           GROUP BY issue.id
           ORDER BY issue.kind, MIN(document.file_name), MIN(record.record_index), issue.rule"""
    ).fetchall()
    for issue, kind, rule, evidence, members, file_name, index in rows:
        if kind == "unresolved_record":
            print(f"{kind}: {rule}, {file_name} row {index}")
            continue
        print(f"{kind}: {rule}, {members} transactions{describe_evidence(evidence)}")
        subjects = conn.execute(
            """SELECT transaction_id FROM review_issue_subject
               WHERE review_issue_id = ? ORDER BY transaction_id""",
            (issue,),
        ).fetchall()
        for (transaction_id,) in subjects:
            print(f"  Transaction {transaction_id}")
    print(f"Open review items: {len(rows)}")
    return 0


def run_totals(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    movement = account_movement(conn, account_id)

    print(f"Account inflows: {format_cents(movement.inflow_cents)}")
    print(f"Account outflows: {format_cents(movement.outflow_cents)}")
    print(f"Net account movement: {format_cents(movement.net_cents)}")
    print(f"Transactions: {movement.transactions}, of which pending: {movement.pending_transactions}")
    print("Disclosures:")
    print("- These are account movements. They include transfers and card payments.")
    print(f"- {MATCHING_NOTICE}")
    stale = stale_accounts(conn, DEFAULT_RULES, account_id)
    if stale:
        print(
            f"- {len(stale)} accounts have not been reconciled under the current matching "
            "rules, so overlapping files there may be counted twice, or their transactions "
            "may not record a primary source. Run reconcile."
        )
    if movement.unresolved_records:
        print(
            f"- {movement.unresolved_records} unresolved records are not included, "
            "and their amounts may be unknown."
        )
    if movement.candidate_groups:
        print(
            f"- {movement.candidate_groups} possible-duplicate groups cover "
            f"{movement.transactions_in_candidate_groups} distinct transactions, "
            "all counted in full. "
            "Totals may be overstated, and no exact adjustment can be stated."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except CommandError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except sqlite3.OperationalError as error:
        reason = BUSY_EXPLANATION if "locked" in str(error) else "database error"
        print(f"Error: {reason}", file=sys.stderr)
        return 2
    except Exception:
        print(f"Error: {UNEXPECTED_ERROR}", file=sys.stderr)
        return 2
