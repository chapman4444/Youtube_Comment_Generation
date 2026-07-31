# LLM YouTube Comment Generation

An installable, read-only YouTube comment and reply packet builder. It gathers
video, transcript, and comment evidence; combines that evidence with selected
writing approaches and dials; and produces Markdown packets for use with the
language model of your choice. You review and post any final text yourself.

The application supports Python 3.10 through 3.12.

## Screenshots

| Start screen | Generated packet |
| --- | --- |
| ![Start screen](docs/screenshots/01-start-screen.png) | ![Generated packet](docs/screenshots/02-generated-packet.png) |

| Activity and retrieval receipt | Transcript source controls |
| --- | --- |
| ![Activity and retrieval receipt](docs/screenshots/03-activity-log.png) | ![Transcript source controls](docs/screenshots/04-transcript-sources.png) |

![Answer validation](docs/screenshots/05-answer-validation.png)

### Full workflow examples

| Source video | Model-answer review |
| --- | --- |
| ![Source video](docs/screenshots/youtube-video.png) | ![Model-answer review](docs/screenshots/model-answer-review.png) |

| Model critique | Video metadata |
| --- | --- |
| ![Model critique](docs/screenshots/model-critique.png) | ![Video metadata](docs/screenshots/video-metadata.png) |

| Video description | Retrieved comments |
| --- | --- |
| ![Video description](docs/screenshots/video-description.png) | ![Retrieved comments](docs/screenshots/comments.png) |

| Retrieved replies | Generated-packet detail |
| --- | --- |
| ![Retrieved replies](docs/screenshots/replies.png) | ![Generated-packet detail](docs/screenshots/generated-packet-detail.png) |

![Published comment](docs/screenshots/published-comment.png)

## Install

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[verify,transcripts]"
```

The `transcripts` extra installs both lightweight caption routes:
`youtube-transcript-api` and `yt-dlp`. To enable the heavier local Whisper
fallback as well:

```powershell
python -m pip install -e ".[local-transcription]"
```

Set `YOUTUBE_API_KEY` in your environment for commands that retrieve YouTube
data. Transcript support is optional; without it, commands that do not need a
transcript still work and `ytcomment doctor` reports the limitation.

## Launch

Show the command-line help:

```powershell
ytcomment --help
```

Open the main GUI in comment mode:

```powershell
ytcomment comment build --window
```

Open it in reply mode:

```powershell
ytcomment gui
```

On Windows, `gui.bat` opens comment mode and `gui.bat --replies` opens reply
mode. The supplied `comment.bat`, `reply.bat`, `doctor.bat`, and
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

## Workflows

For a comment, choose or paste a YouTube video, select writing approaches,
dials, length, or a writing preset, then build the packet. The completed packet
is copied for you to paste into a model. Paste the model's answer into the
visible answer box (or use the clipboard shortcut), then validate and save the
draft.

Built-in presets cover Default, Concise and direct, Evidence first,
Constructive, Dry and sharp, and Full analysis. **Save as...** captures the
current registers, dials, and length as a custom preset. Presets deliberately
exclude videos, handles, paths, proxies, retrieval limits, and credentials.

For replies, open reply mode and identify your YouTube handle. The application
scans your threads, can build a triage packet, and then walks through each
selected person. Every accepted draft is saved immediately. Nothing is posted
to YouTube.

Accepted and posted are deliberately different states. After you manually
post a saved draft, use **Record as posted** in the GUI so the scoreboard may
measure it. The GUI shows the exact draft and asks for confirmation before
recording. The equivalent CLI operation is:

```powershell
ytcomment history record URL_OR_ID --workflow comment --draft-file comment.txt
ytcomment history record URL_OR_ID --workflow reply --draft-file reply.txt --target-comment-id COMMENT_ID --run-id RUN
```

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
Changing the video or a packet-affecting setting re-enables Build while
leaving the previous packet available for reference. Metadata, description,
transcript, comments, and replies each have a separate tab and Copy button.
Selected text in every text view can also be copied from its right-click menu.

The CLI exposes the same core workflows:

```powershell
ytcomment comment build URL_OR_ID
ytcomment reply guided URL_OR_ID --my-handle @name
ytcomment doctor
```

Use `ytcomment <group> <command> --help` for the complete options.

## Verify

Run the full suite:

```powershell
python -m pytest -q
```

Check tracked files for private state, credentials, and personal work notes:

```powershell
ytcomment privacy check
```

The same privacy audit and test suite run automatically on GitHub for Python
3.10, 3.11, and 3.12.

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
operator remains responsible for reviewing and manually posting final text.

Architecture documentation is available in `docs/architecture/`.
