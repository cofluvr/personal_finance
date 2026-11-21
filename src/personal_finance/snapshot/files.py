"""Creating, verifying and listing snapshot files (D-075 points 4 and 7, the M19.2 slice plan).

create builds every section inside one read transaction on one read-only connection, so a writer
waits until the snapshot is built and the snapshot is of one state. It then writes a new file only,
to a destination pf export would accept, 0600, atomically: a temporary file in the same folder,
fsynced, linked to the final name (which fails if it exists), removed, and the folder fsynced.
Then it records the snapshot without its path. verify writes nothing.
"""

import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from personal_finance.db.exports import ExportRefused, refuse_unsafe_export_destination
from personal_finance.planning.entries import in_one_write
from personal_finance.snapshot import validate
from personal_finance.snapshot.builder import FORMAT, build_snapshot
from personal_finance.snapshot.canonical import NotCanonical, parsed_canonical, sha256_of

SNAPSHOT = "a snapshot"
ENVELOPE_FIELDS = ("content", "content_sha256", "format", "generated_at", "schema_version",
                   "snapshot_id")


class SnapshotRefused(Exception):
    """A snapshot not written, or not verified, saying why."""


class SnapshotNotRecorded(Exception):
    """A snapshot written whose record failed: the file stays, and this says so."""


@dataclass(frozen=True)
class Written:
    snapshot_id: str
    schema_version: str
    as_of: str
    window_days: int
    generated_at: str
    content_sha256: str
    bytes_written: int
    transactions: int


def build_in_one_read(conn: sqlite3.Connection, as_of: date, window_days: int,
                      snapshot_id: str, generated_at: str) -> bytes:
    """Every section from one read transaction: its shared lock holds writers off until the
    build is done (point 4)."""
    conn.execute("BEGIN")
    try:
        conn.execute("SELECT COUNT(*) FROM account").fetchone()
        return build_snapshot(conn, as_of, window_days, snapshot_id, generated_at)
    finally:
        conn.execute("COMMIT")


def write_atomically(out_path: Path, data: bytes) -> int:
    """A new 0600 file at out_path holding data, or nothing at all. The destination is checked
    by the caller first; a name taken since is refused by the link."""
    absolute = Path(os.path.abspath(out_path))
    temporary = absolute.parent / f".{absolute.name}.{uuid.uuid4().hex}.partial"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, absolute)
        except FileExistsError:
            raise ExportRefused(f"{out_path} already exists, and a snapshot never replaces a "
                                "file. Nothing was written.") from None
    finally:
        temporary.unlink(missing_ok=True)
    folder = os.open(absolute.parent, os.O_RDONLY)
    try:
        os.fsync(folder)
    finally:
        os.close(folder)
    return len(data)


def record(conn: sqlite3.Connection, document: dict) -> None:
    content = document["content"]
    in_one_write(conn, lambda: conn.execute(
        """INSERT INTO snapshot_record (snapshot_id, schema_version, as_of, window_days,
                                        generated_at, content_sha256)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (document["snapshot_id"], document["schema_version"], content["cutoff"]["as_of"],
         content["period"]["window_days"], document["generated_at"],
         document["content_sha256"])))


def create(read_conn: sqlite3.Connection, write_conn_of, out_path: Path, as_of: date,
           window_days: int, snapshot_id: str, generated_at: str, real_ledger: bool) -> Written:
    """Build, write and record one snapshot. write_conn_of opens the write connection the record
    needs, after the file is written."""
    refuse_unsafe_export_destination(out_path, real_ledger, SNAPSHOT)
    data = build_in_one_read(read_conn, as_of, window_days, snapshot_id, generated_at)
    document = parsed_canonical(data)
    written = write_atomically(out_path, data)
    try:
        conn = write_conn_of()
        try:
            record(conn, document)
        finally:
            conn.close()
    except Exception as error:
        raise SnapshotNotRecorded(
            f"the snapshot was written to {out_path}, but recording it failed: "
            f"{type(error).__name__}. The file stays; nothing was retried.") from None
    content = document["content"]
    return Written(snapshot_id, document["schema_version"], content["cutoff"]["as_of"],
                   window_days, generated_at, document["content_sha256"], written,
                   len(content["transactions"]))


def verified(data: bytes, conn: sqlite3.Connection | None = None) -> dict:
    """The snapshot, refused at the first check it fails: canonical bytes, the envelope, the
    digest, the schema, the reconciliations, the excluded keys, and with a ledger its record."""
    try:
        document = parsed_canonical(data)
    except NotCanonical as refusal:
        raise SnapshotRefused(f"{refusal}.") from None
    if not isinstance(document, dict) or sorted(document) != sorted(ENVELOPE_FIELDS) or \
            document["format"] != FORMAT:
        raise SnapshotRefused("this is not a snapshot: its envelope is not one.")
    if sha256_of(document["content"]) != document["content_sha256"]:
        raise SnapshotRefused("the snapshot's content does not match its digest.")
    errors = validate.validate(document, validate.load_schema())
    if errors:
        raise SnapshotRefused(f"the snapshot does not match its schema: {errors[0]}.")
    unreconciled = validate.unreconciled(document["content"])
    if unreconciled:
        raise SnapshotRefused(f"the snapshot does not reconcile: {unreconciled[0]}.")
    excluded = validate.excluded_keys(document["content"])
    if excluded:
        raise SnapshotRefused(f"the snapshot holds an excluded key: {excluded[0]}.")
    if conn is not None:
        found = conn.execute("SELECT content_sha256 FROM snapshot_record WHERE snapshot_id = ?",
                             (document["snapshot_id"],)).fetchone()
        if found is None or found[0] != document["content_sha256"]:
            raise SnapshotRefused("this ledger holds no record of this snapshot with this "
                                  "digest.")
    return document


def records(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        """SELECT snapshot_id, schema_version, as_of, window_days, generated_at, content_sha256
           FROM snapshot_record ORDER BY generated_at, snapshot_id""").fetchall()
