"""Structured release evidence shared by the recorder and archive validator."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

# 2 adds source_provenance. Source identity proves the manifest equals the
# local checkout; it never said which commit that checkout was, so evidence
# could describe a tree that existed on one machine and nowhere else and
# still validate. Recording the commit is what turns "matches a checkout"
# into "matches this commit".
SCHEMA_VERSION = 2
SHA1 = re.compile(r"^[0-9a-f]{40}$")
RECORDER = "tools/record_release_verification.py"
STRUCTURED_EVIDENCE_NAME = "RELEASE_VERIFICATION.json"
HUMAN_EVIDENCE_NAME = "RELEASE_VERIFICATION.md"
REQUIRED_GATES = (
    "Python 3.10 Windows matrix",
    "Python 3.11 Windows matrix",
    "Python 3.12 Windows matrix",
    "Two-run determinism",
    "Clean-wheel installation",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def clean_install_payload(output: str) -> Mapping[str, Any]:
    """Return the final JSON object emitted by the clean-install gate."""

    starts = [index for index, character in enumerate(output) if character == "{"]
    decoder = json.JSONDecoder()
    for start in reversed(starts):
        try:
            payload, _end = decoder.raw_decode(output[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "wheel_sha256" in payload:
            return payload
    raise ValueError("clean-install output has no complete artifact record")


def validate_release_record(
    record: Mapping[str, Any],
    manifest_digest: str,
) -> None:
    """Reject incomplete, contradictory, or stale structured evidence."""

    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported release evidence schema")
    if record.get("recorder") != RECORDER:
        raise ValueError("release evidence has an unknown recorder")
    if record.get("manifest_sha256") != manifest_digest:
        raise ValueError("release evidence does not match the current manifest")
    if record.get("source_tree_mode") != "manifest-reconstructed":
        raise ValueError("release gates did not use a manifest-reconstructed tree")
    if record.get("overall_result") != "PASSED":
        raise ValueError("release evidence does not record an overall pass")

    provenance = record.get("source_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("release evidence names no source commit")
    if not provenance.get("available"):
        raise ValueError("release evidence could not determine its commit")
    if not SHA1.fullmatch(str(provenance.get("commit") or "")):
        raise ValueError("release evidence has an invalid commit id")
    if provenance.get("status_porcelain"):
        raise ValueError("release gates ran against an unclean working tree")
    if provenance.get("release_inputs_differ_from_head"):
        raise ValueError("release inputs differ from the recorded commit")
    if not provenance.get("matches_head"):
        raise ValueError("release evidence does not match its recorded commit")

    for identity_name in ("initial_source_identity", "final_source_identity"):
        identity = record.get(identity_name)
        if not isinstance(identity, dict):
            raise ValueError(f"missing {identity_name}")
        if identity.get("status") != "PASS" or identity.get("problems") != []:
            raise ValueError(f"{identity_name} is contradictory or failed")

    gates = record.get("gates")
    if not isinstance(gates, list):
        raise ValueError("release evidence gates are missing")
    names = [gate.get("name") for gate in gates if isinstance(gate, dict)]
    if names != list(REQUIRED_GATES) or len(set(names)) != len(names):
        raise ValueError("release evidence gates are missing, duplicated, or unknown")
    for gate in gates:
        if not isinstance(gate, dict):
            raise ValueError("release evidence contains an invalid gate")
        if gate.get("status") != "PASS":
            raise ValueError(f"{gate.get('name')} does not record PASS")
        if gate.get("returncode") != 0:
            raise ValueError(f"{gate.get('name')} has a nonzero PASS exit code")
        commands = gate.get("commands")
        if (
            not isinstance(commands, list)
            or not commands
            or not all(isinstance(command, str) and command for command in commands)
        ):
            raise ValueError(f"{gate.get('name')} has incomplete commands")
        output = gate.get("output")
        if not isinstance(output, str) or not output:
            raise ValueError(f"{gate.get('name')} has truncated output")
        if gate.get("output_sha256") != hashlib.sha256(
            output.encode("utf-8")
        ).hexdigest():
            raise ValueError(f"{gate.get('name')} output digest does not match")

    artifacts = record.get("distribution_artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("distribution artifact evidence is missing")
    for name_key, digest_key, suffix in (
        ("wheel", "wheel_sha256", ".whl"),
        ("sdist", "sdist_sha256", ".tar.gz"),
    ):
        name = artifacts.get(name_key)
        digest = artifacts.get(digest_key)
        if not isinstance(name, str) or not name.endswith(suffix):
            raise ValueError(f"invalid recorded {name_key} name")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise ValueError(f"invalid recorded {name_key} SHA-256")

    clean_gate = next(
        gate for gate in gates if gate["name"] == "Clean-wheel installation"
    )
    emitted = clean_install_payload(clean_gate["output"])
    for key in ("wheel", "wheel_sha256", "sdist", "sdist_sha256"):
        if emitted.get(key) != artifacts.get(key):
            raise ValueError(f"recorded {key} contradicts clean-install output")


def render_release_report(record: Mapping[str, Any]) -> str:
    """Render the complete human-readable report from structured evidence."""

    lines = [
        "# Release verification",
        "",
        f"- Overall result: **{record['overall_result']}**",
        f"- Generated: `{record['generated']}`",
        f"- Manifest SHA-256: `{record['manifest_sha256']}`",
        f"- Review archive: `{record['review_archive']}`",
        "- Source tree mode: `manifest-reconstructed`",
        "- Source path override: `PYTHONPATH=<manifest-root>/src`",
        "",
        "These release gates executed only against a disposable source tree "
        "reconstructed from the review archive manifest.",
        "",
    ]
    provenance = record.get("source_provenance") or {}
    lines.extend([
        "## Source provenance",
        "",
        f"- Commit: `{provenance.get('commit') or 'unknown'}`",
        f"- Branch: `{provenance.get('branch') or 'unknown'}`",
        "- Working tree: "
        + (
            "clean"
            if not provenance.get("status_porcelain")
            else "**not clean**"
        ),
        "- Release inputs differing from that commit: "
        + str(len(provenance.get("release_inputs_differ_from_head") or [])),
        "",
        "Source identity below proves the manifest equals the checkout that "
        "was measured. This section names which commit that checkout was, so "
        "the archive can be tied to the repository without repeating the "
        "comparison by hand.",
        "",
    ])
    for key, title in (
        ("initial_source_identity", "Initial source identity"),
        ("final_source_identity", "Final source identity"),
    ):
        identity = record[key]
        if key == "final_source_identity":
            continue
        lines.extend([
            f"## {title}: {identity['status']}",
            "",
            "```text",
            "\n".join(identity["problems"]) if identity["problems"] else (
                "The checkout release-input set exactly matched the manifest."
            ),
            "```",
            "",
        ])
    for gate in record["gates"]:
        lines.extend([
            f"## {gate['name']}: {gate['status']}",
            "",
            f"Exit code: `{gate['returncode']}`",
            "",
            "Commands:",
            "",
        ])
        lines.extend(f"- `{command}`" for command in gate["commands"])
        lines.extend([
            "",
            "```text",
            gate["output"],
            "```",
            "",
        ])
    final_identity = record["final_source_identity"]
    lines.extend([
        f"## Final source identity: {final_identity['status']}",
        "",
        "```text",
        "\n".join(final_identity["problems"]) if final_identity["problems"] else (
            "The checkout release-input set still exactly matched the manifest."
        ),
        "```",
        "",
        "## Distribution artifacts",
        "",
    ])
    # A failing run has no artifacts to name: the clean-wheel gate builds them
    # and only runs once every earlier gate has passed. Indexing them
    # unconditionally meant the recorder died with KeyError while writing the
    # report, so the one run that most needed a written explanation produced a
    # traceback instead and left the reason recoverable only from the JSON.
    artifacts = record["distribution_artifacts"]
    named = ("wheel", "wheel_sha256", "sdist", "sdist_sha256")
    if all(key in artifacts for key in named):
        lines.extend([
            f"- Wheel: `{artifacts['wheel']}`",
            f"- Wheel SHA-256: `{artifacts['wheel_sha256']}`",
            f"- Source distribution: `{artifacts['sdist']}`",
            f"- Source distribution SHA-256: `{artifacts['sdist_sha256']}`",
            "",
        ])
    else:
        lines.extend([
            "None recorded. The clean-wheel installation gate builds and "
            "hashes the distribution, and it runs only after every earlier "
            "gate has passed, so an incomplete run names no artifacts.",
            "",
            "This absence is itself a failure signal and must not be read as "
            "a distribution that was verified and left unnamed.",
            "",
        ])
    return "\n".join(lines)


def load_and_validate_release_evidence(
    root: Path,
    manifest_digest: str,
) -> Mapping[str, Any] | None:
    """Load both evidence forms and require exact semantic agreement."""

    structured = root / STRUCTURED_EVIDENCE_NAME
    human = root / HUMAN_EVIDENCE_NAME
    if not structured.is_file() and not human.is_file():
        return None
    if not structured.is_file() or not human.is_file():
        raise ValueError("release evidence is incomplete")
    try:
        record = json.loads(structured.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("structured release evidence is invalid") from exc
    if not isinstance(record, dict):
        raise ValueError("structured release evidence must be an object")
    validate_release_record(record, manifest_digest)
    expected = render_release_report(record)
    actual = human.read_text(encoding="utf-8")
    if actual != expected:
        raise ValueError(
            "human release report does not exactly match structured evidence"
        )
    return record
