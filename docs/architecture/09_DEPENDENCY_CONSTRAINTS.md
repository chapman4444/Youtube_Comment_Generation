# Dependency constraints

`pyproject.toml` describes compatible package ranges for installing the
library. `constraints/review.txt` defines the exact dependency set used for
this Windows application, CI, review evidence, and release verification on
Python 3.10, 3.11, and 3.12.

The following paths consume the same constraints file:

- `setup_venv.bat`, including core and every optional setup mode;
- `.github/workflows/quality.yml`;
- `tools/verify_clean_install.py`;
- the environment used by `make_review_zip.bat`.

Build isolation receives the same file through `PIP_CONSTRAINT`, so build
requirements cannot silently resolve against a different newest release.
Review evidence records the file's SHA-256.

## Intentional update procedure

1. Edit dependency compatibility ranges only when application compatibility
   actually changes.
2. Resolve proposed exact versions in disposable Python 3.10, 3.11, and 3.12
   environments on Windows.
3. Replace `constraints/review.txt` with the reviewed common set, retaining
   environment markers only when a supported Python version genuinely needs
   a different distribution.
4. Run `python -m pip check`, failure-class Ruff checks, the full test suite,
   transcript-provider imports, `tools/verify_two_runs.py`, and
   `tools/verify_clean_install.py` for the final source identity.
5. Run the checked-in GitHub Actions matrix and retain its logs.
6. Rebuild the review archive with `make_review_zip.bat`. Record the new
   constraints hash, source-manifest hash, and distribution hashes.

Fast-moving providers such as yt-dlp are updated by this procedure, not by an
unbounded install during normal setup.
