# CLI and GUI Contract

## Shared application boundary

CLI and GUI inputs resolve into the same application commands and sessions.
The GUI does not reimplement packet selection, answer extraction, workflow
transitions, history matching, or artifact publication.

```text
CLI arguments or GUI form
    ->
resolved options
    ->
typed application command
    ->
application handler and ports
    ->
typed result or run context
    ->
CLI formatter or GUI view
```

## Option precedence

The window resolves values in this order:

```text
built-in default
    < saved window setting
    < resolved non-default configuration
    < explicit command-line flag
```

Comment evidence depth and reply discovery depth are separate values:

- comment `--max-comments` controls comment evidence retrieval;
- reply `--max-comments` overrides `reply_scan_comments`;
- the GUI reply scan uses `reply_scan_comments`, never the comment packet's
  `max_top`;
- `max_replies_per_thread` controls bounded per-thread reply retrieval.

Every exposed window flag is projected into the model. Unsupported flags are
not silently accepted.

## Writing presets

A `WritingPreset` contains only reusable prose choices:

- comment and reply registers;
- dial selections;
- length and optional target words.

Built-ins are immutable. Custom presets are atomically stored in the private
application-state directory and may replace another custom preset with the
same case-insensitive name. A preset can never carry a video, handle, channel
ID, proxy, output path, retrieval count, or credential.

## Dry-run

Non-windowed `comment build --dry-run` performs no network request, artifact
commit, or clipboard write. `--window --dry-run` is rejected before opening a
window because an interactive Build action would otherwise be ambiguous.

## GUI work and cancellation

The packet window opens before retrieval. Work begins only when the operator
presses Build or starts a reply scan. External work runs on a background
thread and cancellation is cooperative:

- the YouTube adapter checks before every request and page;
- application events check between major steps;
- transcript acquisition and artifact publication have explicit safe points.

## Manual posting and history

The application has no YouTube write scope and never posts. Model-answer
acceptance writes `comment_drafts.md` or `replies_to_review.md`, but it does not
enter engagement history automatically.

After manually posting, the operator must confirm **Record as posted** in the
GUI or run:

```text
ytcomment history record VIDEO --workflow comment --draft-file comment.txt
ytcomment history record VIDEO --workflow reply --draft-file reply.txt \
  --target-comment-id COMMENT_ID --run-id RUN
```

SQLite uses a stable posting-event key for idempotency. Fuzzy normalized text
is retained only for later scoreboard matching, so identical text posted to
different targets remains distinct.

The GUI asks for confirmation using the exact latest accepted draft. After a
successful record, the review artifact marks that draft's posting record as
present and the action becomes unavailable for that draft.

## Scoreboard identity

Scoreboard builds require the operator's immutable channel ID, supplied
directly or resolved from a configured handle. Live comments and replies from
other channels are excluded before matching. Exact text is tried first;
bounded edit matching refuses short/common prefixes, preserves ambiguity, and
never consumes one live item twice. Posting context distinguishes top-level
comments from replies when history provides it.

## Private desktop state

Remembered window geometry, window options, custom presets, and SQLite history
live in the operating system's per-user state directory. Existing settings and
history beside the old output directory are copied forward on first use; the
legacy files are left untouched.

`ytcomment privacy check` audits Git's publishable file set. Review-package
creation runs the same audit against the staged allowlisted copy before
WinRAR is allowed to create the archive.

## Global capabilities

Implemented global options include:

```text
--output human|json
--progress auto|jsonl|none
--config FILE
--log-level LEVEL
--dry-run (on commands that expose it)
```

Do not advertise a parsed option until an executable path consumes it.
