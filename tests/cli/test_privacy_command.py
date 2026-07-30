from __future__ import annotations

import io
import subprocess

from llm_youtube_comment_generation.interfaces.cli.main import main


def test_privacy_command_checks_the_git_file_set(tmp_path, monkeypatch):
    (tmp_path / "window_settings.json").write_text("{}", encoding="utf-8")

    def fake_run(*args, **kwargs):
        if "rev-parse" in args[0]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=str(tmp_path).encode("utf-8"),
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=b"window_settings.json\0",
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = io.StringIO()

    code = main(
        ["privacy", "check", "--root", str(tmp_path)],
        stdout=out,
        stderr=out,
        environment={},
    )

    assert code == 1
    assert "private state file" in out.getvalue()
