"""Each harness guard, proven to bite.

A guard that has never been observed to fail anything is an assumption wearing
a fixture's clothes. The legacy suite's desktop guard was correct and its
history guard was correct, but neither was ever demonstrated, so nothing would
have noticed if a refactor had quietly disabled one.

Every test here asserts a *refusal*. None of them performs the forbidden act.
"""

from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import webbrowser

import pytest

from harness_support import (
    REAL_CREATE_CONNECTION,
    REAL_SOCKET,
    HarnessViolation,
    compare_protected_state,
    protected_state_paths,
    snapshot_protected_state,
)


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------


def test_opening_a_socket_is_refused():
    with pytest.raises(HarnessViolation, match="network connection"):
        socket.socket()


def test_connecting_to_a_host_is_refused():
    with pytest.raises(HarnessViolation, match="network connection"):
        socket.create_connection(("example.invalid", 443))


@pytest.mark.allows_network
def test_a_marked_test_gets_the_real_socket_module_back():
    """The escape hatch has to exist, be explicit, and be observable.

    This asserts the guard stepped aside by identity against the objects
    captured before any patching. It never opens a connection: proving the
    marker works does not require using it.
    """

    assert socket.socket is REAL_SOCKET
    assert socket.create_connection is REAL_CREATE_CONNECTION


def test_an_unmarked_test_does_not_get_the_real_socket():
    """The other half of the pair. Without this the marker could be a no-op."""

    assert socket.socket is not REAL_SOCKET
    assert socket.create_connection is not REAL_CREATE_CONNECTION


# --------------------------------------------------------------------------
# The desktop
# --------------------------------------------------------------------------


def test_launching_a_subprocess_is_refused():
    with pytest.raises(HarnessViolation, match="desktop application"):
        subprocess.Popen(["notepad.exe"])


def test_running_a_command_is_refused():
    with pytest.raises(HarnessViolation, match="desktop application"):
        subprocess.run(["notepad.exe"])


def test_opening_a_browser_is_refused():
    with pytest.raises(HarnessViolation, match="desktop application"):
        webbrowser.open("https://example.invalid")


@pytest.mark.skipif(
    not hasattr(os, "startfile"), reason="os.startfile exists only on Windows"
)
def test_opening_a_file_with_the_shell_is_refused(tmp_path):
    """The exact call the legacy application made from five window methods."""

    target = tmp_path / "output.md"
    target.write_text("nothing", encoding="utf-8")
    with pytest.raises(HarnessViolation, match="desktop application"):
        os.startfile(target)


# --------------------------------------------------------------------------
# Credentials and user settings
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["YOUTUBE_API_KEY", "YOUTUBE_API_KEY_FILE", "GOOGLE_API_KEY"]
)
def test_the_operators_credentials_are_not_visible(name):
    assert os.environ.get(name) is None


def test_the_home_directory_is_disposable(no_test_sees_real_credentials):
    """A test must not be able to read or write the operator's real profile.

    The fixture returns the redirected home, so this asserts against the same
    object the guard installed rather than re-deriving it.
    """

    redirected = no_test_sees_real_credentials
    assert pathlib.Path.home() == redirected
    # The real profile holds a .claude directory; the redirected one is empty.
    assert list(redirected.iterdir()) == []
    assert os.environ["USERPROFILE"] == str(redirected)


def test_the_fake_home_is_not_inside_the_tests_own_tmp_path(tmp_path):
    """tmp_path must stay a clean slate.

    An autouse fixture that drops a directory into every tmp_path makes
    "this directory is empty" false everywhere, and the tests that break are
    the ones with nothing to do with credentials.
    """

    assert list(tmp_path.iterdir()) == []
    assert tmp_path not in pathlib.Path.home().parents


# --------------------------------------------------------------------------
# Protected production state
#
# The negative proof drives the comparison against a temporary file. Corrupting
# the real posted_history.json to prove the guard works would be the exact
# accident the guard exists to prevent, and that file is not recoverable.
# --------------------------------------------------------------------------


def test_the_state_guard_reports_a_modified_file(tmp_path):
    protected = tmp_path / "posted_history.json"
    protected.write_text('[{"draft": "original"}]', encoding="utf-8")

    before = {protected: protected.read_bytes()}
    protected.write_text('[{"draft": "clobbered"}]', encoding="utf-8")
    after = {protected: protected.read_bytes()}

    problems = compare_protected_state(before, after)
    assert len(problems) == 1
    assert "wrote to protected state" in problems[0]


def test_the_state_guard_reports_a_deleted_file(tmp_path):
    protected = tmp_path / "posted_history.json"
    protected.write_text("[]", encoding="utf-8")

    before = {protected: protected.read_bytes()}
    protected.unlink()

    problems = compare_protected_state(before, {protected: None})
    assert len(problems) == 1
    assert "deleted protected state" in problems[0]


def test_the_state_guard_reports_a_created_file(tmp_path):
    protected = tmp_path / "posted_history.json"

    protected.write_text("[]", encoding="utf-8")
    problems = compare_protected_state(
        {protected: None}, {protected: protected.read_bytes()}
    )
    assert len(problems) == 1
    assert "created protected state" in problems[0]


def test_the_state_guard_stays_quiet_when_nothing_changed(tmp_path):
    """A guard that fires on an unchanged file would be worse than none."""

    protected = tmp_path / "posted_history.json"
    protected.write_text("[]", encoding="utf-8")
    snapshot = {protected: protected.read_bytes()}

    assert compare_protected_state(snapshot, dict(snapshot)) == []


def test_the_live_history_is_among_the_guarded_paths():
    """The live measurement data sits in the old project, so guard it there.

    This is the file the whole engagement redesign is measured against and it
    cannot be regenerated. If the path ever stops resolving, this fails loudly
    rather than the suite quietly guarding nothing.
    """

    guarded = protected_state_paths()
    assert [path.name for path in guarded].count("posted_history.json") == 2
    assert any("Comment_Generation_Claude02" in str(path) for path in guarded)
    assert snapshot_protected_state(), "the guard is watching no paths at all"
