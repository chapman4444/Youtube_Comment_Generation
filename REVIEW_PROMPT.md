# Technical review prompt

Review this project critically from structure through GUI behavior, workflow
logic, privacy, persistence, packaging, and release readiness. Keep every
conclusion tied to the evidence layer that actually supports it.

## Evidence model

### Layer 1: Source and tests in this snapshot

The archive contains source code, test code, documentation, launchers, CI
configuration, and verification tools. These files are direct evidence of
what the snapshot contains. Test source shows intended coverage; its presence
is not proof that a test ran or passed.

Use this layer for static findings such as implementation defects, missing
validation, unsafe defaults, absent regressions, misleading documentation, or
release-tooling weaknesses.

### Layer 2: Recorded verification for this staged snapshot

`REVIEW_FILE_MANIFEST.sha256` identifies the staged source files.
`REVIEW_VERIFICATION.md` records the commands, environment overrides,
versions, exit codes, and results produced while building this review
archive. Its final tree-identity gate binds those recorded results to the
regular files that were archived.

Treat this as recorded verification evidence for the manifested staged
snapshot. It is not a fresh execution performed by the reviewer, and it must
not be described as independent reproduction.

### Layer 3: Separate release gates

The repository also defines release checks such as the multi-version CI
matrix, `tools/verify_two_runs.py`, and
`tools/verify_clean_install.py`. Their source proves that the checks are
defined; it does not prove that they passed for this snapshot.

In particular, clean-wheel installation is a separate release gate and is
explicitly **not claimed by this review snapshot**. Do not infer a
clean-install pass, Python-version matrix pass, two-run determinism pass, or
complete release readiness unless separate execution evidence for that exact
source identity is supplied.

## Required review output

Report these conclusions separately:

1. Static source and test assessment.
2. What the recorded staged verification does and does not establish.
3. Which separate release gates remain unverified for the exact snapshot.

Label findings as verified source defects, missing test coverage, recorded
gate failures, or unverified release claims as appropriate. Do not collapse
“ready for code review,” “recorded staged checks passed,” and “ready for
release” into one verdict.
