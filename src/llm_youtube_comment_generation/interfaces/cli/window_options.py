"""Projection of saved, configured, and explicitly typed window options."""

from __future__ import annotations

from ...application.configuration import Configuration, SOURCE_DEFAULT
from ...domain.section_profile import parse_length
from ...domain.writing_options import parse_dials, parse_registers


def apply_window_options(
    options,
    arguments,
    configuration: Configuration,
    *,
    start_mode: str,
) -> None:
    """Resolve built-in < saved < configured < explicit precedence."""

    def configured(name: str) -> bool:
        try:
            return configuration.source_of(name) != SOURCE_DEFAULT
        except KeyError:
            return False

    if getattr(arguments, "video", None):
        options.video = arguments.video

    if configured("output_directory") or not options.output_directory:
        options.output_directory = str(
            configuration.get("output_directory", "output")
        )
    if getattr(arguments, "output_directory", None) is not None:
        options.output_directory = str(arguments.output_directory)

    if configured("packet_characters"):
        options.packet_characters = int(configuration.get("packet_characters"))
    if getattr(arguments, "packet_characters", None) is not None:
        options.packet_characters = int(arguments.packet_characters)

    if configured("transcribe_locally"):
        options.transcribe_locally = bool(
            configuration.get("transcribe_locally", False)
        )
    if getattr(arguments, "transcribe_locally", None) is not None:
        options.transcribe_locally = bool(arguments.transcribe_locally)
    if configured("whisper_model"):
        options.whisper_model = str(
            configuration.get("whisper_model", "small.en")
        )

    if configured("reply_scan_comments"):
        options.reply_scan_comments = int(
            configuration.get("reply_scan_comments", 3000)
        )

    typed_handle = getattr(arguments, "handle", None)
    if typed_handle:
        options.my_handle = typed_handle
    elif configured("my_handle") or not options.my_handle:
        options.my_handle = str(configuration.get("my_handle", ""))

    registers = getattr(arguments, "registers", None)
    if registers:
        chosen = parse_registers(registers)
        if start_mode == "reply":
            options.reply_variations = chosen
            options.reply_approach_mode = "custom"
        else:
            options.comment_variations = chosen
            options.comment_approach_mode = "custom"

    dials = getattr(arguments, "dial", None)
    if dials:
        options.dials.update(parse_dials(dials))

    length = getattr(arguments, "length", None)
    if length:
        parsed = parse_length(length)
        if parsed is None:
            options.length = "auto"
            options.custom_length = ""
        elif length in ("short", "medium", "long"):
            options.length = length
            options.custom_length = ""
        else:
            options.length = "exact"
            options.custom_length = str(round((parsed[0] + parsed[1]) / 2))

    maximum = getattr(arguments, "max_comments", None)
    if maximum is not None:
        if start_mode == "reply":
            options.reply_scan_comments = int(maximum)
        else:
            options.max_top = int(maximum)
            options.max_recent = int(maximum)
    elif start_mode == "comment" and configured("max_comments"):
        maximum = int(configuration.get("max_comments", 500))
        options.max_top = maximum
        options.max_recent = maximum

    guided_limit = getattr(arguments, "guided_limit", None)
    if guided_limit is not None:
        options.guided_limit = int(guided_limit)
