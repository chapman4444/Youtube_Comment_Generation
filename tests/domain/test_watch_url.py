"""The packet has to say which video it is about.

It carried the title, channel, duration, views, likes and comment count, and
not the one fact that identifies the video. A packet is the thing that gets
pasted somewhere else, so a reader of the packet — or of an answer written
from it — had no way back to the source.
"""

from __future__ import annotations

from llm_youtube_comment_generation.domain.video import watch_url

VIDEO = "qru7vjVsJGc"


def test_the_url_is_built_from_the_id():
    assert watch_url(VIDEO) == f"https://www.youtube.com/watch?v={VIDEO}"


def test_a_missing_id_says_unknown_rather_than_building_a_broken_link():
    """A URL ending in nothing looks like a link and goes nowhere."""

    assert watch_url("") == "unknown"
    assert watch_url(None) == "unknown"


def test_nothing_a_third_party_writes_can_ride_into_the_url():
    """The ID is allowlisted first.

    A URL invites a click, and everything else in this region is evidence
    somebody else authored. Characters outside the identifier alphabet are
    dropped rather than escaped, exactly as they are for comment ids.
    """

    assert watch_url("abc def") == "https://www.youtube.com/watch?v=abcdef"
    # Slashes are dropped, so nothing can walk out of the query parameter.
    assert watch_url("../../evil") == "https://www.youtube.com/watch?v=....evil"
    # No second query parameter can be smuggled in: & and = are dropped, so
    # the URL keeps exactly the one parameter this function wrote.
    injected = watch_url("id&list=PL1")
    assert injected == "https://www.youtube.com/watch?v=idlistPL1"
    assert injected.count("?") == 1
    assert "&" not in injected
    assert watch_url("<script>") == "https://www.youtube.com/watch?v=script"


def test_an_id_that_allowlists_down_to_nothing_is_not_a_link():
    assert watch_url("!!!") == "unknown"
