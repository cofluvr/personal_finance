"""Storage by kind: software, database with its journal, originals and backups, each apart, in
bytes and files (PRD §20, D-058 point 6). Sizes are read without following links.
"""

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import personal_finance
from personal_finance.db.originals import entry_names_in, referenced_originals

# SQLite's files beside a database: its rollback journal, or a write-ahead log and its index.
DATABASE_FILE_SUFFIXES = ("", "-journal", "-wal", "-shm")


@dataclass(frozen=True)
class StoredFiles:
    byte_count: int = 0
    file_count: int = 0

    def __add__(self, other: "StoredFiles") -> "StoredFiles":
        return StoredFiles(self.byte_count + other.byte_count, self.file_count + other.file_count)


@dataclass(frozen=True)
class StorageByKind:
    software: StoredFiles
    database: StoredFiles
    referenced_originals: StoredFiles | None
    unreferenced_originals: StoredFiles | None


def stored_file(path: Path) -> StoredFiles:
    return StoredFiles(os.lstat(path).st_size, 1)


def software_files() -> StoredFiles:
    """Every file of the installed personal_finance package, bytecode caches included."""
    package_folder = Path(personal_finance.__file__).parent
    total = StoredFiles()
    for folder, _, file_names in os.walk(package_folder):
        for file_name in file_names:
            total += stored_file(Path(folder) / file_name)
    return total


def database_files(database_path: Path) -> StoredFiles:
    total = StoredFiles()
    for suffix in DATABASE_FILE_SUFFIXES:
        path = Path(f"{database_path}{suffix}")
        if os.path.lexists(path):
            total += stored_file(path)
    return total


def storage_by_kind(
    conn: sqlite3.Connection, database_path: Path, originals_folder: Path | None
) -> StorageByKind:
    """Originals are None for a synthetic ledger, which archives nothing."""
    referenced = unreferenced = None
    if originals_folder is not None:
        referenced_names = {original.content_sha256 for original in referenced_originals(conn)}
        referenced = unreferenced = StoredFiles()
        for entry_name in entry_names_in(originals_folder):
            entry = stored_file(originals_folder / entry_name)
            if entry_name in referenced_names:
                referenced += entry
            else:
                unreferenced += entry
    return StorageByKind(software_files(), database_files(database_path), referenced, unreferenced)
