from __future__ import annotations

import subprocess

import pytest

from tools.verify_two_runs import (
    VerificationRunError,
    compare_runs,
    evaluate_run,
)


def completed(
    returncode: int = 0,
    stdout: str = "PASSED tests/test_one.py::test_one\n1 passed in 0.01s\n",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        ["pytest"], returncode, stdout=stdout, stderr=stderr
    )


@pytest.mark.parametrize("returncode", range(1, 6))
def test_every_nonzero_pytest_exit_code_fails(returncode):
    with pytest.raises(
        VerificationRunError,
        match=rf"pytest exited {returncode}",
    ):
        evaluate_run("run 1", completed(returncode))


@pytest.mark.parametrize("outcome,summary_word", [
    ("SKIPPED", "skipped"),
    ("XFAIL", "xfailed"),
    ("XPASS", "xpassed"),
    ("FAILED", "failed"),
    ("ERROR", "error"),
])
def test_every_non_pass_outcome_fails_even_with_exit_zero(
    outcome,
    summary_word,
):
    result = completed(
        stdout=(
            f"{outcome} tests/test_one.py::test_one\n"
            f"1 {summary_word} in 0.01s\n"
        )
    )

    with pytest.raises(VerificationRunError, match="did not pass"):
        evaluate_run("run 1", result)


def test_zero_collected_tests_fails():
    with pytest.raises(VerificationRunError, match="no per-test outcomes"):
        evaluate_run("run 1", completed(stdout="no tests ran in 0.01s\n"))


def test_reported_and_parsed_counts_must_match():
    with pytest.raises(VerificationRunError, match="reported 2 tests"):
        evaluate_run(
            "run 1",
            completed(
                stdout=(
                    "PASSED tests/test_one.py::test_one\n"
                    "2 passed in 0.01s\n"
                )
            ),
        )


def test_a_clean_run_returns_all_identities():
    outcomes, summary = evaluate_run(
        "run 1",
        completed(
            stdout=(
                "PASSED tests/test_one.py::test_one\n"
                "PASSED tests/test_two.py::test_two[param with spaces]\n"
                "2 passed in 0.01s\n"
            )
        ),
    )

    assert outcomes == {
        "tests/test_one.py::test_one": "PASSED",
        "tests/test_two.py::test_two[param with spaces]": "PASSED",
    }
    assert summary == "2 passed in 0.01s"


def test_run_identity_drift_is_reported():
    problems = compare_runs(
        {"tests/test_one.py::test_one": "PASSED"},
        {"tests/test_two.py::test_two": "PASSED"},
    )

    assert problems
    assert "collected identities differ" in problems[0]
