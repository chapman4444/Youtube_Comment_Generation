# YouTube Comment Generation

[![Quality](https://github.com/chapman4444/Youtube_Comment_Generation/actions/workflows/quality.yml/badge.svg)](https://github.com/chapman4444/Youtube_Comment_Generation/actions/workflows/quality.yml)

A Windows-first research and drafting workbench for thoughtful YouTube comments
and replies. Give it a video, choose how you want to approach the subject, and
it assembles the transcript, description, metadata, comments, and replies into
one evidence-grounded writing packet.

This is not a commenting bot. It does not sign in to YouTube, call a model on
its own, or publish text. You remain the editor: the application gathers and
organizes the evidence, your chosen model helps draft, and you decide what is
worth posting.

The application supports Python 3.10 through 3.12.

## What it does

- Builds top-level comment packets and guided reply packets from one shared core.
- Keeps the transcript, metadata, description, comments, replies, activity log,
  generated packet, and returned answer visible in separate GUI tabs.
- Tries multiple transcript routes with explicit provenance and bounded local
  Whisper fallback.
- Expands relevant and recent evidence when the packet budget has room, then
  reports what was included, shortened, and left out.
- Carries transcript source, language, generated-caption status, and supporting
  artifact names into the model-facing packet.
- Provides 44 writing approaches, eight writing dials, length controls, twelve
  built-in presets, and user-saved custom presets.
- Validates returned answers before saving the final draft.
- Preserves accepted drafts separately from the manual **Record as posted** step.
- Saves complete, inspectable run artifacts rather than hiding the work behind
  an opaque session.

## Screenshots

![The application ready for a video](docs/screenshots/start-screen.png)

| Source video | Retrieved public discussion |
| --- | --- |
| ![The source video in a browser](docs/screenshots/youtube-video.png) | ![Retrieved YouTube comments](docs/screenshots/comments.png) |

| Generated writing packet | Answer validation |
| --- | --- |
| ![Generated comment packet](docs/screenshots/generated-packet.png) | ![Returned answer being validated](docs/screenshots/answer-validation.png) |

![The manually published final comment](docs/screenshots/published-comment.png)

<details>
<summary><strong>Open the complete workflow gallery</strong></summary>

| Retrieval activity | Video metadata |
| --- | --- |
| ![Retrieval activity and run receipt](docs/screenshots/activity-log.png) | ![Retrieved video metadata](docs/screenshots/video-metadata.png) |

| Video description | Transcript and manual source controls |
| --- | --- |
| ![Retrieved video description](docs/screenshots/video-description.png) | ![Transcript with manual source controls](docs/screenshots/transcript-sources.png) |

| Retrieved replies | Full generated-packet view |
| --- | --- |
| ![Retrieved YouTube replies](docs/screenshots/replies.png) | ![Full generated packet](docs/screenshots/generated-packet-detail.png) |

| Model-answer review | Model critique and hardened final |
| --- | --- |
| ![Packet and model answer side by side](docs/screenshots/model-answer-review.png) | ![Model critique and hardened final](docs/screenshots/model-critique.png) |

</details>

The usernames and channel ids in these captures are obscured. The review
archive ships them, because `git archive HEAD` stages every committed file,
so these references resolve from the repository and from an extracted archive
alike.

## Install

### Windows quick start

The supplied launcher keeps the project on its own Python environment. From the
project directory, install the lightweight caption providers and open the GUI:

```batch
setup_venv.bat transcripts
gui.bat
```

The launcher creates `.venv` with Python 3.10 when it does not already exist.
To add local Whisper later, run `setup_venv.bat local-transcription`; to install
both caption providers and Whisper in one step, run `setup_venv.bat all`.

Set `YOUTUBE_API_KEY` in your environment before retrieving video metadata or
comments. The key is never stored in the repository or included in review
packages.

### Manual Python installation

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[transcripts]"
```

The `transcripts` extra installs both lightweight caption routes:
`youtube-transcript-api` and `yt-dlp`. To enable the heavier local Whisper
fallback as well:

```powershell
python -m pip install -e ".[local-transcription]"
```

For a development checkout with the test and clean-build tools installed:

```powershell
python -m pip install -e ".[verify,transcripts]"
```

Transcript support is optional. Without it, commands that do not need a
transcript still work and `ytcomment doctor` reports exactly what is available.

## Launch

Double-click `gui.bat` for the main comment workflow. The window opens before
retrieval; paste a YouTube URL or copy one from your browser, choose your
settings, and press **Build**. Use `gui.bat --replies` for guided reply mode.

The equivalent command-line entry points are:

```powershell
ytcomment --help
ytcomment comment build URL_OR_ID
ytcomment comment build URL_OR_ID --window
ytcomment gui URL_OR_ID --my-handle @name
```

The supplied `comment.bat`, `reply.bat`, `doctor.bat`, and
`scoreboard.bat` launch the same installed application. Every launcher calls
`setup_venv.bat`: on the first run it creates the project-local `.venv` with
Python 3.10 and installs only the core application. This keeps `doctor.bat`,
`scoreboard.bat`, GUI preview, and non-transcript commands available even when
an optional provider cannot be installed. Install the lightweight caption
providers explicitly with `setup_venv.bat transcripts`, local Whisper with
`setup_venv.bat local-transcription`, or both with `setup_venv.bat all`. The
review archive builder uses `setup_venv.bat review`, which installs and
preflights its complete declared verification toolset before staging begins.
Every operational and verification installation is resolved through
`constraints/review.txt`; the flexible compatibility ranges in
`pyproject.toml` remain package metadata rather than the release environment.
The launchers never fall back to an unrelated system-wide `python` command.
Choose the no-caption behavior under **Advanced → Local Whisper**:

- **Ignore** continues without a transcript and does not ask.
- **Ask** explains why captions were unavailable and requests confirmation
  before downloading audio. This is the default.
- **Automatic** starts local transcription without asking.

The persistent **Stop** button cancels caption retrieval or local
transcription at the next safe point. The status bar shows transcript state,
and the **Transcript** tab displays completed Whisper segments as they are
created, with an estimated remaining time when enough progress is available.
Local Whisper remains bounded in every mode: videos longer than 60 minutes
are refused before audio transfer, downloads stop at 200 MiB, and the
60-minute ceiling is also passed to the transcriber when upstream duration
metadata is missing or inaccurate. Both effective limits are shown in
Advanced and `doctor`, may be set through configuration or environment, and
cannot be bypassed by Automatic mode.
Normal Build tries the transcript API, `yt-dlp` captions, a saved transcript,
and then the configured Whisper behavior. Four buttons in the Transcript tab
can rerun a build using exactly one of those sources for diagnosis or manual
recovery.

## Workflow

```mermaid
flowchart LR
    A[Paste a YouTube URL] --> B[Choose a preset or writing options]
    B --> C[Build]
    C --> D[Inspect evidence and copy the packet]
    D --> E[Use the packet with your chosen model]
    E --> F[Paste the complete answer]
    F --> G[Validate and save the draft]
    G --> H[Post manually]
    H --> I[Record as posted]
```

### Comment workflow

1. Paste a YouTube URL, enter an 11-character video ID, or copy a supported URL
   before opening the application.
2. Choose a writing preset or select approaches, writing dials, and length
   directly. Selecting a preset applies it immediately.
3. Press **Build**. The application retrieves the video evidence, assembles and
   saves the packet, displays a compact run receipt, and copies the packet.
4. Review the evidence tabs or paste the packet into the model of your choice.
5. Paste the complete returned answer into **Paste answer**, then click
   **Validate and save answer**. Invalid structure is explained and preserved
   for correction; a valid **Hardened final** is saved as the draft.
6. Post the text yourself if you decide to use it. Only then click
   **Record as posted** if you want the local scoreboard to track it.

Changing the video or a packet-affecting setting re-enables **Build** without
discarding the previous packet. **Reset** returns the window to its opening
state and clears the working tabs.

### Writing presets

The twelve built-in presets are **Default**, **Concise and direct**,
**Evidence first**, **Constructive**, **Dry and sharp**, **Balanced**,
**Skeptical**, **Questions and gaps**, **Direct rebuttal**,
**Creative angles**, **Human impact**, and **Full analysis**.

**Save preset...** captures the current approaches, dials, and length as a
custom preset. Presets deliberately exclude videos, handles, local paths,
proxies, retrieval limits, and credentials.

### Debug workflow

Select **Debug build** before pressing **Build** to produce a one-run diagnostic
packet alongside the normal packet. The returned answer must include a
`### Debug report` immediately before `### Hardened final`. The application
saves the safe build settings, run record, exact packet, complete response,
validation status, and final draft together in one debug bundle. A rejected
response is preserved with the exact reason instead of being lost.

The bundle is deliberately unredacted, because a diagnostic that omitted the
packet and the response could not explain the build it describes. It carries
no credentials and no local paths, but it does carry the retained YouTube
evidence inside the packet: commenter display names, comment and reply text,
the video description, and transcript text. The file says so at the top.
Review it before attaching it to a bug report or posting it publicly.

### Reply workflow

Open reply mode and identify your YouTube handle. The application scans your
threads, can build a triage packet, and then walks through each selected person.
Every accepted draft is saved immediately. Nothing is posted to YouTube.

Accepted and posted are deliberately different states. After you manually
post a saved draft, use **Record as posted** in the GUI so the scoreboard may
measure it. The GUI shows the exact draft and asks for confirmation before
recording. The equivalent CLI operation is:

```powershell
ytcomment history record URL_OR_ID --workflow comment --draft-file comment.txt --event-id UNIQUE_ID
ytcomment history record URL_OR_ID --workflow reply --draft-file reply.txt --target-comment-id COMMENT_ID --run-id RUN
```

Each recorded event needs a stable identity, supplied as `--event-id` or
`--run-id`. Without one the command refuses rather than guess, because two
genuinely distinct posts of the same text to the same video would otherwise
be indistinguishable and the second would be silently discarded. Repeating
the same `--event-id` is safe: it records the event once, so a retry after an
interrupted run cannot create a duplicate.

Reply discovery uses its own scan depth (3,000 comments by default).
`reply --max-comments` and the reply GUI's matching option change that depth;
they do not change the comment packet's evidence sample.

The GUI opens at a screen-aware size, remembers its geometry, and provides a
draggable divider between writing options and output. Every completed build
shows a compact receipt with evidence counts, transcript provenance, logical
YouTube API operation count, packet size, and output location. One logical
operation is one Data API call made by the application. Automatic HTTP
transport retries do not increase this count, so it is not a physical network
attempt counter. The **Activity** tab shows retrieval and processing messages.
Metadata, description, transcript, comments, and replies each have a separate
tab and Copy button. Selected text in every text view can also be copied from
its right-click menu.

The CLI exposes the same core workflows:

```powershell
ytcomment comment build URL_OR_ID
ytcomment reply guided URL_OR_ID --my-handle @name
ytcomment doctor
```

Use `ytcomment <group> <command> --help` for the complete options.

## Design

The application is a modular monolith with a functional core and explicit
ports around YouTube, transcripts, the clipboard, storage, settings, and time.
The CLI and GUI construct the same application commands, so the GUI presents
the workflow without owning a second copy of the business rules.

The packet pipeline records evidence provenance, retrieval completeness,
warnings, budgets, and completion state. YouTube-controlled text is isolated as
untrusted evidence before it reaches the packet. Run publication is atomic, and
an interrupted or incomplete run is not presented as a successful one.
Default section sizes are protected floors rather than permanent ceilings:
relevant and recent coverage expands while measured candidates still fit the
packet budget. Candidate packets are never rendered merely to measure them, and
the live and rebuild paths use the same fitting logic.

The design notes are intentionally concrete:

- [Architecture overview](docs/architecture/01_ARCHITECTURE_OVERVIEW.md)
- [Project structure](docs/architecture/02_PROJECT_STRUCTURE.md)
- [Guided workflow state machine](docs/architecture/04_GUIDED_WORKFLOW_STATE_MACHINE.md)
- [Packet build pipeline](docs/architecture/05_PACKET_BUILD_PIPELINE.md)
- [CLI and GUI contract](docs/architecture/06_CLI_GUI_CONTRACT.md)
- [Dependency constraints](docs/architecture/09_DEPENDENCY_CONSTRAINTS.md)

## Verify

Install the declared review and verification toolset first:

```batch
setup_venv.bat review
```

Run the full suite:

```powershell
python -m pytest -q
```

Check tracked files for private state, credentials, and personal work notes:

```powershell
ytcomment privacy check
```

GitHub Actions runs the privacy audit, failure-class lint, test suite,
transcript-provider imports, two-run determinism gate, and clean-wheel install
on Windows with Python 3.10, 3.11, and 3.12.

Dependency updates are intentional rather than “newest available” installs.
See `docs/architecture/09_DEPENDENCY_CONSTRAINTS.md` for the clean-environment
update and verification procedure.

Window settings, custom presets, and engagement history live under the
operating system's private user-data directory. On Windows the default is:

```text
%LOCALAPPDATA%\YouTubeCommentGeneration
```

Set `YTCOMMENT_STATE_DIR` to choose a different private state location.

Run the release gate twice with identical test identities and outcomes:

```powershell
python tools\verify_two_runs.py
```

Verify a built wheel in a fresh temporary environment, without importing from
`src`. This gate installs and imports both caption providers and the optional
local Whisper provider:

```powershell
python tools\verify_clean_install.py
```

To bind the separate Windows Python matrix, determinism, and clean-wheel
results to a review archive, first create the review ZIP, then record the
release gates against its manifest and rebuild the ZIP:

```text
python tools\record_release_verification.py ^
  --python310 .venv\Scripts\python.exe ^
  --python311 C:\path\to\python311-environment\Scripts\python.exe ^
  --python312 C:\path\to\python312-environment\Scripts\python.exe
make_review_zip.bat
```

The second archive build includes `RELEASE_VERIFICATION.md` and its structured
`RELEASE_VERIFICATION.json` only when the recorder proves an exact two-way
match between the checkout release inputs and the manifest. The gates execute
from a disposable tree reconstructed solely from those manifested files.
Stale, incomplete, contradictory, or nonzero release evidence prevents archive
replacement. A separately retained `.sha256` file binds the completed ZIP
bytes to the delivered package.

## Review package

`make_review_zip.bat` creates a privacy-checked source-review archive.
`REVIEW_PROMPT.md` tells the reviewer to keep three evidence layers separate:
the source and test files present in the snapshot, the verification recorded
while staging that exact snapshot, and separately recorded release gates. When
validated companion release evidence is included, it records the Python
3.10-3.12 matrix, two-run determinism, clean-wheel installation, distribution
hashes, and final exact source identity for that manifest. Without that
companion evidence, those release gates remain unverified. Recorded evidence
is not an independent reviewer rerun.

## Safety boundary

The project uses read-only YouTube access. It contains no posting adapter,
OAuth write scope, or automatic model invocation. All YouTube-controlled text
is treated as untrusted evidence inside explicit packet boundaries. The
operator remains responsible for checking every draft, deciding whether it
should be posted, and manually posting the final text.
