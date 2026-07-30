# Guided Workflow State Machine

## Purpose

The guided comment/reply workflow must have one explicit authoritative state machine.

Do not infer workflow state from scattered booleans, worker references, pending objects, or GUI fields.

## Workflow States

```text
IDLE
ACQUIRING_EVIDENCE
TRIAGE_PACKET_READY
AWAITING_TRIAGE_ANSWER
TARGETS_SELECTED
PERSON_PACKET_READY
AWAITING_PERSON_ANSWER
ANSWER_REJECTED
DRAFT_ACCEPTED
REVIEW_READY
COMPLETE
CANCELLING
CANCELLED
FAILED
```

## Worker Lifecycle

Keep worker lifecycle separate from workflow phase.

```text
IDLE
RUNNING
CANCELLING
COMMITTING
FINISHED
```

A workflow may be waiting for a human answer while no worker exists.

## Intents

```text
START
COPY_CURRENT_PACKET
SUBMIT_TRIAGE_ANSWER
SELECT_TARGETS
SUBMIT_PERSON_ANSWER
SKIP_PERSON
RETRY_CURRENT_PERSON
CANCEL
SAVE
OPEN_REVIEW
```

## Transition Examples

| Current state | Intent | Result |
|---|---|---|
| `IDLE` | `START` | `ACQUIRING_EVIDENCE` |
| `TRIAGE_PACKET_READY` | `COPY_CURRENT_PACKET` | no state change |
| `AWAITING_TRIAGE_ANSWER` | valid triage answer | `TARGETS_SELECTED` |
| `AWAITING_TRIAGE_ANSWER` | invalid answer | no state change |
| `PERSON_PACKET_READY` | copy | no state change |
| `AWAITING_PERSON_ANSWER` | valid answer | `DRAFT_ACCEPTED` |
| `AWAITING_PERSON_ANSWER` | invalid answer | `ANSWER_REJECTED` |
| any cancellable state | `CANCEL` | `CANCELLING` |

## Invariants

- Copying never advances state.
- Invalid answer parsing never advances state.
- Packet text cannot be accepted as an answer.
- Every accepted draft is saved immediately.
- Accepting a draft never implies posting it.
- Recording a posting is explicit, confirmed, idempotent, and reflected in
  the saved review artifact.
- Exactly one layer owns transitions.
- CLI and GUI submit intents; they do not set state directly.
- Exactly one next action is exposed during a guided run.
- The application cannot close while commit-critical work is active.

## State Object

A workflow state record should contain:

```text
phase
worker_lifecycle
current_target_id
current_packet_id
current_index
total_targets
accepted_draft_count
last_warning
last_error
next_allowed_actions
commit_critical
cancellation_requested
```

## Test Requirements

- Every legal transition.
- Every illegal transition.
- Copy-only actions.
- Invalid answer behavior.
- Resume behavior.
- Cancellation behavior.
- Commit-critical close behavior.
- Complete scripted multi-person run.
- Partial-progress preservation.
