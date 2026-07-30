"""Structured state, replacing booleans and free text.

Every enum here is a ``str`` enum whose *values* are the strings the legacy
pipeline already used. That is deliberate and load-bearing: it means
``record["target_state"] == ReplyTargetKind.OWNER`` is true against data
produced by the ported functions, so the typed contract could be introduced
without invalidating the equivalence proof that the port is faithful.

The legacy representation of these was a boolean plus a human-readable note.
That is the specific pattern 08_ANTI_PATTERNS.md rules out: completeness is
structured state, and notes explain it rather than determine it. A caller
must never have to parse English to find out whether retrieval finished.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReplyTargetKind(str, Enum):
    """Who a reply is answering.

    Four states, not two. UNRESOLVABLE exists because a mention naming
    somebody absent from the thread cannot be classified either way, and
    guessing "side exchange" made legitimate replies disappear from the queue.
    """

    OWNER = "owner"
    OTHER_PARTICIPANT = "other"
    UNRESOLVABLE = "unknown"
    OWNER_REPLY = "owner_reply"


@dataclass(frozen=True)
class ReplyTargetResolution:
    """The full answer to "who is this reply for", with its reasoning."""

    kind: ReplyTargetKind
    target_channel_id: str = ""
    raw_mention: str = ""
    reason: str = ""

    @property
    def responds_to_owner(self) -> bool:
        return self.kind is ReplyTargetKind.OWNER


class CandidateStatus(str, Enum):
    """Whether a person is still owed an answer.

    UNCLEAR_AFTER_ANSWER is its own state on purpose. Folding it into
    RETURNED_AFTER_ANSWER drags the operator back in every time somebody he
    already answered joins a side conversation; folding it into ANSWERED hides
    a real follow-up posted under an unrecognised mention form. Both are
    wrong, in opposite directions.
    """

    NEVER_ANSWERED = "new"
    RETURNED_AFTER_ANSWER = "replied again"
    UNCLEAR_AFTER_ANSWER = "maybe replied again"
    ANSWERED = "answered"
    UNCLEAR_TARGET = "unclear target"

    @property
    def outstanding(self) -> bool:
        return self in (
            CandidateStatus.NEVER_ANSWERED,
            CandidateStatus.RETURNED_AFTER_ANSWER,
            CandidateStatus.UNCLEAR_AFTER_ANSWER,
            CandidateStatus.UNCLEAR_TARGET,
        )


class HistoryMatchStatus(str, Enum):
    """Whether a drafted reply was found on the channel.

    AMBIGUOUS is not UNMATCHED. One says the reply cannot be identified, the
    other says it is not there. Collapsing them puts an uncertain row under a
    heading that reads as a finding.
    """

    MATCHED = "matched"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"


class RetrievalStatus(str, Enum):
    """Whether the retrieval actually finished.

    This is the value that decides whether a scoreboard is allowed to say a
    draft was never posted. A truncated scan that does not admit it is
    truncated turns "I could not see it" into "it is not there", which is the
    single most consequential thing this application can get wrong.
    """

    COMPLETE = "complete"
    TOP_LEVEL_TRUNCATED = "top_level_truncated"
    REPLY_THREAD_TRUNCATED = "reply_thread_truncated"
    PAGE_TOKEN_LOOP = "page_token_loop"
    CANCELLED = "cancelled"

    @property
    def is_complete(self) -> bool:
        return self is RetrievalStatus.COMPLETE

    @property
    def may_conclude_absence(self) -> bool:
        """May a caller say "this reply is not on the channel"?

        Only a complete retrieval earns that. Everything else means the reply
        might be past the horizon that was actually fetched.
        """

        return self is RetrievalStatus.COMPLETE


@dataclass(frozen=True)
class RetrievalOutcome:
    """Retrieval status with the counts that justify it.

    The counts are part of the contract, not decoration: "truncated" without
    "12,000 of 47,000" gives the operator no way to judge how much is missing.
    """

    status: RetrievalStatus = RetrievalStatus.COMPLETE
    retrieved: int = 0
    reported_total: int | None = None
    api_operations_used: int = 0
    notes: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return self.status.is_complete

    @property
    def may_conclude_absence(self) -> bool:
        """May a caller say "this comment is not on the video"?

        Two conditions, not one. The status says every scan that ran finished;
        the shortfall says the numbers reconcile. A live run against a real
        video reported ``complete: true`` and ``missing: 18`` in the same
        breath, which is exactly the overstatement this model exists to
        prevent — the scans had finished, but a cap meant some replies were
        never requested at all.

        Erring toward "I cannot prove absence" is deliberate. A false
        incomplete costs the operator a glance; a false complete costs him the
        measurement.
        """

        return self.status.may_conclude_absence and not self.has_shortfall

    @property
    def missing(self) -> int | None:
        if self.reported_total is None:
            return None
        return max(0, self.reported_total - self.retrieved)

    @property
    def has_shortfall(self) -> bool:
        """Whether fewer items were seen than the source claims exist.

        Not automatically a bug: YouTube's own comment count is approximate
        and includes items that were deleted or held for review. It is still
        a reason not to claim absence.
        """

        return bool(self.missing)


class TranscriptAvailability(str, Enum):
    """Why there is or is not a transcript.

    The legacy pipeline had one boolean and a free-text error, so a caller
    that wanted to distinguish "this video has no captions" from "the caption
    library raised" had to match on English. These are the branches its own
    fetch function actually took.
    """

    AVAILABLE = "available"
    NOT_PUBLISHED = "not_published"
    NOT_PUBLIC = "not_public"
    LANGUAGE_UNAVAILABLE = "language_unavailable"
    EMPTY = "empty"
    FETCH_FAILED = "fetch_failed"

    @property
    def is_available(self) -> bool:
        return self is TranscriptAvailability.AVAILABLE


@dataclass(frozen=True)
class TranscriptResult:
    """A transcript, or a precise account of why there is none."""

    entries: tuple[dict, ...] = ()
    availability: TranscriptAvailability = TranscriptAvailability.NOT_PUBLISHED
    language: str = ""
    language_code: str = ""
    is_generated: bool | None = None
    source: str = ""
    detail: str = ""

    @property
    def available(self) -> bool:
        return self.availability.is_available


class WarningCode(str, Enum):
    """Warnings are not errors.

    A run that could not fetch a transcript still produced a packet. A run
    that could not record its drafts still saved the replies. Both must be
    reported without being failures, and a caller must be able to branch on
    which happened.
    """

    TRANSCRIPT_UNAVAILABLE = "transcript_unavailable"
    RETRIEVAL_INCOMPLETE = "retrieval_incomplete"
    HISTORY_NOT_RECORDED = "history_not_recorded"
    AMBIGUOUS_TARGET = "ambiguous_target"
    COMMENTS_DISABLED = "comments_disabled"


@dataclass(frozen=True)
class Warning_:
    """One non-fatal thing the operator needs to know about a run."""

    code: WarningCode
    message: str = ""


class OperationStatus(str, Enum):
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_WARNINGS = "succeeded_with_warnings"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class OperationResult:
    """What every application handler returns."""

    status: OperationStatus = OperationStatus.SUCCEEDED
    value: object = None
    warnings: list[Warning_] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (
            OperationStatus.SUCCEEDED,
            OperationStatus.SUCCEEDED_WITH_WARNINGS,
        )

    def warn(self, code: WarningCode, message: str = "") -> None:
        self.warnings.append(Warning_(code, message))
        if self.status is OperationStatus.SUCCEEDED:
            self.status = OperationStatus.SUCCEEDED_WITH_WARNINGS
