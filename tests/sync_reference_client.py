"""The reference sync client: the phone's side of docs/sync-protocol.md, in Python (D-076 point 8).

It is the specification the iOS application is tested against. It pins the Mac's certificate by
its SHA-256 and refuses any other before sending a byte; sends the snapshot majors it supports;
checks the bytes' digest, then the snapshot by M19's rules; installs it atomically, keeping the
last valid snapshot on any failure; acknowledges only after installing; and reports freshness
from the snapshot, never from the sync time.

It speaks over any connected socket it is given, so the suite drives it over socket.socketpair()
(keeping the socket guard) and the benchmark over loopback TCP.
"""

import hashlib
import json
import os
import ssl
from dataclasses import dataclass
from pathlib import Path

from personal_finance.snapshot.files import SnapshotRefused, verified
from personal_finance.sync.pairing import parsed_payload

INSTALLED_NAME = "snapshot.json"
SUPPORTED_MAJORS = "1"


class PinMismatch(Exception):
    """The server's certificate is not the one pinned: nothing was sent."""


class SyncFailed(Exception):
    """A sync that installed nothing, keeping the last valid snapshot."""

    def __init__(self, reason: str, status: int | None = None):
        super().__init__(reason)
        self.reason, self.status = reason, status


@dataclass(frozen=True)
class Answer:
    status: int
    headers: dict
    body: bytes

    def json(self):
        return json.loads(self.body)


def client_context() -> ssl.SSLContext:
    """TLS 1.3 with no certificate authority: the pin is checked by hand after the handshake."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    return context


def parsed_answer(received: bytes) -> Answer:
    head, _, body = received.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        assert name.lower() not in headers, name
        headers[name.lower()] = value.strip()
    return Answer(status, headers, body)


def exchange(connected_socket, fingerprint: str, request: bytes,
             context: ssl.SSLContext | None = None) -> Answer:
    """One request over TLS on a connected socket, after checking the pin."""
    with (context or client_context()).wrap_socket(connected_socket) as tls:
        presented = hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()
        if presented != fingerprint:
            raise PinMismatch(presented)
        tls.sendall(request)
        received = b"".join(iter(lambda: tls.recv(65536), b""))
    return parsed_answer(received)


def request_bytes(method: str, path: str, host: str, headers=(), body: bytes = b"") -> bytes:
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}", "Connection: close", *headers]
    if body:
        lines += ["Content-Type: application/json", f"Content-Length: {len(body)}"]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


class ReferenceClient:
    def __init__(self, install_folder: Path, connect):
        """connect() returns a connected socket to the server, each call a new connection."""
        self.install_folder = install_folder
        self.connect = connect
        self.address = self.port = self.fingerprint = None
        self.device_id = self.device_secret = None

    @property
    def host(self) -> str:
        return f"{self.address}:{self.port}"

    @property
    def installed_path(self) -> Path:
        return self.install_folder / INSTALLED_NAME

    def pair(self, payload: str) -> Answer:
        fields = parsed_payload(payload)
        self.address, self.port, self.fingerprint = (fields["address"], fields["port"],
                                                     fields["fingerprint"])
        body = json.dumps({"pairing_secret": fields["secret"]}).encode()
        answer = exchange(self.connect(), self.fingerprint,
                          request_bytes("POST", "/v1/pair", self.host, body=body))
        if answer.status == 200:
            paired = answer.json()
            # The phone keeps these in its Keychain.
            self.device_id, self.device_secret = paired["device_id"], paired["device_secret"]
        return answer

    def authorization(self) -> str:
        return f"Authorization: Bearer {self.device_id}.{self.device_secret}"

    def fetch(self, majors: str = SUPPORTED_MAJORS) -> Answer:
        return exchange(self.connect(), self.fingerprint, request_bytes(
            "GET", "/v1/snapshot/latest", self.host,
            headers=(self.authorization(), f"Accept-Snapshot-Major: {majors}")))

    def acknowledge(self, snapshot_id: str, content_sha256: str) -> Answer:
        body = json.dumps({"snapshot_id": snapshot_id, "content_sha256": content_sha256}).encode()
        return exchange(self.connect(), self.fingerprint, request_bytes(
            "POST", "/v1/ack", self.host, headers=(self.authorization(),), body=body))

    def sync(self) -> dict:
        """Fetch, check, install and acknowledge: the installed snapshot, else SyncFailed with
        the last valid one kept."""
        answer = self.fetch()
        if answer.status == 409:
            supported = answer.json()["supported_majors"]
            raise SyncFailed(f"the Mac serves snapshot majors {supported}, and this app reads "
                             f"{SUPPORTED_MAJORS}: update the app or the Mac", answer.status)
        if answer.status != 200:
            raise SyncFailed("refused", answer.status)
        if hashlib.sha256(answer.body).hexdigest() != answer.headers.get("snapshot-sha256"):
            raise SyncFailed("the bytes do not match their digest")
        try:
            document = verified(answer.body)
        except SnapshotRefused as refused:
            raise SyncFailed(f"the snapshot is not valid: {refused}") from None
        self.install(answer.body)
        acknowledged = self.acknowledge(document["snapshot_id"], document["content_sha256"])
        if acknowledged.status != 204:
            raise SyncFailed("installed, but the acknowledgement was refused", acknowledged.status)
        return document

    def install(self, data: bytes) -> None:
        """Atomically: a partial file fsynced, then renamed over the last one."""
        partial = self.install_folder / f".{INSTALLED_NAME}.partial"
        with open(partial, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(partial, self.installed_path)

    def installed(self) -> dict | None:
        if not self.installed_path.is_file():
            return None
        return json.loads(self.installed_path.read_bytes())

    def freshness(self) -> str | None:
        """As of when the data is, from the snapshot itself (shared-contract §5)."""
        document = self.installed()
        return None if document is None else document["content"]["cutoff"]["as_of"]
