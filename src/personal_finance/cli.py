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
from itertools import islice
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
from personal_finance.ingest.pipeline import import_files
from personal_finance.money import format_cents
from personal_finance.reconcile.apply import STATE_ACTIVE, reconcile_account, stale_accounts
from personal_finance.reconcile.balance_observations import record_observation, undo_observation
from personal_finance.reconcile.cross_document import (
    PRIMARY_CRITERIA,
    RULE_CANDIDATES,
    deciding_criterion,
    primary_rank,
)
from personal_finance.reconcile.classification_effects import (
    FINANCIAL_TYPES,
    TYPE_AGAINST_DIRECTION,
    UNCLASSIFIED,
)
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
    undecided_direct_pairs,
    undo_decision,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reconcile.transfer_effects import (
    MATCH_AMOUNTS_DIFFER,
    MATCH_APPLIED,
    MATCH_BASIS_CHANGED,
    MATCH_CONFLICT,
    MATCH_TYPE_DIFFERS,
    ONE_SIDED_COUNTERPART_COVERED,
    ONE_SIDED_COUNTERPART_FOUND,
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
from personal_finance.reports.monthly import monthly_report
from personal_finance.reports.resolution_evidence import (
    binding_entries,
    list_resolutions,
    load_resolution,
    resolution_undo_outlook,
)
from personal_finance.reports.review_evidence import (
    alike_decided_records,
    load_merge_evidence,
    load_review_evidence,
    review_revision,
    rows_sharing_a_document,
    transaction_revision,
)
from personal_finance.reports.storage import StoredFiles, storage_by_kind
from personal_finance.reports.totals import (
    account_movement,
    income_and_spending,
    one_sided_summary,
    transfer_summary,
)
from personal_finance.reports.transfer_evidence import (
    list_matches,
    list_one_sided,
    load_match,
    load_one_sided,
    match_revision,
    one_sided_revision,
)

ACCOUNT_TYPES = ("checking", "savings", "credit_card", "loan", "investment", "retirement")

MATCHING_NOTICE = (
    "Files are compared within each account. Rows matched confidently are counted once. "
    "Other duplicates can go undetected, for example where descriptions differ."
)

BUSY_EXPLANATION = (
    "database is busy: another process is using the ledger. The step that failed changed "
    "nothing. Wait for that process to finish, then run this command again."
)

BROKEN_PIPE_EXIT = 141

# A dense group holds quadratically many pairs, so review show lists only the first few.
DIRECT_PAIRS_SHOWN = 50

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


RULE_EXPLANATIONS = {
    "cross_document_candidates": "Records in different documents look alike, without proof.",
    "cross_document_external_id": "Records share a reliable ID but cannot be merged safely.",
    "identity_decision": "New evidence disagrees with a stored decision.",
    "same_document_repeated_external_id": "One external ID appears on several rows of a document.",
    "same_document_pending_posted": (
        "A pending row and a posted row of one document may be one event."
    ),
}

REASON_EXPLANATIONS = {
    "similar_description": "same amount, dates within the window, similar description",
    "coverage_unknown": "a document's coverage is unknown",
    "coverage_partial": "a document's coverage is partial",
    "different_basis": "the documents state coverage on different date bases",
    "date_outside_coverage": "the date falls outside a coverage claim",
    "pending_not_covered": "a coverage claim says nothing about pending rows",
    "boundary_date": "the date is too close to the end of what coverage supports",
    "single_day_overlap": "the documents overlap by a single day",
    "unresolved_row": "an unresolved row could affect the count",
    "completed_row": (
        "a row completed by hand could affect the count, and its typed values never make a "
        "match confident"
    ),
    "pending_amount_changed": (
        "a pending row and a posted row look alike but for their amount, as when a tip is added. "
        "Confirm them to count the posted amount once"
    ),
    "completed_record_shares_id": (
        "a record completed by hand shares this reliable ID, and is never merged automatically"
    ),
    "external_id_conflict": "records with this ID disagree on a material field",
    "external_id_repeated": "this ID is repeated within a document",
    "automatic_match_withheld": (
        "an automatic match would have joined records a decision keeps apart, so the whole "
        "match was withheld and its records stay separate and counted, which can raise totals"
    ),
    "decision_basis_changed": (
        "a transaction a decision was based on has since been divided by an automatic split, "
        "and the decision still applies to its records"
    ),
}

UNRESOLVED_NOTICE = "This row created no transaction and is not included in totals."

DUPLICATE_NOTICE = (
    "These transactions stay separate and are all counted in full. Totals may be overstated, "
    "and no exact adjustment can be stated."
)


CONFLICT_NOTICE = (
    "The decision stands. These are not possible duplicates. To settle this, confirm which "
    "transactions here are one event and which are different events with review confirm. To "
    "remove a decision, inspect it with review decision show, then use review undo."
)

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

# What each outcome of a classified transaction means (D-053).
CLASSIFICATION_STATE_EXPLANATIONS = {
    FIELD_APPLIED: "the stated type applies",
    FIELD_IN_CONFLICT: "classifications disagree, so it is unclassified. Undo all but one to settle it",
    FIELD_BASIS_CHANGED: (
        "a classification binds records now in several transactions, so it is unclassified. Undo "
        "it, then classify each transaction"
    ),
    TYPE_AGAINST_DIRECTION: (
        "its amount now runs against the stated type, as after a correction, so it is "
        "unclassified. Undo the classification, or the correction"
    ),
}

MATCH_NOTICE = (
    "Account movement and type totals are unchanged, matching never reads transfers, and new "
    "records are not bound, but a re-export that joins either side keeps the match applied."
)

MATCH_UNDO_NOTICE = "Both transactions are unmatched again, and can be matched again."

# What each outcome of a transfer match means (D-054).
MATCH_STATE_EXPLANATIONS = {
    MATCH_APPLIED: "both sides are one movement of money between your accounts",
    MATCH_BASIS_CHANGED: (
        "a side's bound records are now in several transactions, so it does not apply. Undo it, "
        "then match again"
    ),
    MATCH_CONFLICT: (
        "a transaction holds records of two matches, so neither applies. Undo all but one"
    ),
    MATCH_AMOUNTS_DIFFER: (
        "the amounts no longer offset exactly, as after a correction, so it does not apply. Undo "
        "it, or the correction"
    ),
    MATCH_TYPE_DIFFERS: (
        "a type stated on a side no longer fits a transfer between these accounts, so it does not "
        "apply. Undo it, or the classification"
    ),
}

ONE_SIDED_NOTICE = (
    "Account movement and type totals are unchanged. Its other side is not in the ledger, so totals "
    "warn about the counterpart's coverage. If that side is imported later, the one-sided transfer "
    "stops applying until you undo it and match the pair."
)

ONE_SIDED_UNDO_NOTICE = "The transaction counts as an unpaired transfer kind again."

# What each outcome of a one-sided transfer means (D-055).
ONE_SIDED_STATE_EXPLANATIONS = {
    MATCH_APPLIED: "it moves money to or from the counterpart, whose side is not in the ledger",
    MATCH_BASIS_CHANGED: (
        "its bound records are now in several transactions, so it does not apply. Undo it, then "
        "state it again"
    ),
    MATCH_CONFLICT: (
        "its transaction holds records of another match or one-sided transfer, so neither "
        "applies. Undo all but one"
    ),
    MATCH_TYPE_DIFFERS: (
        "the type stated no longer fits a transfer to the counterpart, so it does not apply. Undo "
        "it, or the classification"
    ),
    ONE_SIDED_COUNTERPART_FOUND: (
        "a transaction of the counterpart may now be its other side, so it does not apply. Undo "
        "it, then match the pair"
    ),
    ONE_SIDED_COUNTERPART_COVERED: (
        "the counterpart's complete coverage now spans its dates, so its other side would be in "
        "the ledger, and it does not apply. Undo it, or check that coverage"
    ),
}

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

# What each state of a corrected field means for the value used (D-049).
FIELD_STATE_EXPLANATIONS = {
    FIELD_APPLIED: "the corrected value is used",
    FIELD_IN_CONFLICT: (
        "corrections disagree, so the source value is used. Undo all but one to settle it"
    ),
    FIELD_BASIS_CHANGED: (
        "a correction binds records now in several transactions, so the source value is used. "
        "Undo it, then correct each transaction"
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
    return parser


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


def describe_open_groups(movement) -> str:
    return (
        f"Open review groups: {movement.candidate_groups}, covering "
        f"{movement.transactions_in_candidate_groups} distinct affected transactions."
    )


def describe_corrections(movement) -> list[str]:
    """Corrections on their own lines, apart from duplicates and conflicts (D-049)."""
    lines = []
    if movement.transactions_corrected:
        lines.append(
            f"Transactions using a corrected value: {movement.transactions_corrected}. Their "
            "source values are kept, and undoing a correction restores them."
        )
    if movement.transactions_with_correction_conflict:
        lines.append(
            f"Transactions keeping a source value because corrections disagree: "
            f"{movement.transactions_with_correction_conflict}. These are not possible duplicates "
            "or decision conflicts. Run review corrections."
        )
    if movement.transactions_with_correction_basis_changed:
        lines.append(
            f"Transactions keeping a source value because a correction binds records now in "
            f"several transactions: {movement.transactions_with_correction_basis_changed}. Run "
            "review corrections."
        )
    return lines


def describe_classifications(movement) -> list[str]:
    """Transactions a disagreement leaves unclassified, on their own lines (D-053)."""
    lines = []
    for count, reason in (
        (movement.transactions_with_classification_conflict, "classifications disagree"),
        (movement.transactions_with_classification_basis_changed,
         "a classification binds records now in several transactions"),
        (movement.transactions_with_classification_against_direction,
         "their amount runs against the stated type"),
    ):
        if count:
            lines.append(
                f"Transactions left unclassified because {reason}: {count}. These are not "
                "possible duplicates, decision conflicts or corrections. Run review "
                "classifications."
            )
    return lines


def describe_pending(movement) -> list[str]:
    """Pending-to-posted outcomes on their own lines (D-052)."""
    lines = []
    if movement.transactions_posted_at_changed_amount:
        lines.append(
            f"Transactions posted at another amount than their pending row, such as with a tip: "
            f"{movement.transactions_posted_at_changed_amount}. Each is counted once, at the "
            "posted amount."
        )
    if movement.stale_pending_transactions:
        lines.append(
            f"Pending transactions more than 10 days older than the account's latest date: "
            f"{movement.stale_pending_transactions}. They are counted, and none was removed."
        )
    return lines


def describe_declarations(movement) -> list[str]:
    """Coverage declared after import, on its own line (D-051)."""
    if not movement.documents_with_declared_coverage:
        return []
    return [
        f"Documents whose coverage you declared after import: "
        f"{movement.documents_with_declared_coverage}. Matching uses that coverage. Run review "
        "coverage history."
    ]


def describe_resolutions(movement) -> list[str]:
    """Completed and dismissed rows on their own lines, apart from everything else (D-050)."""
    lines = []
    if movement.transactions_completed:
        lines.append(
            f"Transactions holding a row you completed by hand: {movement.transactions_completed}. "
            "They are counted with the values you supplied. Run review resolutions."
        )
    if movement.records_dismissed:
        lines.append(
            f"Rows you dismissed as adding no transaction: {movement.records_dismissed}. They are "
            "not counted and are not unresolved. Run review resolutions."
        )
    return lines


def describe_conflicts(movement) -> list[str]:
    """Conflicts on their own lines, and only while there are some (D-044, D-045)."""
    if not movement.decision_conflicts:
        return []
    lines = [
        f"Decision conflicts: {movement.decision_conflicts}, covering "
        f"{movement.transactions_in_decision_conflicts} distinct affected transactions, all "
        "counted in full. These are not possible duplicates. One transaction can appear in "
        "several of these counts."
    ]
    if movement.transactions_with_withheld_match:
        lines.append(
            f"Transactions in conflicts where an automatic match was withheld: "
            f"{movement.transactions_with_withheld_match}. Their records stay separate, which "
            "can raise the transaction count and account movements."
        )
    if movement.transactions_with_changed_basis:
        lines.append(
            f"Transactions in conflicts where a decision's basis changed: "
            f"{movement.transactions_with_changed_basis}."
        )
    return lines


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
    rows = conn.execute(
        """SELECT document.id, document.file_name, document.layout_id, account.display_name,
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
    for document_id, name, layout_id, account, kind, start, end, basis, evidence, records, _ in rows:
        line = f"{name}: {records} records, account {account}, layout {layout_id}, "
        document = load_document_coverage(conn, document_id)
        line += describe_coverage_kind(document.effective, document)
        if document.declaration_id:
            line += f", declared after import, claimed at import: {kind}"
        print(f"Document {document_id}: {line}")
    if not rows:
        print("No documents.")
    return 0


def describe_coverage_kind(coverage, document) -> str:
    """One coverage as documents prints it. Pending treatment follows its basis (D-026)."""
    line = f"coverage {coverage.kind}"
    if coverage.kind != "unknown":
        line += (f" {coverage.start or '?'} to {coverage.end or '?'}, {coverage.date_basis or 'no'}"
                 f" basis, evidence {coverage.evidence}")
    if coverage.kind == "complete":
        pending = document_pending_included(document, coverage.date_basis)
        line += f", pending {'included' if pending else 'excluded'}"
    return line


def document_pending_included(document, basis) -> bool:
    return dict(document.pending_included_by_basis)[basis]


def run_transactions(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    # Effective values: a corrected value where one applies, else the source value (D-049).
    rows = conn.execute(
        """SELECT entry.id,
                  COALESCE(fixed_transaction_date.corrected_text, entry.transaction_date,
                           fixed_posting_date.corrected_text, entry.posting_date) AS shown_date,
                  COALESCE(fixed_amount.corrected_amount_cents, entry.amount_cents),
                  entry.settlement_status,
                  COALESCE(fixed_description.corrected_text, entry.description),
                  EXISTS (SELECT 1 FROM transaction_correction fix
                          WHERE fix.transaction_id = entry.id AND fix.state = 'applied'),
                  EXISTS (SELECT 1 FROM record_resolution completion
                          WHERE completion.source_record_id = entry.primary_source_record_id
                            AND completion.kind = 'completed'
                            AND NOT EXISTS (SELECT 1 FROM record_resolution_event undone
                                            WHERE undone.resolution_id = completion.id
                                              AND undone.event = 'undone'))
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
              AND fixed_posting_date.field = 'posting_date'
              AND fixed_posting_date.state = 'applied'
           LEFT JOIN transaction_correction fixed_description
               ON fixed_description.transaction_id = entry.id
              AND fixed_description.field = 'description'
              AND fixed_description.state = 'applied'
           ORDER BY shown_date, entry.id"""
    ).fetchall()
    for transaction_id, when, cents, status, description, corrected, completed in rows:
        marker = "  (corrected)" if corrected else ""
        marker += "  (completed by hand)" if completed else ""
        print(
            f"{transaction_id}  {when}  {format_cents(cents):>12}  {status:<8}  "
            f"{shown(description) if description else ''}{marker}"
        )
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
            print_completed_values((completed_amount, completed_transaction_date,
                                    completed_posting_date, completed_description), "  ")

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


def print_completed_values(supplied, indent) -> None:
    """What a person supplied, apart from what was read (D-050). None means nothing supplied."""
    labels = ("Amount", "Transaction date", "Posting date", "Description")
    print(f"{indent}Completed by hand, supplying what the parser could not read:")
    given = [(label, value) for label, value in zip(labels, supplied) if value is not None]
    for label, value in given:
        print(f"{indent}  {label}: {format_cents(value) if label == 'Amount' else shown(value)}")
    if not given:
        print(f"{indent}  Nothing supplied: every value was read, and the row was accepted as read")


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
            print(f"Item {issue}: {kind}: {rule}, {file_name} row {index}")
            continue
        print(f"Item {issue}: {kind}: {rule}, {members} transactions{describe_evidence(evidence)}")
        subjects = conn.execute(
            """SELECT transaction_id FROM review_issue_subject
               WHERE review_issue_id = ? ORDER BY transaction_id""",
            (issue,),
        ).fetchall()
        for (transaction_id,) in subjects:
            print(f"  Transaction {transaction_id}")
    print(f"Open review items: {len(rows)}")
    conflicts = sum(row[1] == "decision_conflict" for row in rows)
    if conflicts:
        print(f"Of which decision conflicts, which are not possible duplicates: {conflicts}")
    if rows:
        print("To see an item's evidence, including amounts and descriptions, run review show.")
    return 0


def shown(value) -> str:
    """A value as printed, or missing. Escapes keep a cell from imitating other output."""
    if not value:
        return "missing"
    text = str(value)
    return "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode() for char in text
    )


def shown_amount(cents: int | None) -> str:
    return "missing" if cents is None else format_cents(cents)


def run_review_show(args) -> int:
    conn = open_ledger(args.db, read_only=True)
    item = load_review_evidence(conn, args.item_id)
    if item is None:
        raise CommandError("review item not found. A later import can replace one: run review list")

    print(f"Review item {item.issue_id}")
    print(f"  Account: {shown(item.account_name)} ({item.account_id})")
    print(f"  Kind: {item.kind}")
    print(f"  Rule: {item.rule}")
    print(f"  Status: {item.status}")
    print(f"  Revision: {review_revision(item)}")
    print_machine_reasons(item)
    print_decided_pairs(item)
    print_alike_records(alike_decided_records(item))
    if item.rule == RULE_CANDIDATES and item.status == "open":
        print_direct_pairs(undecided_direct_pairs(conn, item))

    shared = rows_sharing_a_document(item)
    names = {document.content_sha256: document.file_name for document in item.documents}
    if shared:
        print("Records from the same document:")
    for digest, rows in shared.items():
        print(f"  {names[digest]}: rows {', '.join(map(str, rows))}")

    for number, entry in enumerate(item.transactions, start=1):
        print(f"Transaction {number} of {len(item.transactions)}: {entry.transaction_id}")
        print_transaction_evidence(entry, shared)
    for record in item.unresolved:
        print_record_evidence(record, "unresolved, no transaction", shared)

    print("Coverage evidence:")
    for document in item.documents:
        print_document_evidence(document)
    if item.account_stale:
        print(
            "This account has not been reconciled under the current matching rules, so this "
            "evidence may be out of date. Run reconcile."
        )
    return 0


def print_machine_reasons(item) -> None:
    print("Machine-generated reasons:")
    print(f"  {RULE_EXPLANATIONS.get(item.rule, f'Unresolved row: {item.rule}.')}")
    for reason in item.reasons:
        print(f"  {reason}: {REASON_EXPLANATIONS.get(reason, 'no explanation recorded')}")
    if item.date_start:
        print(f"  Dates involved: {item.date_start} to {item.date_end}")
    print(f"  {notice_for(item)}")


def notice_for(item) -> str:
    if item.unresolved:
        return UNRESOLVED_NOTICE
    return CONFLICT_NOTICE if item.kind == "decision_conflict" else DUPLICATE_NOTICE


DECIDED_HEADINGS = {
    "different_event": ("Already decided, as different events:", "is a different event from"),
    "same_event": ("Already decided, as one event:", "is the same event as"),
}


def print_decided_pairs(item) -> None:
    for relation, (heading, verb) in DECIDED_HEADINGS.items():
        pairs = [pair for pair in item.decided if pair.relation == relation]
        if pairs:
            print(heading)
        for pair in pairs:
            print(f"  Decision {pair.decision_id}:")
            print(f"    {describe_side(pair.left)}")
            print(f"    {verb} {describe_side(pair.right)}")


def print_alike_records(alike) -> None:
    """Evidence that a record repeats a decided one. It binds nothing (D-048)."""
    alike = list(islice(alike, DIRECT_PAIRS_SHOWN + 1))
    if not alike:
        return
    print("Alike a decided record, and not bound by any decision:")
    for entry in alike[:DIRECT_PAIRS_SHOWN]:
        print(
            f"  {shown(entry.record.file_name)} row {entry.record.row} matches "
            f"{shown(entry.decided.file_name)} row {entry.decided.row} in every parsed value, "
            f"decided by {', '.join(entry.decision_ids)}"
        )
    if len(alike) > DIRECT_PAIRS_SHOWN:
        print(f"  Only the first {DIRECT_PAIRS_SHOWN} are listed.")
    print("  No decision transfers to a new record. To decide one, confirm a partition here.")


def describe_side(records) -> str:
    return ", ".join(f"{shown(record.file_name)} row {record.row}" for record in records)


def print_direct_pairs(pairs) -> None:
    """Only these can be rejected. Sharing an item is not enough (D-045)."""
    listed = list(islice(pairs, DIRECT_PAIRS_SHOWN + 1))
    print("Direct candidate pairs, undecided:")
    if not listed:
        print("  None.")
    for left, right in map(sorted, listed[:DIRECT_PAIRS_SHOWN]):
        print(f"  {left} {right}")
    if len(listed) > DIRECT_PAIRS_SHOWN:
        print(f"  Only the first {DIRECT_PAIRS_SHOWN} are listed. Other pairs here may also be direct.")


def print_transaction_evidence(entry, shared) -> None:
    print("  Current logical transaction values:")
    print(f"    Transaction date: {shown(entry.transaction_date)}")
    print(f"    Posting date: {shown(entry.posting_date)}")
    print(f"    Amount: {shown_amount(entry.amount_cents)}")
    print(f"    Status: {entry.settlement_status}")
    print(f"    Description: {shown(entry.description)}")
    print(f"    External ID: {shown(entry.external_id)}")

    ranks = {
        record.record_id: primary_rank(
            record.parsed.settlement_status, *_effective_rank_values(record),
            record.content_sha256, record.row, completed_by_hand=record.completion is not None,
        )
        for record in entry.records
    }
    primary = next(
        (record for record in entry.records
         if (record.content_sha256, record.row) == entry.primary_source),
        None,
    )
    primary_id = primary.record_id if primary else None
    print("  Primary-source selection:")
    if primary is None:
        print("    Not recorded. Run reconcile to record it.")
    else:
        print(f"    {primary.file_name} row {primary.row} supplies the values above")
    for record in entry.records:
        print_record_evidence(record, describe_role(record.record_id, primary_id, ranks), shared)
    print_corrections(entry)
    print_classifications(entry)
    print_transfers(entry)


def _effective_rank_values(record):
    """Dates and description as derivation ranked them (D-050)."""
    parsed, completion = record.parsed, record.completion
    if completion is None:
        return parsed.transaction_date, parsed.posting_date, parsed.description
    return (parsed.transaction_date or completion.transaction_date,
            parsed.posting_date or completion.posting_date,
            parsed.description or completion.description)


def print_corrections(entry) -> None:
    """Corrections stay apart from the source values above (D-049)."""
    if not entry.corrections:
        return
    print("  Corrections, kept apart from the source values above:")
    for correction in entry.corrections:
        print(
            f"    Correction {correction.correction_id}: {correction.field} corrected to "
            f"{shown_corrected_value(correction.field, correction.corrected_value)}, binding "
            f"{describe_side(correction.bound_records)}"
        )
    state_by_field = {correction.field: correction.field_state for correction in entry.corrections}
    for field, state in sorted(state_by_field.items()):
        print(f"    {field}: {FIELD_STATE_EXPLANATIONS[state]}")


def print_classifications(entry) -> None:
    """Classifications stay apart from the source values, like corrections (D-053)."""
    if not entry.classifications:
        print(f"  Financial type: {UNCLASSIFIED}")
        return
    print("  Classifications:")
    for classification in entry.classifications:
        print(
            f"    Classification {classification.classification_id}: "
            f"{classification.financial_type}, binding {describe_side(classification.bound_records)}"
        )
    state = entry.classifications[0].state
    print(f"    Financial type: {CLASSIFICATION_STATE_EXPLANATIONS[state]}")


def print_transfers(entry) -> None:
    """Transfer matches binding this transaction's records (D-054)."""
    for transfer in entry.transfers:
        print(f"  Transfer match {transfer.match_id}, this transaction's side: {transfer.side}")
        print(f"    Binding here: {describe_side(transfer.bound_records)}")
        print(f"    Binding on the other side: {describe_side(transfer.counterpart_bound_records)}")
        if transfer.counterpart_transaction_id:
            print(f"    Other side now: transaction {transfer.counterpart_transaction_id}")
        print(f"    Transfer: {MATCH_STATE_EXPLANATIONS[transfer.state]}")
    for statement in entry.one_sided_transfers:
        print(f"  One-sided transfer {statement.one_sided_transfer_id}, counterpart: "
              f"{shown(statement.counterpart_account)}")
        print(f"    Binding: {describe_side(statement.bound_records)}")
        print(f"    Transfer: {ONE_SIDED_STATE_EXPLANATIONS[statement.state]}")


def shown_corrected_value(field, value) -> str:
    return format_cents(value) if field == "amount" else shown(value)


def print_record_evidence(record, role, shared) -> None:
    parsed = record.parsed
    print(f"  Source {record.file_name}, row {record.row}")
    print(f"    Record: {record.record_id}")
    print(f"    Role: {role}")
    print(f"    Link rule: {record.link_rule or 'none'}")
    if record.content_sha256 in shared:
        print("    Shares its document with another record in this item")
    print(f"    Original source cells: {list(record.cells)}")
    print("    Parsed source values:")
    print(f"      Result: {parsed.status}{f' ({parsed.reason_code})' if parsed.reason_code else ''}")
    print(f"      Transaction date: {shown(parsed.transaction_date)}")
    print(f"      Posting date: {shown(parsed.posting_date)}")
    print(f"      Amount: {shown_amount(parsed.amount_cents)}")
    print(f"      Status: {parsed.settlement_status}")
    print(f"      Description: {shown(parsed.description)}")
    print(f"      External ID: {shown(parsed.external_id)}")
    completion = record.completion
    if completion is not None:
        print_completed_values((completion.amount_cents, completion.transaction_date,
                                completion.posting_date, completion.description), "    ")


def print_document_evidence(document) -> None:
    print(f"  {document.file_name}")
    print(f"    Document SHA-256: {document.content_sha256}")
    print(f"    Layout: {document.layout_id}, parser version {document.parser_version}")
    print(f"    Coverage kind: {document.coverage_kind}")
    print(f"    Claimed interval: {shown(document.coverage_start)} to {shown(document.coverage_end)}")
    print(f"    Date basis: {shown(document.date_basis)}")
    print(f"    Coverage evidence: {shown(document.coverage_evidence)}")
    print(f"    Generated on: {shown(document.generated_on)}")
    if document.declared is not None:
        declared = document.declared
        interval = (f" {declared.coverage_start} to {declared.coverage_end}, "
                    f"{declared.date_basis} basis" if declared.coverage_kind == "complete" else "")
        print(f"    Declared after import, which matching uses: {declared.coverage_kind}{interval}")
    if document.effective_end is not None:
        print(f"    Last date matching relies on: {document.effective_end}")
        print(f"    Pending rows: {'included' if document.pending_covered else 'excluded'}")
    print(f"    External ID guarantee: {document.id_guarantee}")


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
    print_decided_pairs(merge)
    print_transaction_evidence(entry, {})
    print("Coverage evidence:")
    for document in merge.documents:
        print_document_evidence(document)
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
    movement = account_movement(conn, account_id)
    # Before any output, so a broken invariant stops the report rather than truncating it.
    groups = income_and_spending(conn, account_id)

    print(f"Account inflows: {format_cents(movement.inflow_cents)}")
    print(f"Account outflows: {format_cents(movement.outflow_cents)}")
    print(f"Net account movement: {format_cents(movement.net_cents)}")
    print(f"Transactions: {movement.transactions}, of which pending: {movement.pending_transactions}")
    print("By financial type, as you classified them:")
    for financial_type, count, cents in movement.financial_types:
        print(f"  {financial_type}: {count} transactions, {format_cents(cents)}")
    print(
        f"  {UNCLASSIFIED}: {movement.unclassified_transactions} transactions, "
        f"{format_cents(movement.unclassified_cents)}"
    )
    transfers = transfer_summary(conn, account_id)
    print("Transfers between your accounts, as you matched them:")
    print(f"  Matched: {transfers.matches} pairs, moving {format_cents(transfers.matched_cents)}")
    print(f"  In a candidate pair, not matched: {transfers.transactions_in_candidates} transactions")
    one_sided = one_sided_summary(conn, account_id)
    print(
        f"  One-sided, the other side not in the ledger: {one_sided.applied} transactions, "
        f"{format_cents(one_sided.out_cents)} out and {format_cents(one_sided.in_cents)} in"
    )
    print(
        f"  Of a transfer kind with no match, candidate or one-sided transfer: "
        f"{transfers.unpaired_transfer_kind} transactions"
    )
    print_income_and_spending(groups)
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
    for line in describe_conflicts(movement):
        print(f"- {line}")
    if movement.transactions_confirmed:
        print(
            f"- {movement.transactions_confirmed} transactions hold records you confirmed as one "
            "event, and each is counted once. Undoing a confirmation can raise totals."
        )
    if movement.transactions_separated:
        print(
            f"- {movement.transactions_separated} transactions hold records you separated from an "
            "automatic match, and each is counted. Undoing a separation can lower totals."
        )
    for line in describe_corrections(movement):
        print(f"- {line}")
    for line in (*describe_resolutions(movement), *describe_declarations(movement),
                 *describe_pending(movement), *describe_classifications(movement),
                 *describe_transfers(transfers), *describe_one_sided(one_sided),
                 *describe_income_and_spending(groups)):
        print(f"- {line}")
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


def out_and_in(group) -> str:
    return (f"{group.transactions} transactions, {format_cents(group.out_cents)} out and "
            f"{format_cents(group.in_cents)} in")


def print_income_and_spending(groups) -> None:
    """Five groups, each transaction in one, adding to net account movement (D-056)."""
    print("Income and spending, as you classified and matched them:")
    print_income_and_spending_groups(groups)


def print_income_and_spending_groups(groups) -> None:
    income, spending = groups.income, groups.spending
    print(f"  Income: {income.transactions} transactions, "
          f"{format_cents(income.in_cents - income.out_cents)}")
    print(f"  Spending: {spending.transactions} transactions, "
          f"{format_cents(spending.out_cents - spending.in_cents)}")
    for financial_type, group in groups.spending_by_type:
        print(f"    {financial_type}: {group.transactions} transactions, "
              f"{format_cents(group.out_cents - group.in_cents)}")
    print(f"  Confirmed transfers: {out_and_in(groups.confirmed_transfers)}")
    for financial_type, group in groups.confirmed_transfers_by_type:
        print(f"    {financial_type}: {out_and_in(group)}")
    print(f"  Of a transfer kind, not confirmed: {out_and_in(groups.unconfirmed_transfer_kinds)}")
    print(f"  Unclassified: {out_and_in(groups.unclassified)}")


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
    # Before any output, so a broken invariant stops the report rather than truncating it.
    report = monthly_report(conn, account_id, first_month, last_month)

    if not report.months:
        print("No transactions, so there are no months to show.")
    for month in report.months:
        print_month(month)
        if month.accounts_covered:
            print("  Covered for the whole month: "
                  + ", ".join(shown(name) for name in month.accounts_covered))
        if month.accounts_not_covered:
            print("  Not covered for the whole month: "
                  + ", ".join(shown(name) for name in month.accounts_not_covered))

    print("Disclosures:")
    print(
        "- Each transaction is in the month of its effective transaction date, else its "
        "effective posting date. Amounts are account movements, with pending transactions "
        "counted as in totals."
    )
    print(
        "- A month is covered for an account only when complete transaction-basis coverage spans "
        "every day of it. A month not covered may be missing transactions."
    )
    if report.transactions_outside_range:
        print(
            f"- {report.transactions_outside_range} transactions, "
            f"{format_cents(report.net_cents_outside_range)}, are in months outside this range."
        )
    if report.unresolved_records:
        print(
            f"- {report.unresolved_records} unresolved records are no transaction, so no month "
            "counts them, and their amounts may be unknown."
        )
    stale = stale_accounts(conn, DEFAULT_RULES, account_id)
    if stale:
        print(
            f"- {len(stale)} accounts have not been reconciled under the current matching "
            "rules, so overlapping files there may be counted twice. Run reconcile."
        )
    return 0


def print_month(month) -> None:
    print(
        f"{month.month}: net account movement {format_cents(month.net_cents)} over "
        f"{month.transactions} transactions, of which pending: {month.pending_transactions}"
    )
    print(f"  Dated by transaction date: {month.dated_by_transaction_date}, "
          f"by posting date: {month.dated_by_posting_date}")
    print_income_and_spending_groups(month.income_and_spending)
    if month.open_review_items:
        print(f"  Open review items: {len(month.open_review_items)}, holding "
              f"{month.transactions_in_open_review_items} transactions here")
    for count, label in (
        (month.transactions_with_unsettled_correction, "an unsettled correction"),
        (month.transactions_with_unsettled_classification, "an unsettled classification"),
        (month.transactions_with_unsettled_match, "a transfer match that no longer applies"),
        (month.transactions_with_unsettled_one_sided_transfer,
         "a one-sided transfer that no longer applies"),
    ):
        if count:
            print(f"  With {label}: {count} transactions")
    if month.matched_sides_with_other_side_in_another_month:
        print(
            f"  Matched transfers whose other side is in another month: "
            f"{month.matched_sides_with_other_side_in_another_month}, so this month's movement "
            "includes them"
        )


def describe_income_and_spending(groups) -> list[str]:
    """How far income and spending may be understated, from what they leave out (D-011, D-056)."""
    unconfirmed, unclassified = groups.unconfirmed_transfer_kinds, groups.unclassified
    if not (unconfirmed.transactions or unclassified.transactions):
        return []
    return [
        "Income and spending count only what you classified, and leave out transfers you "
        "confirmed. Spending may be understated by up to "
        f"{format_cents(unconfirmed.out_cents + unclassified.out_cents)} and income by up to "
        f"{format_cents(unconfirmed.in_cents + unclassified.in_cents)}, the money out and in of "
        "transactions of a transfer kind not confirmed and of unclassified transactions."
    ]


def describe_transfers(transfers) -> list[str]:
    """Matches that no longer apply, and unmatched candidates, on their own lines (D-011, D-054)."""
    lines = [
        f"{count} transfer matches no longer apply, because {reason}. Their transactions count as "
        "unmatched. Run review transfers."
        for count, reason in (
            (transfers.basis_changed, "a side's bound records are now in several transactions"),
            (transfers.conflicts, "a transaction holds records of two matches"),
            (transfers.amounts_differ, "the amounts no longer offset exactly"),
            (transfers.types_differ, "a type no longer fits a transfer between those accounts"),
        )
        if count
    ]
    if transfers.transactions_in_candidates:
        lines.append(
            f"{transfers.transactions_in_candidates} transactions may be transfers between your "
            "accounts and are not matched. Each still counts as the type stated, or unclassified. "
            "Run review transfers."
        )
    return lines


def describe_one_sided(one_sided) -> list[str]:
    """Coverage warnings for one-sided transfers, and those that no longer apply (D-012, D-055)."""
    lines = []
    if one_sided.applied:
        lines.append(
            f"{one_sided.applied} one-sided transfers rest on another account whose side is not in "
            f"the ledger: {one_sided.counterpart_without_documents} where that account has no "
            f"documents, {one_sided.counterpart_partly_covered} where its documents do not cover "
            "every day within "
            f"{TRANSFER_DATE_WINDOW_DAYS} days. Import its statements, or declare their coverage, "
            "to check them."
        )
    if one_sided.card_payments_without_history:
        lines.append(
            f"{one_sided.card_payments_without_history} card payments, "
            f"{format_cents(one_sided.card_payments_without_history_cents)}, go to a card whose "
            "purchases for those dates are not in the ledger, so spending on that card is "
            "understated."
        )
    if one_sided.loan_payments_without_history:
        lines.append(
            f"{one_sided.loan_payments_without_history} loan payments, "
            f"{format_cents(one_sided.loan_payments_without_history_cents)}, go to a loan whose "
            "interest for those dates is not in the ledger, so spending on interest is "
            "understated."
        )
    lines += [
        f"{count} one-sided transfers no longer apply, because {reason}. Their transactions count "
        "as unpaired. Run review transfers."
        for count, reason in (
            (one_sided.basis_changed, "their bound records are now in several transactions"),
            (one_sided.conflicts, "a transaction holds records of another match or one-sided "
                                  "transfer"),
            (one_sided.types_differ, "a type no longer fits a transfer to the counterpart"),
            (one_sided.counterparts_found, "a transaction of the counterpart may be the other "
                                           "side"),
            (one_sided.counterparts_covered, "the counterpart's complete coverage spans their "
                                             "dates"),
        )
        if count
    ]
    return lines


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
    except (CommandError, DecisionRefused, UnsafeLocation, BackupRefused) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except sqlite3.OperationalError as error:
        reason = BUSY_EXPLANATION if "locked" in str(error) else "database error"
        print(f"Error: {reason}", file=sys.stderr)
        return 2
    except Exception:
        print(f"Error: {UNEXPECTED_ERROR}", file=sys.stderr)
        return 2
