# Anti-Patterns to Avoid

## Microservices

Do not split this local desktop product into network services.

## Generic Plugin Framework

Do not build a plugin system before a real external extension requirement exists.

A registry for built-in writing options is sufficient.

## Giant Service Class

Do not create one class that retrieves data, applies policy, renders packets, writes files, and controls the GUI.

## GUI Business Logic

The GUI must not own targeting, ranking, parsing, packet construction, or workflow transitions.

## CLI as Internal Subprocess API

The GUI should not need to shell out to the CLI internally.

Both should use the same application layer.

## Global Mutable Configuration

Pass explicit configuration to commands and handlers.

## Boolean-Driven Workflow State

Do not model workflow state with combinations such as:

```text
is_running
has_packet
waiting
done
cancelled
has_result
```

Use an explicit state machine.

## Dictionary Soup

Do not pass large untyped dictionaries through the system.

Use typed domain models.

## Event Sourcing for Everything

The application needs structured operational events, not a full event-sourced architecture.

## Database Before Need

Do not introduce a database merely to look production-grade.

Use the simplest storage format that satisfies integrity and query needs.

## `utils.py` Dumping Ground

Every module should have one clear responsibility.

## One Universal Pipeline

Comment packets, targeted replies, operator-thread triage, and history measurement share components but are distinct use cases.

Do not force them into one giant orchestration function.

## Repeated Render-and-Shrink

Measure and allocate before rendering.

## Silent Fallback

Refuse rather than guess when:

- answer extraction fails;
- target resolution is ambiguous;
- retrieval is incomplete;
- history is corrupt;
- a prompt placeholder is unresolved.

## Multiple Answers to One State Question

Define one authoritative answer for:

- is work running;
- is cancellation requested;
- is commit active;
- what step comes next;
- may the application close.
