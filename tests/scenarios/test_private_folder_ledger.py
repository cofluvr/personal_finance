"""Private-folder real ledgers: the simpler protection, for a folder such as iCloud Drive (D-081).

`pf init --real --protection private-folder` accepts any existing folder you own outside a git work
tree, synced folders included, and asks no disk image anything. Every open makes the folder, the
database and the originals folder private again, as a sync client restores its own file modes on
each download, and refuses while a sync conflict's copy sits beside the ledger.

The `icloud_folder` fixture places the folder inside a synthetic home's iCloud Drive, treats a work
tree found above tmp_path as absent (as `vault` does), and makes every disk image probe fail the
test, so the suite proves none is asked.
"""

import os
import shutil
import sqlite3
from pathlib import Path

import pytest
from test_decisions import CAFE, CARD_HEADER
from test_real_ledger import (  # noqa: F401, the vault fixture
    COMMANDS,
    LEDGER_TABLES,
    SYNTHETIC_MOUNT_POINT,
    RealLedger,
    probe_recording,
    vault,
)
from test_snapshot_files import AS_OF
from test_transfer_migration import migrations_up_to

from personal_finance import cli
from personal_finance.db import real_ledger, volume_probes
from personal_finance.db.migrate import connect, create_database, migrate
from personal_finance.db.real_ledger import (
    ENCRYPTED_DISK_IMAGE,
    PRIVATE_FOLDER,
    git_work_tree_containing,
    mark_real_ledger,
    real_ledger_protection,
)

ICLOUD_DRIVE_UNDER_HOME = "Library/Mobile Documents/com~apple~CloudDocs"
PRIVATE_FOLDER_CREATED = "Created real ledger {path}, protected by its private folder\n"


def no_disk_image_is_asked(*_):
    raise AssertionError("a private-folder ledger asked a disk image probe")


@pytest.fixture
def icloud_folder(tmp_path, monkeypatch):
    """A folder in a synthetic home's iCloud Drive, with the modes a sync download leaves."""
    search_from_the_disk = git_work_tree_containing

    def work_tree_within_tmp_path(path):
        found = search_from_the_disk(path)
        if found is None or (found != tmp_path and tmp_path not in found.parents):
            return None
        return found

    monkeypatch.setattr(real_ledger, "git_work_tree_containing", work_tree_within_tmp_path)
    monkeypatch.setattr(real_ledger, "mount_point_containing", no_disk_image_is_asked)
    monkeypatch.setattr(volume_probes, "diskutil_info_plist", no_disk_image_is_asked)
    monkeypatch.setattr(volume_probes, "hdiutil_info_plist", no_disk_image_is_asked)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    folder = tmp_path / "home" / ICLOUD_DRIVE_UNDER_HOME / "Finance"
    folder.mkdir(parents=True)
    folder.chmod(0o755)
    return folder


class PrivateFolderLedger(RealLedger):
    """A ledger made by `init --real --protection private-folder`, with one card account A."""

    def __init__(self, folder, capsys, name="ledger.db"):
        self.folder = folder
        self.path = folder / name
        self.capsys = capsys
        self.db = str(self.path)
        self.files = 0
        code, out, err = self.run("init", "--real", "--protection", "private-folder")
        assert code == 0, err
        assert out.startswith(PRIVATE_FOLDER_CREATED.format(path=self.path))
        self.add_account("A")

    def protection(self):
        conn = connect(self.path)
        try:
            return real_ledger_protection(conn)
        finally:
            conn.close()


def init(capsys, path, *words):
    capsys.readouterr()
    code = cli.main(["init", "--db", str(path), *words])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def mode_of(path):
    return path.stat().st_mode & 0o777


class TestInit:
    def test_an_icloud_folder_is_accepted_and_made_private(self, icloud_folder, capsys):
        path = icloud_folder / "ledger.db"
        code, out, err = init(capsys, path, "--real", "--protection", "private-folder")
        assert (code, err) == (0, "")
        assert out.startswith(PRIVATE_FOLDER_CREATED.format(path=path))
        assert "one computer at a time" in out
        assert mode_of(icloud_folder) == 0o700
        assert mode_of(path) == 0o600
        conn = connect(path)
        assert real_ledger_protection(conn) == PRIVATE_FOLDER
        conn.close()

    def test_real_alone_still_means_an_encrypted_disk_image(self, icloud_folder, capsys):
        for words in (("--real",), ("--real", "--protection", "encrypted-disk-image")):
            code, _, err = init(capsys, icloud_folder / "ledger.db", *words)
            assert code == 2 and "inside a synced folder" in err
            assert not (icloud_folder / "ledger.db").exists()

    def test_protection_without_real_is_refused(self, icloud_folder, capsys):
        code, _, err = init(capsys, icloud_folder / "ledger.db", "--protection", "private-folder")
        assert code == 2 and "add --real" in err
        assert not (icloud_folder / "ledger.db").exists()

    def refused(self, capsys, path, message):
        code, _, err = init(capsys, path, "--real", "--protection", "private-folder")
        assert code == 2
        assert message in err
        assert not path.exists()

    def test_a_missing_folder(self, icloud_folder, capsys):
        self.refused(capsys, icloud_folder / "missing" / "ledger.db", "must already exist")

    def test_a_git_work_tree_above_the_folder(self, icloud_folder, capsys):
        (icloud_folder / ".git").mkdir()
        self.refused(capsys, icloud_folder / "ledger.db", "inside a git work tree")

    def test_a_folder_owned_by_someone_else(self, icloud_folder, capsys, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: icloud_folder.stat().st_uid + 1)
        self.refused(capsys, icloud_folder / "ledger.db", "must be owned by you")
        assert mode_of(icloud_folder) == 0o755

    def test_a_link_is_followed_and_its_target_checked(self, icloud_folder, capsys, tmp_path):
        link = tmp_path / "link"
        link.symlink_to(icloud_folder)
        code, _, err = init(capsys, link / "ledger.db", "--real", "--protection",
                            "private-folder")
        assert (code, err) == (0, "")
        assert (icloud_folder / "ledger.db").is_file()
        (tmp_path / "checkout").mkdir()
        (tmp_path / "checkout" / ".git").mkdir()
        (tmp_path / "into_checkout").symlink_to(tmp_path / "checkout")
        self.refused(capsys, tmp_path / "into_checkout" / "ledger.db", "inside a git work tree")


class TestTheProtection:
    def test_it_is_never_changed(self, icloud_folder, capsys):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        conn = connect(ledger.path)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(f"UPDATE real_ledger SET protection = '{ENCRYPTED_DISK_IMAGE}'")
        conn.close()
        assert ledger.protection() == PRIVATE_FOLDER

    def test_only_the_two_protections_are_stored(self, tmp_path):
        for name, protection, accepted in (("a.db", "none", False),
                                           ("b.db", PRIVATE_FOLDER, True)):
            create_database(tmp_path / name)
            conn = connect(tmp_path / name)
            if accepted:
                mark_real_ledger(conn, protection)
                assert real_ledger_protection(conn) == protection
            else:
                with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                    mark_real_ledger(conn, protection)
                assert real_ledger_protection(conn) is None
            conn.close()

    def test_a_real_ledger_made_before_0037_keeps_its_disk_image(self, tmp_path):
        path = tmp_path / "ledger.db"
        create_database(path, migrations_up_to(tmp_path / "thirty_six", 36))
        conn = connect(path)
        conn.execute("INSERT INTO real_ledger (only_row) VALUES (1)")
        assert real_ledger_protection(conn) == ENCRYPTED_DISK_IMAGE
        assert migrate(conn) == 37
        assert real_ledger_protection(conn) == ENCRYPTED_DISK_IMAGE
        conn.close()


def as_a_sync_download_leaves_it(ledger):
    ledger.folder.chmod(0o755)
    ledger.path.chmod(0o644)
    (ledger.folder / "originals").chmod(0o755)


class TestEveryOpen:
    @pytest.mark.parametrize("command", COMMANDS)
    def test_modes_a_sync_left_are_made_private_again(self, icloud_folder, capsys, command):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        ledger.card("jan.csv", CAFE)
        as_a_sync_download_leaves_it(ledger)
        code, _, err = ledger.run(*command)
        assert (code, err) == (0, "")
        assert mode_of(ledger.folder) == 0o700
        assert mode_of(ledger.path) == 0o600
        assert mode_of(ledger.folder / "originals") == 0o700

    @pytest.mark.parametrize("command", COMMANDS)
    def test_a_sync_conflicts_copy_refuses_every_open(self, icloud_folder, capsys, command):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        ledger.card("jan.csv", CAFE)
        shutil.copy2(ledger.path, icloud_folder / "ledger 2.db")
        before = ledger.everything()
        code, out, err = ledger.run(*command)
        assert code == 2 and out == ""
        assert "conflicting copy of this ledger beside it: ledger 2.db" in err
        assert ledger.everything() == before

    def test_the_copy_opens_and_the_ledger_opens_once_it_is_moved(self, icloud_folder, capsys,
                                                                  tmp_path):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        ledger.card("jan.csv", CAFE)
        shutil.copy2(ledger.path, icloud_folder / "ledger 2.db")
        ledger.db = str(icloud_folder / "ledger 2.db")
        assert ledger.run("totals")[0] == 0
        (icloud_folder / "ledger 2.db").rename(tmp_path / "kept elsewhere.db")
        ledger.db = str(ledger.path)
        assert ledger.run("totals")[0] == 0

    def test_names_that_are_not_a_conflicts_copy_are_left_alone(self, icloud_folder, capsys):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        for name in ("ledger.db-journal", "ledger 2.csv", "ledger two.db", "ledger .db",
                     "other 2.db", "ledger 2.db.backup"):
            (icloud_folder / name).write_text("")
        assert ledger.run("totals")[:3:2] == (0, "")

    def test_a_folder_someone_else_owns_is_refused(self, icloud_folder, capsys, monkeypatch):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        monkeypatch.setattr(os, "geteuid", lambda: icloud_folder.stat().st_uid + 1)
        code, _, err = ledger.run("totals")
        assert code == 2 and "must be owned by you" in err

    def test_a_work_tree_made_around_it_is_refused(self, icloud_folder, capsys):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        (icloud_folder / ".git").mkdir()
        code, _, err = ledger.run("totals")
        assert code == 2 and "inside a git work tree" in err


class TestImports:
    def test_originals_are_kept_and_verified(self, icloud_folder, capsys):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        ledger.card("jan.csv", CAFE)
        assert len(os.listdir(icloud_folder / "originals")) == 1
        as_a_sync_download_leaves_it(ledger)
        code, out, _ = ledger.run("archive", "verify")
        assert code == 0 and "The archive is intact." in out

    def test_a_file_inside_a_git_work_tree_is_refused(self, icloud_folder, capsys, tmp_path):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        work_tree = tmp_path / "checkout"
        (work_tree / ".git").mkdir(parents=True)
        (work_tree / "jan.csv").write_text(CARD_HEADER + CAFE + "\n")
        code, _, err = ledger.run("import", "--account", "A", "--layout", "synthetic_card_v1",
                                  str(work_tree / "jan.csv"))
        assert code == 2 and "inside a git work tree" in err


class TestFilesLeavingTheLedger:
    def test_an_export_needs_no_disk_image(self, icloud_folder, capsys, tmp_path):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        ledger.card("jan.csv", CAFE)
        out_folder = tmp_path / "exports"
        out_folder.mkdir(mode=0o700)
        code, _, err = ledger.run("export", "transactions", "--out", str(out_folder / "a.csv"))
        assert (code, err) == (0, "")

    def test_a_snapshot_needs_no_disk_image(self, icloud_folder, capsys, tmp_path):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        ledger.card("jan.csv", CAFE)
        out_folder = tmp_path / "phone"
        out_folder.mkdir(mode=0o700)
        code, _, err = ledger.run("snapshot", "create", "--out", str(out_folder / "phone.json"),
                                  "--as-of", AS_OF)
        assert (code, err) == (0, "")

    def test_an_encrypted_disk_image_ledger_still_exports_only_onto_one(self, vault, capsys,
                                                                        tmp_path, monkeypatch):
        ledger = RealLedger(vault, capsys)
        on_the_startup_disk = tmp_path / "exports"
        on_the_startup_disk.mkdir(mode=0o700)
        startup_mount_point = Path("/System/Volumes/Data")

        def mount_point_of(folder):
            if folder == on_the_startup_disk or on_the_startup_disk in folder.parents:
                return startup_mount_point
            return SYNTHETIC_MOUNT_POINT

        def diskutil_answer(mount_point):
            name = ("filevault_startup_volume" if mount_point == startup_mount_point
                    else "encrypted_disk_image")
            return 0, probe_recording(name)

        monkeypatch.setattr(real_ledger, "mount_point_containing", mount_point_of)
        monkeypatch.setattr(volume_probes, "diskutil_info_plist", diskutil_answer)
        code, _, err = ledger.run("export", "transactions", "--out",
                                  str(on_the_startup_disk / "a.csv"))
        assert code == 2 and "must be on a mounted disk image" in err
        assert not (on_the_startup_disk / "a.csv").exists()

    def test_an_export_into_a_synced_folder_is_still_refused(self, icloud_folder, capsys):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        code, _, err = ledger.run("export", "transactions", "--out",
                                  str(icloud_folder / "a.csv"))
        assert code == 2 and "synced folder" in err


class TestBackups:
    def test_a_backup_on_the_same_disk_restores_as_a_private_folder_ledger(
            self, icloud_folder, capsys, tmp_path):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        ledger.card("jan.csv", CAFE)
        external = tmp_path / "external"
        external.mkdir()
        external.chmod(0o755)
        code, _, err = ledger.run("backup", "create", "--to", str(external / "b1"))
        assert (code, err) == (0, "")
        assert mode_of(external / "b1") == 0o700

        other_mac = tmp_path / "home" / ICLOUD_DRIVE_UNDER_HOME / "Restored"
        other_mac.mkdir()
        other_mac.chmod(0o755)
        restored = other_mac / "ledger.db"
        capsys.readouterr()
        code = cli.main(["backup", "restore", "--from", str(external / "b1"),
                         "--to", str(restored)])
        assert code == 0, capsys.readouterr().err
        assert mode_of(other_mac) == 0o700
        restored_ledger = PrivateFolderLedger.__new__(PrivateFolderLedger)
        restored_ledger.path, restored_ledger.db = restored, str(restored)
        assert restored_ledger.protection() == PRIVATE_FOLDER
        assert restored_ledger.dump(LEDGER_TABLES) == ledger.everything()

    def test_a_backup_inside_a_git_work_tree_is_refused(self, icloud_folder, capsys, tmp_path):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        (tmp_path / "checkout" / ".git").mkdir(parents=True)
        code, _, err = ledger.run("backup", "create", "--to", str(tmp_path / "checkout" / "b1"))
        assert code == 2 and "inside a git work tree" in err
        assert not (tmp_path / "checkout" / "b1").exists()

    def test_a_backup_into_a_missing_folder_is_refused(self, icloud_folder, capsys, tmp_path):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        code, _, err = ledger.run("backup", "create", "--to", str(tmp_path / "nope" / "b1"))
        assert code == 2 and "must already exist" in err

    def test_a_restore_into_a_git_work_tree_is_refused(self, icloud_folder, capsys, tmp_path):
        ledger = PrivateFolderLedger(icloud_folder, capsys)
        assert ledger.run("backup", "create", "--to", str(tmp_path / "b1"))[0] == 0
        (tmp_path / "checkout" / ".git").mkdir(parents=True)
        capsys.readouterr()
        code = cli.main(["backup", "restore", "--from", str(tmp_path / "b1"),
                         "--to", str(tmp_path / "checkout" / "ledger.db")])
        assert code == 2 and "inside a git work tree" in capsys.readouterr().err
        assert not (tmp_path / "checkout" / "ledger.db").exists()
