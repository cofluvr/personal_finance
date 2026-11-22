"""Creating, verifying and listing snapshots, using synthetic data only (VB1 to VB3, D-075 points
4 and 7, the M19.2 slice plan). The builder and format are test_snapshot.py, and migration 0035
test_snapshot_migration.py."""

import json
import os
import re
import stat
import threading

import pytest
from test_local_ui import unchanged_state
from test_real_ledger import vault  # noqa: F401, a fixture
from test_snapshot import SnapshotLedger, household
from test_safe_to_spend import AS_OF

from personal_finance.db.migrate import connect
from personal_finance.snapshot import builder, files
from personal_finance.snapshot.canonical import canonical_bytes, sha256_of


@pytest.fixture
def ledger(tmp_path, capsys, vault):  # noqa: F811
    built = household(SnapshotLedger(tmp_path, capsys))
    built.vault = vault
    return built


def create(ledger, name="phone.json", *words):
    path = ledger.vault / name
    code, out, err = ledger.run("snapshot", "create", "--out", str(path), "--as-of", AS_OF,
                                *words)
    return code, out, err, path


def run_without_db(ledger, path):
    from personal_finance.cli import main

    ledger.capsys.readouterr()
    code = main(["snapshot", "verify", str(path)])
    captured = ledger.capsys.readouterr()
    return code, captured.out, captured.err


def records(ledger):
    conn = ledger.conn()
    try:
        return conn.execute("SELECT * FROM snapshot_record").fetchall()
    finally:
        conn.close()


class TestCreate:  # VB2, point 7
    def test_it_writes_a_new_private_file_and_records_it_without_the_path(self, ledger):
        code, out, err, path = create(ledger)
        assert (code, err) == (0, ""), err
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert sorted(os.listdir(ledger.vault)) == ["phone.json"]
        document = json.loads(path.read_bytes())
        (row,) = records(ledger)
        assert row[:6] == (document["snapshot_id"], builder.SCHEMA_VERSION, AS_OF, 90, document["generated_at"],
                           document["content_sha256"])
        assert str(path) not in repr(row) and "phone" not in repr(row)
        assert re.search(r"^Snapshot \S+ written to .*: \d+ bytes, schema "
                         + re.escape(builder.SCHEMA_VERSION) + r", as of "
                         r"2026-05-04, 2 transactions over 90 days\.$", out, re.MULTILINE)
        listed = ledger.run("snapshots")[1]
        assert f"Snapshot {document['snapshot_id']}: schema {builder.SCHEMA_VERSION}, as of {AS_OF}, 90 days" in listed

    def test_an_existing_file_is_refused_and_kept(self, ledger):
        path = ledger.vault / "phone.json"
        path.write_text("mine")
        code, _, err, _ = create(ledger)
        assert code == 2 and "already exists, and a snapshot never replaces a file" in err
        assert path.read_text() == "mine" and records(ledger) == []

    @pytest.mark.parametrize("unsafe", ["shared", "link", "missing", "git"])
    def test_an_unsafe_destination_is_refused_writing_nothing(self, ledger, unsafe):
        folder = ledger.vault
        if unsafe == "shared":
            folder.chmod(0o755)
        elif unsafe == "link":
            folder = ledger.vault.parent / "link"
            folder.symlink_to(ledger.vault)
        elif unsafe == "missing":
            folder = ledger.vault / "nope"
        else:
            folder = ledger.vault / "repository"
            folder.mkdir(mode=0o700)
            (folder / ".git").mkdir()
        before = sorted(os.listdir(ledger.vault))
        code, _, err = ledger.run("snapshot", "create", "--out", str(folder / "phone.json"),
                                  "--as-of", AS_OF)
        assert code == 2 and "Nothing was written" in err, err
        assert sorted(os.listdir(ledger.vault)) == before and records(ledger) == []

    def test_a_link_where_the_file_would_be_is_refused(self, ledger):
        (ledger.vault / "phone.json").symlink_to(ledger.vault / "elsewhere.json")
        code, _, err, _ = create(ledger)
        assert code == 2 and "already exists" in err
        assert not (ledger.vault / "elsewhere.json").exists() and records(ledger) == []

    def test_the_final_name_taken_while_writing_is_refused(self, ledger, monkeypatch):
        real_link = os.link

        def taken(source, target):
            open(target, "w").close()
            return real_link(source, target)

        monkeypatch.setattr(files.os, "link", taken)
        code, _, err, path = create(ledger)
        assert code == 2 and "never replaces a file" in err
        assert sorted(os.listdir(ledger.vault)) == ["phone.json"] and path.read_bytes() == b""
        assert records(ledger) == []

    def test_a_failed_record_leaves_the_file_and_says_so(self, ledger, monkeypatch):
        def failing(conn, document):
            raise RuntimeError("no")

        monkeypatch.setattr(files, "record", failing)
        code, _, err, path = create(ledger)
        assert code == 2 and "but recording it failed" in err and path.is_file()
        assert records(ledger) == []

    @pytest.mark.parametrize("days", ["0", "367", "x"])
    def test_the_window_is_1_to_366_days(self, ledger, days):
        code, _, err, path = create(ledger, "phone.json", "--window-days", days)
        assert code == 2 and "--window-days must be" in err and not path.exists()


class TestOneState:  # VB1, point 4
    def test_a_writer_waits_and_the_snapshot_is_the_state_before(self, ledger, monkeypatch):
        conn = connect(ledger.path, read_only=True)
        before = files.build_in_one_read(conn, builder.date.fromisoformat(AS_OF), 90,
                                         files.uuid.UUID(int=1, version=4).__str__(),
                                         "2026-05-04T00:00:00.000Z")
        wrote = threading.Event()
        started = threading.Event()

        def writer():
            started.set()
            other = connect(ledger.path)
            try:
                other.execute("INSERT INTO household_member (name) VALUES ('Cy')")
            finally:
                other.close()
            wrote.set()

        real_review = builder.review_section

        def during(review_conn):
            thread = threading.Thread(target=writer)
            thread.start()
            started.wait()
            assert not wrote.wait(0.5), "the writer committed during the build"
            during.thread = thread
            return real_review(review_conn)

        monkeypatch.setattr(builder, "review_section", during)
        made = files.build_in_one_read(conn, builder.date.fromisoformat(AS_OF), 90,
                                       files.uuid.UUID(int=1, version=4).__str__(),
                                       "2026-05-04T00:00:00.000Z")
        during.thread.join(10)
        assert wrote.is_set()
        assert made == before
        monkeypatch.setattr(builder, "review_section", real_review)
        after = files.build_in_one_read(conn, builder.date.fromisoformat(AS_OF), 90,
                                        files.uuid.UUID(int=1, version=4).__str__(),
                                        "2026-05-04T00:00:00.000Z")
        conn.close()
        assert after != before
        assert [member["name"] for member in json.loads(after)["content"]["household"][
            "members"]] == ["Alex", "Bea", "Cy"]


def rewritten(path, change):
    """The file with its content changed and its digest made right again, so only the change
    is wrong."""
    document = json.loads(path.read_bytes())
    change(document["content"])
    document["content_sha256"] = sha256_of(document["content"])
    path.write_bytes(canonical_bytes(document))


class TestVerify:  # VB3
    @pytest.fixture
    def written(self, ledger):
        code, _, err, path = create(ledger)
        assert code == 0, err
        return path

    def test_a_fresh_snapshot_verifies_writing_nothing(self, ledger, written):
        before = unchanged_state(ledger.path)
        code, out, err = ledger.run("snapshot", "verify", str(written))
        assert (code, err) == (0, ""), err
        assert out.endswith("recorded in this ledger.\n")
        code, out, _ = run_without_db(ledger, written)
        assert code == 0 and out.startswith("Snapshot ") and "recorded" not in out
        assert unchanged_state(ledger.path) == before

    def test_a_one_byte_change_is_refused(self, ledger, written):
        data = bytearray(written.read_bytes())
        position = data.index(b'"possible_duplicate":0') + len(b'"possible_duplicate":')
        data[position] = ord("1")
        written.write_bytes(bytes(data))
        code, _, err = run_without_db(ledger, written)
        assert code == 2 and "does not match its digest" in err

    def test_bytes_not_canonical_are_refused(self, ledger, written):
        written.write_bytes(written.read_bytes() + b"\n")
        code, _, err = run_without_db(ledger, written)
        assert code == 2 and "not in canonical form" in err

    def test_a_changed_digest_is_refused(self, ledger, written):
        document = json.loads(written.read_bytes())
        document["content_sha256"] = "0" * 64
        written.write_bytes(canonical_bytes(document))
        code, _, err = run_without_db(ledger, written)
        assert code == 2 and "does not match its digest" in err

    def test_a_broken_reconciliation_is_refused(self, ledger, written):
        rewritten(written, lambda content: content["months"][-1].update(
            net_cents=content["months"][-1]["net_cents"] + 1))
        code, _, err = run_without_db(ledger, written)
        assert code == 2 and "does not reconcile: month 2026-05" in err

    def test_an_excluded_key_is_refused(self, ledger, written):
        rewritten(written, lambda content: content["accounts"][0].update(last4="1234"))
        code, _, err = run_without_db(ledger, written)
        assert code == 2 and "holds an excluded key: content.accounts[0].last4" in err

    def test_a_schema_error_is_refused(self, ledger, written):
        rewritten(written, lambda content: content["review"].update(possible_duplicate="0"))
        code, _, err = run_without_db(ledger, written)
        assert code == 2 and "does not match its schema" in err

    def test_another_ledger_has_no_record(self, ledger, written, tmp_path, capsys):
        folder = tmp_path / "other"
        folder.mkdir()
        other = SnapshotLedger(folder, capsys)
        code, _, err = other.run("snapshot", "verify", str(written))
        assert code == 2 and "holds no record of this snapshot" in err

    def test_not_a_snapshot(self, ledger):
        path = ledger.vault / "other.json"
        path.write_bytes(b'{"a":1}')
        code, _, err = run_without_db(ledger, path)
        assert code == 2 and "this is not a snapshot" in err
