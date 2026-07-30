from llm_youtube_comment_generation.application.privacy import (
    audit_files,
    render_findings,
)
import codecs

import pytest


def test_private_state_and_personal_notes_are_findings(tmp_path):
    (tmp_path / "window_settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "HANDOFF.md").write_text("notes", encoding="utf-8")

    findings = audit_files(
        tmp_path, ["window_settings.json", "HANDOFF.md"]
    )

    assert {finding.kind for finding in findings} == {
        "private state file", "personal project note",
    }


def test_everything_under_local_notes_is_a_finding(tmp_path):
    note = tmp_path / "local_notes" / "legacy" / "idea.md"
    note.parent.mkdir(parents=True)
    note.write_text("private planning", encoding="utf-8")

    findings = audit_files(tmp_path, ["local_notes/legacy/idea.md"])

    assert len(findings) == 1
    assert findings[0].kind == "personal project note"


def test_api_key_and_user_home_are_reported_without_echoing_the_key(tmp_path):
    key = "AIza" + "A" * 35
    home = "C:" + "\\Users\\" + "Operator\\notes"
    (tmp_path / "bad.txt").write_text(
        f"{key}\n{home}\n",
        encoding="utf-8",
    )

    findings = audit_files(tmp_path, ["bad.txt"])
    rendered = render_findings(findings)

    assert "YouTube API key" in rendered
    assert "Windows user directory" in rendered
    assert key not in rendered


def test_clean_publishable_files_pass(tmp_path):
    (tmp_path / "README.md").write_text(
        "Use C:\\Users\\<user> as the placeholder.",
        encoding="utf-8",
    )

    assert audit_files(tmp_path, ["README.md"]) == ()


@pytest.mark.parametrize(
    "encoding,bom",
    [
        ("utf-8", b""),
        ("utf-8", codecs.BOM_UTF8),
        ("utf-16-le", codecs.BOM_UTF16_LE),
        ("utf-16-be", codecs.BOM_UTF16_BE),
    ],
)
def test_common_windows_text_encodings_are_scanned(tmp_path, encoding, bom):
    key = "AIza" + "B" * 35
    path = tmp_path / "candidate.md"
    path.write_bytes(bom + key.encode(encoding))

    findings = audit_files(tmp_path, [path.name])

    assert any(finding.kind == "YouTube API key" for finding in findings)


def test_malformed_text_fails_closed_without_echoing_bytes(tmp_path):
    path = tmp_path / "broken.md"
    path.write_bytes(b"\xff\xfe\x00\xd8")

    findings = audit_files(tmp_path, [path.name])
    rendered = render_findings(findings)

    assert any(finding.kind == "unscannable text file" for finding in findings)
    assert "\\xff" not in rendered


def test_read_failure_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "unreadable.md"
    path.write_text("safe", encoding="utf-8")
    original = type(path).read_bytes

    def refuse(candidate):
        if candidate == path:
            raise OSError("synthetic refusal")
        return original(candidate)

    monkeypatch.setattr(type(path), "read_bytes", refuse)

    findings = audit_files(tmp_path, [path.name])

    assert any(finding.kind == "unscannable text file" for finding in findings)


def test_channel_ids_and_credential_urls_are_private(tmp_path):
    channel = "UC" + "C" * 22
    password = "synthetic-password"
    proxy = "socks5://" + f"operator:{password}@" + "proxy.example:1080"
    path = tmp_path / "notes.txt"
    path.write_text(
        f"{channel}\n{proxy}\n",
        encoding="utf-8",
    )

    findings = audit_files(tmp_path, [path.name])
    rendered = render_findings(findings)

    assert "YouTube channel ID" in rendered
    assert "credential-bearing URL" in rendered
    assert channel not in rendered
    assert password not in rendered


def test_documented_placeholders_are_allowed(tmp_path):
    path = tmp_path / "README.md"
    path.write_text(
        "Use UC<channel-id>, AIza<api-key>, and "
        "C:\\Users\\<user>\\project.",
        encoding="utf-8",
    )

    assert audit_files(tmp_path, [path.name]) == ()
