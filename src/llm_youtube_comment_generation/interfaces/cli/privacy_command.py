"""Command-line privacy audit over Git's publishable file set."""

from __future__ import annotations

from pathlib import Path

from ...application.privacy import audit_files, render_findings
from ...infrastructure.git_files import tracked_files


def run(root: str | Path, stdout) -> int:
    root = Path(root).expanduser().resolve()
    findings = audit_files(root, tracked_files(root))
    print(render_findings(findings), file=stdout)
    return 1 if findings else 0
