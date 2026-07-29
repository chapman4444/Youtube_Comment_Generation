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
python -m pip install -e ".[test,transcripts]"
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
`scoreboard.bat` launch the same installed application.

## Workflows

For a comment, choose or paste a YouTube video, select writing approaches,
dials, and length, then build the packet. The completed packet is copied for
you to paste into a model. Copy the model's answer back and use the GUI action
to validate and save the draft.

For replies, open reply mode and identify your YouTube handle. The application
scans your threads, can build a triage packet, and then walks through each
selected person. Every accepted draft is saved immediately. Nothing is posted
to YouTube.

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

Run the release gate twice with identical test identities and outcomes:

```powershell
python tools\verify_two_runs.py
```

Verify a built wheel in a fresh temporary environment, without importing from
`src`:

```powershell
python tools\verify_clean_install.py
```

## Safety boundary

The project uses read-only YouTube access. It contains no posting adapter,
OAuth write scope, or automatic model invocation. All YouTube-controlled text
is treated as untrusted evidence inside explicit packet boundaries. The
operator remains responsible for reviewing and manually posting final text.

Architecture documentation is available in `docs/architecture/`.
