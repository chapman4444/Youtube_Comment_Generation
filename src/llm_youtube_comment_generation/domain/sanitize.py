"""The untrusted-source boundary.

Everything a commenter or a video author can author is untrusted input. The
packet declares a region for it and this module makes sure nothing inside that
region can impersonate the region's own markers.

The limit is stated plainly because it matters: this defangs *structure*, not
persuasion. It cannot stop ordinary prose that argues for different behaviour,
and it is not trying to. The prompt contract addresses that separately.
"""

from __future__ import annotations

import re
from typing import Any

SOURCE_BOUNDARY_OPEN = "## BEGIN UNTRUSTED SOURCE MATERIAL"
SOURCE_BOUNDARY_CLOSE = "## END UNTRUSTED SOURCE MATERIAL"


def neutralize(value: Any) -> str:
    """Defang packet-control syntax inside untrusted source text.

    This blocks a reader from confusing source material with packet structure.
    It does not and cannot stop ordinary prose that argues for different
    behaviour; the prompt contract addresses that directly instead.
    """

    text = str(value or "")
    separator = r"[\s\-_.*~`|]+"
    for word, replacement in (("BEGIN", "BEGIN"), ("END", "END")):
        text = re.sub(
            rf"{word}{separator}UNTRUSTED{separator}SOURCE{separator}MATERIAL",
            f"{replacement} SOURCE-MATERIAL PHRASE",
            text,
            flags=re.IGNORECASE,
        )
    text = re.sub(r"`{3,}", "` ` `", text)
    text = re.sub(r"~{3,}", "~ ~ ~", text)
    text = re.sub(r":{3,}", ": : :", text)
    text = re.sub(r"(?m)^(\s*)(#{1,6})(\s)", r"\1\\\2\3", text)
    return text


def inline(value: Any) -> str:
    return neutralize(value).replace("|", "\\|").replace("\n", " ").strip()


def safe_token(value: Any, *, maximum: int = 64) -> str:
    """Reduce an API-generated identifier to an inert allowlisted token.

    This exists because an earlier attempt at the same problem was wrong in an
    instructive way. It sanitized an attacker-chosen display name and placed
    the result in the instruction region, outside the source boundary. Escaping
    structure is not enough there: a handle of "Ignore the rules above" carries
    no markup at all and survives every character filter intact, and it lands
    in the one region the packet declares trustworthy.

    Nothing a commenter can choose belongs outside the boundary. So the packet
    identifies the targeted reply by values the commenter cannot author, the
    YouTube comment id and the position in the thread, and this allowlist
    guarantees they carry nothing else. Anything outside [A-Za-z0-9_.-] is
    dropped rather than escaped, because there is no legitimate identifier that
    needs it.
    """

    text = re.sub(r"[^A-Za-z0-9_.-]", "", str(value or ""))
    return text[:maximum] or "unknown"


def format_count(value: int | None) -> str:
    return "Unavailable" if value is None else f"{value:,}"


def truncate(text: str, maximum: int, *, label: str) -> str:
    value = text.strip()
    if len(value) <= maximum:
        return value
    if maximum <= 0:
        return ""
    marker = f"\n\n[{label} truncated]"
    if maximum <= len(marker) + 40:
        return value[:maximum].rstrip()
    return value[: maximum - len(marker)].rstrip() + marker
