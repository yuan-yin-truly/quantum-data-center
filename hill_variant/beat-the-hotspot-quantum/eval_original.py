"""Frozen Autolab Hill entry point. The submission contains data, never code to run.

This file is visible to the climber on purpose: how a layout is judged is public.
The score denominators are read from private/ so that nothing in a submission
directory can shadow the baseline the score is divided by. Their values are not
secret -- the README publishes both.
"""

from pathlib import Path
import os
import stat
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from verify_high_accuracy import PINNED_HOTSPOT_SHA256, judge
from verify_submission import verify

HOTSPOT = ROOT / "vendor/HotSpot/hotspot"


def _ensure_executable(binary: Path) -> None:
    """Give the pinned HotSpot build its execute bit back.

    This hill is authored on Windows, where git cannot record an execute bit, so
    the binary reaches a Linux scoring node as mode 644 and will not run. Setting
    the bit does not touch the bytes, so the SHA-256 the judge verifies is
    unchanged.
    """
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if os.name == "posix" and not os.access(binary, os.X_OK):
        raise RuntimeError(f"cannot make {binary} executable on this node")


def eval(submission: Path, *, final: bool = False, **params) -> dict:
    submission_file = Path(submission) / "submission.json"
    validity = verify(submission_file, ROOT / "challenge_spec.json")
    grid = 128 if final else 64
    common_config = [{"name": "thermal_grid", "value": f"{grid}x{grid}", "primary": True},
                     {"name": "hotspot_sha256", "value": PINNED_HOTSPOT_SHA256, "primary": True}]
    if not validity["passed"]:
        invalid_metrics = [{"name": name, "value": 1_000_000.0, "direction": "min"}
                           for name in ("score", "worst_gpu_c", "worst_hbm_c")]
        return {"passed": False, "metrics": invalid_metrics, "config": common_config,
                "details": {"reason": validity["reason"]}}
    _ensure_executable(HOTSPOT)
    result = judge(submission_file, HOTSPOT, grid=grid,
                   reference_file=ROOT / "private" / f"reference_{grid}.json")
    return {"passed": True,
            "metrics": [{"name": "score", "value": result["score"], "direction": "min"},
                        {"name": "worst_gpu_c", "value": result["worst_gpu_c"], "direction": "min"},
                        {"name": "worst_hbm_c", "value": result["worst_hbm_c"], "direction": "min"}],
            "config": common_config,
            "details": {"constraint_report": validity,
                        "per_workload": result["workloads"],
                        "reference": result["reference_c"],
                        "final": final}}
