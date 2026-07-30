"""Construction of real external adapters for command-line and GUI runs."""

from __future__ import annotations

from typing import Callable

from ...application.configuration import Configuration
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
    whisper_model: str | None = None,
) -> PortBundle:
    """Construct the real read-only adapters. Tests replace this wholesale."""

    use_local_transcriber = (
        bool(configuration.get("transcribe_locally"))
        if transcribe_locally is None
        else bool(transcribe_locally)
    )
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
        )
        if use_local_transcriber else None
    )
    return PortBundle(
        youtube=YouTubeAdapter(
            api_key,
            build_session(configuration.get("proxy_url", "")),
            cancelled=cancelled,
        ),
        transcripts=SavedTranscriptFallback(
            ChainedTranscripts(
                TranscriptAdapter(
                    configuration.get("transcript_languages", ("en",)),
                    proxy_url=configuration.get("proxy_url", ""),
                ),
                YtDlpTranscriptAdapter(
                    configuration.get("transcript_languages", ("en",)),
                    proxy_url=configuration.get("proxy_url", ""),
                ),
                # Local transcription is a separate, explicit fallback role.
                # A conclusive no-caption result enables it.
                local_fallback=local_transcriber,
            ),
            configuration.get("output_directory", "output"),
        ),
        clipboard=SystemClipboard(),
        events=events,
    )
