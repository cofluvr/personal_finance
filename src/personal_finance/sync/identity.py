"""The Mac's sync identity: a P-256 key and a self-signed certificate, made once by the system's
openssl (D-076 point 2, the M20.1 slice plan points 2 and 3).

The one program this module runs is OPENSSL, with OPENSSL_ARGUMENTS and nothing else: no shell, an
empty environment, no input, its output discarded, at most 30 seconds. It writes into a new 0700
partial folder, the files are made 0600 there, and the folder is renamed into place as
sync/<identity ID>/ beside the ledger before the identity is recorded. The key never leaves that
folder: it is never printed, backed up or put in a snapshot. The fingerprint is the SHA-256 of the
certificate's DER bytes, decoded from the PEM here, so ssl is needed only by the server.
"""

import base64
import binascii
import hashlib
import os
import shutil
import sqlite3
import stat
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from personal_finance.db.real_ledger import UnsafeLocation, refuse_unless_private

SYNC_FOLDER_NAME = "sync"
KEY_NAME = "key.pem"
CERTIFICATE_NAME = "certificate.pem"
OPENSSL = "/usr/bin/openssl"
OPENSSL_TIMEOUT_SECONDS = 30
CERTIFICATE_SUBJECT = "/CN=commoncents-sync"
PEM_CERTIFICATE_BEGIN = "-----BEGIN CERTIFICATE-----"
PEM_CERTIFICATE_END = "-----END CERTIFICATE-----"


class IdentityRefused(Exception):
    """An identity not made, found or used, saying why. Nothing was changed."""


@dataclass(frozen=True)
class SyncIdentity:
    identity_id: str
    certificate_sha256: str
    created_at: str

    def folder(self, sync_folder: Path) -> Path:
        return sync_folder / self.identity_id

    def key_path(self, sync_folder: Path) -> Path:
        return self.folder(sync_folder) / KEY_NAME

    def certificate_path(self, sync_folder: Path) -> Path:
        return self.folder(sync_folder) / CERTIFICATE_NAME

    @property
    def fingerprint_prefix(self) -> str:
        """The first 16 hex digits, which a person compares against the phone's."""
        return self.certificate_sha256[:16]


def openssl_arguments(key_path: Path, certificate_path: Path) -> list[str]:
    # ec_param_enc:named_curve: without it LibreSSL writes the curve's explicit parameters, which
    # TLS stacks such as the phone's refuse.
    return [OPENSSL, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-pkeyopt", "ec_param_enc:named_curve", "-nodes", "-days", "3650", "-subj", CERTIFICATE_SUBJECT,
            "-keyout", str(key_path), "-out", str(certificate_path)]


def run_openssl(key_path: Path, certificate_path: Path) -> None:
    try:
        finished = subprocess.run(openssl_arguments(key_path, certificate_path),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, env={},
                                  timeout=OPENSSL_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        raise IdentityRefused(f"{OPENSSL} could not be run, so no identity was made. Nothing "
                              "was changed.") from None
    if finished.returncode != 0:
        raise IdentityRefused(f"{OPENSSL} failed, so no identity was made. Nothing was "
                              "changed.")


def sync_folder_beside(database_path: Path) -> Path:
    return database_path.resolve().parent / SYNC_FOLDER_NAME


def refuse_unsafe_sync_folder(sync_folder: Path) -> None:
    """The originals folder's rules (D-058 point 2): no symbolic link, a folder, yours, 0700."""
    if sync_folder.is_symlink():
        raise UnsafeLocation(f"the sync folder cannot be a symbolic link: {sync_folder}")
    if not sync_folder.is_dir():
        raise UnsafeLocation(f"the sync folder must be a folder: {sync_folder}")
    refuse_unless_private(sync_folder, private_mode="700")


def prepared_sync_folder(database_path: Path) -> Path:
    sync_folder = sync_folder_beside(database_path)
    if not sync_folder.exists() and not sync_folder.is_symlink():
        sync_folder.mkdir(mode=0o700)
    refuse_unsafe_sync_folder(sync_folder)
    return sync_folder


def certificate_sha256(certificate_pem: bytes) -> str:
    """The SHA-256 of the one certificate's DER bytes, as the phone pins it."""
    text = certificate_pem.decode("ascii", errors="strict").strip()
    if not (text.startswith(PEM_CERTIFICATE_BEGIN) and text.endswith(PEM_CERTIFICATE_END)) or \
            text.count(PEM_CERTIFICATE_BEGIN) != 1:
        raise IdentityRefused("the certificate openssl wrote is not one PEM certificate. Nothing "
                              "was changed.")
    body = text[len(PEM_CERTIFICATE_BEGIN):-len(PEM_CERTIFICATE_END)]
    try:
        der = base64.b64decode("".join(body.split()), validate=True)
    except binascii.Error:
        raise IdentityRefused("the certificate openssl wrote is not valid PEM. Nothing was "
                              "changed.") from None
    return hashlib.sha256(der).hexdigest()


def load_identities(conn: sqlite3.Connection) -> list[tuple[SyncIdentity, bool]]:
    """Every identity in the order made, with whether it is retired."""
    rows = conn.execute(
        """SELECT identity.identity_id, identity.certificate_sha256, identity.created_at,
                  retired.identity_id IS NOT NULL
           FROM sync_identity identity
           LEFT JOIN sync_identity_event retired
               ON retired.identity_id = identity.identity_id AND retired.event = 'retired'
           ORDER BY identity.created_at, identity.identity_id""").fetchall()
    return [(SyncIdentity(identity_id, fingerprint, created_at), bool(retired))
            for identity_id, fingerprint, created_at, retired in rows]


def current_identity(conn: sqlite3.Connection) -> SyncIdentity | None:
    current = [identity for identity, retired in load_identities(conn) if not retired]
    if len(current) > 1:
        raise IdentityRefused("this ledger holds more than one current sync identity.")
    return current[0] if current else None


def required_identity(conn: sqlite3.Connection) -> SyncIdentity:
    identity = current_identity(conn)
    if identity is None:
        raise IdentityRefused("this ledger has no sync identity. Make one with sync identity "
                              "create.")
    return identity


def checked_identity_files(identity: SyncIdentity, sync_folder: Path) -> tuple[Path, Path]:
    """The key and certificate, refused unless private and the certificate the one recorded."""
    refuse_unsafe_sync_folder(sync_folder)
    folder = identity.folder(sync_folder)
    refuse_unsafe_sync_folder(folder)
    paths = identity.key_path(sync_folder), identity.certificate_path(sync_folder)
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise IdentityRefused(f"the sync identity's files are missing from {folder}. Rotate "
                                  "the identity with sync identity rotate.")
        refuse_unless_private(path, private_mode="600")
    if certificate_sha256(paths[1].read_bytes()) != identity.certificate_sha256:
        raise IdentityRefused(f"the certificate in {folder} is not the one this ledger "
                              "recorded. Rotate the identity with sync identity rotate.")
    return paths


def made_identity_folder(sync_folder: Path) -> tuple[str, str]:
    """A new identity's folder in place, as (identity ID, certificate SHA-256)."""
    identity_id = str(uuid.uuid4())
    partial = sync_folder / f".{identity_id}.partial"
    partial.mkdir(mode=0o700)
    try:
        key_path, certificate_path = partial / KEY_NAME, partial / CERTIFICATE_NAME
        run_openssl(key_path, certificate_path)
        for path in (key_path, certificate_path):
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise IdentityRefused("openssl did not write the identity's files. Nothing was "
                                      "changed.")
            os.chmod(path, 0o600)
        fingerprint = certificate_sha256(certificate_path.read_bytes())
        os.rename(partial, sync_folder / identity_id)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return identity_id, fingerprint


def record_identity(conn: sqlite3.Connection, identity_id: str, fingerprint: str) -> None:
    conn.execute("INSERT INTO sync_identity (identity_id, certificate_sha256) VALUES (?, ?)",
                 (identity_id, fingerprint))


def retire_identity(conn: sqlite3.Connection, identity_id: str) -> None:
    conn.execute("INSERT INTO sync_identity_event (identity_id, event) VALUES (?, 'retired')",
                 (identity_id,))


def remove_identity_folder(sync_folder: Path, identity_id: str) -> None:
    """A retired identity's key is deleted: nothing may use it again."""
    shutil.rmtree(sync_folder / identity_id, ignore_errors=True)
