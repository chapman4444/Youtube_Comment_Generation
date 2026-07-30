"""Structured logging that cannot leak the API key.

Redaction happens in a filter on the handler rather than at each call site.
A rule applied at call sites is a rule somebody forgets once, and once is
enough: a key in a log file is a key in the bug report the log gets pasted
into.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .external_errors import proxy_secret_values, sanitize_external_text

MINIMUM_SECRET_LENGTH = 8


class RedactingFilter(logging.Filter):
    """Removes registered secrets from every record that passes through.

    Short strings are never redacted: replacing a two-character secret would
    corrupt every message that happened to contain those characters, and the
    resulting log would be worse than one that leaked.
    """

    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self._proxy_urls: list[str] = []
        self._secrets = [
            str(secret) for secret in (secrets or [])
            if secret and len(str(secret)) >= MINIMUM_SECRET_LENGTH
        ]

    def add(self, secret: str) -> None:
        if secret and len(secret) >= MINIMUM_SECRET_LENGTH:
            self._secrets.append(secret)

    def add_proxy(self, proxy_url: str) -> None:
        if proxy_url:
            self._proxy_urls.append(proxy_url)
            for secret in proxy_secret_values(proxy_url):
                self.add(secret)

    def _clean(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        for proxy_url in self._proxy_urls:
            value = sanitize_external_text(value, proxy_url)
        for secret in self._secrets:
            value = value.replace(secret, "[redacted]")
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._clean(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._clean(v) for k, v in record.args.items()}
            else:
                record.args = tuple(self._clean(a) for a in record.args)

        # The traceback is the dangerous one and it is easy to miss: a key
        # passed as an argument appears in the exception's own message, and
        # formatters render exc_info long after any filter has run. Format it
        # here, clean it, and hand the formatter the cleaned text instead.
        if record.exc_info:
            record.exc_text = self._clean(
                logging.Formatter().formatException(record.exc_info)
            )
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self._clean(record.exc_text)
        return True


class JsonlFormatter(logging.Formatter):
    """One JSON object per line, for a log a machine can read."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # exc_text, not exc_info: the filter has already formatted and
        # redacted it. Re-formatting exc_info here would reintroduce the
        # unredacted traceback.
        if record.exc_text:
            payload["exception"] = record.exc_text
        elif record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure(level: str = "WARNING", secrets: list[str] | None = None,
              jsonl: bool = False, stream=None) -> RedactingFilter:
    """Install logging for one run and return the filter, so a caller can
    register a secret discovered later."""

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler = logging.StreamHandler(stream)
    if jsonl:
        handler.setFormatter(JsonlFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    redactor = RedactingFilter(secrets)
    handler.addFilter(redactor)
    root.addHandler(handler)
    root.setLevel(getattr(logging, str(level).upper(), logging.WARNING))
    return redactor
