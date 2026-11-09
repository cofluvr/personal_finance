"""Migration 0016 on a populated ledger, and its append-only tables (B8, D-057).

A ledger built at the latest version, with 0016's empty tables dropped and set back to version 15, is
a version 15 ledger: 0016 creates tables only. Migration stops at 16, so that only 0016 is tested.
"""

import sqlite3

import pytest
from test_balance_observations import BalanceLedger, february
from test_decisions import ALL_TABLES, BALANCE_TABLES, REAL_LEDGER_TABLES
from test_one_sided_transfers import stated
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_15_TABLES = tuple(table for table in ALL_TABLES if table not in BALANCE_TABLES)


def set_back_to_version_15(path) -> None:
    conn = connect(path)
    for table in (*REAL_LEDGER_TABLES, *BALANCE_TABLES):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 15")
    conn.close()


@pytest.fixture
def populated(tmp_path, capsys):
    """Checking A and savings S, holding February's rows and a one-sided transfer."""
    ledger = BalanceLedger(tmp_path, capsys)
    ledger.add_account("S", "savings")
    ledger.rows("feb.csv", "X1,2026-01-30,2026-02-01,SYNTHETIC SHOP,-20.00,POSTED",
                "X2,2026-02-27,2026-02-28,SYNTHETIC REFUND,3.00,POSTED")
    stated(ledger)
    set_back_to_version_15(ledger.path)
    return ledger


class TestMigration:
    def test_it_adds_empty_tables_and_makes_no_account_stale(self, populated, tmp_path):
        before = populated.dump(VERSION_15_TABLES)
        assert markers(populated) == ["A"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "sixteen", 16)) == 16
        for table in BALANCE_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_15_TABLES) == before
        assert markers(populated) == ["A"]
        assert "have not been reconciled" not in populated.totals()

    def test_observations_work_after_it(self, populated):
        assert populated.run("migrate")[0] == 0
        populated.record_ok("2026-01-31", "100.00")
        populated.record_ok("2026-02-28", "83.00")
        assert populated.outcomes() == [("2026-01-31", "2026-02-28", "agrees")]

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 16)
        sixteenth = load_migrations()[15].path
        (folder / sixteenth.name).write_text(sixteenth.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_15_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 15
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(BALANCE_TABLES)
        conn.close()
        assert populated.dump(VERSION_15_TABLES) == before


@pytest.fixture
def history(tmp_path, capsys):
    """An observation recorded and undone on 31 January, then one active on each day."""
    ledger = BalanceLedger(tmp_path, capsys)
    ledger.add_account("S", "savings")
    observation = ledger.record_ok("2026-01-31", "99.00")
    assert ledger.undo_balance(observation)[0] == 0
    february(ledger)
    return ledger


def new_observation(conn, account, day="2026-03-31", observation_id="new"):
    conn.execute(
        """INSERT INTO balance_observation (id, account_id, observed_on, balance_cents)
           VALUES (?, ?, ?, 100)""",
        (observation_id, account, day),
    )


def made(conn, observation_id="new"):
    conn.execute("INSERT INTO balance_observation_event (balance_observation_id, event) "
                 "VALUES (?, 'made')", (observation_id,))


class TestAppendOnly:
    @pytest.mark.parametrize("statement", [
        "UPDATE balance_observation SET balance_cents = balance_cents",
        "DELETE FROM balance_observation",
        "INSERT INTO balance_observation SELECT * FROM balance_observation",
        "UPDATE balance_observation_event SET event = 'made'",
        "DELETE FROM balance_observation_event",
        "INSERT INTO balance_observation_event (balance_observation_id, event) "
        "SELECT balance_observation_id, event FROM balance_observation_event",
    ])
    def test_history_refuses_change(self, history, statement):
        before = history.dump(BALANCE_TABLES)
        conn = history.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert history.dump(BALANCE_TABLES) == before

    def test_one_active_observation_per_account_and_day(self, history):
        conn = history.conn()
        account = history.account_id("A")
        new_observation(conn, account, "2026-02-28")
        with pytest.raises(sqlite3.IntegrityError, match="one active balance observation per day"):
            made(conn)
        # 31 January's undone observation does not count, but the one active since does. Another
        # day, or the same day in another account, is another observation.
        new_observation(conn, account, "2026-01-31", "again")
        with pytest.raises(sqlite3.IntegrityError, match="one active balance observation per day"):
            made(conn, "again")
        new_observation(conn, account, "2026-03-31", "march")
        made(conn, "march")
        new_observation(conn, history.account_id("S"), "2026-02-28", "savings")
        made(conn, "savings")
        conn.close()

    def test_an_undone_observation_frees_its_day(self, tmp_path, capsys):
        ledger = BalanceLedger(tmp_path, capsys)
        observation = ledger.record_ok("2026-01-31", "99.00")
        conn = ledger.conn()
        new_observation(conn, ledger.account_id("A"), "2026-01-31")
        with pytest.raises(sqlite3.IntegrityError, match="one active balance observation per day"):
            made(conn)
        conn.execute("INSERT INTO balance_observation_event (balance_observation_id, event) "
                     "VALUES (?, 'undone')", (observation,))
        made(conn)
        conn.close()

    @pytest.mark.parametrize("day", ["2026-02-30", "2026-2-28", "20260228", "2026-02-28 "])
    def test_a_day_must_be_a_date(self, history, day):
        conn = history.conn()
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            new_observation(conn, history.account_id("A"), day)
        new_observation(conn, history.account_id("A"), "2026-03-31")
        conn.close()

    def test_an_amount_is_whole_cents(self, history):
        conn = history.conn()
        insert = """INSERT INTO balance_observation (id, account_id, observed_on, balance_cents)
                    VALUES ('new', ?, '2026-03-31', ?)"""
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, (history.account_id("A"), 1.5))
        conn.execute(insert, (history.account_id("A"), 150))
        conn.close()
