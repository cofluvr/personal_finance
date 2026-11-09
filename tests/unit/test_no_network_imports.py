"""No network, and it is shown (W1, D-058 point 9).

Every module under src/ is parsed, not run. Point 9's modules are refused, with others that reach the
network or run another program, and `os`'s calls that run a program. Dynamic imports are refused
whatever they name, since a name built at run time cannot be checked. The one allowance is
`subprocess` in db/volume_probes.py, for `diskutil` and `hdiutil`.
"""

import ast
import shutil
from pathlib import Path

import pytest

import personal_finance

PACKAGE_FOLDER = Path(personal_finance.__file__).parent
REFUSED_MODULES = {
    # Point 9.
    "socket", "ssl", "http", "urllib", "ftplib", "smtplib", "subprocess",
    # The same reach by other names.
    "_socket", "_ssl", "asyncio", "socketserver", "xmlrpc", "poplib", "imaplib", "nntplib",
    "telnetlib", "webbrowser", "multiprocessing", "concurrent", "pty", "ctypes",
}
PROGRAM_RUNNING_OS_CALLS = {
    "system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp",
    "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
}
ALLOWED = {("db/volume_probes.py", "subprocess")}


def refused_uses(source: str, relative_path: str) -> list[str]:
    """Each refused import, dynamic import or program-running `os` call in one module's source."""
    found = []

    def refuse_module(module_name: str, line: int) -> None:
        top_level = module_name.split(".")[0]
        if top_level in REFUSED_MODULES and (relative_path, top_level) not in ALLOWED:
            found.append(f"{relative_path}:{line} imports {module_name}")

    tree = ast.parse(source)
    # The module each imported name stands for, so an alias such as `import os as o` is seen.
    bound_modules = {alias.asname or alias.name.split(".")[0]:
                     alias.name if alias.asname else alias.name.split(".")[0]
                     for node in ast.walk(tree) if isinstance(node, ast.Import)
                     for alias in node.names}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refuse_module(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                refuse_module(node.module, node.lineno)
                if node.module == "os":
                    for alias in node.names:
                        if alias.name in PROGRAM_RUNNING_OS_CALLS:
                            found.append(f"{relative_path}:{node.lineno} imports os.{alias.name}")
                if node.module == "importlib":
                    found.append(f"{relative_path}:{node.lineno} imports from importlib")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module_name = bound_modules.get(node.value.id, node.value.id)
            if module_name == "os" and node.attr in PROGRAM_RUNNING_OS_CALLS:
                found.append(f"{relative_path}:{node.lineno} uses os.{node.attr}")
            if module_name == "importlib" and node.attr == "import_module":
                found.append(f"{relative_path}:{node.lineno} imports dynamically")
        elif isinstance(node, ast.Name) and node.id == "__import__":
            found.append(f"{relative_path}:{node.lineno} imports dynamically")
    return found


def refused_uses_under(package_folder: Path) -> tuple[list[str], list[str]]:
    found, modules = [], []
    for path in sorted(package_folder.rglob("*.py")):
        relative_path = path.relative_to(package_folder).as_posix()
        modules.append(relative_path)
        found += refused_uses(path.read_text(encoding="utf-8"), relative_path)
    return found, modules


def test_no_module_reaches_the_network_or_runs_a_program():
    found, modules = refused_uses_under(PACKAGE_FOLDER)
    assert found == []
    assert {"cli.py", "db/volume_probes.py", "db/backups.py", "ingest/pipeline.py",
            "reports/storage.py"} <= set(modules)


def test_the_one_allowance_is_used_by_one_call_to_a_fixed_program():
    """The allowance is not stale, and the probes run only `diskutil` and `hdiutil`."""
    tree = ast.parse((PACKAGE_FOLDER / "db" / "volume_probes.py").read_text())
    imported = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names]
    assert "subprocess" in imported
    subprocess_uses = [node for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                       and isinstance(node.value, ast.Name) and node.value.id == "subprocess"
                       and node.attr not in ("SubprocessError",)]
    assert [use.attr for use in subprocess_uses] == ["run"]
    programs = [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                and node.value.value.startswith("/")]
    assert sorted(program.value for program in programs) == ["/usr/bin/hdiutil",
                                                             "/usr/sbin/diskutil"]
    from personal_finance.db import volume_probes
    assert [name for name in dir(volume_probes) if name.endswith("_info_plist")] == [
        "diskutil_info_plist", "hdiutil_info_plist"]


ADDED = [
    ("cli.py", "import socket"),
    ("cli.py", "import urllib.request"),
    ("cli.py", "from http import client"),
    ("reports/totals.py", "from urllib.request import urlopen"),
    ("db/migrate.py", "import ssl as transport"),
    ("db/originals.py", "import subprocess"),
    ("db/volume_probes.py", "import socket"),
    ("db/backups.py", "import asyncio"),
    ("cli.py", "import webbrowser"),
    ("cli.py", "socket_module = __import__('socket')"),
    ("cli.py", "import importlib\nimportlib.import_module('ssl')"),
    ("cli.py", "from importlib import import_module"),
    ("cli.py", "import os\nos.system('true')"),
    ("cli.py", "from os import popen"),
    ("cli.py", "import os\nos.posix_spawn"),
    ("cli.py", "import os as operating_system\noperating_system.system('true')"),
    ("cli.py", "import importlib as loader\nloader.import_module('ssl')"),
]


@pytest.mark.parametrize("relative_path, added", ADDED,
                         ids=[f"{path}: {added}" for path, added in ADDED])
def test_an_added_import_fails(tmp_path, relative_path, added):
    copy = tmp_path / "personal_finance"
    shutil.copytree(PACKAGE_FOLDER, copy, ignore=shutil.ignore_patterns("__pycache__"))
    module = copy / relative_path
    module.write_text(module.read_text() + "\n" + added + "\n")
    found, _ = refused_uses_under(copy)
    assert len(found) >= 1
    assert all(entry.startswith(f"{relative_path}:") for entry in found)


def test_harmless_imports_pass_as_a_control(tmp_path):
    copy = tmp_path / "personal_finance"
    shutil.copytree(PACKAGE_FOLDER, copy, ignore=shutil.ignore_patterns("__pycache__"))
    module = copy / "cli.py"
    module.write_text(module.read_text()
                      + "\nimport os, json, sqlite3, hashlib\nfrom os import path\nos.fspath\n")
    assert refused_uses_under(copy) == ([], refused_uses_under(PACKAGE_FOLDER)[1])
