"""The real YouTube Data API adapter.

The adapter absorbs the API so the port does not have to. Pagination, page
tokens, retry, quota accounting and HTTP status codes all stop here; what
crosses the boundary is comments plus a ``RetrievalOutcome`` that says
honestly whether those were all of them.

Read-only by construction: an API key grants no write capability, and there
is no method here that posts.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..domain.comments import parse_comment_item
from ..domain.errors import ConfigurationError, OperationCancelled, classify_api_error
from ..domain.statuses import RetrievalOutcome, RetrievalStatus
from ..domain.video import as_int, parse_video_item
from ..ports.youtube import CommentPage

LOGGER = logging.getLogger(__name__)

API_BASE_URL = "https://www.googleapis.com/youtube/v3"
REQUEST_TIMEOUT = (10, 30)
USER_AGENT = "llm-youtube-comment-generation/0.1"

# A page is 100 items, so this bounds one thread's retrieval at 3,000 replies.
# The cap exists because a runaway thread would otherwise spend the whole
# day's quota on one conversation.
MAX_PAGE_REQUESTS = 30


def build_session(proxy_url: str = "") -> requests.Session:
    """An HTTPS session that retries the failures worth retrying.

    5xx and 429 are retried; 4xx is not, because a bad request will be just
    as bad the second time and retrying a 403 burns quota confirming it.
    """

    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": USER_AGENT})
    if proxy_url:
        session.proxies.update({"https": proxy_url, "http": proxy_url})
    return session


class YouTubeAdapter:
    """Implements YouTubePort against the real Data API."""

    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        if not api_key:
            raise ConfigurationError("A YouTube Data API key is required.")
        self._api_key = api_key
        self._session = session or build_session()
        self._cancelled = cancelled or (lambda: False)
        self._api_operations = 0

    # -- port surface ----------------------------------------------------

    @property
    def api_operations_used(self) -> int:
        """Logical API calls; transport-level retries are not counted."""

        return self._api_operations

    @property
    def requests_used(self) -> int:
        """Backward-compatible alias for pre-0.2 integrations."""

        return self.api_operations_used

    def video(self, video_id: str) -> dict[str, Any]:
        payload = self.get("videos", {
            "part": "snippet,contentDetails,statistics,status",
            "id": video_id,
        })
        items = payload.get("items") or []
        if not items:
            raise ConfigurationError(
                f"No video was found for {video_id}. It may be private, "
                "deleted, or the ID may be wrong."
            )
        return parse_video_item(video_id, items[0])

    def comment_threads(
        self,
        video_id: str,
        *,
        order: str = "relevance",
        maximum: int = 100,
    ) -> CommentPage:
        if maximum < 1:
            raise ConfigurationError("maximum comments must be at least 1.")
        collected: list[dict[str, Any]] = []
        notes: list[str] = []
        started = self._api_operations

        def page(token: str) -> dict[str, Any]:
            remaining = max(1, maximum - len(collected))
            return self.get("commentThreads", {
                "part": "snippet",
                "videoId": video_id,
                "order": order,
                "maxResults": min(100, remaining),
                "textFormat": "plainText",
                **({"pageToken": token} if token else {}),
            })

        status = self._paginate(
            page,
            lambda payload: self._absorb_threads(payload, collected, order),
            maximum=maximum,
            have=lambda: len(collected),
            notes=notes,
            truncation=RetrievalStatus.TOP_LEVEL_TRUNCATED,
        )
        return CommentPage(
            comments=collected[:maximum],
            outcome=RetrievalOutcome(
                status=status,
                retrieved=min(len(collected), maximum),
                reported_total=None,
                api_operations_used=self._api_operations - started,
                notes=tuple(notes),
            ),
        )

    def replies(self, parent_comment_id: str, *, maximum: int = 100) -> CommentPage:
        if maximum < 1:
            raise ConfigurationError("maximum replies must be at least 1.")
        collected: list[dict[str, Any]] = []
        notes: list[str] = []
        started = self._api_operations

        def page(token: str) -> dict[str, Any]:
            remaining = max(1, maximum - len(collected))
            return self.get("comments", {
                "part": "snippet",
                "parentId": parent_comment_id,
                "maxResults": min(100, remaining),
                "textFormat": "plainText",
                **({"pageToken": token} if token else {}),
            })

        def absorb(payload: dict[str, Any]) -> None:
            for item in payload.get("items") or []:
                collected.append(
                    parse_comment_item(item, parent_id=parent_comment_id)
                )

        status = self._paginate(
            page, absorb, maximum=maximum, have=lambda: len(collected),
            notes=notes, truncation=RetrievalStatus.REPLY_THREAD_TRUNCATED,
        )
        return CommentPage(
            comments=collected[:maximum],
            outcome=RetrievalOutcome(
                status=status,
                retrieved=min(len(collected), maximum),
                reported_total=None,
                api_operations_used=self._api_operations - started,
                notes=tuple(notes),
            ),
        )

    def channel_id_for_handle(self, handle: str) -> str:
        wanted = handle if handle.startswith("@") else "@" + handle
        payload = self.get("channels", {"part": "id", "forHandle": wanted})
        items = payload.get("items") or []
        if not items or not items[0].get("id"):
            raise ConfigurationError(f"No channel was found for handle: {wanted}")
        return str(items[0]["id"])

    # -- internals -------------------------------------------------------

    def _absorb_threads(
        self,
        payload: dict[str, Any],
        into: list[dict[str, Any]],
        order: str,
    ) -> None:
        for item in payload.get("items") or []:
            snippet = item.get("snippet") or {}
            top = snippet.get("topLevelComment") or {}
            record = parse_comment_item(top, order_source=order)
            record["total_reply_count"] = as_int(snippet.get("totalReplyCount")) or 0
            into.append(record)

    def _paginate(
        self,
        fetch_page: Callable[[str], dict[str, Any]],
        absorb: Callable[[dict[str, Any]], None],
        *,
        maximum: int,
        have: Callable[[], int],
        notes: list[str],
        truncation: RetrievalStatus,
    ) -> RetrievalStatus:
        """Walk pages, and say precisely why walking stopped.

        Every exit from this loop is a distinct RetrievalStatus. That is the
        whole point: "I stopped because I ran out of pages" and "I stopped
        because I hit my own limit" mean different things to a caller
        deciding whether a reply is genuinely absent.
        """

        token = ""
        seen_tokens: set[str] = set()
        for request_number in range(MAX_PAGE_REQUESTS):
            if self._cancelled():
                notes.append("cancelled before retrieval finished")
                return RetrievalStatus.CANCELLED

            payload = fetch_page(token)
            before = have()
            absorb(payload)
            retained = have()

            # maxResults is a request, not permission to trust the response.
            # If the API returns more than the remaining allowance, the public
            # method must trim the excess to honour its contract. That local
            # trim is itself proof that the scan is incomplete, even when the
            # response has no continuation token.
            if retained > maximum:
                notes.append(
                    f"the API returned {retained - before:,} items when only "
                    f"{maximum - before:,} remained within the requested "
                    f"limit of {maximum:,}; excess items were not retained"
                )
                return truncation

            if retained >= maximum:
                # Only truncation if there was more to come.
                if payload.get("nextPageToken"):
                    notes.append(
                        f"stopped at the requested limit of {maximum:,}; "
                        "more were available"
                    )
                    return truncation
                return RetrievalStatus.COMPLETE

            token = str(payload.get("nextPageToken") or "")
            if not token:
                return RetrievalStatus.COMPLETE

            # A repeated token means the API is looping us. Continuing would
            # spend quota forever collecting the same page.
            if token in seen_tokens:
                notes.append(
                    f"the API returned a repeated page token after "
                    f"{have():,} items; retrieval stopped to avoid a loop"
                )
                return RetrievalStatus.PAGE_TOKEN_LOOP
            seen_tokens.add(token)

        notes.append(
            f"stopped after {MAX_PAGE_REQUESTS} page requests with "
            f"{have():,} items retrieved; more remain"
        )
        return truncation

    def get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        """One API call. Translates HTTP into the domain error hierarchy."""

        if self._cancelled():
            raise OperationCancelled("Cancelled before the request was sent.")

        self._api_operations += 1
        response = self._session.get(
            f"{API_BASE_URL}/{resource}",
            params={**params, "key": self._api_key},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"error": {"message": response.text[:400]}}
            raise classify_api_error(resource, response.status_code, payload)
        try:
            return response.json()
        except ValueError as exc:
            raise classify_api_error(
                resource, response.status_code,
                {"error": {"message": "the response was not JSON"}},
            ) from exc
