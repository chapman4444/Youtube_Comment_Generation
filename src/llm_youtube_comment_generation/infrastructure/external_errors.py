"""Sanitize untrusted provider failures before they enter application state."""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit

USERINFO_URL = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s@]+)@"
)


def proxy_secret_values(proxy_url: str) -> tuple[str, ...]:
    """Credential spellings that an external library may echo."""

    text = str(proxy_url or "").strip()
    if not text:
        return ()
    values = {text}
    try:
        parsed = urlsplit(text)
    except ValueError:
        return tuple(values)
    for value in (parsed.username, parsed.password):
        if not value:
            continue
        decoded = unquote(value)
        values.update({
            value,
            decoded,
            quote(decoded, safe=""),
        })
    return tuple(sorted(values, key=len, reverse=True))


def sanitize_external_text(
    value: object,
    proxy_url: str = "",
    *,
    limit: int | None = None,
) -> str:
    """Remove proxy user-information from one external diagnostic string."""

    text = str(value or "")
    text = USERINFO_URL.sub(r"\1[credentials-redacted]@", text)
    for secret in proxy_secret_values(proxy_url):
        if secret == proxy_url:
            continue
        if len(secret) >= 4:
            text = re.sub(
                re.escape(secret),
                "[redacted]",
                text,
                flags=re.IGNORECASE,
            )
    text = next(
        (line.strip() for line in text.splitlines() if line.strip()),
        "",
    )
    if limit is not None and len(text) > limit:
        text = text[: max(0, limit - 3)].rstrip() + "..."
    return text


def sanitize_external_error(
    error: BaseException,
    proxy_url: str = "",
    *,
    limit: int = 200,
) -> str:
    """Keep an exception type and bounded useful text, never credentials."""

    detail = sanitize_external_text(error, proxy_url, limit=limit)
    return f"{type(error).__name__}: {detail}".rstrip(": ")
