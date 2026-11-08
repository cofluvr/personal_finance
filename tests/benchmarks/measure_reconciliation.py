"""Measures import and reconciliation cost on synthetic files (A39).

Not part of the test suite. Run from the repository root:

    PYTHONPATH=src:tests/benchmarks .venv/bin/python tests/benchmarks/measure_reconciliation.py
    (add --worst for the stress shapes, --constrained for dense groups with decisions,
    --confirmed to compare confirmation with rejection, --separated to compare separating a
    merge with rejection and partition, --superseded to compare a separation superseding a
    confirmation with a partition, --corrected for value corrections, --resolved for completing
    and dismissing unresolved rows, --declared for coverage declared after import, --pending for
    pending rows posted at another amount, --classified for financial types, --transfers for
    transfer matches across two accounts, or rows per month such as 200 1000 4000)

Databases are created in a temporary folder and removed afterwards. Each timing covers
one import_files call: reading and parsing the file, writing records, reconciling the
account and committing. It excludes generating the data, writing the CSV file and
creating the database.

Provisional targets (D-034) apply only to the 24-file ordinary and dense fixtures at
4,000 rows a month, on the recorded machine. They are reported here and are deliberately
not test assertions, because wall-clock checks would make the suite flaky.
"""

import sys
import tempfile
import time
from itertools import islice
from pathlib import Path

from synthetic_ledger import dense_rows, full_reexports, ordinary_rows, variant_rows, with_overlap

from personal_finance.db.migrate import connect, create_database
from personal_finance.cli import DIRECT_PAIRS_SHOWN
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1, SYNTHETIC_CHECKING_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.reconcile import apply as apply_module
from personal_finance.reconcile.apply import decision_states, load_evidence
from personal_finance.reconcile.classification_effects import (
    classification_chain_states,
    load_active_classifications,
    write_classification_effects,
)
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
from personal_finance.reconcile.transfers import match_transfer, undo_transfer
from personal_finance.reports.totals import account_movement, transfer_summary
from personal_finance.reports.transfer_evidence import load_match, match_revision
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
                   VALUES (?, 'acct', 'amount', -1, ?, 't6-0')""",
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
                   VALUES (?, 'acct', 'amount', ?, ?, 't6-0', ?)""",
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
                   VALUES (?, 'acct', 'purchase', ?, 't6-0')""",
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
                   VALUES (?, 'acct', ?, ?, 't6-0', ?)""",
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
    for number, (transaction_id, record_id) in enumerate(conn.execute(
        "SELECT transaction_id, source_record_id FROM transaction_source WHERE account_id = 'out' "
        "ORDER BY source_record_id"
    ).fetchall()):
        classification_id = f"f{number:06}"
        conn.execute(
            """INSERT INTO type_classification (id, account_id, financial_type,
                                                target_transaction_id, target_revision)
               VALUES (?, 'out', 'transfer', ?, 't6-0')""",
            (classification_id, transaction_id),
        )
        conn.execute("INSERT INTO type_classification_record VALUES (?, ?)",
                     (classification_id, record_id))
        conn.execute("INSERT INTO type_classification_event (classification_id, event) "
                     "VALUES (?, 'made')", (classification_id,))
    write_classification_effects(conn, "out")
    conn.execute("COMMIT")
    return conn


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
                conn.execute("INSERT INTO transfer_match_side VALUES (?, ?, ?, ?, 't6-0')",
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


def main() -> None:
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
    sizes = [(24, 200), (24, 1000), (24, 4000)]
    if len(sys.argv) > 1:
        sizes = [(24, int(value)) for value in sys.argv[1:]]
    for shape in SHAPES:
        for months, rows_per_month in sizes:
            measure(shape, months, rows_per_month)


if __name__ == "__main__":
    main()
