"""Record release gates against the exact source identity in a review ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

try:
    from tools.release_evidence_format import (
        STRUCTURED_EVIDENCE_NAME,
        clean_install_payload,
        render_release_report,
    )
except ModuleNotFoundError:
    from release_evidence_format import (
        STRUCTURED_EVIDENCE_NAME,
        clean_install_payload,
        render_release_report,
    )

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = (
    ROOT / "review_packages" / "Youtube_Comment_Generation_review.zip"
)
DEFAULT_REPORT = ROOT / "review_packages" / "RELEASE_VERIFICATION.md"
DEFAULT_STRUCTURED_REPORT = (
    ROOT / "review_packages" / STRUCTURED_EVIDENCE_NAME
)
MANIFEST_NAME = "REVIEW_FILE_MANIFEST.sha256"
EXCLUDED_TOP_LEVEL_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "env",
    "output",
    "models",
    "review_packages",
    "local_notes",
    "ab_compare",
    "previous_runs",
}
EXCLUDED_DIRECTORY_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
}
EXCLUDED_TOP_LEVEL_FILES = {
    "posted_history.json",
    "engagement_history.sqlite3",
    "replies_to_review.md",
    "comment_drafts.md",
    "youtube_packet_settings.json",
    "window_settings.json",
    "settings.json",
    "writing_presets.json",
    "BUILD_DESIGN_REQUEST_FOR_CLAUDE.md",
    "CHANGES_MADE.md",
    "FILES_CHANGED.txt",
    "HANDOFF.md",
    "OTHER_COMPUTER_FIX.txt",
    "PHASES.md",
    "REMAINING_UNVERIFIED.md",
    "TEST_RESULTS_AFTER.txt",
    "launcher_fix_for_other_computer.zip",
    "cmd_dump.ahk",
}


@dataclass(frozen=True)
class GateResult:
    name: str
    commands: tuple[str, ...]
    returncode: int
    output: str


def load_archive_manifest(
    archive: Path,
) -> tuple[str, dict[str, str]]:
    """Read and validate the portable source manifest from a review ZIP."""

    with zipfile.ZipFile(archive) as package:
        body = package.read(MANIFEST_NAME)
    text = body.decode("utf-8")
    entries: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        digest, separator, relative = line.partition("  ")
        if (
            separator != "  "
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not relative
            or relative in entries
        ):
            raise ValueError(
                f"invalid {MANIFEST_NAME} line {line_number}: {line!r}"
            )
        entries[relative] = digest
    if not entries:
        raise ValueError(f"{MANIFEST_NAME} is empty")
    return hashlib.sha256(body).hexdigest(), entries


def compare_checkout(
    root: Path,
    entries: dict[str, str],
) -> tuple[str, ...]:
    """Prove equality between the manifest and checkout release inputs."""

    problems: list[str] = []
    for relative, expected in entries.items():
        path = root / Path(relative)
        if not path.is_file():
            problems.append(f"missing: {relative}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(f"mismatched: {relative}")
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in release_input_files(root)
    }
    extra = sorted(actual_paths - set(entries))
    problems.extend(f"unmanifested: {relative}" for relative in extra)
    return tuple(problems)


def release_input_files(root: Path) -> tuple[Path, ...]:
    """Enumerate every checkout file capable of influencing release gates."""

    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = relative.parts
        if not parts:
            continue
        if parts[0] in EXCLUDED_TOP_LEVEL_DIRECTORIES:
            continue
        if relative.as_posix() in EXCLUDED_TOP_LEVEL_FILES:
            continue
        if any(
            part in EXCLUDED_DIRECTORY_NAMES or part.endswith(".egg-info")
            for part in parts[:-1]
        ):
            continue
        if path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        files.append(path)
    return tuple(
        sorted(files, key=lambda item: item.relative_to(root).as_posix().casefold())
    )


def reconstruct_manifest_tree(
    root: Path,
    destination: Path,
    entries: dict[str, str],
) -> None:
    """Create a disposable tree containing only manifested source inputs."""

    destination.mkdir(parents=True)
    for relative, expected in entries.items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"unsafe manifest path: {relative}")
        source = root / relative_path
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"copied manifest file changed: {relative}")
    manifest_body = "".join(
        f"{digest}  {relative}\n" for relative, digest in entries.items()
    )
    (destination / MANIFEST_NAME).write_text(
        manifest_body, encoding="utf-8", newline="\n"
    )


def _redact(text: str) -> str:
    result = text
    for private, replacement in (
        (ROOT, "<project-root>"),
        (Path.home(), "<user-home>"),
    ):
        parts = [
            re.escape(part)
            for part in re.split(r"[\\/]+", str(private))
            if part
        ]
        pattern = re.compile(r"[\\/]+".join(parts), re.IGNORECASE)
        result = pattern.sub(replacement, result)
    return result.replace("\\", "/").strip()


def _display(command: Sequence[str]) -> str:
    return _redact(subprocess.list2cmdline(command))


def run_commands(
    name: str,
    python: Path,
    commands: Sequence[Sequence[str]],
    *,
    environment: dict[str, str],
    cwd: Path,
) -> GateResult:
    """Run one release gate group and retain its commands and output."""

    displays: list[str] = []
    output: list[str] = []
    returncode = 0
    for arguments in commands:
        command = [str(python), *arguments]
        display = _display(command)
        displays.append(display)
        output.append(f"$ {display}")
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        output.append(_redact(completed.stdout))
        output.append(f"[exit code {completed.returncode}]")
        if completed.returncode:
            returncode = completed.returncode
            break
    return GateResult(
        name=name,
        commands=tuple(displays),
        returncode=returncode,
        output="\n".join(output).strip(),
    )


def python_gate_commands(expected: str) -> tuple[tuple[str, ...], ...]:
    """The checks run for every supported Python version."""

    version_check = (
        "-c",
        (
            "import sys; "
            f"assert sys.version_info[:2] == ({expected.replace('.', ', ')}), "
            "sys.version"
        ),
    )
    commands = (
        version_check,
        ("-m", "pip", "check"),
        ("-m", "ruff", "check", "src", "tests", "tools"),
        ("tools/privacy_audit.py", "--manifest", MANIFEST_NAME),
        ("-m", "pytest", "-q"),
        ("-c", "import youtube_transcript_api, yt_dlp"),
    )
    if expected == "3.12":
        return commands + (("-c", "import faster_whisper"),)
    return commands


def write_reports(
    path: Path,
    structured_path: Path,
    *,
    manifest_digest: str,
    archive: Path,
    gates: Sequence[GateResult],
    initial_problems: Sequence[str],
    final_problems: Sequence[str],
) -> None:
    """Write matching machine-verifiable and human-readable evidence."""

    passed = (
        not initial_problems
        and not final_problems
        and all(gate.returncode == 0 for gate in gates)
    )
    gate_rows = [
        {
            "name": gate.name,
            "commands": list(gate.commands),
            "returncode": gate.returncode,
            "status": "PASS" if gate.returncode == 0 else "FAIL",
            "output": gate.output or "(no output)",
            "output_sha256": hashlib.sha256(
                (gate.output or "(no output)").encode("utf-8")
            ).hexdigest(),
        }
        for gate in gates
    ]
    artifacts: dict[str, str] = {}
    clean_gate = next(
        (gate for gate in gate_rows if gate["name"] == "Clean-wheel installation"),
        None,
    )
    if clean_gate is not None:
        try:
            payload = clean_install_payload(clean_gate["output"])
        except ValueError:
            payload = {}
        if "wheel_sha256" in payload:
            artifacts = {
                key: payload[key]
                for key in ("wheel", "wheel_sha256", "sdist", "sdist_sha256")
            }
    record = {
        "schema_version": 1,
        "recorder": "tools/record_release_verification.py",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "manifest_sha256": manifest_digest,
        "review_archive": archive.name,
        "source_tree_mode": "manifest-reconstructed",
        "overall_result": "PASSED" if passed else "FAILED",
        "initial_source_identity": {
            "status": "PASS" if not initial_problems else "FAIL",
            "problems": list(initial_problems),
        },
        "gates": gate_rows,
        "final_source_identity": {
            "status": "PASS" if not final_problems else "FAIL",
            "problems": list(final_problems),
        },
        "distribution_artifacts": artifacts,
    }
    structured_path.parent.mkdir(parents=True, exist_ok=True)
    structured_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_release_report(record), encoding="utf-8", newline="\n"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run and record release gates against a review ZIP manifest."
        )
    )
    parser.add_argument("--review-zip", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--structured-report",
        type=Path,
        default=DEFAULT_STRUCTURED_REPORT,
    )
    parser.add_argument("--python310", type=Path, required=True)
    parser.add_argument("--python311", type=Path, required=True)
    parser.add_argument("--python312", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_digest, entries = load_archive_manifest(args.review_zip)
    initial_problems = compare_checkout(ROOT, entries)
    gates: list[GateResult] = []
    if not initial_problems:
        with tempfile.TemporaryDirectory(
            prefix="ytcomment-release-source-"
        ) as raw:
            gate_root = Path(raw) / "source"
            reconstruct_manifest_tree(ROOT, gate_root, entries)
            environment = os.environ.copy()
            environment.pop("PYTHONHOME", None)
            environment["PYTHONPATH"] = str(gate_root / "src")
            environment["PIP_CONSTRAINT"] = str(
                gate_root / "constraints" / "review.txt"
            )
            for version, python in (
                ("3.10", args.python310),
                ("3.11", args.python311),
                ("3.12", args.python312),
            ):
                gates.append(
                    run_commands(
                        f"Python {version} Windows matrix",
                        python,
                        python_gate_commands(version),
                        environment=environment,
                        cwd=gate_root,
                    )
                )
            if all(gate.returncode == 0 for gate in gates):
                gates.append(
                    run_commands(
                        "Two-run determinism",
                        args.python312,
                        (("tools/verify_two_runs.py",),),
                        environment=environment,
                        cwd=gate_root,
                    )
                )
            if all(gate.returncode == 0 for gate in gates):
                gates.append(
                    run_commands(
                        "Clean-wheel installation",
                        args.python312,
                        (("tools/verify_clean_install.py",),),
                        environment=environment,
                        cwd=gate_root,
                    )
                )

    final_problems = compare_checkout(ROOT, entries)
    write_reports(
        args.report,
        args.structured_report,
        manifest_digest=manifest_digest,
        archive=args.review_zip,
        gates=gates,
        initial_problems=initial_problems,
        final_problems=final_problems,
    )
    passed = (
        not initial_problems
        and not final_problems
        and len(gates) == 5
        and all(gate.returncode == 0 for gate in gates)
    )
    print(f"Release verification: {'PASS' if passed else 'FAIL'}")
    print(f"Manifest SHA-256: {manifest_digest}")
    print(f"Report: {args.report}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
