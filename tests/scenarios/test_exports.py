"""CSV export from the terminal to a gated destination (WD1, D-073 point 7), using synthetic data
only. An unsafe or existing destination is refused, writing nothing; the file is 0600; formula-
like cells are prefixed; money round-trips exactly; and missing values are empty."""

import csv
import io
import os
import stat

import pytest
from test_decisions import CHECKING_HEADER, Ledger
from test_real_ledger import (  # noqa: F401, vault is a fixture
    RealLedger,
    place_on_volume,
    probe_recording,
    vault,
)
from test_tags import TagLedger

from personal_finance.db import exports
from personal_finance.money import parse_cents
from personal_finance.reports.export_rows import TRANSACTION_COLUMNS

# Import trims a description's spaces, tabs and returns, so those two starts are tested on cells
# directly, in test_cells_starting_with_each_formula_character_are_prefixed.
FORMULA_DESCRIPTIONS = ("=SUM(A1)", "+1", "-2", "@x")


@pytest.fixture
def ledger(tmp_path, capsys, vault):
    """Checking rows with formula-like descriptions, one without a posting date, and one tagged
    and categorized, in a synthetic ledger. vault is the private folder exports go to."""
    found = TagLedger(tmp_path, capsys)
    rows = [f"S-{number},2026-01-{number + 1:02d},2026-01-{number + 1:02d},"
            f"\"{description}\",-{number + 1}.05,POSTED"
            for number, description in enumerate(FORMULA_DESCRIPTIONS)]
    rows.append("S-9,2026-01-20,,SYNTHETIC PLAIN,1234567.89,POSTED")
    found.load_path(found.write("a.csv", CHECKING_HEADER, rows), layout="synthetic_checking_v1")
    found.vault = vault
    return found


def exported(ledger, *words, name="out.csv"):
    path = ledger.vault / name
    kind, *rest = words
    code, out, err = ledger.run("export", kind, "--out", str(path), *rest)
    return code, out, err, path


def read_rows(path):
    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"), newline="")))


class TestTheFile:  # WD1
    def test_it_is_new_private_and_its_columns_fixed(self, ledger):
        code, out, err, path = exported(ledger, "transactions")
        assert code == 0, err
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        rows = read_rows(path)
        assert tuple(rows[0]) == TRANSACTION_COLUMNS
        assert len(rows) == 1 + len(FORMULA_DESCRIPTIONS) + 1
        assert "Exported 5 transactions" in out and "not encrypted" in out

    def test_formula_like_cells_are_prefixed_and_amounts_keep_their_sign(self, ledger):
        _, _, _, path = exported(ledger, "transactions")
        by_description = {row[6]: row for row in read_rows(path)[1:]}
        for description in FORMULA_DESCRIPTIONS:
            assert "'" + description in by_description, description
        assert all(row[4].startswith("-") for row in by_description.values()
                   if row[6] != "SYNTHETIC PLAIN")
        assert "SYNTHETIC PLAIN" in by_description

    def test_money_round_trips_exactly_and_missing_is_empty(self, ledger):
        _, _, _, path = exported(ledger, "transactions")
        conn = ledger.conn()
        stored = dict(conn.execute("SELECT id, amount_cents FROM ledger_transaction"))
        conn.close()
        for row in read_rows(path)[1:]:
            assert parse_cents(row[4]) == stored[row[0]]
        plain = next(row for row in read_rows(path)[1:] if row[6] == "SYNTHETIC PLAIN")
        assert plain[3] == "" and plain[4] == "1234567.89"
        assert plain[7] == "" and plain[8] == "" and plain[9] == ""

    def test_type_category_and_tags_are_the_ones_in_effect(self, ledger):
        transaction = ledger.transaction_ids()[0]
        for words in (("--type", "purchase"),):
            assert ledger.run("review", "classify", transaction, "--account", "A", "--revision",
                              ledger.transaction_revision(transaction), *words)[0] == 0
        assert ledger.run("review", "categorize", transaction, "--account", "A", "--revision",
                          ledger.transaction_revision(transaction), "--category", "Food")[0] == 0
        for name in ("Trip", "Work"):
            assert ledger.run("tag", "add", name)[0] == 0
        ledger.tag_ok(transaction, "Work,Trip")
        _, _, _, path = exported(ledger, "transactions")
        row = next(row for row in read_rows(path)[1:] if row[0] == transaction)
        assert row[7:] == ["purchase", "Food", "Trip, Work"]

    def test_filters_select_by_account_and_date(self, ledger):
        code, _, err, path = exported(ledger, "transactions", "--from", "2026-01-02", "--to",
                                      "2026-01-03")
        assert code == 0, err
        assert [row[2] for row in read_rows(path)[1:]] == ["2026-01-02", "2026-01-03"]

    @pytest.mark.parametrize("report, words, command", [
        ("totals", (), ("totals",)),
        ("monthly", ("--from", "2026-01"), ("report", "monthly", "--from", "2026-01")),
        ("household", (), ("report", "household")),
    ])
    def test_a_report_is_its_lines_one_a_row(self, ledger, report, words, command):
        code, _, err, path = exported(ledger, "report", report, *words)
        assert code == 0, err
        printed = ledger.run(*command)[1]
        lines = [row[0] for row in read_rows(path)[1:]]
        assert [line[1:] if line.startswith("'") else line for line in lines] == \
            printed.splitlines()


class TestTheDestination:  # WD1
    def assert_refused(self, ledger, path, message):
        before = sorted(os.listdir(path.parent)) if path.parent.exists() else None
        code, _, err = ledger.run("export", "transactions", "--out", str(path))
        assert code == 2 and message in err, err
        if before is not None:
            assert sorted(os.listdir(path.parent)) == before

    def test_an_existing_file_is_refused_and_kept(self, ledger):
        path = ledger.vault / "out.csv"
        path.write_text("mine")
        self.assert_refused(ledger, path, "already exists")
        assert path.read_text() == "mine"

    def test_a_folder_others_can_read_is_refused(self, ledger):
        ledger.vault.chmod(0o755)
        self.assert_refused(ledger, ledger.vault / "out.csv", "private")

    def test_a_folder_reached_through_a_link_is_refused(self, ledger):
        link = ledger.vault.parent / "link"
        link.symlink_to(ledger.vault)
        self.assert_refused(ledger, link / "out.csv", "symbolic link")

    def test_a_git_work_tree_is_refused(self, ledger):
        tree = ledger.vault / "repository"
        tree.mkdir(mode=0o700)
        (tree / ".git").mkdir()
        self.assert_refused(ledger, tree / "out.csv", "git work tree")

    def test_a_synced_folder_is_refused(self, ledger):
        synced = ledger.vault.parent / "home" / "Dropbox"
        synced.mkdir(mode=0o700)
        self.assert_refused(ledger, synced / "out.csv", "synced folder")

    def test_a_missing_folder_is_refused(self, ledger):
        code, _, err = ledger.run("export", "transactions", "--out",
                                  str(ledger.vault / "nope" / "out.csv"))
        assert code == 2 and "must already exist" in err

    def test_a_link_where_the_file_would_be_is_refused(self, ledger):
        (ledger.vault / "out.csv").symlink_to(ledger.vault / "elsewhere.csv")
        self.assert_refused(ledger, ledger.vault / "out.csv", "already exists")
        assert not (ledger.vault / "elsewhere.csv").exists()

    def test_a_real_ledger_exports_only_onto_an_encrypted_image(self, vault, capsys,
                                                                 monkeypatch):
        real = RealLedger(vault, capsys)
        out_folder = vault / "exports"
        out_folder.mkdir(mode=0o700)
        assert real.run("export", "transactions", "--out", str(out_folder / "a.csv"))[0] == 0
        place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"))
        code, _, err = real.run("export", "transactions", "--out", str(out_folder / "b.csv"))
        # The open's own gate refuses first, as for every command on a real ledger (D-058).
        assert code == 2 and "encrypted" in err
        assert not (out_folder / "b.csv").exists()

    def test_a_failure_while_writing_leaves_no_file(self, ledger, monkeypatch):
        def failing_fsync(descriptor):
            raise OSError("synthetic failure")

        monkeypatch.setattr(exports.os, "fsync", failing_fsync)
        code, _, err, path = exported(ledger, "transactions")
        assert code == 2 and not path.exists()


def test_cells_starting_with_each_formula_character_are_prefixed():
    for start in exports.FORMULA_STARTS:
        assert exports.protected_cell(f"{start}x") == f"'{start}x"
    assert exports.protected_cell("x=1") == "x=1"
    text = exports.csv_text(("amount", "note"), [("-12.34", "-12.34"), (None, None)],
                            frozenset({"amount"}))
    assert text == "amount,note\r\n-12.34,'-12.34\r\n,\r\n"


def test_a_plain_ledger_with_no_vault_refuses_the_repository(tmp_path, capsys):
    ledger = Ledger(tmp_path, capsys)
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    code, _, err = ledger.run("export", "transactions", "--out", str(folder / "out.csv"))
    assert code == 2 and "git work tree" in err


def test_the_transactions_page_shows_the_command_and_offers_no_download(ledger):
    from local_ui_client import parsed_page
    from test_local_ui_writes import Browser

    browser = Browser(ledger.path)
    try:
        response = browser.get("/transactions?from=2026-01-02")
    finally:
        browser.close()
    hint = parsed_page(response.body).hint_text
    assert f"pf export transactions --db {ledger.db} --out FILE.csv --from 2026-01-02" in hint
    assert response.header("Content-Disposition") is None
    assert "download" not in response.text.lower().replace("downloads", "")
