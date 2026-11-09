"""Encryption: a real ledger lives only on an encrypted disk image (E1 to E5, D-058 points 3, as
amended, and 4).

Neither diskutil nor hdiutil runs here, and no volume is mounted. Their answers are synthetic
recordings in tests/fixtures/synthetic/volume_probes, using the keys they report on macOS Golden
Gate 27.2.
"""

import os
import plistlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from test_decisions import CAFE, CARD_HEADER, Ledger
from test_real_ledger import (  # noqa: F401, vault is a fixture
    COMMANDS,
    SYNTHETIC_MOUNT_POINT,
    RealLedger,
    init_real,
    place_on_volume,
    probe_recording,
    vault,
)

from personal_finance import cli
from personal_finance.db import real_ledger, volume_probes

SOURCE_FOLDER = Path(__file__).parents[2] / "src"
STARTUP_DATA_VOLUME = Path("/System/Volumes/Data")


def changed_recording(**changes):
    """The passing recording with keys changed. A key given as None is removed."""
    volume = plistlib.loads(probe_recording("encrypted_disk_image"))
    for key, value in changes.items():
        if value is None:
            del volume[key]
        else:
            volume[key] = value
    return plistlib.dumps(volume)


def answer(diskutil_output, message, *, diskutil_exit_code=0, mount_point=SYNTHETIC_MOUNT_POINT,
           id):
    return pytest.param(diskutil_output, diskutil_exit_code, mount_point, message, id=id)


# Each answer breaks exactly one rule, so no broader refusal stands in for the one under test.
NOT_ENCRYPTED = (f"neither the APFS volume at {SYNTHETIC_MOUNT_POINT} nor the disk image holding "
                 "it is reported encrypted")
NOT_A_DISK_IMAGE = "must be on a mounted disk image"
UNDESCRIBED = f"diskutil could not describe {SYNTHETIC_MOUNT_POINT}"
REFUSED_ANSWERS = [
    answer(probe_recording("unencrypted_disk_image"), NOT_ENCRYPTED, id="not encrypted"),
    answer(changed_recording(Encryption=None), NOT_ENCRYPTED, id="encryption missing"),
    answer(changed_recording(Encryption="Yes"), NOT_ENCRYPTED, id="encryption a string"),
    answer(changed_recording(Encryption=1), NOT_ENCRYPTED, id="encryption a number"),
    answer(probe_recording("filevault_startup_volume"), NOT_A_DISK_IMAGE,
           mount_point=STARTUP_DATA_VOLUME, id="FileVault startup volume"),
    answer(changed_recording(BusProtocol=None), NOT_A_DISK_IMAGE, id="bus protocol missing"),
    answer(probe_recording("ownership_ignored_disk_image"),
           f"Run: sudo diskutil enableOwnership {SYNTHETIC_MOUNT_POINT}", id="ownership ignored"),
    answer(changed_recording(GlobalPermissionsEnabled=None), "ignores file ownership",
           id="ownership missing"),
    answer(changed_recording(FilesystemType="hfs"), "must hold an APFS volume", id="not APFS"),
    answer(changed_recording(MountPoint="/Volumes/Other"),
           f"described a volume other than {SYNTHETIC_MOUNT_POINT}", id="another volume"),
    answer(probe_recording("not_a_disk_error"), UNDESCRIBED, diskutil_exit_code=1,
           id="diskutil error"),
    answer(changed_recording(Error=True), UNDESCRIBED, id="error key"),
    answer(probe_recording("encrypted_disk_image"), UNDESCRIBED, diskutil_exit_code=1,
           id="failed exit code"),
    answer(b"", UNDESCRIBED, id="no output"),
    answer(b"not a plist", UNDESCRIBED, id="not a plist"),
    answer(b'<?xml version="1.0"?><plist><dict><key>Encryption</key>', UNDESCRIBED,
           id="truncated plist"),
    answer(plistlib.dumps([True]), UNDESCRIBED, id="not a dictionary"),
]

# One answer of each kind, for every kind of open.
REFUSED_ON_OPEN = [
    answer(probe_recording("unencrypted_disk_image"), NOT_ENCRYPTED, id="not encrypted"),
    answer(probe_recording("filevault_startup_volume"), NOT_A_DISK_IMAGE,
           mount_point=STARTUP_DATA_VOLUME, id="FileVault startup volume"),
    answer(probe_recording("not_a_disk_error"), UNDESCRIBED, diskutil_exit_code=1,
           id="diskutil error"),
]


def cannot_run_diskutil(mount_point):
    raise volume_probes.ProbeDidNotAnswer("diskutil: TimeoutExpired")


class TestInitOnlyOnAnEncryptedDiskImage:
    """E1, for init --real."""

    def test_an_encrypted_disk_image_is_accepted(self, vault, capsys, monkeypatch):
        asked = place_on_volume(monkeypatch, probe_recording("encrypted_disk_image"))
        code, err = init_real(capsys, vault / "ledger.db")
        assert (code, err) == (0, "")
        assert asked.diskutil_about == [SYNTHETIC_MOUNT_POINT]

    @pytest.mark.parametrize(("diskutil_output", "diskutil_exit_code", "mount_point", "message"),
                             REFUSED_ANSWERS)
    def test_any_other_answer_refuses_creating_nothing(self, vault, capsys, monkeypatch,
                                                       diskutil_output, diskutil_exit_code,
                                                       mount_point, message):
        place_on_volume(monkeypatch, diskutil_output, mount_point=mount_point,
                        diskutil_exit_code=diskutil_exit_code)
        code, err = init_real(capsys, vault / "ledger.db")
        assert code == 2
        assert message in err
        assert list(vault.iterdir()) == []

    def test_a_probe_that_cannot_run_refuses(self, vault, capsys, monkeypatch):
        monkeypatch.setattr(volume_probes, "diskutil_info_plist", cannot_run_diskutil)
        code, err = init_real(capsys, vault / "ledger.db")
        assert code == 2
        assert f"could not ask diskutil whether {SYNTHETIC_MOUNT_POINT} is encrypted" in err
        assert list(vault.iterdir()) == []

    def test_the_volume_root_is_refused_before_asking(self, vault, capsys, monkeypatch):
        asked = place_on_volume(monkeypatch, probe_recording("encrypted_disk_image"),
                                      mount_point=vault)
        code, err = init_real(capsys, vault / "ledger.db")
        assert code == 2
        assert f"not at the volume's root: {vault}" in err
        assert list(vault.iterdir()) == []
        assert asked.diskutil_about == []


class TestEveryOpenAsks:
    """E1, for every kind of open."""

    @pytest.mark.parametrize("command", COMMANDS)
    def test_every_open_asks_about_its_volume_once(self, vault, capsys, monkeypatch, command):
        ledger = RealLedger(vault, capsys)
        ledger.card("jan.csv", CAFE)
        asked = place_on_volume(monkeypatch, probe_recording("encrypted_disk_image"))
        code, _, err = ledger.run(*command)
        assert (code, err) == (0, "")
        assert asked.diskutil_about == [SYNTHETIC_MOUNT_POINT]

    @pytest.mark.parametrize(("diskutil_output", "diskutil_exit_code", "mount_point", "message"),
                             REFUSED_ON_OPEN)
    @pytest.mark.parametrize("command", COMMANDS)
    def test_a_refused_answer_refuses_with_nothing_changed(self, vault, capsys, monkeypatch,
                                                           command, diskutil_output,
                                                           diskutil_exit_code, mount_point,
                                                           message):
        ledger = RealLedger(vault, capsys)
        ledger.card("jan.csv", CAFE)
        before = ledger.everything()
        place_on_volume(monkeypatch, diskutil_output, mount_point=mount_point,
                        diskutil_exit_code=diskutil_exit_code)
        code, out, err = ledger.run(*command)
        assert code == 2
        assert message in err
        assert out == ""
        assert ledger.everything() == before

    def test_a_refused_answer_refuses_an_import(self, vault, capsys, monkeypatch):
        ledger = RealLedger(vault, capsys)
        path = ledger.write("jan.csv", CARD_HEADER, [CAFE])
        place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"))
        code, out, err = ledger.run("import", "--account", "A", "--layout", "synthetic_card_v1",
                                    str(path))
        assert code == 2
        assert NOT_ENCRYPTED in err
        assert out == ""
        assert ledger.count() == 0

    @pytest.mark.parametrize("command", COMMANDS)
    def test_a_probe_that_cannot_run_refuses_an_open(self, vault, capsys, monkeypatch, command):
        ledger = RealLedger(vault, capsys)
        before = ledger.everything()
        monkeypatch.setattr(volume_probes, "diskutil_info_plist", cannot_run_diskutil)
        code, _, err = ledger.run(*command)
        assert code == 2
        assert "could not ask diskutil whether" in err
        assert ledger.everything() == before


class TestTheProbe:
    """E2: the probe asks diskutil about the folder's mount point, never anything else."""

    def test_the_mount_point_is_the_nearest_one_at_or_above_the_folder(self, tmp_path):
        mount_point = real_ledger.mount_point_containing(tmp_path)
        assert os.path.ismount(mount_point)
        assert mount_point == tmp_path or mount_point in tmp_path.parents
        between = [tmp_path, *tmp_path.parents][:[tmp_path, *tmp_path.parents].index(mount_point)]
        assert not any(os.path.ismount(folder) for folder in between)

    def test_a_mount_point_is_its_own(self):
        assert real_ledger.mount_point_containing(Path("/")) == Path("/")

    @pytest.mark.parametrize(("probe", "expected_arguments"), [
        (lambda: volume_probes.diskutil_info_plist(SYNTHETIC_MOUNT_POINT),
         ["/usr/sbin/diskutil", "info", "-plist", "/Volumes/SyntheticLedger"]),
        (volume_probes.hdiutil_info_plist, ["/usr/bin/hdiutil", "info", "-plist"]),
    ], ids=["diskutil", "hdiutil"])
    def test_each_probe_runs_its_program_by_full_path(self, monkeypatch, probe,
                                                      expected_arguments):
        calls = []

        def run(arguments, **options):
            calls.append((arguments, options))
            return subprocess.CompletedProcess(arguments, 3, stdout=b"output", stderr=b"noise")

        monkeypatch.setattr(volume_probes.subprocess, "run", run)
        assert probe() == (3, b"output")
        [(arguments, options)] = calls
        assert arguments == expected_arguments
        assert options["capture_output"] is True
        assert options["timeout"] == volume_probes.SECONDS_TO_WAIT_FOR_A_PROBE

    @pytest.mark.parametrize("failure", [
        FileNotFoundError("diskutil"),
        PermissionError("diskutil"),
        subprocess.TimeoutExpired("diskutil", 30),
    ])
    def test_a_program_that_cannot_run_did_not_answer(self, monkeypatch, failure):
        def run(arguments, **options):
            raise failure

        monkeypatch.setattr(volume_probes.subprocess, "run", run)
        with pytest.raises(volume_probes.ProbeDidNotAnswer,
                           match=f"hdiutil: {type(failure).__name__}"):
            volume_probes.hdiutil_info_plist()


def temp_store_of_every_connection(monkeypatch, ledger, command):
    opened = []

    def recording_connect(*arguments, **options):
        conn = connect(*arguments, **options)
        opened.append(conn)
        return conn

    connect = cli.connect
    monkeypatch.setattr(cli, "connect", recording_connect)
    code, _, err = ledger.run(*command)
    assert (code, err) == (0, "")
    assert opened
    return {conn.execute("PRAGMA temp_store").fetchone()[0] for conn in opened}


# Run in a child process, since SQLite reads SQLITE_TMPDIR once, when a process first uses it.
LARGE_SORT_SCRIPT = textwrap.dedent("""
    import os, sys
    from pathlib import Path
    from personal_finance import cli
    from personal_finance.db import real_ledger

    # The location rules are tested apart. This child measures only the temporary storage.
    real_ledger.refuse_unsafe_real_ledger_location = lambda database_path: None
    database, temp_folder = sys.argv[1:]
    conn = cli.open_ledger(Path(database), read_only=True)
    conn.execute("PRAGMA cache_size = 16")
    before = os.stat(temp_folder).st_mtime_ns
    rows = conn.execute(
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 50000) "
        "SELECT randomblob(200) FROM n ORDER BY 1"
    ).fetchall()
    assert len(rows) == 50000
    print(os.stat(temp_folder).st_mtime_ns != before)
""")


def large_sort_touches_temp_folder(tmp_path, database):
    temp_folder = tmp_path / f"sqlite-temp-{database.parent.name}"
    temp_folder.mkdir()
    script = tmp_path / "large_sort.py"
    script.write_text(LARGE_SORT_SCRIPT)
    finished = subprocess.run(
        [sys.executable, str(script), str(database), str(temp_folder)],
        capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONPATH": str(SOURCE_FOLDER), "SQLITE_TMPDIR": str(temp_folder)},
    )
    assert finished.returncode == 0, finished.stderr
    return {"True\n": True, "False\n": False}[finished.stdout]


class TestTemporaryFilesStayInMemory:
    """E3."""

    @pytest.mark.parametrize("command", COMMANDS)
    def test_every_connection_to_a_real_ledger_keeps_them_in_memory(self, vault, capsys,
                                                                    monkeypatch, command):
        ledger = RealLedger(vault, capsys)
        ledger.card("jan.csv", CAFE)
        memory = 2
        assert temp_store_of_every_connection(monkeypatch, ledger, command) == {memory}

    def test_a_large_sort_on_a_real_ledger_writes_nothing_to_the_temp_folder(self, vault, capsys,
                                                                             tmp_path):
        real = RealLedger(vault, capsys)
        synthetic_folder = tmp_path / "synthetic"
        synthetic_folder.mkdir()
        synthetic = Ledger(synthetic_folder, capsys)
        # The control: the same sort on a synthetic ledger spills to the temp folder.
        assert large_sort_touches_temp_folder(tmp_path, synthetic.path) is True
        assert large_sort_touches_temp_folder(tmp_path, real.path) is False


class TestTheRollbackJournal:
    """E4."""

    def test_it_sits_beside_the_database_and_is_private_whatever_the_umask(self, vault, capsys):
        ledger = RealLedger(vault, capsys)
        journal = ledger.path.with_name(f"{ledger.path.name}-journal")
        conn = cli.open_ledger(ledger.path)
        umask_before = os.umask(0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE account SET display_name = 'B'")
            assert sorted(vault.iterdir()) == [ledger.path, journal]
            assert journal.stat().st_mode & 0o777 == 0o600
            conn.execute("ROLLBACK")
        finally:
            os.umask(umask_before)
            conn.close()
        assert sorted(vault.iterdir()) == [ledger.path]


class TestSyntheticLedgersAreNeverProbed:
    """E5, with every earlier criterion."""

    def test_no_command_on_a_synthetic_ledger_asks_diskutil(self, tmp_path, capsys, monkeypatch):
        # An answer that would refuse, so a probe would also fail the command.
        asked = place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"))
        ledger = Ledger(tmp_path, capsys)
        ledger.card("jan.csv", CAFE)
        for command in COMMANDS:
            code, _, err = ledger.run(*command)
            assert (code, err) == (0, "")
        assert asked.diskutil_about == []
        assert asked.hdiutil == 0

    @pytest.mark.parametrize("command", COMMANDS)
    def test_a_synthetic_ledger_keeps_the_default_temporary_storage(self, tmp_path, capsys,
                                                                    monkeypatch, command):
        ledger = Ledger(tmp_path, capsys)
        ledger.card("jan.csv", CAFE)
        default = 0
        assert temp_store_of_every_connection(monkeypatch, ledger, command) == {default}


def changed_hdiutil_recording(change):
    """The passing hdiutil recording, with `change` applied to its images and the ledger's image."""
    attached = plistlib.loads(probe_recording("hdiutil_image_encrypted"))
    [ledger_image] = [image for image in attached["images"]
                      if image["image-path"].endswith("SyntheticLedger.sparsebundle")]
    change(attached, ledger_image)
    return plistlib.dumps(attached)


def without_key(key):
    return lambda attached, ledger_image: ledger_image.pop(key)


def set_value(key, value):
    return lambda attached, ledger_image: ledger_image.__setitem__(key, value)


def change_volume_entity(key, value):
    def change(attached, ledger_image):
        [volume_entity] = [entity for entity in ledger_image["system-entities"]
                           if "mount-point" in entity]
        volume_entity[key] = value
    return change


def hdiutil_answer(hdiutil_output, message, *, hdiutil_exit_code=0,
                   diskutil_output=probe_recording("unencrypted_disk_image"), id):
    return pytest.param(diskutil_output, hdiutil_output, hdiutil_exit_code, message, id=id)


# diskutil reports the APFS volume unencrypted throughout, so only hdiutil's answer decides. Each
# answer breaks exactly one thing in the passing one.
NOT_EXACTLY_ONE_IMAGE = (f"hdiutil does not show exactly one disk image holding "
                         f"{SYNTHETIC_MOUNT_POINT}")
HDIUTIL_UNDESCRIBED = "hdiutil could not describe the attached disk images"
REFUSED_HDIUTIL_ANSWERS = [
    hdiutil_answer(probe_recording("hdiutil_image_not_encrypted"), NOT_ENCRYPTED,
                   id="image not encrypted"),
    hdiutil_answer(changed_hdiutil_recording(without_key("image-encrypted")), NOT_ENCRYPTED,
                   id="image encryption missing"),
    hdiutil_answer(changed_hdiutil_recording(set_value("image-encrypted", "YES")), NOT_ENCRYPTED,
                   id="image encryption a string"),
    hdiutil_answer(changed_hdiutil_recording(
        lambda attached, ledger_image: attached["images"].remove(ledger_image)),
        NOT_EXACTLY_ONE_IMAGE, id="no image holds the volume"),
    hdiutil_answer(changed_hdiutil_recording(
        lambda attached, ledger_image: attached["images"].append(dict(ledger_image))),
        NOT_EXACTLY_ONE_IMAGE, id="two images hold the volume"),
    hdiutil_answer(changed_hdiutil_recording(change_volume_entity("mount-point", "/Volumes/Other")),
                   NOT_EXACTLY_ONE_IMAGE, id="the device at another mount point"),
    hdiutil_answer(changed_hdiutil_recording(change_volume_entity("dev-entry", "/dev/disk91s1")),
                   NOT_EXACTLY_ONE_IMAGE, id="another device at the mount point"),
    hdiutil_answer(changed_hdiutil_recording(set_value("system-entities", 90)),
                   NOT_EXACTLY_ONE_IMAGE, id="entities not a list"),
    hdiutil_answer(probe_recording("hdiutil_image_encrypted"), NOT_EXACTLY_ONE_IMAGE,
                   diskutil_output=changed_recording(Encryption=False, EncryptionThisVolumeProper=False,
                                                     FileVault=False, DeviceIdentifier=None),
                   id="diskutil names no device"),
    hdiutil_answer(changed_hdiutil_recording(
        lambda attached, ledger_image: attached.__setitem__("images", {"0": ledger_image})),
        HDIUTIL_UNDESCRIBED, id="images not a list"),
    hdiutil_answer(changed_hdiutil_recording(
        lambda attached, ledger_image: attached.__setitem__("Error", True)),
        HDIUTIL_UNDESCRIBED, id="error key"),
    hdiutil_answer(probe_recording("hdiutil_image_encrypted"), HDIUTIL_UNDESCRIBED,
                   hdiutil_exit_code=1, id="failed exit code"),
    hdiutil_answer(b"not a plist", HDIUTIL_UNDESCRIBED, id="not a plist"),
]


class TestAnEncryptedImageFile:
    """D-058 point 3, as amended a second time: a disk image encrypted as a file, holding an APFS
    volume that diskutil reports unencrypted, is accepted when hdiutil reports the image encrypted."""

    def test_it_is_accepted_by_init(self, vault, capsys, monkeypatch):
        asked = place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"),
                                hdiutil_output=probe_recording("hdiutil_image_encrypted"))
        code, err = init_real(capsys, vault / "ledger.db")
        assert (code, err) == (0, "")
        assert (asked.diskutil_about, asked.hdiutil) == ([SYNTHETIC_MOUNT_POINT], 1)

    @pytest.mark.parametrize("command", COMMANDS)
    def test_it_is_accepted_by_every_open(self, vault, capsys, monkeypatch, command):
        ledger = RealLedger(vault, capsys)
        ledger.card("jan.csv", CAFE)
        asked = place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"),
                                hdiutil_output=probe_recording("hdiutil_image_encrypted"))
        code, _, err = ledger.run(*command)
        assert (code, err) == (0, "")
        assert asked.hdiutil == 1

    def test_hdiutil_is_not_asked_when_the_volume_is_encrypted(self, vault, capsys, monkeypatch):
        asked = place_on_volume(monkeypatch, probe_recording("encrypted_disk_image"),
                                hdiutil_output=b"not a plist")
        code, err = init_real(capsys, vault / "ledger.db")
        assert (code, err) == (0, "")
        assert asked.hdiutil == 0

    @pytest.mark.parametrize(("diskutil_output", "hdiutil_output", "hdiutil_exit_code", "message"),
                             REFUSED_HDIUTIL_ANSWERS)
    def test_any_other_answer_refuses_creating_nothing(self, vault, capsys, monkeypatch,
                                                       diskutil_output, hdiutil_output,
                                                       hdiutil_exit_code, message):
        place_on_volume(monkeypatch, diskutil_output, hdiutil_output=hdiutil_output,
                        hdiutil_exit_code=hdiutil_exit_code)
        code, err = init_real(capsys, vault / "ledger.db")
        assert code == 2
        assert message in err
        assert list(vault.iterdir()) == []

    @pytest.mark.parametrize("command", COMMANDS)
    def test_an_image_no_longer_encrypted_refuses_every_open(self, vault, capsys, monkeypatch,
                                                             command):
        ledger = RealLedger(vault, capsys)
        ledger.card("jan.csv", CAFE)
        before = ledger.everything()
        place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"),
                        hdiutil_output=probe_recording("hdiutil_image_not_encrypted"))
        code, out, err = ledger.run(*command)
        assert code == 2
        assert NOT_ENCRYPTED in err
        assert out == ""
        assert ledger.everything() == before

    def test_hdiutil_that_cannot_run_refuses(self, vault, capsys, monkeypatch):
        place_on_volume(monkeypatch, probe_recording("unencrypted_disk_image"))

        def cannot_run_hdiutil():
            raise volume_probes.ProbeDidNotAnswer("hdiutil: FileNotFoundError")

        monkeypatch.setattr(volume_probes, "hdiutil_info_plist", cannot_run_hdiutil)
        code, err = init_real(capsys, vault / "ledger.db")
        assert code == 2
        assert ("could not ask hdiutil whether the disk image holding /Volumes/SyntheticLedger is "
                "encrypted (hdiutil: FileNotFoundError)") in err
        assert list(vault.iterdir()) == []
