"""The command line.

Parses arguments, builds typed commands, calls handlers, formats results,
maps typed errors to exit codes. No domain logic.

Dependencies are injected rather than constructed inline so the whole CLI is
testable against fakes: `main(argv, build_ports=...)` runs the real argument
parsing and the real exit-code mapping with no network at all.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from ...application import (
    build_comment_packet,
    compare,
    inspect_video,
    runs,
    scan_threads,
    scoreboard,
)
from ...application.build_comment_packet import BuildCommentPacketCommand
from ...application.commands import InspectVideoCommand
from ...application.guided_session import REVIEW_FILENAME, GuidedSession
from ...application.scan_threads import ScanMyThreadsCommand
from ...domain.statuses import OperationStatus
from ...application.configuration import (
    API_KEY_VARIABLES,
    Configuration,
    redact,
    resolve,
    resolve_api_key,
)
from ...domain.errors import (
    EXIT_ERROR,
    EXIT_SUCCESS,
    OperationCancelled,
    PacketError,
)
from ...domain.extraction import looks_like_packet_text
from ...domain.ids import find_video_reference
from ...domain.reply_packet import (
    ReplyEvidence,
    build_reply_packet,
    build_triage_packet,
    triage_selection,
)
from ...domain.section_profile import measure_comment_register, parse_length
from ...domain.video import format_timestamp
from ...domain.writing_options import (
    format_dial_listing,
    format_register_listing,
    parse_dials,
    parse_registers,
)
from ...infrastructure import desktop, prompt_resources, word_resources
from ...infrastructure.event_sinks import make_event_sink
from ...infrastructure.logging_setup import configure as configure_logging
from ...infrastructure.filesystem_artifacts import (
    FilesystemArtifactStore,
    unique_run_root,
)
from ...infrastructure.sqlite_history import migrate_json
from ...infrastructure.system_clipboard import SystemClipboard
from ...infrastructure.system_clock import SystemClock
from ...infrastructure.transcript_api import library_available
from . import formatters
from .state_storage import (
    history_store,
    legacy_state_path as _legacy_state_path,
    load_window_settings as _load_window_settings,
    private_state_directory as _private_state_directory,
    save_window_settings as _save_window_settings,
    window_settings_path as _window_settings_path,
)
from .composition import default_ports
from .window_options import apply_window_options

LOGGER = logging.getLogger("ytcomment")

PROGRAM = "ytcomment"


VIDEO_HELP = ("a YouTube URL or an 11-character ID; omit it to take the "
              "video from the clipboard")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="Build YouTube comment and reply packets. Never posts.",
    )
    parser.add_argument("--config", metavar="FILE",
                        help="a JSON settings file to layer over the defaults")
    parser.add_argument("--output", choices=("human", "json"), default=None,
                        dest="output_format",
                        help="human-readable text, or JSON for scripting")
    parser.add_argument("--progress", choices=("auto", "jsonl", "none"),
                        default=None,
                        help="how progress is reported while work runs")
    parser.add_argument("--log-level", default=None, dest="log_level",
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="show per-item progress, not just steps")
    parser.add_argument("--log-jsonl", action="store_true", dest="log_jsonl",
                        help="emit structured logs, one JSON object per line")

    subparsers = parser.add_subparsers(dest="group")

    video = subparsers.add_parser("video", help="inspect a video")
    video_sub = video.add_subparsers(dest="action")
    inspect = video_sub.add_parser(
        "inspect", help="retrieve a video and report what is actually there"
    )
    inspect.add_argument("video", nargs="?", default=None, help=VIDEO_HELP)
    inspect.add_argument("--max-comments", type=int, default=None,
                         dest="max_comments")
    inspect.add_argument("--replies", action="store_true",
                         dest="include_replies",
                         help="also fetch replies for the busiest threads")
    inspect.add_argument("--languages", default=None,
                         dest="transcript_languages",
                         help="comma-separated transcript language preferences")
    inspect.add_argument("--dry-run", action="store_true", dest="dry_run",
                         help="report what would happen without spending quota")

    comment = subparsers.add_parser("comment", help="build a comment packet")
    comment_sub = comment.add_subparsers(dest="action")
    build_packet = comment_sub.add_parser(
        "build", help="assemble a packet for a video and write the run"
    )
    build_packet.add_argument("video", nargs="?", default=None,
                              help=VIDEO_HELP)
    build_packet.add_argument("--registers", default=None,
                              help="comma-separated register names; omit for "
                                   "the defaults")
    build_packet.add_argument("--dial", action="append", default=None,
                              metavar="NAME=VALUE",
                              help="set one dial; repeat for more")
    build_packet.add_argument("--length", default=None,
                              help="auto, short, medium, long, a range like "
                                   "20-60, or a single number")
    build_packet.add_argument("--max-comments", type=int, default=None,
                              dest="max_comments")
    build_packet.add_argument("--packet-characters", type=int, default=None,
                              dest="packet_characters")
    build_packet.add_argument("--output-dir", default=None,
                              dest="output_directory")
    build_packet.add_argument("--allow-no-transcript", action="store_true",
                              dest="allow_no_transcript",
                              help="build even when the video has no captions; "
                                   "the packet will say so")
    build_packet.add_argument(
        "--window", action="store_true", dest="open_window",
        help="build the packet, then open a window to copy it and paste the "
             "answer back. The comment flow had no window at all; gui.bat "
             "opens this one.",
    )
    build_packet.add_argument(
        "--transcribe", action="store_true", dest="transcribe_locally",
        default=None,
        help="if the video has no captions at all, download the audio and "
             "transcribe it on this machine. Takes minutes, not seconds, and "
             "the packet records that the words came from a machine listening "
             "rather than from a published caption track.",
    )
    build_packet.add_argument("--no-copy", action="store_true", dest="no_copy",
                              help="do not put the packet on the clipboard")
    build_packet.add_argument("--dry-run", action="store_true", dest="dry_run")
    comment_sub.add_parser("variations", help="list every selectable register")
    comment_sub.add_parser("dials", help="list every dial and its settings")

    reply = subparsers.add_parser("reply", help="work on replies you owe")
    reply_sub = reply.add_subparsers(dest="action")
    for name, help_text in (
        ("scan-mine", "find your threads and who is owed a reply"),
        ("target-comment", "show one person, chosen by their comment id"),
        ("target-reply", "show one person, chosen by their handle"),
        ("build", "assemble a reply packet for one person"),
        ("triage", "assemble a packet asking who is worth answering"),
        ("guided", "work through several people, saving as you go"),
    ):
        sub = reply_sub.add_parser(name, help=help_text)
        sub.add_argument("video", nargs="?", default=None, help=VIDEO_HELP)
        sub.add_argument("--my-channel-id", default=None, dest="channel_id")
        sub.add_argument("--my-handle", default=None, dest="handle")
        sub.add_argument("--since", default=None,
                         help="a day count, an ISO date, or an ISO datetime")
        sub.add_argument("--max-comments", type=int, default=None,
                         dest="max_comments")
        if name == "scan-mine":
            sub.add_argument("--all", action="store_true", dest="show_all",
                             help="include people you have already answered")
        if name == "target-comment":
            sub.add_argument("--comment-id", required=True, dest="comment_id")
        if name == "target-reply":
            sub.add_argument("--handle-of", required=True, dest="target_handle")
        if name == "build":
            sub.add_argument("--comment-id", default=None, dest="comment_id")
            sub.add_argument("--handle-of", default=None, dest="target_handle")
            sub.add_argument("--registers", default=None)
            sub.add_argument("--dial", action="append", default=None,
                             metavar="NAME=VALUE")
            sub.add_argument("--packet-characters", type=int, default=None,
                             dest="packet_characters")
            sub.add_argument("--output-dir", default=None,
                             dest="output_directory")
        if name == "triage":
            sub.add_argument("--limit", type=int, default=20,
                             dest="triage_limit")
            sub.add_argument("--output-dir", default=None,
                             dest="output_directory")
        if name == "guided":
            sub.add_argument("--registers", default=None)
            sub.add_argument("--dial", action="append", default=None,
                             metavar="NAME=VALUE")
            sub.add_argument("--limit", type=int, default=10,
                             dest="guided_limit",
                             help="how many people to work through")
            sub.add_argument("--output-dir", default=None,
                             dest="output_directory")
            sub.add_argument("--answers-from", default=None,
                             dest="answers_from",
                             help="read answers from a file of blocks "
                                  "separated by a line of ---, instead of "
                                  "the clipboard")

    history = subparsers.add_parser("history", help="the drafts you recorded")
    history_sub = history.add_subparsers(dest="action")
    history_sub.add_parser("list", help="every recorded draft")
    record = history_sub.add_parser(
        "record",
        help="record a draft only after you manually posted it",
    )
    record.add_argument("video", help=VIDEO_HELP)
    draft_source = record.add_mutually_exclusive_group(required=True)
    draft_source.add_argument("--draft", help="the exact posted text")
    draft_source.add_argument(
        "--draft-file",
        help="a UTF-8 file containing the exact posted text",
    )
    record.add_argument("--workflow", choices=("comment", "reply"),
                        required=True)
    record.add_argument("--target", default="")
    record.add_argument("--target-comment-id", default="",
                        dest="target_comment_id")
    record.add_argument("--thread-id", default="", dest="thread_id")
    record.add_argument("--run-id", default="", dest="run_id")
    record.add_argument("--event-id", default="", dest="event_id")
    record.add_argument("--registers", default=None)
    record.add_argument("--posted-at", default=None, dest="posted_at")
    migrate = history_sub.add_parser(
        "migrate", help="copy a legacy posted_history.json into the store"
    )
    migrate.add_argument("source", help="path to posted_history.json")
    history_sub.add_parser(
        "quarantine", help="set an unreadable store aside"
    )

    board = subparsers.add_parser("scoreboard", help="what your replies earned")
    board_sub = board.add_subparsers(dest="action")
    build_board = board_sub.add_parser(
        "build", help="match recorded drafts against what is live now"
    )
    build_board.add_argument("video", nargs="?", default=None,
                             help=VIDEO_HELP)
    build_board.add_argument("--max-comments", type=int, default=None,
                             dest="max_comments")
    build_board.add_argument("--my-channel-id", default=None,
                             dest="channel_id")
    build_board.add_argument("--my-handle", default=None, dest="handle")
    build_board.add_argument("--output-dir", default=None,
                             dest="output_directory")

    rebuild = comment_sub.add_parser(
        "rebuild",
        help="re-render a finished run's packet with different options",
    )
    rebuild.add_argument("run", help="a run directory holding evidence.json")
    rebuild.add_argument("--registers", default=None)
    rebuild.add_argument("--dial", action="append", default=None,
                         metavar="NAME=VALUE")
    rebuild.add_argument("--length", default=None)
    rebuild.add_argument("--packet-characters", type=int, default=None,
                         dest="packet_characters")
    rebuild.add_argument("--output-dir", default=None, dest="output_directory")
    rebuild.add_argument("--allow-no-transcript", action="store_true",
                         dest="allow_no_transcript")
    rebuild.add_argument("--no-copy", action="store_true", dest="no_copy")

    words_parser = subparsers.add_parser(
        "words", help="keyword frequencies from a transcript, filler removed"
    )
    words_parser.add_argument(
        "source", help="a transcript file, or a run directory containing one"
    )
    words_parser.add_argument("--stopwords", default=None,
                              help="comma-separated word-list names; omit for "
                                   "the default")
    words_parser.add_argument("--min-length", type=int, default=3,
                              dest="minimum_length")
    words_parser.add_argument("--min-count", type=int, default=1,
                              dest="minimum_count")
    words_parser.add_argument("--top", type=int, default=40,
                              help="how many rows to print; 0 or less for all")
    words_parser.add_argument("--list-wordlists", action="store_true",
                              dest="list_wordlists")

    compare_parser = subparsers.add_parser(
        "compare", help="diff two packets' instruction regions"
    )
    compare_parser.add_argument("old_packet", help="a packet from the old app")
    compare_parser.add_argument("new_packet", help="a packet from this one")

    gui_parser = subparsers.add_parser(
        "gui", help="open the window on a guided run"
    )
    gui_parser.add_argument("video", nargs="?", default=None, help=VIDEO_HELP)
    gui_parser.add_argument("--my-channel-id", default=None, dest="channel_id")
    gui_parser.add_argument("--my-handle", default=None, dest="handle")
    gui_parser.add_argument("--registers", default=None)
    gui_parser.add_argument("--dial", action="append", default=None,
                            metavar="NAME=VALUE")
    gui_parser.add_argument("--limit", type=int, default=None,
                            dest="guided_limit")
    gui_parser.add_argument("--max-comments", type=int, default=None,
                            dest="max_comments")
    gui_parser.add_argument("--output-dir", default=None,
                            dest="output_directory")
    gui_parser.add_argument(
        "--classic", action="store_true",
        help="the previous window: a scan first, then a queue of buttons. "
             "Kept until the new one has been used in anger; it will go.",
    )
    gui_parser.add_argument(
        "--preview", action="store_true",
        help="open the window on made-up people, with no scan and nothing "
             "saved. The window otherwise needs a video you commented on "
             "where somebody replied and you have not answered.",
    )

    review = subparsers.add_parser("review", help="the replies you drafted")
    review_sub = review.add_subparsers(dest="action")
    show = review_sub.add_parser("show", help="print a run's review file")
    show.add_argument("run_directory", help="a run directory under output/")

    config = subparsers.add_parser("config", help="inspect configuration")
    config_sub = config.add_subparsers(dest="action")
    config_sub.add_parser(
        "print", help="show every effective setting and where it came from"
    )
    config_sub.add_parser(
        "path", help="show where settings and state are read from"
    )

    privacy = subparsers.add_parser(
        "privacy", help="check publishable files for personal data"
    )
    privacy_sub = privacy.add_subparsers(dest="action")
    privacy_check = privacy_sub.add_parser(
        "check", help="audit Git-tracked files before publishing"
    )
    privacy_check.add_argument("--root", default=".")

    runs = subparsers.add_parser("run", help="inspect past runs")
    runs_sub = runs.add_subparsers(dest="action")
    list_runs_parser = runs_sub.add_parser("list", help="every run, newest first")
    list_runs_parser.add_argument("--output-dir", default=None,
                                  dest="output_directory")
    validate_parser = runs_sub.add_parser(
        "validate", help="report everything wrong with one run"
    )
    validate_parser.add_argument("run_directory")

    subparsers.add_parser(
        "doctor", help="check that this installation can actually run"
    )
    return parser


def typed_flags(arguments: argparse.Namespace) -> dict[str, Any]:
    """Only what the operator actually typed.

    argparse defaults are deliberately None so an untouched flag does not
    masquerade as a command-line value and silently outrank the settings
    file. `config print` would otherwise report every setting as coming from
    the command line, which is both wrong and useless.
    """

    names = ("output_format", "progress", "log_level", "max_comments",
             "transcript_languages", "packet_characters", "output_directory",
             # --transcribe defaults to None rather than False for exactly the
             # reason above: store_true's usual False would look like the
             # operator had typed --no-transcribe and would outrank a settings
             # file that turned it on.
             "transcribe_locally")
    return {name: getattr(arguments, name, None) for name in names
            if getattr(arguments, name, None) is not None}


def load_config_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    location = Path(path).expanduser()
    if not location.is_file():
        from ...domain.errors import ConfigurationError
        raise ConfigurationError(f"No configuration file at {location}")
    try:
        loaded = json.loads(location.read_text(encoding="utf-8"))
    except ValueError as exc:
        from ...domain.errors import ConfigurationError
        raise ConfigurationError(f"{location} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        from ...domain.errors import ConfigurationError
        raise ConfigurationError(f"{location} must contain a JSON object.")
    return loaded


def video_from_clipboard(clipboard, stdout) -> str:
    """Take the video from the clipboard when none was given on the line.

    The normal way to reach a video is to copy its URL from the browser, so
    requiring it to be pasted back is a step the tool can remove.

    Two refusals matter more than the convenience:

    A packet is never accepted. The tool puts its own packet on the clipboard
    when a run finishes, so the clipboard usually holds one, and a packet
    quotes the video description — including whatever links are in it. Reading
    a packet back would start a run on a link the operator never chose. This
    is the same rule the guided session already applies to answers, for the
    same reason.

    Nothing is ever guessed silently. What was read is printed before any
    request is made, because a wrong video spends quota and writes a run
    directory under a name the operator did not pick.
    """

    from ...domain.errors import ConfigurationError

    text = ""
    if clipboard is not None:
        text = clipboard.read() or ""

    if looks_like_packet_text(text):
        raise ConfigurationError(
            "The clipboard holds a packet, not a video. Copy the video URL "
            "from your browser, or name the video on the command line."
        )

    video = find_video_reference(text)
    if not video:
        raise ConfigurationError(
            "No video was given and no YouTube link was found on the "
            "clipboard. Copy the video URL, or name the video on the "
            "command line."
        )

    print(f"Read the video from your clipboard: {video}", file=stdout)
    return video


def run_rebuild(arguments, configuration, stdout, clipboard) -> int:
    """Re-render a packet from a finished run, with different options.

    Everything a packet is built from is already written beside it, so asking
    YouTube again to change a register is waste: it spends quota, and it can
    fail for reasons that have nothing to do with the question being asked.
    Rebuilding the seven option variants of one video is what got this
    machine IP-blocked from the transcript endpoint.

    It also keeps the source evidence exact rather than nearly exact. Two
    packets built minutes apart can differ by a comment that arrived in
    between; rebuild uses the original relevance ordering, recency ordering,
    merged comments, replies, transcript and retrieval outcome.
    """

    from ...domain.errors import ConfigurationError
    from ...domain.packet_builder import PacketEvidence, PacketOptions, build
    from ...domain.packets import select_packet_sections
    from ...domain.statuses import RetrievalOutcome, RetrievalStatus
    from ...domain.writing_options import DIALS, dial_choice

    source = Path(arguments.run).expanduser()
    evidence_file = source / "evidence.json"
    record_file = source / "run.json"
    transcript_file = source / "transcript_timestamped.txt"

    if not evidence_file.is_file():
        raise ConfigurationError(
            f"No evidence.json in {source}. Rebuild needs a run directory "
            "written by this tool, not a packet on its own."
        )
    if not record_file.is_file():
        raise ConfigurationError(
            f"No run.json in {source}. Without it the retrieval outcome is "
            "unknown, and a packet that cannot say how complete its evidence "
            "is would be worse than no packet."
        )

    saved = json.loads(evidence_file.read_text(encoding="utf-8"))
    record = json.loads(record_file.read_text(encoding="utf-8"))
    transcript_text = (transcript_file.read_text(encoding="utf-8")
                       if transcript_file.is_file() else "")

    retrieval = record.get("retrieval", {})
    outcome = RetrievalOutcome(
        status=RetrievalStatus(retrieval.get("status", "complete")),
        retrieved=int(retrieval.get("retrieved", 0)),
        reported_total=retrieval.get("reported_total"),
        notes=tuple(retrieval.get("notes", ())),
    )

    schema_version = saved.get("schema_version")
    relevance_comments = saved.get("relevance_comments")
    recent_comments = saved.get("recent_comments")
    if schema_version != 2 or not isinstance(relevance_comments, list) or \
            not isinstance(recent_comments, list):
        raise ConfigurationError(
            "This run predates the versioned rebuild evidence contract. "
            "Its relevance and recency orderings were not saved, so an exact "
            "offline rebuild is impossible. Build the video once with the "
            "current version before using comment rebuild."
        )

    comments = saved.get("comments", [])
    replies = saved.get("replies", [])
    if not isinstance(comments, list) or not isinstance(replies, list):
        raise ConfigurationError(
            "evidence.json does not contain valid comment and reply lists."
        )
    evidence = PacketEvidence(
        video=saved.get("video", {}),
        comments=comments,
        replies=replies,
        transcript_text=transcript_text,
        transcript_available=bool(transcript_text.strip()),
        register=measure_comment_register(comments),
        retrieval=outcome,
        stopwords=word_resources.stopwords(),
    )
    selection = select_packet_sections(
        relevance_comments, recent_comments, comments, evidence.replies,
    )
    options = PacketOptions(
        variations=(parse_registers(arguments.registers)
                    if arguments.registers else ()),
        dials=parse_dials(arguments.dial or []),
        maximum_characters=configuration.get("packet_characters"),
        explicit_length=(parse_length(arguments.length)
                         if arguments.length else None),
        allow_no_transcript=arguments.allow_no_transcript,
    )
    packet = build(
        evidence, selection, options,
        workflow_template=prompt_resources.load("comment_workflow.md").text,
        final_check_template=prompt_resources.load(
            "comment_final_check.md").text,
    )

    video_id = str(saved.get("video", {}).get("video_id") or source.name)
    artifacts = _artifact_store({}, configuration, video_id)
    artifacts.stage("packet.md", packet.text)
    artifacts.stage("evidence.json",
                    json.dumps(saved, indent=2, ensure_ascii=False))
    artifacts.stage("transcript_timestamped.txt", transcript_text)
    rebuilt_record = dict(record)
    rebuilt_record.update({
        "kind": "rebuild",
        "artifact_contract_version": 2,
        "evidence_schema_version": 2,
        "prompt_version": prompt_resources.prompt_version(),
        "rebuilt_from": str(source),
        "variations": list(packet.variations),
        "variation_headings": list(packet.headings),
        "dials": {
            name: dial_choice(name, options.dials) for name in DIALS
        },
        "packet_characters": len(packet.text),
        "budget": options.maximum_characters,
        "allocation": {
            "comment_body": packet.allocation.comment_body,
            "reply_body": packet.allocation.reply_body,
            "transcript": packet.allocation.transcript,
            "transcript_reduced": packet.allocation.transcript_reduced,
        },
        "retrieval": retrieval,
        "transcript": dict(record.get("transcript") or {
            "availability": (
                "available" if transcript_text.strip() else "not_published"
            ),
            "language": "",
            "entries": len(transcript_text.splitlines()),
            "source": "saved-rebuild-evidence",
            "detail": "",
        }),
    })
    artifacts.stage(
        "report.md",
        build_comment_packet.render_report(rebuilt_record, packet),
    )
    artifacts.stage(
        "run.json",
        json.dumps(rebuilt_record, indent=2, ensure_ascii=False),
    )
    published = artifacts.commit()

    print(f"Rebuilt from {source}\n"
          f"Packet written: {len(packet.text):,} characters\n"
          f"  registers  {', '.join(packet.variations)}\n"
          f"  files      {', '.join(published)}\n"
          f"  directory  {getattr(artifacts, 'root', '')}", file=stdout)
    if not arguments.no_copy:
        copy_to_clipboard({"clipboard": clipboard}, packet.text, stdout)
    return EXIT_SUCCESS


def run_words(arguments, stdout) -> int:
    """Keyword frequencies for one transcript.

    Accepts a run directory as well as a file, because that is what the
    operator has: every run writes transcript_timestamped.txt beside its
    packet, and making him find the file inside it is a step the tool can
    take.
    """

    from ...domain.errors import ConfigurationError
    from ...domain.transcript_words import render_table, summarise
    from ...infrastructure import word_resources

    if arguments.list_wordlists:
        print("\n".join(word_resources.available()), file=stdout)
        return EXIT_SUCCESS

    source = Path(arguments.source).expanduser()
    if source.is_dir():
        # Named, not globbed. A legacy run directory holds transcript_plain.txt
        # as well, and sorted()[0] picked that one — an arbitrary choice
        # presented as the obvious one.
        candidates = [
            source / "transcript_timestamped.txt",
            source / "transcript_plain.txt",
        ]
        found = next((path for path in candidates if path.is_file()), None)
        if found is None:
            raise ConfigurationError(
                f"No transcript file in {source}. Expected "
                "transcript_timestamped.txt or transcript_plain.txt."
            )
        source = found
    if not source.is_file():
        raise ConfigurationError(f"No transcript at {source}")

    names = (tuple(part.strip() for part in arguments.stopwords.split(",")
                   if part.strip())
             if arguments.stopwords else word_resources.TRANSCRIPT_STOPWORDS)
    stopwords = word_resources.stopwords(names)

    rows, total, removed = summarise(
        source.read_text(encoding="utf-8"), stopwords,
        minimum_length=arguments.minimum_length,
        minimum_count=arguments.minimum_count,
    )
    shown = rows if arguments.top <= 0 else rows[:arguments.top]

    print(f"{source}\n", file=stdout)
    print(render_table(shown, total_tokens=total, removed=removed,
                       distinct=len(rows)), file=stdout)
    if len(shown) < len(rows):
        print(f"\nShowing {len(shown):,} of {len(rows):,} keywords. "
              f"--top 0 for all.", file=stdout)
    return EXIT_SUCCESS


def describe_triage_selection(found, waiting, listed) -> str:
    """Say how many people the packet lists, and where the rest went.

    The scan prints how many people it found. The packet lists only those
    still waiting, capped by --limit. Printing the first number and not the
    second reads as "all of them are in here", and the operator triages a
    shorter list than he thinks he is looking at.
    """

    if not listed:
        if waiting:
            # Saying "nobody is waiting" here would be false: --limit held
            # them back. An empty packet has two very different causes.
            return (f"nobody — --limit held back all "
                    f"{len(waiting):,} people still waiting")
        return "nobody — no one in this scan is waiting for an answer"

    sentence = f"{len(listed):,} of {len(found):,} people found"
    answered = len(found) - len(waiting)
    held_back = len(waiting) - len(listed)

    because = []
    if answered:
        because.append(f"{answered:,} already answered")
    if held_back:
        because.append(f"{held_back:,} held back by --limit")
    if because:
        sentence += f" ({', '.join(because)})"
    return sentence


def copy_to_clipboard(ports, text: str, stdout) -> bool:
    """Put a finished packet on the clipboard, and say so.

    Announced rather than silent. Replacing the clipboard is a real side
    effect on whatever the operator had there, and a tool that does it
    without a word is one you stop trusting with anything else.
    """

    clipboard = ports.get("clipboard")
    if clipboard is None:
        return False
    # Both signals matter. The adapter reports whether the system accepted
    # the data; the read-back catches the case where it accepted it and lost
    # it anyway, which is exactly what Tk did on Windows.
    accepted = clipboard.write(text)
    if accepted is False or clipboard.read() != text:
        # Another application can hold the clipboard. Worth saying, because
        # the operator is about to paste and would otherwise paste whatever
        # was there before.
        print("  clipboard  could not be set; copy packet.md by hand",
              file=stdout)
        return False
    print(f"  clipboard  the packet is on your clipboard "
          f"({len(text):,} characters), ready to paste", file=stdout)
    return True


def _whisper_state(configuration) -> str:
    """Whether transcribing here is possible, and whether it is switched on.

    Two different facts, and reporting only one of them is how an operator
    concludes his setting is broken when the library is missing, or that the
    library is missing when the setting is off.
    """

    from ...infrastructure.whisper_transcript import (
        library_available as whisper_available,
    )

    installed = whisper_available()
    wanted = bool(configuration.get("transcribe_locally"))
    model = configuration.get("whisper_model", "small.en")

    if not installed:
        return ("not installed - videos with no captions at all cannot be "
                "transcribed. Run: python -m pip install -e "
                "\".[local-transcription]\"")
    if not wanted:
        return (f"installed, off. Turn it on with --transcribe or "
                f"YTCOMMENT_TRANSCRIBE_LOCALLY=1 ({model})")
    return f"installed, on ({model}). Costs minutes of CPU per video."


def _saved_transcript_state(configuration) -> str:
    """How many videos this machine could already answer for offline."""

    from ...infrastructure.saved_transcripts import find_saved

    root = Path(configuration.get("output_directory", "output"))
    if not root.is_dir():
        return "no output directory yet, so nothing has been saved"
    videos = {
        path.parent.name.split("_")[0]
        for path in root.glob("*/transcript_timestamped.txt")
        if path.stat().st_size > 0
    }
    if not videos:
        return "nothing saved yet - the first successful fetch creates one"
    return (f"{len(videos)} video(s) can be rebuilt without fetching "
            "anything")


def ytdlp_available() -> bool:
    """Whether the player-API source can be used."""

    from ...infrastructure.ytdlp_transcript import (
        library_available as available,
    )

    return available()


def run_doctor(configuration: Configuration, api_key: str, stream) -> int:
    """Report whether this installation can run, without failing if it cannot.

    `doctor` exists to be run when something is wrong, so it must not be the
    thing that also breaks. A missing transcript library is reported as a
    fact and exits 0: the application works without it.
    """

    root = Path(configuration.get("output_directory", "output"))

    def safe_detail(exc: Exception) -> str:
        """Bound one failed probe without echoing paths or credentials."""

        detail = redact(
            str(exc),
            api_key,
            configuration.get("proxy_url", ""),
        )
        for private, replacement in (
            (str(Path.home()), "<user-home>"),
            (str(root), "<output-directory>"),
        ):
            if private:
                detail = detail.replace(private, replacement)
                detail = detail.replace(
                    private.replace("\\", "/"), replacement
                )
        detail = re.sub(
            r"([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@/\s]+@",
            r"\1[credentials-redacted]@",
            detail,
            flags=re.IGNORECASE,
        )
        detail = " ".join(detail.split())
        if len(detail) > 240:
            detail = detail[:237] + "..."
        return detail or "no detail"

    def checked(name, probe):
        try:
            ok, detail = probe()
            return name, str(detail), bool(ok)
        except Exception as exc:          # noqa: BLE001 - diagnostic boundary
            return (
                name,
                f"CHECK FAILED ({type(exc).__name__}): {safe_detail(exc)}",
                False,
            )

    def history_state() -> tuple[bool, str]:
        store = history_store(configuration)
        return True, f"{len(store.load()):,} drafts recorded"

    # Run this first because creating a missing output directory also makes
    # the saved-transcript check precise. It is still printed in its familiar
    # place below.
    output_check = checked("output directory", lambda: _write_check(root))
    checks = [
        checked(
            "python",
            lambda: (
                True,
                f"{sys.version_info.major}.{sys.version_info.minor}"
                f".{sys.version_info.micro}",
            ),
        ),
        checked(
            "api key",
            lambda: (
                bool(api_key),
                "resolved" if api_key else
                f"NOT FOUND (set {' or '.join(API_KEY_VARIABLES)})",
            ),
        ),
        # Every source that can supply the words, named separately. The
        # transcript stack is four deep now and "transcript library:
        # installed" answered one quarter of the question -- which is worse
        # than answering none of it, because it reads like the whole answer.
        checked(
            "transcript: scrape",
            lambda: (
                True,
                "installed" if library_available()
                else (
                    "not installed - run: python -m pip install -e "
                    "\".[transcripts]\""
                ),
            ),
        ),
        checked(
            "transcript: yt-dlp",
            lambda: (
                True,
                "installed - backs up the scrape endpoint, blocked separately"
                if ytdlp_available()
                else (
                    "not installed - run: python -m pip install -e "
                    "\".[transcripts]\""
                ),
            ),
        ),
        checked(
            "transcript: whisper",
            lambda: (True, _whisper_state(configuration)),
        ),
        checked(
            "transcript: saved",
            lambda: (True, _saved_transcript_state(configuration)),
        ),
        checked(
            "prompt resources",
            lambda: (
                True,
                f"{prompt_resources.prompt_version()} "
                f"({len(list(prompt_resources.PROMPTS.glob('*.md')))} "
                f"templates at {prompt_resources.PROMPTS})",
            ),
        ),
        output_check,
        checked("history store", history_state),
    ]
    print("Installation check", file=stream)
    print("", file=stream)
    width = max(len(name) for name, _, _ in checks)
    for name, detail, ok in checks:
        marker = "ok" if ok else "!!"
        print(f"  {marker} {name:<{width}}  {detail}", file=stream)
    print("", file=stream)
    if not api_key:
        print("  No API key resolved, so no command that retrieves data "
              "will run.", file=stream)
    # doctor is run when something is wrong. It reports and exits 0 so it is
    # never itself the thing that fails.
    return EXIT_SUCCESS


def _write_check(root: Path) -> tuple[bool, str]:
    """Can this run actually write its output? Asked, not assumed.

    A run that discovers its output directory is read-only after spending
    quota has wasted the expensive part.
    """

    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".ytcomment-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, f"{root.resolve()} (writable)"
    except OSError as exc:
        return False, f"{root} is NOT writable ({exc.strerror or exc})"


def run_reply(
    arguments, configuration, api_key, events, stdout, build_ports
) -> int:
    """Scan the operator's threads, and optionally narrow to one target."""

    from ...domain.errors import ConfigurationError

    if not api_key:
        raise ConfigurationError(
            "No API key was found. Set "
            f"{' or '.join(API_KEY_VARIABLES)}."
        )

    command = ScanMyThreadsCommand(
        video=arguments.video,
        channel_id=arguments.channel_id or configuration.get("my_channel_id", ""),
        handle=arguments.handle or configuration.get("my_handle", ""),
        since=arguments.since or "",
        # Not max_comments. Finding one comment of his among a thousand is a
        # different job from deciding how much evidence a packet needs, and
        # using the packet's number meant a comment at position 700 was
        # invisible while the scan reported "complete".
        max_comments=(
            arguments.max_comments
            if arguments.max_comments is not None
            else configuration.get("reply_scan_comments", 3000)
        ),
        max_replies_per_thread=configuration.get(
            "max_replies_per_thread", 100
        ),
        only_unanswered=not getattr(arguments, "show_all", False),
    )

    factory = build_ports or default_ports
    ports = factory(configuration, api_key, events)
    result = scan_threads.handle(
        command,
        youtube=ports["youtube"],
        events=ports["events"],
        clock=ports.get("clock") or SystemClock(),
    )

    as_json = configuration.get("output_format") == "json"

    if arguments.action == "scan-mine":
        if as_json:
            print(json.dumps(formatters.scan_as_dict(result), indent=2,
                             ensure_ascii=False), file=stdout)
        else:
            print(formatters.render_scan(result, command.only_unanswered),
                  file=stdout)
        return EXIT_SUCCESS

    if arguments.action == "guided":
        return run_guided(arguments, configuration, command, result, ports,
                          stdout)

    if arguments.action == "triage":
        packet = build_triage_packet(
            prompt_resources.load("reply_triage.md").text,
            result.value.candidates,
            limit=arguments.triage_limit,
            maximum_characters=configuration.get("packet_characters"),
        )
        # Counted from the same selection the packet lists, never from the
        # scan. The scan line above says how many people were found, which
        # is a larger number whenever somebody has already been answered.
        found = list(result.value.candidates)
        listed = triage_selection(found, limit=arguments.triage_limit)
        waiting = [c for c in found if c.outstanding]

        artifacts = _artifact_store(ports, configuration, command.video_id)
        triage_text = packet
        artifacts.stage("reply_triage_packet.md", packet)
        _stage_run_record(
            artifacts, kind="triage",
            video={"video_id": command.video_id},
            extra={"candidates_found": len(found),
                   "candidates_waiting": len(waiting),
                   "candidates_listed": len(listed),
                   "packet_characters": len(packet)},
        )
        published = artifacts.commit()
        print(f"Triage packet written: {len(packet):,} characters\n"
              f"  files      {', '.join(published)}\n"
              f"  directory  {getattr(artifacts, 'root', '')}\n"
              f"  listed     "
              f"{describe_triage_selection(found, waiting, listed)}",
              file=stdout)
        copy_to_clipboard(ports, triage_text, stdout)
        return EXIT_SUCCESS

    candidate = scan_threads.select_target(
        result.value,
        comment_id=getattr(arguments, "comment_id", "") or "",
        handle=getattr(arguments, "target_handle", "") or "",
    )

    if arguments.action == "build":
        thread = next(
            (t for t in result.value.threads if t.comment_id == candidate.thread_id),
            None,
        )
        transcript = ports["transcripts"].fetch(command.video_id)
        evidence = ReplyEvidence(
            thread=thread,
            target=candidate,
            owner_channel_id=result.value.owner_channel_id,
            video=ports["youtube"].video(command.video_id),
            transcript_text="\n".join(
                f"[{format_timestamp(e.get('start'))}] {e.get('text','')}"
                for e in transcript.entries
            ),
            register=measure_comment_register(thread.replies if thread else []),
            retrieval=result.value.retrieval,
        )
        packet = build_reply_packet(
            evidence,
            workflow_template=prompt_resources.load("reply_workflow.md").text,
            final_check_template=prompt_resources.load("reply_final_check.md").text,
            variations=(parse_registers(arguments.registers)
                        if arguments.registers else ()),
            dials=parse_dials(arguments.dial or []),
            maximum_characters=configuration.get("packet_characters"),
        )
        artifacts = _artifact_store(ports, configuration, command.video_id)
        artifacts.stage("reply_packet.md", packet.text)
        _stage_run_record(
            artifacts, kind="reply", video=evidence.video,
            extra={
                "target": candidate.author,
                "target_comment_id": packet.target_comment_id,
                "target_status": candidate.status.value,
                "variations": list(packet.variations),
                "variation_headings": list(packet.headings),
                "packet_characters": len(packet),
                "budget": configuration.get("packet_characters"),
                "retrieval": {
                    "status": result.value.retrieval.status.value,
                    "may_conclude_absence":
                        result.value.retrieval.may_conclude_absence,
                },
            },
        )
        published = artifacts.commit()
        print(
            f"Reply packet written: {len(packet):,} characters\n"
            f"  answering  {candidate.author} ({candidate.status.value})\n"
            f"  target id  {packet.target_comment_id}\n"
            f"  registers  {', '.join(packet.variations)}\n"
            f"  files      {', '.join(published)}\n"
            f"  directory  {getattr(artifacts, 'root', '')}",
            file=stdout,
        )
        copy_to_clipboard(ports, packet.text, stdout)
        return EXIT_SUCCESS

    if as_json:
        print(json.dumps(formatters.candidate_as_dict(candidate), indent=2,
                         ensure_ascii=False), file=stdout)
    else:
        print(formatters.render_target(candidate), file=stdout)
    return EXIT_SUCCESS


def run_packet_window(
    arguments, configuration, api_key, events, stdout, build_ports,
    *, launcher=None, clipboard=None, start_mode: str = "comment",
) -> int:
    """Open the packet window. Needs no video, and does the work itself.

    Every other way into this application resolves a video before anything
    appears, which meant the window could not be opened to look at and
    "nothing is on the clipboard" was a reason to refuse rather than a state
    to show. This opens first and asks after.
    """

    if getattr(arguments, "dry_run", False):
        from ...domain.errors import ConfigurationError

        raise ConfigurationError(
            "--dry-run cannot be combined with --window. Run without "
            "--window to preview the request with no network, files, or "
            "clipboard changes."
        )

    from ..gui import builder
    from ..gui.options import PacketOptionsModel
    from ..gui.packet_window import PacketWindow

    settings_file = _window_settings_path(configuration)
    options = PacketOptionsModel.from_settings(
        _load_window_settings(
            settings_file,
            legacy=_legacy_state_path(configuration, "window_settings.json"),
        )
    )
    apply_window_options(
        options, arguments, configuration, start_mode=start_mode
    )

    factory = build_ports or default_ports
    # Loaded here, not in the window's package: filenames and the output
    # layout are this layer's business, and a window that knew one would be a
    # second place it is defined.
    templates = {
        name: prompt_resources.load(name).text
        for name in ("comment_workflow.md", "comment_final_check.md")
    }

    reply_templates = {
        name: prompt_resources.load(name).text
        for name in ("reply_workflow.md", "reply_final_check.md")
    }
    from ...infrastructure.json_preset_store import JsonPresetStore

    preset_store = JsonPresetStore(
        _private_state_directory(configuration) / "writing_presets.json"
    )

    def ports_for(events, model=None):
        selected_options = model or options
        if build_ports is not None:
            return factory(configuration, api_key, events)
        job = getattr(events, "job", None)
        return factory(
            configuration,
            api_key,
            events,
            cancelled=(lambda: bool(job and job.cancelled)),
            transcribe_locally=selected_options.transcribe_locally,
            whisper_policy=selected_options.whisper_policy,
            transcript_route=selected_options.transcript_route,
            whisper_model=selected_options.whisper_model,
            confirm_transcription=(
                (lambda reason: bool(job and job.confirm(reason)))
                if selected_options.whisper_policy == "ask"
                else None
            ),
        )

    def store_for(video_id, directory):
        return _artifact_store({}, configuration, video_id, directory)

    def build(model, mode, job):
        if mode == "reply":
            return builder.prepare_replies(
                model, job,
                ports_factory=lambda events: ports_for(events, model),
                templates=reply_templates,
                artifacts_for=store_for,
                session_factory=lambda **kwargs: _guided_session_for(
                    **kwargs,
                    history=history_store(configuration),
                    prompt_version=prompt_resources.prompt_version(),
                ),
                scan=_scan_for_window,
                triage_for=lambda candidates, maximum_characters: (
                    build_triage_packet(
                        prompt_resources.load("reply_triage.md").text,
                        candidates,
                        maximum_characters=maximum_characters,
                    )
                ),
                clock=SystemClock(),
            )
        return builder.build_comment(
            model, job,
            ports_factory=lambda events: ports_for(events, model),
            templates=templates,
            artifacts_for=store_for,
            stopwords=word_resources.stopwords(),
            prompt_version=prompt_resources.prompt_version(),
        )

    launch = launcher
    if launch is None:                              # pragma: no cover - real Tk
        from ..gui.packet_window import launch as launch
    def comment_session_for(run):
        """A session over the packet the window just built.

        Comment mode could build a packet and copy it and then had nowhere to
        put the answer, while reply mode saved every accepted draft. Same
        session type, same refusal order, same immediate save.
        """

        from ...application.comment_session import CommentSession

        return CommentSession(
            packet_text=run.text,
            video=dict(run.video),
            registers=tuple(run.packet.variations),
            packet_path=run.packet_path,
            prompt_version=str(
                run.run_record.get("prompt_version") or ""
            ),
            run_id=str(getattr(run.artifacts, "root", "") or ""),
            artifacts=run.artifacts,
            history=history_store(configuration),
            clipboard=clipboard if clipboard is not None else SystemClipboard(),
            events=events,
        )

    window = launch(
        options=options,
        clipboard=clipboard if clipboard is not None else SystemClipboard(),
        build=build,
        mode=start_mode,
        comment_session_factory=comment_session_for,
        preset_store=preset_store,
        open_path=lambda path: desktop.open_path(
            path, editor=configuration.get("editor", "")),
    )
    _save_window_settings(settings_file, getattr(window, "options", options))
    return EXIT_SUCCESS


@dataclass
class WindowScan:
    """What a window's scan found, in the shape the window needs it.

    Assembled here rather than in the gui package: `ThreadScan` carries no
    video record, so somebody has to fetch one, and deciding that is this
    layer's business. The window gets one object and asks it nothing it does
    not have.
    """

    video_id: str = ""
    video: dict[str, Any] = field(default_factory=dict)
    threads: list = field(default_factory=list)
    waiting: list = field(default_factory=list)
    total: int = 0
    owner_channel_id: str = ""
    api_operations_used: int = 0


def _scan_for_window(*, video, handle, max_comments, youtube, events, clock):
    """One scan, built the way every other caller builds it.

    Wrapped rather than called from the gui package directly: the command
    object and its refusals are this layer's business, and a window that
    constructed one would be a second place the reply contract is expressed.
    """

    command = ScanMyThreadsCommand(
        video=video, handle=handle or "", max_comments=max_comments,
    )
    result = scan_threads.handle(
        command, youtube=youtube, events=events, clock=clock or SystemClock(),
    )
    found = result.value
    video_record = youtube.video(command.video_id)
    return WindowScan(
        video_id=command.video_id,
        video=video_record,
        threads=list(found.threads),
        waiting=[c for c in found.candidates if c.outstanding],
        total=len(found.candidates),
        owner_channel_id=found.owner_channel_id,
        api_operations_used=int(
            getattr(youtube, "api_operations_used", 0) or 0
        ),
    )


def _guided_session_for(
    *, found, waiting, transcript, templates, artifacts, events,
    registers, dials, packet_characters, history=None, prompt_version="",
):
    """A guided session over the people a window's scan just found."""

    return GuidedSession(
        targets=list(waiting),
        threads={t.comment_id: t for t in found.threads},
        owner_channel_id=found.owner_channel_id,
        video=found.video,
        transcript_text="\n".join(
            f"[{format_timestamp(entry.get('start'))}] {entry.get('text', '')}"
            for entry in transcript.entries
        ),
        templates=templates,
        variations=tuple(registers),
        dials=dict(dials),
        packet_characters=packet_characters,
        prompt_version=prompt_version,
        run_id=str(getattr(artifacts, "root", "") or ""),
        artifacts=artifacts,
        history=history,
        clipboard=SystemClipboard(),
        events=events,
    )


def run_gui_preview(stdout, *, launcher=None, clipboard=None) -> int:
    """Open the window on invented people, so it can be seen at all.

    The window needs a video the operator commented on, a reply to that
    comment, and no answer from him yet. All three is a rarer state than it
    sounds, and until one exists the window cannot be looked at, let alone
    learned. Everything here is real except the people: the same controller,
    the same state machine, the same prompt templates.
    """

    from ..gui import preview as preview_data
    from ..gui.controllers import GuidedController
    from ..gui.view_models import equivalent_command_for

    session = preview_data.build_session(
        templates={
            f"{name}.md": prompt_resources.load(f"{name}.md").text
            for name in preview_data.TEMPLATE_NAMES
        },
        clipboard=clipboard if clipboard is not None else SystemClipboard(),
    )
    controller = GuidedController(
        session=session,
        equivalent_command=equivalent_command_for(
            "YOUR_VIDEO", handle="yourhandle",
        ),
    )

    print(
        "Preview: the window is opening on two made-up people. Nothing is "
        "fetched, no quota is spent and nothing is written to disk. Copy "
        "packet puts a real packet on your clipboard, built from the real "
        "templates.",
        file=stdout,
    )
    launch = launcher
    if launch is None:                              # pragma: no cover - real Tk
        from ..gui.main_window import launch as launch
    launch(controller, title=preview_data.TITLE)
    print("Preview window closed. Nothing was saved.", file=stdout)
    return EXIT_SUCCESS


def run_gui(
    arguments, configuration, api_key, events, stdout, build_ports
) -> int:
    """Scan, then hand a ready session to the window.

    The scan happens here rather than inside the window. That is what keeps
    the window free of network work and therefore free of the threading and
    cancellation machinery a responsive one would need.
    """

    from ...domain.errors import ConfigurationError

    # Checked before the API key: a preview reaches no network, so demanding
    # a key for it would gate the one path that exists to be ungated.
    if getattr(arguments, "preview", False):
        return run_gui_preview(stdout)

    if not api_key:
        raise ConfigurationError(
            f"No API key was found. Set {' or '.join(API_KEY_VARIABLES)}."
        )

    # Resolved once. The window prints an equivalent command for the operator
    # to reproduce the run with, and building that from arguments.handle alone
    # emitted a command with no --my-handle at all whenever the handle came
    # from a setting — a copyable command that cannot work.
    my_handle = arguments.handle or configuration.get("my_handle", "")
    my_channel = arguments.channel_id or configuration.get("my_channel_id", "")

    command = ScanMyThreadsCommand(
        video=arguments.video,
        channel_id=my_channel,
        handle=my_handle,
        max_comments=configuration.get("max_comments", 500),
    )
    factory = build_ports or default_ports
    ports = factory(configuration, api_key, events)
    result = scan_threads.handle(
        command, youtube=ports["youtube"], events=ports["events"],
        clock=ports.get("clock") or SystemClock(),
    )

    scan = result.value
    outstanding = [c for c in scan.candidates if c.outstanding]
    if not outstanding:
        # Two different situations, and telling the operator the wrong one
        # sends him to fix the wrong thing. No threads at all means he never
        # commented on this video, or the handle is not the one that did;
        # threads with nobody outstanding means he is simply caught up.
        who = f"@{my_handle.lstrip('@')}" if my_handle else my_channel
        if not scan.threads:
            print(
                f"No window opened: {who} has no comments on this video, so "
                "there is nobody to reply to. The window works through people "
                "who replied to *your* comment and have not heard back — it "
                "is not for writing new comments, which is `comment.bat`.\n"
                "  If you did comment here, check the handle: this scan used "
                f"{who}.",
                file=stdout,
            )
        else:
            print(
                f"No window opened: {who} has {len(scan.threads)} thread(s) "
                f"here and {len(scan.candidates)} people in them, none waiting "
                "for an answer. You are caught up on this video.\n"
                "  To see them anyway: ytcomment reply scan-mine --all",
                file=stdout,
            )
        return EXIT_SUCCESS

    transcript = ports["transcripts"].fetch(command.video_id)
    registers = (parse_registers(arguments.registers)
                 if arguments.registers else ())
    dials = parse_dials(arguments.dial or [])

    session = GuidedSession(
        targets=outstanding[:arguments.guided_limit],
        threads={t.comment_id: t for t in scan.threads},
        owner_channel_id=scan.owner_channel_id,
        video=ports["youtube"].video(command.video_id),
        transcript_text="\n".join(
            f"[{format_timestamp(e.get('start'))}] {e.get('text','')}"
            for e in transcript.entries
        ),
        templates={
            name: prompt_resources.load(name).text
            for name in ("reply_workflow.md", "reply_final_check.md")
        },
        variations=registers,
        dials=dials,
        packet_characters=configuration.get("packet_characters"),
        artifacts=_artifact_store(ports, configuration, command.video_id),
        clipboard=ports.get("clipboard") or SystemClipboard(),
        events=ports["events"],
    )

    # Imported here, not at module scope: the CLI must keep working on a
    # machine with no display, and importing tkinter at startup would end
    # that. The import-direction test enforces the same rule structurally.
    from ..gui.controllers import GuidedController
    from ..gui.main_window import launch
    from ..gui.view_models import equivalent_command_for

    controller = GuidedController(
        session=session,
        equivalent_command=equivalent_command_for(
            command.video_id, handle=my_handle,
            registers=registers, dials=dials,
        ),
    )

    # "Open replies" was wired to nothing. It is the primary action in four
    # phases, including every way a run can end, so the last thing the
    # operator did in a finished run was press a button that did nothing.
    def open_review() -> str:
        return desktop.open_path(
            Path(getattr(session.artifacts, "root", ".")) / REVIEW_FILENAME,
            editor=configuration.get("editor", ""),
        )

    # Said before the window blocks. launch() runs a Tk main loop, so the
    # console goes silent until the window is closed; without this the
    # operator sees a scan finish and then nothing, with no way to tell a
    # window that is opening from one that never will.
    print(
        f"Opening the window on {len(session.targets)} of {len(outstanding)} "
        f"people waiting. Nothing is posted; accepted replies are saved to "
        f"{REVIEW_FILENAME} as you go.",
        file=stdout,
    )
    launch(controller, open_review=open_review)
    print("Window closed.", file=stdout)
    return EXIT_SUCCESS


def run_history(arguments, configuration, stdout) -> int:
    store = history_store(configuration)

    if arguments.action == "record":
        from ...domain.ids import extract_video_id

        if arguments.draft_file:
            draft = Path(arguments.draft_file).expanduser().read_text(
                encoding="utf-8"
            )
        else:
            draft = str(arguments.draft or "")
        posted_at = (
            arguments.posted_at
            or datetime.now(timezone.utc).isoformat()
        )
        entry = {
            "event_id": arguments.event_id,
            "video_id": extract_video_id(arguments.video),
            "target": arguments.target,
            "target_comment_id": arguments.target_comment_id,
            "thread_id": arguments.thread_id,
            "workflow": arguments.workflow,
            "run_id": arguments.run_id,
            "draft": draft,
            "posted_at": posted_at,
            "prompt_version": prompt_resources.prompt_version(),
            "registers": (
                list(parse_registers(arguments.registers))
                if arguments.registers else []
            ),
            "source": "native",
        }
        added = store.append([entry])
        print(
            "Recorded as posted." if added
            else "That posting event was already recorded.",
            file=stdout,
        )
        return EXIT_SUCCESS

    if arguments.action == "migrate":
        report = migrate_json(arguments.source, store)
        print(
            f"Migrated {report['records_added']} of "
            f"{report['records_in_source']} records "
            f"({report['records_already_present']} already present).\n"
            f"  source     {report['source']}\n"
            f"  sha256     {report['source_sha256']}\n"
            f"  unchanged  {report['source_unchanged']}  "
            f"(the migration only ever reads it)\n"
            f"  store      {store.path}",
            file=stdout,
        )
        return EXIT_SUCCESS

    if arguments.action == "quarantine":
        moved = store.quarantine()
        print(f"Set aside: {moved}" if moved else "Nothing to quarantine.",
              file=stdout)
        return EXIT_SUCCESS

    rows = store.load()
    if configuration.get("output_format") == "json":
        print(json.dumps(rows, indent=2, ensure_ascii=False), file=stdout)
        return EXIT_SUCCESS

    print(f"{len(rows)} recorded drafts\n", file=stdout)
    for row in rows:
        print(f"  {row['video_id']}  {row.get('target','')}\n"
              f"      {str(row.get('draft',''))[:96]}", file=stdout)
    return EXIT_SUCCESS


def run_scoreboard(
    arguments, configuration, api_key, events, stdout, build_ports
) -> int:
    from ...domain.errors import ConfigurationError
    from ...domain.ids import extract_video_id

    if not api_key:
        raise ConfigurationError(
            f"No API key was found. Set {' or '.join(API_KEY_VARIABLES)}."
        )

    video_id = extract_video_id(arguments.video)
    factory = build_ports or default_ports
    ports = factory(configuration, api_key, events)
    operator_channel_id = (
        arguments.channel_id
        or configuration.get("my_channel_id", "")
    )
    if not operator_channel_id:
        handle = arguments.handle or configuration.get("my_handle", "")
        if handle:
            operator_channel_id = ports["youtube"].channel_id_for_handle(handle)
    if not operator_channel_id:
        raise ConfigurationError(
            "Scoreboard needs your channel identity. Pass --my-channel-id "
            "(preferred) or --my-handle, or configure YTCOMMENT_MY_CHANNEL_ID."
        )

    result = scoreboard.handle(
        video_id,
        history=ports.get("history") or history_store(configuration),
        youtube=ports["youtube"],
        events=ports["events"],
        operator_channel_id=operator_channel_id,
        max_comments=configuration.get("max_comments", 500),
        max_replies_per_thread=configuration.get(
            "max_replies_per_thread", 100
        ),
    )

    text = scoreboard.render(result.value)
    if configuration.get("output_format") == "json":
        print(json.dumps({
            "rows": result.value.rows,
            "counted": result.value.counted,
            "metrics": result.metrics,
        }, indent=2, ensure_ascii=False, default=str), file=stdout)
    else:
        print(text, file=stdout)
    return EXIT_SUCCESS


def run_guided(
    arguments, configuration, command, result, ports, stdout
) -> int:
    """Walk the operator through several people, saving after each one.

    Answers arrive from a file when --answers-from is given and from the
    clipboard otherwise. The file form exists so a whole run can be exercised
    without a display, which is what makes this testable at all.
    """

    from ...domain.errors import ConfigurationError

    scan = result.value
    outstanding = [c for c in scan.candidates if c.outstanding]
    if not outstanding:
        print("Nobody in this scan is waiting for an answer.", file=stdout)
        return EXIT_SUCCESS

    transcript = ports["transcripts"].fetch(command.video_id)
    session = GuidedSession(
        targets=outstanding[:arguments.guided_limit],
        threads={t.comment_id: t for t in scan.threads},
        owner_channel_id=scan.owner_channel_id,
        video=ports["youtube"].video(command.video_id),
        transcript_text="\n".join(
            f"[{format_timestamp(e.get('start'))}] {e.get('text','')}"
            for e in transcript.entries
        ),
        templates={
            name: prompt_resources.load(name).text
            for name in ("reply_workflow.md", "reply_final_check.md")
        },
        variations=(parse_registers(arguments.registers)
                    if arguments.registers else ()),
        dials=parse_dials(arguments.dial or []),
        packet_characters=configuration.get("packet_characters"),
        artifacts=_artifact_store(ports, configuration, command.video_id),
        clipboard=ports.get("clipboard"),
        events=ports["events"],
    )

    answers: list[str] = []
    if arguments.answers_from:
        source = Path(arguments.answers_from).expanduser()
        if not source.is_file():
            raise ConfigurationError(f"No answers file at {source}")
        answers = [
            block.strip()
            for block in source.read_text(encoding="utf-8").split("\n---\n")
            if block.strip()
        ]

    session.start()
    print(f"{len(session.targets)} people to work through.\n", file=stdout)

    index = 0
    while session.next_person() is not None:
        person = session.current
        packet = session.copy_packet()
        print(f"[{session.state.current_index}/{len(session.targets)}] "
              f"{person.author} ({person.status.value})", file=stdout)
        print(f"    {person.reason}", file=stdout)

        if not answers:
            # Without a scripted source there is nothing to read here: the
            # operator drives this from the GUI or supplies --answers-from.
            print("    packet copied to the clipboard; no answer source, "
                  "stopping", file=stdout)
            session.cancel()
            break

        if index >= len(answers):
            print("    no answer left in the file; stopping here and keeping "
                  "what was accepted", file=stdout)
            session.cancel()
            break

        outcome = session.submit(answers[index])
        index += 1
        if outcome.status is OperationStatus.REFUSED:
            print(f"    refused: {session.state.last_error}", file=stdout)
            session.skip_person()
        else:
            print("    accepted and saved", file=stdout)

    if not session.state.phase.terminal:
        session.finish()

    store = session.artifacts
    _stage_run_record(
        store, kind="guided", video=session.video,
        extra={
            "accepted": len(session.accepted),
            "skipped": len(session.skipped),
            "targets_offered": len(session.targets),
            "final_phase": session.state.phase.value,
            "variations": list(session.variations),
            "drafts": [
                {"author": d.author, "comment_id": d.comment_id,
                 "status": d.status, "words": len(d.draft.split())}
                for d in session.accepted
            ],
        },
    )
    store.commit()
    print(
        f"\n{len(session.accepted)} replies ready to review, "
        f"{len(session.skipped)} skipped\n"
        f"  file       {REVIEW_FILENAME}\n"
        f"  directory  {getattr(store, 'root', '')}",
        file=stdout,
    )
    return EXIT_SUCCESS


def _stage_run_record(artifacts, *, kind: str, video: dict, extra: dict) -> None:
    """Every run records what produced it.

    Without this a reply, triage or guided run is a directory of markdown
    with no way to say which prompt version made it or what was asked for —
    which defeats the point of being able to diagnose a run from its
    artifacts alone.
    """

    artifacts.stage("run.json", json.dumps({
        "kind": kind,
        "artifact_contract_version": 2,
        "video_id": str(video.get("video_id", "")),
        "video_title": str(video.get("title", "")),
        "prompt_version": prompt_resources.prompt_version(),
        **extra,
    }, indent=2, ensure_ascii=False))


def _artifact_store(ports, configuration, video_id: str, directory: str = ""):
    """The run's artifact store, injected in tests and built here otherwise.

    ``directory`` lets the window's own output field win over the setting
    without the window having to know how a run directory is named.
    """

    if "artifacts" in ports:
        return ports["artifacts"]
    root = unique_run_root(
        Path(directory or configuration.get("output_directory", "output")),
        video_id,
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
    )
    return FilesystemArtifactStore(root)


def run_comment_build(
    arguments, configuration, api_key, events, stdout, build_ports
) -> int:
    """Parse the packet options, build, and report where the run landed."""

    from ...domain.errors import ConfigurationError

    if not api_key and not arguments.dry_run:
        raise ConfigurationError(
            "No API key was found. Set "
            f"{' or '.join(API_KEY_VARIABLES)}, or run with --dry-run."
        )

    command = BuildCommentPacketCommand(
        video=arguments.video,
        variations=(parse_registers(arguments.registers)
                    if arguments.registers else ()),
        dials=parse_dials(arguments.dial or []),
        max_comments=configuration.get("max_comments", 500),
        max_replies_per_thread=configuration.get(
            "max_replies_per_thread", 100
        ),
        packet_characters=configuration.get("packet_characters"),
        explicit_length=(parse_length(arguments.length)
                         if arguments.length else None),
        allow_no_transcript=arguments.allow_no_transcript,
        dry_run=arguments.dry_run,
    )

    factory = build_ports or default_ports
    ports = factory(configuration, api_key, events)

    if "artifacts" in ports:
        artifacts = ports["artifacts"]
    else:
        # The parsed video_id, not the raw argument. Using the argument meant
        # a URL fell through to a placeholder name, so a run built from a
        # pasted link was called "run_<timestamp>" and could not be found
        # later by the video it was about.
        root = unique_run_root(
            Path(configuration.get("output_directory", "output")),
            command.video_id,
            datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
        )
        artifacts = FilesystemArtifactStore(root)

    templates = {
        name: prompt_resources.load(name).text
        for name in ("comment_workflow.md", "comment_final_check.md")
    }

    result = build_comment_packet.handle(
        command,
        youtube=ports["youtube"],
        transcripts=ports["transcripts"],
        events=ports["events"],
        artifacts=artifacts,
        templates=templates,
        prompt_version=prompt_resources.prompt_version(),
        # Only consulted when there is no transcript, but loaded either way:
        # a lazy load inside the no-transcript branch would make the one path
        # that already failed the only path that can fail again.
        stopwords=word_resources.stopwords(),
    )

    if command.dry_run:
        print(f"Dry run for {command.video}. No API request was sent.",
              file=stdout)
        return EXIT_SUCCESS

    if configuration.get("output_format") == "json":
        print(json.dumps(result.value["run"], indent=2, ensure_ascii=False),
              file=stdout)
        return EXIT_SUCCESS

    packet = result.value["packet"]
    location = getattr(artifacts, "root", "")
    lines = [
        f"Packet written: {len(packet):,} characters",
        f"  registers  {', '.join(packet.variations)}",
        f"  files      {', '.join(result.artifacts)}",
    ]
    if location:
        lines.append(f"  directory  {location}")
    for warning in result.warnings:
        lines.append(f"  warning    {warning.code.value}: {warning.message}")
    print("\n".join(lines), file=stdout)

    if not arguments.no_copy:
        copy_to_clipboard(ports, packet.text, stdout)
    return EXIT_SUCCESS


def main(
    argv: Sequence[str] | None = None,
    *,
    build_ports: Callable[..., dict[str, Any]] | None = None,
    stdout=None,
    stderr=None,
    environment=None,
    settings: dict[str, Any] | None = None,
    clipboard=None,
) -> int:
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    parser = build_parser()
    arguments = parser.parse_args(list(argv) if argv is not None else None)

    if not arguments.group:
        parser.print_help(stdout)
        return EXIT_SUCCESS

    api_key = ""
    try:
        configuration = resolve(
            settings=settings or {},
            config_file=load_config_file(arguments.config),
            environment=environment,
            flags=typed_flags(arguments),
        )
        api_key = resolve_api_key(environment)
        # Configured with the key already known, so nothing can be logged
        # before redaction is in place.
        configure_logging(
            configuration.get("log_level", "WARNING"),
            secrets=[api_key] if api_key else [],
            jsonl=getattr(arguments, "log_jsonl", False),
            stream=stderr,
        )

        events = make_event_sink(
            configuration.get("progress", "auto"),
            stderr,
            verbose=getattr(arguments, "verbose", False),
        )

        # Resolved once, here, so every command that takes a video gets the
        # same fallback and the same refusals. Only reached when the operator
        # left the argument off, so the clipboard is never read otherwise.
        #
        # Except for the window, which is the one thing that must open with
        # nothing at all. Resolving here would refuse before a window existed
        # -- exactly the behaviour that made the window impossible to look at
        # until you already knew what you wanted from it. It has its own
        # clipboard chip and its own empty, editable box.
        # Windows are exempt. The new one opens with nothing and has its own
        # box; the preview needs no video by definition. Only --classic still
        # scans before anything appears, so only --classic still needs one
        # resolved this early.
        opens_a_window = (
            getattr(arguments, "open_window", False)
            or (arguments.group == "gui"
                and not getattr(arguments, "classic", False))
        )
        if opens_a_window:
            pass
        elif hasattr(arguments, "video") and arguments.video is None:
            arguments.video = video_from_clipboard(
                clipboard if clipboard is not None else SystemClipboard(),
                stdout,
            )

        if arguments.group == "doctor":
            return run_doctor(configuration, api_key, stdout)

        if arguments.group == "privacy":
            if arguments.action == "check":
                from .privacy_command import run as run_privacy

                return run_privacy(arguments.root, stdout)
            parser.print_help(stdout)
            return EXIT_SUCCESS

        if arguments.group == "config":
            if arguments.action == "path":
                root = Path(configuration.get("output_directory", "output"))
                print("\n".join([
                    "Where this run reads and writes",
                    "",
                    f"  output directory  {root.resolve()}",
                    f"  private state     "
                    f"{_private_state_directory(configuration).resolve()}",
                    f"  history store     {history_store(configuration).path}",
                    f"  prompt resources  {prompt_resources.PROMPTS}",
                    f"  prompt version    {prompt_resources.prompt_version()}",
                    "",
                    "  The API key is read from the environment and is never "
                    "written to any of these.",
                ]), file=stdout)
                return EXIT_SUCCESS
            source = "environment" if api_key else "not set"
            print(formatters.render_config(configuration, bool(api_key), source),
                  file=stdout)
            return EXIT_SUCCESS

        if arguments.group == "reply":
            return run_reply(arguments, configuration, api_key, events,
                             stdout, build_ports)

        if arguments.group == "words":
            return run_words(arguments, stdout)

        if arguments.group == "compare":
            comparison = compare.compare_files(
                arguments.old_packet, arguments.new_packet
            )
            print(compare.render(comparison), file=stdout)
            # Exit 0 when the packets ask for the same thing in the same
            # words. Blank-line placement is not a finding, and treating it
            # as one would train the operator to ignore the exit code.
            return (EXIT_SUCCESS if comparison.equivalent_instructions
                    else EXIT_ERROR)

        if arguments.group == "gui":
            # One window by default. The old one scanned before anything
            # appeared and offered eleven equal buttons with no options on
            # it; the new one opens with nothing, carries every register and
            # dial, and runs the same reply path. --classic is an escape
            # hatch until the new one has been used in anger.
            if getattr(arguments, "classic", False) or \
                    getattr(arguments, "preview", False):
                return run_gui(arguments, configuration, api_key, events,
                               stdout, build_ports)
            return run_packet_window(
                arguments, configuration, api_key, events, stdout,
                build_ports, start_mode="reply",
            )

        if arguments.group == "run":
            root = Path(configuration.get("output_directory", "output"))
            if arguments.action == "list":
                print(runs.render_list(runs.list_runs(root)), file=stdout)
                return EXIT_SUCCESS
            if arguments.action == "validate":
                summary = runs.validate_run(arguments.run_directory)
                if configuration.get("output_format") == "json":
                    print(json.dumps({
                        "directory": summary.directory,
                        "kind": summary.kind,
                        "ok": summary.ok,
                        "files": list(summary.files),
                        "problems": summary.problems,
                    }, indent=2), file=stdout)
                else:
                    print(runs.render_validation(summary), file=stdout)
                # A broken run is a finding, and a script checking runs needs
                # to branch on it.
                return EXIT_SUCCESS if summary.ok else EXIT_ERROR
            parser.print_help(stdout)
            return EXIT_SUCCESS

        if arguments.group == "history":
            return run_history(arguments, configuration, stdout)

        if arguments.group == "scoreboard" and arguments.action == "build":
            return run_scoreboard(arguments, configuration, api_key, events,
                                  stdout, build_ports)

        if arguments.group == "review" and arguments.action == "show":
            from ...domain.errors import ConfigurationError
            review = Path(arguments.run_directory).expanduser() / REVIEW_FILENAME
            if not review.is_file():
                raise ConfigurationError(f"No review file at {review}")
            print(review.read_text(encoding="utf-8"), file=stdout)
            return EXIT_SUCCESS

        if arguments.group == "comment":
            if arguments.action == "variations":
                print(format_register_listing(), file=stdout)
                return EXIT_SUCCESS
            if arguments.action == "dials":
                print(format_dial_listing(), file=stdout)
                return EXIT_SUCCESS
            if arguments.action == "build":
                runner = (run_packet_window
                          if getattr(arguments, "open_window", False)
                          else run_comment_build)
                return runner(
                    arguments, configuration, api_key, events,
                    stdout, build_ports,
                )
            if arguments.action == "rebuild":
                # No ports and no key: everything it needs is already on disk.
                return run_rebuild(
                    arguments, configuration, stdout,
                    clipboard if clipboard is not None else SystemClipboard(),
                )
            parser.print_help(stdout)
            return EXIT_SUCCESS

        if arguments.group == "video" and arguments.action == "inspect":
            languages = configuration.get("transcript_languages", ("en",))
            command = InspectVideoCommand(
                video=arguments.video,
                max_comments=configuration.get("max_comments", 500),
                include_replies=arguments.include_replies,
                transcript_languages=(
                    tuple(languages) if isinstance(languages, (tuple, list))
                    else (languages,)
                ),
                dry_run=arguments.dry_run,
            )

            if not api_key and not command.dry_run:
                from ...domain.errors import ConfigurationError
                raise ConfigurationError(
                    "No API key was found. Set "
                    f"{' or '.join(API_KEY_VARIABLES)}, or run with --dry-run."
                )

            factory = build_ports or default_ports
            ports = factory(configuration, api_key, events)
            result = inspect_video.handle(
                command,
                youtube=ports["youtube"],
                transcripts=ports["transcripts"],
                events=ports["events"],
            )

            if configuration.get("output_format") == "json":
                print(formatters.render_json(
                    formatters.inspection_as_dict(result)), file=stdout)
            else:
                print(formatters.render_inspection(result), file=stdout)
            return EXIT_SUCCESS

        parser.print_help(stdout)
        return EXIT_SUCCESS

    except OperationCancelled as exc:
        print(f"Cancelled: {exc}", file=stderr)
        return exc.exit_code
    except PacketError as exc:
        # Every failure the application raises carries its own exit code, so
        # the mapping is one line rather than a table that drifts.
        print(redact(str(exc), api_key), file=stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Cancelled.", file=stderr)
        return OperationCancelled.exit_code
    except Exception as exc:                # noqa: BLE001 - last resort
        LOGGER.exception("unhandled error")
        print(redact(f"{type(exc).__name__}: {exc}", api_key), file=stderr)
        return EXIT_ERROR


if __name__ == "__main__":              # pragma: no cover
    raise SystemExit(main())
