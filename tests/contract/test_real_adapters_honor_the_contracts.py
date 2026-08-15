"""The port contracts, run against the real adapters.

test_port_contracts.py states the shared definition of correct and proves
the fakes satisfy it. This file closes the half its docstring promised and
nothing delivered: the same rules against the shipped adapters, for every
adapter that can be exercised without a network, quota, or a display.

What cannot run here, and why, stated rather than skipped silently:

- YouTubeAdapter and the caption adapters answer over the network, so their
  behaviour rules cannot run in this suite. Their *shape* can: the protocol
  checks below construct them and hold them to their ports, and the
  read-only rule is enforced on the real YouTube adapter's surface.
- SystemClipboard's behaviour would overwrite the operator's actual
  clipboard mid-test, so only its shape is checked.
- SettingsStore has no real adapter yet (the GUI persists its options
  through JsonPresetStore's "Current settings" preset). When one lands it
  belongs in these tables.

The first divergence this file caught was found while writing it: the fake
history store still enforced the fuzzy-text uniqueness the real v2 store
deliberately removed. The agreement test at the bottom exists so the next
divergence fails a build instead of surviving a year.
"""

from __future__ import annotations

import io
import json
import hashlib

import pytest

from fakes import FakeHistoryStore
from llm_youtube_comment_generation.domain.errors import (
    ConfigurationError,
    HistoryCorruptionError,
)
from llm_youtube_comment_generation.infrastructure import (
    filesystem_artifacts as fs_artifacts,
)
from llm_youtube_comment_generation.infrastructure.event_sinks import (
    JsonlEventSink,
    NullEventSink,
    TextEventSink,
)
from llm_youtube_comment_generation.infrastructure.filesystem_artifacts import (
    COMPLETION_MARKER,
    FilesystemArtifactStore,
)
from llm_youtube_comment_generation.infrastructure.memory_artifacts import (
    MemoryArtifactStore,
)
from llm_youtube_comment_generation.infrastructure.sqlite_history import (
    SqliteHistoryStore,
)
from llm_youtube_comment_generation.infrastructure.system_clipboard import (
    SystemClipboard,
)
from llm_youtube_comment_generation.infrastructure.system_clock import (
    SystemClock,
)
from llm_youtube_comment_generation.infrastructure.transcript_api import (
    TranscriptAdapter,
)
from llm_youtube_comment_generation.infrastructure.youtube_api import (
    YouTubeAdapter,
)
from llm_youtube_comment_generation.infrastructure.ytdlp_transcript import (
    YtDlpTranscriptAdapter,
)
from llm_youtube_comment_generation.ports import (
    ArtifactStore,
    ClipboardPort,
    ClockPort,
    EventSink,
    HistoryStore,
    TranscriptPort,
    YouTubePort,
)
from llm_youtube_comment_generation.ports.events import EventKind, ProgressEvent


def real_adapters():
    """Every landed adapter that can be constructed without I/O."""

    return [
        (SystemClock(), ClockPort),
        (SystemClipboard(), ClipboardPort),
        (NullEventSink(), EventSink),
        (TextEventSink(io.StringIO()), EventSink),
        (JsonlEventSink(io.StringIO()), EventSink),
        (MemoryArtifactStore(), ArtifactStore),
        (TranscriptAdapter(), TranscriptPort),
        (YtDlpTranscriptAdapter(), TranscriptPort),
        (YouTubeAdapter("contract-shape-check"), YouTubePort),
    ]


@pytest.mark.parametrize(
    "adapter, port", real_adapters(),
    ids=lambda value: getattr(value, "__name__", type(value).__name__),
)
def test_the_real_adapter_satisfies_its_port(adapter, port):
    """Structural typing is only a promise until something checks it —
    the same rule test_port_contracts.py applies to the fakes."""

    assert isinstance(adapter, port)


def test_the_filesystem_store_satisfies_its_port(tmp_path):
    assert isinstance(FilesystemArtifactStore(tmp_path / "run"), ArtifactStore)


def test_the_sqlite_store_satisfies_its_port(tmp_path):
    assert isinstance(SqliteHistoryStore(tmp_path / "history.db"), HistoryStore)


def test_the_real_youtube_adapter_cannot_post():
    """Read-only is a product decision. The port test proves the interface
    has no way to post; this proves the implementation grew none either."""

    adapter = YouTubeAdapter("contract-shape-check")
    forbidden = [
        name for name in dir(adapter)
        if not name.startswith("_") and any(
            word in name.lower()
            for word in ("post", "insert", "delete", "update", "write",
                         "reply_to")
        )
    ]

    assert forbidden == []


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------


def test_the_system_clock_is_timezone_aware():
    """The reply cutoff compares against aware time; a naive now() raises
    there instead of here."""

    now = SystemClock().now()

    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 0


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


def test_a_real_sink_never_raises_even_on_a_dead_stream():
    """A closed pipe must not take down the run reporting to it."""

    dead = io.StringIO()
    dead.close()

    for sink in (TextEventSink(dead, verbose=True), JsonlEventSink(dead)):
        sink.emit(ProgressEvent(EventKind.STEP, step="x", message="alive?"))
        sink.emit(ProgressEvent(EventKind.PROGRESS, current=1, total=2))


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------


def test_a_missing_sqlite_history_is_simply_an_empty_one(tmp_path):
    assert SqliteHistoryStore(tmp_path / "nowhere.db").load() == []


def test_recording_the_same_draft_twice_adds_one_sqlite_row(tmp_path):
    store = SqliteHistoryStore(tmp_path / "history.db")
    entry = {"video_id": "v1", "draft": "the same reply text",
             "drafted_at": "2026-08-15T00:00:00Z"}

    assert store.append([entry]) == 1
    assert store.append([entry]) == 0
    assert len(store.load()) == 1


def test_an_empty_draft_is_never_recorded_by_sqlite(tmp_path):
    store = SqliteHistoryStore(tmp_path / "history.db")

    assert store.append([{"video_id": "v1", "draft": "   "}]) == 0


def test_an_unreadable_sqlite_history_is_never_written_over(tmp_path):
    """The only irreplaceable state this application owns."""

    path = tmp_path / "history.db"
    path.write_bytes(b"this is not a sqlite database at all")
    store = SqliteHistoryStore(path)

    with pytest.raises(HistoryCorruptionError):
        store.load()
    with pytest.raises(HistoryCorruptionError):
        store.append([{"video_id": "v1", "draft": "something"}])

    assert path.read_bytes() == b"this is not a sqlite database at all"


def test_the_same_corruption_is_quarantined_once_not_twice(tmp_path):
    path = tmp_path / "history.db"
    path.write_bytes(b"garbage")
    store = SqliteHistoryStore(path)

    first = store.quarantine()
    second = store.quarantine()

    assert first == second
    assert not path.exists()


def test_the_fake_and_the_real_history_store_agree_on_identity(tmp_path):
    """The drift detector. The v1 fake deduplicated on normalized text
    after the real store had moved to exact event identity, so the two
    answered "how many of these are new?" differently — the exact
    fake/adapter divergence the harsh-critic review said nothing prevented.
    """

    entries = [
        # The same event twice: one row.
        {"video_id": "v1", "draft": "the same reply text",
         "drafted_at": "2026-08-15T00:00:00Z"},
        {"video_id": "v1", "draft": "the same reply text",
         "drafted_at": "2026-08-15T00:00:00Z"},
        # A light edit: a distinct event, not a duplicate.
        {"video_id": "v1", "draft": "The Same Reply Text!",
         "drafted_at": "2026-08-15T00:00:00Z"},
        # A supplied event id wins over content.
        {"video_id": "v1", "draft": "unrelated", "event_id": "e-1"},
        {"video_id": "v2", "draft": "also unrelated", "event_id": "e-1"},
        # An empty draft is nobody's event.
        {"video_id": "v1", "draft": "   "},
    ]

    real = SqliteHistoryStore(tmp_path / "history.db")
    fake = FakeHistoryStore()

    real_counts = [real.append([entry]) for entry in entries]
    fake_counts = [fake.append([entry]) for entry in entries]

    assert real_counts == fake_counts == [1, 0, 1, 1, 0, 0]
    assert len(real.load()) == len(fake.load()) == 3


# --------------------------------------------------------------------------
# Artifacts
# --------------------------------------------------------------------------


def test_staged_files_are_not_visible_on_disk_until_commit(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "run")
    store.stage("packet.md", "content")

    assert store.committed_names() == ()
    assert not (tmp_path / "run").exists()

    assert store.commit() == ("packet.md",)
    assert store.read("packet.md") == "content"


def test_the_committed_set_carries_a_completion_record_that_validates(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "run")
    store.stage("packet.md", "the packet")
    store.stage("report.md", "the report")
    store.commit()

    record = json.loads(
        (tmp_path / "run" / COMPLETION_MARKER).read_text(encoding="utf-8")
    )

    assert record["files"]["packet.md"] == hashlib.sha256(
        b"the packet").hexdigest()
    assert record["files"]["report.md"] == hashlib.sha256(
        b"the report").hexdigest()


def test_rollback_discards_staged_work_only(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "run")
    store.stage("packet.md", "committed")
    store.commit()
    store.stage("scratch.md", "discarded")

    store.rollback()

    assert store.read("packet.md") == "committed"
    assert not (tmp_path / "run" / "scratch.md").exists()


def test_reading_an_absent_artifact_raises(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "run")
    store.stage("packet.md", "x")
    store.commit()

    with pytest.raises(FileNotFoundError):
        store.read("nothing.md")


def test_a_failed_commit_leaves_the_previous_output_intact(
    tmp_path, monkeypatch,
):
    """The rule the fake proves with fail_on_commit, proved on the real
    store by making the underlying write fail partway through the set."""

    store = FilesystemArtifactStore(tmp_path / "run")
    store.stage("packet.md", "first run")
    store.commit()

    store.stage("packet.md", "second run")
    store.stage("report.md", "second run")

    real_write = fs_artifacts.atomic_write

    def failing_write(path, text):
        if path.name == "report.md":
            raise OSError("disk full, allegedly")
        real_write(path, text)

    monkeypatch.setattr(fs_artifacts, "atomic_write", failing_write)

    with pytest.raises(OSError):
        store.commit()

    assert store.read("packet.md") == "first run"
    record = json.loads(
        (tmp_path / "run" / COMPLETION_MARKER).read_text(encoding="utf-8")
    )
    assert record["files"]["packet.md"] == hashlib.sha256(
        b"first run").hexdigest()


def test_the_real_store_refuses_a_directory_it_does_not_own(tmp_path):
    """The operator's own files are never collateral."""

    root = tmp_path / "run"
    root.mkdir()
    (root / "family_photo.jpg").write_bytes(b"not ours")
    store = FilesystemArtifactStore(root)
    store.stage("packet.md", "x")

    with pytest.raises(ConfigurationError, match="did not write"):
        store.commit()

    assert (root / "family_photo.jpg").read_bytes() == b"not ours"
