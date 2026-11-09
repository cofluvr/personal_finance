"""Where a real ledger may live, and where its imports may come from (D-058, M5.1 and M5.2).

A real ledger holds actual financial data. It is marked once, by `pf init --real`, and every open
checks its location before anything else. A synthetic ledger is never checked and behaves as before.
Each check refuses, naming the rule. None repairs: a wrong mode is reported with the command to fix it.

The location must be a folder inside a mounted disk image whose APFS volume honours file ownership,
and which diskutil reports encrypted or hdiutil reports encrypted as an image. FileVault on the
startup volume does not count (D-058 point 3, as amended). Any answer other than a clear yes refuses.
"""

import os
import plistlib
import sqlite3
from pathlib import Path
from xml.parsers.expat import ExpatError

from personal_finance.db import volume_probes

# Folders a sync client copies off this machine. Relative to the home folder.
SYNCED_FOLDERS_UNDER_HOME = ("Library/Mobile Documents", "Library/CloudStorage", "Dropbox")


class UnsafeLocation(Exception):
    pass


def is_real_ledger(conn: sqlite3.Connection) -> bool:
    """A ledger is real when it holds the marker row. Before migration 0017 none is."""
    has_marker_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'real_ledger'"
    ).fetchone()
    return bool(has_marker_table) and bool(conn.execute("SELECT 1 FROM real_ledger").fetchone())


def mark_real_ledger(conn: sqlite3.Connection) -> None:
    """Mark a ledger holding nothing yet as real. The schema refuses any other ledger."""
    conn.execute("INSERT INTO real_ledger (only_row) VALUES (1)")


def git_work_tree_containing(path: Path) -> Path | None:
    """The nearest folder at or above path holding `.git`, as a directory or a file."""
    for folder in (path, *path.parents):
        if (folder / ".git").exists():
            return folder
    return None


def synced_folder_containing(path: Path) -> Path | None:
    home = Path.home().resolve()
    for relative_folder in SYNCED_FOLDERS_UNDER_HOME:
        synced_folder = home / relative_folder
        if path == synced_folder or synced_folder in path.parents:
            return synced_folder
    return None


def refuse_unsafe_real_ledger_location(database_path: Path) -> None:
    """Refuse a real ledger's database path, existing or not, unless every rule holds."""
    absolute_path = Path(os.path.abspath(database_path))
    resolved_path = database_path.resolve()
    if resolved_path != absolute_path:
        raise UnsafeLocation(
            f"a real ledger cannot be reached through a symbolic link: {database_path} leads to "
            f"{resolved_path}"
        )
    folder = resolved_path.parent
    if not folder.is_dir():
        raise UnsafeLocation(f"the folder for a real ledger must already exist: {folder}")
    work_tree = git_work_tree_containing(folder)
    if work_tree is not None:
        raise UnsafeLocation(f"a real ledger cannot be inside a git work tree: {work_tree}")
    synced_folder = synced_folder_containing(folder)
    if synced_folder is not None:
        raise UnsafeLocation(f"a real ledger cannot be inside a synced folder: {synced_folder}")
    refuse_unless_private(folder, private_mode="700")
    if resolved_path.exists():
        refuse_unless_private(resolved_path, private_mode="600")
    refuse_unless_on_encrypted_disk_image(folder)


def refuse_unless_private(path: Path, *, private_mode: str) -> None:
    status = path.stat()
    if status.st_uid != os.geteuid():
        raise UnsafeLocation(f"a real ledger's files must be owned by you: {path}")
    if status.st_mode & 0o077:
        raise UnsafeLocation(
            f"a real ledger's files must be private to you: {path}. Run: chmod {private_mode} {path}"
        )


def mount_point_containing(folder: Path) -> Path:
    """The nearest mount point at or above folder. `/` always is one."""
    candidate = folder
    while not os.path.ismount(candidate):
        candidate = candidate.parent
    return candidate


def refuse_unless_on_encrypted_disk_image(folder: Path) -> None:
    mount_point = mount_point_containing(folder)
    if mount_point == folder:
        raise UnsafeLocation(
            f"a real ledger must be in a folder inside its volume, not at the volume's root: {folder}"
        )
    volume = probe_answer(
        lambda: volume_probes.diskutil_info_plist(mount_point),
        could_not_ask=f"could not ask diskutil whether {mount_point} is encrypted",
        could_not_describe=f"diskutil could not describe {mount_point}",
    )
    if volume.get("MountPoint") != str(mount_point):
        raise UnsafeLocation(
            f"diskutil described a volume other than {mount_point}, so the real ledger stays closed"
        )
    if volume.get("BusProtocol") != "Disk Image":
        raise UnsafeLocation(
            f"a real ledger must be on a mounted disk image, and {mount_point} is not one. FileVault "
            "on the startup volume does not count"
        )
    if volume.get("FilesystemType") != "apfs":
        raise UnsafeLocation(f"a real ledger's disk image must hold an APFS volume: {mount_point}")
    if volume.get("GlobalPermissionsEnabled") is not True:
        raise UnsafeLocation(
            f"{mount_point} ignores file ownership, so its permissions protect nothing. Run: "
            f"sudo diskutil enableOwnership {mount_point}"
        )
    if volume.get("Encryption") is not True and not disk_image_is_encrypted(volume, mount_point):
        raise UnsafeLocation(
            f"neither the APFS volume at {mount_point} nor the disk image holding it is reported "
            "encrypted"
        )


def disk_image_is_encrypted(volume: dict, mount_point: Path) -> bool:
    """Whether the one attached disk image backing this volume's device at this mount point says it
    is encrypted. diskutil cannot see encryption of the image file itself (D-058 point 3)."""
    attached = probe_answer(
        volume_probes.hdiutil_info_plist,
        could_not_ask=f"could not ask hdiutil whether the disk image holding {mount_point} is "
                      "encrypted",
        could_not_describe="hdiutil could not describe the attached disk images",
    )
    images = attached.get("images")
    if not isinstance(images, list):
        raise UnsafeLocation(
            "hdiutil could not describe the attached disk images, so the real ledger stays closed"
        )
    volume_device = f"/dev/{volume.get('DeviceIdentifier')}"
    images_holding_the_volume = [
        image for image in images
        if isinstance(image, dict) and isinstance(image.get("system-entities"), list)
        and any(
            isinstance(entity, dict) and entity.get("dev-entry") == volume_device
            and entity.get("mount-point") == str(mount_point)
            for entity in image["system-entities"]
        )
    ]
    if len(images_holding_the_volume) != 1:
        raise UnsafeLocation(
            f"hdiutil does not show exactly one disk image holding {mount_point}, so the real "
            "ledger stays closed"
        )
    return images_holding_the_volume[0].get("image-encrypted") is True


def probe_answer(ask, *, could_not_ask: str, could_not_describe: str) -> dict:
    """A probe's plist dictionary. Failing to run, a failed exit, an `Error` key or anything but a
    dictionary refuses."""
    try:
        exit_code, output = ask()
    except volume_probes.ProbeDidNotAnswer as failure:
        raise UnsafeLocation(f"{could_not_ask} ({failure}), so the real ledger stays closed") from None
    try:
        answer = plistlib.loads(output)
    except (ValueError, ExpatError):
        answer = None
    if exit_code != 0 or not isinstance(answer, dict) or "Error" in answer:
        raise UnsafeLocation(f"{could_not_describe}, so the real ledger stays closed")
    return answer


def check_real_ledger_on_open(conn: sqlite3.Connection, database_path: Path) -> None:
    """When the ledger is real, refuse an unsafe location, then keep SQLite's temporary files in
    memory, so no sort or index spills to the system temp folder (D-058 point 4). A synthetic
    ledger is neither checked nor changed."""
    if is_real_ledger(conn):
        refuse_unsafe_real_ledger_location(database_path)
        conn.execute("PRAGMA temp_store = MEMORY")


def refuse_import_from_git_work_tree(import_path: Path) -> None:
    work_tree = git_work_tree_containing(import_path.resolve())
    if work_tree is not None:
        raise UnsafeLocation(
            f"a real ledger does not import files from inside a git work tree: {import_path} is "
            f"inside {work_tree}"
        )
