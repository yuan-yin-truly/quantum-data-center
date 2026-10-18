#!/usr/bin/env python3
"""Organizer-owned HotSpot verifier for a single submission.

The 64x64 mode matches the routine leaderboard. The 128x128 mode is the
high-resolution finalist verifier. 256x256 is an optional mesh diagnostic.
"""

import argparse
import hashlib
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from generate_workloads import HERE, generate
from geometry import validate_layout
from run_simulations import create_hotspot_files, die_peaks, parse_grid
from verify_submission import parse_submission, verify

PINNED_HOTSPOT_SHA256 = "5c3fcad8ae63144b218d2fc1de28ea862f5c6d3751e7ab381d576e5c00cab4bb"
FINALIST_GRID = 128


def judge(submission, hotspot, grid=FINALIST_GRID, reference_file=None, timeout_per_workload_s=1800):
    """Validate one JSON, then run five independent simulations in a temp dir."""
    if grid not in (64, 128, 256):
        raise ValueError("verifier grid must be 64, 128 or 256")
    validity = verify(submission)
    if not validity["passed"]:
        return {"passed": False, "reason": validity["reason"]}
    hotspot = Path(hotspot).resolve()
    if not hotspot.is_file() or hashlib.sha256(hotspot.read_bytes()).hexdigest() != PINNED_HOTSPOT_SHA256:
        raise ValueError("HotSpot binary absent or not the pinned benchmark build")
    vendor = hotspot.parent
    if not all((vendor / p).is_file() for p in
               ("examples/example3/example.config", "examples/example3/example.materials")):
        raise ValueError("HotSpot example.config or materials file is missing")
    spec = json.loads((HERE / "challenge_spec.json").read_text())
    layout, paths = parse_submission(submission, spec)
    routing = validate_layout(spec, layout, wire_routes_grid=paths)
    portable = generate(spec)  # fixed organizer-owned data, no submission input
    cases = {}
    with tempfile.TemporaryDirectory(prefix="chiplet_judge_") as temp:
        run_dir = Path(temp)
        budgets = create_hotspot_files(spec, portable, layout, routing, run_dir, grid, vendor)
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
            peaks = die_peaks(spec, layout, grid_c)
            return workload, {"gpu_peak_c": max(t for die, t in peaks.items() if die.startswith("G")),
                              "hbm_peak_c": max(t for die, t in peaks.items() if die.startswith("H")),
                              "per_die_peak_c": peaks,
                              "total_w": round(budgets[workload]["total_w"], 6)}

        # Independent workload files share a fixed floorplan; no solver state is shared.
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(simulate, workload) for workload in portable["workloads"]]
            for future in as_completed(futures):
                workload, case = future.result()
                cases[workload] = case
        cases = {workload: cases[workload] for workload in portable["workloads"]}
    gpu = max(v["gpu_peak_c"] for v in cases.values())
    hbm = max(v["hbm_peak_c"] for v in cases.values())
    result = {"passed": True, "grid": grid, "finalist_grid": grid == FINALIST_GRID,
              "hotspot_sha256": PINNED_HOTSPOT_SHA256, "constraints": validity,
              "worst_gpu_c": gpu, "worst_hbm_c": hbm, "workloads": cases}
    if reference_file is not None:
        reference = json.loads(Path(reference_file).read_text())
        if reference["grid"] != grid:
            raise ValueError("reference grid differs from verifier grid")
        ambient = spec["thermal_model"]["ambient_c"]
        score = max((gpu-ambient)/(reference["worst_gpu_c"]-ambient),
                    (hbm-ambient)/(reference["worst_hbm_c"]-ambient))
        result.update(reference_c=reference, score=round(score, 8))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", type=Path)
    parser.add_argument("--hotspot", type=Path, required=True)
    parser.add_argument("--grid", type=int, choices=(64, 128, 256), default=128)
    parser.add_argument("--reference", type=Path,
                        help="same-grid baseline JSON; defaults to reference_<grid>.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reference = args.reference or HERE / f"reference_{args.grid}.json"
    result = judge(args.submission, args.hotspot, args.grid,
                   reference if reference.is_file() else None)
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    print(payload, end="")
    raise SystemExit(0 if result["passed"] else 2)


if __name__ == "__main__":
    main()
