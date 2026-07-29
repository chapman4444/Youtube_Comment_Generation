"""A window that can be opened before there is anything to open it on.

The window needs a video the operator commented on, a reply to that comment,
and no answer from him yet. All three at once is rarer than it sounds: two
real runs on a video he had never commented on both ended in a correct refusal
and no window, which is why he had still never seen it.

No test here opens a window. The launcher is injected.
"""

from __future__ import annotations

import io

import pytest

from llm_youtube_comment_generation.domain.workflow import Intent, Phase
from llm_youtube_comment_generation.infrastructure.memory_artifacts import (
    MemoryArtifactStore,
)
from llm_youtube_comment_generation.interfaces.cli.main import run_gui_preview
from llm_youtube_comment_generation.interfaces.gui import preview


def templates() -> dict[str, str]:
    """The real prompt files. The gui package does not read them itself —
    tests/gui/test_gui_boundaries.py enforces that, and caught this module
    getting it wrong."""

    from llm_youtube_comment_generation.infrastructure import prompt_resources

    return {
        f"{name}.md": prompt_resources.load(f"{name}.md").text
        for name in preview.TEMPLATE_NAMES
    }


class FakeClipboard:
    def __init__(self) -> None:
        self.value = ""

    def read(self) -> str:
        return self.value

    def write(self, text: str) -> None:
        self.value = text


@pytest.fixture
def launched():
    """Records what would have been launched, and launches nothing."""

    calls: list[tuple] = []
    return calls, lambda controller, **kwargs: calls.append((controller, kwargs))


# -- it opens without anything real ----------------------------------------


def test_the_preview_needs_no_api_key(launched):
    """Everything else in this command refuses without one, correctly. This
    reaches no network, so demanding a key would gate the one path that
    exists to be ungated."""

    calls, launcher = launched
    stdout = io.StringIO()

    assert run_gui_preview(stdout, launcher=launcher,
                           clipboard=FakeClipboard()) == 0
    assert len(calls) == 1


def test_the_window_says_it_is_a_preview(launched):
    calls, launcher = launched

    run_gui_preview(io.StringIO(), launcher=launcher, clipboard=FakeClipboard())

    assert "PREVIEW" in calls[0][1]["title"]
    assert "nothing is fetched or saved" in calls[0][1]["title"].lower()


def test_it_says_what_it_is_before_and_after(launched):
    _, launcher = launched
    stdout = io.StringIO()

    run_gui_preview(stdout, launcher=launcher, clipboard=FakeClipboard())
    printed = stdout.getvalue()

    assert "made-up people" in printed
    assert "no quota is spent" in printed
    assert "Nothing was saved" in printed


# -- and it is genuinely inert ---------------------------------------------


def test_nothing_is_written_to_disk():
    session = preview.build_session(templates(), clipboard=FakeClipboard())

    assert isinstance(session.artifacts, MemoryArtifactStore)


def test_the_sample_people_say_they_are_samples():
    """A preview that looked like real evidence would be the same mistake
    this project refuses to make everywhere else."""

    assert "made-up" in preview.OWNER_COMMENT["text"]
    assert "preview" in preview.VIDEO["title"].lower()
    for reply in preview.REPLIES:
        assert reply["text"].lower().startswith("sample reply")


def test_the_queue_has_more_than_one_person():
    """One person never shows what "next person" does."""

    session = preview.build_session(templates(), clipboard=FakeClipboard())

    assert len(session.targets) == 2


# -- the workflow really runs on it ----------------------------------------


def test_a_whole_run_works_on_the_invented_queue():
    """The same controller and the same state machine as a real run."""

    from llm_youtube_comment_generation.interfaces.gui.controllers import (
        GuidedController,
    )

    clipboard = FakeClipboard()
    session = preview.build_session(templates(), clipboard=clipboard)
    controller = GuidedController(session=session)

    controller.submit(Intent.START)
    controller.submit(Intent.NEXT_PERSON)
    controller.submit(Intent.COPY_CURRENT_PACKET)

    assert "### Hardened final" in clipboard.read(), "no real packet was built"

    clipboard.write("### Hardened final\nthe reply I would send\n")
    controller.submit(Intent.SUBMIT_PERSON_ANSWER)
    view = controller.submit(Intent.SAVE)

    assert view.phase is Phase.COMPLETE
    assert len(session.accepted) == 1


# -- the in-memory store keeps the real contract ---------------------------


def test_staged_files_are_invisible_until_committed():
    store = MemoryArtifactStore()
    store.stage("packet.md", "text")

    assert store.committed_names() == ()

    assert store.commit() == ("packet.md",)
    assert store.read("packet.md") == "text"


def test_rollback_discards_the_staged_set():
    store = MemoryArtifactStore()
    store.stage("packet.md", "text")
    store.rollback()

    assert store.commit() == ()
    assert store.committed_names() == ()


def test_reading_something_never_committed_is_an_error():
    with pytest.raises(KeyError):
        MemoryArtifactStore().read("absent.md")
