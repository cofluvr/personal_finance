"""No network, and it is shown (W1, D-058 point 9).

Every module under src/ is parsed, not run. Point 9's modules are refused, with others that reach the
network or run another program, and `os`'s calls that run a program. Dynamic imports are refused
whatever they name, since a name built at run time cannot be checked. The allowances:

- `subprocess` in db/volume_probes.py, for `diskutil` and `hdiutil`;
- `http.server` in ui/server.py, for the local UI's two classes, bound to 127.0.0.1 alone (D-062
  point 1);
- `ssl` and `http.server` in sync/server.py, for TLS 1.3 on one private address, and `subprocess`
  in sync/identity.py, for `/usr/bin/openssl` alone (D-076 point 10, M20).

An allowance names a module, and `http.server` allows neither `http` itself nor `http.client`.

pypdf, a runtime dependency, is parsed the same way (D-060 point 1). Its one allowance is
`subprocess` in its filters.py, used only by its JBIG2 decoder to run jbig2dec, which
ingest/pdf_reader.py never lets it run. segno, the other (D-076 point 3), is parsed too: its seven
uses are each allowed only in the one function or import line named in SEGNO_ALLOWED, on paths
sync/pairing.py never takes, since it calls make_qr and reads the matrix alone.
"""

import ast
from pathlib import Path

import pypdf
import pytest
import segno

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
ALLOWED = {("db/volume_probes.py", "subprocess"), ("ui/server.py", "http.server"),
           ("sync/server.py", "ssl"), ("sync/server.py", "http.server"),
           ("sync/identity.py", "subprocess")}
SYNC_ALLOWANCES = {("sync/server.py", "ssl"), ("sync/server.py", "http.server"),
                   ("sync/identity.py", "subprocess")}
PYPDF_FOLDER = Path(pypdf.__file__).parent
PYPDF_ALLOWED = {("filters.py", "subprocess")}
SEGNO_FOLDER = Path(segno.__file__).parent
# Each segno use W1 finds: the module, the function it is in (None for a top-level import), and
# what it imports. Nothing else in segno may reach the network or run a program.
SEGNO_ALLOWED = {
    ("__init__.py", "QRCode.show", "webbrowser"),
    ("__init__.py", "QRCode.show", "urllib.parse"),
    ("__init__.py", "QRCode.show", "urllib.request"),
    ("__init__.py", "QRCode.__getattr__", "from importlib"),
    ("helpers.py", None, "urllib.parse"),
    ("writers.py", None, "urllib.parse"),
    ("writers.py", "write_terminal_win", "ctypes"),
}


def refused_uses(source: str, relative_path: str, allowed=ALLOWED) -> list[str]:
    """Each refused import, dynamic import or program-running `os` call in one module's source."""
    found = []

    def refuse_module(module_name: str, line: int) -> None:
        top_level = module_name.split(".")[0]
        if (top_level in REFUSED_MODULES and (relative_path, top_level) not in allowed
                and (relative_path, module_name) not in allowed):
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


def refused_uses_under(package_folder: Path, allowed=ALLOWED) -> tuple[list[str], list[str]]:
    found, modules = [], []
    for path in sorted(package_folder.rglob("*.py")):
        relative_path = path.relative_to(package_folder).as_posix()
        modules.append(relative_path)
        found += refused_uses(path.read_text(encoding="utf-8"), relative_path, allowed)
    return found, modules


def test_no_module_reaches_the_network_or_runs_a_program():
    found, modules = refused_uses_under(PACKAGE_FOLDER)
    assert found == []
    assert {"cli.py", "db/volume_probes.py", "db/backups.py", "ingest/pipeline.py",
            "reports/storage.py", "ui/server.py"} <= set(modules)


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
    ("ui/server.py", "import socket"),
    ("ui/server.py", "import socketserver"),
    ("ui/server.py", "import http.client"),
    ("ui/server.py", "from http import client"),
    ("ui/server.py", "import urllib.parse"),
    ("ui/server.py", "import subprocess"),
    ("reports/report_text.py", "from http.server import HTTPServer"),
    ("cli.py", "import http.server"),
    ("sync/server.py", "import socket"),
    ("sync/server.py", "import subprocess"),
    ("sync/server.py", "import http.client"),
    ("sync/server.py", "import urllib.request"),
    ("sync/identity.py", "import ssl"),
    ("sync/identity.py", "import socket"),
    ("sync/pairing.py", "import ssl"),
    ("sync/pairing.py", "import subprocess"),
    ("sync/devices.py", "import http.server"),
    ("sync/devices.py", "import subprocess"),
]


@pytest.mark.parametrize("relative_path, added", ADDED,
                         ids=[f"{path}: {added}" for path, added in ADDED])
def test_an_added_import_fails(relative_path, added):
    """Only the edited module is scanned: the others are unchanged, and the first test shows
    them clean, so a scan of the whole package would find the same."""
    edited_source = (PACKAGE_FOLDER / relative_path).read_text(encoding="utf-8")
    found = refused_uses(edited_source + "\n" + added + "\n", relative_path)
    assert len(found) >= 1
    assert all(entry.startswith(f"{relative_path}:") for entry in found)


def test_without_its_allowance_the_server_alone_is_refused_as_the_control():
    found, _ = refused_uses_under(PACKAGE_FOLDER, allowed=ALLOWED - {("ui/server.py",
                                                                      "http.server")})
    assert found and all(entry.startswith("ui/server.py:") for entry in found)


@pytest.mark.parametrize("allowance", sorted(SYNC_ALLOWANCES))
def test_without_each_sync_allowance_its_module_alone_is_refused(allowance):
    """The control for each of M20's allowances: each is used, and allows only its module."""
    found, _ = refused_uses_under(PACKAGE_FOLDER, allowed=ALLOWED - {allowance})
    relative_path, module_name = allowance
    assert found and all(entry.startswith(f"{relative_path}:") and module_name in entry
                         for entry in found)


def test_the_identity_runs_one_fixed_program_with_fixed_arguments():
    """subprocess in sync/identity.py is one run of /usr/bin/openssl, its argument list built from
    constants and the two paths alone, with no shell (D-076 point 2)."""
    from personal_finance.sync import identity

    tree = ast.parse((PACKAGE_FOLDER / "sync" / "identity.py").read_text(encoding="utf-8"))
    uses = sorted(node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                  and isinstance(node.value, ast.Name) and node.value.id == "subprocess")
    assert uses == ["DEVNULL", "DEVNULL", "DEVNULL", "SubprocessError", "run"]
    programs = [node.value.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                and node.value.value.startswith("/usr/")]
    assert programs == ["/usr/bin/openssl"]
    (run_call,) = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and ast.unparse(node.func) == "subprocess.run"]
    assert sorted(keyword.arg for keyword in run_call.keywords) == [
        "check", "env", "stderr", "stdin", "stdout", "timeout"]
    assert identity.openssl_arguments(Path("/k"), Path("/c")) == [
        "/usr/bin/openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
        "ec_paramgen_curve:prime256v1", "-pkeyopt", "ec_param_enc:named_curve", "-nodes", "-days",
        "3650", "-subj", "/CN=commoncents-sync", "-keyout", "/k", "-out", "/c"]


def network_imports(relative_path: str) -> list:
    tree = ast.parse((PACKAGE_FOLDER / relative_path).read_text(encoding="utf-8"))
    network = {"http", "socket", "socketserver", "ssl"}
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [(alias.name, None) for alias in node.names
                        if alias.name.split(".")[0] in network]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in network:
            imports.append((node.module, sorted(alias.name for alias in node.names)))
    return sorted(imports, key=repr)


def test_the_sync_server_imports_ssl_and_two_classes_from_http_and_no_socket():
    """Not socket: every connection it makes is the HTTPServer's own, on the address checked."""
    assert network_imports("sync/server.py") == [
        ("http.server", ["BaseHTTPRequestHandler", "HTTPServer"]), ("ssl", None)]


def test_the_sync_server_names_no_address_and_checks_the_one_it_is_given():
    """The address comes only from its caller, checked as private before the socket is made:
    the check is the first statement of __init__, and super().__init__ the last."""
    source = (PACKAGE_FOLDER / "sync" / "server.py").read_text(encoding="utf-8")
    assert "0.0.0.0" not in source and "'::'" not in source and "localhost" not in source
    assert "127.0.0.1" not in source and "allow_reuse_address = False" in source
    tree = ast.parse(source)
    server = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.ClassDef) and node.name == "SyncServer")
    init = next(node for node in server.body
                if isinstance(node, ast.FunctionDef) and node.name == "__init__")
    assert ast.unparse(init.body[0]) == "self.checked_address(address)"
    assert ast.unparse(init.body[-1]).startswith("super().__init__((address, port)")
    check = next(node for node in server.body
                 if isinstance(node, ast.FunctionDef) and node.name == "checked_address")
    assert ast.unparse(check.body[0]) == "devices.checked_private_address(address)"
    assert not any(isinstance(node, ast.Attribute) and node.attr == "server_address"
                   and isinstance(node.ctx, ast.Store) for node in ast.walk(tree))


def test_the_tls_settings_are_pinned():
    from personal_finance.sync import server

    source = ast.unparse(next(node for node in ast.walk(ast.parse(
        (PACKAGE_FOLDER / "sync" / "server.py").read_text())) if isinstance(node, ast.FunctionDef)
        and node.name == "tls_context"))
    for setting in ("ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)",
                    "context.minimum_version = ssl.TLSVersion.TLSv1_3",
                    "context.options |= ssl.OP_NO_COMPRESSION | ssl.OP_NO_TICKET",
                    "context.num_tickets = 0", "context.verify_mode = ssl.CERT_NONE"):
        assert setting in source
    assert server.SUPPORTED_MAJORS == (1,)


def test_the_server_imports_two_classes_from_http_and_nothing_else_of_the_network():
    """D-062 point 1: not SimpleHTTPRequestHandler, which serves the working directory, not
    CGIHTTPRequestHandler, which runs programs, and not a threading server."""
    tree = ast.parse((PACKAGE_FOLDER / "ui" / "server.py").read_text(encoding="utf-8"))
    network = {"http", "socket", "socketserver"}
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [(alias.name, None) for alias in node.names
                        if alias.name.split(".")[0] in network]
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in network:
            imports.append((node.module, sorted(alias.name for alias in node.names)))
    assert imports == [("http.server", ["BaseHTTPRequestHandler", "HTTPServer"])]


def test_the_server_binds_the_loopback_constant_and_nothing_else():
    """The one address the server is given is the tuple (LOOPBACK_ADDRESS, 0), and that name is
    the constant 127.0.0.1. No other address appears, and no code sets one."""
    source = (PACKAGE_FOLDER / "ui" / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "LOOPBACK_ADDRESS"
                           for target in node.targets)]
    assert [ast.unparse(node.value) for node in assignments] == ["'127.0.0.1'"]
    addresses = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Tuple)
                 and any(isinstance(element, ast.Name) and element.id == "LOOPBACK_ADDRESS"
                         for element in node.elts)]
    assert addresses == ["(LOOPBACK_ADDRESS, 0)"]
    assert not any(isinstance(node, ast.Attribute) and node.attr == "server_address"
                   and isinstance(node.ctx, ast.Store) for node in ast.walk(tree))
    assert "0.0.0.0" not in source and "'::'" not in source and "localhost" not in source
    assert "allow_reuse_address = False" in source


def test_harmless_imports_pass_as_a_control():
    edited_source = (PACKAGE_FOLDER / "cli.py").read_text(encoding="utf-8")
    harmless = "\nimport os, json, sqlite3, hashlib\nfrom os import path\nos.fspath\n"
    assert refused_uses(edited_source + harmless, "cli.py") == []


def test_pypdf_reaches_no_network_and_runs_no_program_outside_its_allowance():
    found, modules = refused_uses_under(PYPDF_FOLDER, PYPDF_ALLOWED)
    assert found == []
    assert {"filters.py", "_reader.py", "_page.py"} <= set(modules)


def test_without_its_allowance_pypdf_is_refused_as_the_control():
    found, _ = refused_uses_under(PYPDF_FOLDER, allowed=set())
    assert [entry.split(":")[0] for entry in found] == ["filters.py"]


def test_pypdfs_allowance_is_only_its_jbig2_decoder_running_a_program():
    """Every use of subprocess in filters.py is a `run` inside JBIG2Decode, so a release that
    uses it anywhere else fails here and is reviewed before it is adopted."""
    tree = ast.parse((PYPDF_FOLDER / "filters.py").read_text(encoding="utf-8"))
    decoder = next(node for node in ast.walk(tree)
                   if isinstance(node, ast.ClassDef) and node.name == "JBIG2Decode")

    def subprocess_uses(root):
        return [node for node in ast.walk(root) if isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name) and node.value.id == "subprocess"]

    assert [use.attr for use in subprocess_uses(decoder)] == ["run", "run"]
    assert len(subprocess_uses(tree)) == 2


def segno_uses() -> set:
    """Each refused use in segno, as (module, enclosing function, what it imports)."""
    found_uses = set()
    for path in sorted(SEGNO_FOLDER.rglob("*.py")):
        relative_path = path.relative_to(SEGNO_FOLDER).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        spans = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        spans.append((item.lineno, item.end_lineno, f"{node.name}.{item.name}"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                spans.append((node.lineno, node.end_lineno, node.name))
        for entry in refused_uses(source, relative_path, allowed=set()):
            line = int(entry.split(":")[1].split(" ")[0])
            imported = entry.split(" imports ", 1)[1]
            enclosing = next((name for first, last, name in spans if first <= line <= last),
                             None)
            found_uses.add((relative_path, enclosing, imported))
    return found_uses


def test_segno_reaches_the_network_or_runs_a_program_only_where_allowed():
    """A release adding any use elsewhere, or moving one, fails here and is reviewed first."""
    assert segno.__version__ == "1.6.6"
    assert segno_uses() == SEGNO_ALLOWED


def test_without_its_allowances_segno_is_refused_as_the_control():
    found, modules = refused_uses_under(SEGNO_FOLDER, allowed=set())
    assert len(found) == len(SEGNO_ALLOWED)
    assert {"__init__.py", "encoder.py", "writers.py"} <= set(modules)


def test_only_pairing_imports_segno_and_uses_make_qr_alone():
    """Never show, save, a writer or a to_* converter: only make_qr, then its matrix."""
    importers = []
    for path in sorted(PACKAGE_FOLDER.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(name.split(".")[0] == "segno" for name in names):
                importers.append(path.relative_to(PACKAGE_FOLDER).as_posix())
    assert importers == ["sync/pairing.py"]
    tree = ast.parse((PACKAGE_FOLDER / "sync" / "pairing.py").read_text(encoding="utf-8"))
    uses = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "segno"]
    assert uses == ["make_qr"]
    called = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.Attribute)
              and isinstance(node.value, ast.Call) and ast.unparse(node.value.func) ==
              "segno.make_qr"]
    assert called == ["segno.make_qr(payload, error='m').matrix"]


def test_only_the_pdf_reader_imports_pypdf():
    importers = []
    for path in sorted(PACKAGE_FOLDER.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(name.split(".")[0] == "pypdf" for name in names):
                importers.append(path.relative_to(PACKAGE_FOLDER).as_posix())
    assert importers == ["ingest/pdf_reader.py"]
