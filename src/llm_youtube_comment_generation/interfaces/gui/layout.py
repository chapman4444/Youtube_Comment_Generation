"""Display-independent sizing rules for the packet window."""

from __future__ import annotations

import re

MINIMUM_WIDTH = 1024
MINIMUM_HEIGHT = 700
PREFERRED_WIDTH = 1440
PREFERRED_HEIGHT = 850
_GEOMETRY = re.compile(r"^\d+x\d+(?:[+-]\d+[+-]\d+)?$")


def initial_size(screen_width: int, screen_height: int) -> tuple[int, int]:
    """Use most of the display without forcing the window off-screen."""

    available_width = max(800, int(screen_width) - 48)
    available_height = max(620, int(screen_height) - 88)
    width = min(
        available_width,
        max(MINIMUM_WIDTH, min(PREFERRED_WIDTH, int(screen_width * 0.82))),
    )
    height = min(
        available_height,
        max(MINIMUM_HEIGHT, min(PREFERRED_HEIGHT, int(screen_height * 0.80))),
    )
    return width, height


def valid_saved_geometry(value: str) -> bool:
    return bool(_GEOMETRY.fullmatch(str(value or "").strip()))
