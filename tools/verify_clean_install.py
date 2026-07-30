"""Build distributions and test the wheel from a fresh temporary environment.

No PYTHONPATH override is used. The temporary environment and distributions
live outside the repository and are removed when the gate finishes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "REVIEW_FILE_MANIFEST.sha256"


def run(command: list[str], *, cwd: Path = ROOT, env=None) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=str(cwd), env=env, check=True)


def manifested_paths(root: Path) -> tuple[tuple[Path, str | None], ...]:
    """Return the bounded source inputs for the clean-install copy."""

    manifest = root / MANIFEST_NAME
    if manifest.is_file():
        rows: list[tuple[Path, str | None]] = []
        for line_number, line in enumerate(
            manifest.read_text(encoding="utf-8").splitlines(), start=1
        ):
            digest, separator, relative = line.partition("  ")
            path = Path(relative)
            if (
                separator != "  "
                or len(digest) != 64
                or path.is_absolute()
                or ".." in path.parts
            ):
                raise SystemExit(
                    f"invalid {MANIFEST_NAME} line {line_number}"
                )
            rows.append((path, digest))
        if not rows:
            raise SystemExit(f"{MANIFEST_NAME} is empty")
        return tuple(rows)

    completed = subprocess.run(
        ["git", "-c", f"safe.directory={root.as_posix()}", "ls-files", "-z"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise SystemExit(
            "clean-install verification requires either "
            f"{MANIFEST_NAME} or a readable Git index"
        )
    return tuple(
        (Path(raw.decode("utf-8")), None)
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def copy_manifested_source(root: Path, destination: Path) -> None:
    """Copy only declared source inputs and verify manifested hashes."""

    destination.mkdir(parents=True)
    for relative, expected in manifested_paths(root):
        source = root / relative
        if not source.is_file():
            raise SystemExit(f"declared source input is missing: {relative}")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if expected is not None:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != expected:
                raise SystemExit(
                    f"declared source input hash differs: {relative}"
                )
    source_manifest = root / MANIFEST_NAME
    if source_manifest.is_file():
        shutil.copy2(source_manifest, destination / MANIFEST_NAME)


def main() -> int:
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    clean_env.pop("PYTHONHOME", None)

    with tempfile.TemporaryDirectory(prefix="ytcomment-clean-install-") as raw:
        temporary = Path(raw)
        distributions = temporary / "distributions"
        environment = temporary / "venv"
        source_copy = temporary / "source"

        copy_manifested_source(ROOT, source_copy)
        clean_env["PIP_CONSTRAINT"] = str(
            source_copy / "constraints" / "review.txt"
        )

        run([
            sys.executable, "-m", "build",
            "--outdir", str(distributions), str(source_copy),
        ], env=clean_env)

        wheels = sorted(distributions.glob("*.whl"))
        sdists = sorted(distributions.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise SystemExit(
                f"expected one wheel and one source distribution, found "
                f"{len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
            )

        run([sys.executable, "-m", "venv", str(environment)], env=clean_env)
        python = environment / ("Scripts/python.exe" if os.name == "nt"
                                else "bin/python")
        command = environment / ("Scripts/ytcomment.exe" if os.name == "nt"
                                 else "bin/ytcomment")

        run([
            str(python), "-m", "pip", "install",
            "-c", str(source_copy / "constraints" / "review.txt"),
            f"{wheels[0]}[verify,transcripts,local-transcription]",
        ], cwd=temporary, env=clean_env)
        run(
            [str(python), "-m", "pip", "check"],
            cwd=temporary,
            env=clean_env,
        )
        run(
            [str(python), "-m", "pip", "freeze", "--all"],
            cwd=temporary,
            env=clean_env,
        )

        smoke = (
            "import json, pathlib, faster_whisper, "
            "youtube_transcript_api, yt_dlp, "
            "llm_youtube_comment_generation as package; "
            "path=pathlib.Path(package.__file__).resolve(); "
            f"source=pathlib.Path({str(ROOT / 'src')!r}).resolve(); "
            "assert source not in path.parents, (path, source); "
            "print(json.dumps({'installed_import': str(path)}))"
        )
        run([str(python), "-c", smoke], cwd=temporary, env=clean_env)
        run([str(command), "--help"], cwd=temporary, env=clean_env)

        run([
            str(python), "-m", "pytest", "-q",
            "tests/cli/test_cli.py",
            "tests/cli/test_window_settings.py",
            "tests/test_launchers.py",
        ], cwd=source_copy, env=clean_env)
        run(
            [str(python), "-m", "pytest", "-q"],
            cwd=source_copy,
            env=clean_env,
        )

        print(json.dumps({
            "wheel": wheels[0].name,
            "wheel_sha256": hashlib.sha256(wheels[0].read_bytes()).hexdigest(),
            "sdist": sdists[0].name,
            "sdist_sha256": hashlib.sha256(sdists[0].read_bytes()).hexdigest(),
            "temporary_environment_removed_on_exit": True,
            "source_path_override": False,
            "constraints": "constraints/review.txt",
            "transcript_imports": [
                "youtube_transcript_api",
                "yt_dlp",
                "faster_whisper",
            ],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
