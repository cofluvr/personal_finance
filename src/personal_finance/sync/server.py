"""The sync server: HTTPS on one private address, one request at a time, read-only, in the
foreground for a limited time (D-076 points 1, 4, 5 and 6, the M20 slice plans).

TLS 1.3 only, no client certificates, no compression, no session tickets. The phone pins the
certificate's SHA-256, learnt at pairing; there is no certificate authority. In pair mode the one
route is POST /v1/pair, during its window. In serve mode the routes are GET /v1/snapshot/latest
and POST /v1/ack, each authenticated against the ledger on every request. Every other method or
path is 404. Every answer's body is fixed, repeating nothing from the request, and nothing is
logged (D-037): the command prints counts only when it stops.

The address is checked as private before any socket opens. A test hook binding loopback is a
subclass in tests/, which nothing here can reach.
"""

import hashlib
import json
import re
import sqlite3
import ssl
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer

from personal_finance.sync import devices

SUPPORTED_MAJORS = (1,)
LARGEST_BODY_BYTES = 4096
LARGEST_HEADER_BYTES = 8192
REQUEST_TIMEOUT_SECONDS = 10
POLL_SECONDS = 0.25
AUTHENTICATION_FAILURE_LIMIT = 10
PAIR, SERVE = "pair", "serve"

BEARER = re.compile(r"Bearer ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
                    r"\.([A-Za-z0-9_-]{43})")
SECRET = re.compile(r"[A-Za-z0-9_-]{43}")
SNAPSHOT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
MAJORS = re.compile(r"[0-9]{1,3}(, ?[0-9]{1,3})*")

UNAUTHORIZED = {"error": "unauthorized"}
NOT_FOUND = {"error": "not_found"}
BAD_REQUEST = {"error": "bad_request"}
NOT_DELIVERED = {"error": "not_delivered"}
BODY_TOO_LARGE = {"error": "body_too_large"}
HEADERS_TOO_LARGE = {"error": "headers_too_large"}
UNSUPPORTED_MAJOR = {"error": "unsupported_snapshot_major",
                     "supported_majors": list(SUPPORTED_MAJORS)}
BUSY = {"error": "busy"}
FAILED = {"error": "server_error"}


def tls_context(certificate_path, key_path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.options |= ssl.OP_NO_COMPRESSION | ssl.OP_NO_TICKET
    context.num_tickets = 0
    context.verify_mode = ssl.CERT_NONE
    context.load_cert_chain(certificate_path, key_path)
    return context


class BodyRefused(Exception):
    """A request body refused, with the answer to give."""

    def __init__(self, status: int, answer: dict):
        super().__init__(status)
        self.status, self.answer = status, answer


def strict_object(pairs):
    names = [name for name, _ in pairs]
    if len(set(names)) != len(names):
        raise ValueError("a repeated name")
    return dict(pairs)


def refuse_number(text):
    raise ValueError("no number is expected")


def parsed_body(data: bytes, fields: tuple[str, ...]) -> dict:
    """Exactly these string fields in one JSON object, else refused."""
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=strict_object,
                           parse_float=refuse_number, parse_int=refuse_number,
                           parse_constant=refuse_number)
    except (UnicodeDecodeError, ValueError):
        raise BodyRefused(400, BAD_REQUEST) from None
    if not isinstance(value, dict) or sorted(value) != sorted(fields) or \
            not all(isinstance(value[name], str) for name in fields):
        raise BodyRefused(400, BAD_REQUEST)
    return value


class SyncServer(HTTPServer):
    """One pairing window or one serve session on a private address."""

    allow_reuse_address = False
    timeout = POLL_SECONDS

    def __init__(self, address: str, port: int, context: ssl.SSLContext,
                 conn: sqlite3.Connection, *,
                 mode: str, minutes: float, utc_now, document: dict | None = None,
                 snapshot: bytes | None = None, window_id: str | None = None,
                 device_name: str | None = None):
        self.checked_address(address)
        self.context = context
        # One connection for the session: each statement reads what is committed now, so a
        # revocation by another process applies on the device's next request.
        self.conn = conn
        self.mode = mode
        self.utc_now = utc_now
        self.document, self.snapshot = document, snapshot
        self.snapshot_sha256 = None if snapshot is None else hashlib.sha256(snapshot).hexdigest()
        self.window_id, self.device_name = window_id, device_name
        self.deadline = time.monotonic() + minutes * 60
        self.counts = Counter()
        self.paired = None
        self.finished = False
        super().__init__((address, port), SyncRequestHandler)

    @staticmethod
    def checked_address(address: str) -> None:
        devices.checked_private_address(address)

    def server_bind(self):
        # HTTPServer.server_bind looks up a name for the address. Skip it: no resolver is asked.
        super(HTTPServer, self).server_bind()
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        """The default prints a traceback, which could quote data (D-037). The handler answers
        every error it can, so this is reached only when the client has gone."""

    def tls_wrapped(self, connection):
        """The connection after its TLS handshake, else closed and counted as refused."""
        connection.settimeout(REQUEST_TIMEOUT_SECONDS)
        try:
            return self.context.wrap_socket(connection, server_side=True)
        except OSError:
            connection.close()
            self.counts["refused"] += 1
            raise

    def get_request(self):
        connection, client_address = self.socket.accept()
        return self.tls_wrapped(connection), client_address

    def should_stop(self) -> bool:
        return (self.finished or time.monotonic() >= self.deadline
                or self.counts["unauthorized"] >= AUTHENTICATION_FAILURE_LIMIT)

    def run(self) -> None:
        """Until the time limit, the failure limit, or in pair mode the window's end."""
        while not self.should_stop():
            self.handle_request()


class SyncRequestHandler(BaseHTTPRequestHandler):
    timeout = REQUEST_TIMEOUT_SECONDS
    default_request_version = "HTTP/1.0"

    def version_string(self) -> str:
        return "pf"

    def log_message(self, format, *args):
        """No request logging (D-037)."""

    def send_error(self, code, message=None, explain=None):
        """http.server's own refusals as fixed answers: an unknown method is 404, as an unknown
        path is, too many or too long headers 431, and anything else it cannot read 400."""
        if code == 501:
            return self.answer(404, NOT_FOUND)
        if code == 431:
            return self.answer(431, HEADERS_TOO_LARGE)
        self.answer(400, BAD_REQUEST)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method: str) -> None:
        try:
            if sum(len(name) + len(value) + 4 for name, value in self.headers.items()) > \
                    LARGEST_HEADER_BYTES:
                return self.answer(431, HEADERS_TOO_LARGE)
            route = (method, self.path)
            if self.server.mode == PAIR:
                if route == ("POST", "/v1/pair"):
                    return self.pair()
            elif route == ("GET", "/v1/snapshot/latest"):
                return self.latest()
            elif route == ("POST", "/v1/ack"):
                return self.acknowledge()
            return self.answer(404, NOT_FOUND)
        except BodyRefused as refused:
            return self.answer(refused.status, refused.answer)
        except sqlite3.OperationalError as error:
            return self.answer(503, BUSY if "locked" in str(error) else FAILED)
        except Exception:
            return self.answer(500, FAILED)

    # The routes.

    def latest(self) -> None:
        device = self.authenticated()
        if device is None:
            return self.answer(401, UNAUTHORIZED)
        self.refuse_any_body()
        if not self.accepts_a_supported_major():
            return self.answer(409, UNSUPPORTED_MAJOR)
        devices.record_delivery(self.server.conn, device.device_id, self.server.document)
        self.server.counts["served"] += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.server.snapshot)))
        self.send_header("Snapshot-SHA256", self.server.snapshot_sha256)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(self.server.snapshot)

    def acknowledge(self) -> None:
        device = self.authenticated()
        if device is None:
            return self.answer(401, UNAUTHORIZED)
        body = parsed_body(self.body(), ("snapshot_id", "content_sha256"))
        if not SNAPSHOT_ID.fullmatch(body["snapshot_id"]) or \
                not SHA256_HEX.fullmatch(body["content_sha256"]):
            return self.answer(400, BAD_REQUEST)
        matched = devices.acknowledge(self.server.conn, device.device_id, body["snapshot_id"],
                                      body["content_sha256"])
        if not matched:
            return self.answer(400, NOT_DELIVERED)
        self.server.counts["acknowledged"] += 1
        self.send_response(204)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

    def pair(self) -> None:
        body = parsed_body(self.body(), ("pairing_secret",))
        server = self.server
        # A secret of the wrong shape is a failed attempt like any other.
        presented = body["pairing_secret"] if SECRET.fullmatch(body["pairing_secret"]) else ""
        device = devices.attempt_pairing(server.conn, server.window_id, presented,
                                         server.device_name, server.utc_now())
        server.finished = not devices.window_state(server.conn, server.window_id,
                                                   server.utc_now())[0]
        if device is None:
            return self.answer(401, UNAUTHORIZED)
        server.paired = device
        self.answer(200, {"device_id": device.device_id, "device_secret": device.device_secret})

    # Reading the request.

    def authenticated(self):
        """The paired device the request's bearer names and proves, looked up now, else None,
        counted toward the session's failure limit."""
        values = self.headers.get_all("Authorization") or []
        found = BEARER.fullmatch(values[0]) if len(values) == 1 else None
        device = None
        if found:
            device = devices.authenticated_device(self.server.conn, found[1], found[2])
        if device is None:
            self.server.counts["unauthorized"] += 1
        return device

    def accepts_a_supported_major(self) -> bool:
        values = self.headers.get_all("Accept-Snapshot-Major") or []
        if len(values) != 1 or not MAJORS.fullmatch(values[0]):
            return False
        return any(int(major) in SUPPORTED_MAJORS for major in values[0].split(","))

    def declared_length(self) -> int:
        if self.headers.get_all("Transfer-Encoding"):
            raise BodyRefused(400, BAD_REQUEST)
        values = self.headers.get_all("Content-Length") or []
        if not values:
            return 0
        if len(values) != 1 or not values[0].isdigit() or len(values[0]) > 6:
            raise BodyRefused(400, BAD_REQUEST)
        return int(values[0])

    def refuse_any_body(self) -> None:
        if self.declared_length():
            raise BodyRefused(400, BAD_REQUEST)

    def body(self) -> bytes:
        length = self.declared_length()
        if length > LARGEST_BODY_BYTES:
            raise BodyRefused(413, BODY_TOO_LARGE)
        if self.headers.get("Content-Type") != "application/json" or not length:
            raise BodyRefused(400, BAD_REQUEST)
        data = self.rfile.read(length)
        if len(data) != length:
            raise BodyRefused(400, BAD_REQUEST)
        return data

    # Answering.

    def answer(self, status: int, answer: dict) -> None:
        if status >= 400:
            self.server.counts["refused"] += 1
        data = json.dumps(answer, sort_keys=True, separators=(",", ":")).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
