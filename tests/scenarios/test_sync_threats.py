"""D-076 point 10's threat model, each row with a test and a control that succeeds (YC1), using
synthetic data only. Pairing's own rows (a second use, an expired window, a sixth attempt) are in
test_sync_pairing.py, and revocation's in test_sync_serve.py; the rows here are those of the
connection and the request."""

import json
import ssl
from datetime import date

import pytest
from sync_harness import SyncLedger, raw_exchange
from sync_reference_client import PinMismatch, client_context, exchange, request_bytes

from personal_finance.sync import identity

AS_OF = date(2026, 5, 4)
SENTINEL = "SENTINEL-7Q3Z"


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


def authorized(ledger, *extra):
    return (f"Authorization: Bearer {ledger.client.device_id}.{ledger.client.device_secret}",
            *extra)


def status_of(received: bytes) -> int:
    return int(received.split(b" ", 2)[1])


class TestAnotherDeviceOnTheNetwork:
    @pytest.mark.parametrize("method, path, body", [
        ("GET", "/v1/snapshot/latest", b""),
        ("POST", "/v1/ack", b'{"snapshot_id": "x", "content_sha256": "y"}')])
    @pytest.mark.parametrize("secret", [None, "wrong", "revoked"])
    def test_every_endpoint_refuses_without_a_good_secret(self, ledger, serving, method, path,
                                                          body, secret):
        if secret == "revoked":
            token = ledger.revoke_token(ledger.client.device_id)
            assert ledger.run("sync", "revoke", ledger.client.device_id, "--revision",
                              token)[0] == 0
        headers = ["Accept-Snapshot-Major: 1"]
        if secret is not None:
            value = ledger.client.device_secret if secret == "revoked" else "A" * 43
            headers.append(f"Authorization: Bearer {ledger.client.device_id}.{value}")
        received = raw_exchange(serving, request_bytes(method, path, "h", headers=headers,
                                                       body=body), client_context())
        assert received.endswith(b'\r\n\r\n{"error":"unauthorized"}')
        assert status_of(received) == 401

    def test_the_control_with_the_secret_is_served(self, ledger, serving):
        assert ledger.client.fetch().status == 200


class TestAManInTheMiddle:
    def test_the_client_refuses_another_certificate_before_sending(self, ledger, serving,
                                                                   tmp_path):
        identity.run_openssl(tmp_path / "other_key.pem", tmp_path / "other_certificate.pem")
        impostor = ledger.serving_server(AS_OF)
        impostor.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        impostor.context.minimum_version = ssl.TLSVersion.TLSv1_3
        impostor.context.load_cert_chain(tmp_path / "other_certificate.pem",
                                         tmp_path / "other_key.pem")
        ledger.connected(ledger.client, impostor)
        with pytest.raises(PinMismatch):
            ledger.client.fetch()
        ledger.client.connect.wait()
        assert impostor.counts["unauthorized"] == impostor.counts["served"] == 0
        assert ledger.table("sync_delivery") == []
        impostor.server_close()
        impostor.conn.close()

    def test_the_control_with_the_pinned_certificate_succeeds(self, ledger, serving):
        assert ledger.client.fetch().status == 200


class TestADowngrade:
    def test_a_tls_1_2_client_is_refused(self, ledger, serving):
        context = client_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        with pytest.raises(ssl.SSLError):
            raw_exchange(serving, request_bytes("GET", "/v1/snapshot/latest", "h",
                                                headers=authorized(ledger)), context)
        assert serving.counts["refused"] == 1 and serving.counts["served"] == 0

    def test_a_plaintext_client_is_refused(self, ledger, serving):
        received = raw_exchange(serving, request_bytes(
            "GET", "/v1/snapshot/latest", "h",
            headers=authorized(ledger, "Accept-Snapshot-Major: 1")))
        assert b"HTTP/" not in received and b"commoncents" not in received
        assert serving.counts["refused"] == 1 and ledger.table("sync_delivery") == []

    def test_the_control_tls_1_3_client_is_served(self, ledger, serving):
        received = raw_exchange(serving, request_bytes(
            "GET", "/v1/snapshot/latest", "h",
            headers=authorized(ledger, "Accept-Snapshot-Major: 1")), client_context())
        assert status_of(received) == 200 and received.endswith(serving.snapshot)


class TestMalformedRequests:
    def send(self, ledger, serving, request: bytes) -> bytes:
        return raw_exchange(serving, request, client_context())

    def ack_request(self, ledger, body: bytes, *headers):
        return request_bytes("POST", "/v1/ack", "h", headers=authorized(ledger, *headers),
                             body=body)

    def test_oversized_headers_are_refused(self, ledger, serving):
        received = self.send(ledger, serving, request_bytes(
            "GET", "/v1/snapshot/latest", "h",
            headers=authorized(ledger, "Accept-Snapshot-Major: 1", f"X-Pad: {'p' * 9000}")))
        assert status_of(received) == 431 and ledger.table("sync_delivery") == []

    def test_too_many_headers_are_refused(self, ledger, serving):
        received = self.send(ledger, serving, request_bytes(
            "GET", "/v1/snapshot/latest", "h",
            headers=authorized(ledger, *(f"X-{n}: v" for n in range(120)))))
        assert status_of(received) == 431

    def test_an_oversized_body_is_refused(self, ledger, serving):
        received = self.send(ledger, serving, self.ack_request(ledger, b"{" + b" " * 5000 + b"}"))
        assert (status_of(received), received.endswith(b'{"error":"body_too_large"}')) == (413,
                                                                                         True)

    @pytest.mark.parametrize("body", [
        b"not json", b"[]", b'{"snapshot_id": "a"}', b'{"snapshot_id": 1, "content_sha256": 2}',
        b'{"snapshot_id": "a", "content_sha256": "b", "extra": "c"}',
        b'{"snapshot_id": "a", "snapshot_id": "b", "content_sha256": "c"}',
        b'{"snapshot_id": 1.5, "content_sha256": "c"}', b'{"snapshot_id": NaN}', b"\xff\xfe"])
    def test_bad_json_and_unknown_fields_are_refused(self, ledger, serving, body):
        received = self.send(ledger, serving, self.ack_request(ledger, body))
        assert status_of(received) == 400 and ledger.table("sync_acknowledgement") == []

    def test_a_body_on_a_get_is_refused(self, ledger, serving):
        received = self.send(ledger, serving, request_bytes(
            "GET", "/v1/snapshot/latest", "h", headers=authorized(ledger, "Accept-Snapshot-Major: 1"),
            body=b"{}"))
        assert status_of(received) == 400

    def valid_ack(self, serving) -> bytes:
        return json.dumps({"snapshot_id": serving.document["snapshot_id"],
                           "content_sha256": serving.document["content_sha256"]}).encode()

    @pytest.mark.parametrize("extra", ["Transfer-Encoding: chunked", "Content-Length: 12abc"])
    def test_framing_other_than_one_content_length_is_refused(self, ledger, serving, extra):
        """With an acknowledgement that would otherwise be recorded, as the control shows."""
        ledger.client.fetch()
        body = self.valid_ack(serving)
        length = "" if extra.startswith("Content-Length") else f"Content-Length: {len(body)}\r\n"
        request = (f"POST /v1/ack HTTP/1.1\r\nHost: h\r\n{authorized(ledger)[0]}\r\n"
                   f"Content-Type: application/json\r\n{length}{extra}\r\n\r\n").encode() + body
        assert status_of(self.send(ledger, serving, request)) == 400
        assert ledger.table("sync_acknowledgement") == []
        assert status_of(self.send(ledger, serving, self.ack_request(ledger, body))) == 204

    @pytest.mark.parametrize("shape", ["extra", "repeated"])
    def test_valid_values_in_a_wrong_shape_are_refused(self, ledger, serving, shape):
        """Every value would be accepted alone, so only the shape can refuse it."""
        ledger.client.fetch()
        document = serving.document
        pairs = (f'"snapshot_id": "{document["snapshot_id"]}", '
                 f'"content_sha256": "{document["content_sha256"]}"')
        body = ("{" + pairs + ', "extra": "c"}' if shape == "extra" else
                "{" + f'"snapshot_id": "{document["snapshot_id"]}", ' + pairs + "}").encode()
        assert status_of(self.send(ledger, serving, self.ack_request(ledger, body))) == 400
        assert ledger.table("sync_acknowledgement") == []
        assert status_of(self.send(ledger, serving,
                                   self.ack_request(ledger, self.valid_ack(serving)))) == 204

    @pytest.mark.parametrize("method, path", [
        ("PUT", "/v1/ack"), ("DELETE", "/v1/snapshot/latest"), ("HEAD", "/v1/snapshot/latest"),
        ("GET", "/"), ("GET", "/v1/snapshot/latest?x=1"), ("POST", "/v1/pair"),
        ("GET", "/v1/snapshot/../snapshot/latest")])
    def test_any_other_method_or_path_is_404(self, ledger, serving, method, path):
        received = self.send(ledger, serving, request_bytes(method, path, "h",
                                                           headers=authorized(ledger)))
        assert status_of(received) == 404

    @pytest.mark.parametrize("where", ["path", "header", "body", "authorization", "majors"])
    def test_sentinels_are_never_echoed(self, ledger, serving, where):
        path = f"/{SENTINEL}" if where == "path" else "/v1/ack"
        headers = [f"X-Note: {SENTINEL}"] if where == "header" else []
        if where == "authorization":
            headers.append(f"Authorization: Bearer {SENTINEL}")
        else:
            headers.append(authorized(ledger)[0])
        if where == "majors":
            path = "/v1/snapshot/latest"
            headers.append(f"Accept-Snapshot-Major: {SENTINEL}")
        body = (f'{{"snapshot_id": "{SENTINEL}", "content_sha256": "x"}}'.encode()
                if path == "/v1/ack" else b"")
        received = self.send(ledger, serving, request_bytes("POST" if body else "GET", path,
                                                           "h", headers=headers, body=body))
        assert SENTINEL.encode() not in received
        assert status_of(received) in (400, 401, 404, 409)

    def test_a_request_line_it_cannot_read_gets_a_fixed_answer(self, ledger, serving):
        received = self.send(ledger, serving, f"{SENTINEL}\r\n\r\n".encode())
        assert status_of(received) == 400 and SENTINEL.encode() not in received


class TestNothingIsLogged:
    def test_no_request_writes_to_stdout_or_stderr(self, ledger, serving, capsys):
        capsys.readouterr()
        ledger.client.sync()
        raw_exchange(serving, b"garbage\r\n\r\n", client_context())
        raw_exchange(serving, b"plaintext")
        ledger.client.device_secret = "A" * 43
        ledger.client.fetch()
        assert capsys.readouterr() == ("", "")
