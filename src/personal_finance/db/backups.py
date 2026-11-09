"""Backing up a ledger, checking a backup, and restoring one (D-058 points 7 and 8, M5.4).

A backup is a new folder holding `ledger.db`, copied with SQLite's online backup API, every
referenced original under `originals/`, and `manifest.json`: each file's SHA-256 and size, the
schema and code versions, and the ledger's logical digest. Nothing here overwrites: a backup is
written only into a folder it creates, and a restore only to a new path. A real ledger's backup and
restore pass the location and encrypted-volume gates, and a backup must be on a mounted volume other
than the ledger's. Two disk images whose files share a disk are not detected (point 7, as amended).
A synthetic ledger's backup and restore are not gated, as nothing else about it is.

The manifest shows that a backup is whole and unchanged. It is not signed, so it proves nothing
against someone who rewrites the manifest too.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

import personal_finance
from personal_finance.db import real_ledger
from personal_finance.db.migrate import load_migrations, schema_version
from personal_finance.db.originals import (
    ORIGINALS_FOLDER_NAME,
    originals_folder_beside,
    referenced_originals,
    sync_folder,
    verify_originals,
)
from personal_finance.db.real_ledger import (
    UnsafeLocation,
    is_real_ledger,
    refuse_unsafe_real_ledger_location,
)

BACKUP_LEDGER_NAME = "ledger.db"
MANIFEST_NAME = "manifest.json"
MANIFEST_FORMAT = 1
ORIGINAL_IN_BACKUP = re.compile(rf"{ORIGINALS_FOLDER_NAME}/(?P<content_sha256>[0-9a-f]{{64}})")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class BackupRefused(Exception):
    """A backup or restore that cannot go ahead. Nothing is left written."""


class BackupNotIntact(BackupRefused):
    def __init__(self, reason: str):
        super().__init__(f"the backup is not intact: {reason}")
        self.reason = reason


@dataclass(frozen=True)
class CheckedBackup:
    manifest: dict
    byte_count: int

    @property
    def schema_version(self) -> int:
        return self.manifest["schema_version"]

    @property
    def is_real(self) -> bool:
        return self.manifest["real_ledger"]

    @property
    def logical_digest(self) -> str:
        return self.manifest["logical_digest"]

    @property
    def original_names(self) -> list[str]:
        return [name for name in self.manifest["files"] if name != BACKUP_LEDGER_NAME]

    @property
    def file_count(self) -> int:
        return len(self.manifest["files"]) + 1


def tagged(value) -> list:
    """A column value with its SQLite storage class, so 1, 1.0, '1' and b'1' differ."""
    if value is None:
        return ["null"]
    if isinstance(value, int):
        return ["integer", value]
    if isinstance(value, float):
        return ["real", value.hex()]
    if isinstance(value, str):
        return ["text", value]
    return ["blob", bytes(value).hex()]


def logical_digest(conn: sqlite3.Connection) -> str:
    """SHA-256 over the schema version, every schema object, and every table's rows in primary-key
    order, so two ledgers with one digest hold the same schema and the same rows. Values are
    tagged with their storage class, and blobs written as hex."""
    digest = hashlib.sha256()

    def add(item) -> None:
        digest.update(json.dumps(item, separators=(",", ":")).encode() + b"\n")

    add(["user_version", schema_version(conn)])
    for schema_object in conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
    ):
        add(["schema", *schema_object])
    table_names = [name for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_stat%' "
        "ORDER BY name"
    )]
    for table_name in table_names:
        columns = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        # A table without a primary key is ordered by every column, never by rowid.
        key_columns = [column[1] for column in sorted(columns, key=lambda column: column[5])
                       if column[5]] or [column[1] for column in columns]
        order = ", ".join(f'"{name}"' for name in key_columns)
        add(["table", table_name, [column[1] for column in columns]])
        for row in conn.execute(f'SELECT * FROM "{table_name}" ORDER BY {order}'):
            add([tagged(value) for value in row])
    return digest.hexdigest()


def read_regular_file(path: Path) -> bytes | None:
    """A regular file's bytes, or None for a link, anything else, or a file that cannot be read."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as opened_file:
        if not stat.S_ISREG(os.fstat(opened_file.fileno()).st_mode):
            return None
        return opened_file.read()


def write_new_file(path: Path, content: bytes, *, final_mode: int) -> None:
    """Write a file that must not exist yet, synced, then set to final_mode."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as new_file:
        new_file.write(content)
        new_file.flush()
        os.fsync(new_file.fileno())
    os.chmod(path, final_mode)


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def remove_written(path: Path) -> None:
    """Remove a file or folder this module created. Its files are read-only, its folders not."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


# Creating a backup.

def refuse_unsafe_backup_destination(database_path: Path, backup_folder: Path) -> None:
    """Points 2 and 3 for the folder that will hold the backup, and a volume other than the
    ledger's."""
    try:
        refuse_unsafe_real_ledger_location(backup_folder)
    except UnsafeLocation as refusal:
        raise BackupRefused(f"the backup destination is refused: {refusal}") from None
    ledger_volume = real_ledger.mount_point_containing(database_path.resolve().parent)
    backup_volume = real_ledger.mount_point_containing(backup_folder.parent)
    if backup_volume == ledger_volume:
        raise BackupRefused(
            f"a backup must be on a mounted volume other than the ledger's, and {backup_folder} is "
            f"on {ledger_volume}"
        )


def refuse_unless_archive_intact(conn: sqlite3.Connection, database_path: Path) -> None:
    verification = verify_originals(conn, originals_folder_beside(database_path))
    if verification.missing or verification.altered:
        raise BackupRefused(
            f"{len(verification.missing)} originals are missing and {len(verification.altered)} "
            "altered, so nothing was backed up. Run pf archive verify to see them"
        )


def create_backup(conn: sqlite3.Connection, database_path: Path, backup_folder: Path
                  ) -> CheckedBackup:
    """Write a backup into backup_folder, which must not exist, check it as `backup verify` does,
    then record it in the ledger. Any failure removes the folder."""
    backup_folder = Path(os.path.abspath(backup_folder))
    if os.path.lexists(backup_folder):
        raise BackupRefused(f"a backup is always a new folder, and {backup_folder} already exists")
    is_real = is_real_ledger(conn)
    if is_real:
        refuse_unsafe_backup_destination(database_path, backup_folder)
        refuse_unless_archive_intact(conn, database_path)
    try:
        backup_folder.mkdir(mode=0o700)
    except OSError:
        raise BackupRefused(f"could not create the backup folder {backup_folder}") from None
    try:
        write_backup(conn, database_path, backup_folder)
        checked = check_backup(backup_folder)
        record_backup(conn, backup_folder, checked)
    except BaseException:
        remove_written(backup_folder)
        raise
    return checked


def write_backup(conn: sqlite3.Connection, database_path: Path, backup_folder: Path) -> None:
    ledger_copy_path = backup_folder / BACKUP_LEDGER_NAME
    os.close(os.open(ledger_copy_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600))
    ledger_copy = sqlite3.connect(ledger_copy_path)
    try:
        # One step: the whole ledger is copied under one read lock, so a writer waits for it.
        conn.backup(ledger_copy)
        manifest = {
            "format": MANIFEST_FORMAT,
            "real_ledger": is_real_ledger(ledger_copy),
            "schema_version": schema_version(ledger_copy),
            "code_version": personal_finance.__version__,
            "logical_digest": logical_digest(ledger_copy),
        }
        referenced_names = [original.content_sha256
                            for original in referenced_originals(ledger_copy)]
    finally:
        ledger_copy.close()
    ledger_copy_bytes = read_regular_file(ledger_copy_path)
    os.chmod(ledger_copy_path, 0o400)
    files = {BACKUP_LEDGER_NAME: ledger_copy_bytes}

    if manifest["real_ledger"]:
        originals_copy = backup_folder / ORIGINALS_FOLDER_NAME
        originals_copy.mkdir(mode=0o700)
        originals_folder = originals_folder_beside(database_path)
        for content_sha256 in referenced_names:
            content = read_regular_file(originals_folder / content_sha256)
            if content is None or sha256_of(content) != content_sha256:
                raise BackupRefused(
                    f"the original {content_sha256} changed while it was backed up, so nothing "
                    "was backed up. Run pf archive verify to see it"
                )
            write_new_file(originals_copy / content_sha256, content, final_mode=0o400)
            files[f"{ORIGINALS_FOLDER_NAME}/{content_sha256}"] = content
        sync_folder(originals_copy)

    manifest["files"] = {name: {"sha256": sha256_of(content), "size": len(content)}
                         for name, content in sorted(files.items())}
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    write_new_file(backup_folder / MANIFEST_NAME, manifest_text.encode(), final_mode=0o400)
    sync_folder(backup_folder)


def record_backup(conn: sqlite3.Connection, backup_folder: Path, checked: CheckedBackup) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """INSERT INTO backup_record (id, backup_folder, byte_count, file_count, logical_digest)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), str(backup_folder), checked.byte_count, checked.file_count,
             checked.logical_digest),
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


@dataclass(frozen=True)
class RecordedBackup:
    backup_folder: str
    byte_count: int
    file_count: int
    created_at: str


def recorded_backups(conn: sqlite3.Connection) -> list[RecordedBackup]:
    return [RecordedBackup(*row) for row in conn.execute(
        "SELECT backup_folder, byte_count, file_count, created_at FROM backup_record "
        "ORDER BY created_at, id"
    )]


# Checking a backup.

def read_manifest(backup_folder: Path) -> dict:
    """The manifest, refused unless every field has the shape `create_backup` writes."""
    if not stat.S_ISDIR(lstat_mode(backup_folder)):
        raise BackupNotIntact(f"{backup_folder} is not a backup folder")
    manifest_bytes = read_regular_file(backup_folder / MANIFEST_NAME)
    if manifest_bytes is None:
        raise BackupNotIntact(f"{MANIFEST_NAME} is missing")
    try:
        manifest = json.loads(manifest_bytes)
    except (ValueError, UnicodeDecodeError):
        manifest = None
    if not (isinstance(manifest, dict)
            and manifest.get("format") == MANIFEST_FORMAT
            and type(manifest.get("real_ledger")) is bool
            and type(manifest.get("schema_version")) is int
            and isinstance(manifest.get("code_version"), str)
            and isinstance(manifest.get("logical_digest"), str)
            and SHA256_HEX.fullmatch(manifest["logical_digest"])
            and isinstance(manifest.get("files"), dict)
            and BACKUP_LEDGER_NAME in manifest["files"]
            and all(valid_file_entry(name, entry) for name, entry in manifest["files"].items())):
        raise BackupNotIntact(f"{MANIFEST_NAME} is not a manifest this code wrote")
    return manifest


def valid_file_entry(name, entry) -> bool:
    return ((name == BACKUP_LEDGER_NAME or ORIGINAL_IN_BACKUP.fullmatch(name) is not None)
            and isinstance(entry, dict) and set(entry) == {"sha256", "size"}
            and isinstance(entry["sha256"], str) and SHA256_HEX.fullmatch(entry["sha256"])
            and type(entry["size"]) is int)


def lstat_mode(path: Path) -> int:
    try:
        return os.lstat(path).st_mode
    except OSError:
        return 0


def names_in_backup(backup_folder: Path) -> set[str]:
    """Every file in the folder but the manifest, with originals as `originals/<name>`."""
    names = set()
    for entry_name in os.listdir(backup_folder):
        if entry_name == MANIFEST_NAME:
            continue
        if entry_name == ORIGINALS_FOLDER_NAME:
            originals_copy = backup_folder / ORIGINALS_FOLDER_NAME
            if not stat.S_ISDIR(lstat_mode(originals_copy)):
                raise BackupNotIntact(f"{ORIGINALS_FOLDER_NAME} is not a folder")
            names.update(f"{ORIGINALS_FOLDER_NAME}/{name}" for name in os.listdir(originals_copy))
        else:
            names.add(entry_name)
    return names


def refuse_unless_matches(path: Path, name: str, expected: dict) -> None:
    content = read_regular_file(path)
    if content is None:
        raise BackupNotIntact(f"{name} is not a regular file")
    if len(content) != expected["size"] or sha256_of(content) != expected["sha256"]:
        raise BackupNotIntact(f"{name} does not match the manifest")


def check_backup(backup_folder: Path) -> CheckedBackup:
    """Every check a restore runs, on the backup where it is: every file the manifest names and
    nothing else, then the ledger's integrity, foreign keys, schema version and logical digest."""
    manifest = read_manifest(backup_folder)
    found_names = names_in_backup(backup_folder)
    missing_names = sorted(set(manifest["files"]) - found_names)
    if missing_names:
        raise BackupNotIntact(f"{missing_names[0]} is missing")
    unlisted_names = sorted(found_names - set(manifest["files"]))
    if unlisted_names:
        raise BackupNotIntact(f"{unlisted_names[0]} is not in the manifest")
    for name, expected in sorted(manifest["files"].items()):
        refuse_unless_matches(backup_folder / name, name, expected)
    check_ledger_copy(backup_folder / BACKUP_LEDGER_NAME, manifest)
    byte_count = sum(entry["size"] for entry in manifest["files"].values())
    return CheckedBackup(manifest, byte_count + lstat_size(backup_folder / MANIFEST_NAME))


def lstat_size(path: Path) -> int:
    return os.lstat(path).st_size


def check_ledger_copy(ledger_path: Path, manifest: dict) -> None:
    """The checks a copied ledger must pass, opened read-only and immutable, so nothing is written
    beside it."""
    conn = sqlite3.connect(f"{ledger_path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError:
            integrity = None
        if integrity != [("ok",)]:
            raise BackupNotIntact(f"{BACKUP_LEDGER_NAME} fails SQLite's integrity check")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupNotIntact(f"{BACKUP_LEDGER_NAME} fails SQLite's foreign key check")
        copied_version, latest = schema_version(conn), len(load_migrations())
        if copied_version != manifest["schema_version"]:
            raise BackupNotIntact(
                f"{BACKUP_LEDGER_NAME}'s schema version differs from the manifest's")
        if copied_version > latest:
            raise BackupNotIntact(
                f"{BACKUP_LEDGER_NAME} uses schema version {copied_version}, which is newer than "
                f"this code ({latest})"
            )
        if logical_digest(conn) != manifest["logical_digest"]:
            raise BackupNotIntact(
                f"{BACKUP_LEDGER_NAME}'s logical digest differs from the manifest's")
        if is_real_ledger(conn) != manifest["real_ledger"]:
            raise BackupNotIntact(f"whether {BACKUP_LEDGER_NAME} is real differs from the manifest")
        referenced_names = {f"{ORIGINALS_FOLDER_NAME}/{original.content_sha256}"
                            for original in referenced_originals(conn)}
        if not manifest["real_ledger"]:
            referenced_names = set()
        if referenced_names != set(manifest["files"]) - {BACKUP_LEDGER_NAME}:
            raise BackupNotIntact(
                f"the originals differ from the documents {BACKUP_LEDGER_NAME} references")
    finally:
        conn.close()


# Restoring a backup.

def restore_backup(backup_folder: Path, database_path: Path) -> CheckedBackup:
    """Restore to database_path, which must not exist, with a real ledger's originals beside it.
    The backup is checked, then the written copies are checked again, and any failure removes
    everything written."""
    database_path = Path(os.path.abspath(database_path))
    if os.path.lexists(database_path):
        raise BackupRefused(f"a restore never overwrites, and {database_path} already exists")
    checked = check_backup(backup_folder)
    folder = database_path.parent
    originals_folder = folder / ORIGINALS_FOLDER_NAME
    if checked.is_real:
        try:
            refuse_unsafe_real_ledger_location(database_path)
        except UnsafeLocation as refusal:
            raise BackupRefused(f"the restore destination is refused: {refusal}") from None
        if os.path.lexists(originals_folder):
            raise BackupRefused(
                f"{originals_folder} already exists, and a restored ledger never shares another "
                "ledger's originals"
            )
    elif not folder.is_dir():
        raise BackupRefused(f"the folder for the restored ledger must already exist: {folder}")

    files = checked.manifest["files"]
    partial_path = folder / f".{database_path.name}.{uuid.uuid4().hex}.partial"
    written = []
    try:
        if checked.original_names:
            originals_folder.mkdir(mode=0o700)
            written.append(originals_folder)
            for name in checked.original_names:
                write_new_file(folder / name, read_regular_file(backup_folder / name),
                               final_mode=0o400)
                refuse_unless_matches(folder / name, name, files[name])
            sync_folder(originals_folder)
        write_new_file(partial_path, read_regular_file(backup_folder / BACKUP_LEDGER_NAME),
                       final_mode=0o600)
        written.append(partial_path)
        refuse_unless_matches(partial_path, BACKUP_LEDGER_NAME, files[BACKUP_LEDGER_NAME])
        check_ledger_copy(partial_path, checked.manifest)
        os.link(partial_path, database_path)
        written.append(database_path)
        partial_path.unlink()
        written.remove(partial_path)
        sync_folder(folder)
    except BaseException:
        for path in reversed(written):
            remove_written(path)
        raise
    return checked
