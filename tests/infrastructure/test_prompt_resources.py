"""The prompt migration, asserted byte for byte.

The prompt text is the operator's own writing and is the product. These tests
exist so that a change to it cannot happen quietly.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re

import pytest

from llm_youtube_comment_generation.domain.errors import ConfigurationError
from llm_youtube_comment_generation.infrastructure import prompt_resources
from llm_youtube_comment_generation.infrastructure.prompt_resources import (
    CHECKSUMS,
    MANIFEST,
    PROMPTS,
    PromptResource,
    load,
    prompt_version,
)

TEMPLATES = [
    "comment_workflow.md", "comment_final_check.md",
    "reply_workflow.md", "reply_final_check.md", "reply_triage.md",
]


@pytest.fixture(autouse=True)
def clear_prompt_resource_caches_after_each_test():
    yield
    prompt_resources.load.cache_clear()
    prompt_resources._manifest.cache_clear()
    prompt_resources._checksums.cache_clear()


@pytest.fixture(scope="module")
def recorded():
    return json.loads(CHECKSUMS.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", TEMPLATES)
def test_the_text_matches_its_recorded_checksum(name, recorded):
    """Byte for byte. No normalising of whitespace, line endings or Unicode.

    The prompt text is the product. This is what makes an edit to it an
    explicit act with a record, rather than something that can happen quietly.
    """

    raw = (PROMPTS / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == recorded[name]["sha256"]


@pytest.mark.parametrize("name", TEMPLATES)
def test_a_template_that_no_longer_matches_the_legacy_text_says_so(
    name, recorded
):
    """Divergence from the migrated bytes is allowed, but never silent.

    The migration checksum is the proof that the operator's prompt came out of
    the legacy module unchanged. An authorised edit on top of it does not make
    that false, so the record keeps both and requires a reason for the gap.
    Without this, re-recording a checksum would erase the evidence.
    """

    entry = recorded[name]
    diverged = "migrated_sha256" in entry

    if not diverged:
        assert "changed" not in entry, (
            f"{name} records a change but no migrated checksum"
        )
        return

    assert entry["migrated_sha256"] != entry["sha256"]
    assert entry.get("changed"), f"{name} diverged with no reason recorded"


@pytest.mark.parametrize("name", TEMPLATES)
def test_every_template_is_valid_utf8_with_no_bom(name):
    raw = (PROMPTS / name).read_bytes()

    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8", errors="strict")
    assert "�" not in text


@pytest.mark.parametrize("name", TEMPLATES)
def test_the_recorded_character_count_still_holds(name, recorded):
    text = (PROMPTS / name).read_text(encoding="utf-8")

    assert len(text) == recorded[name]["characters"]


def test_every_template_is_declared_in_the_manifest():
    declared = set(json.loads(MANIFEST.read_text(encoding="utf-8")))
    present = {path.name for path in PROMPTS.glob("*.md")}

    assert present <= declared, f"undeclared prompt files: {present - declared}"


@pytest.mark.parametrize("name", TEMPLATES)
def test_placeholders_are_declared_rather_than_discovered(name):
    """The loader refuses anything it was not told about.

    An undeclared placeholder means the renderer does not know to fill it,
    and the failure would show up as a literal brace in a packet pasted into
    a model.
    """

    resource = load(name)
    present = set(re.findall(r"\{([a-z_]+)\}", resource.text))

    assert present <= resource.placeholders


def test_loading_an_undeclared_resource_refuses():
    with pytest.raises(ConfigurationError, match="not declared"):
        load("no_such_prompt.md")


def test_filling_an_undeclared_placeholder_refuses():
    resource = load("comment_final_check.md")

    with pytest.raises(ConfigurationError, match="does not declare"):
        resource.fill({"not_a_placeholder": "x"})


def test_filling_leaves_no_declared_placeholder_behind():
    resource = load("comment_final_check.md")

    filled = resource.fill({
        "check_count": "five", "check_substance": "x", "check_waiver": "",
        "structure_check": "x", "critique_check": "x",
        "final_check": "x", "option_checks": "",
    })

    assert resource.unfilled(filled) == []


def test_a_partially_filled_template_reports_what_is_missing():
    resource = load("comment_final_check.md")

    filled = resource.fill({"check_count": "five"})

    assert set(resource.unfilled(filled)) == {
        "check_substance", "check_waiver", "structure_check",
        "critique_check", "final_check", "option_checks",
    }


def test_filling_does_not_use_str_format():
    """The prompt text contains literal braces in its own examples.

    str.format would either raise on them or consume them silently, and the
    damage would be invisible until a model read the result.
    """

    resource = PromptResource(
        name="t.md", text="keep {this} and fill {check_count}",
        placeholders=frozenset({"check_count"}), sha256="",
    )

    assert resource.fill({"check_count": "five"}) == "keep {this} and fill five"


def test_the_prompt_version_is_derived_not_hand_maintained():
    """A hand-maintained version number is one somebody forgets to bump."""

    version = prompt_version()

    assert len(version) == 12
    assert version == prompt_version()          # stable across calls


def test_the_comment_template_declares_resolved_structural_contracts():
    """Optional sections are inserted only after option resolution."""

    workflow = load("comment_workflow.md").text

    assert "{grounding_contract}" in workflow
    assert "{critique_contract}" in workflow
    assert "{final_contract}" in workflow
    assert "### Harsh critique" not in workflow


def test_comment_templates_reject_duplicate_angles_and_wrapped_urls():
    workflow = load("comment_workflow.md").text
    final_check = load("comment_final_check.md").text
    compact = " ".join(workflow.split())

    assert "No more than two variations may make substantially the same" in compact
    assert "does not create a new inference" in compact
    assert "Do not wrap it in Markdown link syntax" in workflow
    assert "Diversity:" in final_check
    assert "exactly one plain" in final_check


def _temporary_prompt_set(monkeypatch, tmp_path, raw: bytes, *, checksum=True):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "sample.md").write_bytes(raw)
    (prompts / "manifest.json").write_text(
        json.dumps({"sample.md": {"placeholders": []}}),
        encoding="utf-8",
    )
    checksums = {}
    if checksum:
        checksums["sample.md"] = {
            "sha256": hashlib.sha256(b"expected bytes").hexdigest()
        }
    (prompts / "checksums.json").write_text(
        json.dumps(checksums), encoding="utf-8"
    )
    monkeypatch.setattr(prompt_resources, "PROMPTS", prompts)
    monkeypatch.setattr(prompt_resources, "MANIFEST", prompts / "manifest.json")
    monkeypatch.setattr(prompt_resources, "CHECKSUMS", prompts / "checksums.json")
    prompt_resources.load.cache_clear()
    prompt_resources._manifest.cache_clear()
    prompt_resources._checksums.cache_clear()


def test_runtime_loader_refuses_changed_prompt_bytes(monkeypatch, tmp_path):
    _temporary_prompt_set(monkeypatch, tmp_path, b"changed bytes")

    with pytest.raises(ConfigurationError, match="expected.*actual"):
        prompt_resources.load("sample.md")


def test_runtime_loader_requires_a_checksum_entry(monkeypatch, tmp_path):
    _temporary_prompt_set(
        monkeypatch, tmp_path, b"expected bytes", checksum=False
    )

    with pytest.raises(ConfigurationError, match="no recorded checksum"):
        prompt_resources.load("sample.md")


def test_runtime_loader_reports_invalid_utf8(monkeypatch, tmp_path):
    _temporary_prompt_set(monkeypatch, tmp_path, b"\xff")

    with pytest.raises(ConfigurationError, match="not valid UTF-8"):
        prompt_resources.load("sample.md")
