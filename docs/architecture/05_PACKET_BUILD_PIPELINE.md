# Packet Build Pipeline

## Canonical Sequence

```text
validate
    ↓
resolve video
    ↓
acquire metadata
    ↓
acquire transcript
    ↓
acquire comments/replies
    ↓
normalize evidence
    ↓
measure sections
    ↓
allocate budget
    ↓
render once
    ↓
validate boundaries
    ↓
stage artifacts
    ↓
commit atomically
```

## Measure Before Rendering

Do not repeatedly render, inspect size, remove content, and render again.

Use:

```text
RawEvidence
    -> NormalizedEvidence
    -> MeasuredEvidence
    -> PacketAllocation
    -> RenderedPacket
    -> ValidatedPacket
    -> CommittedRun
```

## Protected Sections

Protected content may include:

- the operator’s own top-level comment;
- the selected target comment;
- the selected target reply;
- the relevant thread context;
- evidence required to understand the exchange.

Protected sections must not silently disappear under budget pressure.

## Reducible Sections

Possible reducible sections:

- transcript excerpts;
- lower-priority surrounding comments;
- redundant metadata;
- secondary examples.

A full transcript artifact can be written separately even when packet excerpts are reduced.

## Untrusted Evidence Boundary

All YouTube-controlled content remains inside explicit evidence markers:

- titles;
- descriptions;
- transcripts;
- display names;
- handles;
- comments;
- replies.

Defang content that could impersonate packet structure:

- evidence-boundary markers;
- code fences;
- markdown headings;
- packet-control tokens.

Nothing a commenter can author belongs in the trusted instruction region.

Use API-assigned identifiers outside the evidence boundary when a target must be referenced.

## Validation Before Commit

Validate:

- required prompt resources;
- allowed placeholders;
- final output checklist;
- evidence boundaries;
- no unfilled placeholders;
- no missing protected section;
- packet size;
- retrieval disclosures;
- artifact ownership.

## Staged Commit

```text
begin staging
write packet
write transcript
write evidence JSON
write report
validate staged artifacts
commit
```

On failure:

```text
rollback staging
preserve previous committed output
```

Primary deliverables outrank telemetry. History or logging failure must not invalidate an already committed packet or review file.
