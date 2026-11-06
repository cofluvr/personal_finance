"""Measures import and reconciliation cost on synthetic files (A39).

Not part of the test suite. Run from the repository root:

    PYTHONPATH=src:tests/benchmarks .venv/bin/python tests/benchmarks/measure_reconciliation.py

Databases are created in a temporary folder and removed afterwards.
"""

import sys
import tempfile
import time
from pathlib import Path

from synthetic_ledger import dense_rows, ordinary_rows, variant_rows, with_overlap

from personal_finance.db.migrate import connect, create_database
from personal_finance.ingest.layouts import SYNTHETIC_CARD_V1
from personal_finance.ingest.pipeline import import_files
from personal_finance.reconcile.apply import _load_evidence
from personal_finance.reconcile.cross_document import derive
from personal_finance.reconcile.rules import DEFAULT_RULES

SHAPES = {"ordinary": ordinary_rows, "dense": dense_rows, "variants": variant_rows}


def measure(shape: str, months: int, rows_per_month: int) -> None:
    files = with_overlap(SHAPES[shape](months, rows_per_month))
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

        documents, records, unresolved, _ = _load_evidence(conn, "acct")
        started = time.perf_counter()
        derivation = derive(documents, records, unresolved, DEFAULT_RULES)
        derive_seconds = time.perf_counter() - started

        rows = len(records)
        items = len(derivation.items)
        print(
            f"{shape:9} rows={rows:7} files={len(files):3} "
            f"first={import_seconds[0]:7.2f}s last={import_seconds[-1]:7.2f}s "
            f"cumulative={sum(import_seconds):8.2f}s derive={derive_seconds:6.2f}s "
            f"steps={derivation.candidate_steps:9} items={items:6}",
            flush=True,
        )
        conn.close()


def main() -> None:
    sizes = [(24, 200), (24, 1000), (24, 4000)]
    if len(sys.argv) > 1:
        sizes = [(24, int(value)) for value in sys.argv[1:]]
    for shape in SHAPES:
        for months, rows_per_month in sizes:
            measure(shape, months, rows_per_month)


if __name__ == "__main__":
    main()
