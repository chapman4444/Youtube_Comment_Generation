# Proposed Project Structure

```text
LLM_Youtube_Comment_Generation/
│
├── pyproject.toml
├── README.md
│
├── src/
│   └── llm_youtube_comment_generation/
│       │
│       ├── domain/
│       │   ├── ids.py
│       │   ├── video.py
│       │   ├── comments.py
│       │   ├── threads.py
│       │   ├── targeting.py
│       │   ├── candidates.py
│       │   ├── writing_options.py
│       │   ├── packets.py
│       │   ├── history.py
│       │   └── workflow.py
│       │
│       ├── application/
│       │   ├── commands.py
│       │   ├── results.py
│       │   │
│       │   ├── comments/
│       │   │   ├── inspect_video.py
│       │   │   └── build_packet.py
│       │   │
│       │   ├── replies/
│       │   │   ├── target_comment.py
│       │   │   ├── target_reply.py
│       │   │   ├── scan_my_threads.py
│       │   │   ├── triage.py
│       │   │   ├── build_packet.py
│       │   │   └── guided_session.py
│       │   │
│       │   ├── history/
│       │   │   ├── record.py
│       │   │   └── scoreboard.py
│       │   │
│       │   └── runs/
│       │       ├── inspect.py
│       │       └── validate.py
│       │
│       ├── ports/
│       │   ├── youtube.py
│       │   ├── transcripts.py
│       │   ├── clipboard.py
│       │   ├── artifacts.py
│       │   ├── history.py
│       │   ├── settings.py
│       │   ├── clock.py
│       │   └── events.py
│       │
│       ├── infrastructure/
│       │   ├── youtube_api.py
│       │   ├── transcript_api.py
│       │   ├── system_clipboard.py
│       │   ├── filesystem_artifacts.py
│       │   ├── json_history.py
│       │   ├── user_settings.py
│       │   └── logging_jsonl.py
│       │
│       ├── interfaces/
│       │   ├── cli/
│       │   │   ├── main.py
│       │   │   ├── parsers.py
│       │   │   └── formatters.py
│       │   │
│       │   └── gui/
│       │       ├── main.py
│       │       ├── main_window.py
│       │       ├── controllers.py
│       │       └── view_models.py
│       │
│       └── resources/
│           ├── prompts/
│           ├── registers.json
│           └── dials.json
│
└── tests/
    ├── unit/
    ├── domain/
    ├── application/
    ├── contract/
    ├── cli/
    ├── golden/
    ├── gui/
    └── fixtures/
```

## Responsibility Rules

### `domain/`

Contains product rules and typed facts.

Must not import infrastructure or interfaces.

### `application/`

Contains use-case orchestration.

May depend on domain objects and ports.

Must not depend on concrete infrastructure.

### `ports/`

Contains protocols or abstract interfaces.

Ports describe what the application needs.

### `infrastructure/`

Contains concrete adapters for external systems.

May depend on third-party packages.

### `interfaces/cli/`

Parses arguments, creates commands, calls application handlers, formats results.

No domain logic.

### `interfaces/gui/`

Collects user input, creates commands, renders state and results.

No domain logic.

### `resources/`

Stores versioned prompt text and declarative writing-option definitions.

## Naming Rule

Do not create generic dumping grounds such as:

```text
utils.py
helpers.py
common.py
manager.py
misc.py
```

Create a module only when it has a clear responsibility and test boundary.
