"""The application's one call to another program: `diskutil info -plist` (D-058, M5.2).

It returns diskutil's exit code and output unread. What they mean is decided in real_ledger.
"""

import subprocess
from pathlib import Path

DISKUTIL_PATH = "/usr/sbin/diskutil"
SECONDS_TO_WAIT_FOR_DISKUTIL = 30


class DiskutilDidNotAnswer(Exception):
    pass


def info_plist(mount_point: Path) -> tuple[int, bytes]:
    """Run `diskutil info -plist` on a mount point. diskutil does not accept other folders."""
    try:
        finished = subprocess.run(
            [DISKUTIL_PATH, "info", "-plist", str(mount_point)],
            capture_output=True,
            timeout=SECONDS_TO_WAIT_FOR_DISKUTIL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as failure:
        raise DiskutilDidNotAnswer(type(failure).__name__) from None
    return finished.returncode, finished.stdout
