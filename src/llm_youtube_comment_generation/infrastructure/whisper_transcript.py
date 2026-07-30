"""Make the transcript here, when YouTube has none to give.

Every other source asks YouTube for words somebody already wrote down. This
one downloads the audio and listens to it, which is the only route that works
for a video with **no captions published at all** — a gap no amount of
retrying, proxying or falling back could close, because there was nothing on
the other end to fetch.

It is deliberately last and deliberately off by default. A caption fetch is
one request; this is an audio download, a model that may not be on disk yet,
and minutes of CPU. Spending that silently in the middle of a packet build
would be a nasty surprise, so it runs only when asked for -- `--transcribe`,
or `transcribe_locally` in the settings.

**A machine transcript is labelled as one.** ``source`` says ``whisper`` and
``is_generated`` is true, both of which reach the run record. The packet's
transcript is evidence the model will quote, and evidence produced by guessing
at audio on this machine is not the same kind of thing as a caption track the
uploader published. Nothing downstream has to guess which it got.

Nothing is left behind. The audio goes to a temporary directory and is deleted
whether or not the transcription worked; a half-gigabyte of stray .m4a in the
operator's output directory would be this tool's mess, not his.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from ..domain.statuses import TranscriptAvailability, TranscriptResult

LOGGER = logging.getLogger(__name__)

SOURCE = "whisper"

#: Small enough to download in a minute and run on a CPU in about real time,
#: big enough to beat YouTube's own auto-captions on clear speech. The
#: operator can name a bigger one; nothing here assumes this size.
DEFAULT_MODEL = "small.en"

#: A guess about what was said is not the same as knowing. Segments the model
#: is this unsure of are dropped rather than quoted into a packet as though
#: somebody said them.
MINIMUM_CONFIDENCE = -1.0


def library_available() -> bool:
    """Whether faster-whisper can be imported. `doctor` reports this."""

    try:
        import faster_whisper  # noqa: F401
    except Exception:                       # noqa: BLE001 - reporting only
        return False
    return True


def download_audio(video_id: str, into: Path, proxy_url: str = "") -> Path:
    """Fetch the audio track alone. Returns the file written."""

    import yt_dlp

    template = str(into / "%(id)s.%(ext)s")
    options: dict[str, Any] = {
        # Audio only. Pulling video would be tens of times the bytes for
        # something never looked at.
        "format": "bestaudio/best",
        "outtmpl": template,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _Silent(),
    }
    if proxy_url:
        options["proxy"] = proxy_url

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=True
        )

    written = list(into.glob(f"{info.get('id', video_id)}.*"))
    if not written:
        raise OSError("yt-dlp reported success but wrote no audio file")
    return written[0]


class _Silent:
    """yt-dlp writes progress to stdout unless told otherwise."""

    def debug(self, message: str) -> None:
        LOGGER.debug("yt-dlp: %s", message)

    info = debug

    def warning(self, message: str) -> None:
        LOGGER.debug("yt-dlp: %s", message)

    def error(self, message: str) -> None:
        LOGGER.warning("yt-dlp: %s", message)


def transcribe(
    audio: Path,
    *,
    model_name: str = DEFAULT_MODEL,
    language: str = "",
    maximum_seconds: int | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Run the model over one audio file. Returns (entries, language)."""

    from faster_whisper import WhisperModel

    # int8 on CPU: several times faster than float32 and, on speech, not
    # audibly worse. A machine without a GPU is the case here.
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    options: dict[str, Any] = {
        "language": language or None,
        # Skips silence rather than hallucinating words into it, which is
        # whisper's best-known failure and the one that would put invented
        # sentences into a packet.
        "vad_filter": True,
    }
    if maximum_seconds is not None:
        options["clip_timestamps"] = f"0,{max(1, int(maximum_seconds))}"
    segments, info = model.transcribe(str(audio), **options)
    return list(_entries(segments)), str(getattr(info, "language", "") or "")


def _entries(segments: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for segment in segments:
        text = " ".join(str(getattr(segment, "text", "")).split())
        if not text:
            continue
        confidence = float(getattr(segment, "avg_logprob", 0.0) or 0.0)
        if confidence < MINIMUM_CONFIDENCE:
            LOGGER.debug("dropped a low-confidence segment: %r", text[:60])
            continue
        start = float(getattr(segment, "start", 0.0) or 0.0)
        end = float(getattr(segment, "end", 0.0) or 0.0)
        yield {
            "text": text,
            "start": start,
            "duration": max(0.0, end - start),
            "end": end,
        }


class WhisperTranscriptAdapter:
    """Implements TranscriptPort by transcribing the audio locally."""

    def __init__(
        self,
        languages: Sequence[str] = ("en",),
        proxy_url: str = "",
        model_name: str = DEFAULT_MODEL,
        downloader: Callable[..., Path] | None = None,
        transcriber: Callable[..., tuple[list[dict[str, Any]], str]] | None = None,
        events=None,
    ) -> None:
        self._languages = tuple(languages)
        self._proxy_url = proxy_url or ""
        self._model_name = model_name
        self._download = downloader or download_audio
        self._transcribe = transcriber or transcribe
        self._events = events
        self._done: dict[str, TranscriptResult] = {}

    def fetch(
        self,
        video_id: str,
        languages: Sequence[str] = (),
    ) -> TranscriptResult:
        wanted = tuple(languages) or self._languages

        cached = self._done.get(video_id)
        if cached is not None:
            return cached

        if self._download is download_audio and not library_available():
            return TranscriptResult(
                availability=TranscriptAvailability.FETCH_FAILED,
                source=SOURCE,
                detail=("faster-whisper is not installed, so the audio could "
                        "not be transcribed here"),
            )

        self._say(
            f"No captions were published, so the audio is being transcribed "
            f"here with {self._model_name}. This takes minutes, not seconds."
        )

        # A temporary directory, removed whichever way this goes. Half a
        # gigabyte of stray audio in the operator's output would be our mess.
        with tempfile.TemporaryDirectory(prefix="ytcomment-audio-") as scratch:
            try:
                audio = self._download(video_id, Path(scratch), self._proxy_url)
            except Exception as exc:        # noqa: BLE001 - library raises broadly
                return TranscriptResult(
                    availability=TranscriptAvailability.FETCH_FAILED,
                    source=SOURCE,
                    detail=(f"the audio could not be downloaded "
                            f"({type(exc).__name__}: "
                            f"{str(exc).splitlines()[0][:120]})"),
                )

            try:
                entries, detected = self._transcribe(
                    audio,
                    model_name=self._model_name,
                    language=wanted[0].split("-")[0] if wanted else "",
                )
            except Exception as exc:        # noqa: BLE001
                return TranscriptResult(
                    availability=TranscriptAvailability.FETCH_FAILED,
                    source=SOURCE,
                    detail=(f"the audio downloaded but could not be "
                            f"transcribed ({type(exc).__name__}: "
                            f"{str(exc).splitlines()[0][:120]})"),
                )

        if not entries:
            return TranscriptResult(
                availability=TranscriptAvailability.EMPTY,
                source=SOURCE,
                detail="the audio produced no speech",
            )

        result = TranscriptResult(
            entries=tuple(entries),
            availability=TranscriptAvailability.AVAILABLE,
            language=detected or (wanted[0] if wanted else ""),
            language_code=detected or (wanted[0] if wanted else ""),
            # Never presented as a published caption track. This is a machine
            # listening to audio, and the run record says so.
            is_generated=True,
            source=SOURCE,
            detail=(f"no captions were published for this video, so the audio "
                    f"was transcribed on this machine with {self._model_name}. "
                    "Treat it as a machine's reading of speech, not a "
                    "transcript the uploader published."),
        )
        self._done[video_id] = result
        self._say(f"Transcribed {len(entries):,} segments.")
        return result

    def _say(self, message: str) -> None:
        """Tell the operator, because this is the slow one."""

        LOGGER.info("%s", message)
        if self._events is None:
            return
        try:
            from ..ports.events import EventKind, ProgressEvent

            self._events.emit(ProgressEvent(
                EventKind.STEP, step="transcribe", message=message
            ))
        except Exception:                   # noqa: BLE001 - reporting only
            LOGGER.debug("could not emit a progress event", exc_info=True)
