"""The domain layer may not depend on anything outside itself.

This is checked by parsing the source rather than by reading it, because the
rule is only worth stating if it is mechanically enforced. The legacy
application had no such boundary: its domain rules, its HTTP client, its
clipboard and its Tk window were the same 4,100-line module, which is the
reason a rule change could not be tested without a network and a display.

The test proves itself both ways. A passing check on real modules means little
on its own, since it would also pass if the checker were broken; the negative
proof drives the same function at a temporary module containing a forbidden
import and requires it to be caught.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

SRC = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "llm_youtube_comment_generation"
)
DOMAIN = SRC / "domain"
PORTS = SRC / "ports"
APPLICATION = SRC / "application"
INFRASTRUCTURE = SRC / "infrastructure"
INTERFACES = SRC / "interfaces"

PACKAGE = "llm_youtube_comment_generation"

# Which layers each layer is allowed to reach into. Adding a key here is how a
# phase declares its boundary; forgetting to is how a boundary quietly rots.
#
# The load-bearing entry is `application`: it may depend on ports but NOT on
# infrastructure. A handler that imported the YouTube adapter could not be
# tested without a network, which is the entire reason the ports layer exists.
ALLOWED_INWARD: dict[str, frozenset[str]] = {
    "domain": frozenset({"domain"}),
    "ports": frozenset({"domain", "ports"}),
    "application": frozenset({"domain", "ports", "application"}),
    "infrastructure": frozenset({"domain", "ports", "infrastructure"}),
    # interfaces is the composition root: it is the one layer allowed to see
    # both an abstraction and its implementation, because somebody has to
    # decide which adapter to construct.
    "interfaces": frozenset({"domain", "ports", "application",
                             "infrastructure", "interfaces"}),
}

# Only the adapters may touch a third-party package. That is what "the
# adapter absorbs the API" means in enforceable terms.
THIRD_PARTY_ALLOWED = frozenset({"infrastructure"})

# The GUI framework, allowed in exactly one place. The rule was always "the
# domain and application must not depend on a GUI framework", never "no
# module may import tkinter" — a GUI interface that could not import one
# would be a contradiction. Scoped to the directory rather than the layer so
# interfaces/cli is still refused it.
GUI_FRAMEWORK_MODULES = frozenset({"tkinter", "turtle"})
GUI_DIRECTORY = "interfaces/gui"


def is_gui_module(path: pathlib.Path) -> bool:
    try:
        return GUI_DIRECTORY in path.resolve().relative_to(SRC).as_posix()
    except ValueError:
        return False

# Named rather than inferred. These are the layers the domain must not reach
# into even though they live in the same distribution.
OUTWARD_LAYERS = frozenset({
    "application", "ports", "infrastructure", "interfaces", "cli", "gui",
})

# "Standard library" is not the same rule as "no outward dependency", and the
# difference is not academic: tkinter, socket and subprocess are all stdlib,
# and every one of them is a thing 01_ARCHITECTURE_OVERVIEW.md states the
# domain must not import. Checked before the stdlib allowance, longest match
# first, so urllib.parse stays legal while urllib.request does not.
FORBIDDEN_STDLIB: dict[str, str] = {
    "tkinter": "a GUI framework",
    "turtle": "a GUI framework",
    "socket": "a network client",
    "socketserver": "a network server",
    "ssl": "a network client",
    "http": "an HTTP client",
    "urllib.request": "an HTTP client",
    "urllib.error": "an HTTP client",
    "ftplib": "a network client",
    "smtplib": "a network client",
    "imaplib": "a network client",
    "poplib": "a network client",
    "xmlrpc": "a network client",
    "asyncio": "an I/O runtime",
    "subprocess": "an operating-system launch helper",
    "webbrowser": "an operating-system launch helper",
    "ctypes": "an operating-system launch helper",
    "multiprocessing": "an operating-system launch helper",
    "sqlite3": "a storage engine",
    "shelve": "a storage engine",
    "dbm": "a storage engine",
}


def forbidden_stdlib_reason(name: str) -> str:
    """Why this stdlib import is still not allowed here, or an empty string."""

    for denied, reason in FORBIDDEN_STDLIB.items():
        if name == denied or name.startswith(denied + "."):
            return reason
    return ""


def imported_roots(tree: ast.Module) -> list[tuple[str, int, int]]:
    """Every module name a file imports, as (name, line, relative level)."""

    found: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno, 0))
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.lineno, node.level))
    return found


def package_depth(path: pathlib.Path) -> int:
    """How many package directories sit between the package root and this file.

    `domain/errors.py` is 1; `interfaces/cli/main.py` is 2. This decides which
    relative-import level reaches the package root, and getting it wrong is
    how a checker either waves through a real violation or rejects a legal
    import — an earlier version hard-coded 2 and rejected every import in the
    CLI, which is nested one deeper than every other layer.
    """

    try:
        relative = path.resolve().relative_to(SRC)
    except ValueError:
        return 1                    # a temporary module in a negative proof
    return len(relative.parts) - 1


def forbidden_imports(
    path: pathlib.Path,
    layer: str = "domain",
) -> list[str]:
    """Return one message per import this module is not allowed to make.

    An empty list means the file obeys the dependency direction.
    """

    allowed = ALLOWED_INWARD.get(layer, frozenset({layer}))
    depth = package_depth(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    problems: list[str] = []

    for name, line, level in imported_roots(tree):
        # A relative import at or below the module's own depth stays inside
        # its layer. Exactly one level further reaches the package root, which
        # is how a layer names another one ("from ..domain.statuses import").
        # Beyond that it has climbed out of the distribution entirely.
        if level:
            if level <= depth:
                continue
            if level == depth + 1:
                reached = name.split(".")[0] if name else ""
                if reached and reached in allowed:
                    continue
                problems.append(
                    f"{path.name}:{line}: {layer} imports {name}, which is in "
                    f"the {reached or 'root'} layer"
                )
                continue
            problems.append(
                f"{path.name}:{line}: relative import climbs out of the "
                f"package (level {level} from depth {depth})"
            )
            continue

        root = name.split(".")[0]
        if not root:
            continue
        # The stdlib denylist is about keeping the pure layers pure. An
        # adapter that could not import socket or subprocess would not be an
        # adapter.
        reason = forbidden_stdlib_reason(name)
        if reason and root in GUI_FRAMEWORK_MODULES and is_gui_module(path):
            continue
        if reason and layer not in THIRD_PARTY_ALLOWED:
            problems.append(
                f"{path.name}:{line}: {layer} imports {name}, which is {reason}"
            )
            continue
        if root in sys.stdlib_module_names:
            continue
        if root == PACKAGE:
            parts = name.split(".")
            target = parts[1] if len(parts) > 1 else ""
            if target and target not in allowed:
                problems.append(
                    f"{path.name}:{line}: {layer} imports {name}, which is in "
                    f"the {target} layer"
                )
            continue
        if root in OUTWARD_LAYERS and root not in allowed:
            problems.append(
                f"{path.name}:{line}: {layer} imports the {root} layer ({name})"
            )
            continue
        if layer in THIRD_PARTY_ALLOWED:
            continue
        problems.append(
            f"{path.name}:{line}: {layer} imports third-party module {name!r}"
        )

    return problems


def domain_modules() -> list[pathlib.Path]:
    return sorted(DOMAIN.rglob("*.py"))


def port_modules() -> list[pathlib.Path]:
    return sorted(PORTS.rglob("*.py"))


def test_the_layers_actually_have_modules_to_check():
    """A checker that scans nothing passes trivially."""

    assert domain_modules(), f"no domain modules found under {DOMAIN}"
    assert port_modules(), f"no port modules found under {PORTS}"


@pytest.mark.parametrize(
    "module", domain_modules(), ids=lambda path: path.name
)
def test_a_domain_module_imports_only_the_standard_library(module):
    problems = forbidden_imports(module, "domain")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    "module", port_modules(), ids=lambda path: path.name
)
def test_a_port_declares_a_need_without_importing_an_implementation(module):
    """A port may speak the domain's vocabulary and nothing else.

    The moment a port needs `requests` in order to be *defined*, the boundary
    has already failed: the interface would be describing an HTTP client
    rather than what the application needs.
    """

    problems = forbidden_imports(module, "ports")
    assert not problems, "\n".join(problems)


def application_modules() -> list[pathlib.Path]:
    return sorted(APPLICATION.rglob("*.py"))


def infrastructure_modules() -> list[pathlib.Path]:
    return sorted(INFRASTRUCTURE.rglob("*.py"))


def interface_modules() -> list[pathlib.Path]:
    return sorted(INTERFACES.rglob("*.py"))


@pytest.mark.parametrize(
    "module", application_modules(), ids=lambda path: path.name
)
def test_an_application_module_never_imports_an_adapter(module):
    """The rule that keeps every use case testable.

    A handler that imported the YouTube adapter could not be run without a
    network, and the whole ports layer would have been for nothing.
    """

    problems = forbidden_imports(module, "application")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    "module", infrastructure_modules(), ids=lambda path: path.name
)
def test_an_adapter_may_use_the_outside_world_but_not_an_interface(module):
    problems = forbidden_imports(module, "infrastructure")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize(
    "module", interface_modules(), ids=lambda path: path.name
)
def test_an_interface_module_obeys_the_composition_root_rule(module):
    problems = forbidden_imports(module, "interfaces")
    assert not problems, "\n".join(problems)


def test_the_application_layer_is_the_one_that_must_not_see_an_adapter(tmp_path):
    """Negative proof for the boundary that matters most."""

    module = tmp_path / "pretend_handler.py"
    module.write_text(
        f"from {PACKAGE}.infrastructure.youtube_api import YouTubeAdapter\n",
        encoding="utf-8",
    )

    problems = forbidden_imports(module, "application")
    assert problems and "infrastructure layer" in problems[0]

    # The same import is legal from the composition root.
    assert forbidden_imports(module, "interfaces") == []


def test_only_an_adapter_may_import_a_third_party_package(tmp_path):
    """"The adapter absorbs the API", stated so it can fail."""

    module = tmp_path / "pretend.py"
    module.write_text("import requests\n", encoding="utf-8")

    assert forbidden_imports(module, "infrastructure") == []
    for layer in ("domain", "ports", "application", "interfaces"):
        problems = forbidden_imports(module, layer)
        assert problems, f"{layer} was allowed to import requests"


def test_only_the_gui_directory_may_import_a_gui_framework():
    """The allowance is scoped to a directory, not handed to a whole layer.

    interfaces/cli sits in the same layer as interfaces/gui and must still be
    refused tkinter: a CLI that imported one would fail on a headless
    machine, which is where a CLI most needs to work.
    """

    gui_module = SRC / "interfaces" / "gui" / "main_window.py"
    cli_module = SRC / "interfaces" / "cli" / "main.py"

    assert is_gui_module(gui_module)
    assert not is_gui_module(cli_module)

    for module in interface_modules():
        text = module.read_text(encoding="utf-8")
        if "import tkinter" in text:
            assert is_gui_module(module), (
                f"{module.name} imports tkinter outside interfaces/gui"
            )


def test_the_cli_would_be_refused_a_gui_framework(tmp_path):
    """Negative proof for the scoping, using a module outside the GUI tree."""

    module = tmp_path / "pretend_cli.py"
    module.write_text("import tkinter\n", encoding="utf-8")

    problems = forbidden_imports(module, "interfaces")

    assert problems and "GUI framework" in problems[0]


def test_the_real_adapters_do_import_the_outside_world():
    """Otherwise the previous test proves nothing about this codebase.

    If no adapter actually reached for a third-party package, the permission
    would be untested and the boundary would be theoretical.
    """

    text = "".join(m.read_text(encoding="utf-8") for m in infrastructure_modules())
    assert "import requests" in text


def test_a_port_may_reach_the_domain_but_not_the_other_way():
    """The dependency arrow, asserted in both directions.

    Ports import domain types deliberately — that is what keeps the interface
    in the application's vocabulary. The domain importing a port would invert
    the arrow and make the pure core depend on an I/O description.
    """

    ports_using_domain = [
        module.name for module in port_modules()
        if "domain" in module.read_text(encoding="utf-8")
    ]
    assert ports_using_domain, "no port references a domain type at all"

    for module in domain_modules():
        text = module.read_text(encoding="utf-8")
        assert "import ports" not in text
        assert "from ..ports" not in text
        assert f"from {PACKAGE}.ports" not in text


# --------------------------------------------------------------------------
# Negative proof
#
# A temporary module, never a tracked one. Editing a real domain file to prove
# the guard bites and then restoring it risks leaving the forbidden import
# behind if the test fails partway, which would be a defect introduced by the
# test that exists to prevent defects.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line, expected",
    [
        ("import requests", "third-party"),
        ("from requests import Session", "third-party"),
        ("from youtube_transcript_api import YouTubeTranscriptApi", "third-party"),
        # Stdlib, and still forbidden. These are the cases a naive
        # "is it stdlib?" check waves through, and all three are things the
        # architecture explicitly bars the domain from touching.
        ("import tkinter", "a GUI framework"),
        ("import socket", "a network client"),
        ("import urllib.request", "an HTTP client"),
        ("import subprocess", "an operating-system launch helper"),
        ("import sqlite3", "a storage engine"),
        (f"from {PACKAGE}.infrastructure import youtube_api", "infrastructure"),
        (f"import {PACKAGE}.ports.youtube", "ports"),
        ("from ...interfaces import cli", "climbs out"),
    ],
)
def test_the_guard_fails_on_a_forbidden_import(tmp_path, line, expected):
    """The checker must catch each forbidden shape, not merely pass on clean code."""

    module = tmp_path / "pretend_domain_module.py"
    module.write_text(
        f'"""A temporary module that breaks the rule on purpose."""\n'
        f"import re\n"
        f"{line}\n",
        encoding="utf-8",
    )

    problems = forbidden_imports(module)
    assert problems, f"the guard did not object to {line!r}"
    assert any(expected in problem for problem in problems), (
        f"expected a {expected!r} objection to {line!r}, got: {problems}"
    )


@pytest.mark.parametrize("line, expected", [
    ("import requests", "third-party"),
    ("import tkinter", "a GUI framework"),
    (f"from {PACKAGE}.infrastructure import youtube_api", "infrastructure"),
    (f"from {PACKAGE}.interfaces.cli import main", "interfaces"),
])
def test_the_guard_fails_on_a_port_reaching_outward(tmp_path, line, expected):
    """The ports layer gets its own negative proof, not a borrowed one.

    A rule that was only ever demonstrated against domain files would not
    prove the ports layer is checked at all.
    """

    module = tmp_path / "pretend_port.py"
    module.write_text(
        '"""A temporary port that breaks the rule on purpose."""\n'
        "from typing import Protocol\n"
        f"{line}\n",
        encoding="utf-8",
    )

    problems = forbidden_imports(module, "ports")
    assert problems, f"the ports guard did not object to {line!r}"
    assert any(expected in problem for problem in problems), (
        f"expected a {expected!r} objection, got: {problems}"
    )


def test_the_ports_layer_may_legitimately_import_the_domain(tmp_path):
    """The permissive half. Without it the rule would just forbid everything."""

    module = tmp_path / "pretend_port.py"
    module.write_text(
        "from typing import Protocol, runtime_checkable\n"
        "from ..domain.statuses import RetrievalOutcome\n"
        f"from {PACKAGE}.domain.errors import ConfigurationError\n"
        "from .youtube import CommentPage\n",
        encoding="utf-8",
    )

    assert forbidden_imports(module, "ports") == []


def test_the_domain_may_not_import_a_port(tmp_path):
    """The same import that is legal in ports is illegal in the domain."""

    module = tmp_path / "pretend_domain.py"
    module.write_text(
        f"from {PACKAGE}.ports.youtube import YouTubePort\n",
        encoding="utf-8",
    )

    problems = forbidden_imports(module, "domain")
    assert problems and "ports layer" in problems[0]


def test_the_guard_allows_what_the_domain_legitimately_needs(tmp_path):
    """The negative proof is worthless if the checker rejects everything."""

    module = tmp_path / "pretend_domain_module.py"
    module.write_text(
        "import re\n"
        "import json\n"
        "from datetime import datetime, timezone\n"
        # urllib.parse is pure string work and is how video IDs are read out
        # of a URL. Only the network half of urllib is barred.
        "from urllib.parse import urlparse, parse_qs\n"
        "from .errors import ConfigurationError\n"
        "from . import video\n"
        f"from {PACKAGE}.domain.comments import merge_comments\n",
        encoding="utf-8",
    )

    assert forbidden_imports(module) == []
