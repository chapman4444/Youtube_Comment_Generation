"""Read-only, bounded live smoke test for the local Whisper fallback."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from llm_youtube_comment_generation.domain.ids import extract_video_id
from llm_youtube_comment_generation.infrastructure.whisper_transcript import (
    download_audio,
    transcribe,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--model", default="small.en")
    parser.add_argument("--seconds", type=int, default=60)
    arguments = parser.parse_args()

    video_id = extract_video_id(arguments.video)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ytcomment-whisper-smoke-") as raw:
        audio = download_audio(video_id, Path(raw))
        entries, language = transcribe(
            audio,
            model_name=arguments.model,
            language="en",
            maximum_seconds=max(1, arguments.seconds),
        )
    text = " ".join(str(entry.get("text", "")) for entry in entries).strip()
    print(json.dumps({
        "video_id": video_id,
        "source": "whisper",
        "model": arguments.model,
        "sample_seconds": max(1, arguments.seconds),
        "language": language,
        "entries": len(entries),
        "characters": len(text),
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "temporary_audio_removed": True,
    }, indent=2))
    return 0 if entries else 1


if __name__ == "__main__":
    raise SystemExit(main())
