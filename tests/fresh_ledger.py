"""A new, fully migrated synthetic ledger for test setup, copied from one built once per process.

Building a ledger replays every migration, about 40 ms; writing a copy of a built one takes about
1 ms, and the suite builds thousands. Use this only where a test needs a ledger to exist. Tests of
creation itself (`pf init`, `create_database`, migrations, `init --real`) build theirs the real
way. test_migrations.py checks that a copy matches a ledger made by `create_database`.
"""

import os
import tempfile
from pathlib import Path

from personal_finance.db.migrate import create_database

_migrated_ledger_bytes: bytes | None = None


def migrated_ledger_bytes() -> bytes:
    """The bytes of a ledger made by `create_database` with the current migrations."""
    global _migrated_ledger_bytes
    if _migrated_ledger_bytes is None:
        with tempfile.TemporaryDirectory() as folder:
            template_path = Path(folder) / "template.db"
            create_database(template_path)
            _migrated_ledger_bytes = template_path.read_bytes()
    return _migrated_ledger_bytes


def create_fresh_ledger(path: Path) -> None:
    """Write a new migrated ledger at path, readable only by its owner, as `create_database`
    does. An existing file is an error, never overwritten."""
    file_descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(file_descriptor, "wb") as ledger_file:
        ledger_file.write(migrated_ledger_bytes())
