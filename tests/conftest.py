"""Harness invariants.

Every guard here is autouse and denies by default. They exist because the
legacy suite learned each lesson the expensive way: it opened the operator's
editor once per window test on a real desktop, and it wrote to the production
draft history, which is the one file in the project that cannot be
regenerated.

A guard that is never proven to bite is decoration. Each one is paired with a
deliberate negative proof in tests/harness/test_guards.py.
"""

from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import webbrowser

import pytest

from harness_support import (  # noqa: F401 - re-exported for the proofs
    HarnessViolation,
    compare_protected_state,
    snapshot_protected_state,
)


@pytest.fixture(autouse=True)
def production_state_is_off_limits():
    """No test may write to the real draft history.

    Pointing the code under test at tmp_path is the fix; this is the assertion
    that keeps it fixed. The legacy leak was invisible for as long as it
    existed because nothing ever compared the file against itself, and the
    damage lands in the scoreboard, which is the one tool that decides whether
    the engagement changes were worth making.
    """

    before = snapshot_protected_state()
    yield
    problems = compare_protected_state(before, snapshot_protected_state())
    assert not problems, "; ".join(problems) + ". Use tmp_path instead."


@pytest.fixture(autouse=True)
def no_test_reaches_the_network(request, monkeypatch):
    """No test may open a socket.

    The legacy harness had no network guard at all, so a mistake in an adapter
    test would spend real API quota against the operator's key and its results
    would depend on YouTube being up. Tests that need network behaviour use a
    fake port, which is the entire reason the ports layer exists.
    """

    if "allows_network" in request.keywords:
        return

    def refuse(*args, **kwargs):
        raise HarnessViolation(
            "a test tried to open a network connection. Use a fake port "
            "instead, or mark the test with @pytest.mark.allows_network if it "
            "genuinely must reach the network."
        )

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def no_test_reaches_the_desktop(request, monkeypatch):
    """No test may launch an editor, a file manager, or a browser.

    The legacy application ended its "open the output" path in os.startfile(),
    and five window methods called it. Running the window suite on a real
    desktop therefore opened the operator's editor once per test and stole
    focus from whatever he was doing. It went unnoticed for as long as it
    existed because those tests only ever ran headless, where startfile is
    never reached.

    Guarding the operating-system calls rather than the application's own
    wrapper is deliberate: this keeps biting after the wrapper is renamed.
    """

    if "opens_for_real" in request.keywords:
        return

    def refuse(*args, **kwargs):
        raise HarnessViolation(
            "a test tried to launch a desktop application. Assert on the path "
            "that would have been opened instead."
        )

    # os.startfile is Windows-only and absent elsewhere; guard it when present.
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", refuse, raising=False)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(webbrowser, "open", refuse)


@pytest.fixture(autouse=True)
def no_test_sees_real_credentials(monkeypatch, tmp_path_factory):
    """A test must not be able to authenticate as the operator.

    Removing the key rather than replacing it with a plausible one is
    deliberate: a test that silently succeeds against a fake credential is a
    test that would have spent quota with a real one.
    """

    for name in ("YOUTUBE_API_KEY", "YOUTUBE_API_KEY_FILE", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    # Settings and caches land under the home directory, so it is redirected
    # somewhere disposable. Deliberately NOT inside tmp_path: an autouse
    # fixture that drops a directory into every test's tmp_path makes
    # tmp_path silently non-empty, and any test that treats it as a clean
    # slate then fails for a reason that has nothing to do with what it is
    # testing. Two tests were written against that assumption before this
    # was noticed.
    home = tmp_path_factory.mktemp("fake-home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    return home
