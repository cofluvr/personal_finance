"""bin/prune-build removes only bulk files, and only outside the folders it keeps."""
import os
import subprocess
import sys
from pathlib import Path

PRUNE_BUILD = Path(__file__).resolve().parents[2] / "bin" / "prune-build"


def run_prune_build(build_directory: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PRUNE_BUILD), "--build-directory", str(build_directory), *arguments],
        capture_output=True, text=True, check=True)


def make_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    return path


def make_build_directory(tmp_path: Path) -> dict[str, Path]:
    build_directory = tmp_path / "build"
    files = {
        "old_ledger": make_file(build_directory / "m1" / "g6" / "ledgers" / "ledger.db"),
        "old_wal": make_file(build_directory / "m1" / "ledger.db-wal"),
        "old_cache_file": make_file(build_directory / "m1" / "breaks" / "cache" / "c01" / "x.txt"),
        "old_pytest_file": make_file(
            build_directory / "m1" / "tmp" / "pytest-of-someone" / "pytest-1" / "note.txt"),
        "old_script": make_file(build_directory / "m1" / "g6" / "capture.py"),
        "old_log": make_file(build_directory / "m1" / "gate.log"),
        "kept_ledger": make_file(build_directory / "ios" / "ledger.db"),
        "new_ledger": make_file(build_directory / "m2" / "ledger.db"),
        "worktree_ledger": make_file(build_directory / "wt-old" / "tests" / "fixture.db"),
    }
    make_file(build_directory / "wt-old" / ".git")
    for name, path in files.items():
        if name != "new_ledger":
            os.utime(path, (1_000_000, 1_000_000))
    os.utime(build_directory / "wt-old" / ".git", (1_000_000, 1_000_000))
    # A folder's own time is recent after files are removed from it; its files' times decide.
    os.utime(build_directory / "m2", (1_000_000, 1_000_000))
    files["build_directory"] = build_directory
    return files


def test_a_dry_run_removes_nothing(tmp_path):
    files = make_build_directory(tmp_path)

    result = run_prune_build(files["build_directory"], "--keep-newest", "1", "--keep", "ios")

    assert "Kept whole: ios, m2, wt-old\n" in result.stdout
    assert "Would remove 4 files" in result.stdout
    assert all(path.exists() for name, path in files.items())


def test_delete_removes_bulk_and_keeps_text_and_kept_folders(tmp_path):
    files = make_build_directory(tmp_path)

    run_prune_build(files["build_directory"], "--keep-newest", "1", "--keep", "ios", "--delete")

    for removed in ("old_ledger", "old_wal", "old_cache_file", "old_pytest_file"):
        assert not files[removed].exists(), removed
    for kept in ("old_script", "old_log", "kept_ledger", "new_ledger", "worktree_ledger"):
        assert files[kept].exists(), kept
    assert not (files["build_directory"] / "m1" / "breaks").exists()
    assert not (files["build_directory"] / "m1" / "g6" / "ledgers").exists()
