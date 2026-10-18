#!/usr/bin/env python3
"""Thermal runs for the LOCAL-ONLY quantum variant (runs where HotSpot can run).

Needs only numpy and the original hill modules, so it executes inside the pinned
evaluation container (``ghcr.io/czaja107/beat-the-hotspot-eval``) exactly like the
original judge. ``eval_quantum.py`` writes a job file and calls this module.

Two paths:

* ``modifiers`` empty or identity: the ORIGINAL ``verify_high_accuracy.judge`` is
  called unchanged. This is the classical core and reproduces the official numbers.
* otherwise ``judge_modified``: a line-for-line mirror of ``judge`` that differs only
  in that the spec (link utilisation) and the portable power maps come from
  ``hybrid_power.apply_modifiers``. ``create_hotspot_files``, the simulator command,
  the grid parser and ``die_peaks`` are the original functions.

Results are NOT leaderboard comparable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from generate_workloads import generate  # noqa: E402
from geometry import validate_layout  # noqa: E402
from hybrid_power import apply_modifiers, is_identity  # noqa: E402
from run_simulations import create_hotspot_files, die_peaks, parse_grid  # noqa: E402
from verify_high_accuracy import PINNED_HOTSPOT_SHA256, judge  # noqa: E402
from verify_submission import parse_submission, verify  # noqa: E402

HOTSPOT = HERE / "vendor/HotSpot/hotspot"
REFERENCE_DIR = HERE / "reference"


def ensure_executable(binary: Path) -> None:
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if os.name == "posix" and not os.access(binary, os.X_OK):
        raise RuntimeError(f"cannot make {binary} executable on this node")


def reference_file(grid: int) -> Path:
    path = REFERENCE_DIR / f"reference_{grid}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} missing: the published official baseline peaks for the {grid} mesh are needed for the score")
    return path


def judge_modified(submission, hotspot, grid, reference, modifiers, timeout_per_workload_s=1800):
    """Mirror of ``verify_high_accuracy.judge`` with modified power maps and link traffic."""
    hotspot = Path(hotspot).resolve()
    validity = verify(submission)
    if not validity["passed"]:
        return {"passed": False, "reason": validity["reason"]}
    if not hotspot.is_file() or hashlib.sha256(hotspot.read_bytes()).hexdigest() != PINNED_HOTSPOT_SHA256:
        raise ValueError("HotSpot binary absent or not the pinned benchmark build")
    vendor = hotspot.parent
    spec = json.loads((HERE / "challenge_spec.json").read_text())
    layout, paths = parse_submission(submission, spec)
    routing = validate_layout(spec, layout, wire_routes_grid=paths)
    spec_m, portable_m = apply_modifiers(spec, generate(spec), modifiers)
    replaced = set((modifiers or {}).get("replaced_dies") or [])
    cases = {}
    with tempfile.TemporaryDirectory(prefix="chiplet_quantum_judge_") as temp:
        run_dir = Path(temp)
        budgets = create_hotspot_files(spec_m, portable_m, layout, routing, run_dir, grid, vendor)

        def simulate(workload):
            args = [str(hotspot), "-c", "benchmark.config", "-f", "chiplets.flp",
                    "-p", f"{workload}.ptrace", "-materials_file",
                    str(vendor / "examples/example3/example.materials"),
                    "-model_type", "grid", "-detailed_3D", "on", "-grid_layer_file", "stack.lcf",
                    "-grid_steady_file", f"{workload}.grid", "-steady_file", f"{workload}.steady"]
            proc = subprocess.run(args, cwd=run_dir, text=True, capture_output=True,
                                  timeout=timeout_per_workload_s)
            if proc.returncode:
                raise RuntimeError(f"HotSpot {workload} returned {proc.returncode}: {proc.stderr[-1000:]}")
            grid_c = parse_grid(run_dir / f"{workload}.grid", grid)
            peaks = die_peaks(spec_m, layout, grid_c)
            gpus = [t for die, t in peaks.items() if die.startswith("G") and die not in replaced]
            hbms = [t for die, t in peaks.items() if die.startswith("H") and die not in replaced]
            return workload, {"gpu_peak_c": max(gpus) if gpus else None,
                              "hbm_peak_c": max(hbms) if hbms else None,
                              "per_die_peak_c": peaks,
                              "total_w": round(budgets[workload]["total_w"], 6)}

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(simulate, workload) for workload in portable_m["workloads"]]
            for future in as_completed(futures):
                workload, case = future.result()
                cases[workload] = case
        cases = {workload: cases[workload] for workload in portable_m["workloads"]}
    gpu_vals = [v["gpu_peak_c"] for v in cases.values() if v["gpu_peak_c"] is not None]
    hbm_vals = [v["hbm_peak_c"] for v in cases.values() if v["hbm_peak_c"] is not None]
    gpu = max(gpu_vals) if gpu_vals else None
    hbm = max(hbm_vals) if hbm_vals else None
    result = {"passed": True, "grid": grid, "finalist_grid": grid == 128,
              "hotspot_sha256": PINNED_HOTSPOT_SHA256, "constraints": validity,
              "worst_gpu_c": gpu, "worst_hbm_c": hbm, "workloads": cases,
              "replaced_dies": sorted(replaced)}
    ref = json.loads(Path(reference).read_text())
    if ref["grid"] != grid:
        raise ValueError("reference grid differs from verifier grid")
    ambient = spec["thermal_model"]["ambient_c"]
    terms = []
    if gpu is not None:
        terms.append((gpu - ambient) / (ref["worst_gpu_c"] - ambient))
    if hbm is not None:
        terms.append((hbm - ambient) / (ref["worst_hbm_c"] - ambient))
    result.update(reference_c=ref, score=round(max(terms), 8) if terms else None)
    return result


def run_one(submission: Path, grid: int, modifiers: dict | None, force_mirror: bool = False) -> dict:
    """``force_mirror`` runs ``judge_modified`` even for identity modifiers (equivalence test hook)."""
    ensure_executable(HOTSPOT)
    ref = reference_file(grid)
    if is_identity(modifiers) and not force_mirror:
        result = judge(submission, HOTSPOT, grid=grid, reference_file=ref)
        result["path"] = "original_judge"
    else:
        result = judge_modified(submission, HOTSPOT, grid, ref, modifiers)
        result["path"] = "judge_modified"
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path, help="JSON: {submission, grid, runs:[{name, modifiers}]}")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    job = json.loads(args.job.read_text())
    results = {}
    for run in job["runs"]:
        results[run["name"]] = run_one(Path(job["submission"]), int(job["grid"]), run.get("modifiers"),
                                   bool(run.get("force_mirror", False)))
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
