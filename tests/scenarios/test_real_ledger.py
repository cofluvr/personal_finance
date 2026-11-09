"""Real ledgers: the marker, and where one may live and import from (H1 to H5, D-058).

pytest's temporary folder can sit inside this repository, which is a git work tree, when TMPDIR
points into build/. The `vault` fixture therefore treats a work tree found above tmp_path as absent,
while one made inside tmp_path is still found by the real search. It also places the folder on a
synthetic encrypted disk image, answering for diskutil with a recording (M5.2), so the suite never
runs diskutil or mounts a volume.
"""

import os
import sqlite3
from pathlib import Path

import pytest
from test_decisions import ALL_TABLES, CARD_HEADER, CAFE, Ledger

from personal_finance import cli
from personal_finance.db import diskutil, real_ledger
from personal_finance.db.migrate import connect, create_database
from personal_finance.db.real_ledger import (
    SYNCED_FOLDERS_UNDER_HOME,
    git_work_tree_containing,
    is_real_ledger,
    mark_real_ledger,
)

LEDGER_TABLES = (*ALL_TABLES, "account", "import_run", "real_ledger")

DISKUTIL_RECORDINGS = Path(__file__).parents[1] / "fixtures" / "synthetic" / "diskutil"
SYNTHETIC_MOUNT_POINT = Path("/Volumes/SyntheticLedger")


def diskutil_recording(name):
    return (DISKUTIL_RECORDINGS / f"{name}.plist").read_bytes()


def place_on_volume(monkeypatch, diskutil_output, *, mount_point=SYNTHETIC_MOUNT_POINT,
                    diskutil_exit_code=0):
    """Make every folder's mount point `mount_point`, and diskutil's answer about it the one given.
    Returns the list of mount points diskutil was asked about."""
    asked_about = []

    def answer(asked_mount_point):
        asked_about.append(asked_mount_point)
        return diskutil_exit_code, diskutil_output

    monkeypatch.setattr(real_ledger, "mount_point_containing", lambda folder: mount_point)
    monkeypatch.setattr(diskutil, "info_plist", answer)
    return asked_about


class RealLedger(Ledger):
    """A ledger made by `init --real`, with one card account A."""

    def __init__(self, folder, capsys, name="ledger.db"):
        self.folder = folder
        self.path = folder / name
        self.capsys = capsys
        self.db = str(self.path)
        self.files = 0
        code, out, err = self.run("init", "--real")
        assert code == 0, err
        assert out == f"Created real ledger {self.path}\n"
        self.add_account("A")

    def everything(self):
        return self.dump(LEDGER_TABLES)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """A private folder for a real ledger on an encrypted disk image, under a home with no synced
    folders."""
    search_from_the_disk = git_work_tree_containing

    def work_tree_within_tmp_path(path):
        found = search_from_the_disk(path)
        if found is None or (found != tmp_path and tmp_path not in found.parents):
            return None
        return found

    monkeypatch.setattr(real_ledger, "git_work_tree_containing", work_tree_within_tmp_path)
    place_on_volume(monkeypatch, diskutil_recording("encrypted_disk_image"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    folder = tmp_path / "vault"
    folder.mkdir(mode=0o700)
    folder.chmod(0o700)
    return folder


def init_real(capsys, path):
    capsys.readouterr()
    code = cli.main(["init", "--db", str(path), "--real"])
    return code, capsys.readouterr().err



class TestTheMarker:
    """H1."""

    def test_init_real_marks_the_ledger_and_plain_init_does_not(self, vault, capsys, tmp_path):
        real = RealLedger(vault, capsys)
        synthetic = Ledger(tmp_path, capsys)
        for ledger, expected in ((real, True), (synthetic, False)):
            conn = ledger.conn()
            assert is_real_ledger(conn) is expected
            conn.close()

    def test_only_a_ledger_holding_nothing_can_be_marked(self, tmp_path, capsys):
        empty = tmp_path / "empty.db"
        create_database(empty)
        conn = connect(empty)
        mark_real_ledger(conn)
        assert is_real_ledger(conn)
        conn.close()

        holding_an_account = Ledger(tmp_path, capsys)
        conn = holding_an_account.conn()
        with pytest.raises(sqlite3.IntegrityError, match="holding nothing yet"):
            mark_real_ledger(conn)
        assert not is_real_ledger(conn)
        conn.close()

    def test_a_ledger_holding_only_an_import_run_cannot_be_marked(self, tmp_path):
        path = tmp_path / "run.db"
        create_database(path)
        conn = connect(path)
        conn.execute("INSERT INTO import_run (id) VALUES ('run')")
        with pytest.raises(sqlite3.IntegrityError, match="holding nothing yet"):
            mark_real_ledger(conn)
        conn.close()

    @pytest.mark.parametrize("statement", [
        "UPDATE real_ledger SET created_at = 'then'",
        "DELETE FROM real_ledger",
        "INSERT OR REPLACE INTO real_ledger (only_row) VALUES (1)",
        "INSERT INTO real_ledger (only_row) VALUES (2)",
    ])
    def test_the_marker_is_never_changed_or_removed(self, tmp_path, statement):
        # A marked ledger holding nothing yet, so the trigger refusing a mark on a ledger with an
        # account does not stand in for the ones under test.
        path = tmp_path / "marked.db"
        create_database(path)
        conn = connect(path)
        mark_real_ledger(conn)
        before = conn.execute("SELECT * FROM real_ledger").fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)
        assert conn.execute("SELECT * FROM real_ledger").fetchall() == before
        conn.close()


class TestInitRefusals:
    """H2: each refusal names its rule and creates nothing."""

    def refused(self, capsys, path, message):
        listing_before = sorted(path.parent.iterdir()) if path.parent.is_dir() else None
        code, err = init_real(capsys, path)
        assert code == 2
        assert message in err
        assert not path.exists()
        if listing_before is not None:
            assert sorted(path.parent.iterdir()) == listing_before

    def test_a_private_folder_is_accepted_and_the_ledger_is_private(self, vault, capsys):
        code, err = init_real(capsys, vault / "ledger.db")
        assert (code, err) == (0, "")
        assert (vault / "ledger.db").stat().st_mode & 0o777 == 0o600

    def test_a_missing_folder(self, vault, capsys):
        self.refused(capsys, vault / "missing" / "ledger.db", "must already exist")

    def test_a_git_work_tree_above_the_folder(self, vault, capsys):
        (vault / ".git").mkdir()
        inner = vault / "inner"
        inner.mkdir(mode=0o700)
        self.refused(capsys, inner / "ledger.db", f"inside a git work tree: {vault}")

    def test_a_git_file_marks_a_work_tree_too(self, vault, capsys):
        (vault / ".git").write_text("gitdir: elsewhere\n")
        self.refused(capsys, vault / "ledger.db", "inside a git work tree")

    @pytest.mark.parametrize("synced", SYNCED_FOLDERS_UNDER_HOME)
    def test_each_synced_folder(self, vault, capsys, tmp_path, synced):
        folder = tmp_path / "home" / synced / "finance"
        folder.mkdir(parents=True, mode=0o700)
        folder.chmod(0o700)
        self.refused(capsys, folder / "ledger.db", "inside a synced folder")

    def test_a_symbolic_link_to_the_folder(self, vault, capsys, tmp_path):
        link = tmp_path / "link"
        link.symlink_to(vault)
        self.refused(capsys, link / "ledger.db", "through a symbolic link")

    def test_a_symbolic_link_at_the_database_path(self, vault, capsys):
        (vault / "ledger.db").symlink_to(vault / "elsewhere.db")
        code, err = init_real(capsys, vault / "ledger.db")
        assert code == 2 and "through a symbolic link" in err
        assert not (vault / "elsewhere.db").exists()

    @pytest.mark.parametrize("mode", [0o750, 0o705, 0o720, 0o702])
    def test_a_folder_others_can_reach(self, vault, capsys, mode):
        vault.chmod(mode)
        self.refused(capsys, vault / "ledger.db", f"Run: chmod 700 {vault}")

    def test_a_folder_owned_by_someone_else(self, vault, capsys, monkeypatch):
        monkeypatch.setattr(os, "geteuid", lambda: vault.stat().st_uid + 1)
        self.refused(capsys, vault / "ledger.db", "must be owned by you")

    def test_an_existing_file_is_still_never_overwritten(self, vault, capsys):
        (vault / "ledger.db").write_text("not a ledger")
        (vault / "ledger.db").chmod(0o600)
        code, err = init_real(capsys, vault / "ledger.db")
        assert code == 2 and "refusing to overwrite" in err
        assert (vault / "ledger.db").read_text() == "not a ledger"


# Every kind of open: read-only, writing, and migrate, which opens without open_ledger.
COMMANDS = [("totals",), ("transactions",), ("review", "list"), ("report", "monthly"),
            ("account", "add", "--name", "B", "--type", "savings"), ("migrate",)]


def loosen_folder(ledger):
    ledger.folder.chmod(0o755)
    return f"Run: chmod 700 {ledger.folder}"


def loosen_database(ledger):
    ledger.path.chmod(0o644)
    return f"Run: chmod 600 {ledger.path}"


def wrap_in_work_tree(ledger):
    (ledger.folder / ".git").mkdir()
    return "inside a git work tree"


def reach_through_link(ledger):
    link = ledger.folder.parent / "link"
    link.symlink_to(ledger.folder)
    ledger.db = str(link / ledger.path.name)
    return "through a symbolic link"


class TestEveryOpenChecks:
    """H3."""

    @pytest.mark.parametrize("unsafe", [loosen_folder, loosen_database, wrap_in_work_tree,
                                        reach_through_link])
    @pytest.mark.parametrize("command", COMMANDS)
    def test_a_ledger_that_became_unsafe_is_refused(self, vault, capsys, unsafe, command):
        ledger = RealLedger(vault, capsys)
        ledger.card("jan.csv", CAFE)
        before = ledger.everything()
        message = unsafe(ledger)
        code, out, err = ledger.run(*command)
        assert code == 2
        assert message in err
        assert out == ""
        ledger.db = str(ledger.path)
        ledger.folder.chmod(0o700)
        ledger.path.chmod(0o600)
        assert ledger.everything() == before

    @pytest.mark.parametrize("command", COMMANDS)
    def test_a_safe_ledger_opens_for_every_kind_of_command(self, vault, capsys, command):
        ledger = RealLedger(vault, capsys)
        ledger.card("jan.csv", CAFE)
        code, _, err = ledger.run(*command)
        assert (code, err) == (0, "")


class TestImports:
    """H4."""

    def test_a_real_ledger_refuses_a_file_inside_a_git_work_tree(self, vault, capsys, tmp_path):
        ledger = RealLedger(vault, capsys)
        work_tree = tmp_path / "checkout"
        (work_tree / ".git").mkdir(parents=True)
        inside = work_tree / "jan.csv"
        inside.write_text(CARD_HEADER + CAFE + "\n")
        outside = tmp_path / "jan.csv"
        outside.write_text(CARD_HEADER + CAFE + "\n")
        before = ledger.everything()

        code, out, err = ledger.run("import", "--account", "A", "--layout", "synthetic_card_v1",
                                    str(outside), str(inside))
        assert code == 2
        assert f"{inside} is inside {work_tree}" in err
        assert out == ""
        assert ledger.everything() == before

        ledger.load_path(outside)
        assert ledger.count() == 1

    def test_a_link_into_a_work_tree_is_followed(self, vault, capsys, tmp_path):
        ledger = RealLedger(vault, capsys)
        work_tree = tmp_path / "checkout"
        (work_tree / ".git").mkdir(parents=True)
        (work_tree / "jan.csv").write_text(CARD_HEADER + CAFE + "\n")
        (tmp_path / "jan.csv").symlink_to(work_tree / "jan.csv")
        code, _, err = ledger.run("import", "--account", "A", "--layout", "synthetic_card_v1",
                                  str(tmp_path / "jan.csv"))
        assert code == 2 and "inside a git work tree" in err
        assert ledger.count() == 0

    def test_a_synthetic_ledger_imports_from_a_work_tree(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        ledger = Ledger(tmp_path, capsys)
        ledger.card("jan.csv", CAFE)
        assert ledger.count() == 1


class TestSyntheticLedgersAreUnchecked:
    """H5, with every earlier criterion."""

    def test_a_shared_synthetic_ledger_in_a_work_tree_opens(self, tmp_path, capsys):
        (tmp_path / ".git").mkdir()
        ledger = Ledger(tmp_path, capsys)
        tmp_path.chmod(0o755)
        ledger.path.chmod(0o644)
        for command in COMMANDS:
            code, _, err = ledger.run(*command)
            assert (code, err) == (0, "")
        tmp_path.chmod(0o700)
