"""Pairing windows, paired devices and deliveries in the ledger (D-076 points 3, 4, 6 and 7, the
M20 slice plans).

Only hashes of secrets are stored. A window is single-use, open at most 120 seconds, and closed by
its fifth failure. A device is checked against the ledger on every request, so a revocation
applies on its next one. dv1 covers revoking a device and rotating the identity, each with the
state it acts on. One pair or serve runs at a time, by a lock released if its process dies.
"""

import fcntl
import hashlib
import hmac
import ipaddress
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from personal_finance.planning.entries import in_one_write, refuse_unless_revision
from personal_finance.reconcile.decisions import DecisionRefused
from personal_finance.reports.category_rule_evidence import digest
from personal_finance.snapshot.files import insert_record
from personal_finance.sync import identity as identities
from personal_finance.sync.identity import IdentityRefused, SyncIdentity

DEVICE_REVISION_VERSION = 1
PAIRING_WINDOW_SECONDS = 120
PAIRING_FAILURE_LIMIT = 5
SECRET_BYTES = 32
DEFAULT_PORT = 8443
LOCK_NAME = "sync.lock"
LONGEST_DEVICE_NAME = 64
PRIVATE_NETWORKS = tuple(ipaddress.IPv4Network(network)
                         for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))

ADDRESS_REFUSED = ("--address must be this Mac's private IPv4 address on the local network, such "
                   "as 192.168.1.20 (RFC 1918). Loopback, link-local, public and wildcard "
                   "addresses are refused.")
PORT_REFUSED = "--port must be a whole number from 1024 to 65535."
NAME_REFUSED = f"--name must be 1 to {LONGEST_DEVICE_NAME} characters, the device's name."
WINDOW_OPEN = ("a pairing window is already open. Wait for it to close, at most "
               f"{PAIRING_WINDOW_SECONDS} seconds. Nothing was changed.")
LOCK_HELD = ("another sync pair or sync serve is running on this ledger. Stop it first. Nothing "
             "was changed.")
DEVICE_NOT_FOUND = "no paired device has that ID. Nothing was changed."
DEVICE_REVOKED = "that device is already revoked. Nothing was changed."
REVOKE_STALE = ("the revision does not match this device now. Run sync devices for the current "
                "revision. Nothing was changed.")
ROTATE_STALE = ("the revision does not match this identity and its devices now. Run sync "
                "identity show for the current revision. Nothing was changed.")
IDENTITY_EXISTS = ("this ledger already has a sync identity. Rotate it with sync identity "
                   "rotate instead. Nothing was changed.")


class SyncRefused(Exception):
    """A sync command refused, saying why. Nothing was changed."""


def utc_text(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def secret_sha256(secret: str) -> str:
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def same_hash(presented: str, stored: str) -> bool:
    return hmac.compare_digest(presented.encode("ascii"), stored.encode("ascii"))


# Where it listens.

def checked_private_address(text: str) -> str:
    """An RFC 1918 IPv4 address, written as ipaddress writes it, else refused (point 4)."""
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        raise SyncRefused(ADDRESS_REFUSED) from None
    if str(address) != text or not any(address in network for network in PRIVATE_NETWORKS):
        raise SyncRefused(ADDRESS_REFUSED)
    return text


def checked_port(text: str) -> int:
    if not text.isdigit() or not 1024 <= int(text) <= 65535:
        raise SyncRefused(PORT_REFUSED)
    return int(text)


def checked_device_name(text: str) -> str:
    if not 1 <= len(text) <= LONGEST_DEVICE_NAME:
        raise SyncRefused(NAME_REFUSED)
    return text


@contextmanager
def sync_lock(sync_folder: Path):
    """Held while a pair, serve, identity create or rotate runs: a second is refused."""
    descriptor = os.open(sync_folder / LOCK_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncRefused(LOCK_HELD) from None
        yield
    finally:
        os.close(descriptor)


# Devices.

@dataclass(frozen=True)
class PairedDevice:
    device_id: str
    name: str
    identity_id: str
    created_at: str
    revoked_at: str | None
    secret_sha256: str

    @property
    def state(self) -> str:
        return "revoked" if self.revoked_at else "active"

    def material(self) -> dict:
        return {"device_id": self.device_id, "name": self.name, "identity_id": self.identity_id,
                "created_at": self.created_at, "state": self.state}


def load_devices(conn: sqlite3.Connection) -> list[PairedDevice]:
    return [PairedDevice(*row) for row in conn.execute(
        """SELECT device.device_id, device.name, device.identity_id, device.created_at,
                  revoked.created_at, device.secret_sha256
           FROM paired_device device
           LEFT JOIN paired_device_event revoked
               ON revoked.device_id = device.device_id AND revoked.event = 'revoked'
           ORDER BY device.created_at, device.device_id""")]


def find_device(conn: sqlite3.Connection, device_id: str) -> PairedDevice:
    found = next((device for device in load_devices(conn) if device.device_id == device_id), None)
    if found is None:
        raise DecisionRefused(DEVICE_NOT_FOUND)
    return found


def revoke_revision(device: PairedDevice) -> str:
    material = {"operation": "revoke", "device": device.material()}
    return f"dv{DEVICE_REVISION_VERSION}-{digest(material)}"


def rotate_revision(identity: SyncIdentity, devices: list[PairedDevice]) -> str:
    material = {"operation": "rotate",
                "identity": {"identity_id": identity.identity_id,
                             "certificate_sha256": identity.certificate_sha256},
                "devices": [{"device_id": device.device_id, "state": device.state}
                            for device in devices]}
    return f"dv{DEVICE_REVISION_VERSION}-{digest(material)}"


def revoke_device(conn: sqlite3.Connection, device_id: str, revision: str) -> PairedDevice:
    def write():
        device = find_device(conn, device_id)
        refuse_unless_revision(revoke_revision(device), revision, REVOKE_STALE)
        if device.revoked_at:
            raise DecisionRefused(DEVICE_REVOKED)
        conn.execute("INSERT INTO paired_device_event (device_id, event) VALUES (?, 'revoked')",
                     (device_id,))
        return device

    return in_one_write(conn, write)


def authenticated_device(conn: sqlite3.Connection, device_id: str,
                         device_secret: str) -> PairedDevice | None:
    """The active device of the current identity holding this secret, else None. The hash is
    compared in constant time even for an unknown device."""
    current = identities.current_identity(conn)
    device = next((device for device in load_devices(conn) if device.device_id == device_id),
                  None)
    stored = device.secret_sha256 if device else "0" * 64
    matches = same_hash(secret_sha256(device_secret), stored)
    if not matches or device is None or device.revoked_at or current is None or \
            device.identity_id != current.identity_id:
        return None
    return device


# The identity, made and rotated.

def create_identity(conn: sqlite3.Connection, sync_folder: Path) -> SyncIdentity:
    if identities.current_identity(conn) is not None:
        raise IdentityRefused(IDENTITY_EXISTS)
    identity_id, fingerprint = identities.made_identity_folder(sync_folder)

    def write():
        if identities.current_identity(conn) is not None:
            raise IdentityRefused(IDENTITY_EXISTS)
        identities.record_identity(conn, identity_id, fingerprint)

    try:
        in_one_write(conn, write)
    except BaseException:
        identities.remove_identity_folder(sync_folder, identity_id)
        raise
    return identities.required_identity(conn)


def rotate_identity(conn: sqlite3.Connection, sync_folder: Path,
                    revision: str) -> tuple[SyncIdentity, list[PairedDevice]]:
    """A new identity, the old one retired and every active device revoked, in one transaction.
    The old key is then deleted."""
    old = identities.required_identity(conn)
    refuse_unless_revision(rotate_revision(old, load_devices(conn)), revision, ROTATE_STALE)
    identity_id, fingerprint = identities.made_identity_folder(sync_folder)

    def write():
        current = identities.required_identity(conn)
        devices = load_devices(conn)
        refuse_unless_revision(rotate_revision(current, devices), revision, ROTATE_STALE)
        identities.retire_identity(conn, current.identity_id)
        identities.record_identity(conn, identity_id, fingerprint)
        revoked = [device for device in devices if not device.revoked_at]
        conn.executemany("INSERT INTO paired_device_event (device_id, event) "
                         "VALUES (?, 'revoked')", [(device.device_id,) for device in revoked])
        return current, revoked

    try:
        retired, revoked = in_one_write(conn, write)
    except BaseException:
        identities.remove_identity_folder(sync_folder, identity_id)
        raise
    identities.remove_identity_folder(sync_folder, retired.identity_id)
    return identities.required_identity(conn), revoked


# Pairing windows.

@dataclass(frozen=True)
class OpenedWindow:
    window_id: str
    pairing_secret: str
    closes_at: str


@dataclass(frozen=True)
class NewDevice:
    device_id: str
    device_secret: str


def window_state(conn: sqlite3.Connection, window_id: str, now: datetime) -> tuple[bool, int]:
    """(open, failures): open while not used, not closed, not past its time and under its
    failure limit."""
    closes_at, = conn.execute("SELECT closes_at FROM pairing_window WHERE window_id = ?",
                              (window_id,)).fetchone()
    events = [event for event, in conn.execute(
        "SELECT event FROM pairing_window_event WHERE window_id = ?", (window_id,))]
    failures = events.count("failed")
    is_open = ("used" not in events and "closed" not in events and utc_text(now) < closes_at
               and failures < PAIRING_FAILURE_LIMIT)
    return is_open, failures


def open_window(conn: sqlite3.Connection, identity: SyncIdentity, address: str, port: int,
                now: datetime) -> OpenedWindow:
    pairing_secret = secrets.token_urlsafe(SECRET_BYTES)
    window_id = str(uuid.uuid4())
    closes_at = utc_text(now + timedelta(seconds=PAIRING_WINDOW_SECONDS))

    def write():
        for other, in conn.execute("SELECT window_id FROM pairing_window").fetchall():
            if window_state(conn, other, now)[0]:
                raise SyncRefused(WINDOW_OPEN)
        conn.execute("""INSERT INTO pairing_window (window_id, identity_id, secret_sha256, address,
                                                    port, closes_at)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                     (window_id, identity.identity_id, secret_sha256(pairing_secret), address,
                      port, closes_at))

    in_one_write(conn, write)
    return OpenedWindow(window_id, pairing_secret, closes_at)


def attempt_pairing(conn: sqlite3.Connection, window_id: str, presented_secret: str,
                    device_name: str, now: datetime) -> NewDevice | None:
    """A new device when the window is open and the secret its own, else None, the failure
    recorded and the window closed at its limit."""
    def write():
        is_open, failures = window_state(conn, window_id, now)
        if not is_open:
            return None
        identity_id, stored = conn.execute(
            "SELECT identity_id, secret_sha256 FROM pairing_window WHERE window_id = ?",
            (window_id,)).fetchone()
        if not same_hash(secret_sha256(presented_secret), stored):
            conn.execute("INSERT INTO pairing_window_event (window_id, event) VALUES (?, 'failed')",
                         (window_id,))
            if failures + 1 >= PAIRING_FAILURE_LIMIT:
                close(conn, window_id)
            return None
        device = NewDevice(str(uuid.uuid4()), secrets.token_urlsafe(SECRET_BYTES))
        conn.execute("""INSERT INTO paired_device (device_id, name, secret_sha256, identity_id,
                                                   window_id)
                        VALUES (?, ?, ?, ?, ?)""",
                     (device.device_id, device_name, secret_sha256(device.device_secret),
                      identity_id, window_id))
        conn.execute("INSERT INTO pairing_window_event (window_id, event) VALUES (?, 'used')",
                     (window_id,))
        close(conn, window_id)
        return device

    return in_one_write(conn, write)


def close(conn: sqlite3.Connection, window_id: str) -> None:
    if not conn.execute("SELECT 1 FROM pairing_window_event WHERE window_id = ? AND "
                        "event = 'closed'", (window_id,)).fetchone():
        conn.execute("INSERT INTO pairing_window_event (window_id, event) VALUES (?, 'closed')",
                     (window_id,))


def close_window(conn: sqlite3.Connection, window_id: str) -> None:
    in_one_write(conn, lambda: close(conn, window_id))


def window_failures(conn: sqlite3.Connection, window_id: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM pairing_window_event WHERE window_id = ? AND "
                        "event = 'failed'", (window_id,)).fetchone()[0]


# Deliveries and acknowledgements.

def record_delivery(conn: sqlite3.Connection, device_id: str, document: dict) -> str:
    """The snapshot's record and this device's delivery, each written once (point 7)."""
    snapshot_id = document["snapshot_id"]

    def write():
        if not conn.execute("SELECT 1 FROM snapshot_record WHERE snapshot_id = ?",
                            (snapshot_id,)).fetchone():
            insert_record(conn, document)
        found = conn.execute("SELECT delivery_id FROM sync_delivery WHERE device_id = ? AND "
                             "snapshot_id = ?", (device_id, snapshot_id)).fetchone()
        if found:
            return found[0]
        delivery_id = str(uuid.uuid4())
        conn.execute("""INSERT INTO sync_delivery (delivery_id, device_id, snapshot_id,
                                                   content_sha256)
                        VALUES (?, ?, ?, ?)""",
                     (delivery_id, device_id, snapshot_id, document["content_sha256"]))
        return delivery_id

    return in_one_write(conn, write)


def acknowledge(conn: sqlite3.Connection, device_id: str, snapshot_id: str,
                content_sha256: str) -> bool:
    """Whether this matches a delivery to this device, recording its acknowledgement once."""
    def write():
        found = conn.execute("SELECT delivery_id, content_sha256 FROM sync_delivery "
                             "WHERE device_id = ? AND snapshot_id = ?",
                             (device_id, snapshot_id)).fetchone()
        if found is None or not same_hash(content_sha256, found[1]):
            return False
        if not conn.execute("SELECT 1 FROM sync_acknowledgement WHERE delivery_id = ?",
                            (found[0],)).fetchone():
            conn.execute("INSERT INTO sync_acknowledgement (delivery_id) VALUES (?)",
                         (found[0],))
        return True

    return in_one_write(conn, write)


@dataclass(frozen=True)
class Delivery:
    device_id: str
    device_name: str
    snapshot_id: str
    content_sha256: str
    served_at: str
    acknowledged_at: str | None


def load_deliveries(conn: sqlite3.Connection, device_id: str | None = None) -> list[Delivery]:
    rows = conn.execute(
        """SELECT delivery.device_id, device.name, delivery.snapshot_id, delivery.content_sha256,
                  delivery.created_at, acknowledgement.created_at
           FROM sync_delivery delivery
           JOIN paired_device device ON device.device_id = delivery.device_id
           LEFT JOIN sync_acknowledgement acknowledgement
               ON acknowledgement.delivery_id = delivery.delivery_id
           WHERE ? IS NULL OR delivery.device_id = ?
           ORDER BY delivery.created_at, delivery.delivery_id""", (device_id, device_id))
    return [Delivery(*row) for row in rows]
