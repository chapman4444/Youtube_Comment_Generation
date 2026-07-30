"""Release-friendly entry point for the tracked-file privacy audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llm_youtube_comment_generation.application.privacy import (
    audit_files,
    render_findings,
)
from llm_youtube_comment_generation.interfaces.cli.privacy_command import (
    run as run_tracked,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if args.manifest is None:
        return run_tracked(root, sys.stdout)
    paths = []
    for line in args.manifest.read_text(encoding="utf-8").splitlines():
        _digest, separator, relative = line.partition("  ")
        if separator != "  " or not relative:
            raise SystemExit("invalid privacy-audit manifest")
        paths.append(root / relative)
    findings = audit_files(root, paths)
    print(render_findings(findings))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
