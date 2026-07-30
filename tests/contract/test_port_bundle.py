from llm_youtube_comment_generation.ports.bundle import PortBundle


class Port:
    pass


def test_typed_bundle_keeps_mapping_compatibility():
    youtube = transcripts = clipboard = events = Port()
    bundle = PortBundle(
        youtube=youtube,
        transcripts=transcripts,
        clipboard=clipboard,
        events=events,
        extras={"history": "history"},
    )

    assert bundle.youtube is youtube
    assert bundle["youtube"] is youtube
    assert bundle.get("history") == "history"
    assert set(bundle) == {
        "youtube", "transcripts", "clipboard", "events", "history",
    }
