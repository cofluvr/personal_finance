"""Fuzzing every parser and input boundary with Hypothesis (ZB4, D-077 point 6, the M21.2 slice plan
point 3). Synthetic data only, outside the gating suite. Usage:

    python tests/stress/run_fuzz.py --target T --examples N --seed S --work FOLDER

T is one of amounts, csv, pdf, snapshot, sync, ui, or all. Each target states what must hold. A
failure prints Hypothesis's falsifying example and writes it to tests/stress/seeds/, to become a
fixed test; the exit code is then 1."""

import argparse
import hashlib
import json
import re
import socket
import sqlite3
import sys
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests" / "scenarios")]

from hypothesis import HealthCheck, given, seed, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

SEEDS = Path(__file__).resolve().parent / "seeds"
OUTCOMES = {"imported", "already_imported", "failed"}
FAILURE_CODE = re.compile(r"[a-z][a-z_]*[a-z]")


def fresh_ledger(folder: Path, name: str) -> Path:
    from fresh_ledger import create_fresh_ledger

    path = folder / f"{name}.db"
    if path.exists():
        path.unlink()
    create_fresh_ledger(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO account (id, display_name, account_type) VALUES ('a', 'A', "
                 "'checking')")
    conn.commit()
    conn.close()
    return path


def counts(conn) -> tuple:
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                 for table in ("source_document", "source_record", "ledger_transaction"))


# amounts: exact parsing or a refusal, never a guess.

def target_amounts(examples, folder):
    from personal_finance.money import MoneyParseError, format_cents, parse_cents
    from personal_finance.planning.entries import parsed_date
    from personal_finance.reconcile.decisions import DecisionRefused

    @given(text=st.text(max_size=24))
    @settings(max_examples=examples, deadline=None, database=None)
    def any_text(text):
        """Anything is parsed to whole cents or refused, and what is parsed prints back."""
        try:
            cents = parse_cents(text)
        except MoneyParseError:
            return
        if cents is None:
            assert text.strip() == "", text
            return
        assert isinstance(cents, int) and parse_cents(format_cents(cents)) == cents

    @given(negative=st.booleans(), units=st.integers(0, 10**9), hundredths=st.integers(0, 99))
    @settings(max_examples=examples, deadline=None, database=None)
    def exact(negative, units, hundredths):
        """An amount written with two decimals is exactly its cents: the oracle is the digits."""
        text = f"{'-' if negative else ''}{units}.{hundredths:02d}"
        expected = (units * 100 + hundredths) * (-1 if negative else 1)
        assert parse_cents(text) == expected, text

    @given(text=st.one_of(st.text(max_size=12), st.dates().map(str)))
    @settings(max_examples=examples, deadline=None, database=None)
    def dates(text):
        try:
            assert parsed_date(text, "--from") == text
        except DecisionRefused:
            return

    any_text()
    exact()
    dates()


# csv: every file imports or fails with a code; nothing partial, nothing fabricated.

CHECKING_HEADER = "Transaction ID,Transaction Date,Posted Date,Description,Amount,Status"
valid_rows = st.lists(st.tuples(st.integers(-99999, 99999).filter(bool),
                                st.text("ABCDEFGHIJ ", min_size=1, max_size=12).map(str.strip)
                                .filter(bool)), max_size=6)
junk_lines = st.lists(st.text(max_size=40).map(lambda text: text.replace("\n", " ")),
                      max_size=3)


def target_csv(examples, folder):
    from personal_finance.ingest.layouts import SYNTHETIC_CHECKING_V1
    from personal_finance.ingest.pipeline import import_files

    @given(rows=valid_rows, junk=junk_lines, raw=st.binary(max_size=200),
           use_raw=st.booleans(), header=st.sampled_from([CHECKING_HEADER, "Date,Amount", ""]))
    @settings(max_examples=examples, deadline=None, database=None,
              suppress_health_check=[HealthCheck.too_slow])
    def csv(rows, junk, raw, use_raw, header):
        path = fresh_ledger(folder, "csv")
        lines = [header] + [f"R{index},2026-01-05,2026-01-06,{text},{cents / 100:.2f},POSTED"
                            for index, (cents, text) in enumerate(rows)] + junk
        data = raw if use_raw else ("\n".join(lines) + "\n").encode()
        file = folder / "fuzz.csv"
        file.write_bytes(data)
        conn = sqlite3.connect(path, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        before = counts(conn)
        (result,) = import_files(conn, [file], account_id="a", layout=SYNTHETIC_CHECKING_V1)
        after = counts(conn)
        assert result.outcome in OUTCOMES, result
        if result.outcome == "failed":
            assert FAILURE_CODE.fullmatch(result.failure_code or ""), result
            assert after == before, (result, before, after)
        elif not use_raw and header == CHECKING_HEADER and not any(junk):
            amounts = sorted(cents for (cents,) in conn.execute(
                "SELECT amount_cents FROM record_parse WHERE status = 'parsed'"))
            assert amounts == sorted(cents for cents, _ in rows), (amounts, rows)
        conn.close()

    csv()


# pdf: mutated synthetic printouts fail only by documented codes.

def target_pdf(examples, folder):
    from test_csv_pdf_matching import OCTOBER, printout

    from personal_finance.ingest.layouts import US_BANK_CARD_ACTIVITY_PDF_V1
    from personal_finance.ingest.pipeline import import_files

    original = printout(OCTOBER)

    @given(flips=st.lists(st.tuples(st.integers(0, len(original) - 1), st.integers(0, 255)),
                          max_size=8),
           cut=st.integers(0, len(original)))
    @settings(max_examples=examples, deadline=None, database=None,
              suppress_health_check=[HealthCheck.too_slow])
    def pdf(flips, cut):
        data = bytearray(original[:cut] if cut < 40 else original)
        for position, value in flips:
            if position < len(data):
                data[position] = value
        path = fresh_ledger(folder, "pdf")
        conn = sqlite3.connect(path, isolation_level=None)
        conn.execute("UPDATE account SET account_type = 'credit_card', last4 = '4321'")
        file = folder / "fuzz.pdf"
        file.write_bytes(bytes(data))
        before = counts(conn)
        (result,) = import_files(conn, [file], account_id="a", layout=US_BANK_CARD_ACTIVITY_PDF_V1)
        assert result.outcome in OUTCOMES, result
        if result.outcome == "failed":
            assert FAILURE_CODE.fullmatch(result.failure_code or ""), result
            assert counts(conn) == before
        conn.close()

    pdf()


# snapshot: a mutated snapshot is refused with a reason, never accepted wrongly or crashing.

def mutations(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from mutations(item, (*path, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from mutations(item, (*path, index))
    yield path


def target_snapshot(examples, folder):
    from personal_finance.snapshot.canonical import canonical_bytes, sha256_of
    from personal_finance.snapshot.files import SnapshotRefused, verified

    golden = (ROOT / "tests/fixtures/synthetic/snapshots/v1.0/household.json").read_bytes()
    document = json.loads(golden)
    paths = [path for path in mutations(document) if path]
    replacements = st.one_of(st.none(), st.booleans(), st.integers(-10**12, 10**12),
                             st.text(max_size=8), st.just([]), st.just({}))

    @given(index=st.integers(0, len(paths) - 1), replacement=replacements,
           redigest=st.booleans())
    @settings(max_examples=examples, deadline=None, database=None)
    def snapshot(index, replacement, redigest):
        changed = json.loads(golden)
        *parents, last = paths[index]
        holder = changed
        for key in parents:
            holder = holder[key]
        if holder[last] == replacement:
            return
        holder[last] = replacement
        if redigest and isinstance(changed.get("content"), dict):
            try:
                changed["content_sha256"] = sha256_of(changed["content"])
            except Exception:
                pass
        try:
            data = canonical_bytes(changed)
        except Exception:
            return
        try:
            verified(data)
        except SnapshotRefused as refused:
            assert str(refused), "a refusal says why"
            return
        # Accepted: only a change the schema allows (a nullable or free value), redigested.
        assert redigest, ("accepted without its digest", paths[index])

    snapshot()


# sync and ui: arbitrary requests get a fixed answer, write nothing and echo nothing.

def served_once(server, data: bytes, tls_context=None) -> bytes:
    client, served = socket.socketpair()

    def serve():
        try:
            connection = server.tls_wrapped(served) if tls_context else served
        except OSError:
            return
        server.process_request(connection, ("127.0.0.1", 50000))

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        if tls_context:
            with tls_context.wrap_socket(client) as tls:
                tls.sendall(data)
                received = b"".join(iter(lambda: tls.recv(65536), b""))
        else:
            client.sendall(data)
            client.shutdown(socket.SHUT_WR)
            received = b"".join(iter(lambda: client.recv(65536), b""))
    finally:
        client.close()
        thread.join(30)
    return received


requests = st.one_of(
    st.binary(max_size=300),
    st.builds(lambda method, path, headers, body: (
        f"{method} {path} HTTP/1.1\r\n" + "".join(f"{name}: {value}\r\n"
                                                  for name, value in headers) + "\r\n"
    ).encode("latin-1", "replace") + body,
        st.sampled_from(["GET", "POST", "PUT", "HEAD", "DELETE", "OPTIONS", "get", "X"]),
        st.sampled_from(["/", "/v1/ack", "/v1/pair", "/v1/snapshot/latest", "/start",
                         "/review", "/transactions?search=a", "//", "/%00"]),
        st.lists(st.tuples(st.sampled_from(["Host", "Authorization", "Content-Length",
                                            "Content-Type", "Cookie", "Origin",
                                            "Accept-Snapshot-Major", "Transfer-Encoding"]),
                           st.text("abcdef0123456789-.:/ ", max_size=60)), max_size=6),
        st.binary(max_size=120)))


def logical(path: Path) -> str:
    from personal_finance.db.backups import logical_digest

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return logical_digest(conn)
    finally:
        conn.close()


SENTINEL = b"ZQXJ"


def target_sync(examples, folder):
    import io
    import contextlib
    from datetime import date

    from sync_harness import Clock, LoopbackSyncServer
    from sync_reference_client import client_context

    from personal_finance.cli import main
    from personal_finance.snapshot.files import build_in_one_read, verified
    from personal_finance.sync import identity
    from personal_finance.sync.server import SERVE, tls_context

    path = fresh_ledger(folder, "sync")
    with contextlib.redirect_stdout(io.StringIO()):
        assert main(["sync", "identity", "create", "--db", str(path)]) == 0
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True, autocommit=True,
                           check_same_thread=False)
    current = identity.required_identity(conn)
    key, certificate = identity.checked_identity_files(current, identity.sync_folder_beside(path))
    data = build_in_one_read(conn, date(2026, 5, 4), 90, "5b1f0a52-8f0e-4c55-9d7a-2f6b9e1c3d40",
                             "2026-05-04T17:00:00.000Z")
    server = LoopbackSyncServer("127.0.0.1", 0, tls_context(certificate, key), conn,
                                mode=SERVE, minutes=60, utc_now=Clock(),
                                document=verified(data), snapshot=data)
    fixed = {b'{"error":"unauthorized"}', b'{"error":"not_found"}', b'{"error":"bad_request"}',
             b'{"error":"body_too_large"}', b'{"error":"headers_too_large"}',
             b'{"error":"not_delivered"}',
             b'{"error":"unsupported_snapshot_major","supported_majors":[1]}'}
    before = logical(path)

    @given(request=requests)
    @settings(max_examples=examples, deadline=None, database=None,
              suppress_health_check=[HealthCheck.too_slow])
    def sync(request):
        # Complete header blocks only: an unfinished one gets no answer after the 10-second
        # timeout, as the stalled-client case of test_sync_threats.py.
        received = served_once(server, request + SENTINEL + b"\r\n\r\n", client_context())
        head, _, body = received.partition(b"\r\n\r\n")
        assert received == b"" and not request.strip(b"\r\n ") or \
            head.startswith(b"HTTP/1.0 "), received[:80]
        assert SENTINEL not in received
        assert received == b"" or body in fixed, body[:120]
        assert logical(path) == before

    try:
        sync()
    finally:
        server.server_close()
        conn.close()


def target_ui(examples, folder):
    from local_ui_client import UiClient

    path = fresh_ledger(folder, "ui")
    client = UiClient(path)
    before = logical(path)

    @given(request=requests)
    @settings(max_examples=examples, deadline=None, database=None,
              suppress_health_check=[HealthCheck.too_slow])
    def ui(request):
        received = served_once(client.server, request + SENTINEL + b"\r\n\r\n")
        assert SENTINEL not in received
        # A blank request line gets no answer from http.server: nothing written, nothing echoed.
        if received:
            status = int(received.split(b" ", 2)[1])
            assert status in (200, 303, 400, 403, 404, 405, 408, 411, 413, 414, 415, 421, 431,
                              501), status
        assert logical(path) == before

    try:
        ui()
    finally:
        client.close()


TARGETS = {"amounts": target_amounts, "csv": target_csv, "pdf": target_pdf,
           "snapshot": target_snapshot, "sync": target_sync, "ui": target_ui}


def main() -> int:
    options = argparse.ArgumentParser()
    options.add_argument("--target", required=True, choices=[*TARGETS, "all"])
    options.add_argument("--examples", type=int, default=200)
    options.add_argument("--seed", type=int, default=0)
    options.add_argument("--work", type=Path, required=True)
    arguments = options.parse_args()
    work = arguments.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    failed = []
    for name in (TARGETS if arguments.target == "all" else [arguments.target]):
        folder = work / name
        folder.mkdir(mode=0o700, exist_ok=True)
        try:
            seed(arguments.seed)(lambda: TARGETS[name](arguments.examples, folder))()
            print(f"{name}: {arguments.examples} examples passed, seed {arguments.seed}",
                  flush=True)
        except Exception:
            failure = traceback.format_exc()
            failed.append(name)
            SEEDS.mkdir(exist_ok=True)
            digest = hashlib.sha256(failure.encode()).hexdigest()[:8]
            (SEEDS / f"{name}-seed{arguments.seed}-{digest}.txt").write_text(failure)
            print(f"{name}: FAILED, seed {arguments.seed}\n{failure[-1500:]}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
