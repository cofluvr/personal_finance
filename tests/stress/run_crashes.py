"""Crashes at every commit point (ZB3, D-077 point 5, the M21.2 slice plan point 2). Synthetic data
only, outside the gating suite. Usage:

    python tests/stress/run_crashes.py --points all|N --seed S --work FOLDER

Builds test_snapshot.py's household once, then for each write command below: runs it once to its
end on a copy (the after state, and how many SQL statements it ran), and then, for every statement
N it runs (or N sampled with the seed), runs it again on a fresh copy killed with SIGKILL at its
Nth statement. After each kill the ledger must open through the gate, pass SQLite's
integrity_check and foreign_key_check, and equal the before or the after state, table by table,
with clock readings set aside (uuid4 is made deterministic in the child, so IDs compare exactly).
Exits 1 on any failure, naming the command and N."""

import argparse
import contextlib
import io
import random
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests" / "scenarios")]
CHILD = Path(__file__).resolve().parent / "crash_child.py"
CLOCK = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")
RANDOM_DIGEST = re.compile(r"'[0-9a-f]{64}'")
AS_OF = "2026-05-04"


class Capture:
    """capsys for a ledger helper outside pytest."""

    def __init__(self):
        self.out, self.err = io.StringIO(), io.StringIO()

    @property
    @contextlib.contextmanager
    def redirect(self):
        with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err):
            yield

    def readouterr(self):
        from collections import namedtuple

        result = namedtuple("Captured", "out err")(self.out.getvalue(), self.err.getvalue())
        self.out.seek(0), self.out.truncate(), self.err.seek(0), self.err.truncate()
        return result


def state(path: Path) -> dict:
    """Every table's rows, sorted, with clock readings set aside."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [name for name, in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name")]
        # A new identity's certificate digest is random by nature: openssl makes a new key.
        return {table: sorted(RANDOM_DIGEST.sub("H", CLOCK.sub("T", repr(row)))
                              if table == "sync_identity" else CLOCK.sub("T", repr(row))
                              for row in conn.execute(f"SELECT * FROM {table}"))
                for table in tables} | {
            "user_version": conn.execute("PRAGMA user_version").fetchone()[0]}
    finally:
        conn.close()


def sound(path: Path) -> list[str]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        problems = []
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            problems.append("integrity_check")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            problems.append("foreign_key_check")
        return problems
    finally:
        conn.close()


def opens(path: Path) -> bool:
    found = subprocess.run([str(ROOT / "bin" / "pf"), "storage", "--db", str(path)],
                           capture_output=True, text=True, timeout=120)
    return found.returncode == 0 or "pf migrate" in found.stderr


def child(kill_at: int, words: list[str], count_file: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHILD), str(kill_at), str(count_file), *words],
        capture_output=True, text=True, timeout=300,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src"),
             "HOME": str(count_file.parent)})


def interrupted_import_only(now: dict, before: dict, after: dict) -> bool:
    """D-023: an import commits each file on its own after writing its run's row, and marks the
    run finished last. A kill between leaves that row without finished_at, with every other
    table as before (no file committed) or as after (the file committed), and nothing else."""
    extra = sorted(set(now["import_run"]) - set(before["import_run"]))
    others = [table for table in now if table != "import_run"]
    return ((all(now[table] == before[table] for table in others)
             or all(now[table] == after[table] for table in others))
            and len(extra) == 1 and extra[0].endswith(", None)")
            and set(before["import_run"]) <= set(now["import_run"]))


def household(folder: Path):
    from test_snapshot import SnapshotLedger
    from test_snapshot import household as build

    capture = Capture()
    with capture.redirect:
        ledger = build(SnapshotLedger(folder, capture))
        ledger.capture = capture
        return ledger


def commands(ledger, folder: Path) -> dict:
    """Each write command's words, with the tokens it needs taken from the base ledger."""
    with ledger.capture.redirect:
        transaction = ledger.deposit("extra.csv", "2026-05-02", amount="-42.00",
                                     text="SYNTHETIC SHOP", financial_type=None)
        purchase = ledger.pay("insurer.csv", "2026-05-03", amount="-300.00",
                              text="SYNTHETIC INSURER")
        ledger.assign_ok(ledger.reserve, "A", "300.00", as_of=AS_OF)
        token = ledger.transaction_revision(transaction)
        purchase_token = ledger.transaction_revision(purchase)
        fund_words = ledger.fund_words(name="Car", monthly="50.00", as_of=AS_OF)
        fund_token = ledger.fund_preview_revision(name="Car", monthly="50.00", as_of=AS_OF)
        trip = ledger.add_fund_ok(name="Trip", monthly="20.00", as_of=AS_OF)
        assign_token = ledger.assignment_token(trip, "A", AS_OF)
        buffer_token = ledger.setting_token("checking_buffer_cents")
    new_file = folder / "new.csv"
    new_file.write_text("Transaction ID,Transaction Date,Posted Date,Description,Amount,Status\n"
                        "N1,2026-05-03,2026-05-03,SYNTHETIC NEW ONE,-10.00,POSTED\n"
                        "N2,2026-05-03,2026-05-03,SYNTHETIC NEW TWO,-11.00,POSTED\n")
    db = ["--db", str(ledger.path)]
    return {
        "import": ["import", *db, "--account", "A", "--layout", "synthetic_checking_v1",
                   str(new_file)],
        "classify": ["review", "classify", transaction, *db, "--account", "A", "--revision",
                     token, "--type", "purchase"],
        "categorize": ["review", "categorize", purchase, *db, "--account", "A",
                       "--revision", purchase_token, "--category", "Food"],
        "consume": ["review", "consume", purchase, *db, "--account", "A", "--fund",
                    ledger.reserve, "--revision", purchase_token],
        "fund add": ["fund", "add", *db, *fund_words, "--revision", fund_token],
        "fund assign": ["fund", "assign", *db, "--fund", trip, "--account", "A",
                        "--amount", "100.00", "--as-of", AS_OF, "--revision", assign_token],
        "setting undo": ["setting", "undo", *db, "checking_buffer_cents", "--revision",
                         buffer_token],
        "scenario add": ["scenario", "add", *db, "--name", "Move"],
        "sync identity create": ["sync", "identity", "create", *db],
    }


def migration_base(folder: Path) -> Path:
    """A ledger set back to 35 with a populated household, for crashing migration 0036."""
    from test_decisions import drop_sync_tables

    path = folder / "at-35.db"
    conn = sqlite3.connect(path, isolation_level=None)
    drop_sync_tables(conn)
    conn.execute("PRAGMA user_version = 35")
    conn.close()
    return path


def main() -> int:
    options = argparse.ArgumentParser()
    options.add_argument("--points", default="all")
    options.add_argument("--seed", type=int, default=0)
    options.add_argument("--work", type=Path, required=True)
    options.add_argument("--only", action="append", default=[])
    arguments = options.parse_args()
    random.seed(arguments.seed)
    work = arguments.work.resolve()
    work.mkdir(parents=True)
    base_folder = work / "base"
    base_folder.mkdir(mode=0o700)
    ledger = household(base_folder)
    plan = commands(ledger, base_folder)
    shutil.copy(ledger.path, base_folder / "at-35.db")
    plan["migrate 0036"] = ["migrate", "--db", str(migration_base(base_folder))]
    failures, kills = [], 0
    for name, words in plan.items():
        if arguments.only and name not in arguments.only:
            continue
        source = Path(words[words.index("--db") + 1])
        before = state(source)
        reference = work / f"{name.replace(' ', '-')}-after"
        reference.mkdir(mode=0o700)
        shutil.copy(source, reference / source.name)
        ran = [word.replace(str(source), str(reference / source.name)) for word in words]
        count_file = reference / "count"
        finished = child(0, ran, count_file)
        assert finished.returncode == 0, (name, "did not run to its end", finished.stderr)
        after, statements = state(reference / source.name), int(count_file.read_text())
        assert after != before, (name, "changed nothing")
        points = list(range(1, statements + 1))
        if arguments.points != "all":
            points = sorted(random.sample(points, min(int(arguments.points), len(points))))
        print(f"{name}: {statements} statements, killing at {len(points)}", flush=True)
        for point in points:
            folder = work / f"{name.replace(' ', '-')}-{point}"
            folder.mkdir(mode=0o700)
            shutil.copy(source, folder / source.name)
            killed = [word.replace(str(source), str(folder / source.name)) for word in words]
            child(point, killed, folder / "count")
            kills += 1
            path = folder / source.name
            problems = sound(path)
            now = state(path)
            if now not in (before, after) and not interrupted_import_only(now, before, after):
                changed = [table for table in now if now[table] not in (before.get(table),
                                                                        after.get(table))]
                problems.append(f"neither before nor after: {changed[:5]}")
            if not opens(path):
                problems.append("does not open through the gate")
            if problems:
                failures.append((name, point, problems))
                print(f"  FAILED at {point}: {problems}", flush=True)
            else:
                shutil.rmtree(folder)
    print(f"{kills} kills over {len(plan)} commands, {len(failures)} failures, seed "
          f"{arguments.seed}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
