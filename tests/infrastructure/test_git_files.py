from __future__ import annotations

import subprocess

from llm_youtube_comment_generation.infrastructure.git_files import (
    tracked_files,
)


def test_nested_non_repository_root_uses_its_own_files(tmp_path, monkeypatch):
    nested = tmp_path / "review_stage"
    nested.mkdir()
    (nested / "README.md").write_text("review", encoding="utf-8")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=str(tmp_path).encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert tracked_files(nested) == ("README.md",)


def test_every_nested_git_call_trusts_only_the_requested_root(
    tmp_path,
    monkeypatch,
):
    root = tmp_path.resolve()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        output = (
            str(root).encode("utf-8")
            if command[-2:] == ["rev-parse", "--show-toplevel"]
            else b"README.md\0"
        )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=output,
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert tracked_files(root) == ("README.md",)
    assert len(calls) == 2
    for command, kwargs in calls:
        assert command[:3] == [
            "git",
            "-c",
            f"safe.directory={root.as_posix()}",
        ]
        assert command[3:5] == ["-C", str(root)]
        assert kwargs == {"check": False, "capture_output": True}
