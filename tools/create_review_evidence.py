"""Create verification evidence that is bound to a staged review snapshot."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_NAME = "REVIEW_VERIFICATION.md"
MANIFEST_NAME = "REVIEW_FILE_MANIFEST.sha256"
EXCLUDED_NAMES = {EVIDENCE_NAME, MANIFEST_NAME}
VERSIONED_DISTRIBUTIONS = (
    "llm-youtube-comment-generation",
    "pytest",
    "ruff",
    "requests",
    "youtube-transcript-api",
    "yt-dlp",
    "faster-whisper",
)
MATERIAL_ENVIRONMENT_KEYS = (
    "PYTHONPATH",
    "PYTEST_ADDOPTS",
    "PYTHONWARNINGS",
)


@dataclass(frozen=True)
class GateResult:
    name: str
    command: str
    returncode: int
    output: str


def snapshot_files(root: Path) -> tuple[Path, ...]:
    """Return the exact regular files covered by the review manifest."""

    return tuple(
        sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.name not in EXCLUDED_NAMES
                and ".git" not in path.relative_to(root).parts
            ),
            key=lambda path: path.relative_to(root).as_posix().casefold(),
        )
    )


def write_manifest(root: Path, files: tuple[Path, ...]) -> str:
    """Write a portable SHA-256 manifest and return its own digest."""

    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(root).as_posix()
        lines.append(f"{digest}  {relative}")
    body = "\n".join(lines) + "\n"
    (root / MANIFEST_NAME).write_text(body, encoding="utf-8", newline="\n")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def snapshot_hashes(
    root: Path,
    files: tuple[Path, ...] | None = None,
) -> dict[str, str]:
    selected = files if files is not None else snapshot_files(root)
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in selected
    }


def compare_final_tree(
    root: Path,
    expected: Mapping[str, str],
) -> tuple[str, ...]:
    """Prove the gated regular files and directory tree did not drift."""

    current_files = snapshot_files(root)
    current = snapshot_hashes(root, current_files)
    problems: list[str] = []
    added = sorted(set(current) - set(expected))
    missing = sorted(set(expected) - set(current))
    modified = sorted(
        path for path in set(expected) & set(current)
        if expected[path] != current[path]
    )
    if added:
        problems.append(f"added files: {added[:10]}")
    if missing:
        problems.append(f"missing files: {missing[:10]}")
    if modified:
        problems.append(f"modified files: {modified[:10]}")

    required_directories: set[str] = set()
    for relative in expected:
        parent = Path(relative).parent
        while parent != Path("."):
            required_directories.add(parent.as_posix())
            parent = parent.parent
    actual_directories = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir()
        and ".git" not in path.relative_to(root).parts
    }
    unexpected_directories = sorted(
        actual_directories - required_directories
    )
    if unexpected_directories:
        problems.append(
            f"unexpected directories: {unexpected_directories[:10]}"
        )
    return tuple(problems)


def _redact(text: str, root: Path) -> str:
    replacements = {
        str(root): "<review-root>",
        str(Path.home()): "<user-home>",
    }
    redacted = text
    for private, replacement in replacements.items():
        redacted = redacted.replace(private, replacement)
        redacted = redacted.replace(private.replace("\\", "/"), replacement)
    return redacted.replace("\\", "/").strip()


def verification_provenance(
    root: Path,
    environment: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    """The bounded execution facts needed to reproduce the recorded gates."""

    rows: list[tuple[str, str]] = [
        ("Python executable", Path(sys.executable).name),
        ("Working directory", "<review-root>"),
    ]
    for name in MATERIAL_ENVIRONMENT_KEYS:
        if name in environment:
            rows.append((name, _redact(environment[name], root)))
    for distribution in VERSIONED_DISTRIBUTIONS:
        try:
            version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            version = "not installed"
        rows.append((distribution, version))
    return tuple(rows)


def platform_label() -> str:
    """Describe the platform without launching an operating-system command."""

    if sys.platform == "win32":
        version = sys.getwindowsversion()
        return f"Windows {version.major}.{version.minor}.{version.build}"
    if hasattr(os, "uname"):
        version = os.uname()
        return f"{version.sysname} {version.release}"
    return sys.platform


def run_gate(
    name: str,
    command: list[str],
    display_command: str,
    *,
    root: Path,
    environment: dict[str, str],
) -> GateResult:
    completed = subprocess.run(
        command,
        cwd=root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return GateResult(
        name=name,
        command=display_command,
        returncode=completed.returncode,
        output=_redact(completed.stdout, root),
    )


def write_evidence(
    root: Path,
    *,
    files: tuple[Path, ...],
    manifest_digest: str,
    gates: tuple[GateResult, ...],
    total_bytes: int | None = None,
    provenance: tuple[tuple[str, str], ...] = (),
) -> None:
    source_bytes = (
        sum(path.stat().st_size for path in files)
        if total_bytes is None
        else total_bytes
    )
    overall = "PASSED" if all(gate.returncode == 0 for gate in gates) else "FAILED"
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Review snapshot verification",
        "",
        f"- Overall result: **{overall}**",
        f"- Generated: `{created}`",
        (
            f"- Python: `{sys.version_info.major}.{sys.version_info.minor}."
            f"{sys.version_info.micro}`"
        ),
        f"- Platform: `{platform_label()}`",
        f"- Manifested source files: `{len(files)}`",
        f"- Manifested source bytes: `{source_bytes}`",
        f"- Manifest SHA-256: `{manifest_digest}`",
        "",
        "## Evidence layers",
        "",
        "1. **Snapshot materials:** source, tests, documentation, launchers, "
        "and gate definitions show what this archive contains. Test source "
        "is not a test result.",
        "2. **Recorded staged verification:** the commands and results below "
        "were recorded while building the manifested staged snapshot. They "
        "are not an independent reviewer rerun.",
        "3. **Separate release gates:** multi-version CI, two-run "
        "determinism, and clean-wheel installation require their own "
        "execution evidence for this exact source identity. This snapshot "
        "explicitly does not claim those results.",
        "",
        "## Execution provenance",
        "",
    ]
    lines.extend(
        f"- {name}: `{value}`" for name, value in provenance
    )
    lines.extend([
        "",
        "The commands below ran against this staged source snapshot before it "
        "was archived. A nonzero result prevents the review ZIP from being "
        "created. In particular, clean-wheel installation is a separate "
        "release gate and is not claimed by this artifact.",
        "",
    ])
    for gate in gates:
        status = "PASS" if gate.returncode == 0 else "FAIL"
        lines.extend(
            [
                f"## {gate.name}: {status}",
                "",
                f"Command: `{gate.command}`",
                f"Exit code: `{gate.returncode}`",
                "",
                "```text",
                gate.output or "(no output)",
                "```",
                "",
            ]
        )
    (root / EVIDENCE_NAME).write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )


def remove_generated_test_artifacts(root: Path) -> None:
    """Remove only caches created after the staged manifest was written."""

    cache_directories = [
        path
        for path in root.rglob("*")
        if path.is_dir()
        and path.name in {"__pycache__", ".pytest_cache", ".ruff_cache"}
    ]
    for path in sorted(cache_directories, key=lambda item: len(item.parts), reverse=True):
        shutil.rmtree(path)
    for pattern in ("*.pyc", "*.pyo"):
        for path in root.rglob(pattern):
            path.unlink()
    for name in ("output",):
        path = root / name
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def main() -> int:
    files = snapshot_files(ROOT)
    initial_hashes = snapshot_hashes(ROOT, files)
    initial_bytes = sum(path.stat().st_size for path in files)
    manifest_digest = write_manifest(ROOT, files)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    provenance = verification_provenance(ROOT, environment)
    gates = (
        run_gate(
            "Privacy audit",
            [sys.executable, "tools/privacy_audit.py"],
            "python tools/privacy_audit.py",
            root=ROOT,
            environment=environment,
        ),
        run_gate(
            "Failure-class source checks",
            [sys.executable, "-m", "ruff", "check", "src", "tests", "tools"],
            "python -m ruff check src tests tools",
            root=ROOT,
            environment=environment,
        ),
        run_gate(
            "Full automated test suite",
            [sys.executable, "-m", "pytest", "-q"],
            "python -m pytest -q",
            root=ROOT,
            environment=environment,
        ),
    )
    remove_generated_test_artifacts(ROOT)
    drift = compare_final_tree(ROOT, initial_hashes)
    integrity = GateResult(
        name="Final staged-tree identity",
        command="compare final paths and SHA-256 hashes to initial manifest",
        returncode=1 if drift else 0,
        output="\n".join(drift) if drift else (
            "Final regular files and required directories match the "
            "pre-gate snapshot."
        ),
    )
    gates = gates + (integrity,)
    write_evidence(
        ROOT,
        files=files,
        manifest_digest=manifest_digest,
        gates=gates,
        total_bytes=initial_bytes,
        provenance=provenance,
    )
    for gate in gates:
        status = "PASS" if gate.returncode == 0 else "FAIL"
        print(f"{gate.name}: {status}")
    print(f"Evidence: {ROOT / EVIDENCE_NAME}")
    print(f"Manifest: {ROOT / MANIFEST_NAME}")
    return 0 if all(gate.returncode == 0 for gate in gates) else 1


if __name__ == "__main__":
    raise SystemExit(main())
