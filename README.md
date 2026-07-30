# LLM YouTube Comment Generation

An installable, read-only YouTube comment and reply packet builder. It gathers
video, transcript, and comment evidence; combines that evidence with selected
writing approaches and dials; and produces Markdown packets for use with the
language model of your choice. You review and post any final text yourself.

The application supports Python 3.10 through 3.12.

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
Python 3.10 and installs both caption sources (`youtube-transcript-api` and
`yt-dlp`) plus the optional local Whisper transcriber. The launchers never
fall back to an unrelated system-wide `python` command. Whisper remains off
until **Advanced → Use local Whisper when captions are unavailable** is
selected, because it downloads audio and takes substantially longer.

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
attempt counter.

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

## Review package

`make_review_zip.bat` creates a privacy-checked source-review archive.
`REVIEW_PROMPT.md` tells the reviewer to keep three evidence layers separate:
the source and test files present in the snapshot, the verification recorded
while staging that exact snapshot, and release gates that require separate
execution evidence. The review archive explicitly does not claim that the
clean-wheel gate passed.

## Safety boundary

The project uses read-only YouTube access. It contains no posting adapter,
OAuth write scope, or automatic model invocation. All YouTube-controlled text
is treated as untrusted evidence inside explicit packet boundaries. The
operator remains responsible for reviewing and manually posting final text.

Architecture documentation is available in `docs/architecture/`.
