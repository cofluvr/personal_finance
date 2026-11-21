"""Migration 0035, snapshot records, on a populated ledger (VB2, D-067 G10, D-075 point 7), using
synthetic data only. Its table is empty, nothing else shown changes, a ledger at 34 is refused
until migrate, a failure leaves everything as it was, and the table is append-only, each check
refusing on its own with a control that succeeds."""

import sqlite3

import pytest
from test_decisions import CAFE, SCENARIO_TABLES, SNAPSHOT_TABLES, drop_snapshot_tables
from test_funds import FundLedger
from test_scenario_migration import VERSION_33_TABLES, shown_now
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_34_TABLES = (*VERSION_33_TABLES, *SCENARIO_TABLES)


@pytest.fixture
def populated(tmp_path, capsys):
    """A purchase, a possible duplicate, a goal and a scenario, set back to 34."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.card("a.csv", CAFE)
    ledger.card("b.csv", CAFE)
    ledger.add_fund_ok(name="House", monthly="100.00", as_of="2026-03-15")
    assert ledger.run("scenario", "add", "--name", "Move")[0] == 0
    ledger.shown_before = [*shown_now(ledger), ledger.run("scenarios")]
    conn = connect(ledger.path)
    drop_snapshot_tables(conn)
    conn.execute("PRAGMA user_version = 34")
    conn.close()
    return ledger


class TestMigration:  # VB2, G10
    def test_it_adds_an_empty_table_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_34_TABLES)
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "thirty-five", 35)) == 35
        assert conn.execute("SELECT COUNT(*) FROM snapshot_record").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_34_TABLES) == before
        assert markers(populated) == ["A"]
        assert [*shown_now(populated), populated.run("scenarios")] == populated.shown_before

    def test_a_ledger_at_34_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("snapshots")
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("snapshots")[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 35)
        newest = load_migrations()[34].path
        assert newest.name == "0035_snapshot_records.sql"
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_34_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction and schema_version(conn) == 34
        assert "snapshot_record" not in {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master")}
        conn.close()
        assert populated.dump(VERSION_34_TABLES) == before


ROW = {"snapshot_id": "0b4a4b64-6f2e-4c4e-9a8e-3c8f9d7c1a22", "schema_version": "1.0",
       "as_of": "2026-05-04", "window_days": 90, "generated_at": "2026-05-04T17:00:00.000Z",
       "content_sha256": "a" * 64}
INSERT = ("INSERT INTO snapshot_record (snapshot_id, schema_version, as_of, window_days, "
          "generated_at, content_sha256) VALUES (:snapshot_id, :schema_version, :as_of, "
          ":window_days, :generated_at, :content_sha256)")


@pytest.fixture
def recorded(tmp_path, capsys):
    ledger = FundLedger(tmp_path, capsys)
    conn = ledger.conn()
    conn.execute(INSERT, ROW)
    conn.close()
    return ledger


class TestTheTable:  # VB2, G2
    def test_rows_refuse_update_delete_and_replace(self, recorded):
        before = recorded.dump(SNAPSHOT_TABLES)
        conn = recorded.conn()
        for each in ("UPDATE snapshot_record SET window_days = 1", "DELETE FROM snapshot_record",
                     "INSERT INTO snapshot_record SELECT * FROM snapshot_record"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(each)
        conn.close()
        assert recorded.dump(SNAPSHOT_TABLES) == before

    def test_a_control_insert_succeeds(self, recorded):
        conn = recorded.conn()
        conn.execute(INSERT, {**ROW, "snapshot_id": "1" * 36, "schema_version": "12.30",
                              "window_days": 366})
        conn.close()

    @pytest.mark.parametrize("changes", [
        {"snapshot_id": "short"}, {"schema_version": "1"}, {"schema_version": "1.0a"},
        {"as_of": "2026-02-30"}, {"window_days": 0}, {"window_days": 367},
        {"generated_at": "2026-05-04 17:00:00"}, {"content_sha256": "a" * 63},
        {"content_sha256": "A" * 64}])
    def test_each_check_refuses_alone(self, recorded, changes):
        conn = recorded.conn()
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(INSERT, {**ROW, "snapshot_id": "2" * 36, **changes})
        conn.close()
