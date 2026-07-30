from __future__ import annotations

import argparse
import json
from io import StringIO

from llm_youtube_comment_generation.application.configuration import resolve
from llm_youtube_comment_generation.application.runs import validate_run
from llm_youtube_comment_generation.domain import packets
from llm_youtube_comment_generation.interfaces.cli.main import run_rebuild


class Clipboard:
    def __init__(self) -> None:
        self.text = ""

    def read(self) -> str:
        return self.text

    def write(self, text: str) -> None:
        self.text = text


def comment(comment_id, text, *, likes, replies, published):
    return {
        "comment_id": comment_id,
        "author": f"author-{comment_id}",
        "text": text,
        "like_count": likes,
        "total_reply_count": replies,
        "published_at": published,
    }


def source_run(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    comments = [
        comment("liked", "most liked", likes=100, replies=0,
                published="2026-01-01T00:00:00Z"),
        comment("replied", "most replied", likes=4, replies=20,
                published="2026-01-02T00:00:00Z"),
        comment("relevant", "most relevant", likes=1, replies=0,
                published="2026-01-03T00:00:00Z"),
        comment("recent", "most recent", likes=0, replies=0,
                published="2026-07-30T00:00:00Z"),
    ]
    evidence = {
        "schema_version": 2,
        "video": {
            "video_id": "gC-J7zwYMAM",
            "title": "Offline rebuild test",
            "description": "A deliberately ordered fixture.",
        },
        "comments": comments,
        "replies": [],
        "relevance_comments": [
            comments[2], comments[0], comments[1], comments[3],
        ],
        "recent_comments": [
            comments[3], comments[2], comments[1], comments[0],
        ],
    }
    record = {
        "kind": "comment",
        "artifact_contract_version": 2,
        "evidence_schema_version": 2,
        "video_id": "gC-J7zwYMAM",
        "video_title": "Offline rebuild test",
        "prompt_version": "source-version",
        "variations": [],
        "variation_headings": [],
        "dials": {},
        "packet_characters": 0,
        "budget": 280_000,
        "allocation": {
            "comment_body": 1_600,
            "reply_body": 1_000,
            "transcript": 0,
            "transcript_reduced": False,
        },
        "retrieval": {
            "status": "complete",
            "may_conclude_absence": True,
            "retrieved": len(comments),
            "reported_total": len(comments),
            "notes": [],
        },
        "transcript": {
            "availability": "available",
            "language": "en",
            "entries": 1,
            "source": "published-captions",
            "detail": "",
        },
        "counts": {"comments": len(comments), "replies": 0},
        "api_operations_used": 0,
        "warnings": [],
    }
    (source / "evidence.json").write_text(
        json.dumps(evidence), encoding="utf-8"
    )
    (source / "run.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    (source / "transcript_timestamped.txt").write_text(
        "[00:00:00] transcript words\n", encoding="utf-8"
    )
    return source


def arguments(source, *, registers=None):
    return argparse.Namespace(
        run=str(source),
        registers=registers,
        dial=None,
        length=None,
        allow_no_transcript=False,
        no_copy=True,
    )


def rebuild(tmp_path, source, *, registers=None):
    output = tmp_path / "rebuilt"
    configuration = resolve(settings={
        "output_directory": str(output),
        "packet_characters": 280_000,
    })
    code = run_rebuild(
        arguments(source, registers=registers),
        configuration,
        StringIO(),
        Clipboard(),
    )
    directories = sorted(path for path in output.iterdir() if path.is_dir())
    return code, directories[-1]


def test_unchanged_rebuild_preserves_ranked_inputs_and_validates(
    tmp_path, monkeypatch,
):
    source = source_run(tmp_path)
    calls = []
    real_select = packets.select_packet_sections

    def capture(relevance, recent, comments, replies):
        selection = real_select(relevance, recent, comments, replies)
        calls.append({
            "relevance": [item["comment_id"] for item in relevance],
            "recent": [item["comment_id"] for item in recent],
            "selected": {
                "liked": [item["comment_id"] for item in selection.most_liked],
                "replied": [
                    item["comment_id"] for item in selection.most_replied
                ],
                "relevant": [
                    item["comment_id"] for item in selection.relevant
                ],
                "recent": [item["comment_id"] for item in selection.recent],
            },
        })
        return selection

    monkeypatch.setattr(packets, "select_packet_sections", capture)
    first_code, first = rebuild(tmp_path, source)
    second_code, second = rebuild(tmp_path, source)

    assert first_code == second_code == 0
    assert calls[0] == calls[1]
    assert calls[0]["relevance"] == [
        "relevant", "liked", "replied", "recent",
    ]
    assert calls[0]["recent"] == [
        "recent", "relevant", "replied", "liked",
    ]
    assert (first / "packet.md").read_text(encoding="utf-8") == (
        second / "packet.md"
    ).read_text(encoding="utf-8")
    assert validate_run(first).ok
    assert validate_run(second).ok
    assert validate_run(first).kind == "rebuild"
    for name in (
        "packet.md",
        "run.json",
        "report.md",
        "evidence.json",
        "transcript_timestamped.txt",
        ".artifacts-complete.json",
    ):
        assert (first / name).is_file()


def test_changed_options_reuse_the_same_ranked_evidence(
    tmp_path, monkeypatch,
):
    source = source_run(tmp_path)
    selected = []
    real_select = packets.select_packet_sections

    def capture(relevance, recent, comments, replies):
        selection = real_select(relevance, recent, comments, replies)
        selected.append({
            "relevant": [
                item["comment_id"] for item in selection.relevant
            ],
            "recent": [item["comment_id"] for item in selection.recent],
            "liked": [item["comment_id"] for item in selection.most_liked],
            "replied": [
                item["comment_id"] for item in selection.most_replied
            ],
        })
        return selection

    monkeypatch.setattr(packets, "select_packet_sections", capture)
    _, default_run = rebuild(tmp_path, source)
    _, changed_run = rebuild(tmp_path, source, registers="dry_joke")

    assert selected[0] == selected[1]
    assert (default_run / "evidence.json").read_text(encoding="utf-8") == (
        changed_run / "evidence.json"
    ).read_text(encoding="utf-8")
    assert (default_run / "packet.md").read_text(encoding="utf-8") != (
        changed_run / "packet.md"
    ).read_text(encoding="utf-8")
    assert validate_run(default_run).ok
    assert validate_run(changed_run).ok


def test_legacy_evidence_is_refused_instead_of_reordered(tmp_path):
    source = source_run(tmp_path)
    evidence_path = source / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence.pop("relevance_comments")
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    configuration = resolve(settings={
        "output_directory": str(tmp_path / "rebuilt"),
        "packet_characters": 280_000,
    })

    from llm_youtube_comment_generation.domain.errors import ConfigurationError
    import pytest

    with pytest.raises(ConfigurationError, match="exact offline rebuild"):
        run_rebuild(
            arguments(source),
            configuration,
            StringIO(),
            Clipboard(),
        )
