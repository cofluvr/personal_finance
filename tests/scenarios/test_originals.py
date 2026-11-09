"""Archiving originals, and storage by kind (Y1 to Y5, D-017, D-058 points 5 and 6).

A real ledger here lives in the `vault` fixture's folder, on a synthetic encrypted disk image, so
no volume is mounted. Every document is synthetic.
"""

import hashlib
import os
import sqlite3
import stat
from pathlib import Path

import pytest
from ledger_view import semantic_view
from test_decisions import CAFE, CARD_HEADER, OTHER, Ledger
from test_real_ledger import RealLedger, vault  # noqa: F401, vault is a fixture

import personal_finance
from personal_finance.db import originals as originals_module
from personal_finance.ingest import pipeline
from personal_finance.ingest.errors import ImportFailure
from personal_finance.reconcile.rules import DEFAULT_RULES

GROCER_TWO = "03/21/2026,SYNTHETIC GROCER,4.00,"


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def originals_of(ledger):
    return ledger.folder / "originals"


def entries(folder):
    return sorted(os.listdir(folder))


def import_file(ledger, path):
    return ledger.run("import", "--account", "A", "--layout", "synthetic_card_v1", str(path))


def writable(folder):
    """Let a test change the archive as an outside process could."""
    folder.chmod(0o700)
    for entry in folder.iterdir():
        if not entry.is_symlink():
            entry.chmod(0o600)


def archive_calls(monkeypatch):
    calls = []
    archive = pipeline.archive_original

    def counted(originals_folder, content, content_sha256):
        calls.append(content_sha256)
        archive(originals_folder, content, content_sha256)

    monkeypatch.setattr(pipeline, "archive_original", counted)
    return calls


class TestArchivingOnImport:
    """Y1."""

    def test_a_new_document_is_copied_under_its_sha256_read_only(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        ledger.load_path(path)

        digest = sha256_of(path)
        conn = ledger.conn()
        assert conn.execute("SELECT content_sha256 FROM source_document").fetchall() == [(digest,)]
        assert entries(originals_of(ledger)) == [digest]
        original = originals_of(ledger) / digest
        assert original.read_bytes() == path.read_bytes()
        assert stat.S_IMODE(original.lstat().st_mode) == 0o400
        assert stat.S_IMODE(originals_of(ledger).stat().st_mode) == 0o700

    def test_each_new_document_of_a_run_is_archived(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        first = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        second = ledger.write("mar.csv", CARD_HEADER, [OTHER])
        code, _, err = ledger.run("import", "--account", "A", "--layout", "synthetic_card_v1",
                                  str(first), str(second))
        assert (code, err) == (0, "")
        assert entries(originals_of(ledger)) == sorted([sha256_of(first), sha256_of(second)])

    def test_the_copy_is_made_before_the_import_commits(self, vault, capsys, monkeypatch):
        ledger = RealLedger(vault, capsys)
        committed_documents_when_archived = []
        archive = pipeline.archive_original

        def watched(originals_folder, content, content_sha256):
            watcher = sqlite3.connect(ledger.path)
            committed_documents_when_archived.append(
                watcher.execute("SELECT COUNT(*) FROM source_document").fetchone()[0])
            watcher.close()
            archive(originals_folder, content, content_sha256)

        monkeypatch.setattr(pipeline, "archive_original", watched)
        ledger.card("jan.csv", CAFE)
        assert committed_documents_when_archived == [0]
        assert ledger.count() == 1

    def test_a_repeat_import_copies_nothing(self, vault, capsys, monkeypatch):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        ledger.load_path(path)
        original = originals_of(ledger) / sha256_of(path)
        before = original.lstat()

        calls = archive_calls(monkeypatch)
        out = ledger.load_path(path)
        assert "already imported" in out
        assert calls == []
        after = original.lstat()
        assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
        assert entries(originals_of(ledger)) == [sha256_of(path)]


def failing_rename(source, destination):
    raise OSError("synthetic: the disk is full")


class TestAFailedCopy:
    """Y2."""

    def refused(self, ledger, path):
        before = ledger.everything()
        code, out, err = import_file(ledger, path)
        assert code == 1, err
        assert f"{path.name}: failed (archive_failed)" in out
        assert "Run pf archive verify to check the archive." in out
        after = ledger.everything()
        assert len(after.pop("import_run")) == 1
        before.pop("import_run")
        assert after == before
        attempts = ledger.conn().execute(
            "SELECT outcome, source_document_id, failure_code FROM import_attempt").fetchall()
        assert attempts == [("failed", None, "archive_failed")]

    def test_a_failed_write_fails_the_file_keeping_nothing(self, vault, capsys, monkeypatch):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        monkeypatch.setattr(originals_module.os, "rename", failing_rename)
        self.refused(ledger, path)
        assert entries(originals_of(ledger)) == []

    def test_a_folder_that_cannot_be_written_fails_the_file(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        originals_of(ledger).mkdir(mode=0o500)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        self.refused(ledger, path)
        assert entries(originals_of(ledger)) == []

    def test_other_files_of_the_run_still_import(self, vault, capsys, monkeypatch):
        ledger = RealLedger(vault, capsys)
        failing = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        passing = ledger.write("mar.csv", CARD_HEADER, [OTHER])
        archive = pipeline.archive_original

        def fails_for_jan(originals_folder, content, content_sha256):
            if content_sha256 == sha256_of(failing):
                raise ImportFailure("archive_failed")
            archive(originals_folder, content, content_sha256)

        monkeypatch.setattr(pipeline, "archive_original", fails_for_jan)
        code, out, _ = ledger.run("import", "--account", "A", "--layout", "synthetic_card_v1",
                                  str(failing), str(passing))
        assert code == 1
        assert "jan.csv: failed (archive_failed)" in out
        assert ledger.count() == 1
        assert entries(originals_of(ledger)) == [sha256_of(passing)]

    def test_a_different_file_holding_the_name_is_kept_and_fails_the_file(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        originals_of(ledger).mkdir(mode=0o700)
        squatter = originals_of(ledger) / sha256_of(path)
        squatter.write_bytes(b"synthetic altered bytes")
        self.refused(ledger, path)
        assert squatter.read_bytes() == b"synthetic altered bytes"

    def test_a_link_holding_the_name_fails_the_file(self, vault, capsys, tmp_path):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        originals_of(ledger).mkdir(mode=0o700)
        (originals_of(ledger) / sha256_of(path)).symlink_to(path)
        self.refused(ledger, path)

    def test_a_matching_file_holding_the_name_is_kept_as_the_original(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        originals_of(ledger).mkdir(mode=0o700)
        left = originals_of(ledger) / sha256_of(path)
        left.write_bytes(path.read_bytes())
        inode = left.lstat().st_ino
        ledger.load_path(path)
        assert left.lstat().st_ino == inode
        assert entries(originals_of(ledger)) == [sha256_of(path)]

    def test_a_copy_left_by_a_rolled_back_import_is_not_referenced(self, vault, capsys,
                                                                    monkeypatch):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        archive = pipeline.archive_original

        def commit_fails_after_copy(originals_folder, content, content_sha256):
            archive(originals_folder, content, content_sha256)
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(pipeline, "archive_original", commit_fails_after_copy)
        code, out, _ = import_file(ledger, path)
        assert code == 1 and "failed (database_busy)" in out
        assert ledger.count() == 0
        size = path.stat().st_size

        code, out, _ = ledger.run("archive", "verify")
        assert code == 1
        assert out.splitlines()[-2:] == [f"  {sha256_of(path)}", "The archive is not intact."]
        assert "Not referenced: 1" in out
        out = ledger.run("storage")[1]
        assert (f"Originals: 0 bytes in 0 files referenced, {size} bytes in 1 files not "
                "referenced") in out

        monkeypatch.setattr(pipeline, "archive_original", archive)
        ledger.load_path(path)
        code, out, _ = ledger.run("archive", "verify")
        assert code == 0 and "Originals intact: 1" in out
        assert entries(originals_of(ledger)) == [sha256_of(path)]


class TestUnsafeOriginalsFolder:
    """Y2, D-058 point 2's rules for the originals folder, on import and verify."""

    def make_link(self, ledger, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        originals_of(ledger).symlink_to(elsewhere)
        return "originals folder cannot be a symbolic link"

    def make_shared(self, ledger, tmp_path):
        originals_of(ledger).mkdir(mode=0o700)
        originals_of(ledger).chmod(0o750)
        return f"Run: chmod 700 {originals_of(ledger)}"

    def make_a_file(self, ledger, tmp_path):
        originals_of(ledger).write_bytes(b"")
        return "originals folder must be a folder"

    @pytest.mark.parametrize("unsafe", [make_link, make_shared, make_a_file])
    def test_an_import_is_refused_importing_nothing(self, vault, capsys, tmp_path, unsafe):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        message = unsafe(self, ledger, tmp_path)
        before = ledger.everything()
        code, out, err = import_file(ledger, path)
        assert (code, out) == (2, "")
        assert message in err
        assert ledger.everything() == before

    @pytest.mark.parametrize("unsafe", [make_link, make_shared, make_a_file])
    def test_verify_is_refused(self, vault, capsys, tmp_path, unsafe):
        ledger = RealLedger(vault, capsys)
        message = unsafe(self, ledger, tmp_path)
        code, out, err = ledger.run("archive", "verify")
        assert (code, out) == (2, "")
        assert message in err


class TestArchivingChangesNothingElse:
    """Y3."""

    def import_three(self, ledger):
        ledger.card("jan.csv", CAFE)
        ledger.card("mar.csv", OTHER, GROCER_TWO)
        ledger.card("both.csv", CAFE, OTHER)

    def test_a_real_ledger_has_the_same_outcome_tokens_and_provenance(self, vault, capsys,
                                                                      tmp_path):
        real = RealLedger(vault, capsys)
        self.import_three(real)
        synthetic_folder = tmp_path / "synthetic"
        synthetic_folder.mkdir()
        synthetic = Ledger(synthetic_folder, capsys)
        self.import_three(synthetic)

        assert semantic_view(real.conn()) == semantic_view(synthetic.conn())
        assert real.run("totals")[1] == synthetic.run("totals")[1]
        assert len(entries(originals_of(real))) == 3

    def test_no_identity_reads_the_archive(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE, OTHER])
        ledger.load_path(path)
        before = semantic_view(ledger.conn())
        transactions = ledger.run("transactions")[1]

        writable(originals_of(ledger))
        (originals_of(ledger) / sha256_of(path)).rename(ledger.folder / "moved_away")
        assert semantic_view(ledger.conn()) == before
        assert ledger.run("transactions")[1] == transactions
        assert "already imported, nothing changed" in ledger.load_path(path)
        assert semantic_view(ledger.conn()) == before

    def test_a_synthetic_ledger_archives_nothing(self, tmp_path, capsys, monkeypatch):
        calls = archive_calls(monkeypatch)
        ledger = Ledger(tmp_path, capsys)
        ledger.card("jan.csv", CAFE)
        assert ledger.count() == 1
        assert calls == []
        assert not os.path.lexists(tmp_path / "originals")

    def test_the_pipeline_archives_only_when_given_a_folder(self, tmp_path, capsys,
                                                            monkeypatch):
        calls = archive_calls(monkeypatch)
        ledger = Ledger(tmp_path, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        conn = ledger.conn()
        account_id = conn.execute("SELECT id FROM account").fetchone()[0]
        from personal_finance.ingest.layouts import LAYOUTS
        [result] = pipeline.import_files(conn, [path], account_id=account_id,
                                         layout=LAYOUTS["synthetic_card_v1"], rules=DEFAULT_RULES)
        assert result.outcome == "imported"
        assert calls == []


class TestArchiveVerify:
    """Y4."""

    def test_an_intact_archive_passes(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        ledger.card("jan.csv", CAFE)
        ledger.card("mar.csv", OTHER)
        code, out, err = ledger.run("archive", "verify")
        assert (code, err) == (0, "")
        assert out == ("Originals intact: 2\nMissing: 0\nAltered: 0\nNot referenced: 0\n"
                       "The archive is intact.\n")

    def test_a_ledger_with_no_documents_passes(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        code, out, _ = ledger.run("archive", "verify")
        assert code == 0
        assert out.endswith("The archive is intact.\n")

    def test_missing_altered_and_unreferenced_are_reported_exactly(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        paths = {name: ledger.write(name, CARD_HEADER, [row])
                 for name, row in (("intact.csv", CAFE), ("missing.csv", OTHER),
                                   ("altered.csv", GROCER_TWO),
                                   ("linked.csv", "04/02/2026,SYNTHETIC BAKERY,3.00,"))}
        for path in paths.values():
            ledger.load_path(path)
        documents = dict(ledger.conn().execute("SELECT file_name, id FROM source_document"))
        archive = originals_of(ledger)
        writable(archive)
        (archive / sha256_of(paths["missing.csv"])).unlink()
        (archive / sha256_of(paths["altered.csv"])).write_bytes(b"synthetic altered bytes")
        linked = archive / sha256_of(paths["linked.csv"])
        linked.rename(ledger.folder / "same_bytes_elsewhere")
        linked.symlink_to(ledger.folder / "same_bytes_elsewhere")
        (archive / "stray").write_bytes(b"")
        (archive / f".{'0' * 64}.abc.partial").write_bytes(b"")

        before = ledger.everything()
        code, out, _ = ledger.run("archive", "verify")
        assert code == 1
        altered = sorted(
            (sha256_of(paths[name]), documents[name]) for name in ("altered.csv", "linked.csv"))
        assert out.splitlines() == [
            "Originals intact: 1",
            "Missing: 1",
            f"  {sha256_of(paths['missing.csv'])}, document {documents['missing.csv']}",
            "Altered: 2",
            *(f"  {digest}, document {document}" for digest, document in altered),
            "Not referenced: 2",
            f"  .{'0' * 64}.abc.partial",
            "  stray",
            "The archive is not intact.",
        ]
        assert ledger.everything() == before

    def test_a_folder_at_an_originals_name_is_altered(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        ledger.load_path(path)
        original = originals_of(ledger) / sha256_of(path)
        writable(originals_of(ledger))
        original.unlink()
        original.mkdir()
        code, out, err = ledger.run("archive", "verify")
        assert (code, err) == (1, "")
        assert "Altered: 1" in out

    def test_a_missing_folder_reports_every_original_missing(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        ledger.card("jan.csv", CAFE)
        writable(originals_of(ledger))
        for entry in originals_of(ledger).iterdir():
            entry.unlink()
        originals_of(ledger).rmdir()
        code, out, _ = ledger.run("archive", "verify")
        assert code == 1
        assert "Missing: 1" in out and "Originals intact: 0" in out

    def test_a_synthetic_ledger_is_refused(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        code, out, err = ledger.run("archive", "verify")
        assert (code, out) == (2, "")
        assert "a synthetic ledger keeps no originals" in err


def package_files():
    package_folder = Path(personal_finance.__file__).parent
    files = [Path(folder) / name for folder, _, names in os.walk(package_folder) for name in names]
    return sum(path.lstat().st_size for path in files), len(files)


class TestStorage:
    """Y5."""

    def test_a_synthetic_ledger(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        ledger.card("jan.csv", CAFE)
        before = ledger.dump()
        code, out, err = ledger.run("storage")
        assert (code, err) == (0, "")
        software_bytes, software_files = package_files()
        assert out.splitlines() == [
            f"Software: {software_bytes} bytes in {software_files} files (the personal_finance "
            "package; the Python interpreter and its environment are not counted)",
            f"Database: {ledger.path.stat().st_size} bytes in 1 files (the ledger with its "
            "journal)",
            "Originals: none, a synthetic ledger archives nothing",
            "Backups: none recorded (backup create arrives in M5.4)",
        ]
        assert ledger.dump() == before

    def test_software_holds_the_package_and_nothing_beside_it(self):
        from personal_finance.reports.storage import software_files
        software = software_files()
        assert (software.byte_count, software.file_count) == package_files()
        cli_size = (Path(personal_finance.__file__).parent / "cli.py").stat().st_size
        assert software.byte_count > cli_size

    def test_the_journal_counts_with_the_database(self, tmp_path, capsys):
        ledger = Ledger(tmp_path, capsys)
        writer = sqlite3.connect(ledger.path, isolation_level=None)
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE account SET institution = 'Synthetic'")
        journal = Path(f"{ledger.path}-journal")
        assert journal.exists()
        out = ledger.run("storage")[1]
        expected = ledger.path.stat().st_size + journal.stat().st_size
        writer.execute("ROLLBACK")
        writer.close()
        assert f"Database: {expected} bytes in 2 files (the ledger with its journal)" in out

    def test_a_real_ledger_counts_referenced_and_unreferenced_originals(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        first = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        second = ledger.write("mar.csv", CARD_HEADER, [OTHER, GROCER_TWO])
        ledger.load_path(first)
        ledger.load_path(second)
        writable(originals_of(ledger))
        (originals_of(ledger) / "stray").write_bytes(b"12345")
        (originals_of(ledger) / "link").symlink_to(second)
        link_size = len(str(second))
        referenced = first.stat().st_size + second.stat().st_size
        out = ledger.run("storage")[1]
        assert (f"Originals: {referenced} bytes in 2 files referenced, {5 + link_size} bytes in 2 "
                "files not referenced") in out
        assert "Backups: none recorded (backup create arrives in M5.4)" in out

    def test_a_real_ledger_before_any_import_has_no_originals(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        out = ledger.run("storage")[1]
        assert ("Originals: 0 bytes in 0 files referenced, 0 bytes in 0 files not referenced"
                in out)
