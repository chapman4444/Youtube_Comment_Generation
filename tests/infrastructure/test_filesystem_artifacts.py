"""Staged, atomic artifact commit on a real filesystem.

A half-written output set is worse than none: the operator cannot tell which
half is stale.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
from pathlib import Path

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.infrastructure.filesystem_artifacts import (
    COMPLETION_MARKER,
    FilesystemArtifactStore,
    atomic_write,
    unique_run_root,
)


def test_nothing_is_visible_until_commit(tmp_path):
    store = FilesystemArtifactStore(tmp_path / "run")
    store.stage("packet.md", "content")

    assert not (tmp_path / "run" / "packet.md").exists()

    assert store.commit() == ("packet.md",)
    assert store.read("packet.md") == "content"
    assert (tmp_path / "run" / COMPLETION_MARKER).is_file()


def test_rollback_leaves_the_previous_output_intact(tmp_path):
    root = tmp_path / "run"
    store = FilesystemArtifactStore(root)
    store.stage("packet.md", "first run")
    store.commit()

    second = FilesystemArtifactStore(root)
    second.stage("packet.md", "second run")
    second.rollback()

    assert (root / "packet.md").read_text(encoding="utf-8") == "first run"


def test_a_failed_commit_restores_what_was_there_before(tmp_path, monkeypatch):
    root = tmp_path / "run"
    first = FilesystemArtifactStore(root)
    first.stage("packet.md", "first run")
    first.stage("report.md", "first report")
    first.commit()

    second = FilesystemArtifactStore(root)
    second.stage("packet.md", "second run")
    second.stage("report.md", "second report")

    real_write = atomic_write
    calls = {"n": 0}

    def failing_write(path, text):
        calls["n"] += 1
        if calls["n"] == 2:                 # fail partway through the set
            raise OSError("disk full")
        return real_write(path, text)

    monkeypatch.setattr(
        "llm_youtube_comment_generation.infrastructure."
        "filesystem_artifacts.atomic_write",
        failing_write,
    )

    with pytest.raises(OSError):
        second.commit()

    assert (root / "packet.md").read_text(encoding="utf-8") == "first run"
    assert (root / "report.md").read_text(encoding="utf-8") == "first report"
    assert (root / COMPLETION_MARKER).is_file()


def test_a_new_run_is_promoted_only_after_every_file_is_ready(
    tmp_path, monkeypatch,
):
    root = tmp_path / "run"
    store = FilesystemArtifactStore(root)
    store.stage("packet.md", "packet")
    store.stage("report.md", "report")

    real_write = atomic_write

    def failing_write(path, text):
        if path.name == "report.md":
            raise OSError("interrupted")
        return real_write(path, text)

    monkeypatch.setattr(
        "llm_youtube_comment_generation.infrastructure."
        "filesystem_artifacts.atomic_write",
        failing_write,
    )

    with pytest.raises(OSError, match="interrupted"):
        store.commit()

    assert not root.exists()
    assert list(tmp_path.glob(".run.publishing.*")) == []


def test_a_failed_restore_preserves_and_reports_the_backup(
    tmp_path, monkeypatch,
):
    root = tmp_path / "run"
    first = FilesystemArtifactStore(root)
    first.stage("packet.md", "first")
    first.stage("report.md", "first report")
    first.commit()

    second = FilesystemArtifactStore(root)
    second.stage("packet.md", "second")
    second.stage("report.md", "second report")
    real_write = atomic_write
    calls = {"count": 0}

    def failing_write(path, text):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("publication failed")
        return real_write(path, text)

    monkeypatch.setattr(
        "llm_youtube_comment_generation.infrastructure."
        "filesystem_artifacts.atomic_write",
        failing_write,
    )
    monkeypatch.setattr(
        FilesystemArtifactStore,
        "_restore",
        lambda self, backup: (_ for _ in ()).throw(
            OSError("restoration failed")
        ),
    )

    with pytest.raises(ConfigurationError, match="backup was preserved") as exc:
        second.commit()

    backup_path = str(exc.value).split("preserved at ", 1)[1].split(
        ". Publication error", 1
    )[0]
    assert Path(backup_path).is_dir()


def test_atomic_write_leaves_no_partial_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "out.md"

    def exploding_replace(source, destination):
        raise OSError("no")

    monkeypatch.setattr("os.replace", exploding_replace)

    with pytest.raises(OSError):
        atomic_write(target, "content")

    assert not target.exists()
    assert list(tmp_path.glob(".*partial")) == []


def test_atomic_write_replaces_existing_content(tmp_path):
    target = tmp_path / "out.md"
    atomic_write(target, "first")
    atomic_write(target, "second")

    assert target.read_text(encoding="utf-8") == "second"


def test_a_directory_holding_foreign_files_is_refused(tmp_path):
    """Explaining where somebody's files went is more expensive than refusing."""

    root = tmp_path / "run"
    root.mkdir()
    (root / "holiday.jpg").write_bytes(b"not ours")

    store = FilesystemArtifactStore(root)
    store.stage("packet.md", "content")

    with pytest.raises(ConfigurationError, match="did not write"):
        store.commit()

    assert (root / "holiday.jpg").exists()


def test_our_own_artifacts_may_be_replaced(tmp_path):
    root = tmp_path / "run"
    first = FilesystemArtifactStore(root)
    first.stage("packet.md", "first")
    first.commit()

    second = FilesystemArtifactStore(root)
    second.stage("packet.md", "second")

    assert second.commit() == ("packet.md",)
    assert second.read("packet.md") == "second"


def test_a_run_root_never_collides(tmp_path):
    """The second run of a video is usually the one made after noticing
    something wrong with the first."""

    first = unique_run_root(tmp_path, "gC-J7zwYMAM", "20260727-120000")
    second = unique_run_root(tmp_path, "gC-J7zwYMAM", "20260727-120000")

    assert first != second
    assert first.is_dir()
    assert second.is_dir()


def _allocate_and_publish(base, barrier, results, content):
    barrier.wait()
    root = unique_run_root(
        Path(base), "gC-J7zwYMAM", "20260727-120000"
    )
    store = FilesystemArtifactStore(root)
    store.stage("packet.md", content)
    store.commit()
    results.put(str(root))


def test_two_processes_publish_to_distinct_reserved_roots(tmp_path):
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_allocate_and_publish,
            args=(str(tmp_path), barrier, results, content),
        )
        for content in ("first process", "second process")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0

    roots = [Path(results.get(timeout=2)) for _ in processes]
    assert len(set(roots)) == 2
    contents = {
        (root / "packet.md").read_text(encoding="utf-8")
        for root in roots
    }
    assert contents == {"first process", "second process"}
    for root in roots:
        marker = json.loads(
            (root / COMPLETION_MARKER).read_text(encoding="utf-8")
        )
        digest = hashlib.sha256((root / "packet.md").read_bytes()).hexdigest()
        assert marker == {"version": 1, "files": {"packet.md": digest}}


def test_artifact_names_must_be_plain(tmp_path):
    """A name with a path in it would escape the run directory."""

    store = FilesystemArtifactStore(tmp_path)

    for bad in ("../escape.md", "sub/dir.md"):
        with pytest.raises(ConfigurationError, match="plain"):
            store.stage(bad, "x")


def test_files_are_written_with_unix_newlines(tmp_path):
    """A packet is pasted into a web form; stray carriage returns travel."""

    store = FilesystemArtifactStore(tmp_path / "run")
    store.stage("packet.md", "line one\nline two\n")
    store.commit()

    raw = (tmp_path / "run" / "packet.md").read_bytes()
    assert b"\r\n" not in raw


def test_unicode_punctuation_and_emoji_are_written_as_utf8(tmp_path):
    text = "BAM’s response preserved the evidence. 😄\n"
    store = FilesystemArtifactStore(tmp_path / "run")
    store.stage("comment_drafts.md", text)

    store.commit()

    raw = (tmp_path / "run" / "comment_drafts.md").read_bytes()
    assert raw == text.encode("utf-8")
    assert raw.decode("utf-8") == text


def test_a_later_commit_keeps_the_manifest_cumulative(tmp_path):
    """The GUI saves a draft into the same store after the build commits.
    Rebuilding the marker from the staged set alone shrank it to one file,
    after which packet.md was no longer digest-certified at all."""

    from llm_youtube_comment_generation.infrastructure.filesystem_artifacts \
        import COMPLETION_MARKER, FilesystemArtifactStore

    store = FilesystemArtifactStore(tmp_path / "run")
    store.stage("packet.md", "the packet")
    store.stage("run.json", "{}")
    store.commit()

    store.stage("comment_drafts.md", "the saved draft")
    store.commit()

    marker = json.loads(
        (tmp_path / "run" / COMPLETION_MARKER).read_text(encoding="utf-8"))

    assert set(marker["files"]) == {
        "packet.md", "run.json", "comment_drafts.md"}
    assert marker["files"]["packet.md"] == hashlib.sha256(
        b"the packet").hexdigest()
