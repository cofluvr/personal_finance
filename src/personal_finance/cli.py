"""Command line interface.

Output goes to the terminal only. Nothing here writes a log, and only the
commands that exist to show selected data print descriptions or raw rows (D-037).
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path

from personal_finance.db.backups import (
    BackupNotIntact,
    BackupRefused,
    CheckedBackup,
    check_backup,
    create_backup,
    restore_backup,
)
from personal_finance.db.migrate import (
    MigrationError,
    connect,
    create_database,
    load_migrations,
    migrate,
    schema_version,
)
from personal_finance.db.originals import (
    originals_folder_beside,
    prepare_originals_folder,
    verify_originals,
)
from personal_finance.db.real_ledger import (
    UnsafeLocation,
    check_real_ledger_on_open,
    is_real_ledger,
    mark_real_ledger,
    refuse_import_from_git_work_tree,
    refuse_unsafe_real_ledger_location,
)
from personal_finance.ingest.coverage import DATE_BASES, declare_complete
from personal_finance.ingest.errors import ImportFailure
from personal_finance.ingest.layouts import LAYOUTS
from personal_finance.ingest.pdf_reader import read_pdf_lines
from personal_finance.ingest.pipeline import import_files
from personal_finance.money import format_cents
from personal_finance.reconcile.apply import STATE_ACTIVE, reconcile_account, stale_accounts
from personal_finance.reconcile.balance_observations import record_observation, undo_observation
from personal_finance.reconcile.cross_document import (
    PRIMARY_CRITERIA,
    primary_rank,
)
from personal_finance.reconcile.classification_effects import (
    FINANCIAL_TYPES,
    TYPE_AGAINST_DIRECTION,
    UNCLASSIFIED,
)
from personal_finance.reconcile.categories import add_category, list_categories
from personal_finance.reconcile.classifications import classify_transaction, undo_classification
from personal_finance.reconcile.correction_effects import (
    FIELD_APPLIED,
    FIELD_BASIS_CHANGED,
    FIELD_IN_CONFLICT,
)
from personal_finance.reconcile.corrections import correct_value, undo_correction
from personal_finance.reconcile.coverage_declarations import declare_coverage, undo_declaration
from personal_finance.reconcile.record_resolutions import (
    complete_record,
    dismiss_record,
    undo_resolution,
)
from personal_finance.reconcile.decisions import (
    DecisionRefused,
    confirm_groups,
    reject_pairs,
    separable_transactions,
    separate_records,
    undo_decision,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reconcile.transfer_effects import (
    TRANSFER_DATE_WINDOW_DAYS,
    transfer_candidates,
)
from personal_finance.reconcile.transfers import (
    match_transfer,
    state_one_sided,
    undo_one_sided,
    undo_transfer,
)
from personal_finance.reports.balances import (
    check_balances,
    list_observations,
    load_observation,
    observation_revision,
)
from personal_finance.reports.classification_evidence import (
    classification_undo_outlook,
    list_classifications,
    load_classification,
)
from personal_finance.reports.correction_evidence import (
    correction_undo_outlook,
    list_corrections,
    load_correction,
)
from personal_finance.reports.decision_evidence import (
    list_decisions,
    load_decision,
    shown_kind,
    undo_outlook,
)
from personal_finance.reports.coverage_evidence import (
    declaration_undo_outlook,
    document_coverage_revision,
    list_declarations,
    load_declaration,
    load_document_coverage,
)
from personal_finance.reports.import_summary import summarize_run
from personal_finance.reports.report_text import (
    CLASSIFICATION_STATE_EXPLANATIONS,
    FIELD_STATE_EXPLANATIONS,
    MATCH_STATE_EXPLANATIONS,
    ONE_SIDED_STATE_EXPLANATIONS,
    ReportLines,
    add_completed_values,
    add_decided_pairs,
    add_document_evidence,
    add_transaction_evidence,
    describe_classifications,
    describe_conflicts,
    describe_corrections,
    describe_coverage_kind,
    describe_declarations,
    describe_open_groups,
    describe_pending,
    describe_resolutions,
    describe_role,
    document_list_lines,
    monthly_report_lines,
    review_item_report,
    review_queue_lines,
    shown,
    totals_report_lines,
    transaction_list_lines,
)
from personal_finance.reports.resolution_evidence import (
    binding_entries,
    list_resolutions,
    load_resolution,
    resolution_undo_outlook,
)
from personal_finance.reports.review_evidence import (
    load_merge_evidence,
    transaction_revision,
)
from personal_finance.reports.storage import StoredFiles, storage_by_kind
from personal_finance.reports.totals import account_movement
from personal_finance.reports.transfer_evidence import (
    list_matches,
    list_one_sided,
    load_match,
    load_one_sided,
    match_revision,
    one_sided_revision,
)

ACCOUNT_TYPES = ("checking", "savings", "credit_card", "loan", "investment", "retirement")


BUSY_EXPLANATION = (
    "database is busy: another process is using the ledger. The step that failed changed "
    "nothing. Wait for that process to finish, then run this command again."
)

BROKEN_PIPE_EXIT = 141


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
    "archive_failed": (
        "The original could not be kept in originals/ beside the ledger, or a different file "
        "already holds its name, so this file was not imported and nothing from it was kept. "
        "Run pf archive verify to check the archive."
    ),
    "coverage_conflict": (
        "This declaration differs from the coverage the document already has, or replaces "
        "coverage the document states. Existing data is unchanged. To change a document's "
        "coverage, find its ID with documents and use review coverage declare."
    ),
}


CONFIRM_NOTICE = (
    "Transactions confirmed as one event are counted once, so totals can be lower than before. "
    "Run totals to see them."
)

SEPARATE_NOTICE = (
    "Records separated from an automatic match are counted as separate transactions, so totals "
    "can be higher than before. Run totals to see them."
)

ID_OVERRIDE_NOTICE = (
    "Records in different groups share an ID that the source declares reliable, with guarantee "
    "{guarantee}. This decision overrides that match for these records only."
)

UNDO_NOTICE = (
    "This re-derives from the evidence held now, without this decision. It does not restore "
    "an earlier snapshot, so totals may differ from those before the decision if evidence "
    "has arrived since."
)


CORRECTION_NOTICE = (
    "Totals and transactions use the corrected value. Source values stay unchanged, and matching "
    "never reads corrections. New records are not bound, but a re-export that joins this "
    "transaction keeps the correction applied."
)

CORRECTION_UNDO_NOTICE = (
    "The source value applies again, or the correction this one superseded. Source values were "
    "never changed."
)

CLASSIFY_NOTICE = (
    "Totals list each financial type apart. Account movement is unchanged, matching never reads "
    "types, and new records are not bound, but a re-export that joins this transaction keeps the "
    "type applied."
)

CLASSIFICATION_UNDO_NOTICE = (
    "The transaction is unclassified again, or has the type of the classification this one "
    "superseded."
)


MATCH_NOTICE = (
    "Account movement and type totals are unchanged, matching never reads transfers, and new "
    "records are not bound, but a re-export that joins either side keeps the match applied."
)

MATCH_UNDO_NOTICE = "Both transactions are unmatched again, and can be matched again."


ONE_SIDED_NOTICE = (
    "Account movement and type totals are unchanged. Its other side is not in the ledger, so totals "
    "warn about the counterpart's coverage. If that side is imported later, the one-sided transfer "
    "stops applying until you undo it and match the pair."
)

ONE_SIDED_UNDO_NOTICE = "The transaction counts as an unpaired transfer kind again."


COMPLETE_NOTICE = (
    "The row is now a transaction and is counted, using the values you supplied with those read "
    "from the source. Its source cells stay unchanged. Matching never pairs it on typed values, "
    "so a possible duplicate is raised for review instead."
)

DISMISS_NOTICE = (
    "The row adds no transaction and no longer counts as unresolved. Its source cells stay "
    "unchanged. It no longer keeps matches in its document from being confident, so totals can "
    "be lower than before."
)

RESOLUTION_UNDO_NOTICE = (
    "This re-derives from the evidence held now, without this resolution, and the row is "
    "unresolved again. It does not restore an earlier snapshot."
)

COVERAGE_NOTICE = (
    "Matching uses the declared coverage from now on, so totals can change. The claim made at "
    "import is kept, and undoing this declaration restores the coverage before it."
)

COVERAGE_UNDO_NOTICE = (
    "This re-derives from the evidence held now, with the coverage before this declaration. It "
    "does not restore an earlier snapshot."
)


class CommandError(Exception):
    pass


def print_report(lines: ReportLines) -> None:
    for line in lines:
        print(line.text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pf")
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name, parent=commands, *, handler, help):
        sub = parent.add_parser(name, help=help)
        sub.add_argument("--db", type=Path, required=True, help="path to the ledger database")
        sub.set_defaults(handler=handler)
        return sub

    init = command("init", handler=run_init, help="create a new ledger database")
    init.add_argument(
        "--real",
        action="store_true",
        help="for actual financial data: the ledger's location is checked on every open",
    )
    command("migrate", handler=run_migrate, help="upgrade a ledger to the current schema")

    account = commands.add_parser("account", help="manage accounts")
    account_commands = account.add_subparsers(dest="account_command", required=True)
    add = command("add", account_commands, handler=run_account_add, help="add an account")
    add.add_argument("--name", required=True)
    add.add_argument("--type", required=True, choices=ACCOUNT_TYPES)
    add.add_argument("--institution")
    add.add_argument("--last4")

    category = commands.add_parser("category", help="name the categories spending can take")
    category_commands = category.add_subparsers(dest="category_command", required=True)
    category_add = command("add", category_commands, handler=run_category_add,
                           help="add a category, or a subcategory of a top-level one")
    category_add.add_argument("name", help="the category's name, compared exactly")
    category_add.add_argument("--parent", help="the top-level category this one is under")
    command("list", category_commands, handler=run_category_list,
            help="list the categories, each under its parent")

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

    archive = commands.add_parser("archive", help="check the originals a real ledger keeps")
    archive_commands = archive.add_subparsers(dest="archive_command", required=True)
    command("verify", archive_commands, handler=run_archive_verify,
            help="rehash every original, and list missing, altered and unreferenced ones")
    command("storage", handler=run_storage,
            help="show software, database, originals and backups storage apart")

    backup = commands.add_parser("backup", help="back up a ledger, check a backup, or restore one")
    backup_commands = backup.add_subparsers(dest="backup_command", required=True)
    backup_create = command("create", backup_commands, handler=run_backup_create,
                            help="write a backup of the ledger into a new folder")
    backup_create.add_argument("--to", required=True, type=Path, dest="backup_folder",
                               help="the new backup folder, which must not exist yet")
    backup_verify = backup_commands.add_parser(
        "verify", help="check a backup as a restore would, restoring nothing")
    backup_verify.add_argument("--from", required=True, type=Path, dest="backup_folder",
                               help="a backup folder written by backup create")
    backup_verify.set_defaults(handler=run_backup_verify)
    backup_restore = backup_commands.add_parser(
        "restore", help="restore a backup to a new ledger path")
    backup_restore.add_argument("--from", required=True, type=Path, dest="backup_folder",
                                help="a backup folder written by backup create")
    backup_restore.add_argument("--to", required=True, type=Path, dest="restored_db",
                                help="the restored ledger's path, which must not exist yet")
    backup_restore.set_defaults(handler=run_backup_restore)

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
    show = command(
        "show", review_commands, handler=run_review_show,
        help="show the evidence behind one review item, including amounts and descriptions",
    )
    show.add_argument("item_id", help="an item ID from review list")

    reject = command(
        "reject", review_commands, handler=run_review_reject,
        help="record that direct candidate pairs in an item are different events",
    )
    reject.add_argument("item_id", help="an item ID from review list")
    reject.add_argument("--account", required=True, help="account name or ID")
    reject.add_argument("--revision", required=True, help="the revision from review show")
    reject.add_argument(
        "--pair", required=True, nargs=2, action="append", metavar=("T1", "T2"),
        help="two transaction IDs from review show. Repeat for several pairs in one decision",
    )

    confirm = command(
        "confirm", review_commands, handler=run_review_confirm,
        help="record which transactions in an item are one event, and which are different events",
    )
    confirm.add_argument("item_id", help="an item ID from review list")
    confirm.add_argument("--account", required=True, help="account name or ID")
    confirm.add_argument("--revision", required=True, help="the revision from review show")
    confirm.add_argument(
        "--group", required=True, nargs="+", action="append", metavar="T",
        help="transaction IDs that are one event. Repeat for each group: groups are different "
        "events, and transactions left out stay undecided",
    )
    confirm.add_argument(
        "--supersedes", metavar="DECISION_ID",
        help="a decision these groups contradict, which this one replaces",
    )
    confirm.add_argument(
        "--supersedes-revision", metavar="REVISION",
        help="the revision from review decision show for the decision being replaced",
    )
    confirm.add_argument(
        "--keep", type=int, action="append", default=[], metavar="N",
        help="a pair number of the replaced decision to carry over. Repeat for each pair",
    )

    merges = command(
        "merges", review_commands, handler=run_review_merges,
        help="list transactions holding records joined automatically",
    )
    merges.add_argument("--account", help="account name or ID (default: every account)")

    merge = review_commands.add_parser("merge", help="inspect one merged transaction")
    merge_commands = merge.add_subparsers(dest="merge_command", required=True)
    merge_show = command(
        "show", merge_commands, handler=run_review_merge_show,
        help="show the evidence behind one transaction, including amounts and descriptions",
    )
    merge_show.add_argument("transaction_id", help="a transaction ID from review merges")

    separate = command(
        "separate", review_commands, handler=run_review_separate,
        help="record which records of a merged transaction are one event, and which are different",
    )
    separate.add_argument("transaction_id", help="a transaction ID from review merges")
    separate.add_argument("--account", required=True, help="account name or ID")
    separate.add_argument("--revision", required=True, help="the revision from review merge show")
    separate.add_argument(
        "--group", required=True, nargs="+", action="append", metavar="R",
        help="record IDs that are one event. Repeat for each group: groups are different events, "
        "and every record of the transaction must be in one",
    )
    separate.add_argument(
        "--supersedes", metavar="DECISION_ID",
        help="a confirmation whose one-event records these groups split, which this one replaces",
    )
    separate.add_argument(
        "--supersedes-revision", metavar="REVISION",
        help="the revision from review decision show for the decision being replaced",
    )
    separate.add_argument(
        "--keep", type=int, action="append", default=[], metavar="N",
        help="a pair number of the replaced decision to carry over. Repeat for each pair",
    )

    decisions = command(
        "decisions", review_commands, handler=run_review_decisions, help="list stored decisions"
    )
    decisions.add_argument("--account", help="account name or ID")

    decision = review_commands.add_parser("decision", help="inspect one stored decision")
    decision_commands = decision.add_subparsers(dest="decision_command", required=True)
    decision_show = command(
        "show", decision_commands, handler=run_review_decision_show,
        help="show what a decision binds and what undoing it would do",
    )
    decision_show.add_argument("decision_id", help="a decision ID from review decisions")

    undo = command(
        "undo", review_commands, handler=run_review_undo,
        help="re-derive from current evidence without a decision, keeping it on record",
    )
    undo.add_argument("decision_id", help="a decision ID from review decisions")
    undo.add_argument("--account", required=True, help="account name or ID")
    undo.add_argument("--revision", required=True, help="the revision from review decision show")

    transaction = review_commands.add_parser("transaction", help="inspect one transaction")
    transaction_commands = transaction.add_subparsers(dest="transaction_command", required=True)
    transaction_show = command(
        "show", transaction_commands, handler=run_review_transaction_show,
        help="show one transaction's evidence, corrections and classifications, including amounts "
        "and descriptions",
    )
    transaction_show.add_argument("transaction_id", help="a transaction ID from transactions")

    correct = command(
        "correct", review_commands, handler=run_review_correct,
        help="record a corrected value for one field of a transaction, keeping its source value",
    )
    correct.add_argument("transaction_id", help="a transaction ID from transactions")
    correct.add_argument("--account", required=True, help="account name or ID")
    correct.add_argument(
        "--revision", required=True, help="the revision from review transaction show"
    )
    correct.add_argument(
        "--field", required=True,
        help="amount, transaction_date, posting_date or description",
    )
    correct.add_argument(
        "--value", required=True,
        help="the corrected value: an amount such as --value=-12.50, negative for money out, a "
        "date as YYYY-MM-DD, or a description",
    )
    correct.add_argument(
        "--supersedes", metavar="CORRECTION_ID",
        help="the correction applying to this field now, which this one replaces",
    )
    correct.add_argument(
        "--supersedes-revision", metavar="REVISION",
        help="the revision from review correction show for the correction being replaced",
    )

    corrections = command(
        "corrections", review_commands, handler=run_review_corrections,
        help="list stored corrections",
    )
    corrections.add_argument("--account", help="account name or ID")

    correction = review_commands.add_parser("correction", help="inspect or undo one correction")
    correction_commands = correction.add_subparsers(dest="correction_command", required=True)
    correction_show = command(
        "show", correction_commands, handler=run_review_correction_show,
        help="show what a correction binds and what undoing it would do",
    )
    correction_show.add_argument("correction_id", help="a correction ID from review corrections")
    correction_undo = command(
        "undo", correction_commands, handler=run_review_correction_undo,
        help="stop a correction applying, keeping it on record",
    )
    correction_undo.add_argument("correction_id", help="a correction ID from review corrections")
    correction_undo.add_argument("--account", required=True, help="account name or ID")
    correction_undo.add_argument(
        "--revision", required=True, help="the revision from review correction show"
    )

    classify = command(
        "classify", review_commands, handler=run_review_classify,
        help="state the financial type of a transaction",
    )
    classify.add_argument("transaction_id", help="a transaction ID from transactions")
    classify.add_argument("--account", required=True, help="account name or ID")
    classify.add_argument(
        "--revision", required=True, help="the revision from review transaction show"
    )
    classify.add_argument("--type", required=True, dest="financial_type",
                          help=", ".join(FINANCIAL_TYPES))
    classify.add_argument(
        "--supersedes", metavar="CLASSIFICATION_ID",
        help="the classification applying to this transaction now, which this one replaces",
    )
    classify.add_argument(
        "--supersedes-revision", metavar="REVISION",
        help="the revision from review classification show for the classification being replaced",
    )

    classifications = command(
        "classifications", review_commands, handler=run_review_classifications,
        help="list stored classifications",
    )
    classifications.add_argument("--account", help="account name or ID")

    classification = review_commands.add_parser(
        "classification", help="inspect or undo one classification"
    )
    classification_commands = classification.add_subparsers(
        dest="classification_command", required=True
    )
    classification_show = command(
        "show", classification_commands, handler=run_review_classification_show,
        help="show what a classification binds and what undoing it would do",
    )
    classification_show.add_argument(
        "classification_id", help="a classification ID from review classifications"
    )
    classification_undo = command(
        "undo", classification_commands, handler=run_review_classification_undo,
        help="stop a classification applying, keeping it on record",
    )
    classification_undo.add_argument(
        "classification_id", help="a classification ID from review classifications"
    )
    classification_undo.add_argument("--account", required=True, help="account name or ID")
    classification_undo.add_argument(
        "--revision", required=True, help="the revision from review classification show"
    )

    transfers = command(
        "transfers", review_commands, handler=run_review_transfers,
        help="list transfer candidates, stored transfer matches and one-sided transfers",
    )
    transfers.add_argument("--account", help="account name or ID")

    transfer = review_commands.add_parser(
        "transfer", help="match, inspect or undo a transfer between two accounts"
    )
    transfer_commands = transfer.add_subparsers(dest="transfer_command", required=True)
    transfer_match = command(
        "match", transfer_commands, handler=run_review_transfer_match,
        help="state that two transactions of two accounts are one transfer",
    )
    transfer_match.add_argument("transaction_id", help="a transaction ID from review transfers")
    transfer_match.add_argument("--account", required=True, help="its account name or ID")
    transfer_match.add_argument(
        "--revision", required=True, help="the revision from review transaction show"
    )
    transfer_match.add_argument("--counterpart", required=True, dest="counterpart_id",
                                help="the other transaction's ID, from review transfers")
    transfer_match.add_argument("--counterpart-account", required=True,
                                help="the other transaction's account name or ID")
    transfer_match.add_argument(
        "--counterpart-revision", required=True,
        help="the other transaction's revision from review transaction show",
    )
    one_sided = command(
        "one-sided", transfer_commands, handler=run_review_transfer_one_sided,
        help="state that a transaction moves money to or from an account whose side is not "
             "in the ledger",
    )
    one_sided.add_argument("transaction_id", help="a transaction ID from review transfers")
    one_sided.add_argument("--account", required=True, help="its account name or ID")
    one_sided.add_argument(
        "--revision", required=True, help="the revision from review transaction show"
    )
    one_sided.add_argument(
        "--counterpart-account", required=True,
        help="the name or ID of the other account, registered with account add",
    )
    transfer_show = command(
        "show", transfer_commands, handler=run_review_transfer_show,
        help="show what a transfer match or one-sided transfer binds, and its undo revision",
    )
    transfer_show.add_argument(
        "transfer_id", help="a match or one-sided transfer ID from review transfers")
    transfer_undo = command(
        "undo", transfer_commands, handler=run_review_transfer_undo,
        help="stop a transfer match or one-sided transfer applying, keeping it on record",
    )
    transfer_undo.add_argument(
        "transfer_id", help="a match or one-sided transfer ID from review transfers")
    transfer_undo.add_argument("--account", required=True,
                               help="the name or ID of either of its accounts")
    transfer_undo.add_argument(
        "--revision", required=True, help="the revision from review transfer show"
    )

    complete = command(
        "complete", review_commands, handler=run_review_complete,
        help="supply the values an unresolved row lacks, so that it becomes a transaction",
    )
    complete.add_argument("item_id", help="an unresolved-record item ID from review list")
    complete.add_argument("--account", required=True, help="account name or ID")
    complete.add_argument("--revision", required=True, help="the revision from review show")
    complete.add_argument(
        "--amount", help="the amount, such as --amount=-12.50, negative for money out"
    )
    complete.add_argument("--transaction-date", help="the transaction date, YYYY-MM-DD")
    complete.add_argument("--posting-date", help="the posting date, YYYY-MM-DD")
    complete.add_argument("--description", help="the description")

    dismiss = command(
        "dismiss", review_commands, handler=run_review_dismiss,
        help="state that an unresolved row adds no transaction, keeping it on record",
    )
    dismiss.add_argument("item_id", help="an unresolved-record item ID from review list")
    dismiss.add_argument("--account", required=True, help="account name or ID")
    dismiss.add_argument("--revision", required=True, help="the revision from review show")

    resolutions = command(
        "resolutions", review_commands, handler=run_review_resolutions,
        help="list stored completions and dismissals",
    )
    resolutions.add_argument("--account", help="account name or ID")

    resolution = review_commands.add_parser("resolution", help="inspect or undo one resolution")
    resolution_commands = resolution.add_subparsers(dest="resolution_command", required=True)
    resolution_show = command(
        "show", resolution_commands, handler=run_review_resolution_show,
        help="show what a resolution resolved and what undoing it would do",
    )
    resolution_show.add_argument("resolution_id", help="a resolution ID from review resolutions")
    resolution_undo = command(
        "undo", resolution_commands, handler=run_review_resolution_undo,
        help="make a resolved row unresolved again, keeping the resolution on record",
    )
    resolution_undo.add_argument("resolution_id", help="a resolution ID from review resolutions")
    resolution_undo.add_argument("--account", required=True, help="account name or ID")
    resolution_undo.add_argument(
        "--revision", required=True, help="the revision from review resolution show"
    )

    coverage = review_commands.add_parser("coverage", help="inspect or declare a document's coverage")
    coverage_commands = coverage.add_subparsers(dest="coverage_command", required=True)
    coverage_show = command(
        "show", coverage_commands, handler=run_review_coverage_show,
        help="show a document's coverage: the claim at import and any declaration since",
    )
    coverage_show.add_argument("document_id", help="a document ID from documents")
    coverage_declare = command(
        "declare", coverage_commands, handler=run_review_coverage_declare,
        help="declare a document's coverage after import, keeping the claim at import",
    )
    coverage_declare.add_argument("document_id", help="a document ID from documents")
    coverage_declare.add_argument("--account", required=True, help="account name or ID")
    coverage_declare.add_argument(
        "--revision", required=True, help="the revision from review coverage show"
    )
    coverage_declare.add_argument(
        "--coverage-kind", required=True, help="complete, or unknown to withdraw a claim"
    )
    coverage_declare.add_argument("--coverage-start", help="first covered date, inclusive (YYYY-MM-DD)")
    coverage_declare.add_argument("--coverage-end", help="last covered date, inclusive (YYYY-MM-DD)")
    coverage_declare.add_argument("--coverage-basis", help="transaction or posting")
    coverage_history = command(
        "history", coverage_commands, handler=run_review_coverage_history,
        help="list coverage declared after import",
    )
    coverage_history.add_argument("--account", help="account name or ID")
    coverage_undo = command(
        "undo", coverage_commands, handler=run_review_coverage_undo,
        help="stop a coverage declaration applying, keeping it on record",
    )
    coverage_undo.add_argument("declaration_id", help="a declaration ID from review coverage history")
    coverage_undo.add_argument("--account", required=True, help="account name or ID")
    coverage_undo.add_argument(
        "--revision", required=True, help="the revision from review coverage show"
    )

    totals = command("totals", handler=run_totals, help="show account movement")
    totals.add_argument("--account", help="account name or ID")

    report = commands.add_parser("report", help="show reports by period")
    report_commands = report.add_subparsers(dest="report_command", required=True)
    monthly = command(
        "monthly", report_commands, handler=run_report_monthly,
        help="show account movement and income and spending by month, with disclosures",
    )
    monthly.add_argument("--account", help="account name or ID")
    monthly.add_argument("--from", dest="first_month", help="the first month, YYYY-MM, inclusive")
    monthly.add_argument("--to", dest="last_month", help="the last month, YYYY-MM, inclusive")

    command(
        "ui", handler=run_ui,
        help="serve read-only pages of this ledger on 127.0.0.1, to this browser only, until Ctrl-C",
    )

    balance = commands.add_parser(
        "balance", help="record posted balances and check them against transactions"
    )
    balance_commands = balance.add_subparsers(dest="balance_command", required=True)
    balance_record = command(
        "record", balance_commands, handler=run_balance_record,
        help="record an account's posted balance at the end of one day",
    )
    balance_record.add_argument("--account", required=True, help="account name or ID")
    balance_record.add_argument("--date", required=True, help="the day, YYYY-MM-DD")
    stated_amount = balance_record.add_mutually_exclusive_group(required=True)
    stated_amount.add_argument(
        "--balance", help="the balance of any account but a credit card or loan, such as "
                          "--balance=-12.50 when overdrawn")
    stated_amount.add_argument(
        "--owed", help="what a credit card or loan owes, such as --owed=-5.00 for a credit balance")
    balance_list = command(
        "list", balance_commands, handler=run_balance_list,
        help="list balance observations, with the token to undo each active one",
    )
    balance_list.add_argument("--account", help="account name or ID")
    balance_check = command(
        "check", balance_commands, handler=run_balance_check,
        help="compare consecutive balance observations with the transactions between them",
    )
    balance_check.add_argument("--account", required=True, help="account name or ID")
    balance_undo = command(
        "undo", balance_commands, handler=run_balance_undo,
        help="stop a balance observation applying, keeping it on record",
    )
    balance_undo.add_argument("--account", required=True, help="account name or ID")
    balance_undo.add_argument("--observation", required=True, dest="observation_id",
                              help="an observation ID from balance list")
    balance_undo.add_argument("--token", required=True, help="its token from balance list")

    pdf = commands.add_parser("pdf", help="read a PDF statement without importing it")
    pdf_commands = pdf.add_subparsers(dest="pdf_command", required=True)
    pdf_text = pdf_commands.add_parser(
        "text", help="print a PDF's text as an import would read it. Opens no ledger, writes nothing"
    )
    pdf_text.add_argument("file", type=Path, metavar="FILE")
    pdf_text.set_defaults(handler=run_pdf_text)
    return parser


def run_pdf_text(args) -> int:
    """Each page's lines, as a PDF layout reads them, so their structure can be described."""
    try:
        pages = read_pdf_lines(args.file.read_bytes())
    except OSError:
        raise CommandError("the file could not be read: unreadable_file") from None
    except ImportFailure as failure:
        raise CommandError(f"the file could not be read as a PDF: {failure.code}") from None
    for number, lines in enumerate(pages, start=1):
        print(f"Page {number}")
        for line in lines:
            print(f"  {shown(line)}")
    return 0


def open_ledger(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a ledger on the current schema. Upgrading is only ever done by migrate."""
    if not path.is_file():
        raise CommandError(f"database not found: {path}")
    conn = connect(path, read_only=read_only)
    check_real_ledger_on_open(conn, path)
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
    if args.real:
        refuse_unsafe_real_ledger_location(args.db)
    try:
        create_database(args.db)
    except FileExistsError:
        raise CommandError(f"refusing to overwrite existing file: {args.db}") from None
    if args.real:
        conn = connect(args.db)
        mark_real_ledger(conn)
        conn.close()
        print(f"Created real ledger {args.db}")
    else:
        print(f"Created {args.db}")
    return 0


def run_migrate(args) -> int:
    """Upgrade the schema and its metadata. Transaction grouping is left to reconcile."""
    if not args.db.is_file():
        raise CommandError(f"database not found: {args.db}")
    conn = connect(args.db)
    check_real_ledger_on_open(conn, args.db)
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


def run_category_add(args) -> int:
    conn = open_ledger(args.db)
    category = add_category(conn, args.name, args.parent)
    under = f", under {shown(args.parent)}" if category.parent_id is not None else ""
    print(f"Added category {shown(category.name)}{under}")
    return 0


def run_category_list(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    categories = list_categories(conn)
    for category in categories:
        indent = "  " if category.parent_id is not None else ""
        print(f"{indent}{shown(category.name)}")
    print(f"Categories: {len(categories)}")
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
    real = is_real_ledger(conn)
    if real:
        for import_path in args.files:
            refuse_import_from_git_work_tree(import_path)
    account_id = find_account(conn, args.account)
    originals_folder = prepare_originals_folder(args.db) if real else None
    results = import_files(
        conn,
        args.files,
        account_id=account_id,
        layout=LAYOUTS[args.layout],
        declared_coverage=declared,
        originals_folder=originals_folder,
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
    for line in describe_conflicts(movement):
        print(f"  {line}")
    for line in describe_corrections(movement):
        print(f"  {line}")
    for line in (*describe_resolutions(movement), *describe_declarations(movement),
                 *describe_pending(movement), *describe_classifications(movement)):
        print(f"  {line}")
    print(f"  Unresolved records, not included in totals: {movement.unresolved_records}")


def run_archive_verify(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    if not is_real_ledger(conn):
        raise CommandError("a synthetic ledger keeps no originals, so there is nothing to verify")
    verification = verify_originals(conn, originals_folder_beside(args.db))
    print(f"Originals intact: {len(verification.intact)}")
    for heading, originals in (("Missing", verification.missing),
                               ("Altered", verification.altered)):
        print(f"{heading}: {len(originals)}")
        for original in originals:
            print(f"  {original.content_sha256}, document {original.source_document_id}")
    print(f"Not referenced: {len(verification.unreferenced_entry_names)}")
    for entry_name in verification.unreferenced_entry_names:
        print(f"  {shown(entry_name)}")
    print("The archive is intact." if verification.passed else "The archive is not intact.")
    return 0 if verification.passed else 1


def shown_files(stored) -> str:
    return f"{stored.byte_count} bytes in {stored.file_count} files"


def run_storage(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    originals_folder = originals_folder_beside(args.db) if is_real_ledger(conn) else None
    storage = storage_by_kind(conn, args.db, originals_folder)
    print(f"Software: {shown_files(storage.software)} (the personal_finance package; the Python "
          "interpreter and its environment are not counted)")
    print(f"Database: {shown_files(storage.database)} (the ledger with its journal)")
    if originals_folder is None:
        print("Originals: none, a synthetic ledger archives nothing")
    else:
        print(f"Originals: {shown_files(storage.referenced_originals)} referenced, "
              f"{shown_files(storage.unreferenced_originals)} not referenced")
    if not storage.backups:
        print("Backups: none recorded")
    else:
        total = StoredFiles(sum(backup.byte_count for backup in storage.backups),
                            sum(backup.file_count for backup in storage.backups))
        print(f"Backups: {shown_files(total)} in {len(storage.backups)} recorded, as written; "
              "their volumes are not read")
        for backup in storage.backups:
            print(f"  {backup.created_at} {shown(backup.backup_folder)}: "
                  f"{shown_files(StoredFiles(backup.byte_count, backup.file_count))}")
    return 0


def print_checked_backup(checked: CheckedBackup) -> None:
    if checked.is_real:
        print(f"Ledger: real, with {len(checked.original_names)} originals")
    else:
        print("Ledger: synthetic, with no originals")
    print(f"Files: {checked.byte_count} bytes in {checked.file_count} files, each matching the "
          "manifest")
    print("SQLite integrity and foreign key checks: ok")
    latest = len(load_migrations())
    if checked.schema_version < latest:
        print(f"Schema version: {checked.schema_version}, older than this code's {latest}")
    else:
        print(f"Schema version: {checked.schema_version}")
    print(f"Logical digest: {checked.logical_digest}, matching the manifest")


def run_backup_create(args) -> int:
    conn = open_ledger(args.db)
    checked = create_backup(conn, args.db, args.backup_folder)
    print(f"Backup written to {shown(args.backup_folder)}")
    print_checked_backup(checked)
    print(f"Recorded in the ledger. To check it later, run: pf backup verify --from "
          f"{shown(args.backup_folder)}")
    return 0


def run_backup_verify(args) -> int:
    try:
        checked = check_backup(args.backup_folder)
    except BackupNotIntact as failure:
        print(f"The backup is not intact: {failure.reason}.")
        return 1
    print_checked_backup(checked)
    print("The backup is intact.")
    return 0


def run_backup_restore(args) -> int:
    checked = restore_backup(args.backup_folder, args.restored_db)
    print(f"Restored {shown(args.restored_db)} from {shown(args.backup_folder)}")
    print_checked_backup(checked)
    if checked.schema_version < len(load_migrations()):
        print(f"Before using it, run: pf migrate --db {shown(args.restored_db)}")
    return 0


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
        print(f"Account {account_id}: source memberships changed: {result.moved_records}.")
        movement = account_movement(conn, account_id)
        print(describe_open_groups(movement))
        for line in describe_conflicts(movement):
            print(line)
    return 0


def run_documents(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    print_report(document_list_lines(conn))
    return 0


def run_transactions(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    print_report(transaction_list_lines(conn))
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
    print(f"  Description: {shown(description)}")
    corrected_fields = conn.execute(
        """SELECT field, state, corrected_amount_cents, corrected_text FROM transaction_correction
           WHERE transaction_id = ? ORDER BY field""",
        (args.transaction_id,),
    ).fetchall()
    if corrected_fields:
        print("Corrections, applied over the source values above:")
    for field, state, corrected_amount_cents, corrected_text in corrected_fields:
        if state == FIELD_APPLIED:
            value = format_cents(corrected_amount_cents) if field == "amount" else shown(corrected_text)
            print(f"  {field}: corrected to {value}")
        else:
            print(f"  {field}: {FIELD_STATE_EXPLANATIONS[state]}")

    sources = conn.execute(
        """SELECT document.file_name, document.content_sha256, document.layout_id,
                  record.id, record.record_index, record.raw_json, link.link_rule,
                  parse.settlement_status, origin.original_transaction_id,
                  parse.transaction_date, parse.posting_date, parse.description,
                  completion.completed_amount_cents, completion.completed_transaction_date,
                  completion.completed_posting_date, completion.completed_description,
                  completion.id IS NOT NULL
           FROM transaction_source link
           JOIN source_record record ON record.id = link.source_record_id
           JOIN source_document document ON document.id = link.source_document_id
           JOIN document_interpretation meaning ON meaning.source_document_id = document.id
           JOIN record_parse parse ON parse.source_record_id = record.id
                                  AND parse.parser_version = meaning.parser_version
           LEFT JOIN source_record_origin origin ON origin.source_record_id = record.id
           LEFT JOIN record_resolution completion
               ON completion.source_record_id = record.id AND completion.kind = 'completed'
              AND NOT EXISTS (SELECT 1 FROM record_resolution_event undone
                              WHERE undone.resolution_id = completion.id
                                AND undone.event = 'undone')
           WHERE link.transaction_id = ?
           ORDER BY document.imported_at""",
        (args.transaction_id,),
    ).fetchall()

    ranks = {
        source[3]: primary_rank(*_traced_rank_values(source), source[1], source[4],
                                completed_by_hand=bool(source[16]))
        for source in sources
    }
    print("Current sources:")
    for (name, digest, layout_id, record_id, index, raw_json, rule, source_status, original,
         *_, completed_amount, completed_transaction_date, completed_posting_date,
         completed_description, completed) in sources:
        print(f"Source {name}, row {index}")
        print(f"  Document SHA-256: {digest}")
        print(f"  Layout: {layout_id}")
        print(f"  Record: {record_id}")
        print(f"  Link rule: {rule}")
        print(f"  Role: {describe_role(record_id, primary_id, ranks)}")
        print(f"  Source status: {source_status}")
        print(f"  Original transaction: {original or 'unknown'}")
        print(f"  Original row: {json.loads(raw_json)}")
        if completed:
            completed_values = ReportLines()
            add_completed_values(completed_values, (completed_amount, completed_transaction_date,
                                                    completed_posting_date, completed_description),
                                 "  ")
            print_report(completed_values)

    if primary_id is None:
        print("Displayed values: source not recorded. Run reconcile to record it.")
    elif len(sources) > 1:
        print(f"Displayed values come from record {primary_id}, chosen by, in order:")
        for number, criterion in enumerate(PRIMARY_CRITERIA, start=1):
            print(f"  {number}. {criterion}")
    print_history(conn, args.transaction_id)
    return 0


def _traced_rank_values(source):
    """Status, dates and description as derivation ranked them: a completed record's are read
    where the parse has them, else supplied (D-050)."""
    status, transaction_date, posting_date, description = source[7], *source[9:12]
    supplied = source[13:16]
    return (status, transaction_date or supplied[0], posting_date or supplied[1],
            description or supplied[2])


def print_history(conn, transaction_id) -> None:
    """Past moves into or out of a transaction. Membership above is what counts now."""
    moves = conn.execute(
        """SELECT history.created_at, history.action, history.reason,
                  history.source_record_id, history.from_transaction_id,
                  history.to_transaction_id, history.decision_id
           FROM transaction_link_history history
           WHERE history.from_transaction_id = ?1 OR history.to_transaction_id = ?1
           ORDER BY history.id""",
        (transaction_id,),
    ).fetchall()
    if moves:
        print("Historical moves (not current membership):")
    for created_at, action, reason, record_id, source, target, decision_id in moves:
        cause = f"{reason}, decision {decision_id}" if decision_id else reason
        print(f"  {created_at} {action}: record {record_id} moved from {source} to {target} ({cause})")

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


def run_review_list(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    print_report(review_queue_lines(conn))
    return 0


def run_review_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    report = review_item_report(conn, args.item_id)
    if report is None:
        raise CommandError("review item not found. A later import can replace one: run review list")
    print_report(report.lines)
    return 0


def run_review_reject(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    pairs = [tuple(pair) for pair in args.pair]
    result = reject_pairs(conn, account_id, args.item_id, args.revision, pairs)

    print(f"Decision {result.decision_id} recorded: {result.pairs} pairs rejected.")
    print(f"  Source-record pairs bound: {result.bound_record_pairs}. New records are not bound.")
    print("  Totals and source memberships are unchanged, and these transactions stay counted.")
    if result.item_still_open:
        print(f"  Item {args.item_id} stays open: undecided candidates remain in it.")
    else:
        print(f"  Item {args.item_id} closed: no undecided candidate relationship remains in it.")
    return 0


def check_superseding(args) -> None:
    if bool(args.supersedes) != bool(args.supersedes_revision):
        raise CommandError("--supersedes and --supersedes-revision must be given together.")
    if args.keep and not args.supersedes:
        raise CommandError("--keep needs --supersedes.")


def print_superseding(args, result) -> None:
    if args.supersedes:
        print(
            f"  Supersedes decision {args.supersedes}: {result.contradicted_pairs} of its pairs "
            f"contradicted, {result.kept_pairs} kept. It stays on record."
        )


def run_review_confirm(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    check_superseding(args)
    result = confirm_groups(
        conn, account_id, args.item_id, args.revision, args.group,
        supersedes=args.supersedes, supersedes_revision=args.supersedes_revision,
        keep=tuple(args.keep),
    )

    print(f"Decision {result.decision_id} recorded: {result.groups} groups confirmed.")
    print_superseding(args, result)
    print(f"  Transactions: {result.transactions_before} before, {result.transactions_after} now.")
    print("  Transactions left out stay undecided. New records are not bound.")
    print(f"  {CONFIRM_NOTICE}")
    if result.item_still_open:
        print(f"  Item {args.item_id} stays open: undecided relationships remain in it.")
    else:
        print(f"  Item {args.item_id} closed: nothing in it is left undecided.")
    return 0


def run_review_merges(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    if args.account:
        accounts = [find_account(conn, args.account)]
    else:
        accounts = [row[0] for row in conn.execute("SELECT id FROM account ORDER BY id")]
    found = 0
    for account_id in accounts:
        for transaction_id, records, rules in separable_transactions(conn, account_id):
            print(f"Transaction {transaction_id}: {records} records, {', '.join(rules)}")
            found += 1
    print(f"Transactions holding records joined automatically: {found}")
    if found:
        print("To see one's evidence, including amounts and descriptions, run review merge show.")
    return 0


def run_review_merge_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    merge = load_merge_evidence(conn, args.transaction_id)
    if merge is None:
        raise CommandError("transaction not found. Run review merges.")
    return print_transaction_inspection(merge)


def run_review_transaction_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    merge = load_merge_evidence(conn, args.transaction_id)
    if merge is None:
        raise CommandError("transaction not found. Run transactions.")
    return print_transaction_inspection(merge)


def print_transaction_inspection(merge) -> int:
    """One transaction's evidence, as review merge show and review transaction show print it."""
    entry = merge.transaction
    print(f"Transaction {entry.transaction_id}")
    print(f"  Account: {shown(merge.account_name)} ({merge.account_id})")
    print(f"  Records: {len(entry.records)}")
    print(f"  Revision: {transaction_revision(merge)}")
    evidence = ReportLines()
    add_decided_pairs(evidence, merge)
    add_transaction_evidence(evidence, entry, {})
    evidence.add("Coverage evidence:")
    for document in merge.documents:
        add_document_evidence(evidence, document)
    print_report(evidence)
    if merge.account_stale:
        print(
            "This account has not been reconciled under the current matching rules, so this "
            "evidence may be out of date. Run reconcile."
        )
    return 0


def run_review_separate(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    check_superseding(args)
    result = separate_records(
        conn, account_id, args.transaction_id, args.revision, args.group,
        supersedes=args.supersedes, supersedes_revision=args.supersedes_revision,
        keep=tuple(args.keep),
    )

    print(f"Decision {result.decision_id} recorded: {result.groups} groups separated.")
    print_superseding(args, result)
    print(f"  Transactions: {result.transactions_before} before, {result.transactions_after} now.")
    print("  New records are not bound, so a later file can raise the question again.")
    if result.overridden_id_guarantee:
        print(f"  {ID_OVERRIDE_NOTICE.format(guarantee=result.overridden_id_guarantee)}")
    print(f"  {SEPARATE_NOTICE}")
    return 0


def run_review_decisions(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    rows = list_decisions(conn, account_id)
    for decision_id, account, created_at, state, pairs, kind in rows:
        print(
            f"Decision {decision_id}: {state}, {kind}, {pairs} pairs, {shown(account)}, "
            f"{created_at}"
        )
    print(f"Decisions: {len(rows)}")
    if rows:
        print("To see what a decision binds, run review decision show.")
    return 0


def run_review_decision_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    decision = load_decision(conn, args.decision_id)
    if decision is None:
        raise CommandError("decision not found. Run review decisions.")

    print(f"Decision {decision.decision_id}")
    print(f"  Account: {shown(decision.account_name)} ({decision.account_id})")
    print(f"  Kind: {shown_kind(decision.kind, decision.target_kind)}")
    print(f"  Status: {decision.state}")
    print(f"  Made: {decision.created_at}")
    if decision.undone_at:
        print(f"  Undone: {decision.undone_at}. It stays on record and no longer applies.")
    if decision.superseded_by:
        print(
            f"  Superseded by decision {decision.superseded_by}. It stays on record and no "
            "longer applies, unless that decision is undone."
        )
    if decision.newest != decision.superseded_by:
        print(
            f"  Newest of its chain: decision {decision.newest}, the only one that can be "
            "undone. Each undo restores the decision before it."
        )
    if decision.supersedes_decision_id:
        print(f"  Supersedes decision {decision.supersedes_decision_id}")
    if decision.target_kind == "transaction":
        print(f"  From transaction: {decision.target_id}")
    else:
        print(f"  From review item: {decision.target_id}")

    for number, pair in enumerate(decision.pairs, start=1):
        print(f"Pair {number} of {len(decision.pairs)}: {pair.relation}")
        if pair.left_part is None:
            print(f"  At decision time: {pair.left_transaction_id} and {pair.right_transaction_id}")
        elif pair.left_part == pair.right_part:
            print(f"  At decision time: both in {pair.left_transaction_id}, group {pair.left_part}")
        else:
            print(
                f"  At decision time: both in {pair.left_transaction_id}, groups "
                f"{pair.left_part} and {pair.right_part}"
            )
        for label, records in (("One side", pair.left), ("Other side", pair.right)):
            print(f"  {label}:")
            for record in records:
                where = record.transaction_id or "no transaction"
                print(f"    {shown(record.file_name)} row {record.row}, now in {where}")

    if decision.state == STATE_ACTIVE:
        stale = bool(stale_accounts(conn, DEFAULT_RULES, decision.account_id))
        outlook = undo_outlook(conn, decision, DEFAULT_RULES)
        print(f"  Revision: {outlook.revision}")
        print("Undoing this decision now:")
        if decision.supersedes_decision_id:
            print(f"  Restores decision {decision.supersedes_decision_id}, which it superseded")
        print(f"  Transactions: {outlook.transactions_now} now, {outlook.transactions_after} after")
        if outlook.changes_corrected_values:
            print("  Changes which corrected values apply, or where. Run review corrections after.")
        if outlook.changes_classifications:
            print(
                "  Changes which classifications apply, or where. Run review classifications after."
            )
        print(f"  {UNDO_NOTICE}")
        if stale:
            print(
                "This account has not been reconciled under the current matching rules, so "
                "undo will be refused until it is. Run reconcile."
            )
    return 0


def run_review_undo(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    result = undo_decision(conn, account_id, args.decision_id, args.revision)

    print(f"Decision {args.decision_id} undone. It stays on record and no longer applies.")
    if result.restored:
        print(f"  Decision {result.restored}, which it superseded, applies again.")
    print(f"  Transactions: {result.transactions_before} before, {result.transactions_after} now.")
    print(f"  Source memberships changed: {result.moved_records}")
    print_newly_unsettled(result.newly_unsettled_correction_fields)
    print_newly_unclassified(result.newly_unclassified_transactions)
    print_newly_unmatched(result.newly_unsettled_matches)
    print(f"  {UNDO_NOTICE}")
    return 0


def print_newly_unsettled(count) -> None:
    if count:
        print(
            f"  Corrected fields now using their source value, because corrections disagree or "
            f"lost their basis: {count}. Run review corrections."
        )


def run_review_correct(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    if bool(args.supersedes) != bool(args.supersedes_revision):
        raise CommandError("--supersedes and --supersedes-revision must be given together.")
    result = correct_value(
        conn, account_id, args.transaction_id, args.revision, args.field, args.value,
        supersedes=args.supersedes, supersedes_revision=args.supersedes_revision,
    )

    print(
        f"Correction {result.correction_id} recorded: the {result.field} of transaction "
        f"{args.transaction_id}, binding {result.bound_record_count} records."
    )
    if args.supersedes:
        print(f"  Supersedes correction {args.supersedes}. It stays on record.")
    print(f"  {CORRECTION_NOTICE}")
    return 0


def run_review_corrections(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    rows = list_corrections(conn, account_id)
    for correction_id, account, created_at, state, field, bound_count in rows:
        print(
            f"Correction {correction_id}: {state}, {field}, {bound_count} records, "
            f"{shown(account)}, {created_at}"
        )
    print(f"Corrections: {len(rows)}")
    unsettled = conn.execute(
        """SELECT fix.transaction_id, fix.field, fix.state FROM transaction_correction fix
           JOIN ledger_transaction entry ON entry.id = fix.transaction_id
           WHERE fix.state <> 'applied' AND (:account IS NULL OR entry.account_id = :account)
           ORDER BY fix.transaction_id, fix.field""",
        {"account": account_id},
    ).fetchall()
    for transaction_id, field, state in unsettled:
        print(f"Transaction {transaction_id}, {field}: {FIELD_STATE_EXPLANATIONS[state]}")
    if rows:
        print("To see what a correction binds, run review correction show.")
    return 0


# How a field's state reads in an undo preview. None means no correction applies at all.
PREVIEW_STATES = {
    None: "source value, uncorrected",
    FIELD_APPLIED: "corrected",
    FIELD_IN_CONFLICT: "source value, corrections disagree",
    FIELD_BASIS_CHANGED: "source value, basis changed",
}


def run_review_correction_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    correction = load_correction(conn, args.correction_id)
    if correction is None:
        raise CommandError("correction not found. Run review corrections.")

    print(f"Correction {correction.correction_id}")
    print(f"  Account: {shown(correction.account_name)} ({correction.account_id})")
    print(f"  Field: {correction.field}")
    print(f"  Status: {correction.state}")
    print(f"  Made: {correction.created_at}")
    if correction.undone_at:
        print(f"  Undone: {correction.undone_at}. It stays on record and no longer applies.")
    if correction.superseded_by:
        print(
            f"  Superseded by correction {correction.superseded_by}. It stays on record and no "
            "longer applies, unless that correction is undone."
        )
    if correction.newest_of_chain != correction.superseded_by:
        print(
            f"  Newest of its chain: correction {correction.newest_of_chain}, the only one that "
            "can be undone. Each undo restores the correction before it."
        )
    if correction.supersedes_correction_id:
        print(f"  Supersedes correction {correction.supersedes_correction_id}")
    print(f"  From transaction: {correction.target_transaction_id}")
    print("Bound records:")
    for record in correction.bound_records:
        where = record.transaction_id or "no transaction"
        print(f"  {shown(record.file_name)} row {record.row}, now in {where}")

    if correction.state == STATE_ACTIVE:
        outlook = correction_undo_outlook(conn, correction)
        print(f"  Revision: {outlook.revision}")
        print("Undoing this correction now:")
        if correction.supersedes_correction_id:
            print(
                f"  Restores correction {correction.supersedes_correction_id}, which it superseded"
            )
        for transaction_id, state_now, state_after in outlook.field_state_by_transaction:
            print(
                f"  Transaction {transaction_id}, {correction.field}: {PREVIEW_STATES[state_now]} "
                f"now, {PREVIEW_STATES[state_after]} after"
            )
        if stale_accounts(conn, DEFAULT_RULES, correction.account_id):
            print(
                "This account has not been reconciled under the current matching rules, so "
                "undo will be refused until it is. Run reconcile."
            )
    return 0


def run_review_correction_undo(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    result = undo_correction(conn, account_id, args.correction_id, args.revision)

    print(f"Correction {args.correction_id} undone. It stays on record and no longer applies.")
    if result.restored:
        print(f"  Correction {result.restored}, which it superseded, applies again.")
    print_newly_unsettled(result.newly_unsettled_fields)
    print_newly_unclassified(result.newly_unclassified_transactions)
    print_newly_unmatched(result.newly_unsettled_matches)
    print(f"  {CORRECTION_UNDO_NOTICE}")
    return 0


def print_newly_unmatched(count) -> None:
    if count:
        print(
            f"  Transfer matches or one-sided transfers that no longer apply, because records split "
            f"or reach another, amounts no longer offset, a type no longer fits, or a counterpart "
            f"now shows or is covered: {count}. Run review transfers."
        )


def print_newly_unclassified(count) -> None:
    if count:
        print(
            f"  Classified transactions now unclassified, because classifications disagree, lost "
            f"their basis or no longer fit the direction: {count}. Run review classifications."
        )


def run_review_classify(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    if bool(args.supersedes) != bool(args.supersedes_revision):
        raise CommandError("--supersedes and --supersedes-revision must be given together.")
    result = classify_transaction(
        conn, account_id, args.transaction_id, args.revision, args.financial_type,
        supersedes=args.supersedes, supersedes_revision=args.supersedes_revision,
    )

    print(
        f"Classification {result.classification_id} recorded: transaction {args.transaction_id} "
        f"is a {result.financial_type}, binding {result.bound_record_count} records."
    )
    if args.supersedes:
        print(f"  Supersedes classification {args.supersedes}. It stays on record.")
    print(f"  {CLASSIFY_NOTICE}")
    return 0


def run_review_classifications(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    rows = list_classifications(conn, account_id)
    for classification_id, account, created_at, state, financial_type, bound_count in rows:
        print(
            f"Classification {classification_id}: {state}, {financial_type}, {bound_count} "
            f"records, {shown(account)}, {created_at}"
        )
    print(f"Classifications: {len(rows)}")
    unsettled = conn.execute(
        """SELECT kind.transaction_id, kind.state FROM transaction_classification kind
           JOIN ledger_transaction entry ON entry.id = kind.transaction_id
           WHERE kind.state <> 'applied' AND (:account IS NULL OR entry.account_id = :account)
           ORDER BY kind.transaction_id""",
        {"account": account_id},
    ).fetchall()
    for transaction_id, state in unsettled:
        print(f"Transaction {transaction_id}: {CLASSIFICATION_STATE_EXPLANATIONS[state]}")
    if rows:
        print("To see what a classification binds, run review classification show.")
    return 0


# How a classified transaction's outcome reads in an undo preview.
CLASSIFICATION_PREVIEW_STATES = {
    None: UNCLASSIFIED,
    FIELD_APPLIED: "classified",
    FIELD_IN_CONFLICT: "unclassified, classifications disagree",
    FIELD_BASIS_CHANGED: "unclassified, basis changed",
    TYPE_AGAINST_DIRECTION: "unclassified, against its direction",
}


def run_review_classification_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    classification = load_classification(conn, args.classification_id)
    if classification is None:
        raise CommandError("classification not found. Run review classifications.")

    print(f"Classification {classification.classification_id}")
    print(f"  Account: {shown(classification.account_name)} ({classification.account_id})")
    print(f"  Type: {classification.financial_type}")
    print(f"  Status: {classification.state}")
    print(f"  Made: {classification.created_at}")
    if classification.undone_at:
        print(f"  Undone: {classification.undone_at}. It stays on record and no longer applies.")
    if classification.superseded_by:
        print(
            f"  Superseded by classification {classification.superseded_by}. It stays on record "
            "and no longer applies, unless that classification is undone."
        )
    if classification.newest_of_chain != classification.superseded_by:
        print(
            f"  Newest of its chain: classification {classification.newest_of_chain}, the only "
            "one that can be undone. Each undo restores the classification before it."
        )
    if classification.supersedes_classification_id:
        print(f"  Supersedes classification {classification.supersedes_classification_id}")
    print(f"  From transaction: {classification.target_transaction_id}")
    print("Bound records:")
    for record in classification.bound_records:
        where = record.transaction_id or "no transaction"
        print(f"  {shown(record.file_name)} row {record.row}, now in {where}")

    if classification.state == STATE_ACTIVE:
        outlook = classification_undo_outlook(conn, classification)
        print(f"  Revision: {outlook.revision}")
        print("Undoing this classification now:")
        if classification.supersedes_classification_id:
            print(
                f"  Restores classification {classification.supersedes_classification_id}, which "
                "it superseded"
            )
        for transaction_id, state_now, state_after in outlook.state_by_transaction:
            print(
                f"  Transaction {transaction_id}: {CLASSIFICATION_PREVIEW_STATES[state_now]} now, "
                f"{CLASSIFICATION_PREVIEW_STATES[state_after]} after"
            )
        if stale_accounts(conn, DEFAULT_RULES, classification.account_id):
            print(
                "This account has not been reconciled under the current matching rules, so "
                "undo will be refused until it is. Run reconcile."
            )
    return 0


def run_review_classification_undo(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    result = undo_classification(conn, account_id, args.classification_id, args.revision)

    print(
        f"Classification {args.classification_id} undone. It stays on record and no longer "
        "applies."
    )
    if result.restored:
        print(f"  Classification {result.restored}, which it superseded, applies again.")
    print_newly_unclassified(result.newly_unclassified_transactions)
    print_newly_unmatched(result.newly_unsettled_matches)
    print(f"  {CLASSIFICATION_UNDO_NOTICE}")
    return 0


def run_review_transfers(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    name_by_account = dict(conn.execute("SELECT id, display_name FROM account"))

    def side(facts):
        kind = facts.financial_type or UNCLASSIFIED
        return (f"transaction {facts.transaction_id} ({shown(name_by_account[facts.account_id])}, "
                f"{kind})")

    candidates = transfer_candidates(conn, account_id)
    for candidate in candidates:
        print(f"Candidate: {side(candidate.outflow)} to {side(candidate.inflow)}")
    print(f"Transfer candidates: {len(candidates)}")
    rows = list_matches(conn, account_id)
    for match_id, state, effect, outflow_account, inflow_account, created_at in rows:
        outcome = f", {effect}" if effect else ""
        print(
            f"Match {match_id}: {state}{outcome}, {shown(outflow_account)} to "
            f"{shown(inflow_account)}, {created_at}"
        )
    print(f"Transfer matches: {len(rows)}")
    one_sided_rows = list_one_sided(conn, account_id)
    for statement_id, state, effect, own, counterpart, created_at in one_sided_rows:
        outcome = f", {effect}" if effect else ""
        print(
            f"One-sided transfer {statement_id}: {state}{outcome}, {shown(own)} with "
            f"{shown(counterpart)}, {created_at}"
        )
    print(f"One-sided transfers: {len(one_sided_rows)}")
    if candidates:
        print(
            "A candidate is a transfer kind on one side and the exactly opposite amount in another "
            f"account within {TRANSFER_DATE_WINDOW_DAYS} days. To see its evidence, including "
            "amounts, run review transaction show on each side."
        )
    if rows or one_sided_rows:
        print("To see what a match or one-sided transfer binds, run review transfer show.")
    return 0


def run_review_transfer_match(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    counterpart_account_id = find_account(conn, args.counterpart_account)
    result = match_transfer(
        conn, account_id, args.transaction_id, args.revision, counterpart_account_id,
        args.counterpart_id, args.counterpart_revision,
    )

    print(
        f"Match {result.match_id} recorded: transaction {result.outflow_transaction_id} to "
        f"transaction {result.inflow_transaction_id}, binding {result.outflow_record_count} and "
        f"{result.inflow_record_count} records."
    )
    print(f"  {MATCH_NOTICE}")
    return 0


def run_review_transfer_one_sided(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    counterpart_account_id = find_account(conn, args.counterpart_account)
    result = state_one_sided(conn, account_id, args.transaction_id, args.revision,
                             counterpart_account_id)

    print(
        f"One-sided transfer {result.one_sided_transfer_id} recorded: transaction "
        f"{args.transaction_id} with {shown(args.counterpart_account)}, binding "
        f"{result.record_count} records."
    )
    print(f"  {ONE_SIDED_NOTICE}")
    return 0


def run_review_transfer_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    match = load_match(conn, args.transfer_id)
    if match is None:
        statement = load_one_sided(conn, args.transfer_id)
        if statement is None:
            raise CommandError(
                "transfer match or one-sided transfer not found. Run review transfers.")
        return print_one_sided(conn, statement)

    print(f"Transfer match {match.match_id}")
    print(f"  Status: {match.state}")
    print(f"  Made: {match.created_at}")
    if match.undone_at:
        print(f"  Undone: {match.undone_at}. It stays on record and no longer applies.")
    for side in (match.outflow, match.inflow):
        print(f"{side.side.capitalize()} side:")
        print(f"  Account: {shown(side.account_name)} ({side.account_id})")
        print(f"  From transaction: {side.target_transaction_id}")
        for record in side.bound_records:
            where = record.transaction_id or "no transaction"
            print(f"  {shown(record.file_name)} row {record.row}, now in {where}")
    if match.state == STATE_ACTIVE:
        print(f"  Transfer: {MATCH_STATE_EXPLANATIONS[match.effect]}")
        print(f"  Revision: {match_revision(conn, match)}")
        print(f"Undoing this match now: {MATCH_UNDO_NOTICE}")
        if stale_accounts(conn, DEFAULT_RULES, match.outflow.account_id) or stale_accounts(
                conn, DEFAULT_RULES, match.inflow.account_id):
            print(
                "An account of this match has not been reconciled under the current matching "
                "rules, so undo will be refused until it is. Run reconcile."
            )
    return 0


def print_one_sided(conn, statement) -> int:
    print(f"One-sided transfer {statement.one_sided_transfer_id}")
    print(f"  Status: {statement.state}")
    print(f"  Made: {statement.created_at}")
    if statement.undone_at:
        print(f"  Undone: {statement.undone_at}. It stays on record and no longer applies.")
    print(f"  Account: {shown(statement.account_name)} ({statement.account_id})")
    print(f"  Counterpart: {shown(statement.counterpart_account_name)} "
          f"({statement.counterpart_account_id})")
    print(f"  From transaction: {statement.target_transaction_id}")
    for record in statement.bound_records:
        where = record.transaction_id or "no transaction"
        print(f"  {shown(record.file_name)} row {record.row}, now in {where}")
    if statement.state == STATE_ACTIVE:
        print(f"  Transfer: {ONE_SIDED_STATE_EXPLANATIONS[statement.effect]}")
        print(f"  Revision: {one_sided_revision(conn, statement)}")
        print(f"Undoing this one-sided transfer now: {ONE_SIDED_UNDO_NOTICE}")
        if any(stale_accounts(conn, DEFAULT_RULES, account) for account in statement.account_ids):
            print(
                "An account of this one-sided transfer has not been reconciled under the current "
                "matching rules, so undo will be refused until it is. Run reconcile."
            )
    return 0


def run_review_transfer_undo(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    if load_one_sided(conn, args.transfer_id) is not None:
        newly_unsettled = undo_one_sided(conn, account_id, args.transfer_id, args.revision)
        print(f"One-sided transfer {args.transfer_id} undone. It stays on record and no longer "
              "applies.")
        print(f"  {ONE_SIDED_UNDO_NOTICE}")
        print_newly_unmatched(newly_unsettled)
        return 0
    if load_match(conn, args.transfer_id) is None:
        raise CommandError("transfer match or one-sided transfer not found. Run review transfers.")
    newly_unsettled = undo_transfer(conn, account_id, args.transfer_id, args.revision)

    print(f"Match {args.transfer_id} undone. It stays on record and no longer applies.")
    print(f"  {MATCH_UNDO_NOTICE}")
    print_newly_unmatched(newly_unsettled)
    return 0


def run_review_complete(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    supplied = {
        field: value
        for field, value in (("amount", args.amount), ("transaction_date", args.transaction_date),
                             ("posting_date", args.posting_date),
                             ("description", args.description))
        if value is not None
    }
    result = complete_record(conn, account_id, args.item_id, args.revision, supplied)

    fields = ", ".join(result.supplied_fields) or "nothing, since every value was read"
    print(f"Resolution {result.resolution_id} recorded: row completed, supplying {fields}.")
    print(f"  Now transaction {result.transaction_id}. Item {args.item_id} closed.")
    print_resolution_effect(result)
    print(f"  {COMPLETE_NOTICE}")
    return 0


def run_review_dismiss(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    result = dismiss_record(conn, account_id, args.item_id, args.revision)

    print(f"Resolution {result.resolution_id} recorded: row dismissed. Item {args.item_id} closed.")
    print_resolution_effect(result)
    print(f"  {DISMISS_NOTICE}")
    return 0


def print_resolution_effect(result) -> None:
    print(f"  Transactions: {result.transactions_before} before, {result.transactions_after} now.")
    print(f"  Source memberships changed: {result.moved_records}")
    print_newly_unsettled(result.newly_unsettled_correction_fields)
    print_newly_unclassified(result.newly_unclassified_transactions)
    print_newly_unmatched(result.newly_unsettled_matches)


def run_review_resolutions(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    rows = list_resolutions(conn, account_id)
    for resolution_id, account, created_at, state, kind, file_name, row in rows:
        print(
            f"Resolution {resolution_id}: {state}, {kind}, {shown(file_name)} row {row}, "
            f"{shown(account)}, {created_at}"
        )
    print(f"Resolutions: {len(rows)}")
    if rows:
        print("To see what a resolution resolved, run review resolution show.")
    return 0


def run_review_resolution_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    resolution = load_resolution(conn, args.resolution_id)
    if resolution is None:
        raise CommandError("resolution not found. Run review resolutions.")

    record = resolution.record
    print(f"Resolution {resolution.resolution_id}")
    print(f"  Account: {shown(resolution.account_name)} ({resolution.account_id})")
    print(f"  Kind: {resolution.kind}")
    print(f"  Status: {resolution.state}")
    print(f"  Made: {resolution.created_at}")
    if resolution.undone_at:
        print(f"  Undone: {resolution.undone_at}. It stays on record and no longer applies.")
    print(f"  From review item: {resolution.target_issue_id}")
    print(f"  Record: {shown(record.file_name)} row {record.row}, now in "
          f"{record.transaction_id or 'no transaction'}")
    if resolution.kind == "completed":
        supplied = [field for field, value in zip(
            ("amount", "transaction_date", "posting_date", "description"),
            resolution.completed_values) if value is not None]
        print(f"  Supplied: {', '.join(supplied) or 'nothing, since every value was read'}")

    if resolution.state == STATE_ACTIVE:
        outlook = resolution_undo_outlook(conn, resolution, DEFAULT_RULES)
        print(f"  Revision: {outlook.revision}")
        print("Undoing this resolution now:")
        print(f"  Transactions: {outlook.transactions_now} now, {outlook.transactions_after} after")
        if resolution.kind == "completed":
            decisions, corrections, classifications, matches, one_sided = binding_entries(
                conn, record.record_id)
            for decision in decisions:
                print(f"  Refused while decision {decision} binds the record. Undo it first.")
            for correction in corrections:
                print(f"  Refused while correction {correction} binds the record. Undo it first.")
            for classification in classifications:
                print(
                    f"  Refused while classification {classification} binds the record. Undo it "
                    "first."
                )
            for match in matches:
                print(
                    f"  Refused while transfer match {match} binds the record. Undo it first."
                )
            for statement in one_sided:
                print(
                    f"  Refused while one-sided transfer {statement} binds the record. Undo it "
                    "first."
                )
        print(f"  {RESOLUTION_UNDO_NOTICE}")
        if stale_accounts(conn, DEFAULT_RULES, resolution.account_id):
            print(
                "This account has not been reconciled under the current matching rules, so "
                "undo will be refused until it is. Run reconcile."
            )
    return 0


def run_review_resolution_undo(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    result = undo_resolution(conn, account_id, args.resolution_id, args.revision)

    print(f"Resolution {args.resolution_id} undone. It stays on record and no longer applies.")
    print(f"  The row is unresolved again, as item {result.issue_id}.")
    print_resolution_effect(result)
    print(f"  {RESOLUTION_UNDO_NOTICE}")
    return 0


def run_review_coverage_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    document = load_document_coverage(conn, args.document_id)
    if document is None:
        raise CommandError("document not found. Run documents.")

    print(f"Document {document.document_id}: {shown(document.file_name)}")
    print(f"  Account: {shown(document.account_name)} ({document.account_id})")
    print(f"  Layout: {document.layout_id}")
    print(f"  Document SHA-256: {document.content_sha256}")
    print(f"  Claimed at import: {describe_coverage_kind(document.claimed, document)}")
    if document.declaration_id:
        print(f"  Declared after import: {describe_coverage_kind(document.effective, document)}, "
              f"declaration {document.declaration_id}")
    print(f"  Matching uses: {describe_coverage_kind(document.effective, document)}")
    print(f"  Date bases this layout offers: {', '.join(document.offered_bases) or 'none'}")
    print(f"  Revision: {document_coverage_revision(document)}")
    if document.claimed.evidence == "document_metadata":
        print("  The document states this coverage itself, so it can only be withdrawn.")

    history = [row for row in list_declarations(conn, document.account_id)
               if load_declaration(conn, row[0]).document_id == document.document_id]
    if history:
        print("Declarations, oldest first:")
    for declaration_id, _, created_at, state, kind, _ in history:
        print(f"  Declaration {declaration_id}: {state}, {kind}, {created_at}")
    if document.declaration_id:
        declaration = load_declaration(conn, document.declaration_id)
        outlook = declaration_undo_outlook(conn, declaration, DEFAULT_RULES)
        print(f"Undoing declaration {declaration.declaration_id} now:")
        print(f"  Revision: {outlook.revision}")
        restored = declaration.supersedes_declaration_id
        print(f"  Restores {f'declaration {restored}' if restored else 'the claim at import'}")
        print(f"  Transactions: {outlook.transactions_now} now, {outlook.transactions_after} after")
    if stale_accounts(conn, DEFAULT_RULES, document.account_id):
        print(
            "This account has not been reconciled under the current matching rules, so "
            "declaring and undoing will be refused until it is. Run reconcile."
        )
    return 0


def run_review_coverage_declare(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    result = declare_coverage(
        conn, account_id, args.document_id, args.revision, args.coverage_kind,
        args.coverage_start, args.coverage_end, args.coverage_basis,
    )

    print(f"Declaration {result.declaration_id} recorded for document {args.document_id}.")
    if result.other_declaration_id:
        print(f"  Supersedes declaration {result.other_declaration_id}. It stays on record.")
    print_coverage_effect(result)
    print(f"  {COVERAGE_NOTICE}")
    return 0


def print_coverage_effect(result) -> None:
    print(f"  Transactions: {result.transactions_before} before, {result.transactions_after} now.")
    print(f"  Source memberships changed: {result.moved_records}")
    print_newly_unsettled(result.newly_unsettled_correction_fields)
    print_newly_unclassified(result.newly_unclassified_transactions)
    print_newly_unmatched(result.newly_unsettled_matches)


def run_review_coverage_history(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    rows = list_declarations(conn, account_id)
    for declaration_id, account, created_at, state, kind, file_name in rows:
        print(
            f"Declaration {declaration_id}: {state}, {kind}, {shown(file_name)}, {shown(account)}, "
            f"{created_at}"
        )
    print(f"Coverage declarations: {len(rows)}")
    if rows:
        print("To see a document's coverage and undo its declaration, run review coverage show.")
    return 0


def run_review_coverage_undo(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    result = undo_declaration(conn, account_id, args.declaration_id, args.revision)

    print(f"Declaration {args.declaration_id} undone. It stays on record and no longer applies.")
    restored = result.other_declaration_id
    print(f"  {f'Declaration {restored}' if restored else 'The claim at import'} applies again.")
    print_coverage_effect(result)
    print(f"  {COVERAGE_UNDO_NOTICE}")
    return 0


def run_totals(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    print_report(totals_report_lines(conn, account_id))
    return 0


BALANCE_NOTICE = (
    "An observation is evidence about balances only. It is not transaction evidence, so it changes "
    "no total, review item or coverage. Run balance check to compare it with the transactions."
)

BALANCE_UNDO_NOTICE = (
    "The intervals either side of it are one interval again. Run balance check to see them."
)


def shown_balance(observation, cents) -> str:
    """A balance as the account states it: what a card or loan owes, else its balance."""
    return f"owed {format_cents(-cents)}" if observation.states_owed else format_cents(cents)


def run_balance_record(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    owed = args.owed is not None
    observation_id = record_observation(
        conn, account_id, args.date, args.owed if owed else args.balance, owed=owed)

    observation = load_observation(conn, observation_id)
    print(
        f"Balance observation {observation_id} recorded: {shown(observation.account_name)} on "
        f"{observation.observed_on}, {shown_balance(observation, observation.balance_cents)}."
    )
    print(f"  {BALANCE_NOTICE}")
    return 0


def run_balance_list(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    observations = list_observations(conn, account_id)
    for observation in observations:
        print(
            f"Observation {observation.observation_id}: {shown(observation.account_name)} on "
            f"{observation.observed_on}, {shown_balance(observation, observation.balance_cents)}, "
            f"{observation.state}, made {observation.created_at}"
        )
        if observation.state == STATE_ACTIVE:
            print(f"  Token: {observation_revision(conn, observation)}")
        else:
            print(f"  Undone: {observation.undone_at}. It stays on record and no longer applies.")
    active = sum(observation.state == STATE_ACTIVE for observation in observations)
    print(f"Balance observations: {len(observations)}, of which active: {active}")
    return 0


def run_balance_check(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account)
    check = check_balances(conn, account_id)

    print(f"Active balance observations: {len(check.observations)}")
    if len(check.observations) < 2:
        print("An interval needs two observations, so there is nothing to compare yet.")
    for interval in check.intervals:
        opening, closing = interval.opening, interval.closing
        difference = interval.difference_cents
        if opening.states_owed:
            difference = -difference
        outcome = "agrees" if difference == 0 else f"differs by {format_cents(difference)}"
        print(f"After {opening.observed_on} through {closing.observed_on}: {outcome}")
        print(
            f"  Opening {shown_balance(opening, opening.balance_cents)}, account movement "
            f"{format_cents(interval.activity.cents)} over {interval.activity.transactions} "
            f"transactions, expected {shown_balance(closing, interval.expected_closing_cents)}, "
            f"observed {shown_balance(closing, closing.balance_cents)}"
        )
        if interval.covered:
            print("  Covered: complete posting-basis coverage spans every day of it.")
        else:
            print(
                "  Not covered: complete posting-basis coverage does not span every day of it, so "
                "transactions may be missing."
            )
        for label, counted in (
            ("Pending, left out", interval.pending_left_out),
            ("Of unknown status, counted", interval.unknown_status),
            ("With no posting date, counted by transaction date", interval.without_posting_date),
        ):
            if counted.transactions:
                print(f"  {label}: {counted.transactions} transactions, "
                      f"{format_cents(counted.cents)}")
        if interval.open_review_items:
            print(
                f"  Open review items: {len(interval.open_review_items)}, holding "
                f"{interval.transactions_in_open_review_items} transactions here"
            )

    print("Disclosures:")
    print(
        "- Agreement is evidence, not coverage. It declares no coverage, settles no review item "
        "and changes no total. A difference is shown, never absorbed into an adjustment."
    )
    print(
        "- Activity uses effective amounts, and each transaction's effective posting date, else "
        "its transaction date. Types, transfers and classifications do not enter it."
    )
    if check.unresolved_records:
        print(
            f"- {check.unresolved_records} unresolved records of this account are no transaction, "
            "so no interval counts them, and they may explain a difference."
        )
    if stale_accounts(conn, DEFAULT_RULES, account_id):
        print(
            "- This account has not been reconciled under the current matching rules, so "
            "overlapping files may be counted twice. Run reconcile."
        )
    return 0


def run_balance_undo(args) -> int:
    conn = open_ledger(args.db)
    account_id = find_account(conn, args.account)
    undo_observation(conn, account_id, args.observation_id, args.token)

    print(f"Balance observation {args.observation_id} undone. It stays on record and no longer "
          "applies.")
    print(f"  {BALANCE_UNDO_NOTICE}")
    return 0


MONTH_PATTERN = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def validated_month(option, text) -> str | None:
    if text is None:
        return None
    if not MONTH_PATTERN.fullmatch(text) or text < "0001-01":
        raise CommandError(f"{option} must be a month as YYYY-MM. Nothing was changed.")
    return text


def run_report_monthly(args) -> int:
    first_month = validated_month("--from", args.first_month)
    last_month = validated_month("--to", args.last_month)
    if first_month and last_month and first_month > last_month:
        raise CommandError("--from is after --to. Nothing was changed.")
    conn = open_ledger(args.db, read_only=True)
    account_id = find_account(conn, args.account) if args.account else None
    print_report(monthly_report_lines(conn, account_id, first_month, last_month))
    return 0


def run_ui(args) -> int:
    # Imported here, since the server imports this module for open_ledger and its messages.
    from personal_finance.ui.server import LoopbackServer

    # Through the gate before any port opens, so an unsafe ledger is refused first (D-058).
    open_ledger(args.db, read_only=True).close()
    server = LoopbackServer(args.db)
    print(f"Serving {args.db} read-only, on 127.0.0.1 only. Open this address once:")
    print(f"  {server.launch_address}")
    print("It works once, in one browser. Use a private window, so the browser keeps no history "
          "of these pages. Stop with Ctrl-C.")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # Ctrl-C is how pf ui is stopped, so it is not an error here.
        print("Stopped.")
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code = args.handler(args)
        sys.stdout.flush()
        return code
    except BrokenPipeError:
        # The reader went away, as in `pf transactions | head`. Nothing went wrong here.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return BROKEN_PIPE_EXIT
    except Exception as error:
        print(f"Error: {explained_error(error)}", file=sys.stderr)
        return 2


def explained_error(error: Exception) -> str:
    """What an error may say, the same in the CLI and the local UI. Expected errors keep their
    sanitized messages, and any other says only that something went wrong (D-037)."""
    if isinstance(error, (CommandError, DecisionRefused, UnsafeLocation, BackupRefused)):
        return str(error)
    if isinstance(error, sqlite3.OperationalError):
        return BUSY_EXPLANATION if "locked" in str(error) else "database error"
    return UNEXPECTED_ERROR
