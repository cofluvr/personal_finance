"""Where a real ledger may live, and where its imports may come from (D-058, M5.1, M5.2, D-081).

A real ledger holds actual financial data. It is marked once, by `pf init --real`, with one of two
protections, and every open checks its location before anything else. A synthetic ledger is never
checked and behaves as before.

`encrypted_disk_image` (D-058, the default): the location must be a folder inside a mounted disk
image whose APFS volume honours file ownership, and which diskutil reports encrypted or hdiutil
reports encrypted as an image. FileVault on the startup volume does not count (D-058 point 3, as
amended). Any answer other than a clear yes refuses. Each check refuses, naming the rule. None
repairs: a wrong mode is reported with the command to fix it.

`private_folder` (D-081): any existing folder you own outside a git work tree, synced folders such
as iCloud Drive included, so two Macs can share one ledger. The folder, the database and the
originals folder are made private to you on every open, as a sync client restores its own file
modes on each download. A copy a sync client kept after a conflict, such as `ledger 2.db` beside
`ledger.db`, refuses every open until the owner keeps one of them.
"""

import os
import plistlib
import re
import sqlite3
import stat
from pathlib import Path
from xml.parsers.expat import ExpatError

from personal_finance.db import volume_probes

# Folders a sync client copies off this machine. Relative to the home folder.
SYNCED_FOLDERS_UNDER_HOME = ("Library/Mobile Documents", "Library/CloudStorage", "Dropbox")

# A real ledger's protections, as migration 0037 stores them (D-081).
ENCRYPTED_DISK_IMAGE = "encrypted_disk_image"
PRIVATE_FOLDER = "private_folder"


class UnsafeLocation(Exception):
    pass


def is_real_ledger(conn: sqlite3.Connection) -> bool:
    """A ledger is real when it holds the marker row. Before migration 0017 none is."""
    return real_ledger_protection(conn) is not None


def real_ledger_protection(conn: sqlite3.Connection) -> str | None:
    """A real ledger's protection, or None for a synthetic ledger. Before migration 0037 every
    real ledger is protected by an encrypted disk image."""
    has_marker_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'real_ledger'"
    ).fetchone()
    if not has_marker_table or not conn.execute("SELECT 1 FROM real_ledger").fetchone():
        return None
    marker_columns = {row[1] for row in conn.execute("PRAGMA table_info(real_ledger)")}
    if "protection" not in marker_columns:
        return ENCRYPTED_DISK_IMAGE
    return conn.execute("SELECT protection FROM real_ledger").fetchone()[0]


def requires_encrypted_disk_image(conn: sqlite3.Connection) -> bool:
    """Whether files leaving this ledger, such as exports and snapshots, must go to an encrypted
    disk image too."""
    return real_ledger_protection(conn) == ENCRYPTED_DISK_IMAGE


def mark_real_ledger(conn: sqlite3.Connection, protection: str = ENCRYPTED_DISK_IMAGE) -> None:
    """Mark a ledger holding nothing yet as real. The schema refuses any other ledger."""
    conn.execute("INSERT INTO real_ledger (only_row, protection) VALUES (1, ?)", (protection,))


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


def refuse_unsafe_location_for_protection(protection: str, database_path: Path) -> None:
    """The location rules of a real ledger with this protection, for its database path."""
    if protection == ENCRYPTED_DISK_IMAGE:
        refuse_unsafe_real_ledger_location(database_path)
    elif protection == PRIVATE_FOLDER:
        refuse_unsafe_private_folder_location(database_path)
    else:
        raise UnsafeLocation(f"this real ledger names a protection this code does not know: "
                             f"{protection}")


def refuse_unsafe_real_ledger_location(database_path: Path) -> None:
    """Refuse an encrypted-disk-image ledger's database path, existing or not, unless every rule
    holds."""
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


def refuse_unsafe_private_folder_location(database_path: Path) -> None:
    """Refuse a private-folder ledger's database path, existing or not, unless its folder exists
    outside a git work tree and is yours, then make the folder, the database and any originals
    folder private. A symbolic link is followed, and the rules apply where it leads. A synced
    folder is accepted."""
    resolved_path = database_path.resolve()
    folder = resolved_path.parent
    if not folder.is_dir():
        raise UnsafeLocation(f"the folder for a real ledger must already exist: {folder}")
    work_tree = git_work_tree_containing(folder)
    if work_tree is not None:
        raise UnsafeLocation(f"a real ledger cannot be inside a git work tree: {work_tree}")
    make_private(folder)
    if resolved_path.exists():
        make_private(resolved_path)
    # Named here, not imported, as originals.py imports this module.
    originals_folder = folder / "originals"
    if originals_folder.is_dir() and not originals_folder.is_symlink():
        make_private(originals_folder)


def make_private(path: Path) -> None:
    """Remove every permission others have on a path you own. A path someone else owns refuses."""
    status = path.stat()
    if status.st_uid != os.geteuid():
        raise UnsafeLocation(f"a real ledger's files must be owned by you: {path}")
    if status.st_mode & 0o077:
        os.chmod(path, stat.S_IMODE(status.st_mode) & ~0o077)


def conflicting_copies_beside(database_path: Path) -> list[Path]:
    """Copies a sync client keeps after a conflict, named like `ledger 2.db` beside `ledger.db`."""
    resolved_path = database_path.resolve()
    copy_name = re.compile(
        rf"{re.escape(resolved_path.stem)} \d+{re.escape(resolved_path.suffix)}")
    return sorted(entry for entry in resolved_path.parent.iterdir()
                  if copy_name.fullmatch(entry.name))


def refuse_conflicting_copies(database_path: Path) -> None:
    copies = conflicting_copies_beside(database_path)
    if copies:
        names = ", ".join(copy.name for copy in copies)
        raise UnsafeLocation(
            f"a sync service kept a conflicting copy of this ledger beside it: {names}. Two "
            "computers changed the ledger before syncing finished, so each copy holds changes the "
            "other lacks. Nothing was opened. Look at each copy with --db, keep the one to go on "
            f"with as {database_path.resolve().name}, and move the other out of this folder"
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
    """When the ledger is real, refuse an unsafe location for its protection, then keep SQLite's
    temporary files in memory, so no sort or index spills to the system temp folder (D-058 point
    4). A private-folder ledger with a sync conflict's copy beside it refuses too. A synthetic
    ledger is neither checked nor changed."""
    protection = real_ledger_protection(conn)
    if protection is None:
        return
    refuse_unsafe_location_for_protection(protection, database_path)
    if protection == PRIVATE_FOLDER:
        refuse_conflicting_copies(database_path)
    conn.execute("PRAGMA temp_store = MEMORY")


def refuse_import_from_git_work_tree(import_path: Path) -> None:
    work_tree = git_work_tree_containing(import_path.resolve())
    if work_tree is not None:
        raise UnsafeLocation(
            f"a real ledger does not import files from inside a git work tree: {import_path} is "
            f"inside {work_tree}"
        )
