"""The application's only calls to other programs: `diskutil info -plist` and `hdiutil info -plist`
(D-058, M5.2).

Each returns the program's exit code and output unread. What they mean is decided in real_ledger.
"""

import subprocess
from pathlib import Path

DISKUTIL_PATH = "/usr/sbin/diskutil"
HDIUTIL_PATH = "/usr/bin/hdiutil"
SECONDS_TO_WAIT_FOR_A_PROBE = 30


class ProbeDidNotAnswer(Exception):
    pass


def diskutil_info_plist(mount_point: Path) -> tuple[int, bytes]:
    """Describe one volume. diskutil accepts its mount point, not other folders."""
    return run_probe([DISKUTIL_PATH, "info", "-plist", str(mount_point)])


def hdiutil_info_plist() -> tuple[int, bytes]:
    """Describe every attached disk image, with the devices and mount points it backs."""
    return run_probe([HDIUTIL_PATH, "info", "-plist"])


def run_probe(arguments: list[str]) -> tuple[int, bytes]:
    try:
        finished = subprocess.run(
            arguments,
            capture_output=True,
            timeout=SECONDS_TO_WAIT_FOR_A_PROBE,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as failure:
        raise ProbeDidNotAnswer(f"{Path(arguments[0]).name}: {type(failure).__name__}") from None
    return finished.returncode, finished.stdout
