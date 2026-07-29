# CLI and GUI Contract

## Canonical Rule

The CLI and GUI use the same typed commands, validators, handlers, and result objects.

The GUI does not implement a separate version of the application.

## Shared Command Flow

```text
User input
    ↓
CLI parser or GUI form
    ↓
Typed application command
    ↓
Application handler
    ↓
Domain logic and ports
    ↓
Typed result
    ↓
CLI formatter or GUI view
```

## Example Commands

```text
InspectVideoCommand
BuildCommentPacketCommand
TargetPublicCommentCommand
TargetReplyCommand
ScanOwnedThreadsCommand
BuildTriagePacketCommand
StartGuidedReplySessionCommand
SubmitGuidedAnswerCommand
BuildScoreboardCommand
InspectRunCommand
```

## CLI Responsibilities

The CLI may:

- parse arguments;
- load configuration;
- create typed commands;
- call application handlers;
- render human output;
- emit JSON;
- emit JSONL progress;
- map typed errors to exit codes.

The CLI may not contain domain logic.

## GUI Responsibilities

The GUI may:

- collect input;
- select targets;
- create typed commands;
- display workflow state;
- show progress and warnings;
- navigate candidates;
- copy packets;
- accept answers;
- open outputs.

The GUI may not:

- reconstruct answered state;
- resolve mentions;
- rank candidates;
- parse answers independently;
- build packets;
- own transitions;
- write final review files;
- maintain separate validation rules.

## Equivalent CLI Command

Where practical, the GUI should show the equivalent CLI command for the configured operation.

This improves:

- reproducibility;
- debugging;
- support;
- testability;
- operator understanding.

## Suggested CLI Command Areas

```text
llm-youtube video inspect
llm-youtube comment build
llm-youtube reply target-comment
llm-youtube reply target-reply
llm-youtube reply scan-mine
llm-youtube reply triage
llm-youtube reply guided
llm-youtube review open
llm-youtube history list
llm-youtube scoreboard build
llm-youtube run inspect
llm-youtube config print
llm-youtube doctor
```

Final names should use the operator’s vocabulary consistently.

## Global CLI Capabilities

Where applicable:

```text
--output human|json
--progress auto|jsonl|none
--config FILE
--log-level LEVEL
--profile
--dry-run
```

Do not add flags solely to satisfy a pattern. Every flag must have clear product value.
