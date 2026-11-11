"""Measures import and reconciliation cost on synthetic files (A39).

Not part of the test suite. Run from the repository root:

    PYTHONPATH=src:tests/benchmarks .venv/bin/python tests/benchmarks/measure_reconciliation.py
    (add --worst for the stress shapes, --constrained for dense groups with decisions,
    --confirmed to compare confirmation with rejection, --separated to compare separating a
    merge with rejection and partition, --superseded to compare a separation superseding a
    confirmation with a partition, --corrected for value corrections, --resolved for completing
    and dismissing unresolved rows, --declared for coverage declared after import, --pending for
    pending rows posted at another amount, --classified for financial types, --transfers for
    transfer matches across two accounts, --one-sided for one-sided transfers, --income for income
    and spending in totals, --scale for the 100,000-transaction shape of M4.4, --scale
    --category-rules N for it with N category rules (D-064), --scale --household for it with
    household members, defaults and 5,000 allocations (D-065), or rows per month
    such as 200 1000 4000)

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
from itertools import islice
from pathlib import Path

from synthetic_ledger import dense_rows, full_reexports, ordinary_rows, variant_rows, with_overlap

from personal_finance.db.migrate import connect, create_database
from personal_finance.cli import main as cli_main
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.money import format_cents
from personal_finance.reconcile import apply as apply_module
from personal_finance.reconcile import classifications as classifications_module
from personal_finance.reconcile.apply import decision_states, load_evidence
from personal_finance.reconcile.balance_observations import record_observation
from personal_finance.reconcile.classification_effects import (
    classification_chain_states,
    load_active_classifications,
    write_classification_effects,
)
from personal_finance.reconcile.allocations import Stated, allocate_transaction, undo_allocation
from personal_finance.reconcile.category_rules import add_rule, checked_definition, undo_rule
from personal_finance.reconcile.household import (
    set_account_default,
    set_share,
    undo_account_default,
    undo_share,
)
from personal_finance.reconcile.household_effects import attributed_transactions, load_household
from personal_finance.reconcile.classifications import classify_transaction, undo_classification
from personal_finance.reconcile.correction_effects import (
    correction_chain_states,
    load_active_corrections,
    write_correction_effects,
)
from personal_finance.reconcile.corrections import correct_value, undo_correction
from personal_finance.reconcile.cross_document import Constraint, Document, Record, derive
from personal_finance.reconcile.coverage_declarations import declare_coverage, undo_declaration
from personal_finance.reconcile.record_resolutions import (
    complete_record,
    dismiss_record,
    undo_resolution,
)
from personal_finance.reconcile.decisions import (
    confirm_groups,
    reject_pairs,
    separate_records,
    undo_decision,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports.report_text import DIRECT_PAIRS_SHOWN
from personal_finance.reports.category_rule_evidence import (
    load_rule,
    reach_of_rules,
    rule_preview_outlook,
    rule_undo_outlook,
)
from personal_finance.reports.classification_evidence import (
    classification_undo_outlook,
    load_classification,
)
from personal_finance.reports.correction_evidence import correction_undo_outlook, load_correction
from personal_finance.reports.decision_evidence import load_decision, undo_outlook
from personal_finance.reports.coverage_evidence import (
    declaration_undo_outlook,
    document_coverage_revision,
    load_declaration,
    load_document_coverage,
)
from personal_finance.reports.resolution_evidence import load_resolution, resolution_undo_outlook
from personal_finance.reconcile.transfer_effects import transfer_candidates, write_transfer_effects
from personal_finance.reconcile.transfers import (
    match_transfer,
    state_one_sided,
    undo_one_sided,
    undo_transfer,
)
from personal_finance.reports.allocation_evidence import allocation_undo_outlook, load_allocation
from personal_finance.reports.balances import check_balances
from personal_finance.reports.household_evidence import account_reach, share_reach
from personal_finance.reports.monthly import monthly_report
from personal_finance.reports.totals import (
    account_movement,
    income_and_spending,
    one_sided_summary,
    transfer_summary,
)
from personal_finance.reports.transfer_evidence import (
    load_match,
    load_one_sided,
    match_revision,
    one_sided_revision,
)
from personal_finance.reports.review_evidence import (
    DecidedPair,
    DecidedRecord,
    ParsedValues,
    RecordEvidence,
    ReviewEvidence,
    TransactionEvidence,
    alike_decided_records,
    load_merge_evidence,
    load_review_evidence,
    review_revision,
    transaction_revision,
)

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


def worst_cases() -> None:
    """Shapes chosen to stress the two costs that do not follow row count alone."""
    for copies, rows in ((6, 2000), (12, 2000), (24, 2000), (12, 8000)):
        run(f"reexport{copies}", full_reexports(copies, rows))
    for spellings in (500, 1000):
        run(f"spell{spellings}", with_overlap(variant_rows(24, 1000, spellings)))


def dense_group(units: int, documents: int = 2):
    """One candidate group: every record alike, spread evenly over unmerged documents."""
    files = [
        Document(id=str(number), content_sha256=str(number).ljust(64, "0"))
        for number in range(documents)
    ]
    records = [
        Record(str(index), str(index % documents), index + 1, -650,
               posting_date="2026-01-10", description="SYNTHETIC CAFE", settlement_status="posted")
        for index in range(units)
    ]
    return files, records


def measure_derive(units: int, constraints: int) -> None:
    """Derivation alone. Constraints bind one record of the first document to one of the next."""
    files, records = dense_group(units)
    bound = tuple(
        Constraint(f"d{number}", (str(2 * number),), (str(2 * number + 1),))
        for number in range(constraints)
    )
    started = time.perf_counter()
    result = derive(files, records, [], DEFAULT_RULES, bound)
    seconds = time.perf_counter() - started
    print(
        f"derive units={units:6} constraints={constraints:5} seconds={seconds:7.3f} "
        f"compared_pairs={result.recomputed_pairs:10} items={len(result.items)}",
        flush=True,
    )


def measure_reject(rows_per_file: int) -> None:
    """A whole rejection through a real ledger, including the checks under the write lock."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "ledger.db"
        create_database(path)
        conn = connect(path)
        conn.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'credit_card')"
        )
        header = "Date,Description,Debit,Credit\n"
        for name, padding in (("a.csv", ""), ("b.csv", " ")):
            source = root / name
            source.write_text(header + padding + "01/10/2026,SYNTHETIC CAFE,6.50,\n" * rows_per_file)
            (result,) = import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
            assert result.outcome == "imported", result

        (issue,) = conn.execute("SELECT id FROM review_issue").fetchone()
        started = time.perf_counter()
        item = load_review_evidence(conn, issue)
        token = review_revision(item)
        inspect_seconds = time.perf_counter() - started
        left = next(entry for entry in item.transactions
                    if entry.records[0].file_name == "a.csv").transaction_id
        right = next(entry for entry in item.transactions
                     if entry.records[0].file_name == "b.csv").transaction_id

        started = time.perf_counter()
        decision_id = reject_pairs(conn, "acct", issue, token, [(left, right)]).decision_id
        reject_seconds = time.perf_counter() - started

        started = time.perf_counter()
        revision = undo_outlook(conn, load_decision(conn, decision_id), DEFAULT_RULES).revision
        outlook_seconds = time.perf_counter() - started

        started = time.perf_counter()
        undo_decision(conn, "acct", decision_id, revision)
        undo_seconds = time.perf_counter() - started
        print(
            f"reject transactions={2 * rows_per_file:6} evidence={inspect_seconds:7.3f}s "
            f"reject={reject_seconds:7.3f}s decision_show={outlook_seconds:7.3f}s "
            f"undo={undo_seconds:7.3f}s",
            flush=True,
        )
        conn.close()


def constrained() -> None:
    for units in (100, 500, 1000, 2000, 4000):
        for constraints in (0, 1, units // 10):
            measure_derive(units, constraints)
    for rows_per_file in (50, 250, 500, 1000):
        measure_reject(rows_per_file)


def measure_derive_confirmed(units: int, confirmations: int, partition: bool) -> None:
    """Derivation alone, with confirmations joining records of the first two of three documents.

    The joined transaction can still link with the third document, so it stays in the group.
    A partition also keeps it apart from a record of the third, which touches the group the
    way a rejection does.
    """
    files, records = dense_group(units, documents=3)
    bound = []
    for number in range(confirmations):
        left, right = str(3 * number), str(3 * number + 1)
        bound.append(Constraint(f"c{number:05}", (left,), (right,), "same_event", True))
        if partition:
            bound.append(Constraint(f"c{number:05}", (left, right), (str(3 * number + 2),),
                                    "different_event", True))
    started = time.perf_counter()
    result = derive(files, records, [], DEFAULT_RULES, tuple(bound))
    seconds = time.perf_counter() - started
    print(
        f"derive units={units:6} confirmations={confirmations:5} partition={partition!s:5} "
        f"seconds={seconds:7.3f} compared_pairs={result.recomputed_pairs:10} "
        f"groups={len(result.groups)}",
        flush=True,
    )


def measure_decision(rows_per_file: int, kind: str) -> None:
    """One decision through a real ledger, then a later import, decision show and undo.

    Three files, so that a confirmed transaction stays in the group through the third.
    """
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "ledger.db"
        create_database(path)
        conn = connect(path)
        conn.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'credit_card')"
        )
        header = "Date,Description,Debit,Credit\n"
        for name, padding in (("a.csv", ""), ("b.csv", " "), ("c.csv", "  ")):
            source = root / name
            source.write_text(header + padding + "01/10/2026,SYNTHETIC CAFE,6.50,\n" * rows_per_file)
            (result,) = import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
            assert result.outcome == "imported", result

        (issue,) = conn.execute("SELECT id FROM review_issue").fetchone()
        started = time.perf_counter()
        item = load_review_evidence(conn, issue)
        token = review_revision(item)
        inspect_seconds = time.perf_counter() - started
        by_file = {"a.csv": [], "b.csv": [], "c.csv": []}
        for entry in item.transactions:
            by_file[entry.records[0].file_name].append(entry.transaction_id)
        left, right, third = by_file["a.csv"][0], by_file["b.csv"][0], by_file["c.csv"][0]

        started = time.perf_counter()
        if kind == "reject":
            decision_id = reject_pairs(conn, "acct", issue, token, [(left, right)]).decision_id
        elif kind == "confirm":
            decision_id = confirm_groups(conn, "acct", issue, token, [[left, right]]).decision_id
        else:
            decision_id = confirm_groups(
                conn, "acct", issue, token, [[left, right], [third]]
            ).decision_id
        decide_seconds = time.perf_counter() - started

        later = root / "later.csv"
        later.write_text(header + "03/20/2026,SYNTHETIC GROCER,9.00,\n")
        started = time.perf_counter()
        import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started

        started = time.perf_counter()
        revision = undo_outlook(conn, load_decision(conn, decision_id), DEFAULT_RULES).revision
        outlook_seconds = time.perf_counter() - started

        started = time.perf_counter()
        undo_decision(conn, "acct", decision_id, revision)
        undo_seconds = time.perf_counter() - started
        print(
            f"{kind:9} transactions={3 * rows_per_file:6} evidence={inspect_seconds:7.3f}s "
            f"decide={decide_seconds:7.3f}s later_import={later_seconds:7.3f}s "
            f"decision_show={outlook_seconds:7.3f}s undo={undo_seconds:7.3f}s",
            flush=True,
        )
        conn.close()


def confirmed() -> None:
    for units in (100, 500, 1000, 2000, 4000):
        files, records = dense_group(units, documents=3)
        started = time.perf_counter()
        result = derive(files, records, [], DEFAULT_RULES, (Constraint("d", ("0",), ("1",)),))
        print(
            f"derive units={units:6} rejection=    1 seconds={time.perf_counter() - started:7.3f} "
            f"compared_pairs={result.recomputed_pairs:10}",
            flush=True,
        )
        for confirmations, partition in ((1, False), (1, True), (units // 10, False),
                                         (units // 10, True)):
            measure_derive_confirmed(units, confirmations, partition)
    for rows_per_file in (33, 167, 333, 667):
        for kind in ("reject", "confirm", "partition"):
            measure_decision(rows_per_file, kind)


def merged_group(merges: int):
    """Two complete documents pairing every row exactly, and a third of unknown coverage.

    Each merge links with every row of the third document, so the group holds 2 * merges
    units, and a record separated from its merge still links with all of the third. With
    only the two merging documents, a separated record would link with nothing.
    """
    complete = dict(coverage_kind="complete", coverage_start="2026-01-01",
                    coverage_end="2026-01-31", date_basis="posting", evidence="user_declared")
    files = [
        Document(id="a", content_sha256="a".ljust(64, "0"), **complete),
        Document(id="b", content_sha256="b".ljust(64, "0"), **complete),
        Document(id="c", content_sha256="c".ljust(64, "0")),
    ]
    records = [
        Record(f"{name}{index:05}", name, index + 1, -650, posting_date="2026-01-10",
               description="SYNTHETIC CAFE", settlement_status="posted")
        for name in "abc"
        for index in range(merges)
    ]
    return files, records


def separation(number: int) -> Constraint:
    """The one pair of a separation of merge number into its two records (D-047)."""
    return Constraint(f"s{number:05}", (f"a{number:05}",), (f"b{number:05}",),
                      "different_event", True)


def measure_derive_separated(merges: int) -> None:
    files, records = merged_group(merges)
    cases = {
        "none": (),
        "rejection": (Constraint("d", ("a00000", "b00000"), ("c00000",)),),
        "partition": (Constraint("p", ("a00000", "b00000"), ("c00000",), "different_event", True),),
        "separation": (separation(0),),
        "separations_10pct": tuple(separation(number) for number in range(max(1, merges // 10))),
    }
    for name, bound in cases.items():
        started = time.perf_counter()
        result = derive(files, records, [], DEFAULT_RULES, bound)
        seconds = time.perf_counter() - started
        print(
            f"derive merges={merges:5} units={2 * merges:5} {name:17} seconds={seconds:7.3f} "
            f"compared_pairs={result.recomputed_pairs:10} groups={len(result.groups)} "
            f"items={len(result.items)}",
            flush=True,
        )


def measure_separate(rows_per_file: int, kind: str) -> None:
    """One decision through a real ledger on the merged shape, then a later import, decision
    show and undo. A rejection of a merge against a row of the third file is the baseline,
    since a partition into single transactions on a candidate item is refused (D-046)."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "ledger.db"
        create_database(path)
        conn = connect(path)
        conn.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'credit_card')"
        )
        header = "Date,Description,Debit,Credit\n"
        whole = declare_complete("2026-01-01", "2026-01-31", "posting")
        for name, padding, declared in (("a.csv", "", whole), ("b.csv", " ", whole),
                                        ("c.csv", "  ", None)):
            source = root / name
            source.write_text(header + padding + "01/10/2026,SYNTHETIC CAFE,6.50,\n" * rows_per_file)
            (result,) = import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1,
                                     declared_coverage=declared)
            assert result.outcome == "imported", result

        (merged,) = conn.execute(
            """SELECT transaction_id FROM transaction_source GROUP BY transaction_id
               HAVING COUNT(*) = 2 ORDER BY MIN(source_record_id) LIMIT 1"""
        ).fetchone()
        transactions = conn.execute("SELECT COUNT(*) FROM ledger_transaction").fetchone()[0]
        started = time.perf_counter()
        if kind == "separate":
            merge = load_merge_evidence(conn, merged)
            token = transaction_revision(merge)
        else:
            (issue,) = conn.execute("SELECT id FROM review_issue").fetchone()
            item = load_review_evidence(conn, issue)
            token = review_revision(item)
        inspect_seconds = time.perf_counter() - started

        started = time.perf_counter()
        if kind == "separate":
            groups = [[record.record_id] for record in merge.transaction.records]
            decision_id = separate_records(conn, "acct", merged, token, groups).decision_id
        else:
            third = next(entry.transaction_id for entry in item.transactions
                         if entry.records[0].file_name == "c.csv")
            decision_id = reject_pairs(conn, "acct", issue, token, [(merged, third)]).decision_id
        decide_seconds = time.perf_counter() - started

        later = root / "later.csv"
        later.write_text(header + "03/20/2026,SYNTHETIC GROCER,9.00,\n")
        started = time.perf_counter()
        import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started

        started = time.perf_counter()
        revision = undo_outlook(conn, load_decision(conn, decision_id), DEFAULT_RULES).revision
        outlook_seconds = time.perf_counter() - started

        started = time.perf_counter()
        undo_decision(conn, "acct", decision_id, revision)
        undo_seconds = time.perf_counter() - started
        print(
            f"{kind:9} transactions={transactions:6} evidence={inspect_seconds:7.3f}s "
            f"decide={decide_seconds:7.3f}s later_import={later_seconds:7.3f}s "
            f"decision_show={outlook_seconds:7.3f}s undo={undo_seconds:7.3f}s",
            flush=True,
        )
        conn.close()


def separated() -> None:
    for merges in (50, 250, 500, 1000, 2000):
        measure_derive_separated(merges)
    for rows_per_file in (50, 250, 500, 1000):
        for kind in ("reject", "separate"):
            measure_separate(rows_per_file, kind)


def measure_derive_superseded(units: int, decisions: int) -> None:
    """Derivation alone, on three unmerged documents, so a separated record still links with the
    third (D-048). A partition keeps a confirmed pair apart from a record of the third. A
    separation superseding a plain confirmation leaves only its pair of different events."""
    files, records = dense_group(units, documents=3)
    cases = {
        "partition": [
            constraint
            for number in range(decisions)
            for constraint in (
                Constraint(f"p{number:05}", (str(3 * number),), (str(3 * number + 1),),
                           "same_event", True),
                Constraint(f"p{number:05}", (str(3 * number), str(3 * number + 1)),
                           (str(3 * number + 2),), "different_event", True),
            )
        ],
        "superseding": [
            Constraint(f"s{number:05}", (str(3 * number),), (str(3 * number + 1),),
                       "different_event", True)
            for number in range(decisions)
        ],
    }
    for name, bound in cases.items():
        started = time.perf_counter()
        result = derive(files, records, [], DEFAULT_RULES, tuple(bound))
        seconds = time.perf_counter() - started
        print(
            f"derive units={units:6} decisions={decisions:5} {name:11} seconds={seconds:7.3f} "
            f"compared_pairs={result.recomputed_pairs:10} groups={len(result.groups)}",
            flush=True,
        )


def measure_superseding(rows_per_file: int, kind: str) -> None:
    """One decision through a real ledger on three unmerged files, then a later import, decision
    show and undo. The baseline is a partition keeping a confirmed pair apart from the third
    file. The superseding separation splits a pair confirmed beforehand, which is not timed."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        path = root / "ledger.db"
        create_database(path)
        conn = connect(path)
        conn.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'credit_card')"
        )
        header = "Date,Description,Debit,Credit\n"
        for name, padding in (("a.csv", ""), ("b.csv", " "), ("c.csv", "  ")):
            source = root / name
            source.write_text(header + padding + "01/10/2026,SYNTHETIC CAFE,6.50,\n" * rows_per_file)
            (result,) = import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
            assert result.outcome == "imported", result

        (issue,) = conn.execute("SELECT id FROM review_issue").fetchone()
        item = load_review_evidence(conn, issue)
        by_file = {"a.csv": [], "b.csv": [], "c.csv": []}
        for entry in item.transactions:
            by_file[entry.records[0].file_name].append(entry.transaction_id)
        left, right, third = by_file["a.csv"][0], by_file["b.csv"][0], by_file["c.csv"][0]
        transactions = len(item.transactions)

        if kind == "superseding":
            old = confirm_groups(conn, "acct", issue, review_revision(item),
                                 [[left, right]]).decision_id
            old_token = undo_outlook(conn, load_decision(conn, old), DEFAULT_RULES).revision
            (joined,) = conn.execute(
                "SELECT transaction_id FROM transaction_source GROUP BY transaction_id "
                "HAVING COUNT(*) = 2"
            ).fetchone()
        started = time.perf_counter()
        if kind == "superseding":
            merge = load_merge_evidence(conn, joined)
            token = transaction_revision(merge)
        else:
            token = review_revision(load_review_evidence(conn, issue))
        inspect_seconds = time.perf_counter() - started

        started = time.perf_counter()
        if kind == "superseding":
            groups = [[record.record_id] for record in merge.transaction.records]
            decision_id = separate_records(conn, "acct", joined, token, groups,
                                           supersedes=old, supersedes_revision=old_token).decision_id
        else:
            decision_id = confirm_groups(
                conn, "acct", issue, token, [[left, right], [third]]
            ).decision_id
        decide_seconds = time.perf_counter() - started

        later = root / "later.csv"
        later.write_text(header + "03/20/2026,SYNTHETIC GROCER,9.00,\n")
        started = time.perf_counter()
        import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started

        started = time.perf_counter()
        revision = undo_outlook(conn, load_decision(conn, decision_id), DEFAULT_RULES).revision
        outlook_seconds = time.perf_counter() - started

        started = time.perf_counter()
        undo_decision(conn, "acct", decision_id, revision)
        undo_seconds = time.perf_counter() - started
        print(
            f"{kind:11} transactions={transactions:6} evidence={inspect_seconds:7.3f}s "
            f"decide={decide_seconds:7.3f}s later_import={later_seconds:7.3f}s "
            f"decision_show={outlook_seconds:7.3f}s undo={undo_seconds:7.3f}s",
            flush=True,
        )
        conn.close()


def measure_chain(length: int) -> None:
    """decision_states on one chain, each decision superseding the one before. It reads every
    decision of the account once, so a chain costs what as many unrelated decisions cost."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "ledger.db"
        create_database(path)
        conn = connect(path)
        conn.execute(
            "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'credit_card')"
        )
        conn.execute("BEGIN")
        for number in range(length):
            conn.execute(
                """INSERT INTO decision (id, account_id, target_id, target_revision, kind,
                                         supersedes_decision_id)
                   VALUES (?, 'acct', 'item', 'r3-0', 'confirm', ?)""",
                (f"d{number:05}", f"d{number - 1:05}" if number else None),
            )
        conn.execute("COMMIT")
        started = time.perf_counter()
        states = decision_states(conn, "acct")
        seconds = time.perf_counter() - started
        active = sum(state == "active" for state in states.values())
        print(f"chain decisions={length:5} seconds={seconds:7.4f} active={active}", flush=True)
        conn.close()


def measure_alike(transactions: int) -> None:
    """The alike listing on one item where half the records are decided and every other record
    repeats one of them in every parsed value, the most it can list."""
    parsed = ParsedValues("parsed", None, None, "2026-01-10", -650, "SYNTHETIC CAFE", None,
                          "posted")
    entries, decided = [], []
    for number in range(transactions):
        digest = f"{number:064d}"
        record = RecordEvidence(f"r{number}", digest, f"{number}.csv", 1, (), parsed, "new_record")
        entries.append(TransactionEvidence(f"t{number}", None, "2026-01-10", -650,
                                           "SYNTHETIC CAFE", None, "posted", (digest, 1),
                                           (record,)))
    for number in range(0, transactions // 2, 2):
        sides = [(DecidedRecord(f"{index:064d}", f"{index}.csv", 1),) for index in (number, number + 1)]
        decided.append(DecidedPair(f"d{number}", "different_event", *sides))
    item = ReviewEvidence("i", "possible_duplicate", "cross_document_candidates", "open", (),
                          None, None, tuple(entries), (), (), False, "acct", "a", tuple(decided))
    started = time.perf_counter()
    found = list(islice(alike_decided_records(item), DIRECT_PAIRS_SHOWN + 1))
    seconds = time.perf_counter() - started
    print(f"alike transactions={transactions:5} seconds={seconds:7.4f} listed={len(found)}",
          flush=True)


def superseded() -> None:
    for units in (100, 500, 1000, 2000, 4000):
        for decisions in (1, max(1, units // 30)):
            measure_derive_superseded(units, decisions)
    for rows_per_file in (33, 167, 333, 667):
        for kind in ("partition", "superseding"):
            measure_superseding(rows_per_file, kind)
    for length in (50, 2000):
        measure_chain(length)
    for transactions in (200, 2000, 20000):
        measure_alike(transactions)


def new_ledger(root: Path):
    path = root / "ledger.db"
    create_database(path)
    conn = connect(path)
    conn.execute(
        "INSERT INTO account (id, display_name, account_type) VALUES ('acct', 'a', 'credit_card')"
    )
    return conn


def measure_correcting_dense(rows_per_file: int) -> None:
    """A correction through a real ledger where derivation is quadratic: three unmerged files of
    one dense group, with a partition touching it. A correction moves no record, so it must not
    pay for derivation, which the later import does (D-049)."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        conn = new_ledger(root)
        header = "Date,Description,Debit,Credit\n"
        for name, padding in (("a.csv", ""), ("b.csv", " "), ("c.csv", "  ")):
            source = root / name
            source.write_text(header + padding + "01/10/2026,SYNTHETIC CAFE,6.50,\n" * rows_per_file)
            (result,) = import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
            assert result.outcome == "imported", result
        (issue,) = conn.execute("SELECT id FROM review_issue").fetchone()
        item = load_review_evidence(conn, issue)
        by_file = {"a.csv": [], "b.csv": [], "c.csv": []}
        for entry in item.transactions:
            by_file[entry.records[0].file_name].append(entry.transaction_id)
        left, right, third = by_file["a.csv"][0], by_file["b.csv"][0], by_file["c.csv"][0]
        confirm_groups(conn, "acct", issue, review_revision(item), [[left, right], [third]])
        (joined,) = conn.execute(
            "SELECT transaction_id FROM transaction_source GROUP BY transaction_id "
            "HAVING COUNT(*) = 2"
        ).fetchone()
        transactions = account_movement(conn, "acct").transactions

        started = time.perf_counter()
        token = transaction_revision(load_merge_evidence(conn, joined))
        show_seconds = time.perf_counter() - started
        started = time.perf_counter()
        correction_id = correct_value(conn, "acct", joined, token, "amount", "-6.00").correction_id
        correct_seconds = time.perf_counter() - started

        later = root / "later.csv"
        later.write_text(header + "03/20/2026,SYNTHETIC GROCER,9.00,\n")
        started = time.perf_counter()
        import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started

        started = time.perf_counter()
        revision = correction_undo_outlook(conn, load_correction(conn, correction_id)).revision
        outlook_seconds = time.perf_counter() - started
        started = time.perf_counter()
        undo_correction(conn, "acct", correction_id, revision)
        undo_seconds = time.perf_counter() - started
        print(
            f"dense transactions={transactions:6} transaction_show={show_seconds:7.3f}s "
            f"correct={correct_seconds:7.3f}s later_import={later_seconds:7.3f}s "
            f"correction_show={outlook_seconds:7.3f}s undo={undo_seconds:7.3f}s",
            flush=True,
        )
        conn.close()


def measure_many_corrections(count: int) -> None:
    """count transactions, each with an active amount correction, written directly. Rewriting the
    derived rows is linear in corrections, and every correction and import pays it once."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        conn = new_ledger(root)
        header = "Date,Description,Debit,Credit\n"
        source = root / "a.csv"
        source.write_text(header + "".join(
            f"01/{1 + number % 28:02}/2026,SYNTHETIC SHOP {number},{1 + number}.00,\n"
            for number in range(count)
        ))
        import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
        links = conn.execute("SELECT transaction_id, source_record_id FROM transaction_source "
                             "ORDER BY source_record_id").fetchall()
        conn.execute("BEGIN")
        for number, (transaction_id, record_id) in enumerate(links[1:]):
            correction_id = f"c{number:06}"
            conn.execute(
                """INSERT INTO value_correction (id, account_id, field, corrected_amount_cents,
                                                 target_transaction_id, target_revision)
                   VALUES (?, 'acct', 'amount', -1, ?, 't7-0')""",
                (correction_id, transaction_id),
            )
            conn.execute("INSERT INTO value_correction_record VALUES (?, ?)", (correction_id, record_id))
            conn.execute("INSERT INTO value_correction_event (correction_id, event) VALUES (?, 'made')",
                         (correction_id,))
        write_correction_effects(conn, "acct")
        conn.execute("COMMIT")

        conn.execute("BEGIN")
        started = time.perf_counter()
        write_correction_effects(conn, "acct")
        effects_seconds = time.perf_counter() - started
        conn.execute("COMMIT")
        started = time.perf_counter()
        movement = account_movement(conn, "acct")
        totals_seconds = time.perf_counter() - started
        last = links[0][0]
        started = time.perf_counter()
        token = transaction_revision(load_merge_evidence(conn, last))
        correct_value(conn, "acct", last, token, "amount", "-2.00")
        correct_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text(header + "03/20/2026,SYNTHETIC GROCER,9.00,\n")
        started = time.perf_counter()
        import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started
        print(
            f"many corrections={count:6} rewrite={effects_seconds:7.3f}s "
            f"totals={totals_seconds:7.3f}s show_and_correct={correct_seconds:7.3f}s "
            f"later_import={later_seconds:7.3f}s corrected={movement.transactions_corrected}",
            flush=True,
        )
        conn.close()


def measure_correction_chain(length: int) -> None:
    """One chain of corrections, each superseding the one before, written directly."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        conn = new_ledger(root)
        source = root / "a.csv"
        source.write_text("Date,Description,Debit,Credit\n01/10/2026,SYNTHETIC CAFE,6.50,\n")
        import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
        transaction_id, record_id = conn.execute(
            "SELECT transaction_id, source_record_id FROM transaction_source").fetchone()
        conn.execute("BEGIN")
        for number in range(length):
            correction_id = f"c{number:06}"
            conn.execute(
                """INSERT INTO value_correction (id, account_id, field, corrected_amount_cents,
                                                 target_transaction_id, target_revision,
                                                 supersedes_correction_id)
                   VALUES (?, 'acct', 'amount', ?, ?, 't7-0', ?)""",
                (correction_id, -1 - number, transaction_id,
                 f"c{number - 1:06}" if number else None),
            )
            conn.execute("INSERT INTO value_correction_record VALUES (?, ?)", (correction_id, record_id))
            conn.execute("INSERT INTO value_correction_event (correction_id, event) VALUES (?, 'made')",
                         (correction_id,))
        write_correction_effects(conn, "acct")
        conn.execute("COMMIT")
        started = time.perf_counter()
        states, _ = correction_chain_states(conn, "acct")
        states_seconds = time.perf_counter() - started
        started = time.perf_counter()
        active = load_active_corrections(conn, "acct")
        load_seconds = time.perf_counter() - started
        started = time.perf_counter()
        correction_undo_outlook(conn, load_correction(conn, f"c{length - 1:06}"))
        outlook_seconds = time.perf_counter() - started
        print(
            f"chain corrections={length:5} states={states_seconds:7.4f}s "
            f"load_active={load_seconds:7.4f}s correction_show={outlook_seconds:7.4f}s "
            f"active={len(active)}",
            flush=True,
        )
        conn.close()


def corrected() -> None:
    for rows_per_file in (33, 167, 333, 667):
        measure_correcting_dense(rows_per_file)
    for count in (100, 500, 1000, 2000, 4000):
        measure_many_corrections(count)
    for length in (50, 2000):
        measure_correction_chain(length)


def measure_classifying_dense(rows_per_file: int) -> None:
    """A classification through a real ledger where derivation is quadratic, as for corrections. A
    classification moves no record, so it must not pay for derivation, which the later import
    does. The partition's undo token is measured before and after, since it then covers the
    classification under both derivations (D-053)."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        conn = new_ledger(root)
        header = "Date,Description,Debit,Credit\n"
        for name, padding in (("a.csv", ""), ("b.csv", " "), ("c.csv", "  ")):
            source = root / name
            source.write_text(header + padding + "01/10/2026,SYNTHETIC CAFE,6.50,\n" * rows_per_file)
            (result,) = import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
            assert result.outcome == "imported", result
        (issue,) = conn.execute("SELECT id FROM review_issue").fetchone()
        item = load_review_evidence(conn, issue)
        by_file = {"a.csv": [], "b.csv": [], "c.csv": []}
        for entry in item.transactions:
            by_file[entry.records[0].file_name].append(entry.transaction_id)
        left, right, third = by_file["a.csv"][0], by_file["b.csv"][0], by_file["c.csv"][0]
        decision_id = confirm_groups(conn, "acct", issue, review_revision(item),
                                     [[left, right], [third]]).decision_id
        (joined,) = conn.execute(
            "SELECT transaction_id FROM transaction_source GROUP BY transaction_id "
            "HAVING COUNT(*) = 2"
        ).fetchone()
        transactions = account_movement(conn, "acct").transactions

        started = time.perf_counter()
        undo_outlook(conn, load_decision(conn, decision_id), DEFAULT_RULES)
        decision_before_seconds = time.perf_counter() - started
        started = time.perf_counter()
        token = transaction_revision(load_merge_evidence(conn, joined))
        show_seconds = time.perf_counter() - started
        started = time.perf_counter()
        classification_id = classify_transaction(conn, "acct", joined, token,
                                                 "purchase").classification_id
        classify_seconds = time.perf_counter() - started
        started = time.perf_counter()
        outlook = undo_outlook(conn, load_decision(conn, decision_id), DEFAULT_RULES)
        decision_after_seconds = time.perf_counter() - started
        assert outlook.changes_classifications

        later = root / "later.csv"
        later.write_text(header + "03/20/2026,SYNTHETIC GROCER,9.00,\n")
        started = time.perf_counter()
        import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started

        started = time.perf_counter()
        revision = classification_undo_outlook(
            conn, load_classification(conn, classification_id)).revision
        outlook_seconds = time.perf_counter() - started
        started = time.perf_counter()
        undo_classification(conn, "acct", classification_id, revision)
        undo_seconds = time.perf_counter() - started
        print(
            f"dense transactions={transactions:6} transaction_show={show_seconds:7.3f}s "
            f"classify={classify_seconds:7.3f}s later_import={later_seconds:7.3f}s "
            f"classification_show={outlook_seconds:7.3f}s undo={undo_seconds:7.3f}s "
            f"decision_show before={decision_before_seconds:7.3f}s "
            f"after={decision_after_seconds:7.3f}s",
            flush=True,
        )
        conn.close()


def measure_many_classifications(count: int) -> None:
    """count transactions, each with an active classification, written directly. Rewriting the
    derived rows is linear in classifications and transactions, and every import, correction and
    classification pays it once."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        conn = new_ledger(root)
        header = "Date,Description,Debit,Credit\n"
        source = root / "a.csv"
        source.write_text(header + "".join(
            f"01/{1 + number % 28:02}/2026,SYNTHETIC SHOP {number},{1 + number}.00,\n"
            for number in range(count)
        ))
        import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
        links = conn.execute("SELECT transaction_id, source_record_id FROM transaction_source "
                             "ORDER BY source_record_id").fetchall()
        conn.execute("BEGIN")
        for number, (transaction_id, record_id) in enumerate(links[1:]):
            classification_id = f"f{number:06}"
            conn.execute(
                """INSERT INTO type_classification (id, account_id, financial_type,
                                                    target_transaction_id, target_revision)
                   VALUES (?, 'acct', 'purchase', ?, 't7-0')""",
                (classification_id, transaction_id),
            )
            conn.execute("INSERT INTO type_classification_record VALUES (?, ?)",
                         (classification_id, record_id))
            conn.execute("INSERT INTO type_classification_event (classification_id, event) "
                         "VALUES (?, 'made')", (classification_id,))
        write_classification_effects(conn, "acct")
        conn.execute("COMMIT")

        conn.execute("BEGIN")
        started = time.perf_counter()
        write_classification_effects(conn, "acct")
        effects_seconds = time.perf_counter() - started
        conn.execute("COMMIT")
        started = time.perf_counter()
        movement = account_movement(conn, "acct")
        totals_seconds = time.perf_counter() - started
        last = links[0][0]
        started = time.perf_counter()
        token = transaction_revision(load_merge_evidence(conn, last))
        classify_transaction(conn, "acct", last, token, "fee")
        classify_seconds = time.perf_counter() - started
        started = time.perf_counter()
        token = transaction_revision(load_merge_evidence(conn, last))
        correct_value(conn, "acct", last, token, "amount", "-2.00")
        correct_seconds = time.perf_counter() - started
        started = time.perf_counter()
        classification_undo_outlook(conn, load_classification(conn, "f000000"))
        outlook_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text(header + "03/20/2026,SYNTHETIC GROCER,9.00,\n")
        started = time.perf_counter()
        import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started
        (purchases,) = [entry[1] for entry in movement.financial_types if entry[0] == "purchase"]
        assert purchases == count - 1, movement.financial_types
        print(
            f"many classifications={count:6} rewrite={effects_seconds:7.3f}s "
            f"totals={totals_seconds:7.3f}s show_and_classify={classify_seconds:7.3f}s "
            f"show_and_correct={correct_seconds:7.3f}s "
            f"classification_show={outlook_seconds:7.3f}s later_import={later_seconds:7.3f}s "
            f"applied={purchases}",
            flush=True,
        )
        conn.close()


def measure_classification_chain(length: int) -> None:
    """One chain of classifications, each superseding the one before, written directly."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        conn = new_ledger(root)
        source = root / "a.csv"
        source.write_text("Date,Description,Debit,Credit\n01/10/2026,SYNTHETIC CAFE,6.50,\n")
        import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1)
        transaction_id, record_id = conn.execute(
            "SELECT transaction_id, source_record_id FROM transaction_source").fetchone()
        conn.execute("BEGIN")
        for number in range(length):
            classification_id = f"f{number:06}"
            conn.execute(
                """INSERT INTO type_classification (id, account_id, financial_type,
                                                    target_transaction_id, target_revision,
                                                    supersedes_classification_id)
                   VALUES (?, 'acct', ?, ?, 't7-0', ?)""",
                (classification_id, ("purchase", "fee")[number % 2], transaction_id,
                 f"f{number - 1:06}" if number else None),
            )
            conn.execute("INSERT INTO type_classification_record VALUES (?, ?)",
                         (classification_id, record_id))
            conn.execute("INSERT INTO type_classification_event (classification_id, event) "
                         "VALUES (?, 'made')", (classification_id,))
        write_classification_effects(conn, "acct")
        conn.execute("COMMIT")
        started = time.perf_counter()
        classification_chain_states(conn, "acct")
        states_seconds = time.perf_counter() - started
        started = time.perf_counter()
        active = load_active_classifications(conn, "acct")
        load_seconds = time.perf_counter() - started
        started = time.perf_counter()
        classification_undo_outlook(conn, load_classification(conn, f"f{length - 1:06}"))
        outlook_seconds = time.perf_counter() - started
        print(
            f"chain classifications={length:5} states={states_seconds:7.4f}s "
            f"load_active={load_seconds:7.4f}s classification_show={outlook_seconds:7.4f}s "
            f"active={len(active)}",
            flush=True,
        )
        conn.close()


def classified() -> None:
    for rows_per_file in (33, 167, 333, 667):
        measure_classifying_dense(rows_per_file)
    for count in (100, 500, 1000, 2000, 4000):
        measure_many_classifications(count)
    for length in (50, 2000):
        measure_classification_chain(length)


def measure_resolving(rows_per_file: int, kind: str) -> None:
    """Two exports of the same rows_per_file purchases under complete coverage, with one row of a
    that the parser cannot read. That row blocks every confident pair of a (D-024), so resolving it
    without values that rule the purchases out pays for every merge it unblocks, and undoing it for
    every split. The completion supplies a date outside the purchases' dates (D-050)."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        conn = new_ledger(root)
        header = "Date,Description,Debit,Credit\n"
        rows = "".join(
            f"01/{1 + number % 28:02}/2026,SYNTHETIC SHOP {number},{1 + number}.00,\n"
            for number in range(rows_per_file)
        )
        whole = declare_complete("2026-01-01", "2026-01-31", "posting")
        for name, content in (("a.csv", header + rows + "not a row of this layout\n"),
                              ("b.csv", header + " " + rows)):
            source = root / name
            source.write_text(content)
            (result,) = import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CARD_V1,
                                     declared_coverage=whole)
            assert result.outcome == "imported", result
        before = account_movement(conn, "acct").transactions
        assert before == 2 * rows_per_file, "the unreadable row must block every pair"
        (issue,) = conn.execute(
            "SELECT id FROM review_issue WHERE kind = 'unresolved_record'"
        ).fetchone()

        started = time.perf_counter()
        token = review_revision(load_review_evidence(conn, issue))
        show_seconds = time.perf_counter() - started
        started = time.perf_counter()
        if kind == "dismiss":
            resolved = dismiss_record(conn, "acct", issue, token)
        else:
            resolved = complete_record(conn, "acct", issue, token,
                                       {"amount": "-1.00", "posting_date": "2026-03-01"})
        resolve_seconds = time.perf_counter() - started
        assert resolved.transactions_after == rows_per_file + (kind == "complete"), resolved

        later = root / "later.csv"
        later.write_text(header + "03/20/2026,SYNTHETIC GROCER,9.00,\n")
        started = time.perf_counter()
        import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started

        resolution = load_resolution(conn, resolved.resolution_id)
        started = time.perf_counter()
        revision = resolution_undo_outlook(conn, resolution, DEFAULT_RULES).revision
        outlook_seconds = time.perf_counter() - started
        started = time.perf_counter()
        undone = undo_resolution(conn, "acct", resolved.resolution_id, revision)
        undo_seconds = time.perf_counter() - started
        assert undone.transactions_after == 2 * rows_per_file + 1, undone
        print(
            f"{kind:8} pairs={rows_per_file:5} merged={resolved.moved_records:5} "
            f"item_show={show_seconds:7.3f}s resolve={resolve_seconds:7.3f}s "
            f"later_import={later_seconds:7.3f}s resolution_show={outlook_seconds:7.3f}s "
            f"undo={undo_seconds:7.3f}s split={undone.moved_records:5}",
            flush=True,
        )
        conn.close()


def resolved() -> None:
    for kind in ("dismiss", "complete"):
        for rows_per_file in (500, 2000, 5000):
            measure_resolving(rows_per_file, kind)


def measure_declaring(rows_per_file: int) -> None:
    """Two exports of the same rows_per_file purchases, the first of unknown coverage and the second
    declared complete at import. Declaring the first complete afterwards pays for every merge that
    makes, and undoing it for every split. It is compared with importing the second export into a
    ledger where the first was declared complete at import, which makes the same merges (D-051)."""
    header = "Date,Description,Debit,Credit\n"
    rows = "".join(
        f"01/{1 + number % 28:02}/2026,SYNTHETIC SHOP {number},{1 + number}.00,\n"
        for number in range(rows_per_file)
    )
    whole = declare_complete("2026-01-01", "2026-01-31", "posting")
    seconds = {}
    for at_import in (False, True):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            conn = new_ledger(root)
            for name, content, coverage in (("a.csv", header + rows, whole if at_import else None),
                                            ("b.csv", header + " " + rows, whole)):
                source = root / name
                source.write_text(content)
                started = time.perf_counter()
                (result,) = import_files(conn, [source], account_id="acct",
                                         layout=SYNTHETIC_CARD_V1, declared_coverage=coverage)
                seconds[at_import, name] = time.perf_counter() - started
                assert result.outcome == "imported", result
            if at_import:
                assert account_movement(conn, "acct").transactions == rows_per_file
                conn.close()
                continue
            assert account_movement(conn, "acct").transactions == 2 * rows_per_file
            (document_id,) = conn.execute(
                "SELECT id FROM source_document WHERE file_name = 'a.csv'"
            ).fetchone()
            started = time.perf_counter()
            token = document_coverage_revision(load_document_coverage(conn, document_id))
            show_seconds = time.perf_counter() - started
            started = time.perf_counter()
            declared = declare_coverage(conn, "acct", document_id, token, "complete",
                                        "2026-01-01", "2026-01-31", "posting")
            declare_seconds = time.perf_counter() - started
            assert declared.transactions_after == rows_per_file, declared

            later = root / "later.csv"
            later.write_text(header + "03/20/2026,SYNTHETIC GROCER,9.00,\n")
            started = time.perf_counter()
            import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CARD_V1)
            later_seconds = time.perf_counter() - started

            declaration = load_declaration(conn, declared.declaration_id)
            started = time.perf_counter()
            revision = declaration_undo_outlook(conn, declaration, DEFAULT_RULES).revision
            outlook_seconds = time.perf_counter() - started
            started = time.perf_counter()
            undone = undo_declaration(conn, "acct", declared.declaration_id, revision)
            undo_seconds = time.perf_counter() - started
            assert undone.transactions_after == 2 * rows_per_file + 1, undone
            conn.close()
    print(
        f"pairs={rows_per_file:5} merged={declared.moved_records:5} coverage_show={show_seconds:7.3f}s "
        f"declare={declare_seconds:7.3f}s later_import={later_seconds:7.3f}s "
        f"undo_show={outlook_seconds:7.3f}s undo={undo_seconds:7.3f}s split={undone.moved_records:5} "
        f"merging_import={seconds[True, 'b.csv']:7.3f}s",
        flush=True,
    )


def declared() -> None:
    for rows_per_file in (500, 2000, 5000):
        measure_declaring(rows_per_file)


def merchant_name(number: int) -> str:
    """A distinct merchant word for each number, so that no two share a description block."""
    letters = "BCDFGHJKLMNPQRSTVWXZ"
    word = ""
    while True:
        word = letters[number % len(letters)] + word
        number //= len(letters)
        if not number:
            break
    return word.rjust(4, "A") + "MART"


def measure_pending(pairs: int, one_block: bool) -> None:
    """One pending export and one posted export of the same pairs purchases on one day, each posted
    at another amount. With one_block every description is alike, so every pending unit is related
    to every posted unit, the worst case and the one D-032 documents for candidate discovery.
    Otherwise every merchant has its own block, the common case (D-052)."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        conn = new_ledger(root)
        header = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"

        def name(number):
            return f"SYNTHETIC SHOP {number}" if one_block else f"{merchant_name(number)} STORE"

        pending = "".join(f",2026-01-10,,{name(number)},-{number + 1}.00,PENDING\n"
                          for number in range(pairs))
        posted = "".join(f",2026-01-10,2026-01-11,{name(number)},-{number + 1}.50,POSTED\n"
                         for number in range(pairs))
        seconds = []
        for name, content in (("pending.csv", header + pending), ("posted.csv", header + posted)):
            source = root / name
            source.write_text(content)
            started = time.perf_counter()
            (result,) = import_files(conn, [source], account_id="acct", layout=SYNTHETIC_CHECKING_V1)
            seconds.append(time.perf_counter() - started)
            assert result.outcome == "imported", result
        documents, records, unresolved, _ = load_evidence(conn, "acct")
        started = time.perf_counter()
        derivation = derive(documents, records, unresolved, DEFAULT_RULES)
        derive_seconds = time.perf_counter() - started
        raised = sum("pending_amount_changed" in item.reasons for item in derivation.items)
        assert raised >= 1, "the shape must raise pending-to-posted candidates"

        later = root / "later.csv"
        later.write_text(header + ",2026-03-20,2026-03-21,SYNTHETIC GROCER,-9.00,POSTED\n")
        started = time.perf_counter()
        import_files(conn, [later], account_id="acct", layout=SYNTHETIC_CHECKING_V1)
        later_seconds = time.perf_counter() - started
        print(
            f"{'one block' if one_block else 'distinct':9} pairs={pairs:5} "
            f"items={len(derivation.items):5} pending_items={raised:5} "
            f"posted_import={seconds[1]:7.3f}s derive={derive_seconds:7.3f}s "
            f"steps={derivation.candidate_steps:9} later_import={later_seconds:7.3f}s",
            flush=True,
        )
        conn.close()


def pending_posted() -> None:
    for one_block in (False, True):
        for pairs in (100, 500, 2000):
            measure_pending(pairs, one_block)


def transfer_ledger(root: Path, outflows: list[int], inflows: list[int], one_day: bool = False):
    """A checking account with one row per outflow, each classified as a transfer, written
    directly, and a savings account with one row per inflow. Amounts are in cents. one_day puts
    every row on one date, so that every pair is within the window."""
    path = root / "ledger.db"
    create_database(path)
    conn = connect(path)
    conn.execute("INSERT INTO account (id, display_name, account_type) "
                 "VALUES ('out', 'out', 'checking'), ('in', 'in', 'savings')")
    header = "Date,Description,Debit,Credit\n"
    for account, name, amounts, column in (("out", "out.csv", outflows, 0),
                                           ("in", "in.csv", inflows, 1)):
        source = root / name
        source.write_text(header + "".join(
            f"01/{10 if one_day else 1 + number % 28:02}/2026,SYNTHETIC MOVE {number},"
            + ("{0:.2f},".format(-cents / 100) if column == 0 else ",{0:.2f}".format(cents / 100))
            + "\n"
            for number, cents in enumerate(amounts)
        ))
        import_files(conn, [source], account_id=account, layout=SYNTHETIC_CARD_V1)
    conn.execute("BEGIN")
    classify_directly(conn, "out", [
        (transaction_id, record_id, "transfer") for transaction_id, record_id in conn.execute(
            "SELECT transaction_id, source_record_id FROM transaction_source "
            "WHERE account_id = 'out' ORDER BY source_record_id").fetchall()
    ])
    conn.execute("COMMIT")
    return conn


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


def side_by_amount(conn, account):
    return {
        amount: (transaction_id, record_id)
        for transaction_id, record_id, amount in conn.execute(
            """SELECT link.transaction_id, link.source_record_id, entry.amount_cents
               FROM transaction_source link
               JOIN ledger_transaction entry ON entry.id = link.transaction_id
               WHERE link.account_id = ?""",
            (account,),
        )
    }


def measure_many_matches(count: int) -> None:
    """count applied matches, written directly, and one pair left to match. Every import,
    decision, correction and classification in either account rewrites every match's outcome, so
    the later import pays for all of them."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        amounts = [100 * (1 + number) for number in range(count + 1)]
        conn = transfer_ledger(root, [-cents for cents in amounts], amounts)
        outflows, inflows = side_by_amount(conn, "out"), side_by_amount(conn, "in")
        conn.execute("BEGIN")
        for number, cents in enumerate(amounts[1:]):
            match_id = f"m{number:06}"
            conn.execute("INSERT INTO transfer_match (id) VALUES (?)", (match_id,))
            for side, account, (transaction_id, record_id) in (
                    ("outflow", "out", outflows[-cents]), ("inflow", "in", inflows[cents])):
                conn.execute("INSERT INTO transfer_match_side VALUES (?, ?, ?, ?, 't7-0')",
                             (match_id, side, account, transaction_id))
                conn.execute("INSERT INTO transfer_match_record VALUES (?, ?, ?)",
                             (match_id, side, record_id))
            conn.execute("INSERT INTO transfer_match_event (match_id, event) VALUES (?, 'made')",
                         (match_id,))
        write_transfer_effects(conn)
        conn.execute("COMMIT")

        conn.execute("BEGIN")
        started = time.perf_counter()
        write_transfer_effects(conn)
        effects_seconds = time.perf_counter() - started
        conn.execute("COMMIT")
        started = time.perf_counter()
        summary = transfer_summary(conn)
        totals_seconds = time.perf_counter() - started
        outflow, inflow = outflows[-amounts[0]][0], inflows[amounts[0]][0]
        started = time.perf_counter()
        made = match_transfer(
            conn, "out", outflow, transaction_revision(load_merge_evidence(conn, outflow)),
            "in", inflow, transaction_revision(load_merge_evidence(conn, inflow)))
        match_seconds = time.perf_counter() - started
        started = time.perf_counter()
        token = match_revision(conn, load_match(conn, made.match_id))
        undo_transfer(conn, "out", made.match_id, token)
        undo_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text("Date,Description,Debit,Credit\n03/20/2026,SYNTHETIC GROCER,9.00,\n")
        # Count what the import rewrites, so that the timing is known to include every match.
        rewritten = []

        def counted(connection):
            rewritten.append(connection.execute(
                "SELECT COUNT(*) FROM transfer_match_effect").fetchone()[0])
            write_transfer_effects(connection)

        apply_module.write_transfer_effects = counted
        started = time.perf_counter()
        import_files(conn, [later], account_id="out", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started
        apply_module.write_transfer_effects = write_transfer_effects
        assert rewritten == [count], rewritten
        applied = conn.execute(
            "SELECT COUNT(*) FROM transfer_match_effect WHERE state = 'applied'").fetchone()[0]
        assert summary.matches == count and applied == count, (summary, applied)
        print(
            f"many matches={count:6} rewrite={effects_seconds:7.3f}s totals={totals_seconds:7.3f}s "
            f"show_and_match={match_seconds:7.3f}s show_and_undo={undo_seconds:7.3f}s "
            f"later_import={later_seconds:7.3f}s applied={applied}",
            flush=True,
        )
        conn.close()


def measure_candidates(count: int, equal: bool) -> None:
    """count transfer-kind outflows and count inflows, unmatched. Distinct amounts give count
    candidates. Equal amounts on one day give count squared, the quadratic case."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        amounts = [500] * count if equal else [100 * (1 + number) for number in range(count)]
        conn = transfer_ledger(root, [-cents for cents in amounts], amounts, one_day=equal)
        started = time.perf_counter()
        found = transfer_candidates(conn)
        list_seconds = time.perf_counter() - started
        started = time.perf_counter()
        transfer_summary(conn)
        totals_seconds = time.perf_counter() - started
        expected = count * count if equal else count
        assert len(found) == expected, (len(found), expected)
        print(
            f"candidates {'equal' if equal else 'distinct'}={count:5} list={list_seconds:7.3f}s "
            f"totals={totals_seconds:7.3f}s candidates={len(found)}",
            flush=True,
        )
        conn.close()


def transfers() -> None:
    for count in (100, 1000, 4000):
        measure_many_matches(count)
    for count in (1000, 4000):
        measure_candidates(count, equal=False)
    for count in (50, 200, 400):
        measure_candidates(count, equal=True)


def one_sided_ledger(root: Path, statements: int, opposite: int, spans: int):
    """statements + 1 equal outflows on 01/10 in a checking account, each classified as a
    transfer, and a savings counterpart holding opposite equal inflows on 01/20, outside the
    window, so that each statement's search for its other side checks every one of them and finds
    none. The counterpart also has spans single-day documents of complete coverage, none in the
    window, so that each coverage check reads every span. Every outflow but the last is stated
    one-sided, written directly."""
    path = root / "ledger.db"
    create_database(path)
    conn = connect(path)
    conn.execute("INSERT INTO account (id, display_name, account_type) "
                 "VALUES ('out', 'out', 'checking'), ('in', 'in', 'savings')")
    header = "Date,Description,Debit,Credit\n"
    (root / "out.csv").write_text(header + "".join(
        f"01/10/2026,SYNTHETIC MOVE {number},5.00,\n" for number in range(statements + 1)))
    import_files(conn, [root / "out.csv"], account_id="out", layout=SYNTHETIC_CARD_V1)
    (root / "in.csv").write_text(header + "".join(
        f"01/20/2026,SYNTHETIC MOVE IN {number},,5.00\n" for number in range(opposite)))
    import_files(conn, [root / "in.csv"], account_id="in", layout=SYNTHETIC_CARD_V1)
    for number in range(spans):
        day = f"2025-{1 + number // 28:02}-{1 + number % 28:02}"
        source = root / f"span{number}.csv"
        source.write_text(header + f"{day[5:7]}/{day[8:]}/2025,SYNTHETIC GROCER,1.00,\n")
        import_files(conn, [source], account_id="in", layout=SYNTHETIC_CARD_V1,
                     declared_coverage=declare_complete(day, day, "posting"))
    conn.execute("BEGIN")
    links = conn.execute(
        "SELECT transaction_id, source_record_id FROM transaction_source WHERE account_id = 'out' "
        "ORDER BY source_record_id").fetchall()
    classify_directly(conn, "out", [(transaction_id, record_id, "transfer")
                                    for transaction_id, record_id in links])
    for number, (transaction_id, record_id) in enumerate(links[1:]):
        statement_id = f"o{number:06}"
        conn.execute(
            """INSERT INTO one_sided_transfer (id, account_id, counterpart_account_id,
                                               target_transaction_id, target_revision)
               VALUES (?, 'out', 'in', ?, 't7-0')""",
            (statement_id, transaction_id),
        )
        conn.execute("INSERT INTO one_sided_transfer_record VALUES (?, ?)",
                     (statement_id, record_id))
        conn.execute("INSERT INTO one_sided_transfer_event (one_sided_transfer_id, event) "
                     "VALUES (?, 'made')", (statement_id,))
    write_transfer_effects(conn)
    conn.execute("COMMIT")
    return conn, links[0][0]


def measure_one_sided(statements: int, opposite: int, spans: int) -> None:
    """Every import, decision, correction and classification in any account rewrites every
    one-sided transfer's outcome, which checks opposite pairs and reads spans for each, so the
    later import pays statements x (opposite + spans)."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        conn, unstated = one_sided_ledger(root, statements, opposite, spans)
        assert conn.execute(
            "SELECT COUNT(*) FROM document_coverage WHERE account_id = 'in' "
            "AND coverage_kind = 'complete'").fetchone()[0] == spans
        conn.execute("BEGIN")
        started = time.perf_counter()
        write_transfer_effects(conn)
        effects_seconds = time.perf_counter() - started
        conn.execute("COMMIT")
        started = time.perf_counter()
        summary = one_sided_summary(conn)
        totals_seconds = time.perf_counter() - started
        started = time.perf_counter()
        stated = state_one_sided(conn, "out", unstated,
                                 transaction_revision(load_merge_evidence(conn, unstated)), "in")
        state_seconds = time.perf_counter() - started
        started = time.perf_counter()
        token = one_sided_revision(conn, load_one_sided(conn, stated.one_sided_transfer_id))
        undo_one_sided(conn, "out", stated.one_sided_transfer_id, token)
        undo_seconds = time.perf_counter() - started
        later = root / "later.csv"
        later.write_text("Date,Description,Debit,Credit\n03/20/2026,SYNTHETIC GROCER,9.00,\n")
        # Count what the import rewrites, so that the timing is known to include every statement.
        rewritten = []

        def counted(connection):
            rewritten.append(connection.execute(
                "SELECT COUNT(*) FROM one_sided_transfer_effect").fetchone()[0])
            write_transfer_effects(connection)

        apply_module.write_transfer_effects = counted
        started = time.perf_counter()
        import_files(conn, [later], account_id="in", layout=SYNTHETIC_CARD_V1)
        later_seconds = time.perf_counter() - started
        apply_module.write_transfer_effects = write_transfer_effects
        assert rewritten == [statements], rewritten
        applied = conn.execute(
            "SELECT COUNT(*) FROM one_sided_transfer_effect WHERE state = 'applied'").fetchone()[0]
        assert summary.applied == statements and applied == statements, (summary, applied)
        print(
            f"one-sided={statements:5} opposite={opposite:5} spans={spans:4} "
            f"rewrite={effects_seconds:7.3f}s totals={totals_seconds:7.3f}s "
            f"show_and_state={state_seconds:7.3f}s show_and_undo={undo_seconds:7.3f}s "
            f"later_import={later_seconds:7.3f}s applied={applied}",
            flush=True,
        )
        conn.close()


def one_sided() -> None:
    for statements, opposite, spans in ((100, 1, 1), (1000, 1, 1), (100, 1000, 1),
                                        (1000, 1000, 1), (1000, 1, 300), (1000, 1000, 300)):
        measure_one_sided(statements, opposite, spans)


def income_ledger(root: Path, count: int):
    """count of each: matched pairs, one-sided transfers, unconfirmed transfer kinds, purchases,
    income and unclassified inflows, written directly. Amounts differ by group, so nothing is a
    candidate and no one-sided transfer finds its other side."""
    matched = [100 * (1 + number) for number in range(count)]
    one_sided = [100 * (count + 1 + number) for number in range(count)]
    unconfirmed = [100 * (2 * count + 1 + number) for number in range(count)]
    unclassified = [100 * number + 1 for number in range(count)]
    conn = transfer_ledger(root, [-cents for cents in matched + one_sided + unconfirmed],
                           matched + unclassified)
    spending = root / "spending.csv"
    spending.write_text("Date,Description,Debit,Credit\n" + "".join(
        f"02/{1 + number % 28:02}/2026,SYNTHETIC SHOP {number},{number + 1}.07,\n"
        f"02/{1 + number % 28:02}/2026,SYNTHETIC PAY {number},,{number + 1}.03\n"
        for number in range(count)))
    import_files(conn, [spending], account_id="out", layout=SYNTHETIC_CARD_V1)
    outflows, inflows = side_by_amount(conn, "out"), side_by_amount(conn, "in")
    conn.execute("BEGIN")
    classify_directly(conn, "out", [
        (transaction_id, record_id, "purchase" if amount < 0 else "income")
        for transaction_id, record_id, amount in conn.execute(
            """SELECT link.transaction_id, link.source_record_id, entry.amount_cents
               FROM transaction_source link
               JOIN ledger_transaction entry ON entry.id = link.transaction_id
               JOIN source_document document ON document.id = link.source_document_id
               WHERE document.file_name = 'spending.csv'""").fetchall()
    ])
    for number, cents in enumerate(matched):
        match_id = f"m{number:06}"
        conn.execute("INSERT INTO transfer_match (id) VALUES (?)", (match_id,))
        for side, account, (transaction_id, record_id) in (
                ("outflow", "out", outflows[-cents]), ("inflow", "in", inflows[cents])):
            conn.execute("INSERT INTO transfer_match_side VALUES (?, ?, ?, ?, 't7-0')",
                         (match_id, side, account, transaction_id))
            conn.execute("INSERT INTO transfer_match_record VALUES (?, ?, ?)",
                         (match_id, side, record_id))
        conn.execute("INSERT INTO transfer_match_event (match_id, event) VALUES (?, 'made')",
                     (match_id,))
    for number, cents in enumerate(one_sided):
        statement_id = f"o{number:06}"
        transaction_id, record_id = outflows[-cents]
        conn.execute(
            """INSERT INTO one_sided_transfer (id, account_id, counterpart_account_id,
                                               target_transaction_id, target_revision)
               VALUES (?, 'out', 'in', ?, 't7-0')""",
            (statement_id, transaction_id),
        )
        conn.execute("INSERT INTO one_sided_transfer_record VALUES (?, ?)",
                     (statement_id, record_id))
        conn.execute("INSERT INTO one_sided_transfer_event (one_sided_transfer_id, event) "
                     "VALUES (?, 'made')", (statement_id,))
    write_transfer_effects(conn)
    conn.execute("COMMIT")
    return conn


def measure_income_and_spending(count: int) -> None:
    """The groups read, for each transaction, whether an applied match or one-sided transfer names
    it, so a lookup missing the effect indexes would cost transactions x effects: here 6 x count
    transactions against 2 x count effects. Shown apart from the candidate search, which totals
    also runs."""
    with tempfile.TemporaryDirectory() as folder:
        conn = income_ledger(Path(folder), count)
        applied = conn.execute(
            """SELECT (SELECT COUNT(*) FROM transfer_match_effect WHERE state = 'applied'),
                      (SELECT COUNT(*) FROM one_sided_transfer_effect WHERE state = 'applied')"""
        ).fetchone()
        assert applied == (count, count), applied
        started = time.perf_counter()
        groups = income_and_spending(conn)
        groups_seconds = time.perf_counter() - started
        started = time.perf_counter()
        movement = account_movement(conn)
        movement_seconds = time.perf_counter() - started
        started = time.perf_counter()
        transfers = transfer_summary(conn)
        transfers_seconds = time.perf_counter() - started
        found = (groups.confirmed_transfers.transactions, groups.income.transactions,
                 groups.spending.transactions, groups.unconfirmed_transfer_kinds.transactions,
                 groups.unclassified.transactions)
        assert found == (3 * count, count, count, count, count), found
        assert movement.transactions == 7 * count and transfers.transactions_in_candidates == 0
        print(
            f"income and spending transactions={movement.transactions:6} "
            f"effects={2 * count:5} groups={groups_seconds:7.3f}s "
            f"movement={movement_seconds:7.3f}s transfers_with_candidates="
            f"{transfers_seconds:7.3f}s",
            flush=True,
        )
        conn.close()


def income() -> None:
    # 8,000 binds 24,000 transactions, under SQLite's 32,766 variables, which
    # write_transfer_effects passes one per transaction and so exceeds beyond it.
    for count in (1000, 4000, 8000):
        measure_income_and_spending(count)


# The 100,000-transaction shape (D-057 recommendation 8, Z1 to Z6). Every account uses the checking
# layout, whose reliable IDs keep rows of different files apart.
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
               VALUES (?, ?, ?, ?, 't10-0')""", (allocation_id, account, value, transaction))
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


def main() -> None:
    if sys.argv[1:] == ["--scale"]:
        measure_scale()
        return
    if sys.argv[1:] == ["--scale", "--household"]:
        measure_household()
        return
    if sys.argv[1:2] == ["--scale"] and sys.argv[2:3] == ["--category-rules"]:
        measure_category_rules(int(sys.argv[3]))
        return
    if sys.argv[1:] == ["--worst"]:
        worst_cases()
        return
    if sys.argv[1:] == ["--constrained"]:
        constrained()
        return
    if sys.argv[1:] == ["--confirmed"]:
        confirmed()
        return
    if sys.argv[1:] == ["--separated"]:
        separated()
        return
    if sys.argv[1:] == ["--superseded"]:
        superseded()
        return
    if sys.argv[1:] == ["--corrected"]:
        corrected()
        return
    if sys.argv[1:] == ["--resolved"]:
        resolved()
        return
    if sys.argv[1:] == ["--declared"]:
        declared()
        return
    if sys.argv[1:] == ["--pending"]:
        pending_posted()
        return
    if sys.argv[1:] == ["--classified"]:
        classified()
        return
    if sys.argv[1:] == ["--transfers"]:
        transfers()
        return
    if sys.argv[1:] == ["--one-sided"]:
        one_sided()
        return
    if sys.argv[1:] == ["--income"]:
        income()
        return
    sizes = [(24, 200), (24, 1000), (24, 4000)]
    if len(sys.argv) > 1:
        sizes = [(24, int(value)) for value in sys.argv[1:]]
    for shape in SHAPES:
        for months, rows_per_month in sizes:
            measure(shape, months, rows_per_month)


if __name__ == "__main__":
    main()
