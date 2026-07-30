"""Effective configuration, and where each value came from.

Precedence, lowest to highest:

    built-in defaults
      < settings file in the user config directory
      < --config FILE
      < environment variables
      < explicit command-line flags

Every resolved value remembers its origin. That is not a nicety: the most
common support question about a tool like this is "why did it do that", and
the answer is almost always that a setting came from somewhere the operator
had forgotten about.

Secrets are never written to a settings file. The API key is read from the
environment or from a path named in settings, and `config print` reports
whether a key resolved — never the key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..domain.errors import ConfigurationError
from ..domain.packets import DEFAULT_PACKET_CHARACTERS, MINIMUM_PACKET_CHARACTERS

SOURCE_DEFAULT = "built-in default"
SOURCE_SETTINGS = "settings file"
SOURCE_CONFIG_FILE = "--config file"
SOURCE_ENVIRONMENT = "environment"
SOURCE_FLAG = "command line"

PRECEDENCE = (
    SOURCE_DEFAULT,
    SOURCE_SETTINGS,
    SOURCE_CONFIG_FILE,
    SOURCE_ENVIRONMENT,
    SOURCE_FLAG,
)

DEFAULTS: dict[str, Any] = {
    "output_directory": "output",
    # Empty is resolved at the composition boundary to the operating
    # system's private per-user application-data directory.
    "state_directory": "",
    "packet_characters": DEFAULT_PACKET_CHARACTERS,
    "max_comments": 500,
    "max_replies_per_thread": 100,
    "transcript_languages": ("en",),
    "output_format": "human",
    "progress": "auto",
    "log_level": "WARNING",
    "editor": "",
    "proxy_url": "",
    # Who "mine" means. Every scan of the operator's own threads needs it, and
    # it is the same answer every time, so requiring it on the command line
    # made the guided run and the window cost two flags that never vary. A
    # flag still wins when it is given.
    "my_handle": "",
    "my_channel_id": "",
    # Reply mode searches for the operator's own comment among everyone
    # else's, which is a needle in a haystack: on a busy video his comment sat
    # past position 500 and the scan reported "complete" for the 500 it had
    # looked at, having never seen him. The comment packet's max_comments is a
    # different question -- how much evidence to gather -- so it stays where
    # it is and this is separate.
    "reply_scan_comments": 3000,
    # Transcribe the audio here when YouTube published no captions at all.
    # Off by default and deliberately so: every other source is one request,
    # and this is an audio download plus minutes of CPU. Spending that without
    # being asked would be a surprise in the middle of a packet build.
    "transcribe_locally": False,
    "whisper_model": "small.en",
}

# Which environment variable feeds which setting. Named explicitly rather
# than derived from the key, so adding a setting cannot silently start
# reading an environment variable somebody else already uses.
ENVIRONMENT_KEYS: dict[str, str] = {
    "output_directory": "YTCOMMENT_OUTPUT_DIR",
    "state_directory": "YTCOMMENT_STATE_DIR",
    "packet_characters": "YTCOMMENT_PACKET_CHARACTERS",
    "max_comments": "YTCOMMENT_MAX_COMMENTS",
    "log_level": "YTCOMMENT_LOG_LEVEL",
    "proxy_url": "YTCOMMENT_PROXY_URL",
    "editor": "YTCOMMENT_EDITOR",
    "my_handle": "YTCOMMENT_MY_HANDLE",
    "my_channel_id": "YTCOMMENT_MY_CHANNEL_ID",
    "transcribe_locally": "YTCOMMENT_TRANSCRIBE_LOCALLY",
    "whisper_model": "YTCOMMENT_WHISPER_MODEL",
    "reply_scan_comments": "YTCOMMENT_REPLY_SCAN_COMMENTS",
}

#: Settings whose value is a yes or a no. Without this "false" from a file or
#: an environment variable is a non-empty string and therefore true, which is
#: the classic way an off switch turns itself on.
BOOLEAN_SETTINGS = frozenset({"transcribe_locally"})
FALSE_WORDS = frozenset({"", "0", "false", "no", "off", "none"})

API_KEY_VARIABLES = ("YOUTUBE_API_KEY", "YTCOMMENT_API_KEY")

INTEGER_SETTINGS = frozenset({
    "packet_characters", "max_comments", "max_replies_per_thread",
    "reply_scan_comments",
})


@dataclass(frozen=True)
class Resolved:
    """One setting: its value, and where it came from."""

    value: Any
    source: str


class Configuration:
    """The effective settings for one run."""

    def __init__(self, resolved: Mapping[str, Resolved]) -> None:
        self._resolved = dict(resolved)

    def __getitem__(self, name: str) -> Any:
        return self._resolved[name].value

    def get(self, name: str, default: Any = None) -> Any:
        entry = self._resolved.get(name)
        return entry.value if entry else default

    def source_of(self, name: str) -> str:
        return self._resolved[name].source

    def items(self):
        return sorted(self._resolved.items())

    def as_dict(self) -> dict[str, Any]:
        return {name: entry.value for name, entry in self._resolved.items()}


def coerce(name: str, value: Any) -> Any:
    """Turn a string from a file or the environment into the right type."""

    if name in INTEGER_SETTINGS and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"{name} must be a whole number, got {value!r}."
            ) from exc
    if name == "transcript_languages" and isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if name in BOOLEAN_SETTINGS and not isinstance(value, bool):
        return str(value).strip().lower() not in FALSE_WORDS
    return value


def resolve(
    settings: Mapping[str, Any] | None = None,
    config_file: Mapping[str, Any] | None = None,
    environment: Mapping[str, str] | None = None,
    flags: Mapping[str, Any] | None = None,
) -> Configuration:
    """Apply the precedence chain and remember every origin.

    ``flags`` must contain only values the operator actually typed. An
    argument parser that fills in its own defaults would make every setting
    look like it came from the command line, which would make `config print`
    useless and silently defeat the settings file.
    """

    environment = os.environ if environment is None else environment
    resolved: dict[str, Resolved] = {
        name: Resolved(value, SOURCE_DEFAULT) for name, value in DEFAULTS.items()
    }

    for source, values in (
        (SOURCE_SETTINGS, settings or {}),
        (SOURCE_CONFIG_FILE, config_file or {}),
    ):
        for name, value in values.items():
            if name in resolved and value is not None:
                resolved[name] = Resolved(coerce(name, value), source)

    for name, variable in ENVIRONMENT_KEYS.items():
        raw = environment.get(variable)
        if raw not in (None, ""):
            resolved[name] = Resolved(coerce(name, raw), SOURCE_ENVIRONMENT)

    for name, value in (flags or {}).items():
        if value is not None and name in resolved:
            resolved[name] = Resolved(coerce(name, value), SOURCE_FLAG)

    validate(resolved)
    return Configuration(resolved)


def validate(resolved: Mapping[str, Resolved]) -> None:
    """Refuse a configuration that cannot produce a usable run."""

    budget = resolved["packet_characters"].value
    if budget < MINIMUM_PACKET_CHARACTERS:
        raise ConfigurationError(
            f"packet_characters is {budget:,}, below the smallest packet this "
            f"tool can actually assemble ({MINIMUM_PACKET_CHARACTERS:,}). "
            f"Set it from {resolved['packet_characters'].source}."
        )
    if resolved["max_comments"].value < 1:
        raise ConfigurationError("max_comments must be at least 1.")
    if resolved["reply_scan_comments"].value < 1:
        raise ConfigurationError("reply_scan_comments must be at least 1.")
    if resolved["max_replies_per_thread"].value < 1:
        raise ConfigurationError(
            "max_replies_per_thread must be at least 1."
        )
    if resolved["output_format"].value not in ("human", "json"):
        raise ConfigurationError(
            f"output_format must be human or json, got "
            f"{resolved['output_format'].value!r}."
        )
    if resolved["progress"].value not in ("auto", "jsonl", "none"):
        raise ConfigurationError(
            f"progress must be auto, jsonl or none, got "
            f"{resolved['progress'].value!r}."
        )


def resolve_api_key(
    environment: Mapping[str, str] | None = None,
    key_file: str | Path = "",
) -> str:
    """Find the API key, without ever putting it in a settings file.

    Returns an empty string when nothing resolved. The caller decides whether
    that is fatal: `doctor` reports it, a real command refuses.
    """

    environment = os.environ if environment is None else environment
    for variable in API_KEY_VARIABLES:
        value = str(environment.get(variable) or "").strip()
        if value:
            return value

    if key_file:
        path = Path(key_file).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()

    return ""


def redact(text: str, *secrets: str) -> str:
    """Remove credentials from anything about to be shown or logged.

    Short strings are ignored deliberately: redacting a two-character secret
    would corrupt every message that happened to contain those characters.
    """

    cleaned = str(text)
    for secret in secrets:
        secret = str(secret or "")
        if len(secret) >= 8:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned
