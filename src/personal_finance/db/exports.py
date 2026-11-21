"""CSV export to a gated destination (D-073 point 7, M17.4).

An export writes one new file only. Its folder passes the real-ledger folder checks (D-058): no
symbolic link on the way, not in a git work tree, not in a synced folder, private to you, and for
a real ledger on an encrypted disk image. An existing file is refused, the file is created 0600
with O_EXCL, so nothing is overwritten and no temporary copy is made, and a failure while writing
removes what was written. Cells a spreadsheet would read as a formula are prefixed with an
apostrophe; amounts, which are never text, keep their sign.
"""

import csv
import io
import os
from pathlib import Path

from personal_finance.db import real_ledger as checks
from personal_finance.db.real_ledger import UnsafeLocation

FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


class ExportRefused(Exception):
    """An export that was not written, saying why. Nothing was written."""


def protected_cell(text: str) -> str:
    """A text cell as a spreadsheet will not read it as a formula."""
    return "'" + text if text.startswith(FORMULA_STARTS) else text


def refuse_unsafe_export_destination(out_path: Path, real_ledger: bool,
                                     noun: str = "an export") -> None:
    """The checks every file leaving the ledger folder passes: a pf export, and a snapshot
    (D-075 point 7), which names itself in the refusal."""
    absolute_path = Path(os.path.abspath(out_path))
    folder = absolute_path.parent
    if folder.resolve() != folder:
        raise ExportRefused(f"{noun} cannot be reached through a symbolic link: {folder} "
                            f"leads to {folder.resolve()}. Nothing was written.")
    if os.path.lexists(absolute_path):
        raise ExportRefused(f"{out_path} already exists, and {noun} never replaces a file. "
                            "Nothing was written.")
    if not folder.is_dir():
        raise ExportRefused(f"the folder for {noun} must already exist: {folder}. Nothing was "
                            "written.")
    try:
        work_tree = checks.git_work_tree_containing(folder)
        if work_tree is not None:
            raise UnsafeLocation(f"{noun} cannot be inside a git work tree: {work_tree}")
        synced_folder = checks.synced_folder_containing(folder)
        if synced_folder is not None:
            raise UnsafeLocation(f"{noun} cannot be inside a synced folder: {synced_folder}")
        checks.refuse_unless_private(folder, private_mode="700")
        if real_ledger:
            checks.refuse_unless_on_encrypted_disk_image(folder)
    except UnsafeLocation as refusal:
        raise ExportRefused(f"the {noun.split(' ', 1)[1]} destination is refused: {refusal}. "
                            "Nothing was written.") from None


def csv_text(header: tuple[str, ...], rows, amount_columns: frozenset[str] = frozenset()) -> str:
    """The rows as CSV, each text cell protected, amount columns as they are, and None empty."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if value is None else value if name in amount_columns
                         else protected_cell(str(value)) for name, value in zip(header, row)])
    return buffer.getvalue()


def write_export(out_path: Path, text: str, real_ledger: bool) -> int:
    """Write text to a new private file at out_path, refusing an unsafe destination. Returns the
    bytes written."""
    refuse_unsafe_export_destination(out_path, real_ledger)
    content = text.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(out_path, flags, 0o600)
    except FileExistsError:
        raise ExportRefused(f"{out_path} already exists, and an export never replaces a file. "
                            "Nothing was written.") from None
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        Path(out_path).unlink(missing_ok=True)
        raise
    return len(content)
