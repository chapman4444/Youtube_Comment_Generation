# Core Domain Models

## Identity Value Objects

Use explicit ID types rather than raw strings everywhere.

```text
VideoId
CommentId
ReplyId
ChannelId
RunId
OperationId
```

These prevent accidental comparisons between unrelated identifiers.

## Core Entities

### Video

```text
Video
    video_id
    title
    description
    channel_id
    published_at
```

### Comment

```text
Comment
    comment_id
    video_id
    author_channel_id
    author_display_name
    text
    like_count
    published_at
```

### Reply

```text
Reply
    reply_id
    parent_comment_id
    author_channel_id
    author_display_name
    text
    like_count
    published_at
```

### Thread

```text
Thread
    top_level_comment
    ordered_replies
    participants_by_channel_id
    inferred_targets
    owner_answers_by_target
```

YouTube replies remain a flat ordered list. Do not fake nested reply trees.

## Target Resolution

```text
ReplyTargetKind
    OWNER
    OTHER_PARTICIPANT
    UNRESOLVABLE
```

```text
ReplyTargetResolution
    kind
    target_channel_id optional
    raw_mention optional
    reason
```

Unresolvable targeting must remain visible.

## Candidate Status

```text
CandidateStatus
    NEVER_ANSWERED
    RETURNED_AFTER_ANSWER
    UNCLEAR_AFTER_ANSWER
    ANSWERED
```

Answered state is calculated per owner thread.

Participants are keyed by channel ID, not display name.

## Retrieval Status

```text
RetrievalStatus
    COMPLETE
    TOP_LEVEL_TRUNCATED
    REPLY_THREAD_TRUNCATED
    PAGE_TOKEN_LOOP
    CANCELLED
```

Completeness is structured state. Human-readable notes explain it but do not determine it.

## History Match Status

```text
HistoryMatchStatus
    MATCHED
    UNMATCHED
    AMBIGUOUS
```

Matching rules:

1. Resolve exact normalized matches globally.
2. Consume matched live items.
3. Apply conservative fallback matching only to remaining items.
4. Never assign one live item to multiple history rows.
5. Preserve ambiguity explicitly.

## Packet Models

```text
PacketSection
    section_id
    content
    measured_size
    protected
    reduction_priority
```

```text
PacketAllocation
    total_budget
    allocated_sections
    omitted_sections
    truncation_notes
```

## Writing Options

```text
RegisterDefinition
    id
    display_name
    category
    description
    prompt_directive
    required_output_heading
    waives_analysis
```

```text
DialDefinition
    id
    display_name
    allowed_values
    default_value
    prompt_template
```

CLI choices, GUI controls, prompt instructions, output headings, and validation must all derive from these definitions.

```text
WritingPreset
    name
    description
    comment_variations
    reply_variations
    dials
    length
    custom_length
    builtin
```

Presets contain prose choices only. Personal identity, videos, paths, proxies,
retrieval limits, and credentials are outside the model and cannot be
serialized into a custom preset.

## Composition Ports

`PortBundle` provides typed attributes for the YouTube, transcript, clipboard,
and event ports while retaining mapping access for existing injected fakes.

## Typed Results

```text
OperationResult
    status
    value
    warnings
    artifacts
    metrics
```

Warnings are not errors.

Examples:

```text
TRANSCRIPT_UNAVAILABLE
RETRIEVAL_INCOMPLETE
HISTORY_NOT_RECORDED
AMBIGUOUS_TARGET
```
