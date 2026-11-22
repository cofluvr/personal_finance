"""Migration 0036, pairing and sync, on a populated ledger (YA1, D-067 G10, D-076 point 7), using
synthetic data only. Its tables are empty, nothing else shown changes, a ledger at 35 is refused
until migrate, a failure leaves everything as it was, and every table is append-only, each check
refusing on its own with a control insert that succeeds."""

import sqlite3

import pytest
from test_decisions import CAFE, SNAPSHOT_TABLES, SYNC_TABLES, drop_sync_tables
from test_funds import FundLedger
from test_scenario_migration import shown_now
from test_snapshot_migration import INSERT as SNAPSHOT_INSERT
from test_snapshot_migration import ROW as SNAPSHOT_ROW
from test_snapshot_migration import VERSION_34_TABLES
from test_transfer_migration import markers, migrations_up_to

from personal_finance.db.migrate import connect, load_migrations, migrate, schema_version

VERSION_35_TABLES = (*VERSION_34_TABLES, *SNAPSHOT_TABLES)


@pytest.fixture
def populated(tmp_path, capsys):
    """A purchase, a possible duplicate, a goal, a scenario and a snapshot record, set back to
    35."""
    ledger = FundLedger(tmp_path, capsys)
    ledger.card("a.csv", CAFE)
    ledger.card("b.csv", CAFE)
    ledger.add_fund_ok(name="House", monthly="100.00", as_of="2026-03-15")
    assert ledger.run("scenario", "add", "--name", "Move")[0] == 0
    conn = connect(ledger.path)
    conn.execute(SNAPSHOT_INSERT, SNAPSHOT_ROW)
    conn.close()
    ledger.shown_before = [*shown_now(ledger), ledger.run("snapshots")]
    conn = connect(ledger.path)
    drop_sync_tables(conn)
    conn.execute("PRAGMA user_version = 35")
    conn.close()
    return ledger


class TestMigration:  # YA1, G10
    def test_it_adds_empty_tables_and_changes_nothing_shown(self, populated, tmp_path):
        before = populated.dump(VERSION_35_TABLES)
        conn = connect(populated.path)
        assert migrate(conn, migrations_up_to(tmp_path / "thirty-six", 36)) == 36
        for table in SYNC_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        conn.close()
        assert populated.dump(VERSION_35_TABLES) == before
        assert markers(populated) == ["A"]
        assert populated.run("migrate")[0] == 0
        assert [*shown_now(populated), populated.run("snapshots")] == populated.shown_before

    def test_a_ledger_at_35_is_refused_until_migrate(self, populated):
        code, _, err = populated.run("sync", "devices")
        assert code == 2 and "migrate" in err
        assert populated.run("migrate")[0] == 0
        assert populated.run("sync", "devices")[0] == 0

    def test_a_failure_leaves_everything_as_it_was(self, populated, tmp_path):
        folder = migrations_up_to(tmp_path / "broken", 36)
        newest = load_migrations()[35].path
        assert newest.name == "0036_sync.sql"
        (folder / newest.name).write_text(newest.read_text() + "SELECT no_such_function();")
        before = populated.dump(VERSION_35_TABLES)
        conn = connect(populated.path)
        with pytest.raises(sqlite3.Error):
            migrate(conn, folder)
        assert not conn.in_transaction and schema_version(conn) == 35
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert not names & set(SYNC_TABLES)
        conn.close()
        assert populated.dump(VERSION_35_TABLES) == before


IDENTITY = "11111111-1111-4111-8111-111111111111"
WINDOW = "22222222-2222-4222-8222-222222222222"
DEVICE = "33333333-3333-4333-8333-333333333333"
DELIVERY = "44444444-4444-4444-8444-444444444444"
CLOSES_AT = "2026-05-04T17:02:00.000Z"

ROWS = {
    "sync_identity": ("INSERT INTO sync_identity (identity_id, certificate_sha256) "
                      "VALUES (:identity_id, :certificate_sha256)",
                      {"identity_id": IDENTITY, "certificate_sha256": "a" * 64}),
    "sync_identity_event": ("INSERT INTO sync_identity_event (identity_id, event) "
                            "VALUES (:identity_id, :event)",
                            {"identity_id": IDENTITY, "event": "retired"}),
    "pairing_window": ("INSERT INTO pairing_window (window_id, identity_id, secret_sha256, "
                       "address, port, closes_at) VALUES (:window_id, :identity_id, "
                       ":secret_sha256, :address, :port, :closes_at)",
                       {"window_id": WINDOW, "identity_id": IDENTITY, "secret_sha256": "b" * 64,
                        "address": "192.168.1.20", "port": 8443, "closes_at": CLOSES_AT}),
    "pairing_window_event": ("INSERT INTO pairing_window_event (window_id, event) "
                             "VALUES (:window_id, :event)", {"window_id": WINDOW,
                                                             "event": "used"}),
    "paired_device": ("INSERT INTO paired_device (device_id, name, secret_sha256, identity_id, "
                      "window_id) VALUES (:device_id, :name, :secret_sha256, :identity_id, "
                      ":window_id)",
                      {"device_id": DEVICE, "name": "Phone", "secret_sha256": "c" * 64,
                       "identity_id": IDENTITY, "window_id": WINDOW}),
    "paired_device_event": ("INSERT INTO paired_device_event (device_id, event) "
                            "VALUES (:device_id, :event)", {"device_id": DEVICE,
                                                            "event": "revoked"}),
    "sync_delivery": ("INSERT INTO sync_delivery (delivery_id, device_id, snapshot_id, "
                      "content_sha256) VALUES (:delivery_id, :device_id, :snapshot_id, "
                      ":content_sha256)",
                      {"delivery_id": DELIVERY, "device_id": DEVICE,
                       "snapshot_id": SNAPSHOT_ROW["snapshot_id"], "content_sha256": "a" * 64}),
    "sync_acknowledgement": ("INSERT INTO sync_acknowledgement (delivery_id) "
                             "VALUES (:delivery_id)", {"delivery_id": DELIVERY}),
}


def second(uuid_text: str, digit: str) -> str:
    return digit * 8 + uuid_text[8:]


@pytest.fixture
def recorded(tmp_path, capsys):
    """One row in every table, in the order their references need, and a second identity,
    window, device and delivery with nothing on them, for the control rows."""
    ledger = FundLedger(tmp_path, capsys)
    conn = ledger.conn()
    conn.execute(SNAPSHOT_INSERT, SNAPSHOT_ROW)
    for insert, row in ROWS.values():
        conn.execute(insert, row)
    for table, changes in (
            ("sync_identity", {"identity_id": second(IDENTITY, "5"),
                               "certificate_sha256": "5" * 64}),
            ("pairing_window", {"window_id": second(WINDOW, "5"), "secret_sha256": "5" * 64}),
            ("pairing_window", {"window_id": second(WINDOW, "6"), "secret_sha256": "6" * 64}),
            ("paired_device", {"device_id": second(DEVICE, "5"), "secret_sha256": "5" * 64,
                               "window_id": second(WINDOW, "5")}),
            ("sync_delivery", {"delivery_id": second(DELIVERY, "5"),
                               "device_id": second(DEVICE, "5")})):
        insert, row = ROWS[table]
        conn.execute(insert, {**row, **changes})
    conn.close()
    return ledger


# A new row for each table that succeeds on the recorded ledger: the control for its checks.
CONTROL = {
    "sync_identity": {"identity_id": second(IDENTITY, "9"), "certificate_sha256": "9" * 64},
    "sync_identity_event": {"identity_id": second(IDENTITY, "5"), "event": "retired"},
    "pairing_window": {**ROWS["pairing_window"][1], "window_id": second(WINDOW, "9"),
                       "secret_sha256": "9" * 64, "address": "10.0.0.1", "port": 65535},
    "pairing_window_event": {"window_id": second(WINDOW, "5"), "event": "failed"},
    "paired_device": {"device_id": second(DEVICE, "9"), "name": "x" * 64,
                      "secret_sha256": "9" * 64, "identity_id": IDENTITY,
                      "window_id": second(WINDOW, "6")},
    "paired_device_event": {"device_id": second(DEVICE, "5"), "event": "revoked"},
    "sync_delivery": {"delivery_id": second(DELIVERY, "9"), "device_id": second(DEVICE, "5"),
                      "snapshot_id": "1" * 36, "content_sha256": "0" * 64},
    "sync_acknowledgement": {"delivery_id": second(DELIVERY, "5")},
}


def inserted(ledger, table, changes=None):
    """The table's control row with these changes, inserted and rolled back."""
    conn = ledger.conn()
    conn.execute("BEGIN")
    try:
        if table == "sync_delivery":
            conn.execute(SNAPSHOT_INSERT, {**SNAPSHOT_ROW, "snapshot_id": "1" * 36})
        conn.execute(ROWS[table][0], {**CONTROL[table], **(changes or {})})
    finally:
        conn.execute("ROLLBACK")
        conn.close()


class TestTheTables:  # YA1, G2
    @pytest.mark.parametrize("table", list(ROWS))
    def test_rows_refuse_update_delete_and_replace(self, recorded, table):
        before = recorded.dump(SYNC_TABLES)
        conn = recorded.conn()
        column = next(iter(ROWS[table][1]))
        for each in (f"UPDATE {table} SET {column} = {column}", f"DELETE FROM {table}",
                     f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(each)
        conn.close()
        assert recorded.dump(SYNC_TABLES) == before

    @pytest.mark.parametrize("table", list(ROWS))
    def test_a_control_row_succeeds(self, recorded, table):
        inserted(recorded, table)

    @pytest.mark.parametrize("table, changes", [
        ("sync_identity", {"identity_id": "short"}),
        ("sync_identity", {"certificate_sha256": "A" * 64}),
        ("sync_identity", {"certificate_sha256": "a" * 63}),
        ("sync_identity_event", {"event": "revoked"}),
        ("pairing_window", {"window_id": "short"}),
        ("pairing_window", {"secret_sha256": "g" * 64}),
        ("pairing_window", {"address": "10.0.0.1a"}),
        ("pairing_window", {"address": "1.2.3"}),
        ("pairing_window", {"port": 1023}),
        ("pairing_window", {"port": 65536}),
        ("pairing_window", {"closes_at": "2026-05-04 17:02:00"}),
        ("pairing_window_event", {"event": "opened"}),
        ("paired_device", {"device_id": "short"}),
        ("paired_device", {"name": ""}),
        ("paired_device", {"name": "x" * 65}),
        ("paired_device", {"secret_sha256": "9" * 65}),
        ("paired_device_event", {"event": "paired"}),
        ("sync_delivery", {"delivery_id": "short"}),
        ("sync_delivery", {"content_sha256": "Z" * 64}),
    ])
    def test_each_check_refuses_alone(self, recorded, table, changes):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            inserted(recorded, table, changes)

    @pytest.mark.parametrize("event", ["used", "closed"])
    def test_a_window_is_used_once_and_closed_once(self, recorded, event):
        """WINDOW is used; the second window has none of these, so the control succeeds."""
        conn = recorded.conn()
        insert = ROWS["pairing_window_event"][0]
        conn.execute(insert, {"window_id": second(WINDOW, "5"), "event": event})
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(insert, {"window_id": second(WINDOW, "5"), "event": event})
        conn.close()

    @pytest.mark.parametrize("changes", [
        {"device_id": DEVICE, "snapshot_id": SNAPSHOT_ROW["snapshot_id"]},
        {"delivery_id": DELIVERY}])
    def test_a_device_and_snapshot_are_delivered_once(self, recorded, changes):
        with pytest.raises(sqlite3.DatabaseError, match="append-only|UNIQUE"):
            inserted(recorded, "sync_delivery", changes)

    def test_a_delivery_is_not_replaced_under_a_new_id(self, recorded):
        """INSERT OR REPLACE with a new ID but the same device and snapshot would delete the
        first delivery without its trigger firing."""
        before = recorded.dump(SYNC_TABLES)
        conn = recorded.conn()
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(ROWS["sync_delivery"][0].replace("INSERT", "INSERT OR REPLACE"),
                         {**ROWS["sync_delivery"][1], "delivery_id": second(DELIVERY, "9")})
        conn.close()
        assert recorded.dump(SYNC_TABLES) == before
