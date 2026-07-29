"""Migrate the operator's prompt text out of the legacy module, byte for byte.

The prompt text is the product and it is the operator's writing. It is
extracted programmatically and never retyped: a human transcribing 250 lines
of prompt will introduce a difference, and a difference in this text is a
change to the product nobody asked for.

Writes each template to resources/prompts/ and records the SHA-256 of both
the source constant and the written file. The migration test asserts they are
equal, byte for byte, without normalising whitespace, line endings or Unicode.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import os

# Where the legacy application lives. Read from the environment rather than
# written here: an absolute home path names the account it belongs to, and
# this file is meant to be publishable. Defaults to a sibling directory,
# which is where it actually is.
LEGACY = pathlib.Path(
    os.environ.get("YTCOMMENT_LEGACY_APP")
    or pathlib.Path(__file__).resolve().parents[2] / "Comment_Generation_Claude02"
)
ROOT = pathlib.Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "src" / "llm_youtube_comment_generation" / "resources" / "prompts"
MANIFEST = PROMPTS / "checksums.json"

sys.path.insert(0, str(LEGACY))

# (filename, legacy module, constant name)
TEMPLATES = [
    ("comment_workflow.md", "youtube_video_comment", "COMMENT_WORKFLOW_TEMPLATE"),
    ("comment_final_check.md", "youtube_video_comment", "FINAL_OUTPUT_CHECK_TEMPLATE"),
    ("reply_workflow.md", "youtube_video_reply", "REPLY_WORKFLOW_TEMPLATE"),
    ("reply_final_check.md", "youtube_video_reply", "FINAL_OUTPUT_CHECK_TEMPLATE"),
    ("reply_triage.md", "youtube_video_reply", "TRIAGE_PROMPT"),
]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> None:
    import youtube_video_comment
    import youtube_video_reply

    modules = {
        "youtube_video_comment": youtube_video_comment,
        "youtube_video_reply": youtube_video_reply,
    }

    PROMPTS.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, object]] = {}

    for filename, module_name, constant in TEMPLATES:
        source = getattr(modules[module_name], constant)
        if not isinstance(source, str) or not source.strip():
            raise SystemExit(f"{module_name}.{constant} is not usable prompt text")

        target = PROMPTS / filename
        # Written as bytes with no newline translation. Passing through a text
        # mode that rewrites \n would change the checksum and, worse, change
        # the prompt.
        target.write_bytes(source.encode("utf-8"))

        written = target.read_bytes().decode("utf-8")
        if written != source:
            raise SystemExit(f"{filename} did not round-trip byte for byte")

        manifest[filename] = {
            "source_module": module_name,
            "source_constant": constant,
            "sha256": digest(source),
            "characters": len(source),
            "lines": source.count("\n") + 1,
        }
        print(f"{filename:<26} {len(source):>7,} chars  {digest(source)[:16]}...")

    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"\nmanifest -> {MANIFEST}")


if __name__ == "__main__":
    main()
