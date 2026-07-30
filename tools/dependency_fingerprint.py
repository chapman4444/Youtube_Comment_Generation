"""Detect whether an existing project environment matches core metadata."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

INPUTS = (
    Path("pyproject.toml"),
    Path("constraints/review.txt"),
)


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in INPUTS:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(path)
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "write"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    current = fingerprint(args.root.resolve())
    if args.action == "check":
        try:
            recorded = args.state.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return 1
        return 0 if recorded == current else 1
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.state.write_text(current + "\n", encoding="ascii", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
