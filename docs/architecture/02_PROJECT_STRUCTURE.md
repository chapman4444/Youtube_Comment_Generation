# Current Project Structure

This document describes the implemented source tree. It is not a proposed
future layout.

```text
Youtube_Comment_Generation/
|-- pyproject.toml
|-- README.md
|-- comment.bat
|-- reply.bat
|-- gui.bat
|-- doctor.bat
|-- scoreboard.bat
|-- docs/
|   `-- architecture/
|-- src/
|   `-- llm_youtube_comment_generation/
|       |-- application/
|       |   |-- build_comment_packet.py
|       |   |-- comment_session.py
|       |   |-- configuration.py
|       |   |-- guided_session.py
|       |   |-- inspect_video.py
|       |   |-- scan_threads.py
|       |   `-- scoreboard.py
|       |-- domain/
|       |   |-- candidates.py
|       |   |-- comments.py
|       |   |-- history.py
|       |   |-- packet_builder.py
|       |   |-- reply_packet.py
|       |   |-- targeting.py
|       |   |-- threads.py
|       |   |-- workflow.py
|       |   |-- writing_options.py
|       |   `-- writing_presets.py
|       |-- ports/
|       |   |-- artifacts.py
|       |   |-- bundle.py
|       |   |-- clipboard.py
|       |   |-- events.py
|       |   |-- history.py
|       |   |-- presets.py
|       |   |-- transcripts.py
|       |   `-- youtube.py
|       |-- infrastructure/
|       |   |-- filesystem_artifacts.py
|       |   |-- git_files.py
|       |   |-- json_preset_store.py
|       |   |-- prompt_resources.py
|       |   |-- saved_transcripts.py
|       |   |-- sqlite_history.py
|       |   |-- transcript_api.py
|       |   |-- transcript_chain.py
|       |   |-- user_state.py
|       |   |-- whisper_transcript.py
|       |   |-- youtube_api.py
|       |   `-- ytdlp_transcript.py
|       |-- interfaces/
|       |   |-- cli/
|       |   |   |-- main.py
|       |   |   |-- composition.py
|       |   |   |-- privacy_command.py
|       |   |   |-- state_storage.py
|       |   |   |-- window_options.py
|       |   |   `-- formatters.py
|       |   `-- gui/
|       |       |-- builder.py
|       |       |-- advanced_dialog.py
|       |       |-- layout.py
|       |       |-- options.py
|       |       |-- packet_window.py
|       |       |-- run_receipt.py
|       |       |-- widgets.py
|       |       |-- worker.py
|       |       |-- controllers.py
|       |       `-- view_models.py
|       `-- resources/
|           |-- prompts/
|           `-- wordlists/
|-- tests/
|   |-- application/
|   |-- cli/
|   |-- contract/
|   |-- domain/
|   |-- gui/
|   |-- harness/
|   |-- infrastructure/
|   `-- tools/
`-- tools/
```

The tree above names the main boundaries and representative modules. The
filesystem remains authoritative for the complete inventory.

## Responsibility rules

- `domain/` contains product rules and imports no interfaces or infrastructure.
- `application/` coordinates use cases through ports.
- `ports/` defines what the application needs from outside systems.
- `infrastructure/` implements those ports for YouTube, transcripts, SQLite,
  the filesystem, and the desktop.
- `interfaces/cli/` parses commands, resolves configuration, composes adapters,
  and formats results.
- `interfaces/gui/` collects options, runs work cooperatively off the Tk
  thread, and drives application sessions.
- `resources/` contains versioned prompt and word-list assets.
- Private state is resolved through `user_state.py`; settings, presets, and
  engagement history do not live in the repository or generated-run tree.
- `PortBundle` gives the composition root typed adapter attributes while
  retaining mapping compatibility for injected test fakes.

Avoid generic dumping grounds such as `utils.py`, `helpers.py`, or `misc.py`.
Every module needs a specific responsibility and test boundary.
