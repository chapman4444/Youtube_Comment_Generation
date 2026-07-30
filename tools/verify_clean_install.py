"""Build distributions and test the wheel from a fresh temporary environment.

No PYTHONPATH override is used. The temporary environment and distributions
live outside the repository and are removed when the gate finishes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT, env=None) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=str(cwd), env=env, check=True)


def main() -> int:
    clean_env = os.environ.copy()
    clean_env.pop("PYTHONPATH", None)
    clean_env.pop("PYTHONHOME", None)

    with tempfile.TemporaryDirectory(prefix="ytcomment-clean-install-") as raw:
        temporary = Path(raw)
        distributions = temporary / "distributions"
        environment = temporary / "venv"
        source_copy = temporary / "source"

        ignored = shutil.ignore_patterns(
            ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", "build", "dist", "*.egg-info",
            "*.zip",
        )
        shutil.copytree(ROOT, source_copy, ignore=ignored)

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
            f"{wheels[0]}[verify,transcripts,local-transcription]",
        ], cwd=temporary, env=clean_env)

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
        ], env=clean_env)
        run([str(python), "-m", "pytest", "-q"], env=clean_env)

        print(json.dumps({
            "wheel": wheels[0].name,
            "sdist": sdists[0].name,
            "temporary_environment_removed_on_exit": True,
            "source_path_override": False,
            "transcript_imports": [
                "youtube_transcript_api",
                "yt_dlp",
                "faster_whisper",
            ],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
