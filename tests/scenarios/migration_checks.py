"""The checks every migration's tests make on a populated ledger (D-067 G10, D-082 S2), shared so
each migration's test file states only its version and tables. Each helper asserts; the test that
calls it keeps its own name, so every migration still has its own test of each."""

import sqlite3

import pytest

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version


def migrations_up_to(folder, version):
    """A folder of the migrations up to version, so migrate stops there."""
    folder.mkdir()
    for migration in load_migrations()[:version]:
        (folder / migration.path.name).write_text(migration.path.read_text())
    return folder


def markers(ledger):
    """The display names of the accounts marked as not reconciled under the current rules."""
    conn = ledger.conn()
    found = sorted(row[0] for row in conn.execute(
        """SELECT account.display_name FROM account_reconciliation marker
           JOIN account ON account.id = marker.account_id"""
    ))
    conn.close()
    return found


def assert_it_adds_empty_tables_and_changes_nothing_shown(
        ledger, tmp_path, *, version: int, tables_before, new_tables, shown_now) -> None:
    """Migrating to version adds new_tables empty, leaves tables_before and the real-ledger
    markers as they were, and after pf migrate every command shown_now runs prints what it did
    before the set-back (ledger.shown_before)."""
    before = ledger.dump(tables_before)
    assert markers(ledger) == ["A"]
    conn = connect(ledger.path)
    assert migrate(conn, migrations_up_to(tmp_path / f"up-to-{version}", version)) == version
    for table in new_tables:
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    conn.close()
    assert ledger.dump(tables_before) == before
    assert markers(ledger) == ["A"]
    assert ledger.run("migrate")[0] == 0
    assert shown_now(ledger) == ledger.shown_before


def assert_refused_until_migrate(ledger, *words: str) -> None:
    """A ledger set back one version refuses the command until pf migrate, then runs it."""
    code, _, err = ledger.run(*words)
    assert code == 2 and "migrate" in err
    assert ledger.run("migrate")[0] == 0
    assert ledger.run(*words)[0] == 0


def assert_a_failure_leaves_everything_as_it_was(
        ledger, tmp_path, *, version: int, migration_name: str, tables_before,
        new_tables) -> None:
    """Migration version, named migration_name, with a failing statement added at its end: the
    ledger stays at the version before, holds none of new_tables, and tables_before are
    unchanged."""
    folder = migrations_up_to(tmp_path / "broken", version)
    newest = load_migrations()[version - 1].path
    assert newest.name == migration_name
    (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
    before = ledger.dump(tables_before)
    conn = connect(ledger.path)
    with pytest.raises(sqlite3.Error):
        migrate(conn, folder)
    assert not conn.in_transaction
    assert schema_version(conn) == version - 1
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert not names & set(new_tables)
    conn.close()
    assert ledger.dump(tables_before) == before


def assert_rows_refuse_update_delete_and_replace(ledger, table: str, dumped_tables) -> None:
    """table's rows refuse an update, a delete and a replace, and dumped_tables are unchanged."""
    before = ledger.dump(dumped_tables)
    conn = ledger.conn()
    for statement in (f"UPDATE {table} SET rowid = rowid", f"DELETE FROM {table}",
                      f"INSERT INTO {table} SELECT * FROM {table}"):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
    conn.close()
    assert ledger.dump(dumped_tables) == before
