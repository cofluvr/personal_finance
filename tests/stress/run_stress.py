"""Concurrency stress (ZB2, D-077 point 4, the M21.2 slice plan point 1). Synthetic data only,
outside the gating suite. Usage:

    python tests/stress/run_stress.py --minutes N --seed S --writers W --readers R --work FOLDER

Copies test_snapshot.py's household with 20 more unclassified rows, then runs W writer and R
reader processes against it for N minutes. Writers contend on targets that tokens guard: the
household share (h1), the checking buffer setting (st1) and classifying the extra rows (t13),
each time showing the token, waiting a random moment, then writing with it. Readers run every
report. Every 60 seconds and at the end it checks integrity_check, foreign_key_check and that the
snapshot built now reconciles. At the end: no write may have succeeded with a token another
write to the same target had made stale (that write started after the token was shown and
committed before this one started), and every refusal must be a documented message."""

import argparse
import contextlib
import io
import json
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests" / "scenarios"),
                str(Path(__file__).resolve().parent)]
AS_OF = "2026-05-04"
EXTRA_ROWS = 20
DOCUMENTED = [
    r"revision does not match", r"database is busy", r"already",
    r"must be set first|not set", r"this transaction is not", r"is classified",
    r"Nothing was changed\.$",
]
READS = [["totals"], ["report", "monthly"], ["report", "household"], ["transactions"],
         ["review", "list"], ["safe-to-spend", "--as-of", AS_OF],
         ["report", "budget", "--month", "2026-05", "--as-of", AS_OF],
         ["funds", "--as-of", AS_OF], ["dashboard", "--as-of", AS_OF]]


def run_pf(*words) -> tuple[int, str, str]:
    from personal_finance.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(words))
        except SystemExit as exit:
            # argparse refusing the words: this harness's mistake, reported as undocumented.
            return 2, "", f"usage refused: {' '.join(words[:3])}: {exit.code}"
    return code, out.getvalue(), err.getvalue()


# The roles, each in its own process.

def writer(db: str, seed: int, until: float, log: Path) -> None:
    rng = random.Random(seed)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    extras = [row[0] for row in conn.execute(
        "SELECT transaction_id FROM transaction_source ts JOIN source_record sr "
        "ON sr.id = ts.source_record_id JOIN record_parse rp ON rp.source_record_id = sr.id "
        "WHERE rp.description LIKE 'SYNTHETIC STRESS%'")]
    conn.close()
    with log.open("a") as file:
        while time.time() < until:
            kind = rng.choice(["share", "buffer", "classify"])
            shown_start = time.time()
            if kind == "share":
                target = "share"
                out = run_pf("household", "share", "show", "--db", db)[1]
                token = re.search(r"Revision: (h1-[0-9a-f]{16})", out)
                first = rng.choice([50, 60, 70])
                words = (["household", "share", "undo", "--db", db] if "undo it" in out else
                         ["household", "share", "set", "--db", db, "--part", f"Alex={first}",
                          "--part", f"Bea={100 - first}"])
            elif kind == "buffer":
                target = "buffer"
                out = run_pf("setting", "show", "--db", db)[1]
                block = out.split("Setting checking_buffer_cents:")[1]
                token = re.search(r"Revision: (st1-[0-9a-f]{16})", block)
                words = (["setting", "undo", "--db", db, "checking_buffer_cents"]
                         if "not set" not in block.splitlines()[0] else
                         ["setting", "set", "--db", db, "checking_buffer_cents",
                          f"{rng.randint(1, 900)}.00"])
            else:
                target = rng.choice(extras)
                out = run_pf("review", "transaction", "show", target, "--db", db)[1]
                token = re.search(r"Revision: (t\d+-[0-9a-f]{16})", out)
                words = ["review", "classify", target, "--db", db, "--account", "A",
                         "--type", rng.choice(["purchase", "fee"])]
            shown_end = time.time()
            if token is None:
                continue
            time.sleep(rng.random() * 0.05)
            attempt_start = time.time()
            code, _, err = run_pf(*words, "--revision", token[1])
            file.write(json.dumps({"kind": kind, "target": target, "token": token[1],
                                   "shown_start": shown_start, "shown_end": shown_end,
                                   "attempt_start": attempt_start, "attempt_end": time.time(),
                                   "ok": code == 0, "error": err.strip()}) + "\n")
            file.flush()


def reader(db: str, seed: int, until: float, log: Path) -> None:
    rng = random.Random(seed)
    with log.open("a") as file:
        while time.time() < until:
            words = list(rng.choice(READS))
            # --db goes after the command's group words, as the test Ledger places it.
            position = 2 if words[0] in ("report", "review") else 1
            code, _, err = run_pf(*words[:position], "--db", db, *words[position:])
            file.write(json.dumps({"read": " ".join(words), "ok": code == 0,
                                   "error": err.strip()}) + "\n")
            file.flush()


# The parent.

def prepared(work: Path) -> Path:
    from run_crashes import household

    folder = work / "household"
    folder.mkdir(mode=0o700)
    ledger = household(folder)
    with ledger.capture.redirect:
        rows = [f"ST{index},2026-05-0{1 + index % 4},2026-05-0{1 + index % 4},"
                f"SYNTHETIC STRESS {index},-{index + 1}.00,POSTED" for index in range(EXTRA_ROWS)]
        ledger.load_path(ledger.write("stress.csv", "Transaction ID,Transaction Date,Posted Date,"
                                      "Description,Amount,Status\n", rows),
                         layout="synthetic_checking_v1")
    return ledger.path


def checked(db: Path) -> list[str]:
    from personal_finance.snapshot import builder, validate

    problems = []
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            problems.append("integrity_check")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            problems.append("foreign_key_check")
        conn.execute("BEGIN")
        content = builder.build_content(conn, date.fromisoformat(AS_OF))
        conn.execute("COMMIT")
        problems += validate.unreconciled(content)
    except sqlite3.OperationalError as error:
        if "locked" not in str(error):
            raise
    finally:
        conn.close()
    return problems


def stale_successes(records: list[dict]) -> list[dict]:
    """Writes accepted with a token another write had already spent. Every write here changes
    its target's state, and a token is a digest of that state, so two successive successful
    writes to one target (in commit order) can never carry the same token: if they do, the
    second was accepted stale. A token may recur after other writes return the state to one
    it described (a share set, then undone), and its use is then correct: the state it covers
    is the state now. Earlier versions of this check counted that as stale."""
    by_target = {}
    for record in records:
        if record.get("ok") and "target" in record:
            by_target.setdefault(record["target"], []).append(record)
    stale = []
    for successes in by_target.values():
        successes.sort(key=lambda record: record["attempt_end"])
        stale += [later for earlier, later in zip(successes, successes[1:])
                  if earlier["token"] == later["token"]]
    return stale


def main() -> int:
    options = argparse.ArgumentParser()
    options.add_argument("--minutes", type=float, default=1)
    options.add_argument("--seed", type=int, default=0)
    options.add_argument("--writers", type=int, default=4)
    options.add_argument("--readers", type=int, default=2)
    options.add_argument("--work", type=Path, required=True)
    options.add_argument("--role", choices=["writer", "reader"])
    options.add_argument("--db")
    options.add_argument("--until", type=float)
    options.add_argument("--log", type=Path)
    arguments = options.parse_args()
    if arguments.role:
        role = writer if arguments.role == "writer" else reader
        role(arguments.db, arguments.seed, arguments.until, arguments.log)
        return 0
    work = arguments.work.resolve()
    work.mkdir(parents=True)
    db = prepared(work)
    until = time.time() + arguments.minutes * 60
    children = []
    for index in range(arguments.writers + arguments.readers):
        role = "writer" if index < arguments.writers else "reader"
        log = work / f"{role}-{index}.jsonl"
        children.append(subprocess.Popen(
            [sys.executable, __file__, "--role", role, "--db", str(db), "--until", str(until),
             "--seed", str(arguments.seed * 100 + index), "--log", str(log), "--work",
             str(work)], env={"PATH": "/usr/bin:/bin", "HOME": str(work)}))
    problems = []
    while any(child.poll() is None for child in children):
        time.sleep(min(60, max(1, until - time.time())))
        found = checked(db)
        problems += [f"{time.time() - until:+.0f}s: {problem}" for problem in found]
        print(f"check: {found or 'ok'}", flush=True)
    problems += [f"child exited {child.returncode}" for child in children if child.returncode]
    problems += [f"end: {problem}" for problem in checked(db)]
    records = [json.loads(line) for log in sorted(work.glob("*.jsonl"))
               for line in log.read_text().splitlines()]
    writes = [record for record in records if "target" in record]
    reads = [record for record in records if "read" in record]
    stale = stale_successes(records)
    undocumented = sorted({record["error"] for record in records if not record["ok"]
                           and not any(re.search(pattern, record["error"])
                                       for pattern in DOCUMENTED)})
    read_failures = sorted({record["error"] for record in reads if not record["ok"]
                            and "database is busy" not in record["error"]})
    print(f"writes {len(writes)}: {sum(record['ok'] for record in writes)} succeeded, "
          f"{sum(not record['ok'] for record in writes)} refused; reads {len(reads)}: "
          f"{sum(not record['ok'] for record in reads)} busy or failed", flush=True)
    print(f"stale tokens that succeeded: {len(stale)}; undocumented refusals: {undocumented}; "
          f"read failures: {read_failures}; problems: {problems}", flush=True)
    shutil.copy(db, work / "final.db")
    return 1 if stale or undocumented or read_failures or problems else 0


if __name__ == "__main__":
    sys.exit(main())
