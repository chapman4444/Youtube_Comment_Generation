# Recommended Design Patterns

## Modular Monolith

Use for the overall application.

One installable product with strict internal module boundaries.

## Ports and Adapters

Use for:

- YouTube API;
- transcripts;
- clipboard;
- storage;
- settings;
- clock;
- event output.

This enables real and fake implementations without changing domain logic.

## Functional Core / Imperative Shell

Use pure functions for:

- target resolution;
- answered-state reconstruction;
- ranking;
- packet budgeting;
- history matching;
- output extraction.

Use the imperative shell for:

- API calls;
- filesystem writes;
- clipboard operations;
- progress emission.

## Vertical Use-Case Slices

Organize application behavior around real operations:

- build comment packet;
- build thread-level batch reply packet;
- engage a stranger's thread;
- triage a whole comment section;
- scan operator threads;
- run triage;
- run guided session;
- build scoreboard;
- inspect and validate runs.

## Command Pattern

Use typed commands so CLI and GUI invoke the same behavior.

## Finite-State Machine

Use for the guided workflow.

Keep workflow state separate from worker lifecycle.

## Pipeline

Use for evidence acquisition and packet construction.

## Strategy Registry

Use for writing registers and dials.

Definitions should drive CLI, GUI, prompts, headings, and validation.

## Repository Pattern

Use for:

- history;
- settings;
- run artifacts.

Do not expose path and serialization details throughout the application.

## Unit of Work

Use for staged output commit and rollback.

## Specification Pattern

Use for candidate eligibility and ranking.

Separate:

```text
who qualifies
```

from:

```text
how qualified candidates are ranked
```

## Immutable Records

Use frozen dataclasses or equivalent typed immutable models for facts.

## Structured Results and Errors

Use typed warnings and errors so CLI, GUI, and tests all interpret outcomes consistently.
