"""Backup, verification and restore (R1 to R5, D-058 points 7 and 8, point 7 as amended).

A real ledger lives in the `vault` fixture's folder on the synthetic volume /Volumes/SyntheticLedger,
and the `backups` fixture's folder is on a second synthetic encrypted volume,
/Volumes/SyntheticBackups. Both are answered with recordings, so no volume is mounted. Every
document is synthetic.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_balance_observations import BalanceLedger
from test_confirmations import confirm_ok
from test_decisions import (
    ALL_TABLES,
    BACKUP_TABLES,
    CAFE,
    CATEGORIZATION_TABLES,
    CATEGORY_TABLES,
    CHECKING_HEADER,
    FIRST_HALF,
    OTHER,
    REAL_LEDGER_TABLES,
    SECOND_HALF,
    Ledger,
)
from test_real_ledger import RealLedger, probe_recording, vault  # noqa: F401, vault is a fixture
from test_resolutions import CAFE_NO_AMOUNT
from test_supersession import holding
from test_transfers import IN_ROW, OUT_ROW, rows_of

import personal_finance
from personal_finance import cli
from personal_finance.db import backups, real_ledger, volume_probes
from personal_finance.db.backups import logical_digest
from personal_finance.db.migrate import connect, load_migrations

LATEST = len(load_migrations())
LEDGER_TABLES = (*ALL_TABLES, "account", "import_run", *REAL_LEDGER_TABLES, *BACKUP_TABLES,
                 *CATEGORY_TABLES, *CATEGORIZATION_TABLES)
LEDGER_VOLUME = Path("/Volumes/SyntheticLedger")
BACKUP_VOLUME = Path("/Volumes/SyntheticBackups")


def pf(capsys, *words):
    capsys.readouterr()
    code = cli.main([str(word) for word in words])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(folder):
    """Every path under folder with its bytes, so a test sees anything written or removed."""
    found = {}
    for path in sorted(folder.rglob("*")):
        found[str(path.relative_to(folder))] = (
            "link" if path.is_symlink() else "folder" if path.is_dir() else path.read_bytes())
    return found


def digest_of(path):
    conn = connect(path)
    found = logical_digest(conn)
    conn.close()
    return found


@pytest.fixture
def backups_folder(vault, tmp_path, monkeypatch):
    """A private folder on a second encrypted disk image. Every other folder stays on the ledger's
    volume."""
    folder = tmp_path / "backups"
    folder.mkdir(mode=0o700)
    folder.chmod(0o700)
    recordings = {LEDGER_VOLUME: probe_recording("encrypted_disk_image"),
                  BACKUP_VOLUME: probe_recording("encrypted_backup_disk_image")}

    def mount_point(path):
        return BACKUP_VOLUME if path == folder or folder in path.parents else LEDGER_VOLUME

    monkeypatch.setattr(real_ledger, "mount_point_containing", mount_point)
    monkeypatch.setattr(volume_probes, "diskutil_info_plist",
                        lambda asked: (0, recordings[asked]))
    return folder


class RealBackupLedger(RealLedger, BalanceLedger):
    pass


def real_with_two_documents(vault, capsys):
    ledger = RealBackupLedger(vault, capsys)
    ledger.card("jan.csv", CAFE)
    ledger.card("mar.csv", OTHER)
    return ledger


def created(ledger, backup_folder):
    code, out, err = ledger.run("backup", "create", "--to", str(backup_folder))
    assert code == 0, err
    return out


def manifest_of(backup_folder):
    return json.loads((backup_folder / "manifest.json").read_text())


def writable(backup_folder):
    """Let a test change a backup as an outside process could."""
    for path in [backup_folder, *backup_folder.rglob("*")]:
        if not path.is_symlink():
            path.chmod(0o700 if path.is_dir() else 0o600)


def rewrite_manifest(backup_folder, *, digest=False, **changes):
    """Make the manifest's hashes and sizes match the files again, and its digest too when asked,
    so that only the change under test differs."""
    writable(backup_folder)
    manifest = manifest_of(backup_folder)
    for name in manifest["files"]:
        path = backup_folder / name
        if path.is_file() and not path.is_symlink():
            manifest["files"][name] = {"sha256": sha256_of(path), "size": path.stat().st_size}
    if digest:
        conn = sqlite3.connect(backup_folder / "ledger.db")
        manifest["logical_digest"] = logical_digest(conn)
        conn.close()
    manifest.update(changes)
    (backup_folder / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))


def change_ledger_copy(backup_folder, *statements):
    writable(backup_folder)
    conn = sqlite3.connect(backup_folder / "ledger.db", isolation_level=None)
    conn.execute("PRAGMA foreign_keys = OFF")
    for statement in statements:
        conn.execute(statement)
    conn.close()


class TestCreate:
    """R1 and R2."""

    def test_a_real_ledger_is_backed_up_into_a_new_folder_on_another_volume(
            self, vault, backups_folder, capsys):
        ledger = real_with_two_documents(vault, capsys)
        digest_before = digest_of(ledger.path)
        backup_folder = backups_folder / "first"
        out = created(ledger, backup_folder)

        manifest = manifest_of(backup_folder)
        originals = sorted(os.listdir(vault / "originals"))
        assert sorted(os.listdir(backup_folder)) == ["ledger.db", "manifest.json", "originals"]
        assert sorted(os.listdir(backup_folder / "originals")) == originals
        for name in originals:
            copy = backup_folder / "originals" / name
            assert copy.read_bytes() == (vault / "originals" / name).read_bytes()
            assert stat.S_IMODE(copy.lstat().st_mode) == 0o400
        for path, mode in ((backup_folder, 0o700), (backup_folder / "originals", 0o700),
                           (backup_folder / "ledger.db", 0o400),
                           (backup_folder / "manifest.json", 0o400)):
            assert stat.S_IMODE(path.lstat().st_mode) == mode
        size = sum(path.stat().st_size for path in backup_folder.rglob("*") if path.is_file())
        assert out.splitlines() == [
            f"Backup written to {backup_folder}",
            "Ledger: real, with 2 originals",
            f"Files: {size} bytes in 4 files, each matching the manifest",
            "SQLite integrity and foreign key checks: ok",
            f"Schema version: {LATEST}",
            f"Logical digest: {manifest['logical_digest']}, matching the manifest",
            f"Recorded in the ledger. To check it later, run: pf backup verify --from "
            f"{backup_folder}",
        ]
        assert manifest["logical_digest"] == digest_before

    def test_the_manifest_holds_hashes_sizes_versions_and_the_digest(  # R2
            self, vault, backups_folder, capsys):
        ledger = real_with_two_documents(vault, capsys)
        digest_before = digest_of(ledger.path)
        backup_folder = backups_folder / "first"
        created(ledger, backup_folder)
        manifest = manifest_of(backup_folder)
        assert set(manifest) == {"format", "real_ledger", "schema_version", "code_version",
                                 "logical_digest", "files"}
        assert (manifest["format"], manifest["real_ledger"], manifest["schema_version"],
                manifest["code_version"]) == (1, True, LATEST, personal_finance.__version__)
        assert manifest["logical_digest"] == digest_before
        files = [backup_folder / "ledger.db", *sorted((backup_folder / "originals").iterdir())]
        assert manifest["files"] == {
            str(path.relative_to(backup_folder)): {"sha256": sha256_of(path),
                                                   "size": path.stat().st_size}
            for path in files}

    def test_only_referenced_originals_are_copied(self, vault, backups_folder, capsys):
        ledger = real_with_two_documents(vault, capsys)
        (vault / "originals").chmod(0o700)
        (vault / "originals" / "stray").write_bytes(b"synthetic stray")
        created(ledger, backups_folder / "first")
        assert "stray" not in os.listdir(backups_folder / "first" / "originals")

    def test_it_is_recorded_after_the_copy(self, vault, backups_folder, capsys):
        ledger = real_with_two_documents(vault, capsys)
        created(ledger, backups_folder / "first")
        created(ledger, backups_folder / "second")
        conn = ledger.conn()
        recorded = conn.execute(
            "SELECT backup_folder, byte_count, file_count FROM backup_record ORDER BY created_at"
        ).fetchall()
        conn.close()
        sizes = [sum(path.stat().st_size for path in (backups_folder / name).rglob("*")
                     if path.is_file()) for name in ("first", "second")]
        assert recorded == [(str(backups_folder / "first"), sizes[0], 4),
                            (str(backups_folder / "second"), sizes[1], 4)]
        first_copy = sqlite3.connect(backups_folder / "first" / "ledger.db")
        second_copy = sqlite3.connect(backups_folder / "second" / "ledger.db")
        assert first_copy.execute("SELECT COUNT(*) FROM backup_record").fetchone() == (0,)
        assert second_copy.execute("SELECT backup_folder FROM backup_record").fetchall() == [
            (str(backups_folder / "first"),)]
        first_copy.close()
        second_copy.close()

    def test_a_synthetic_ledger_is_backed_up_anywhere_without_probes(self, tmp_path, capsys,
                                                                    monkeypatch):
        def refuse_to_ask(*arguments):
            raise AssertionError("a synthetic ledger's backup asks no probe")

        monkeypatch.setattr(volume_probes, "diskutil_info_plist", refuse_to_ask)
        monkeypatch.setattr(volume_probes, "hdiutil_info_plist", refuse_to_ask)
        ledger = Ledger(tmp_path, capsys)
        ledger.card("jan.csv", CAFE)
        out = created(ledger, tmp_path / "backup")
        assert "Ledger: synthetic, with no originals" in out
        assert sorted(os.listdir(tmp_path / "backup")) == ["ledger.db", "manifest.json"]
        assert manifest_of(tmp_path / "backup")["real_ledger"] is False


class TestCreateRefusals:
    """R1: refused, writing nothing."""

    def refused(self, ledger, backup_folder, message, watched_folder):
        before = (ledger.dump(LEDGER_TABLES), snapshot(watched_folder))
        code, out, err = ledger.run("backup", "create", "--to", str(backup_folder))
        assert (code, out) == (2, ""), err
        assert message in err
        assert (ledger.dump(LEDGER_TABLES), snapshot(watched_folder)) == before

    @pytest.mark.parametrize("existing", ["folder", "file", "link"])
    def test_an_existing_folder_file_or_link(self, vault, backups_folder, capsys, existing):
        ledger = real_with_two_documents(vault, capsys)
        backup_folder = backups_folder / "first"
        if existing == "folder":
            backup_folder.mkdir()
        elif existing == "file":
            backup_folder.write_bytes(b"")
        else:
            backup_folder.symlink_to(backups_folder / "elsewhere")
        self.refused(ledger, backup_folder, "a backup is always a new folder", backups_folder)

    def test_an_existing_folder_on_a_synthetic_ledger(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        (tmp_path / "backup").mkdir()
        self.refused(ledger, tmp_path / "backup", "a backup is always a new folder", tmp_path)

    def test_the_ledgers_own_volume(self, vault, backups_folder, capsys, tmp_path):
        ledger = real_with_two_documents(vault, capsys)
        beside = tmp_path / "beside"
        beside.mkdir(mode=0o700)
        beside.chmod(0o700)
        self.refused(ledger, beside / "first",
                     f"a backup must be on a mounted volume other than the ledger's, and "
                     f"{beside / 'first'} is on {LEDGER_VOLUME}", tmp_path)

    def test_a_control_on_another_volume_succeeds(self, vault, backups_folder, capsys):
        ledger = real_with_two_documents(vault, capsys)
        created(ledger, backups_folder / "first")

    def make_missing_parent(self, backups_folder, monkeypatch):
        return backups_folder / "absent" / "first", "the folder for a real ledger must already exist"

    def make_shared(self, backups_folder, monkeypatch):
        backups_folder.chmod(0o750)
        return backups_folder / "first", f"Run: chmod 700 {backups_folder}"

    def make_git_work_tree(self, backups_folder, monkeypatch):
        (backups_folder / ".git").mkdir()
        return backups_folder / "first", "cannot be inside a git work tree"

    def make_link(self, backups_folder, monkeypatch):
        link = backups_folder.parent / "linked_backups"
        link.symlink_to(backups_folder)
        return link / "first", "cannot be reached through a symbolic link"

    def make_synced(self, backups_folder, monkeypatch):
        monkeypatch.setenv("HOME", str(backups_folder.parent))
        synced = backups_folder.parent / "Dropbox"
        backups_folder.rename(synced)
        synced.chmod(0o700)
        return synced / "first", "cannot be inside a synced folder"

    def make_unencrypted(self, backups_folder, monkeypatch):
        recording = probe_recording("unencrypted_disk_image").replace(
            b"/Volumes/SyntheticLedger", str(BACKUP_VOLUME).encode())
        answers = {LEDGER_VOLUME: probe_recording("encrypted_disk_image"),
                   BACKUP_VOLUME: recording}
        monkeypatch.setattr(volume_probes, "diskutil_info_plist", lambda asked: (0, answers[asked]))
        return backups_folder / "first", f"hdiutil does not show exactly one disk image holding {BACKUP_VOLUME}"

    def make_probe_failure(self, backups_folder, monkeypatch):
        answers = {LEDGER_VOLUME: (0, probe_recording("encrypted_disk_image")),
                   BACKUP_VOLUME: (1, b"")}
        monkeypatch.setattr(volume_probes, "diskutil_info_plist", lambda asked: answers[asked])
        return backups_folder / "first", f"diskutil could not describe {BACKUP_VOLUME}"

    @pytest.mark.parametrize("unsafe", [make_missing_parent, make_shared, make_git_work_tree,
                                        make_link, make_synced, make_unencrypted,
                                        make_probe_failure])
    def test_an_unsafe_destination(self, vault, backups_folder, capsys, monkeypatch, tmp_path,
                                   unsafe):
        ledger = real_with_two_documents(vault, capsys)
        backup_folder, message = unsafe(self, backups_folder, monkeypatch)
        self.refused(ledger, backup_folder, message, tmp_path)
        assert "the backup destination is refused" in ledger.run(
            "backup", "create", "--to", str(backup_folder))[2]

    @pytest.mark.parametrize("damage", ["missing", "altered"])
    def test_a_missing_or_altered_original(self, vault, backups_folder, capsys, damage):
        ledger = real_with_two_documents(vault, capsys)
        originals = vault / "originals"
        originals.chmod(0o700)
        victim = originals / sorted(os.listdir(originals))[0]
        if damage == "missing":
            victim.unlink()
        else:
            victim.chmod(0o600)
            victim.write_bytes(b"synthetic altered bytes")
        message = (f"{1 if damage == 'missing' else 0} originals are missing and "
                   f"{1 if damage == 'altered' else 0} altered, so nothing was backed up. "
                   "Run pf archive verify")
        self.refused(ledger, backups_folder / "first", message, backups_folder)

    def test_an_original_changing_while_copied_removes_the_folder(
            self, vault, backups_folder, capsys, monkeypatch):
        ledger = real_with_two_documents(vault, capsys)
        read = backups.read_regular_file

        def altered_original(path):
            content = read(path)
            return content + b"x" if path.parent == vault / "originals" else content

        monkeypatch.setattr(backups, "read_regular_file", altered_original)
        self.refused(ledger, backups_folder / "first", "changed while it was backed up",
                     backups_folder)

    def test_a_failed_write_removes_the_folder(self, vault, backups_folder, capsys, monkeypatch):
        ledger = real_with_two_documents(vault, capsys)
        write = backups.write_new_file

        def disk_full_at_the_manifest(path, content, *, final_mode):
            if path.name == "manifest.json":
                raise OSError("synthetic: the disk is full")
            write(path, content, final_mode=final_mode)

        monkeypatch.setattr(backups, "write_new_file", disk_full_at_the_manifest)
        self.refused(ledger, backups_folder / "first", "an unexpected problem", backups_folder)

    def test_a_busy_ledger_at_recording_removes_the_folder(self, vault, backups_folder, capsys,
                                                           monkeypatch):
        ledger = real_with_two_documents(vault, capsys)

        def busy(conn, backup_folder, checked):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(backups, "record_backup", busy)
        self.refused(ledger, backups_folder / "first", "database is busy", backups_folder)

    def test_a_backup_failing_its_check_removes_the_folder(self, vault, backups_folder, capsys,
                                                          monkeypatch):
        ledger = real_with_two_documents(vault, capsys)
        digests = iter(["0" * 64, "1" * 64])
        monkeypatch.setattr(backups, "logical_digest", lambda conn: next(digests))
        self.refused(ledger, backups_folder / "first",
                     "the backup is not intact: ledger.db's logical digest differs", backups_folder)


class TestStorage:
    def test_recorded_backups_are_reported_as_written(self, vault, backups_folder, capsys):
        ledger = real_with_two_documents(vault, capsys)
        created(ledger, backups_folder / "first")
        created(ledger, backups_folder / "second")
        conn = ledger.conn()
        recorded = conn.execute(
            "SELECT created_at, backup_folder, byte_count, file_count FROM backup_record "
            "ORDER BY created_at").fetchall()
        conn.close()
        total = sum(row[2] for row in recorded)
        lines = ledger.run("storage")[1].splitlines()
        assert lines[3:] == [
            f"Backups: {total} bytes in 8 files in 2 recorded, as written; their volumes are not "
            "read",
            *(f"  {created_at} {folder}: {size} bytes in {files} files"
              for created_at, folder, size, files in recorded),
        ]
        shutil.rmtree(backups_folder / "first", ignore_errors=True)
        assert ledger.run("storage")[1].splitlines()[3:] == lines[3:]


def intact_backup(vault, backups_folder, capsys):
    ledger = real_with_two_documents(vault, capsys)
    backup_folder = backups_folder / "first"
    created(ledger, backup_folder)
    return ledger, backup_folder


def remove_ledger_copy(folder):
    (folder / "ledger.db").unlink()


def remove_an_original(folder):
    (folder / "originals" / sorted(os.listdir(folder / "originals"))[0]).unlink()


def remove_the_manifest(folder):
    (folder / "manifest.json").unlink()


def add_a_stray_file(folder):
    (folder / "stray").write_bytes(b"")


def add_a_stray_original(folder):
    (folder / "originals" / ("0" * 64)).write_bytes(b"")


def alter_the_ledger_copy(folder):
    content = bytearray((folder / "ledger.db").read_bytes())
    content[-1] ^= 1
    (folder / "ledger.db").write_bytes(bytes(content))


def alter_an_original(folder):
    (folder / "originals" / sorted(os.listdir(folder / "originals"))[0]).write_bytes(b"x")


def link_an_original(folder):
    original = folder / "originals" / sorted(os.listdir(folder / "originals"))[0]
    original.rename(folder.parent / "moved")
    original.symlink_to(folder.parent / "moved")


def corrupt_a_page(folder):
    path = folder / "ledger.db"
    content = bytearray(path.read_bytes())
    page_size = int.from_bytes(content[16:18], "big")
    for offset in range(page_size * 3 + 8, page_size * 3 + 200):
        content[offset] = 0xFF
    path.write_bytes(bytes(content))
    rewrite_manifest(folder)


def break_a_foreign_key(folder):
    change_ledger_copy(folder, "INSERT INTO balance_observation (id, account_id, observed_on, "
                               "balance_cents) VALUES ('synthetic', 'no such account', "
                               "'2026-01-31', 0)")
    rewrite_manifest(folder)


def change_a_row(folder):
    change_ledger_copy(folder, "INSERT INTO balance_observation (id, account_id, observed_on, "
                               "balance_cents) SELECT 'synthetic', id, '2026-01-31', 0 FROM account")
    rewrite_manifest(folder)


def make_the_schema_newer(folder):
    change_ledger_copy(folder, f"PRAGMA user_version = {LATEST + 1}")
    rewrite_manifest(folder, digest=True, schema_version=LATEST + 1)


def misstate_the_schema_version(folder):
    rewrite_manifest(folder, schema_version=LATEST - 1)


def misstate_the_mark(folder):
    rewrite_manifest(folder, real_ledger=False)


def drop_an_original_from_the_manifest(folder):
    remove_an_original(folder)
    writable(folder)
    manifest = manifest_of(folder)
    del manifest["files"][next(name for name in manifest["files"] if name != "ledger.db")]
    (folder / "manifest.json").write_text(json.dumps(manifest))


def garble_the_manifest(folder):
    (folder / "manifest.json").write_text("{not json")


def change_the_format(folder):
    rewrite_manifest(folder, format=2)


def no_change(folder):
    rewrite_manifest(folder, digest=True)


NOT_INTACT = [
    (remove_ledger_copy, "ledger.db is missing"),
    (remove_an_original, "originals/"),
    (remove_the_manifest, "manifest.json is missing"),
    (add_a_stray_file, "stray is not in the manifest"),
    (add_a_stray_original, f"originals/{'0' * 64} is not in the manifest"),
    (alter_the_ledger_copy, "ledger.db does not match the manifest"),
    (alter_an_original, "does not match the manifest"),
    (link_an_original, "is not a regular file"),
    (corrupt_a_page, "ledger.db fails SQLite's integrity check"),
    (break_a_foreign_key, "ledger.db fails SQLite's foreign key check"),
    (make_the_schema_newer, f"ledger.db uses schema version {LATEST + 1}, which is newer than "
                            f"this code ({LATEST})"),
    (misstate_the_schema_version, "ledger.db's schema version differs from the manifest's"),
    (change_a_row, "ledger.db's logical digest differs from the manifest's"),
    (misstate_the_mark, "whether ledger.db is real differs from the manifest"),
    (drop_an_original_from_the_manifest, "the originals differ from the documents ledger.db "
                                         "references"),
    (garble_the_manifest, "manifest.json is not a manifest this code wrote"),
    (change_the_format, "manifest.json is not a manifest this code wrote"),
]


class TestVerify:
    """R3's checks, run by verify without restoring (R5)."""

    def test_an_intact_backup_passes_and_nothing_is_written(self, vault, backups_folder, capsys):
        _, backup_folder = intact_backup(vault, backups_folder, capsys)
        before = snapshot(backups_folder)
        code, out, err = pf(capsys, "backup", "verify", "--from", backup_folder)
        assert (code, err) == (0, "")
        assert out.splitlines()[0] == "Ledger: real, with 2 originals"
        assert out.endswith("The backup is intact.\n")
        assert snapshot(backups_folder) == before

    def test_the_helper_alone_changes_nothing_that_matters(self, vault, backups_folder, capsys):
        _, backup_folder = intact_backup(vault, backups_folder, capsys)
        no_change(backup_folder)
        assert pf(capsys, "backup", "verify", "--from", backup_folder)[0] == 0

    @pytest.mark.parametrize("damage, reason", NOT_INTACT,
                             ids=[damage.__name__ for damage, _ in NOT_INTACT])
    def test_a_damaged_backup_is_not_intact(self, vault, backups_folder, capsys, damage, reason):
        _, backup_folder = intact_backup(vault, backups_folder, capsys)
        writable(backup_folder)
        damage(backup_folder)
        before = snapshot(backups_folder)
        code, out, err = pf(capsys, "backup", "verify", "--from", backup_folder)
        assert (code, err) == (1, "")
        assert out.startswith("The backup is not intact: ") and out.endswith(".\n")
        assert reason in out
        assert snapshot(backups_folder) == before

    def test_a_folder_that_is_not_a_backup(self, tmp_path, capsys):
        code, out, _ = pf(capsys, "backup", "verify", "--from", tmp_path / "absent")
        assert code == 1 and "is not a backup folder" in out

    def test_a_synthetic_backup_with_an_originals_folder_holding_nothing_passes(
            self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        created(ledger, tmp_path / "backup")
        (tmp_path / "backup").chmod(0o700)
        (tmp_path / "backup" / "originals").mkdir()
        assert pf(capsys, "backup", "verify", "--from", tmp_path / "backup")[0] == 0


class TestRestore:
    """R3."""

    def restore_folder(self, tmp_path):
        folder = tmp_path / "restored"
        folder.mkdir(mode=0o700)
        folder.chmod(0o700)
        return folder

    def test_a_real_backup_restores_to_a_new_gated_path(self, vault, backups_folder, capsys,
                                                       tmp_path):
        ledger, backup_folder = intact_backup(vault, backups_folder, capsys)
        restored = self.restore_folder(tmp_path) / "ledger.db"
        code, out, err = pf(capsys, "backup", "restore", "--from", backup_folder, "--to", restored)
        assert (code, err) == (0, "")
        assert out.splitlines()[0] == f"Restored {restored} from {backup_folder}"
        assert sorted(os.listdir(restored.parent)) == ["ledger.db", "originals"]
        assert stat.S_IMODE(restored.stat().st_mode) == 0o600
        assert stat.S_IMODE((restored.parent / "originals").stat().st_mode) == 0o700
        for original in (restored.parent / "originals").iterdir():
            assert stat.S_IMODE(original.stat().st_mode) == 0o400
            assert original.read_bytes() == (vault / "originals" / original.name).read_bytes()
        code, out, _ = pf(capsys, "archive", "verify", "--db", restored)
        assert code == 0 and "Originals intact: 2" in out
        assert digest_of(restored) == manifest_of(backup_folder)["logical_digest"]

    def refused(self, capsys, backup_folder, restored, message, watched_folder):
        before = snapshot(watched_folder)
        code, out, err = pf(capsys, "backup", "restore", "--from", backup_folder, "--to", restored)
        assert (code, out) == (2, ""), err
        assert message in err
        assert snapshot(watched_folder) == before

    def test_an_existing_path(self, vault, backups_folder, capsys, tmp_path):
        _, backup_folder = intact_backup(vault, backups_folder, capsys)
        restored = self.restore_folder(tmp_path) / "ledger.db"
        restored.write_bytes(b"")
        self.refused(capsys, backup_folder, restored, "a restore never overwrites", tmp_path)

    def test_an_existing_originals_folder(self, vault, backups_folder, capsys, tmp_path):
        _, backup_folder = intact_backup(vault, backups_folder, capsys)
        folder = self.restore_folder(tmp_path)
        (folder / "originals").mkdir()
        self.refused(capsys, backup_folder, folder / "ledger.db",
                     "never shares another ledger's originals", tmp_path)

    @pytest.mark.parametrize("unsafe", ["shared", "git", "link", "unencrypted"])
    def test_an_unsafe_destination(self, vault, backups_folder, capsys, tmp_path, monkeypatch,
                                   unsafe):
        _, backup_folder = intact_backup(vault, backups_folder, capsys)
        folder = self.restore_folder(tmp_path)
        restored = folder / "ledger.db"
        if unsafe == "shared":
            folder.chmod(0o750)
        elif unsafe == "git":
            (folder / ".git").mkdir()
        elif unsafe == "link":
            (tmp_path / "linked").symlink_to(folder)
            restored = tmp_path / "linked" / "ledger.db"
        else:
            monkeypatch.setattr(volume_probes, "diskutil_info_plist",
                                lambda asked: (0, probe_recording("unencrypted_disk_image")))
        self.refused(capsys, backup_folder, restored, "the restore destination is refused",
                     tmp_path)

    @pytest.mark.parametrize("damage, reason", NOT_INTACT,
                             ids=[damage.__name__ for damage, _ in NOT_INTACT])
    def test_a_damaged_backup(self, vault, backups_folder, capsys, tmp_path, damage, reason):
        _, backup_folder = intact_backup(vault, backups_folder, capsys)
        writable(backup_folder)
        damage(backup_folder)
        folder = self.restore_folder(tmp_path)
        self.refused(capsys, backup_folder, folder / "ledger.db", reason, tmp_path)

    @pytest.mark.parametrize("failing_copy", ["ledger", "original"])
    def test_a_written_copy_failing_its_check_leaves_nothing(
            self, vault, backups_folder, capsys, tmp_path, monkeypatch, failing_copy):
        _, backup_folder = intact_backup(vault, backups_folder, capsys)
        folder = self.restore_folder(tmp_path)
        write = backups.write_new_file

        def damaged_write(path, content, *, final_mode):
            if (failing_copy == "ledger") == path.name.endswith(".partial"):
                content = content[:-1] + bytes([content[-1] ^ 1])
            write(path, content, final_mode=final_mode)

        monkeypatch.setattr(backups, "write_new_file", damaged_write)
        self.refused(capsys, backup_folder, folder / "ledger.db", "does not match the manifest",
                     tmp_path)

    def test_the_ledger_copy_is_checked_again_after_writing(
            self, vault, backups_folder, capsys, tmp_path, monkeypatch):
        _, backup_folder = intact_backup(vault, backups_folder, capsys)
        folder = self.restore_folder(tmp_path)
        checked_paths = []
        check = backups.check_ledger_copy

        def recorded_check(ledger_path, manifest):
            checked_paths.append(ledger_path)
            if ledger_path.parent == folder:
                raise backups.BackupNotIntact("synthetic: the written copy fails")
            check(ledger_path, manifest)

        monkeypatch.setattr(backups, "check_ledger_copy", recorded_check)
        self.refused(capsys, backup_folder, folder / "ledger.db", "synthetic: the written copy",
                     tmp_path)
        assert [path.parent for path in checked_paths] == [backup_folder, folder]

    def test_an_older_schema_restores_and_asks_for_migrate(self, tmp_path, capsys):
        ledger = BalanceLedger(tmp_path, capsys)
        ledger.card("jan.csv", CAFE)
        backup_folder = tmp_path / "backup"
        created(ledger, backup_folder)
        # The newest migration's tables, dropped, make the copy a ledger of the version before.
        newest = load_migrations()[-1].path.read_text()
        tables = reversed(re.findall(r"^CREATE TABLE (\w+)", newest, re.MULTILINE))
        change_ledger_copy(backup_folder, *(f"DROP TABLE {table}" for table in tables),
                           f"PRAGMA user_version = {LATEST - 1}")
        rewrite_manifest(backup_folder, digest=True, schema_version=LATEST - 1)
        restored = tmp_path / "restored.db"
        code, out, err = pf(capsys, "backup", "restore", "--from", backup_folder, "--to", restored)
        assert (code, err) == (0, "")
        assert f"Schema version: {LATEST - 1}, older than this code's {LATEST}" in out
        assert out.endswith(f"Before using it, run: pf migrate --db {restored}\n")
        assert pf(capsys, "totals", "--db", restored)[0] == 2
        assert pf(capsys, "migrate", "--db", restored)[0] == 0
        assert pf(capsys, "totals", "--db", restored)[0] == 0

    def test_a_synthetic_backup_restores_without_gates(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        ledger.card("jan.csv", CAFE)
        created(ledger, tmp_path / "backup")
        code, _, err = pf(capsys, "backup", "restore", "--from", tmp_path / "backup", "--to",
                          tmp_path / "restored.db")
        assert (code, err) == (0, "")
        assert not os.path.lexists(tmp_path / "originals")

    def test_a_synthetic_backup_needs_an_existing_folder(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        created(ledger, tmp_path / "backup")
        self.refused(capsys, tmp_path / "backup", tmp_path / "absent" / "restored.db",
                     "must already exist", tmp_path)


# R4: every report, list and token of a restored ledger matches the original's.

LISTS = [("documents",), ("transactions",), ("totals",), ("report", "monthly"),
         ("review", "list"), ("review", "merges"), ("review", "decisions"),
         ("review", "corrections"), ("review", "classifications"), ("review", "transfers"),
         ("review", "resolutions"), ("review", "coverage", "history"), ("balance", "list"),
         ("storage",), ("category", "list"), ("review", "categorizations")]
PER_ACCOUNT = [("totals",), ("report", "monthly"), ("review", "merges"), ("review", "decisions"),
               ("review", "corrections"), ("review", "classifications"), ("review", "transfers"),
               ("review", "resolutions"), ("review", "coverage", "history"),
               ("balance", "list"), ("balance", "check"), ("review", "categorizations")]
PER_ID = [
    ("SELECT id FROM ledger_transaction", [("trace",), ("review", "transaction", "show"),
                                           ("review", "merge", "show")]),
    ("SELECT id FROM review_issue", [("review", "show")]),
    ("SELECT id FROM source_document", [("review", "coverage", "show")]),
    ("SELECT id FROM decision", [("review", "decision", "show")]),
    ("SELECT id FROM value_correction", [("review", "correction", "show")]),
    ("SELECT id FROM type_classification", [("review", "classification", "show")]),
    ("SELECT id FROM transfer_match UNION ALL SELECT id FROM one_sided_transfer",
     [("review", "transfer", "show")]),
    ("SELECT id FROM record_resolution", [("review", "resolution", "show")]),
    ("SELECT id FROM category_assignment", [("review", "categorization", "show")]),
]


def everything_shown(ledger, ids_from):
    """Every list, report and show of the ledger, with token-bearing shows for every ID ids_from
    holds. The ledger's own path is the one thing allowed to differ."""
    conn = ids_from.conn()
    accounts = [name for (name,) in conn.execute("SELECT display_name FROM account")]
    ids = [(query, commands, [row[0] for row in conn.execute(query)])
           for query, commands in PER_ID]
    real = real_ledger.is_real_ledger(conn)
    conn.close()
    words_to_run = list(LISTS)
    words_to_run += [(*words, "--account", account) for words in PER_ACCOUNT
                     for account in accounts]
    words_to_run += [(*words, found_id) for _, commands, found_ids in ids
                     for words in commands for found_id in found_ids]
    if real:
        words_to_run.append(("archive", "verify"))
    shown = {}
    for words in words_to_run:
        code, out, err = ledger.run(*words)
        shown[words] = (code, out.replace(ledger.db, "LEDGER"), err.replace(ledger.db, "LEDGER"))
    return shown, sum(len(found_ids) for _, _, found_ids in ids)


def ledger_at(path, capsys, kind=BalanceLedger):
    ledger = kind.__new__(kind)
    ledger.folder, ledger.path, ledger.capsys, ledger.db, ledger.files = (
        path.parent, path, capsys, str(path), 0)
    return ledger


def assert_restored_alike(ledger, backup_folder, restored_path, capsys):
    """Restore, then compare everything shown, every table and every original with the original
    ledger as it was when backed up."""
    before = (everything_shown(ledger, ledger), ledger.dump(LEDGER_TABLES))
    created(ledger, backup_folder)
    code, _, err = pf(capsys, "backup", "restore", "--from", backup_folder, "--to", restored_path)
    assert (code, err) == (0, "")
    restored = ledger_at(restored_path, capsys)
    after = (everything_shown(restored, ledger), restored.dump(LEDGER_TABLES))
    assert after[1] == before[1]
    assert after[0][1] == before[0][1] > 0
    assert after[0][0] == before[0][0]
    return before[0][0]


def build_rich_ledger(ledger, *, checking_rows, decision, match, one_sided, correction,
                      resolution, declaration, balances):
    """Accounts A, S and T: random checking rows in A with random types, a candidate pair in S
    rejected, confirmed or left open, a match from A to S, a one-sided transfer from A to T, a
    correction, an unresolved record completed or dismissed, a declaration and observations."""
    ledger.add_account("S", "savings")
    ledger.add_account("T", "savings")
    lines = [f"R{index},2026-01-{day:02d},2026-01-{min(day + 2, 28):02d},SYNTHETIC ROW {index},"
             f"{'' if money_in else '-'}{cents // 100}.{cents % 100:02d},POSTED"
             for index, (cents, money_in, _, day) in enumerate(checking_rows)]
    ledger.load_path(ledger.write("a.csv", CHECKING_HEADER, lines),
                     layout="synthetic_checking_v1")
    for transaction, (_, money_in, choice, _) in zip(rows_of(ledger, "a.csv"), checking_rows,
                                                     strict=True):
        financial_type = (None, "refund", "income")[choice] if money_in else (
            None, "purchase", "fee")[choice]
        if financial_type:
            ledger.classify_ok(transaction, financial_type)
        if financial_type in ("purchase", "fee", "refund"):
            code, _, err = ledger.run("review", "categorize", transaction, "--account", "A",
                                      "--revision", ledger.transaction_revision(transaction),
                                      "--category", "Food")
            assert code == 0, err
    if correction:
        ledger.correct_ok(rows_of(ledger, "a.csv")[0], "description", "SYNTHETIC CORRECTED")

    items_before = set(ledger.items())
    ledger.card("p1.csv", CAFE, extra=FIRST_HALF, account="S")
    ledger.card("p2.csv", CAFE, extra=SECOND_HALF, account="S")
    (item,) = set(ledger.items()) - items_before
    if decision == "reject":
        code, _, err = ledger.reject(item, tuple(ledger.transactions(item)), account="S")
        assert code == 0, err
    elif decision == "confirm":
        confirm_ok(ledger, item, tuple(ledger.transactions(item)), account="S")

    ledger.card("out.csv", OUT_ROW)
    ledger.card("in.csv", IN_ROW, account="S")
    if match:
        outflow = holding(ledger, "out.csv")
        ledger.classify_ok(outflow, "transfer")
        ledger.match_ok(outflow, holding(ledger, "in.csv"))
    if one_sided:
        ledger.card("one.csv", "01/15/2026,SYNTHETIC MOVE ONE,30.00,")
        transaction = holding(ledger, "one.csv")
        ledger.classify_ok(transaction, "transfer")
        ledger.one_sided_ok(transaction, "T")

    items_before = set(ledger.items())
    ledger.card("u.csv", CAFE_NO_AMOUNT)
    (unresolved,) = set(ledger.items()) - items_before
    if resolution == "complete":
        ledger.complete_ok(unresolved, amount="-6.50")
    elif resolution == "dismiss":
        ledger.dismiss_ok(unresolved)
    if declaration:
        ledger.declare_ok("out.csv", "complete", start="2026-01-10", end="2026-01-10",
                          basis="posting")
    day = date(2026, 1, 1)
    for step, balance in enumerate(balances):
        ledger.record_ok((day + timedelta(days=7 * step)).isoformat(), f"{balance}.00")


checking_rows = st.lists(st.tuples(st.integers(1, 9999), st.booleans(), st.integers(0, 2),
                                   st.integers(1, 26)), min_size=1, max_size=6)


@settings(max_examples=8, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])
@given(rows=checking_rows, decision=st.sampled_from(("open", "reject", "confirm")),
       match=st.booleans(), one_sided=st.booleans(), correction=st.booleans(),
       resolution=st.sampled_from(("open", "complete", "dismiss")), declaration=st.booleans(),
       balances=st.lists(st.integers(-500, 500), max_size=3))
def test_a_restored_ledger_shows_everything_alike_over_generated_ledgers(  # R4
        capsys, rows, decision, match, one_sided, correction, resolution, declaration, balances):
    with tempfile.TemporaryDirectory() as folder:
        ledger = BalanceLedger(Path(folder), capsys)
        build_rich_ledger(ledger, checking_rows=rows, decision=decision, match=match,
                          one_sided=one_sided, correction=correction, resolution=resolution,
                          declaration=declaration, balances=balances)
        shown = assert_restored_alike(ledger, Path(folder) / "backup",
                                      Path(folder) / "restored.db", capsys)
        assert any(out for code, out, _ in shown.values() if code == 0)


def test_a_restored_real_ledger_shows_everything_alike_with_its_originals(  # R4
        vault, backups_folder, capsys, tmp_path):
    ledger = RealBackupLedger(vault, capsys)
    build_rich_ledger(ledger, checking_rows=[(1250, False, 1, 3), (900, True, 2, 9)],
                      decision="confirm", match=True, one_sided=True, correction=True,
                      resolution="complete", declaration=True, balances=[100, -20])
    restored_folder = tmp_path / "restored"
    restored_folder.mkdir(mode=0o700)
    restored_folder.chmod(0o700)
    shown = assert_restored_alike(ledger, backups_folder / "first", restored_folder / "ledger.db",
                                  capsys)
    assert shown[("archive", "verify")][0] == 0
    originals = sorted(os.listdir(vault / "originals"))
    assert len(originals) == 7
    assert sorted(os.listdir(restored_folder / "originals")) == originals
    for name in originals:
        assert sha256_of(restored_folder / "originals" / name) == name


class TestLogicalDigest:
    def scratch(self, tmp_path, name, *statements):
        conn = sqlite3.connect(tmp_path / name, isolation_level=None)
        for statement in statements:
            conn.execute(statement)
        return conn

    def test_values_of_different_storage_classes_differ(self, tmp_path):
        digests = {logical_digest(self.scratch(tmp_path, f"{index}.db", "CREATE TABLE t (a)",
                                               f"INSERT INTO t VALUES ({value})"))
                   for index, value in enumerate(("1", "1.0", "'1'", "x'31'", "NULL"))}
        assert len(digests) == 5

    def test_row_order_on_disk_does_not_matter(self, tmp_path):
        first = self.scratch(tmp_path, "first.db", "CREATE TABLE t (a TEXT PRIMARY KEY)",
                             "CREATE TABLE u (b)",
                             "INSERT INTO t VALUES ('x'), ('y')", "INSERT INTO u VALUES (1), (2)")
        second = self.scratch(tmp_path, "second.db", "CREATE TABLE t (a TEXT PRIMARY KEY)",
                              "CREATE TABLE u (b)",
                              "INSERT INTO t VALUES ('y'), ('x')", "INSERT INTO u VALUES (2), (1)")
        assert logical_digest(first) == logical_digest(second)

    def test_a_changed_value_a_schema_object_or_the_version_changes_it(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        conn = ledger.conn()
        original = logical_digest(conn)
        conn.execute("UPDATE account SET institution = 'Synthetic'")
        changed_value = logical_digest(conn)
        conn.execute("DROP TRIGGER backup_record_no_update")
        changed_schema = logical_digest(conn)
        conn.execute("PRAGMA user_version = 99")
        changed_version = logical_digest(conn)
        conn.close()
        assert len({original, changed_value, changed_schema, changed_version}) == 4


class TestBackupRecordTable:
    def test_it_is_append_only_with_a_control(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        conn = ledger.conn()
        insert = ("INSERT INTO backup_record (id, backup_folder, byte_count, file_count, "
                  "logical_digest) VALUES ('b', '/synthetic', 10, 2, ?)")
        conn.execute(insert, ("0" * 64,))
        for statement, parameters in (("UPDATE backup_record SET byte_count = 11", ()),
                                      ("DELETE FROM backup_record", ()),
                                      (insert.replace("INSERT", "INSERT OR REPLACE"),
                                       ("1" * 64,))):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                conn.execute(statement, parameters)
        assert conn.execute("SELECT logical_digest FROM backup_record").fetchall() == [
            ("0" * 64,)]
        conn.close()


# R5: a backup taken while another connection writes is consistent.

def observation_writes(path, account_id, stop, digests, committed):
    """Each commit adds an observation and its event, and notes the ledger's digest as committed.
    The digest is read inside the write transaction, so no other commit falls between them."""
    conn = connect(path)
    day = date(2026, 1, 1)
    while not stop.is_set():
        conn.execute("BEGIN IMMEDIATE")
        observation_id = f"synthetic-{len(digests)}"
        conn.execute("INSERT INTO balance_observation (id, account_id, observed_on, balance_cents) "
                     "VALUES (?, ?, ?, 0)", (observation_id, account_id,
                                             (day + timedelta(days=len(digests))).isoformat()))
        conn.execute("INSERT INTO balance_observation_event (balance_observation_id, event) "
                     "VALUES (?, 'made')", (observation_id,))
        digests.append(logical_digest(conn))
        conn.execute("COMMIT")
        committed.release()
        time.sleep(0.01)  # As a person's commands would, leaving the lock free between writes.
    conn.close()


class TestConcurrentWrites:
    def test_a_backup_while_another_connection_commits_is_one_of_its_states(self, tmp_path,
                                                                           capsys):
        ledger = BalanceLedger(tmp_path, capsys)
        for index in range(20):
            ledger.card(f"m{index}.csv", f"01/{1 + index:02d}/2026,SYNTHETIC SHOP {index},1.00,")
        conn = ledger.conn()
        (account_id,) = conn.execute("SELECT id FROM account").fetchone()
        digests = [logical_digest(conn)]
        conn.close()
        stop, committed = threading.Event(), threading.Semaphore(0)
        writer = threading.Thread(target=observation_writes,
                                  args=(ledger.path, account_id, stop, digests, committed))
        writer.start()
        try:
            for _ in range(3):
                assert committed.acquire(timeout=30)
            backup_folder = tmp_path / "backup"
            created(ledger, backup_folder)
            for _ in range(3):
                assert committed.acquire(timeout=30)
        finally:
            stop.set()
            writer.join()

        assert pf(capsys, "backup", "verify", "--from", backup_folder)[0] == 0
        position = digests.index(manifest_of(backup_folder)["logical_digest"])
        assert 3 <= position <= len(digests) - 4
        copy = sqlite3.connect(backup_folder / "ledger.db")
        observations = copy.execute("SELECT COUNT(*) FROM balance_observation").fetchone()[0]
        events = copy.execute("SELECT COUNT(*) FROM balance_observation_event").fetchone()[0]
        copy.close()
        assert observations == events == position

    def test_an_uncommitted_write_is_not_in_the_backup(self, tmp_path, capsys, monkeypatch):
        ledger = BalanceLedger(tmp_path, capsys)
        ledger.card("jan.csv", CAFE)
        digest_before = digest_of(ledger.path)
        writer = connect(ledger.path)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE account SET institution = 'Synthetic'")
        check = backups.check_backup

        def commit_the_writer_first(backup_folder):
            writer.execute("COMMIT")
            return check(backup_folder)

        monkeypatch.setattr(backups, "check_backup", commit_the_writer_first)
        created(ledger, tmp_path / "backup")
        writer.close()
        assert manifest_of(tmp_path / "backup")["logical_digest"] == digest_before
        conn = ledger.conn()
        assert conn.execute("SELECT institution FROM account").fetchone() == ("Synthetic",)
        conn.close()
