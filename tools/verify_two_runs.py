"""Run the suite twice and prove both runs are complete, clean and identical.

"Identical" means the same collected test identities and the same per-test
outcomes. Timings, temporary paths and duration output are deliberately
ignored. Every collected test must be PASSED: skips, expected failures,
unexpected passes, failures and errors all make this release gate fail.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from collections.abc import Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTCOME_LINE = re.compile(
    r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(.+::.+)$"
)
SUMMARY_COUNT = re.compile(
    r"(\d+)\s+(?:passed|failed|errors?|skipped|xfailed|xpassed)\b"
)


class VerificationRunError(RuntimeError):
    """One pytest invocation cannot support a passing verification claim."""


def _bounded_tail(text: str, maximum: int = 1_500) -> str:
    cleaned = text.strip()
    if len(cleaned) <= maximum:
        return cleaned
    return "... " + cleaned[-maximum:]


def evaluate_run(
    label: str,
    finished: subprocess.CompletedProcess[str],
) -> tuple[dict[str, str], str]:
    """Validate one completed pytest process and return its identity map."""

    stdout = finished.stdout or ""
    stderr = finished.stderr or ""
    if finished.returncode != 0:
        detail = _bounded_tail(stderr or stdout) or "(no process output)"
        raise VerificationRunError(
            f"{label}: pytest exited {finished.returncode}; output: {detail}"
        )

    outcomes: dict[str, str] = {}
    for line in stdout.splitlines():
        found = OUTCOME_LINE.match(line)
        if found:
            outcomes[found.group(2).strip()] = found.group(1)

    summary_lines = [
        line.strip()
        for line in stdout.splitlines()
        if SUMMARY_COUNT.search(line)
    ]
    summary = summary_lines[-1] if summary_lines else ""
    reported = sum(int(count) for count in SUMMARY_COUNT.findall(summary))

    if not outcomes:
        raise VerificationRunError(
            f"{label}: no per-test outcomes were parsed"
        )
    if reported != len(outcomes):
        raise VerificationRunError(
            f"{label}: pytest reported {reported} tests but "
            f"{len(outcomes)} identities were parsed"
        )

    non_passes = {
        node: outcome
        for node, outcome in outcomes.items()
        if outcome != "PASSED"
    }
    if non_passes:
        sample = list(non_passes.items())[:5]
        raise VerificationRunError(
            f"{label}: {len(non_passes)} tests did not pass: {sample}"
        )
    return outcomes, summary


def run_once(label: str) -> dict[str, str]:
    finished = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rA"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    outcomes, summary = evaluate_run(label, finished)
    print(f"{label}: {summary}  ({len(outcomes)} identities parsed)")
    return outcomes


def compare_runs(
    first: Mapping[str, str],
    second: Mapping[str, str],
) -> tuple[str, ...]:
    problems: list[str] = []
    if set(first) != set(second):
        only_first = sorted(set(first) - set(second))
        only_second = sorted(set(second) - set(first))
        problems.append(
            f"collected identities differ: {len(only_first)} only in run 1 "
            f"{only_first[:5]}, {len(only_second)} only in run 2 "
            f"{only_second[:5]}"
        )
    changed = [
        f"{node}: {first[node]} -> {second[node]}"
        for node in sorted(set(first) & set(second))
        if first[node] != second[node]
    ]
    if changed:
        problems.append(
            f"{len(changed)} outcomes changed between runs: {changed[:5]}"
        )
    return tuple(problems)


def main() -> int:
    try:
        first = run_once("run 1")
        second = run_once("run 2")
    except VerificationRunError as exc:
        print(f"PROBLEM  {exc}")
        return 1

    problems = compare_runs(first, second)
    print()
    print(f"collected identities  {len(first)} (run 1), {len(second)} (run 2)")
    print(f"identical identities  {set(first) == set(second)}")
    print(f"identical outcomes    {not problems}")
    print("non-passing outcomes  0")
    print()
    if problems:
        for problem in problems:
            print(f"PROBLEM  {problem}")
        return 1
    print(
        "GATE PASSED: two consecutive runs, identical identities, "
        "every collected test passed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
