"""Migration 0009 on a populated ledger, and its append-only tables (V15, D-049).

A ledger built at the latest version, with the empty tables of 0009 and 0010 dropped and set back to
version 8, is a version 8 ledger: both only create tables. Migration stops at 9, so that only 0009 is
tested here.
"""

import sqlite3

import pytest
from test_confirmations import confirm_ok
from test_corrections import CORRECTION_TABLES, CorrectionLedger, single
from test_decisions import ALL_TABLES, CAFE, RESOLUTION_TABLES, pair_up

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_8_TABLES = tuple(table for table in ALL_TABLES
                         if table not in (*CORRECTION_TABLES, *RESOLUTION_TABLES))


def up_to_version_9(folder):
    folder.mkdir()
    for migration in load_migrations()[:9]:
        (folder / migration.path.name).write_text(migration.path.read_text())
    return folder


def set_back_to_version_8(path) -> None:
    conn = connect(path)
    for table in (*RESOLUTION_TABLES, "transaction_correction", "value_correction_event",
                  "value_correction_record", "value_correction"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 8")
    conn.close()


@pytest.fixture
def populated(tmp_path, capsys):
    """Decisions, a merge and open items, with no correction."""
    ledger = CorrectionLedger(tmp_path, capsys)
    item, one, two = pair_up(ledger)
    confirm_ok(ledger, item, (one, two))
    ledger.card("c.csv", CAFE)
    ledger.card("d.csv", "03/20/2026,SYNTHETIC GROCER,9.00,")
    set_back_to_version_8(ledger.path)
    return ledger


class TestMigration:
    def test_it_adds_empty_tables_and_changes_nothing_else(self, populated, tmp_path):
        before = populated.dump(VERSION_8_TABLES)
        conn = connect(populated.path)
        assert migrate(conn, up_to_version_9(tmp_path / "nine")) == 9
        for table in CORRECTION_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_8_TABLES) == before
        assert "have not been reconciled" not in populated.totals()

    def test_corrections_work_after_it_without_reconciling(self, populated):
        assert populated.run("migrate")[0] == 0
        transaction = populated.run("transactions")[1].split()[0]
        populated.correct_ok(transaction, "posting_date", "2026-01-12")

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = tmp_path / "broken"
        folder.mkdir()
        migrations = load_migrations()
        for migration in migrations:
            (folder / migration.path.name).write_text(migration.path.read_text())
        (folder / migrations[8].path.name).write_text(
            migrations[8].path.read_text() + "SELECT no_such_function();"
        )
        before = populated.dump(VERSION_8_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 8
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(CORRECTION_TABLES)
        conn.close()
        assert populated.dump(VERSION_8_TABLES) == before


@pytest.fixture
def corrected(tmp_path, capsys):
    ledger = CorrectionLedger(tmp_path, capsys)
    correction = ledger.correct_ok(single(ledger), "amount", "-6.00")
    ledger.undo_correction(correction)
    return ledger, correction


class TestAppendOnly:
    @pytest.mark.parametrize("statement", [
        "UPDATE value_correction SET corrected_amount_cents = -1",
        "DELETE FROM value_correction",
        "INSERT INTO value_correction SELECT * FROM value_correction",
        "UPDATE value_correction_record SET source_record_id = source_record_id",
        "DELETE FROM value_correction_record",
        "INSERT INTO value_correction_record SELECT * FROM value_correction_record",
        "UPDATE value_correction_event SET event = 'made'",
        "DELETE FROM value_correction_event",
        "INSERT INTO value_correction_event (correction_id, event) "
        "SELECT correction_id, event FROM value_correction_event",
    ])
    def test_history_refuses_change(self, corrected, statement):
        ledger, _ = corrected
        before = ledger.dump(CORRECTION_TABLES)
        conn = ledger.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert ledger.dump(CORRECTION_TABLES) == before

    @pytest.mark.parametrize(("field", "amount", "text"), [
        ("amount", None, "-6.00"),
        ("description", -600, None),
        ("posting_date", None, "2026-02-30"),
        ("description", None, "  "),
        ("settlement_status", None, "posted"),
    ])
    def test_a_stored_value_must_fit_its_field(self, corrected, field, amount, text):
        ledger, _ = corrected
        conn = ledger.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO value_correction (id, account_id, field, corrected_amount_cents,
                                                 corrected_text, target_transaction_id,
                                                 target_revision)
                   VALUES ('x', (SELECT id FROM account), ?, ?, ?, 't', 't3-0')""",
                (field, amount, text),
            )
        conn.close()

    def test_a_correction_supersedes_only_its_own_field(self, corrected):
        ledger, correction = corrected
        conn = ledger.conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO value_correction (id, account_id, field, corrected_text,
                                                 target_transaction_id, target_revision,
                                                 supersedes_correction_id)
                   VALUES ('x', (SELECT id FROM account), 'description', 'CAFE', 't', 't3-0', ?)""",
                (correction,),
            )
        conn.close()
