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
measure and select evidence
    ->
allocate the packet budget
    ->
render and validate once
    ->
stage packet, transcript, evidence, report, and run record
    ->
cooperative cancellation check
    ->
commit the run atomically
```

`inspect_video.handle()` returns the complete transcript result with its
inspection. `build_comment_packet.handle()` reuses that exact object for the
packet, warnings, transcript artifact, report, and `run.json`; one build never
asks the transcript port twice.

## Transcript policy

Remote caption sources run in preference order. A published caption ends the
search. A private video is terminal. A conclusive no-caption result stops
additional caption discovery, but an explicitly enabled local Whisper
fallback may then transcribe the audio. Local transcription is off by default.

Every result records its source. A reused saved transcript and a newly fetched
caption are therefore distinguishable in `run.json`.

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
receipt.

## Evidence and budget rules

Protected evidence includes the selected target, relevant thread context, and
facts required to understand the exchange. Reducible evidence includes
transcript excerpts, lower-priority surrounding comments, redundant metadata,
and secondary examples.

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
