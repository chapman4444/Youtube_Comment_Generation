# AGENTS.md

Guidance for AI agents working in this repository. Read this before changing
code; several of the rules below are enforced by tests that will fail you
rather than warn you.

## What this project is

A Windows-first desktop tool that assembles YouTube evidence (transcript,
metadata, description, comments, replies) into a writing packet for a human
to hand to a model, then validates the returned answer and saves a draft.

It is **not** a bot. There is no posting adapter, no OAuth write scope, and
no automatic model invocation. The operator posts manually and records it
afterwards. Do not add any of those without being asked.

## Architecture — mechanically enforced

Layers: `domain` / `ports` / `application` / `infrastructure` / `interfaces`.
`tests/contract/test_import_direction.py` parses every module and enforces
this, and proves the checker itself works with negative cases.

- `domain` imports the standard library only — and **not** `tkinter`,
  `socket`, `subprocess`, `sqlite3`, `urllib.request`, or `asyncio`, even
  though those are stdlib. `urllib.parse` is fine.
- `ports` may import `domain`. The domain may never import a port.
- `application` may **not** import `infrastructure`. This is the
  load-bearing rule: it keeps every use case runnable on fakes.
- Only `infrastructure` may import third-party packages.
- Only `interfaces/gui` may import `tkinter`. `interfaces/cli` may not.

`tests/gui/test_gui_boundaries.py` adds: the GUI owns no workflow
transitions, and `view_models.py` / `controllers.py` stay Tk-free.

Prefer surgical changes. Do not restructure to taste.

## Conventions that are actually held to

**Comments explain *why*, including past mistakes.** See
`domain/sanitize.py`, which documents an earlier version that placed an
attacker-chosen display name outside the trust boundary. These comments are
load-bearing history — do not strip or "tidy" them.

**Every guard is proved both ways.** A rule gets a positive test and a
negative proof that the checker actually bites. A guard that only ever
passes is treated as unproven.

**No skipped tests.** The suite is designed to have zero. `pytest.ini`
options include `-ra` precisely so a skip is visible, and
`tools/verify_two_runs.py` — a release gate — *fails* on any skip. Adding
`pytest.skip` will break the release matrix.

**Test names are sentences** describing the behaviour, not the function
under test.

Line length 88. Ruff's `select` is deliberately narrow (`E9,F63,F7,F82`).

## Packet assembly rules

- Live builds and offline rebuilds must use the same section-fitting logic in
  `domain/packet_builder.py`. Do not create a second allocator in an
  interface or application module.
- Adaptive growth may measure candidates and ask the allocator whether they
  fit, but it must not render trial packets merely to measure them.
- The model-facing packet carries normalized transcript provenance:
  availability, immediate acquisition route, original source when reused,
  language, generated-caption status, entry count, and producer-declared
  supporting artifact names. Preserve those fields in both live and rebuild
  paths.
- The rendered reduction summary is computed from the final selection and
  allocation. Do not infer it from default section caps.

## Things that will bite you

- **`.bat` files must be CRLF.** `.gitattributes` declares
  `*.bat text eol=crlf`. An LF `.bat` makes `cmd.exe` misparse multi-line
  `if/else` blocks — it executes stray characters as commands.
- **`git` needs `-c safe.directory=<repo>` here.** `.git` is owned by a
  different Windows account, so bare `git` calls fail. `gh` hits the same
  wall; pass `--repo`, `--base`, `--head` explicitly.
- **The test harness blocks `subprocess`.** `tests/conftest.py` refuses
  desktop launches by guarding OS calls, so a tool function that shells out
  cannot be exercised from the suite.
- **Read `git show` output as bytes.** Decoding with the console locale
  (cp1252) dies on a wordlist byte and reports an ordinary file as
  unreadable.
- **Compare against a checkout, not against blobs.** Git stores LF and
  converts on checkout per `.gitattributes` plus `core.autocrlf`. Comparing
  archive bytes to raw blobs invents differences and hides real ones. Use
  `git worktree add --detach <tmp> origin/main`.
- **Any new top-level file becomes a release input immediately.** An
  untracked file at the repo root will be reported as `unmanifested` and
  fail a release recording. Commit it or keep it out of the tree.

## The release archive — two-phase, and easy to get wrong

```
1. make_review_zip.bat                    builds ZIP + REVIEW_VERIFICATION.md
2. tools/record_release_verification.py   runs release gates, writes
                                          RELEASE_VERIFICATION.{md,json}
3. make_review_zip.bat                    rebuild so the evidence is inside
```

Step 3 is required — evidence written in step 2 lands in `review_packages/`
and only reaches the archive on the next build.

- **Changing any manifested file invalidates existing evidence.** Remove
  `RELEASE_VERIFICATION.*` from `review_packages/` before rebuilding, or the
  build exits 8.
- **Never edit a tracked file while the recorder runs.** It compares the
  checkout against the manifest at the end; an edit mid-run wastes the whole
  ~13-minute run.
- **Pre-check before spending that time.** Identity is instant, and
  `tools/verify_two_runs.py` (~4 min) catches the other common failure.

The archive is staged with `git archive HEAD`, so what ships is what is
committed. Uncommitted work never reaches it.

## Evidence vocabulary — keep these distinct

`REVIEW_PROMPT.md` requires reviewers to separate three layers, and reviews
have been marked down for collapsing them:

1. **Source and tests in the snapshot** — test source proves intent, not that
   a test ran.
2. **Recorded staged verification** (`REVIEW_VERIFICATION.md`) — commands run
   while building that snapshot. Not an independent rerun.
3. **Recorded release gates** (`RELEASE_VERIFICATION.*`) — the 3.10/3.11/3.12
   matrix, determinism, clean-wheel install. Also recorded, also not a rerun.

Never merge "ready for code review", "recorded checks passed", and "ready for
release" into one claim. Do not say a command passed unless it ran.

## Safety boundary

Read-only YouTube access. All YouTube-controlled text is untrusted and is
neutralized inside explicit packet boundaries before rendering — see
`domain/sanitize.py`. Nothing a commenter can author belongs outside that
boundary, including in headers: identifiers are allowlisted, not escaped.
Transcript provenance is rendered inside the same untrusted-source boundary.

The debug bundle is deliberately **unredacted** and says so in the file
itself. Do not relabel it "safe" or "shareable".
