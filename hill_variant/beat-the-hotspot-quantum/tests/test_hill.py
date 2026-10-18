"""Hill contract checks, run by `hills check`.

These stay fast on purpose: they pin the submission contract and the rejection
path, which do not need HotSpot. Scoring all five workloads through the pinned
simulator is a separate organizer run, not part of every check.

The tests run inside the hill's container image when the manifest declares one,
using that image's interpreter. The image carries numpy and pytest but not the
hills package, so `run_evaluator` is imported when it is there and the evaluator
is called directly when it is not. Either way it is the same entry point.
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

HILL = Path(__file__).resolve().parents[1]
needs_vendor = pytest.mark.skipif(not (HILL / "vendor/HotSpot/hotspot").exists(),
                              reason="vendor/HotSpot is not in the repo; restore it from the original hill (see README_QUANTUM_VARIANT.md)")
EXAMPLES = HILL / "examples"

if str(HILL) not in sys.path:
    sys.path.insert(0, str(HILL))

try:
    from hills import run_evaluator
except ModuleNotFoundError:
    def run_evaluator(hill, submission, **kwargs):
        from eval import eval as evaluate

        return evaluate(Path(submission), **kwargs)


def test_overlapping_dies_are_rejected():
    result = run_evaluator(HILL, EXAMPLES / "invalid")
    assert not result["passed"]
    assert "clearance" in result["details"]["reason"]


def test_missing_submission_is_rejected(tmp_path):
    result = run_evaluator(HILL, tmp_path)
    assert not result["passed"]


def test_rejection_still_reports_the_declared_metrics():
    result = run_evaluator(HILL, EXAMPLES / "invalid")
    assert [m["name"] for m in result["metrics"]] == ["score", "worst_gpu_c", "worst_hbm_c"]
    assert all(m["direction"] == "min" for m in result["metrics"])


def test_baseline_example_is_a_legal_layout():
    from verify_submission import verify

    report = verify(EXAMPLES / "baseline/submission.json", HILL / "challenge_spec.json")
    assert report["passed"], report["reason"]
    assert len(report["links"]) == 8


def test_published_denominators_match_the_private_copies():
    """The README publishes these numbers; private/ holds what the judge divides by."""
    for grid, gpu, hbm in ((64, 104.59, 97.68), (128, 104.74, 97.70)):
        reference = json.loads((HILL / "reference" / f"reference_{grid}.json").read_text())
        assert reference["grid"] == grid
        assert reference["worst_gpu_c"] == gpu
        assert reference["worst_hbm_c"] == hbm


@needs_vendor
def test_pinned_simulator_is_intact():
    """Catch a mangled binary here rather than on the scoring node.

    The hill ships a Linux x86-64 build and is authored on Windows, so an
    end-of-line filter sneaking in would change these bytes and every run would
    fail the judge's hash check.
    """
    from verify_high_accuracy import PINNED_HOTSPOT_SHA256

    raw = (HILL / "vendor/HotSpot/hotspot").read_bytes()
    assert raw[:4] == b"\x7fELF"
    assert hashlib.sha256(raw).hexdigest() == PINNED_HOTSPOT_SHA256


@needs_vendor
def test_hotspot_support_files_the_judge_requires_are_present():
    for relative in ("examples/example3/example.config",
                     "examples/example3/example.materials"):
        assert (HILL / "vendor/HotSpot" / relative).is_file()


def test_simulator_can_actually_run_here_or_says_why_not():
    """On Linux, prove the pinned build executes before a climb depends on it.

    HotSpot needs glibc 2.34 or newer. Everywhere else this is skipped, because
    a Linux x86-64 binary cannot run on the host and that is expected.
    """
    import os
    import subprocess

    if os.name != "posix" or sys.platform != "linux":
        return

    from eval import HOTSPOT, _ensure_executable

    _ensure_executable(HOTSPOT)
    proc = subprocess.run([str(HOTSPOT)], capture_output=True, text=True, timeout=60)
    combined = proc.stdout + proc.stderr
    assert "GLIBC" not in combined, f"the base image's glibc is too old: {combined[-400:]}"
    assert combined.strip(), "HotSpot produced no output at all, which it should on bad args"
