"""Checks .gitignore with git itself, using paths that need not exist."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")


def is_ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", path],
        cwd=REPO,
        capture_output=True,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        "statement.csv",
        "statement.pdf",
        "statement.CSV",
        "statement.PDF",
        "export.tsv",
        "export.ofx",
        "export.qfx",
        "export.qif",
        "export.xlsx",
        "docs/statement.pdf",
        "src/personal_finance/export.csv",
        "tests/fixtures/real.csv",
        "tests/fixtures/real.pdf",
        "tests/unit/real.csv",
        "ledger.db",
        "ledger.db-journal",
        "ledger.db-wal",
        "ledger.db-shm",
        "ledger.sqlite",
        "ledger.sqlite3",
        "ledger.sqlite3-wal",
        "tests/fixtures/synthetic/ledger.db",
        "backup.zip",
        "ledger.bak",
        ".env",
        ".env.local",
        "private.pem",
        "data/anything.txt",
        "inbox/anything.txt",
        "imports/anything.txt",
        "statements/anything.txt",
        "archive/anything.txt",
        "backups/anything.txt",
        ".venv/bin/python",
        ".DS_Store",
    ],
)
def test_sensitive_paths_are_ignored(path):
    assert is_ignored(path)


@pytest.mark.parametrize(
    "path",
    [
        "tests/fixtures/synthetic/checking.csv",
        "tests/fixtures/synthetic/statement.pdf",
        "tests/fixtures/synthetic/overlap/card.csv",
        "tests/fixtures/synthetic/overlap/statement.pdf",
        "tests/fixtures/synthetic/README.md",
        "src/personal_finance/db/migrations/0001_initial.sql",
        "src/personal_finance/money.py",
        "docs/decisions.md",
        "requirements-dev.txt",
    ],
)
def test_project_files_are_not_ignored(path):
    assert not is_ignored(path)
