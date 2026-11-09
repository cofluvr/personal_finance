"""Migration 0014 on a populated ledger, and its append-only tables (X12, D-054).

A ledger built at the latest version, with the empty tables of 0014 and 0015 dropped and set back
to version 13, is a version 13 ledger: 0014 creates tables and clears markers only. Migration stops
at 14, so that only 0014 is tested.
"""

import sqlite3

import pytest
from test_classifications import against_its_direction
from test_decisions import ALL_TABLES, BACKUP_TABLES, BALANCE_TABLES, ONE_SIDED_TABLES, TRANSFER_TABLES, REAL_LEDGER_TABLES
from test_supersession import holding
from test_transfers import IN_ROW, OUT_ROW, TransferLedger, matched

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_13_TABLES = tuple(table for table in ALL_TABLES
                          if table not in (*TRANSFER_TABLES, *ONE_SIDED_TABLES, *BALANCE_TABLES))
VERSION_13_KEPT = tuple(table for table in VERSION_13_TABLES if table != "account_reconciliation")


def set_back_to_version_13(path) -> None:
    conn = connect(path)
    for table in (*BACKUP_TABLES, *REAL_LEDGER_TABLES, *BALANCE_TABLES, *ONE_SIDED_TABLES, *TRANSFER_TABLES):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.execute(f"DROP TABLE {table}")
    conn.execute("PRAGMA user_version = 13")
    conn.close()


def migrations_up_to(folder, version):
    folder.mkdir()
    for migration in load_migrations()[:version]:
        (folder / migration.path.name).write_text(migration.path.read_text())
    return folder


def stored_against_its_direction(ledger, name):
    """What 0013's rule wrote for a card payment received on a card: unclassified as against its
    direction. The rule of 0014 would apply it, so the row is set back by hand."""
    conn = ledger.conn()
    conn.execute(
        """UPDATE transaction_classification SET state = 'against_direction', financial_type = NULL
           WHERE transaction_id = ?""",
        (holding(ledger, name),),
    )
    conn.close()


@pytest.fixture
def populated(tmp_path, capsys):
    """A checking account with a refund against its direction, which 0014 does not settle, and a
    card holding a card payment received, which 0013 left against its direction."""
    ledger = TransferLedger(tmp_path, capsys)
    against_its_direction(ledger)
    ledger.add_account("Card", "credit_card")
    ledger.card("card.csv", "01/12/2026,SYNTHETIC PAYMENT,,6.50", account="Card")
    ledger.classify_ok(holding(ledger, "card.csv"), "card_payment", account="Card")
    stored_against_its_direction(ledger, "card.csv")
    set_back_to_version_13(ledger.path)
    return ledger


def markers(ledger):
    conn = ledger.conn()
    found = sorted(row[0] for row in conn.execute(
        """SELECT account.display_name FROM account_reconciliation marker
           JOIN account ON account.id = marker.account_id"""
    ))
    conn.close()
    return found


class TestMigration:
    def test_it_adds_empty_tables_and_marks_only_the_card_as_not_current(self, populated, tmp_path):
        before = populated.dump(VERSION_13_KEPT)
        assert markers(populated) == ["A", "Card"]
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "fourteen", 14)) == 14
        for table in TRANSFER_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_13_KEPT) == before
        assert markers(populated) == ["A"]
        # Commands refuse a ledger below the latest version, and later migrations clear no marker.
        assert populated.run("migrate")[0] == 0
        assert markers(populated) == ["A"]
        assert "1 accounts have not been reconciled" in populated.totals()

    def test_reconcile_then_settles_the_card_payment(self, populated):
        assert populated.run("migrate")[0] == 0
        assert populated.run("reconcile")[0] == 0
        assert sorted(state for _, state, _ in populated.outcomes()) == [
            "against_direction", "applied"]
        assert ("card_payment", "1", "6.50") in populated.types()

    def test_a_ledger_with_nothing_against_its_direction_keeps_every_marker(self, tmp_path, capsys):
        ledger = TransferLedger(tmp_path, capsys)
        ledger.add_account("Card", "credit_card")
        ledger.card("a.csv", OUT_ROW)
        ledger.card("card.csv", IN_ROW, account="Card")
        ledger.classify_ok(holding(ledger, "card.csv"), "card_payment", account="Card")
        set_back_to_version_13(ledger.path)
        assert ledger.run("migrate")[0] == 0
        assert markers(ledger) == ["A", "Card"]

    def test_transfers_work_after_it(self, populated):
        assert populated.run("migrate")[0] == 0
        assert populated.run("reconcile")[0] == 0
        populated.add_account("S", "savings")
        matched(populated)

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 14)
        fourteenth = load_migrations()[13].path
        (folder / fourteenth.name).write_text(fourteenth.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_13_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction
        assert schema_version(conn) == 13
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(TRANSFER_TABLES)
        conn.close()
        assert populated.dump(VERSION_13_TABLES) == before


@pytest.fixture
def history(tmp_path, capsys):
    """A match made and undone, and one active."""
    ledger = TransferLedger(tmp_path, capsys)
    ledger.add_account("S", "savings")
    match, _, _ = matched(ledger)
    assert ledger.undo_match(match)[0] == 0
    ledger.match_ok(holding(ledger, "out.csv"), holding(ledger, "in.csv"))
    return ledger


def ids(conn):
    accounts = dict(conn.execute("SELECT display_name, id FROM account"))
    records = dict(conn.execute(
        """SELECT document.file_name, record.id FROM source_record record
           JOIN source_document document ON document.id = record.source_document_id"""
    ))
    return accounts, records


class TestAppendOnly:
    @pytest.mark.parametrize("statement", [
        "UPDATE transfer_match SET created_at = created_at",
        "DELETE FROM transfer_match",
        "INSERT INTO transfer_match SELECT * FROM transfer_match",
        "UPDATE transfer_match_side SET target_revision = 't7-0'",
        "DELETE FROM transfer_match_side",
        "INSERT INTO transfer_match_side SELECT * FROM transfer_match_side",
        "UPDATE transfer_match_record SET source_record_id = source_record_id",
        "DELETE FROM transfer_match_record",
        "INSERT INTO transfer_match_record SELECT * FROM transfer_match_record",
        "UPDATE transfer_match_event SET event = 'made'",
        "DELETE FROM transfer_match_event",
        "INSERT INTO transfer_match_event (match_id, event) "
        "SELECT match_id, event FROM transfer_match_event",
    ])
    def test_history_refuses_change(self, history, statement):
        stored = TRANSFER_TABLES[:4]
        before = history.dump(stored)
        conn = history.conn()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(statement)
        conn.close()
        assert history.dump(stored) == before

    def new_match(self, conn, accounts, records, inflow_account="S"):
        conn.execute("INSERT INTO transfer_match (id) VALUES ('new')")
        conn.execute(
            """INSERT INTO transfer_match_side VALUES ('new', 'outflow', ?, 't', 't7-0')""",
            (accounts["A"],),
        )
        conn.execute(
            """INSERT INTO transfer_match_side VALUES ('new', 'inflow', ?, 't', 't7-0')""",
            (accounts[inflow_account],),
        )

    def test_a_match_joins_two_accounts(self, history):
        conn = history.conn()
        accounts, _ = ids(conn)
        conn.execute("INSERT INTO transfer_match (id) VALUES ('new')")
        conn.execute("INSERT INTO transfer_match_side VALUES ('new', 'outflow', ?, 't', 't7-0')",
                     (accounts["A"],))
        with pytest.raises(sqlite3.IntegrityError, match="joins two accounts"):
            conn.execute("INSERT INTO transfer_match_side VALUES ('new', 'inflow', ?, 't', 't7-0')",
                         (accounts["A"],))
        conn.execute("INSERT INTO transfer_match_side VALUES ('new', 'inflow', ?, 't', 't7-0')",
                     (accounts["S"],))
        conn.close()

    def test_a_side_binds_records_of_its_own_account(self, history):
        conn = history.conn()
        accounts, records = ids(conn)
        self.new_match(conn, accounts, records)
        insert = "INSERT INTO transfer_match_record VALUES ('new', ?, ?)"
        with pytest.raises(sqlite3.IntegrityError, match="its side's account"):
            conn.execute(insert, ("outflow", records["in.csv"]))
        conn.execute(insert, ("outflow", records["out.csv"]))
        conn.close()

    @pytest.mark.parametrize("side", ["sideways", None])
    def test_a_side_is_outflow_or_inflow(self, history, side):
        conn = history.conn()
        accounts, _ = ids(conn)
        conn.execute("INSERT INTO transfer_match (id) VALUES ('new')")
        insert = "INSERT INTO transfer_match_side VALUES ('new', ?, ?, 't', 't7-0')"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, (side, accounts["A"]))
        conn.execute(insert, ("outflow", accounts["A"]))
        conn.close()

    @pytest.mark.parametrize(("state", "both"), [
        ("applied", False), ("conflict", True), ("matched", True),
    ])
    def test_a_derived_row_must_fit_its_state(self, history, state, both):
        conn = history.conn()
        # Derived and rewritten wherever classifications are, so it may be cleared.
        conn.execute("DELETE FROM transfer_match_effect")
        (match,) = conn.execute(
            """SELECT match_id FROM transfer_match_side
               WHERE match_id NOT IN (SELECT match_id FROM transfer_match_event
                                      WHERE event = 'undone') LIMIT 1""").fetchone()
        outflow, inflow = conn.execute(
            "SELECT id FROM ledger_transaction ORDER BY amount_cents").fetchall()
        insert = "INSERT INTO transfer_match_effect VALUES (?, ?, ?, ?)"
        sides = (outflow[0], inflow[0]) if both else (None, None)
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(insert, (match, state, *sides))
        conn.execute(insert, (match, "applied", outflow[0], inflow[0]))
        conn.close()

    def test_no_transaction_is_a_side_of_two_applied_matches(self, history):
        conn = history.conn()
        conn.execute("DELETE FROM transfer_match_effect")
        matches = [row[0] for row in conn.execute("SELECT id FROM transfer_match ORDER BY id")]
        outflow, inflow = (row[0] for row in conn.execute(
            "SELECT id FROM ledger_transaction ORDER BY amount_cents"))
        insert = "INSERT INTO transfer_match_effect VALUES (?, 'applied', ?, ?)"
        conn.execute(insert, (matches[0], outflow, inflow))
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            conn.execute(insert, (matches[1], outflow, inflow))
        conn.execute("INSERT INTO transfer_match_effect VALUES (?, 'conflict', NULL, NULL)",
                     (matches[1],))
        conn.close()
