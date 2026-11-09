"""The pf launcher, run for real against a copy of the code (D-038).

Each copy gets its own environment holding only the declared runtime dependencies, copied from
the project's .venv with no network, so the application is shown to need nothing more, and the
project's .venv is neither used nor changed.
"""

import importlib
import os
import shutil
import stat
import subprocess
import sys
import tomllib
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "tests" / "fixtures" / "synthetic" / "card_jan_no_metadata.csv"


def checkout(parent: Path, *, environment: bool = True) -> Path:
    root = parent / "checkout"
    (root / "bin").mkdir(parents=True)
    shutil.copy2(ROOT / "bin" / "pf", root / "bin" / "pf")
    shutil.copytree(ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__"))
    if environment:
        venv.create(root / ".venv", with_pip=False)
        add_runtime_dependencies(root / ".venv")
    return root


def add_runtime_dependencies(environment: Path) -> None:
    """Copy each package pyproject.toml declares, at its pinned version, from the project's .venv."""
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    installed = ROOT / ".venv" / "lib" / version / "site-packages"
    target = environment / "lib" / version / "site-packages"
    for requirement in declared:
        name, pinned = requirement.split("==")
        for entry in (name, f"{name}-{pinned}.dist-info"):
            shutil.copytree(installed / entry, target / entry,
                            ignore=shutil.ignore_patterns("__pycache__"))


def pf(launcher, *arguments, cwd):
    clean = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [str(launcher), *map(str, arguments)],
        cwd=cwd, env=clean, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture(scope="module")
def spaced(tmp_path_factory):
    return checkout(tmp_path_factory.mktemp("repo") / "a path with spaces")


def test_the_launcher_is_executable():
    assert (ROOT / "bin" / "pf").stat().st_mode & stat.S_IXUSR


def test_it_shows_help_under_the_name_pf(spaced, tmp_path):
    result = pf(spaced / "bin" / "pf", "--help", cwd=tmp_path)
    assert result.returncode == 0
    assert result.stdout.startswith("usage: pf ")


def test_a_full_import_works_from_another_directory_with_spaces(spaced, tmp_path):
    caller = tmp_path / "another place"
    caller.mkdir()
    launcher = spaced / "bin" / "pf"
    db = caller / "my ledger.db"

    assert pf(launcher, "init", "--db", db, cwd=caller).returncode == 0
    assert pf(launcher, "account", "add", "--db", db, "--name", "Synthetic Card", "--type",
              "credit_card", cwd=caller).returncode == 0
    result = pf(launcher, "import", "--db", db, "--account", "Synthetic Card", "--layout",
                "synthetic_card_v1", CARD, cwd=caller)

    assert result.returncode == 0
    assert "Files attempted: 1 (1 imported, 0 already imported, 0 failed)" in result.stdout
    assert pf(launcher, "totals", "--db", db, cwd=caller).returncode == 0


def test_a_relative_database_path_stays_relative_to_the_caller(spaced, tmp_path):
    assert pf(spaced / "bin" / "pf", "init", "--db", "here.db", cwd=tmp_path).returncode == 0
    assert (tmp_path / "here.db").is_file()


def test_the_exit_code_passes_through(spaced, tmp_path):
    result = pf(spaced / "bin" / "pf", "totals", "--db", tmp_path / "missing.db", cwd=tmp_path)
    assert result.returncode == 2
    assert "database not found" in result.stderr


def test_a_symlink_to_the_launcher_finds_its_checkout(spaced, tmp_path):
    link = tmp_path / "linked pf"
    link.symlink_to(spaced / "bin" / "pf")
    assert pf(link, "--help", cwd=tmp_path).returncode == 0


def test_the_callers_directory_cannot_replace_the_application(spaced, tmp_path):
    decoy = tmp_path / "personal_finance"
    decoy.mkdir()
    (decoy / "__init__.py").write_text("")
    (decoy / "__main__.py").write_text("raise SystemExit('decoy ran')")

    result = pf(spaced / "bin" / "pf", "--help", cwd=tmp_path)

    assert result.returncode == 0
    assert "decoy" not in result.stderr


def test_a_missing_environment_is_explained(tmp_path):
    root = checkout(tmp_path / "with spaces here", environment=False)
    result = pf(root / "bin" / "pf", "--help", cwd=tmp_path)
    assert result.returncode == 2
    assert "no Python environment" in result.stderr
    assert "README.md" in result.stderr


def test_the_module_route_still_works(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "personal_finance", "--help"],
        cwd=tmp_path, env={"PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0


def test_the_declared_script_resolves_to_a_callable():
    """A static check. The installed script itself needs network access to check (D-038)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    module, function = project["scripts"]["pf"].split(":")
    assert callable(getattr(importlib.import_module(module), function))
