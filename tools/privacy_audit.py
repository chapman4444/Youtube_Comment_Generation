"""Release-friendly entry point for the tracked-file privacy audit."""

from __future__ import annotations

import sys
from pathlib import Path

from llm_youtube_comment_generation.interfaces.cli.privacy_command import run


if __name__ == "__main__":
    raise SystemExit(run(Path.cwd(), sys.stdout))
