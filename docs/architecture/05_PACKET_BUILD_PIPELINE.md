# Packet Build Pipeline

## Implemented comment-build sequence

```text
validate and canonicalize the video
    ->
fetch video metadata
    ->
fetch relevance and recent comment samples
    ->
fetch bounded reply evidence
    ->
acquire one transcript result
    ->
select the default evidence sections
    ->
grow relevance and recent coverage while measured candidates fit
    ->
allocate the packet budget
    ->
render and validate once
    ->
stage packet, transcript, evidence, report, and run record
    ->
cooperative cancellation check
    ->
publish the complete run and its completion manifest
```

`inspect_video.handle()` returns the complete transcript result with its
inspection. `build_comment_packet.handle()` reuses that exact object for the
packet, warnings, transcript artifact, report, and `run.json`; one build never
asks the transcript port twice.

Normal run directories are first reserved by atomic directory creation, so
independent processes cannot select the same video-and-timestamp root.
Artifacts use atomic file replacement and the completion manifest is written
last. A reserved or interrupted directory therefore remains visibly
incomplete rather than validating as a published run. Replacement of an
existing owned set removes its completion marker before changing files,
writes the new completion manifest last, and restores the prior files after
a caught failure. Validators reject version-two runs whose manifest is
absent, incomplete, or does not match the published bytes.

## Reply, engage, and section-triage builds

A reply build assembles one packet per owner thread, enumerating every
non-owner response as an independent target with identity and relationship
fields. The exact-body guarantee inverts the comment path's measure-first
rule deliberately: the owner comment and target bodies are never truncated,
so the builder shrinks only the context replies, re-rendering the thread at
stepped context sizes until it fits — a bounded number of extra renders,
traded for exact bodies. A thread that cannot fit even with no context
refuses rather than truncating a target.

`reply engage` stages a stranger's comment as the first target of a
synthetic owner thread through the same builder, so budgeting, defanging,
identity, and validation have one implementation. `reply section-triage`
packages the whole retrieved section with ids, marking the operator's own
threads as non-targets.

Reply and triage runs commit six artifacts (packet, `evidence.json`,
transcript, `replies_to_me.csv`, `report.md`, `run.json`); engage and
section-triage runs commit their own smaller sets, and `run validate`
recognises every kind its producers write.

## Transcript policy

Remote caption sources run in preference order. A published caption ends the
search. A private video is terminal. A conclusive no-caption result stops
additional caption discovery. A previously saved transcript is reused before
local transcription is considered.

The GUI has three local-Whisper policies:

- `ignore` continues without a transcript and does not prompt;
- `ask` reports the caption outcome and waits for explicit approval;
- `automatic` starts local transcription without asking.

`ask` is the safe interactive default. CLI/configuration requests that
explicitly enable local transcription map to `automatic` for compatibility.
Cancellation is checked while approval is pending, during audio acquisition,
between completed Whisper segments, and before artifact publication.
Local Whisper also enforces independent operational limits in every policy:
the configured duration is rejected before audio transfer, the configured
byte ceiling is enforced by the download progress hook, the completed
temporary file is checked again, and the duration ceiling reaches
faster-whisper as a final CPU bound when metadata is absent or inaccurate.
Defaults are 60 minutes and 200 MiB. Automatic mode never bypasses them.

Normal GUI builds use this source order:

1. `youtube-transcript-api`;
2. published captions through `yt-dlp`, even when the first independent
   endpoint reported no published or empty captions;
3. a transcript saved by an earlier run;
4. local Whisper according to the selected policy.

The Transcript tab also exposes four one-run manual routes. Each manual route
constructs only the selected transcript provider and does not silently fall
through to another provider. The next normal Build returns to the full chain.

Every packet-producing run records transcript availability, immediate source,
original source, generated status, language and language code, entry count,
detail, originating run, and every caption-source attempt. Reuse therefore
records `saved-transcript` as the immediate route without erasing whether the
original evidence was a published caption, YouTube-generated caption, local
Whisper result, or legacy evidence with unknown provenance.

The model-facing packet carries the availability, immediate acquisition
route, original source, language, generated status, and entry count. It also
points to `evidence.json`, `run.json`, and `transcript_timestamped.txt`, which
are committed beside it. Live builds and offline rebuilds construct this block
from the same normalized provenance fields; a rebuild identifies its immediate
route as saved rebuild evidence while retaining the original source.

## GUI run ownership

The GUI builder returns a comment-run context containing:

- the rendered packet;
- canonical video metadata;
- the exact artifact store used for the packet build;
- the committed packet path;
- the run record.

The answer session reuses that store. `comment_drafts.md` is committed in the
same directory as `packet.md` and `run.json`; raw URL input is never reused as
a directory identifier.

The window renders a compact receipt from the same run record. It shows the
video, comment/reply evidence counts, transcript source and language, logical
YouTube Data API operation count, packet size, and output location. One
operation is one adapter call; transport retries are deliberately not counted
as additional operations. No second retrieval is performed to build the
receipt. Retrieval messages appear in the Activity tab. Published captions
and completed live-Whisper segments appear in the Transcript tab. Metadata,
description, comments, and replies have separate read-only views and explicit
copy actions; these views reuse the evidence already acquired for the build.

## Evidence and budget rules

Protected evidence includes the selected target, relevant thread context, and
facts required to understand the exchange. Reducible evidence includes
transcript excerpts, lower-priority surrounding comments, redundant metadata,
and secondary examples.

The default section caps are floors for ordinary builds, not permanent
ceilings. A pure fitting step grows relevance and recent caps, asks the
allocator whether each measured selection fits, and stops before the next
candidate would violate the body, description, or transcript floors. It never
renders trial packets. Growth also stops when a larger cap would only relabel
comments already present rather than increase unique coverage. Both live
builds and offline rebuilds call this same fitting step.

The rendered reduction summary reports final eligible-versus-included counts,
shortened bodies, and transcript reduction. Those final counts are the
acceptance evidence that adaptive growth actually reached packet output.

All YouTube-controlled text stays inside explicit untrusted-evidence markers.
Content that could impersonate packet structure is defanged before rendering.

## Commit and cancellation

Artifacts are staged and committed as one set. Filesystem publication restores
previous owned files if a write fails. GUI cancellation reaches the YouTube
adapter before each request, is checked before transcript acquisition, and is
checked again immediately before publication.

History is separate from packet commitment. Accepting and saving a draft does
not claim it was posted. Only an explicit **Record as posted** action writes
the engagement history.
