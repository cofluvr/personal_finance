"""The iOS client against the real sync server (D-079's I3, sync-protocol.md), on loopback, with
synthetic data only. Usage: python ios/interop/run_interop.py --work FOLDER

Builds test_snapshot.py's household, makes its sync identity, and starts the backend's pairing
and serving servers on 127.0.0.1 through the test-only hook (tests/scenarios/sync_harness.py).
Then runs CommonCentsKit's Interop tests with swift test: they pair, take the serve port from the
reconnect code, sync, install and acknowledge. Exits 0 only if Swift passed and the ledger
recorded one device, one delivery of the served snapshot and its acknowledgement."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests" / "scenarios"),
                str(ROOT / "tests" / "stress")]

from run_crashes import household  # noqa: E402
from sync_harness import LOOPBACK, LoopbackSyncServer  # noqa: E402

from personal_finance.cli import main as pf  # noqa: E402
from personal_finance.snapshot.files import build_in_one_read, verified  # noqa: E402
from personal_finance.sync import devices, identity  # noqa: E402
from personal_finance.sync.pairing import pairing_payload, reconnect_payload  # noqa: E402
from personal_finance.sync.server import PAIR, SERVE, tls_context  # noqa: E402


def connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=rw", uri=True, autocommit=True,
                           check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def main() -> int:
    options = argparse.ArgumentParser()
    options.add_argument("--work", type=Path, required=True)
    work = options.parse_args().work.resolve()
    work.mkdir(parents=True)
    folder = work / "household"
    folder.mkdir(mode=0o700)
    ledger = household(folder)
    with ledger.capture.redirect:
        assert pf(["sync", "identity", "create", "--db", str(ledger.path)]) == 0
    sync_folder = identity.sync_folder_beside(ledger.path)
    pair_conn, serve_conn = connection(ledger.path), connection(ledger.path)
    current = identity.required_identity(pair_conn)
    key, certificate = identity.checked_identity_files(current, sync_folder)
    utc_now = lambda: datetime.now(timezone.utc)  # noqa: E731
    pairing = LoopbackSyncServer(LOOPBACK, 0, tls_context(certificate, key), pair_conn,
                                 mode=PAIR, minutes=2, utc_now=utc_now, device_name="Interop")
    window = devices.open_window(pair_conn, current, LOOPBACK, pairing.server_port, utc_now())
    pairing.window_id = window.window_id
    data = build_in_one_read(serve_conn, date(2026, 5, 4), 90,
                             "5b1f0a52-8f0e-4c55-9d7a-2f6b9e1c3d40", "2026-05-04T17:00:00.000Z")
    document = verified(data)
    serving = LoopbackSyncServer(LOOPBACK, 0, tls_context(certificate, key), serve_conn,
                                 mode=SERVE, minutes=5, utc_now=utc_now, document=document,
                                 snapshot=data)
    threads = [threading.Thread(target=server.run, daemon=True) for server in (pairing, serving)]
    for thread in threads:
        thread.start()
    plan = work / "interop.json"
    plan.write_text(json.dumps({
        "pairing": pairing_payload(LOOPBACK, pairing.server_port, current.certificate_sha256,
                                   window.pairing_secret),
        "reconnect": reconnect_payload(LOOPBACK, serving.server_port,
                                       current.certificate_sha256),
        "snapshot_id": document["snapshot_id"],
        "content_sha256": document["content_sha256"]}))
    swift = subprocess.run(["swift", "test", "--filter", "Interop"],
                           cwd=ROOT / "ios" / "CommonCentsKit",
                           env={**os.environ, "COMMONCENTS_INTEROP": str(plan)},
                           capture_output=True, text=True, timeout=900)
    print(swift.stdout[-3000:], swift.stderr[-2000:] if swift.returncode else "")
    serving.finished = True
    pairing.finished = True
    for thread in threads:
        thread.join(5)
    check = sqlite3.connect(f"file:{ledger.path}?mode=ro", uri=True)
    devices_paired = check.execute("SELECT name FROM paired_device").fetchall()
    deliveries = check.execute("SELECT snapshot_id, content_sha256 FROM sync_delivery").fetchall()
    acknowledged = check.execute("SELECT COUNT(*) FROM sync_acknowledgement").fetchone()[0]
    check.close()
    print(f"ledger: devices {devices_paired}, deliveries {len(deliveries)}, "
          f"acknowledgements {acknowledged}, served {serving.counts['served']}, "
          f"refused {serving.counts['refused']}")
    ok = (swift.returncode == 0 and devices_paired == [("Interop",)] and deliveries ==
          [(document["snapshot_id"], document["content_sha256"])] and acknowledged == 1)
    print("interop: " + ("passed" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
