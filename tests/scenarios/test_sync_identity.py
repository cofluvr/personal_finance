"""The Mac's sync identity, devices and dv1, using synthetic data only (YA1, D-076 points 2 and 6,
the M20.1 slice plan points 2 and 3). Identity create runs the one pinned openssl command and
writes 0600 files in a 0700 folder; rotation and revocation take dv1 tokens covering what they act
on."""

import base64
import hashlib
import os
import ssl
import stat
import subprocess
from dataclasses import replace

import pytest
from sync_harness import SyncLedger

from personal_finance.sync import devices, identity
from personal_finance.sync.devices import SyncRefused, sync_lock


@pytest.fixture
def ledger(tmp_path, capsys):
    return SyncLedger(tmp_path, capsys)


@pytest.fixture
def made(ledger):
    ledger.made = ledger.make_identity()
    return ledger


# DER of the OIDs 1.2.840.10045.3.1.7 (prime256v1) and 1.2.840.10045.1.1 (prime-field), which
# only explicit parameters hold.
PRIME256V1_OID = bytes.fromhex("06082a8648ce3d030107")
PRIME_FIELD_OID = bytes.fromhex("06072a8648ce3d0101")


def mode(path):
    return stat.S_IMODE(path.lstat().st_mode)


class TestCreate:  # YA1, point 2
    def test_it_writes_a_private_key_and_certificate_and_records_the_fingerprint(self, ledger):
        code, out, err = ledger.run("sync", "identity", "create")
        assert (code, err) == (0, ""), err
        made = ledger.identity()
        folder = made.folder(ledger.sync_folder)
        assert mode(ledger.sync_folder) == mode(folder) == 0o700
        assert sorted(os.listdir(folder)) == ["certificate.pem", "key.pem"]
        assert all(mode(folder / name) == 0o600 for name in os.listdir(folder))
        assert sorted(os.listdir(ledger.sync_folder)) == [made.identity_id, "sync.lock"]
        der = ssl.PEM_cert_to_DER_cert((folder / "certificate.pem").read_text())
        assert made.certificate_sha256 == hashlib.sha256(der).hexdigest()
        assert f"Fingerprint: {made.certificate_sha256}" in out
        key_text = (folder / "key.pem").read_text()
        body = "".join(key_text.splitlines()[1:-1])
        assert body not in out and body[:20] not in out
        assert ledger.table("sync_identity") == [(made.identity_id, made.certificate_sha256,
                                                 made.created_at)]

    def test_the_key_and_certificate_name_the_p256_curve_and_the_server_loads_them(self, made):
        """LibreSSL writes a curve's explicit parameters unless told to name it, and the phone's
        TLS refuses those: both files must carry P-256's OID, not a prime field's."""
        assert isinstance(made.context(), ssl.SSLContext)
        folder = made.made.folder(made.sync_folder)
        text = (folder / "key.pem").read_text()
        assert text.startswith("-----BEGIN PRIVATE KEY-----")
        key_der = base64.b64decode("".join(text.splitlines()[1:-1]))
        certificate_der = ssl.PEM_cert_to_DER_cert((folder / "certificate.pem").read_text())
        for der in (key_der, certificate_der):
            assert PRIME256V1_OID in der and PRIME_FIELD_OID not in der
        # A named P-256 key's PKCS#8 DER is 138 bytes; with explicit parameters it is 381.
        assert len(key_der) == 138

    def test_it_runs_exactly_the_pinned_command(self, ledger, monkeypatch):
        calls = []
        real_run = subprocess.run

        def recording_run(arguments, **options):
            calls.append((arguments, options))
            return real_run(arguments, **options)

        monkeypatch.setattr(identity.subprocess, "run", recording_run)
        ledger.make_identity()
        ((arguments, options),) = calls
        partial = arguments[-3].rsplit("/", 1)[0]
        assert arguments == [
            "/usr/bin/openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
            "ec_paramgen_curve:prime256v1", "-pkeyopt", "ec_param_enc:named_curve", "-nodes", "-days", "3650", "-subj",
            "/CN=commoncents-sync", "-keyout", f"{partial}/key.pem", "-out",
            f"{partial}/certificate.pem"]
        assert partial.endswith(".partial") and partial.startswith(str(ledger.sync_folder))
        assert options == {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                           "stderr": subprocess.DEVNULL, "env": {}, "timeout": 30,
                           "check": False}

    def test_it_refuses_an_existing_identity_changing_nothing(self, made):
        before = sorted(os.listdir(made.sync_folder))
        code, _, err = made.run("sync", "identity", "create")
        assert code == 2 and "already has a sync identity" in err
        assert sorted(os.listdir(made.sync_folder)) == before
        assert len(made.table("sync_identity")) == 1

    @pytest.mark.parametrize("program", ["/no/such/openssl", "/usr/bin/false"])
    def test_a_failed_openssl_leaves_nothing(self, ledger, monkeypatch, program):
        monkeypatch.setattr(identity, "OPENSSL", program)
        code, _, err = ledger.run("sync", "identity", "create")
        assert code == 2 and "no identity was made" in err
        assert os.listdir(ledger.sync_folder) == ["sync.lock"]
        assert ledger.table("sync_identity") == []

    def test_a_failure_recording_it_removes_the_new_folder(self, ledger, monkeypatch):
        def failing(conn, identity_id, fingerprint):
            raise SyncRefused("refused for the test")

        monkeypatch.setattr(identity, "record_identity", failing)
        code, _, err = ledger.run("sync", "identity", "create")
        assert code == 2 and "refused for the test" in err
        assert os.listdir(ledger.sync_folder) == ["sync.lock"]

    def test_an_unsafe_sync_folder_is_refused(self, ledger):
        ledger.sync_folder.mkdir(mode=0o755)
        ledger.sync_folder.chmod(0o755)
        code, _, err = ledger.run("sync", "identity", "create")
        assert code == 2 and "chmod 700" in err
        assert os.listdir(ledger.sync_folder) == []

    def test_a_symbolic_link_for_the_sync_folder_is_refused(self, ledger, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        ledger.sync_folder.symlink_to(elsewhere)
        code, _, err = ledger.run("sync", "identity", "create")
        assert code == 2 and "symbolic link" in err
        assert os.listdir(elsewhere) == []


class TestTheFiles:  # point 2
    def test_missing_files_are_refused_naming_rotation(self, made):
        folder = made.made.folder(made.sync_folder)
        (folder / "key.pem").unlink()
        code, _, err = made.run("sync", "serve", "--address", "192.168.1.20")
        assert code == 2 and "sync identity rotate" in err

    def test_a_certificate_not_the_recorded_one_is_refused(self, made, tmp_path):
        folder = made.made.folder(made.sync_folder)
        identity.run_openssl(tmp_path / "k.pem", tmp_path / "c.pem")
        (folder / "certificate.pem").write_bytes((tmp_path / "c.pem").read_bytes())
        code, _, err = made.run("sync", "pair", "--name", "Phone", "--address", "192.168.1.20")
        assert code == 2 and "not the one this ledger recorded" in err

    def test_a_readable_key_is_refused(self, made):
        (made.made.folder(made.sync_folder) / "key.pem").chmod(0o644)
        code, _, err = made.run("sync", "serve", "--address", "192.168.1.20")
        assert code == 2 and "chmod 600" in err

    def test_a_backup_leaves_the_sync_folder_out(self, made, tmp_path):
        backup_folder = tmp_path / "backup"
        assert made.run("backup", "create", "--to", str(backup_folder))[0] == 0
        assert "sync" not in os.listdir(backup_folder)
        key = (made.made.folder(made.sync_folder) / "key.pem").read_bytes()
        for path in backup_folder.rglob("*"):
            if path.is_file():
                assert key not in path.read_bytes()


class TestShow:
    def test_without_an_identity(self, ledger):
        assert ledger.run("sync", "identity", "show")[:2] == (
            0, "No sync identity. Make one with sync identity create.\n")

    def test_it_shows_the_fingerprint_its_prefix_and_the_rotate_revision(self, made):
        code, out, err = made.run("sync", "identity", "show")
        assert (code, err) == (0, "")
        fingerprint = made.made.certificate_sha256
        assert out.splitlines()[1:3] == [f"  Fingerprint: {fingerprint}",
                                        f"  The phone shows its first 16 digits: "
                                        f"{fingerprint[:16]}"]
        assert made.rotate_token().startswith("dv1-")


class TestRevoke:  # point 6
    def test_revoking_takes_its_token_and_keeps_the_device_on_record(self, made, tmp_path):
        client = made.paired_client(tmp_path / "phone")
        token = made.revoke_token(client.device_id)
        code, out, err = made.run("sync", "revoke", client.device_id, "--revision", token)
        assert (code, err) == (0, ""), err
        assert out == (f"Device {client.device_id} revoked: Phone. Its next request is refused. "
                       "It stays on record.\n")
        _, listed, _ = made.run("sync", "devices")
        assert f"Device {client.device_id}: Phone, paired " in listed and ", revoked " in listed
        assert len(made.table("paired_device")) == 1

    def test_a_stale_token_is_refused(self, made, tmp_path):
        client = made.paired_client(tmp_path / "phone")
        code, _, err = made.run("sync", "revoke", client.device_id, "--revision",
                                "dv1-0000000000000000")
        assert code == 2 and "does not match this device now" in err
        assert made.table("paired_device_event") == []

    def test_revoking_twice_is_refused(self, made, tmp_path):
        client = made.paired_client(tmp_path / "phone")
        token = made.revoke_token(client.device_id)
        assert made.run("sync", "revoke", client.device_id, "--revision", token)[0] == 0
        conn = made.conn()
        revoked = devices.find_device(conn, client.device_id)
        conn.close()
        code, _, err = made.run("sync", "revoke", client.device_id, "--revision",
                                devices.revoke_revision(revoked))
        assert code == 2 and "already revoked" in err
        # The token shown before revoking no longer matches: the state moved it.
        assert made.run("sync", "revoke", client.device_id, "--revision", token)[0] == 2

    def test_an_unknown_device_is_refused(self, made):
        code, _, err = made.run("sync", "revoke", "33333333-3333-4333-8333-333333333333",
                                "--revision", "dv1-0000000000000000")
        assert code == 2 and "no paired device has that ID" in err

    def test_the_token_covers_each_input(self, made, tmp_path):
        client = made.paired_client(tmp_path / "phone")
        conn = made.conn()
        device = devices.find_device(conn, client.device_id)
        conn.close()
        token = devices.revoke_revision(device)
        for changed in ({"device_id": "x"}, {"name": "Other"}, {"identity_id": "x"},
                        {"created_at": "x"}, {"revoked_at": "x"}):
            assert devices.revoke_revision(replace(device, **changed)) != token
        assert devices.revoke_revision(replace(device, secret_sha256="0" * 64)) == token


class TestRotate:  # point 2, the M20.1 slice plan point 3
    def test_rotation_replaces_the_identity_and_revokes_every_device(self, made, tmp_path):
        first = made.paired_client(tmp_path / "one", name="One")
        second = made.paired_client(tmp_path / "two", name="Two")
        old = made.made
        token = made.rotate_token()
        code, out, err = made.run("sync", "identity", "rotate", "--revision", token)
        assert (code, err) == (0, ""), err
        new = made.identity()
        assert new.identity_id != old.identity_id
        assert "2 devices revoked" in out
        assert sorted(os.listdir(made.sync_folder)) == [new.identity_id, "sync.lock"]
        assert {row[0] for row in made.table("paired_device_event")} == {first.device_id,
                                                                         second.device_id}
        assert made.table("sync_identity_event")[0][:2] == (old.identity_id, "retired")

    def test_a_stale_token_is_refused_leaving_the_identity(self, made, tmp_path):
        token = made.rotate_token()
        made.paired_client(tmp_path / "phone")
        before = sorted(os.listdir(made.sync_folder))
        code, _, err = made.run("sync", "identity", "rotate", "--revision", token)
        assert code == 2 and "does not match this identity and its devices" in err
        assert sorted(os.listdir(made.sync_folder)) == before
        assert made.identity() == made.made

    def test_the_token_covers_the_identity_and_each_devices_state(self, made, tmp_path):
        client = made.paired_client(tmp_path / "phone")
        conn = made.conn()
        current, found = identity.required_identity(conn), devices.load_devices(conn)
        conn.close()
        token = devices.rotate_revision(current, found)
        other = identity.SyncIdentity(current.identity_id, "0" * 64, current.created_at)
        assert devices.rotate_revision(other, found) != token
        other = identity.SyncIdentity("x", current.certificate_sha256, current.created_at)
        assert devices.rotate_revision(other, found) != token
        assert devices.rotate_revision(current, []) != token
        revoked = [replace(found[0], revoked_at="x")]
        assert devices.rotate_revision(current, revoked) != token
        assert client.device_id == found[0].device_id

    def test_rotation_needs_an_identity(self, ledger):
        code, _, err = ledger.run("sync", "identity", "rotate", "--revision",
                                  "dv1-0000000000000000")
        assert code == 2 and "no sync identity" in err


class TestTheLock:  # point 5
    def test_a_second_holder_is_refused(self, made):
        with sync_lock(made.sync_folder):
            code, _, err = made.run("sync", "serve", "--address", "192.168.1.20")
            assert code == 2 and "another sync pair or sync serve is running" in err
            code, _, err = made.run("sync", "identity", "rotate", "--revision",
                                    made.rotate_token())
            assert code == 2 and "another sync pair or sync serve" in err
        with sync_lock(made.sync_folder):
            pass
