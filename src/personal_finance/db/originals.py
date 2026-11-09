"""Original documents a real ledger keeps, copied on import into `originals/` beside the database
(D-017, D-058 point 5, M5.3).

Each original is named by its SHA-256, written to a temporary name, synced, set `0400` and renamed
into place. Identity still comes from content and ledger records, never from this folder. Nothing
here deletes an original, and an existing one is never overwritten: a file already holding the
name is kept when its bytes match, and otherwise fails the import, so the change stays visible to
`archive verify`.
"""

import hashlib
import os
import sqlite3
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from personal_finance.db.real_ledger import UnsafeLocation, refuse_unless_private
from personal_finance.ingest.errors import ImportFailure

ORIGINALS_FOLDER_NAME = "originals"


def originals_folder_beside(database_path: Path) -> Path:
    return database_path.resolve().parent / ORIGINALS_FOLDER_NAME


def refuse_unsafe_originals_folder(originals_folder: Path) -> None:
    """D-058 point 2's rules for the folder itself: no symbolic link, owned by you, `0700`."""
    if originals_folder.is_symlink():
        raise UnsafeLocation(
            f"a real ledger's originals folder cannot be a symbolic link: {originals_folder}"
        )
    if not originals_folder.is_dir():
        raise UnsafeLocation(f"a real ledger's originals folder must be a folder: {originals_folder}")
    refuse_unless_private(originals_folder, private_mode="700")


def prepare_originals_folder(database_path: Path) -> Path:
    """The originals folder, created private when missing, and refused unless safe."""
    originals_folder = originals_folder_beside(database_path)
    if not originals_folder.exists() and not originals_folder.is_symlink():
        originals_folder.mkdir(mode=0o700)
    refuse_unsafe_originals_folder(originals_folder)
    return originals_folder


def archive_original(originals_folder: Path, content: bytes, content_sha256: str) -> None:
    """Keep these bytes as the original named content_sha256. Any failure is `archive_failed`."""
    original_path = originals_folder / content_sha256
    if os.path.lexists(original_path):
        if regular_file_sha256(original_path) != content_sha256:
            raise ImportFailure("archive_failed")
        return

    partial_path = originals_folder / f".{content_sha256}.{uuid.uuid4().hex}.partial"
    try:
        descriptor = os.open(partial_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600)
        with os.fdopen(descriptor, "wb") as partial_file:
            partial_file.write(content)
            partial_file.flush()
            os.fsync(partial_file.fileno())
        os.chmod(partial_path, 0o400)
        os.rename(partial_path, original_path)
        sync_folder(originals_folder)
    except OSError:
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass  # Left behind, it is listed as not referenced, never mistaken for an original.
        raise ImportFailure("archive_failed") from None


def sync_folder(folder: Path) -> None:
    descriptor = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def regular_file_sha256(path: Path) -> str | None:
    """The SHA-256 of a regular file, or None for a link, anything else, or a file that cannot be
    read."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        return None
    with os.fdopen(descriptor, "rb") as opened_file:
        return hashlib.file_digest(opened_file, "sha256").hexdigest()


@dataclass(frozen=True)
class ReferencedOriginal:
    content_sha256: str
    source_document_id: str


@dataclass(frozen=True)
class ArchiveVerification:
    intact: list[ReferencedOriginal]
    missing: list[ReferencedOriginal]
    altered: list[ReferencedOriginal]
    unreferenced_entry_names: list[str]

    @property
    def passed(self) -> bool:
        return not (self.missing or self.altered or self.unreferenced_entry_names)


def referenced_originals(conn: sqlite3.Connection) -> list[ReferencedOriginal]:
    return [
        ReferencedOriginal(content_sha256, source_document_id)
        for content_sha256, source_document_id in conn.execute(
            "SELECT content_sha256, id FROM source_document ORDER BY content_sha256"
        )
    ]


def entry_names_in(originals_folder: Path) -> list[str]:
    """Every name in the folder, or none when it does not exist yet. The folder must be safe."""
    if not os.path.lexists(originals_folder):
        return []
    refuse_unsafe_originals_folder(originals_folder)
    return sorted(os.listdir(originals_folder))


def verify_originals(conn: sqlite3.Connection, originals_folder: Path) -> ArchiveVerification:
    """Rehash every referenced original, and list every other entry as not referenced."""
    entry_names = set(entry_names_in(originals_folder))
    referenced = referenced_originals(conn)
    intact, missing, altered = [], [], []
    for original in referenced:
        original_path = originals_folder / original.content_sha256
        if original.content_sha256 not in entry_names:
            missing.append(original)
        elif regular_file_sha256(original_path) == original.content_sha256:
            intact.append(original)
        else:
            altered.append(original)
    referenced_names = {original.content_sha256 for original in referenced}
    return ArchiveVerification(intact, missing, altered, sorted(entry_names - referenced_names))
