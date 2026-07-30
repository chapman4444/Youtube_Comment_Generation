from __future__ import annotations

import hashlib
from pathlib import Path

from tools.verify_clean_install import copy_manifested_source


def test_clean_install_copy_uses_only_manifested_files(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    included = source / "src" / "package" / "included.py"
    included.parent.mkdir(parents=True)
    included.write_text("included = True\n", encoding="utf-8")
    extra = source / "src" / "package" / "unmanifested.py"
    extra.write_text("included = False\n", encoding="utf-8")
    digest = hashlib.sha256(included.read_bytes()).hexdigest()
    (source / "REVIEW_FILE_MANIFEST.sha256").write_text(
        f"{digest}  src/package/included.py\n",
        encoding="utf-8",
    )
    destination = tmp_path / "copy"

    copy_manifested_source(source, destination)

    assert (destination / "src" / "package" / "included.py").is_file()
    assert not (destination / "src" / "package" / "unmanifested.py").exists()
