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
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from ..domain.errors import OperationCancelled
from ..domain.statuses import TranscriptAvailability, TranscriptResult
from .external_errors import sanitize_external_error

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

#: Local transcription is a fallback, not an unlimited media-processing job.
#: Reject longer videos before downloading their audio. The same ceiling is
#: also passed to faster-whisper in case upstream duration metadata is absent
#: or inaccurate.
DEFAULT_MAXIMUM_SECONDS = 60 * 60

#: A second, independent ceiling for malformed metadata, unusually high
#: bitrate audio, and servers that do not report a content length.
DEFAULT_MAXIMUM_AUDIO_BYTES = 200 * 1024 * 1024


class WhisperLimitExceeded(RuntimeError):
    """The local-transcription safety budget was exceeded."""


def library_available() -> bool:
    """Whether faster-whisper can be imported. `doctor` reports this."""

    try:
        import faster_whisper  # noqa: F401
    except Exception:                       # noqa: BLE001 - reporting only
        return False
    return True


def download_audio(
    video_id: str,
    into: Path,
    proxy_url: str = "",
    *,
    maximum_seconds: int = DEFAULT_MAXIMUM_SECONDS,
    maximum_bytes: int = DEFAULT_MAXIMUM_AUDIO_BYTES,
    cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Fetch bounded audio only. Returns the file written."""

    import yt_dlp

    cancelled = cancelled or (lambda: False)
    maximum_seconds = max(1, int(maximum_seconds))
    maximum_bytes = max(1, int(maximum_bytes))

    def stop_if_requested(status: dict[str, Any]) -> None:
        if cancelled():
            raise OperationCancelled("Stopped while downloading the audio.")
        downloaded = int(status.get("downloaded_bytes", 0) or 0)
        if downloaded > maximum_bytes:
            raise WhisperLimitExceeded(
                _byte_limit_message(maximum_bytes)
            )

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
        "progress_hooks": [stop_if_requested],
    }
    if proxy_url:
        options["proxy"] = proxy_url

    with yt_dlp.YoutubeDL(options) as ydl:
        stop_if_requested({})
        # Inspect first and only start the transfer after the duration and any
        # advertised byte size have passed the local-transcription budget.
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
        _enforce_media_limits(
            info,
            maximum_seconds=maximum_seconds,
            maximum_bytes=maximum_bytes,
        )
        stop_if_requested({})
        try:
            info = ydl.process_ie_result(info, download=True)
        except WhisperLimitExceeded:
            raise
        except Exception as exc:
            # yt-dlp may wrap exceptions raised by progress hooks.
            if "audio download exceeded the safety limit" in str(exc):
                raise WhisperLimitExceeded(
                    _byte_limit_message(maximum_bytes)
                ) from exc
            raise
        stop_if_requested({})

    written = list(into.glob(f"{info.get('id', video_id)}.*"))
    if not written:
        raise OSError("yt-dlp reported success but wrote no audio file")
    if written[0].stat().st_size > maximum_bytes:
        raise WhisperLimitExceeded(_byte_limit_message(maximum_bytes))
    return written[0]


def _enforce_media_limits(
    info: dict[str, Any],
    *,
    maximum_seconds: int,
    maximum_bytes: int,
) -> None:
    """Refuse known-oversized media before its audio transfer starts."""

    duration = float(info.get("duration", 0.0) or 0.0)
    if duration > maximum_seconds:
        minutes = maximum_seconds / 60
        raise WhisperLimitExceeded(
            f"video duration is {duration / 60:.1f} minutes; local Whisper "
            f"is limited to {minutes:.0f} minutes"
        )

    candidates = [info]
    candidates.extend(info.get("requested_downloads") or ())
    advertised_bytes = max(
        (
            int(candidate.get("filesize", 0)
                or candidate.get("filesize_approx", 0)
                or 0)
            for candidate in candidates
            if isinstance(candidate, dict)
        ),
        default=0,
    )
    if advertised_bytes > maximum_bytes:
        raise WhisperLimitExceeded(_byte_limit_message(maximum_bytes))


def _byte_limit_message(maximum_bytes: int) -> str:
    megabytes = maximum_bytes / (1024 * 1024)
    return (
        f"audio download exceeded the safety limit of "
        f"{megabytes:.0f} MiB"
    )


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
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[
        [dict[str, Any], float, float | None],
        None,
    ] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Run the model over one audio file. Returns (entries, language)."""

    cancelled = cancelled or (lambda: False)
    if cancelled():
        raise OperationCancelled("Stopped before local transcription began.")

    from faster_whisper import WhisperModel

    # int8 on CPU: several times faster than float32 and, on speech, not
    # audibly worse. A machine without a GPU is the case here.
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    if cancelled():
        raise OperationCancelled("Stopped before local transcription began.")
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
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    started = time.monotonic()

    def report(entry: dict[str, Any]) -> None:
        if progress is None:
            return
        audio_done = float(entry.get("end", 0.0) or 0.0)
        elapsed = max(0.0, time.monotonic() - started)
        eta = (
            max(0.0, duration - audio_done) * elapsed / audio_done
            if duration > audio_done > 0
            else None
        )
        progress(entry, duration, eta)

    return (
        list(
            _entries(
                segments,
                cancelled=cancelled,
                on_entry=report,
            )
        ),
        str(getattr(info, "language", "") or ""),
    )


def _entries(
    segments: Iterable[Any],
    *,
    cancelled: Callable[[], bool] | None = None,
    on_entry: Callable[[dict[str, Any]], None] | None = None,
) -> Iterable[dict[str, Any]]:
    for segment in segments:
        if cancelled is not None and cancelled():
            raise OperationCancelled("Stopped during local transcription.")
        text = " ".join(str(getattr(segment, "text", "")).split())
        if not text:
            continue
        confidence = float(getattr(segment, "avg_logprob", 0.0) or 0.0)
        if confidence < MINIMUM_CONFIDENCE:
            LOGGER.debug("dropped a low-confidence segment: %r", text[:60])
            continue
        start = float(getattr(segment, "start", 0.0) or 0.0)
        end = float(getattr(segment, "end", 0.0) or 0.0)
        entry = {
            "text": text,
            "start": start,
            "duration": max(0.0, end - start),
            "end": end,
        }
        if on_entry is not None:
            on_entry(entry)
        yield entry


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
        cancelled: Callable[[], bool] | None = None,
        maximum_seconds: int = DEFAULT_MAXIMUM_SECONDS,
        maximum_audio_bytes: int = DEFAULT_MAXIMUM_AUDIO_BYTES,
    ) -> None:
        self._languages = tuple(languages)
        self._proxy_url = proxy_url or ""
        self._model_name = model_name
        self._download = downloader or download_audio
        self._transcribe = transcriber or transcribe
        self._events = events
        self._cancelled = cancelled or (lambda: False)
        self._maximum_seconds = max(1, int(maximum_seconds))
        self._maximum_audio_bytes = max(1, int(maximum_audio_bytes))
        self._done: dict[str, TranscriptResult] = {}

    def _stop_if_requested(self, message: str) -> None:
        if self._cancelled():
            raise OperationCancelled(message)

    def fetch(
        self,
        video_id: str,
        languages: Sequence[str] = (),
    ) -> TranscriptResult:
        wanted = tuple(languages) or self._languages

        cached = self._done.get(video_id)
        if cached is not None:
            return cached

        self._stop_if_requested("Stopped before local transcription began.")

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
                if self._download is download_audio:
                    audio = self._download(
                        video_id,
                        Path(scratch),
                        self._proxy_url,
                        maximum_seconds=self._maximum_seconds,
                        maximum_bytes=self._maximum_audio_bytes,
                        cancelled=self._cancelled,
                    )
                else:
                    audio = self._download(
                        video_id, Path(scratch), self._proxy_url
                    )
            except OperationCancelled:
                raise
            except Exception as exc:        # noqa: BLE001 - library raises broadly
                # yt-dlp may wrap an exception raised by a progress hook.
                # Preserve the operator's Stop request rather than reporting
                # that wrapped cancellation as a failed download.
                if self._cancelled():
                    raise OperationCancelled(
                        "Stopped while downloading the audio."
                    ) from exc
                failure_detail = sanitize_external_error(
                    exc, self._proxy_url, limit=120
                )
                return TranscriptResult(
                    availability=TranscriptAvailability.FETCH_FAILED,
                    source=SOURCE,
                    detail=(f"the audio could not be downloaded "
                            f"({failure_detail})"),
                )

            self._stop_if_requested(
                "Stopped before local transcription began."
            )
            try:
                arguments: dict[str, Any] = {
                    "model_name": self._model_name,
                    "language": wanted[0].split("-")[0] if wanted else "",
                }
                if self._transcribe is transcribe:
                    arguments["maximum_seconds"] = self._maximum_seconds
                    arguments["cancelled"] = self._cancelled
                    arguments["progress"] = self._report_progress
                entries, detected = self._transcribe(audio, **arguments)
            except OperationCancelled:
                raise
            except Exception as exc:        # noqa: BLE001
                if self._cancelled():
                    raise OperationCancelled(
                        "Stopped during local transcription."
                    ) from exc
                failure_detail = sanitize_external_error(
                    exc, self._proxy_url, limit=120
                )
                return TranscriptResult(
                    availability=TranscriptAvailability.FETCH_FAILED,
                    source=SOURCE,
                    detail=(f"the audio downloaded but could not be "
                            f"transcribed ({failure_detail})"),
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

    def _report_progress(
        self,
        entry: dict[str, Any],
        duration: float,
        eta_seconds: float | None,
    ) -> None:
        if self._events is None:
            return
        from ..ports.events import EventKind, ProgressEvent

        self._events.emit(ProgressEvent(
            EventKind.PROGRESS,
            step="transcribe",
            current=int(float(entry.get("end", 0.0) or 0.0)),
            total=int(duration) if duration > 0 else None,
            data={
                "transcript_entry": dict(entry),
                "eta_seconds": eta_seconds,
                "duration_seconds": duration,
            },
        ))

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
