"""Serving the snapshot to paired devices, using synthetic data only (YB1 to YB3, D-076 points 5
to 8, the M20.2 slice plan). The reference client receives exactly the snapshot serve built,
verifies, installs and acknowledges it; deliveries and acknowledgements are recorded once; a
device is checked on every request; serve stops at its limits and writes nothing but
deliveries."""

import hashlib
import json
import os
import threading
import time
from datetime import date

import pytest
from sync_harness import (
    Clock,
    LoopbackSyncServer,
    ScriptedServer,
    SyncLedger,
    served_here,
    with_connect,
)
from sync_reference_client import SyncFailed
from test_decisions import ALL_TABLES, SNAPSHOT_TABLES, SYNC_TABLES

from personal_finance import cli
from personal_finance.sync import server as sync_server
from personal_finance.sync.server import AUTHENTICATION_FAILURE_LIMIT

AS_OF = date(2026, 5, 4)


@pytest.fixture
def ledger(tmp_path, capsys):
    built = SyncLedger(tmp_path, capsys)
    built.made = built.make_identity()
    built.client = built.paired_client(tmp_path / "phone")
    return built


@pytest.fixture
def serving(ledger):
    server = ledger.serving_server(AS_OF)
    ledger.connected(ledger.client, server)
    yield server
    ledger.client.connect.wait()
    server.server_close()
    server.conn.close()


class TestDelivery:  # YB1
    def test_the_client_receives_verifies_installs_and_acknowledges_the_snapshot(self, ledger,
                                                                                 serving):
        document = ledger.client.sync()
        assert ledger.client.installed_path.read_bytes() == serving.snapshot
        assert document["snapshot_id"] == serving.document["snapshot_id"]
        assert ledger.client.freshness() == "2026-05-04"
        ((delivery_id, device_id, snapshot_id, digest, _),) = ledger.table("sync_delivery")
        assert (device_id, snapshot_id, digest) == (
            ledger.client.device_id, document["snapshot_id"], document["content_sha256"])
        assert [row[0] for row in ledger.table("sync_acknowledgement")] == [delivery_id]
        assert serving.counts["served"] == serving.counts["acknowledged"] == 1

    def test_the_snapshot_is_recorded_once_without_a_path(self, ledger, serving):
        ledger.client.sync()
        ledger.client.sync()
        ((snapshot_id, version, as_of, window_days, generated_at, digest, _),) = ledger.table(
            "snapshot_record")
        assert (snapshot_id, version, as_of, window_days, generated_at, digest) == (
            serving.document["snapshot_id"], "1.0", "2026-05-04", 90,
            "2026-05-04T17:00:00.000Z", serving.document["content_sha256"])
        _, out, _ = ledger.run("snapshots")
        assert f"Snapshot {snapshot_id}: schema 1.0, as of 2026-05-04" in out

    def test_a_delivery_and_its_acknowledgement_are_recorded_once(self, ledger, serving):
        ledger.client.sync()
        ledger.client.sync()
        assert len(ledger.table("sync_delivery")) == len(ledger.table("sync_acknowledgement")) == 1
        assert serving.counts["served"] == serving.counts["acknowledged"] == 2

    def test_the_snapshot_is_the_one_serve_built_from_the_ledger(self, ledger, serving):
        """Built in one read transaction, as snapshot create builds it."""
        conn = ledger.conn()
        try:
            from personal_finance.snapshot.builder import build_snapshot

            rebuilt = build_snapshot(conn, AS_OF, 90, serving.document["snapshot_id"],
                                     "2026-05-04T17:00:00.000Z")
        finally:
            conn.close()
        assert rebuilt == serving.snapshot
        assert ledger.client.fetch().body == rebuilt

    def test_the_answer_carries_the_bytes_digest(self, ledger, serving):
        answer = ledger.client.fetch()
        assert answer.headers["snapshot-sha256"] == hashlib.sha256(answer.body).hexdigest()
        assert answer.headers["content-type"] == "application/json"
        assert answer.headers["cache-control"] == "no-store"

    @pytest.mark.parametrize("changes", [{"content_sha256": "0" * 64},
                                         {"snapshot_id": "11111111-1111-4111-8111-111111111111"}])
    def test_a_mismatched_acknowledgement_is_refused(self, ledger, serving, changes):
        ledger.client.fetch()
        values = {"snapshot_id": serving.document["snapshot_id"],
                  "content_sha256": serving.document["content_sha256"], **changes}
        answer = ledger.client.acknowledge(**values)
        assert (answer.status, answer.json()) == (400, {"error": "not_delivered"})
        assert ledger.table("sync_acknowledgement") == []
        # The control: the matching acknowledgement succeeds.
        assert ledger.client.acknowledge(serving.document["snapshot_id"],
                                         serving.document["content_sha256"]).status == 204

    def test_an_acknowledgement_before_any_delivery_is_refused(self, ledger, serving):
        answer = ledger.client.acknowledge(serving.document["snapshot_id"],
                                           serving.document["content_sha256"])
        assert answer.status == 400 and ledger.table("sync_acknowledgement") == []

    def test_another_devices_delivery_cannot_be_acknowledged(self, ledger, serving, tmp_path):
        ledger.client.fetch()
        other = ledger.connected(ledger.paired_client(tmp_path / "other", name="Other"), serving)
        answer = other.acknowledge(serving.document["snapshot_id"],
                                   serving.document["content_sha256"])
        assert answer.status == 400 and ledger.table("sync_acknowledgement") == []
        other.connect.wait()


class CorruptingServer(LoopbackSyncServer):
    """Sends one byte changed, digest header and all, as a broken network might."""

    def __init__(self, *options, **named):
        super().__init__(*options, **named)
        self.snapshot = self.snapshot[:-2] + b"!" + self.snapshot[-1:]


class TestTheClientKeepsTheLastValidSnapshot:  # point 8
    def test_a_failed_check_installs_nothing_and_acknowledges_nothing(self, ledger, serving,
                                                                       tmp_path):
        ledger.client.sync()
        installed = ledger.client.installed_path.read_bytes()
        bad = CorruptingServer("127.0.0.1", 0, ledger.context(), ledger.server_conn(),
                               mode=sync_server.SERVE, minutes=1, utc_now=Clock(),
                               document=serving.document, snapshot=serving.snapshot)
        ledger.connected(ledger.client, bad)
        with pytest.raises(SyncFailed, match="do not match their digest"):
            ledger.client.sync()
        ledger.client.connect.wait()
        assert ledger.client.installed_path.read_bytes() == installed
        assert bad.counts["acknowledged"] == 0
        assert sorted(os.listdir(ledger.client.install_folder)) == ["snapshot.json"]
        bad.server_close()

    def test_an_unsupported_major_is_an_actionable_error_keeping_the_last(self, ledger, serving):
        ledger.client.sync()
        before = ledger.client.installed_path.read_bytes()
        answer = ledger.client.fetch(majors="2")
        assert (answer.status, answer.json()) == (
            409, {"error": "unsupported_snapshot_major", "supported_majors": [1]})
        assert ledger.client.installed_path.read_bytes() == before


class TestAuthentication:  # YB2, point 6
    def without(self, client):
        client.device_secret = None
        return client

    @pytest.mark.parametrize("authorization", [
        None, "Bearer", "Bearer x.y", "Basic abc",
        "Bearer 33333333-3333-4333-8333-333333333333." + "A" * 43])
    def test_no_secret_or_a_malformed_one_gives_401(self, ledger, serving, authorization):
        from sync_reference_client import exchange, request_bytes

        headers = ("Accept-Snapshot-Major: 1",) + (
            (f"Authorization: {authorization}",) if authorization else ())
        answer = exchange(ledger.client.connect(), ledger.client.fingerprint,
                          request_bytes("GET", "/v1/snapshot/latest", "h", headers=headers))
        assert (answer.status, answer.json()) == (401, {"error": "unauthorized"})
        assert ledger.table("sync_delivery") == []

    def test_a_wrong_secret_gives_401(self, ledger, serving):
        right = ledger.client.device_secret
        ledger.client.device_secret = right[:-1] + ("A" if right[-1] != "A" else "B")
        assert ledger.client.fetch().status == 401
        ledger.client.device_secret = right
        assert ledger.client.fetch().status == 200

    def test_revocation_applies_on_the_next_request_with_no_restart(self, ledger, serving):
        assert ledger.client.fetch().status == 200
        token = ledger.revoke_token(ledger.client.device_id)
        assert ledger.run("sync", "revoke", ledger.client.device_id, "--revision", token)[0] == 0
        assert ledger.client.fetch().status == 401
        answer = ledger.client.acknowledge(serving.document["snapshot_id"],
                                           serving.document["content_sha256"])
        assert answer.status == 401

    def test_a_retired_identitys_device_gives_401_even_unrevoked(self, ledger, serving):
        """Rotation revokes every device too, so this state is made by hand: the identity check
        refuses alone, and the control before it shows the device served."""
        assert ledger.client.fetch().status == 200
        conn = ledger.conn()
        conn.execute("INSERT INTO sync_identity_event (identity_id, event) VALUES (?, 'retired')",
                     (ledger.made.identity_id,))
        conn.execute("INSERT INTO sync_identity (identity_id, certificate_sha256) VALUES (?, ?)",
                     ("99999999-9999-4999-8999-999999999999", "9" * 64))
        conn.close()
        assert ledger.table("paired_device_event") == []
        assert ledger.client.fetch().status == 401

    def test_a_device_of_a_retired_identity_gives_401(self, ledger, serving, tmp_path):
        assert ledger.run("sync", "identity", "rotate", "--revision", ledger.rotate_token())[0] == 0
        assert ledger.client.fetch().status == 401

    @pytest.mark.parametrize("majors", ["2", "0, 2", "", "one", "1;2", "1,,2"])
    def test_no_supported_major_gives_409_naming_it(self, ledger, serving, majors):
        answer = ledger.client.fetch(majors=majors)
        assert (answer.status, answer.json()["supported_majors"]) == (409, [1])

    @pytest.mark.parametrize("majors", ["1", "2, 1", "1,2"])
    def test_a_list_holding_1_is_served(self, ledger, serving, majors):
        assert ledger.client.fetch(majors=majors).status == 200

    def test_an_unauthenticated_request_learns_nothing_of_the_majors(self, ledger, serving):
        ledger.client.device_secret = "A" * 43
        assert ledger.client.fetch(majors="2").status == 401


class TestTheSession:  # YB3, point 5
    def test_it_stops_at_its_time_limit(self, ledger):
        server = ledger.serving_server(AS_OF, minutes=0.005)
        started = time.monotonic()
        running = threading.Thread(target=server.run, daemon=True)
        running.start()
        running.join(timeout=5)
        assert not running.is_alive(), "serve did not stop at its time limit"
        assert 0.2 < time.monotonic() - started < 3
        server.server_close()
        server.conn.close()

    def test_it_stops_at_its_failure_limit(self, ledger, serving):
        ledger.client.device_secret = "A" * 43
        for count in range(1, AUTHENTICATION_FAILURE_LIMIT + 1):
            assert ledger.client.fetch().status == 401
            assert serving.should_stop() == (count == AUTHENTICATION_FAILURE_LIMIT)
        running = threading.Thread(target=serving.run, daemon=True)
        running.start()
        running.join(timeout=5)
        assert not running.is_alive(), "serve did not stop at its failure limit"

    def test_it_writes_nothing_but_deliveries(self, ledger, serving):
        tables = tuple(table for table in (*ALL_TABLES, "account", "import_run")
                       if table not in SYNC_TABLES + SNAPSHOT_TABLES)
        before = ledger.dump(tables)
        before_sync = {table: ledger.table(table) for table in SYNC_TABLES
                       if table not in ("sync_delivery", "sync_acknowledgement")}
        ledger.client.sync()
        assert ledger.dump(tables) == before
        assert {table: ledger.table(table) for table in before_sync} == before_sync

    def test_counts_are_kept_for_the_final_line(self, ledger, serving):
        ledger.client.sync()
        ledger.client.device_secret = "A" * 43
        ledger.client.fetch()
        assert (serving.counts["served"], serving.counts["acknowledged"],
                serving.counts["refused"]) == (1, 1, 1)


class TestTheCommand:  # YB3, the command as typed
    @pytest.fixture
    def zoned(self, ledger, monkeypatch):
        from test_budget_plans import BudgetLedger

        for helper in ("settings_shown", "setting_token", "set_setting"):
            setattr(ledger, helper, getattr(BudgetLedger, helper).__get__(ledger))
        assert ledger.set_setting()[0] == 0
        monkeypatch.setattr(cli, "current_utc_time", Clock())
        monkeypatch.setattr(cli, "checked_private_address", lambda address: address)
        monkeypatch.setattr(sync_server, "SyncServer", ScriptedServer)
        return ledger

    def test_serve_builds_verifies_serves_and_prints_counts_only(self, zoned):
        client = zoned.client
        seen = {}

        def script(server):
            seen["before"] = zoned.capsys.readouterr()
            seen["document"] = served_here(
                server, lambda connect: with_connect(client, connect).sync(),
                connections_expected=2)
            seen["during"] = zoned.capsys.readouterr()

        ScriptedServer.script = script
        code, out, err = zoned.run("sync", "serve", "--address", "192.168.1.20")
        assert (code, err) == (0, ""), err
        # No request writes to stdout or stderr: only what serve printed before and after.
        assert (seen["during"].out, seen["during"].err) == ("", "")
        out = seen["before"].out + out
        lines = out.splitlines()
        assert lines[0] == (f"Serving snapshot {seen['document']['snapshot_id']} as of "
                            "2026-05-04 on 192.168.1.20:8443 for 10 minutes, to paired devices "
                            "only. If the phone asks where, scan:")
        assert lines[-2:] == ["Stop with Ctrl-C.",
                              "Stopped: 1 snapshots served, 1 acknowledged, 0 requests refused."]
        assert client.device_secret not in out and "ledger.db" not in out

    def test_serve_needs_the_household_timezone(self, ledger, monkeypatch):
        monkeypatch.setattr(cli, "checked_private_address", lambda address: address)
        code, _, err = ledger.run("sync", "serve", "--address", "192.168.1.20")
        assert code == 2 and "timezone" in err

    def test_serve_takes_an_as_of_date_instead(self, ledger, monkeypatch):
        monkeypatch.setattr(cli, "checked_private_address", lambda address: address)
        monkeypatch.setattr(sync_server, "SyncServer", ScriptedServer)
        ScriptedServer.script = lambda server: None
        code, out, err = ledger.run("sync", "serve", "--address", "192.168.1.20", "--as-of",
                                    "2026-04-30")
        assert (code, err) == (0, ""), err
        assert " as of 2026-04-30 on 192.168.1.20:8443 " in out
        code, _, err = ledger.run("sync", "serve", "--address", "192.168.1.20", "--as-of",
                                  "2026-02-30")
        assert code == 2 and "--as-of must be a date" in err

    @pytest.mark.parametrize("words, message", [
        (("--minutes", "0"), "--minutes must be"), (("--minutes", "61"), "--minutes must be"),
        (("--minutes", "1.5"), "--minutes must be"), (("--window-days", "0"), "--window-days"),
        (("--window-days", "367"), "--window-days")])
    def test_limits_outside_their_ranges_are_refused(self, ledger, words, message):
        code, _, err = ledger.run("sync", "serve", "--address", "192.168.1.20", *words)
        assert code == 2 and message in err


def test_deliveries_lists_each_with_its_acknowledgement(ledger, serving, tmp_path):
    ledger.client.sync()
    other = ledger.connected(ledger.paired_client(tmp_path / "other", name="Other"), serving)
    other.fetch()
    other.connect.wait()
    _, out, _ = ledger.run("sync", "deliveries")
    lines = out.splitlines()
    assert lines[0] == "Deliveries" and len(lines) == 3
    assert lines[1].startswith(f"Snapshot {serving.document['snapshot_id']} to Phone "
                               f"({ledger.client.device_id}), digest ")
    assert ", acknowledged " in lines[1] and lines[2].endswith(", not acknowledged")
    _, only, _ = ledger.run("sync", "deliveries", "--device", other.device_id)
    assert only.splitlines()[1:] == [lines[2]]
    code, _, err = ledger.run("sync", "deliveries", "--device", "x")
    assert code == 2 and "no paired device has that ID" in err
    assert json.loads(ledger.client.installed_path.read_bytes())["format"] == \
        "commoncents-snapshot"
