"""Database creation, connections and schema migrations.

The schema version lives in PRAGMA user_version. Each migration runs in one
transaction together with its version bump, so it applies fully or not at all.
"""

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_MIGRATION_NAME = re.compile(r"(?P<version>[0-9]{4})_[a-z0-9_]+\.sql")


class MigrationError(RuntimeError):
    """The migrations or the database version are not in a usable state."""


@dataclass(frozen=True)
class Migration:
    version: int
    path: Path


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Return migrations in order, requiring versions to run 1, 2, 3 and so on."""
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(f"invalid migration file name: {path.name}")
        migrations.append(Migration(int(match["version"]), path))

    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(f"expected migration {expected:04d}, found {migration.path.name}")
    return migrations


def connect(path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open an existing database. A missing file is an error, never a new ledger."""
    mode = "ro" if read_only else "rw"
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode={mode}", uri=True, autocommit=True)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def create_database(path: Path, migrations_dir: Path = MIGRATIONS_DIR) -> None:
    """Create a new database readable only by its owner and bring it up to date."""
    os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    conn = connect(path)
    try:
        migrate(conn, migrations_dir)
    finally:
        conn.close()


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> int:
    """Apply outstanding migrations and return the resulting schema version."""
    migrations = load_migrations(migrations_dir)
    latest = len(migrations)

    current = schema_version(conn)
    if current > latest:
        raise MigrationError(f"database version {current} is newer than this code ({latest})")

    for migration in migrations[current:]:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Another process may have applied this while we waited for the lock.
            if schema_version(conn) < migration.version:
                conn.executescript(migration.path.read_text(encoding="utf-8"))
                conn.execute(f"PRAGMA user_version = {migration.version}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return schema_version(conn)
