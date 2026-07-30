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
