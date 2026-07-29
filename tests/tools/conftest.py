"""Put tools/ on the path for the tests in this directory.

tools/ holds standalone scripts, not a package, and installing it would say
something untrue about what it is. A conftest is where pytest expects this
arrangement to live; doing it inside the test module meant a test that
mutated global state as a side effect of being imported.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"

if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
