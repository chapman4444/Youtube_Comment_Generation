"""Construction of real external adapters for command-line and GUI runs."""

from __future__ import annotations

from typing import Callable

from ...application.configuration import Configuration
from ...domain.statuses import TranscriptResult
from ...infrastructure.saved_transcripts import SavedTranscriptFallback
from ...infrastructure.system_clipboard import SystemClipboard
from ...infrastructure.transcript_api import TranscriptAdapter
from ...infrastructure.transcript_chain import ChainedTranscripts
from ...infrastructure.whisper_transcript import WhisperTranscriptAdapter
from ...infrastructure.youtube_api import YouTubeAdapter, build_session
from ...infrastructure.ytdlp_transcript import YtDlpTranscriptAdapter
from ...ports.bundle import PortBundle


def default_ports(
    configuration: Configuration,
    api_key: str,
    events,
    *,
    cancelled: Callable[[], bool] | None = None,
    transcribe_locally: bool | None = None,
    whisper_policy: str | None = None,
    transcript_route: str = "automatic",
    whisper_model: str | None = None,
    confirm_transcription: Callable[[TranscriptResult], bool] | None = None,
) -> PortBundle:
    """Construct the real read-only adapters. Tests replace this wholesale."""

    if whisper_policy is None:
        use_local_transcriber = (
            bool(configuration.get("transcribe_locally"))
            if transcribe_locally is None
            else bool(transcribe_locally)
        )
        selected_policy = "automatic" if use_local_transcriber else "ignore"
    else:
        selected_policy = str(whisper_policy).strip().lower()
        if selected_policy not in ("ignore", "ask", "automatic"):
            selected_policy = "ask"
        use_local_transcriber = (
            selected_policy == "automatic"
            or (
                selected_policy == "ask"
                and confirm_transcription is not None
            )
        )
    selected_route = str(transcript_route or "automatic").strip().lower()
    if selected_route not in ("automatic", "api", "ytdlp", "saved", "whisper"):
        selected_route = "automatic"
    if selected_route == "whisper":
        use_local_transcriber = True

    selected_whisper_model = (
        str(configuration.get("whisper_model", "small.en"))
        if whisper_model is None
        else str(whisper_model)
    )
    local_transcriber = (
        WhisperTranscriptAdapter(
            configuration.get("transcript_languages", ("en",)),
            proxy_url=configuration.get("proxy_url", ""),
            model_name=selected_whisper_model,
            events=events,
            cancelled=cancelled,
        )
        if use_local_transcriber else None
    )
    caption_api = TranscriptAdapter(
        configuration.get("transcript_languages", ("en",)),
        proxy_url=configuration.get("proxy_url", ""),
    )
    ytdlp_captions = YtDlpTranscriptAdapter(
        configuration.get("transcript_languages", ("en",)),
        proxy_url=configuration.get("proxy_url", ""),
    )
    if selected_route == "api":
        transcript_source = caption_api
    elif selected_route == "ytdlp":
        transcript_source = ytdlp_captions
    elif selected_route == "saved":
        transcript_source = SavedTranscriptFallback(
            None,
            configuration.get("output_directory", "output"),
        )
    elif selected_route == "whisper":
        transcript_source = local_transcriber
    else:
        transcript_source = SavedTranscriptFallback(
            ChainedTranscripts(caption_api, ytdlp_captions),
            configuration.get("output_directory", "output"),
            # A saved transcript is checked before asking to spend time on
            # Whisper. "No live captions" is not the same as "no transcript
            # exists on this machine."
            local_fallback=local_transcriber,
            approve_local_fallback=(
                confirm_transcription if selected_policy == "ask" else None
            ),
        )

    return PortBundle(
        youtube=YouTubeAdapter(
            api_key,
            build_session(configuration.get("proxy_url", "")),
            cancelled=cancelled,
        ),
        transcripts=transcript_source,
        clipboard=SystemClipboard(),
        events=events,
    )
