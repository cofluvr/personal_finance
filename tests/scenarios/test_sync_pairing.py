"""Pairing windows, using synthetic data only (YA2 and YA3, D-076 points 3 and 4, the M20.1 slice
plan points 4 to 8). A window pairs once inside 120 seconds and refuses a second use, an expired
window, a wrong secret and a sixth attempt; only hashes are stored; the QR code encodes point 3's
fields; and --address takes only a private IPv4 address."""

import socket

import pytest
import segno
from sync_harness import (
    LOOPBACK,
    Clock,
    Connections,
    LoopbackSyncServer,
    SyncLedger,
    raw_exchange,
    served_here,
)
from sync_reference_client import ReferenceClient, client_context, request_bytes

from personal_finance import cli
from personal_finance.sync import devices, pairing, server as sync_server
from personal_finance.sync.devices import SyncRefused


@pytest.fixture
def ledger(tmp_path, capsys):
    built = SyncLedger(tmp_path, capsys)
    built.made = built.make_identity()
    return built


@pytest.fixture
def window(ledger):
    clock = Clock()
    server = ledger.pairing_server(clock=clock)
    server.clock = clock
    yield server
    server.server_close()
    server.conn.close()


def attempt(server, secret, tmp_path):
    """One pairing attempt with this secret by a client pinning the right certificate."""
    connections = Connections(server)
    client = ReferenceClient(tmp_path, connections)
    fields = pairing.parsed_payload(server.payload)
    answer = client.pair(pairing.pairing_payload(fields["address"], fields["port"],
                                                 fields["fingerprint"], secret))
    connections.wait()
    return client, answer


def secret_of(server):
    return pairing.parsed_payload(server.payload)["secret"]


WRONG = "A" * 43


class TestPairing:  # YA2
    def test_it_pairs_once_inside_the_window(self, ledger, window, tmp_path):
        client, answer = attempt(window, secret_of(window), tmp_path)
        assert answer.status == 200 and sorted(answer.json()) == ["device_id", "device_secret"]
        assert window.finished and window.paired.device_id == client.device_id
        ((device_id, name, stored, identity_id, window_id, _),) = ledger.table("paired_device")
        assert (device_id, name, identity_id, window_id) == (
            client.device_id, "Phone", ledger.made.identity_id, window.window_id)
        assert stored == devices.secret_sha256(client.device_secret)
        assert [event for _, _, event, _ in ledger.table("pairing_window_event")] == [
            "used", "closed"]

    def test_only_hashes_of_secrets_are_stored(self, ledger, window, tmp_path):
        client, _ = attempt(window, secret_of(window), tmp_path)
        data = ledger.path.read_bytes()
        for secret in (secret_of(window), client.device_secret):
            assert secret.encode() not in data
        assert devices.secret_sha256(secret_of(window)).encode() in data

    def test_a_second_use_is_refused(self, ledger, window, tmp_path):
        attempt(window, secret_of(window), tmp_path)
        _, answer = attempt(window, secret_of(window), tmp_path)
        assert answer.status == 401 and answer.json() == {"error": "unauthorized"}
        assert len(ledger.table("paired_device")) == 1

    def test_an_expired_window_is_refused(self, ledger, window, tmp_path):
        window.clock.advance(120)
        _, answer = attempt(window, secret_of(window), tmp_path)
        assert answer.status == 401 and ledger.table("paired_device") == []
        assert window.finished

    def test_just_inside_the_window_pairs(self, ledger, window, tmp_path):
        window.clock.advance(119.999)
        assert attempt(window, secret_of(window), tmp_path)[1].status == 200

    def test_a_wrong_secret_is_refused_and_counted(self, ledger, window, tmp_path):
        _, answer = attempt(window, WRONG, tmp_path)
        assert answer.status == 401 and ledger.table("paired_device") == []
        assert [event for _, _, event, _ in ledger.table("pairing_window_event")] == ["failed"]
        assert not window.finished
        assert attempt(window, secret_of(window), tmp_path)[1].status == 200

    def test_five_failures_close_the_window_and_a_sixth_attempt_is_refused(self, ledger, window,
                                                                          tmp_path):
        for count in range(1, 6):
            assert attempt(window, WRONG, tmp_path)[1].status == 401
            assert window.finished == (count == 5)
        assert attempt(window, secret_of(window), tmp_path)[1].status == 401
        assert ledger.table("paired_device") == []
        events = [event for _, _, event, _ in ledger.table("pairing_window_event")]
        assert events == ["failed"] * 5 + ["closed"]

    @pytest.mark.parametrize("body", [
        b'{"pairing_secret": "short"}', b'{"pairing_secret": 1}', b"[]", b"not json",
        b'{"pairing_secret": "%s", "name": "x"}', b'{"pairing_secret": "a", "pairing_secret": "b"}'])
    def test_a_malformed_body_is_refused(self, ledger, window, body):
        body = body.replace(b"%s", secret_of(window).encode())
        received = raw_exchange(window, request_bytes("POST", "/v1/pair", "host", body=body),
                                client_context())
        assert received.split(b"\r\n")[0] in (b"HTTP/1.0 401 Unauthorized",
                                              b"HTTP/1.0 400 Bad Request")
        assert ledger.table("paired_device") == []

    def test_in_pair_mode_nothing_else_answers(self, ledger, window):
        for request in (request_bytes("GET", "/v1/snapshot/latest", "host"),
                        request_bytes("POST", "/v1/ack", "host", body=b"{}"),
                        request_bytes("GET", "/v1/pair", "host")):
            received = raw_exchange(window, request, client_context())
            assert received.startswith(b"HTTP/1.0 404 Not Found")

    def test_only_one_window_is_open_at_a_time(self, ledger, window):
        conn = ledger.conn()
        with pytest.raises(SyncRefused, match="already open"):
            devices.open_window(conn, ledger.made, LOOPBACK, 9000, window.clock())
        window.clock.advance(120)
        devices.open_window(conn, ledger.made, LOOPBACK, 9000, window.clock())
        conn.close()

    def test_a_closed_window_frees_the_next(self, ledger, window):
        conn = ledger.conn()
        devices.close_window(conn, window.window_id)
        devices.close_window(conn, window.window_id)
        devices.open_window(conn, ledger.made, LOOPBACK, 9000, window.clock())
        conn.close()


def matrix_of(lines):
    """The modules a terminal QR code shows, dark as True, read back from its half blocks."""
    top = {"█": True, "▀": True, "▄": False, " ": False}
    bottom = {"█": True, "▀": False, "▄": True, " ": False}
    rows = []
    for line in lines:
        assert line.startswith(pairing.BLACK_ON_WHITE) and line.endswith(pairing.RESET)
        cells = line[len(pairing.BLACK_ON_WHITE):-len(pairing.RESET)]
        rows += [[top[cell] for cell in cells], [bottom[cell] for cell in cells]]
    return rows


def unpadded(rows):
    return [row[pairing.QUIET_ZONE:-pairing.QUIET_ZONE]
            for row in rows[pairing.QUIET_ZONE:pairing.QUIET_ZONE + len(rows[0])
                            - 2 * pairing.QUIET_ZONE]]


class TestTheCodes:  # YA2, point 3
    def test_the_payload_holds_point_3s_fields(self, window, ledger):
        fields = pairing.parsed_payload(window.payload)
        assert fields == {"scheme": "commoncents-pair:v1", "address": LOOPBACK,
                          "port": window.server_port,
                          "fingerprint": ledger.made.certificate_sha256,
                          "secret": window.window.pairing_secret}

    def test_the_terminal_qr_code_encodes_exactly_the_payload(self, window):
        """No decoder is in the standard library, so the code drawn is read back to modules and
        compared with the payload's own encoding, module for module: QR encoding is
        deterministic for the same data and error level."""
        lines = pairing.qr_lines(window.payload)
        shown = matrix_of(lines)
        assert all(not any(row) for row in shown[:pairing.QUIET_ZONE])
        expected = [[bool(module) for module in row]
                    for row in segno.make_qr(window.payload, error="m").matrix]
        assert unpadded(shown) == expected
        other = [[bool(module) for module in row]
                 for row in segno.make_qr(window.payload[:-1] + "B", error="m").matrix]
        assert unpadded(shown) != other

    def test_the_manual_code_round_trips_and_holds_no_fingerprint(self, window):
        code = pairing.manual_code("192.168.1.20", 8443, window.window.pairing_secret)
        assert pairing.parsed_manual_code(code) == ("192.168.1.20", 8443,
                                                    window.window.pairing_secret)
        assert all(len(group) == 4 for group in code.split("-")[:-1])
        assert pairing.parsed_manual_code(code.lower()) == pairing.parsed_manual_code(code)

    def test_the_reconnect_code_holds_no_secret(self, ledger):
        payload = pairing.reconnect_payload("192.168.1.20", 8443, ledger.made.certificate_sha256)
        assert "secret" not in payload
        assert pairing.parsed_payload(payload)["scheme"] == "commoncents-connect:v1"

    @pytest.mark.parametrize("payload", [
        "commoncents-pair:v2?address=a&port=1&fingerprint=f&secret=s",
        "commoncents-pair:v1?address=a&port=1&fingerprint=f",
        "commoncents-connect:v1?address=a&port=1&fingerprint=f&secret=s"])
    def test_a_payload_of_another_shape_is_refused(self, payload):
        with pytest.raises(ValueError):
            pairing.parsed_payload(payload)


REFUSED_ADDRESSES = ["127.0.0.1", "169.254.1.2", "8.8.8.8", "0.0.0.0", "255.255.255.255",
                     "100.64.0.1", "192.0.2.1", "::1", "fe80::1", "localhost", "192.168.1.020",
                     "192.168.1", "10.0.0.1 ", ""]


class TestAddresses:  # YA3, point 4
    @pytest.mark.parametrize("address", REFUSED_ADDRESSES)
    @pytest.mark.parametrize("words", [("pair", "--name", "Phone"), ("serve",)])
    def test_the_cli_refuses_all_but_a_private_ipv4_address(self, ledger, address, words):
        before = ledger.dump(("pairing_window",))
        code, out, err = ledger.run("sync", *words, "--address", address)
        assert (code, out) == (2, "") and "--address must be this Mac's private IPv4" in err
        assert ledger.dump(("pairing_window",)) == before

    @pytest.mark.parametrize("address", ["10.0.0.1", "172.16.0.1", "172.31.255.254",
                                         "192.168.1.20"])
    def test_private_addresses_pass(self, address):
        assert devices.checked_private_address(address) == address

    @pytest.mark.parametrize("address", ["172.15.255.255", "172.32.0.0", "11.0.0.1"])
    def test_neighbours_of_the_private_ranges_are_refused(self, address):
        with pytest.raises(SyncRefused):
            devices.checked_private_address(address)

    def test_the_real_server_refuses_loopback_before_any_socket_opens(self, ledger, monkeypatch):
        opened = []
        monkeypatch.setattr(socket.socket, "bind", lambda *args: opened.append(args))
        with pytest.raises(SyncRefused):
            sync_server.SyncServer(LOOPBACK, 0, ledger.context(), ledger.conn(),
                                   mode=sync_server.PAIR, minutes=1, utc_now=Clock())
        assert opened == []

    @pytest.mark.parametrize("port", ["1023", "65536", "0", "-1", "84a3", ""])
    def test_a_port_outside_1024_to_65535_is_refused(self, ledger, port):
        code, _, err = ledger.run("sync", "serve", "--address", "192.168.1.20", "--port", port)
        assert code == 2 and "--port must be" in err

    @pytest.mark.parametrize("name", ["", "x" * 65])
    def test_a_device_name_of_0_or_over_64_characters_is_refused(self, ledger, name):
        code, _, err = ledger.run("sync", "pair", "--name", name, "--address", "192.168.1.20")
        assert code == 2 and "--name must be 1 to 64" in err


class ScriptedServer(LoopbackSyncServer):
    """The CLI's server on loopback, its run() a script of client actions instead of waiting."""

    script = None

    def __init__(self, address, *options, **named):
        super().__init__(LOOPBACK, 0, *options[1:], **named)

    def run(self):
        type(self).script(self)


@pytest.fixture
def scripted(monkeypatch):
    monkeypatch.setattr(cli, "checked_private_address", lambda address: address)
    monkeypatch.setattr(sync_server, "SyncServer", ScriptedServer)
    return ScriptedServer


class TestTheCommand:  # YA2, the command as typed
    def test_pair_shows_the_code_and_pairs_once(self, ledger, scripted, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "current_utc_time", Clock())
        payloads = []
        real_qr_lines = pairing.qr_lines
        monkeypatch.setattr(pairing, "qr_lines",
                            lambda payload: payloads.append(payload) or real_qr_lines(payload))

        def script(server):
            def pair(connect):
                client = ReferenceClient(tmp_path, connect)
                assert client.pair(payloads[0]).status == 200
                return client

            scripted.client = served_here(server, pair)

        scripted.script = script
        code, out, err = ledger.run("sync", "pair", "--name", "Bea's\tphone", "--address",
                                    "192.168.1.20")
        assert (code, err) == (0, ""), err
        assert out.startswith("Pairing Bea's\\tphone on 192.168.1.20:")
        assert f"and check the phone shows {ledger.made.fingerprint_prefix}." in out
        assert out.endswith(f"Paired device {scripted.client.device_id}: Bea's\\tphone. Serve it "
                            "with sync serve.\n")
        assert pairing.manual_code("192.168.1.20", 8443,
                                   pairing.parsed_payload(payloads[0])["secret"]) in out
        assert scripted.client.device_secret not in out

    def test_a_window_with_no_pairing_says_so_and_closes(self, ledger, scripted, monkeypatch):
        monkeypatch.setattr(cli, "current_utc_time", Clock())
        scripted.script = lambda server: None
        code, out, _ = ledger.run("sync", "pair", "--name", "Phone", "--address", "192.168.1.20")
        assert code == 0
        assert out.endswith("Pairing window closed: no device paired, 0 failed attempts.\n")
        assert [event for _, _, event, _ in ledger.table("pairing_window_event")] == ["closed"]

    def test_pair_without_an_identity_is_refused(self, tmp_path, capsys):
        (tmp_path / "bare").mkdir()
        bare = SyncLedger(tmp_path / "bare", capsys)
        code, _, err = bare.run("sync", "pair", "--name", "Phone", "--address", "192.168.1.20")
        assert code == 2 and "no sync identity" in err

    def test_a_port_in_use_is_refused_naming_it(self, ledger, monkeypatch):
        def refusing(*args, **named):
            raise OSError("in use")

        monkeypatch.setattr(sync_server, "SyncServer", refusing)
        code, _, err = ledger.run("sync", "pair", "--name", "Phone", "--address", "192.168.1.20")
        assert code == 2 and "could not listen on 192.168.1.20:8443" in err
        assert ledger.table("pairing_window") == []


def test_the_devices_list_escapes_names(ledger, tmp_path):
    ledger.paired_client(tmp_path / "phone", name="Line\nbreak")
    _, out, _ = ledger.run("sync", "devices")
    assert "Line\\nbreak, paired " in out
