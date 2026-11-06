import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from personal_finance.db import migrate as migrate_module
from personal_finance.db.migrate import (
    MigrationError,
    connect,
    create_database,
    load_migrations,
    migrate,
    schema_version,
)


def write_migrations(directory, **files):
    directory.mkdir()
    for name, sql in files.items():
        (directory / f"{name}.sql").write_text(sql)
    return directory


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row[0] for row in rows}


def test_new_database_is_at_the_latest_version(conn):
    assert schema_version(conn) == len(load_migrations())


def test_new_database_has_the_expected_tables(conn):
    assert table_names(conn) == {
        "account",
        "document_coverage",
        "import_attempt",
        "import_run",
        "ledger_transaction",
        "record_parse",
        "review_issue",
        "review_issue_subject",
        "source_document",
        "source_record",
        "transaction_source",
    }


def test_every_table_is_strict(conn):
    rows = conn.execute("PRAGMA table_list").fetchall()
    tables = [row for row in rows if row[1] in table_names(conn) and row[0] == "main"]
    assert tables
    assert all(row[5] == 1 for row in tables)


def test_migrating_again_changes_nothing(conn):
    before = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    version = schema_version(conn)
    assert migrate(conn) == version
    assert conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == before


def test_foreign_keys_are_on_for_every_connection(db_path):
    conn = connect(db_path)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_connect_does_not_create_a_missing_database(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        connect(path)
    assert not path.exists()


def test_paths_with_spaces_and_special_characters_work(tmp_path):
    path = tmp_path / "a folder #1?" / "ledger.db"
    path.parent.mkdir()
    create_database(path)
    conn = connect(path)
    assert schema_version(conn) >= 1
    conn.close()


def test_create_refuses_to_overwrite_an_existing_file(tmp_path):
    path = tmp_path / "ledger.db"
    path.write_text("existing work")
    with pytest.raises(FileExistsError):
        create_database(path)
    assert path.read_text() == "existing work"


def test_new_database_is_readable_only_by_its_owner(db_path):
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600


def test_database_newer_than_the_code_is_refused(conn):
    conn.execute("PRAGMA user_version = 9999")
    with pytest.raises(MigrationError, match="newer"):
        migrate(conn)


def test_failed_migration_rolls_back_entirely(tmp_path):
    migrations = write_migrations(
        tmp_path / "migrations",
        **{
            "0001_good": "CREATE TABLE good (id INTEGER) STRICT;",
            "0002_bad": "CREATE TABLE partial (id INTEGER) STRICT;\nNOT VALID SQL;",
        },
    )
    path = tmp_path / "ledger.db"
    with pytest.raises(sqlite3.Error):
        create_database(path, migrations)

    conn = connect(path)
    assert schema_version(conn) == 1
    assert table_names(conn) == {"good"}
    assert not conn.in_transaction
    conn.close()


def test_later_migration_upgrades_existing_data(tmp_path):
    migrations = write_migrations(
        tmp_path / "migrations",
        **{"0001_first": "CREATE TABLE item (id INTEGER PRIMARY KEY) STRICT;"},
    )
    path = tmp_path / "ledger.db"
    create_database(path, migrations)
    conn = connect(path)
    conn.execute("INSERT INTO item (id) VALUES (7)")

    (migrations / "0002_second.sql").write_text("ALTER TABLE item ADD COLUMN note TEXT;")

    assert migrate(conn, migrations) == 2
    assert conn.execute("SELECT id, note FROM item").fetchall() == [(7, None)]
    conn.close()


def test_gap_in_migration_numbers_is_refused(tmp_path):
    migrations = write_migrations(
        tmp_path / "migrations", **{"0001_a": "SELECT 1;", "0003_c": "SELECT 1;"}
    )
    with pytest.raises(MigrationError, match="expected migration 0002"):
        load_migrations(migrations)


def test_badly_named_migration_is_refused(tmp_path):
    migrations = write_migrations(tmp_path / "migrations", **{"first": "SELECT 1;"})
    with pytest.raises(MigrationError, match="invalid migration file name"):
        load_migrations(migrations)


def test_migration_applied_while_waiting_for_the_lock_is_skipped(conn, monkeypatch):
    latest = schema_version(conn)
    stale_reads = [0]

    def version_seen(connection):
        return stale_reads.pop() if stale_reads else schema_version(connection)

    monkeypatch.setattr(migrate_module, "schema_version", version_seen)

    assert migrate(conn) == latest


def test_concurrent_migrations_apply_once(tmp_path):
    path = tmp_path / "ledger.db"
    path.touch(mode=0o600)
    script = (
        "import sys; from pathlib import Path\n"
        "from personal_finance.db.migrate import connect, migrate\n"
        "print(migrate(connect(Path(sys.argv[1]))))\n"
    )
    env = {"PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    workers = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(path)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    results = [worker.communicate(timeout=30) + (worker.returncode,) for worker in workers]

    assert [code for _, _, code in results] == [0, 0, 0, 0], results
    conn = connect(path)
    assert schema_version(conn) == len(load_migrations())
    conn.close()
