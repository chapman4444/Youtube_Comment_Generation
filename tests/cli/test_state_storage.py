from __future__ import annotations

from pathlib import Path

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.interfaces.cli import state_storage


def configuration(tmp_path: Path) -> dict[str, str]:
    return {
        "state_directory": str(tmp_path / "private"),
        "output_directory": str(tmp_path / "legacy-root" / "output"),
    }


@pytest.mark.parametrize(
    "failure",
    [
        PermissionError("permission denied"),
        OSError("disk full"),
        OSError("write failed"),
    ],
)
def test_failed_history_migration_fails_closed(
    tmp_path,
    monkeypatch,
    failure,
):
    settings = configuration(tmp_path)
    legacy = state_storage.legacy_state_path(
        settings, "engagement_history.sqlite3"
    )
    legacy.parent.mkdir(parents=True)
    original = b"legacy history bytes"
    legacy.write_bytes(original)
    destination = (
        state_storage.private_state_directory(settings)
        / "engagement_history.sqlite3"
    )
    monkeypatch.setattr(
        state_storage.shutil,
        "copy2",
        lambda _source, _destination: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(ConfigurationError, match="left unchanged"):
        state_storage.history_store(settings)

    assert legacy.read_bytes() == original
    assert not destination.exists()


def test_destination_directory_failure_does_not_create_replacement(
    tmp_path,
    monkeypatch,
):
    settings = configuration(tmp_path)
    legacy = state_storage.legacy_state_path(
        settings, "engagement_history.sqlite3"
    )
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    destination = (
        state_storage.private_state_directory(settings)
        / "engagement_history.sqlite3"
    )
    real_mkdir = Path.mkdir

    def fail_private(path, *args, **kwargs):
        if path == destination.parent:
            raise PermissionError("directory denied")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_private)

    with pytest.raises(ConfigurationError, match="directory denied"):
        state_storage.history_store(settings)

    assert legacy.read_bytes() == b"legacy"
    assert not destination.exists()


def test_successful_history_migration_preserves_every_byte(tmp_path):
    settings = configuration(tmp_path)
    legacy = state_storage.legacy_state_path(
        settings, "engagement_history.sqlite3"
    )
    legacy.parent.mkdir(parents=True)
    original = b"complete legacy database"
    legacy.write_bytes(original)

    store = state_storage.history_store(settings)

    assert store.path.read_bytes() == original
    assert legacy.read_bytes() == original
