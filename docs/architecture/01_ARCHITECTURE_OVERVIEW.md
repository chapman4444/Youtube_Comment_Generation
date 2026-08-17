# Architecture Overview

## Recommended Structure

The best fit for this application is:

```text
Modular monolith
+ Ports and adapters
+ Functional core / imperative shell
+ Vertical use-case slices
+ Explicit finite-state machines
```

This provides strong internal boundaries without the operational overhead of microservices.

## Why a Modular Monolith

This is one desktop application with shared domain rules and several related workflows.

A modular monolith keeps:

- one installation;
- one source repository;
- one configuration system;
- one release artifact;
- one local runtime;
- one coherent test suite.

It still permits strict internal boundaries.

Microservices would add deployment, network, serialization, and failure complexity without providing a useful product benefit.

## Dependency Direction

```text
CLI ─────┐
         ├──> Application services ───> Domain
GUI ─────┘             │
                       v
                     Ports
                       ^
                       │
               Infrastructure adapters
```

The domain layer must not import:

- GUI frameworks;
- CLI parsers;
- HTTP clients;
- transcript libraries;
- clipboard libraries;
- operating-system launch helpers.

## Major Layers

### Domain

Pure business rules:

- mention parsing;
- target resolution;
- answered-state reconstruction;
- candidate eligibility;
- candidate ranking;
- packet budgeting;
- history matching;
- retrieval certainty;
- workflow transitions.

### Application

Use-case orchestration:

- build a comment packet;
- build a thread-level batch reply packet;
- engage a stranger's thread;
- triage a whole comment section;
- scan the operator’s threads;
- run triage;
- run a guided drafting session;
- build a scoreboard;
- inspect and validate runs;
- render debug bundles.

### Ports

Interfaces required by the application:

- YouTube access;
- transcript access;
- clipboard;
- artifact storage;
- history storage;
- settings;
- clock;
- event sink.

### Infrastructure

Real implementations:

- YouTube Data API adapter;
- three caption adapters (transcript API, yt-dlp, local Whisper) behind a
  chained provider with saved-transcript reuse;
- system clipboard (Win32, so the contents outlive the process);
- filesystem artifact store with staged atomic commit;
- SQLite history store with one-time JSON migration;
- system clock and event sinks (text, JSONL, null);
- structured logging.

### Interfaces

User-facing adapters:

- CLI;
- GUI.

## One Command Model

Both interfaces should create the same typed application command.

```text
CLI arguments
    -> typed command
    -> application handler
    -> typed result
    -> CLI formatter
```

```text
GUI controls
    -> typed command
    -> application handler
    -> typed result
    -> GUI view
```

This gives real CLI/GUI parity without forcing the GUI to spawn shell processes internally.

## One-Line Rule

The core owns behavior. The CLI proves it. The GUI presents it.
