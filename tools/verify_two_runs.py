"""Run the suite twice and prove the two runs are identical where it matters.

"Identical" means the same collected test identities and the same per-test
outcomes. It deliberately does NOT mean identical timings, temporary paths or
duration output, all of which vary between runs for reasons that say nothing
about correctness.

Zero skips is enforced separately: a skip is a test that did not run, and the
legacy suite hid a broken Tk installation behind one for as long as it existed.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run_once(label: str) -> dict[str, str]:
    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rA"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    outcomes: dict[str, str] = {}
    for line in finished.stdout.splitlines():
        # Node IDs contain spaces when a parameter does, so this takes the
        # rest of the line rather than one whitespace-delimited token. An
        # earlier version used \S+ and silently dropped nine tests from the
        # gate, which is precisely the kind of quiet undercount this script
        # exists to prevent.
        found = re.match(
            r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(.+::.+)$", line
        )
        if found:
            outcomes[found.group(2).strip()] = found.group(1)
    tail = [l for l in finished.stdout.splitlines() if " passed" in l or " failed" in l]
    summary = tail[-1].strip() if tail else ""
    print(f"{label}: {summary}  ({len(outcomes)} identities parsed)")

    # The parsed count must match what pytest reported, or the gate is
    # checking a subset without saying so.
    reported = sum(int(n) for n in re.findall(
        r"(\d+) (?:passed|failed|error|skipped|xfailed|xpassed)", summary))
    if reported and reported != len(outcomes):
        raise SystemExit(
            f"{label}: pytest reported {reported} tests but {len(outcomes)} "
            f"identities were parsed. The gate would be checking a subset."
        )
    return outcomes


first = run_once("run 1")
second = run_once("run 2")

problems: list[str] = []

if not first:
    problems.append("run 1 reported no per-test outcomes at all")

if set(first) != set(second):
    only_first = sorted(set(first) - set(second))
    only_second = sorted(set(second) - set(first))
    problems.append(
        f"collected identities differ: {len(only_first)} only in run 1 "
        f"{only_first[:5]}, {len(only_second)} only in run 2 {only_second[:5]}"
    )

changed = [
    f"{node}: {first[node]} -> {second[node]}"
    for node in sorted(set(first) & set(second))
    if first[node] != second[node]
]
if changed:
    problems.append(f"{len(changed)} outcomes changed between runs: {changed[:5]}")

for label, outcomes in (("run 1", first), ("run 2", second)):
    bad = {n: o for n, o in outcomes.items()
           if o in ("FAILED", "ERROR")}
    if bad:
        problems.append(f"{label} has {len(bad)} product failures: {list(bad)[:5]}")
    skipped = [n for n, o in outcomes.items() if o == "SKIPPED"]
    if skipped:
        problems.append(f"{label} has {len(skipped)} skips: {skipped[:5]}")

print()
print(f"collected identities  {len(first)} (run 1), {len(second)} (run 2)")
print(f"identical identities  {set(first) == set(second)}")
print(f"identical outcomes    {not changed}")
print(f"product failures      {sum(1 for o in first.values() if o in ('FAILED', 'ERROR'))}")
print(f"skips                 {sum(1 for o in first.values() if o == 'SKIPPED')}")
print()

if problems:
    for problem in problems:
        print(f"PROBLEM  {problem}")
    raise SystemExit(1)
print("GATE PASSED: two consecutive runs, identical identities and outcomes, "
      "zero product failures, zero skips.")
