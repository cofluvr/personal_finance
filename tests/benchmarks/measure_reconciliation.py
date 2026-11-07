"""Measures import and reconciliation cost on synthetic files (A39).

Not part of the test suite. Run from the repository root:

    PYTHONPATH=src:tests/benchmarks .venv/bin/python tests/benchmarks/measure_reconciliation.py
    (add --worst for the stress shapes, --constrained for dense groups with decisions,
    --confirmed to compare confirmation with rejection, --separated to compare separating a
    merge with rejection and partition, or rows per month such as 200 1000 4000)

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
from pathlib import Path

from synthetic_ledger import dense_rows, full_reexports, ordinary_rows, variant_rows, with_overlap

from personal_finance.db.migrate import connect, create_database
from personal_finance.ingest.coverage import declare_complete
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.reconcile.apply import load_evidence
from personal_finance.reconcile.cross_document import Constraint, Document, Record, derive
from personal_finance.reconcile.decisions import (
    confirm_groups,
    reject_pairs,
    separate_records,
    undo_decision,
)
from personal_finance.reconcile.rules import DEFAULT_RULES
from personal_finance.reports.decision_evidence import load_decision, undo_outlook
from personal_finance.reports.review_evidence import (
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
    sizes = [(24, 200), (24, 1000), (24, 4000)]
    if len(sys.argv) > 1:
        sizes = [(24, int(value)) for value in sys.argv[1:]]
    for shape in SHAPES:
        for months, rows_per_month in sizes:
            measure(shape, months, rows_per_month)


if __name__ == "__main__":
    main()
