"""Calibrate the thermal surrogate against real HotSpot runs of the judge's pipeline.

``python -m design_loop calibrate`` runs ~14 layouts / power scenarios (the hill's own example layouts, seeded random
walks around them, and hybrid power modifiers with uniform-map support chiplets), fits the surrogate to the per-die
peaks of all five workloads and stores the training data, the parameters and the leave-one-layout-out error in
``data/surrogate_calibration.json``. Needs Docker and the pinned image; without them nothing is written.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

from .hill import get_hill
from .hotspot import HotspotRunner
from .layout import propose_layout
from .paths import DATA_DIR
from .surrogate import CAL_PATH, ThermalSurrogate

RUNS_PATH = DATA_DIR / "hotspot_calibration_runs.json"


def scenarios(hill, seed: int = 7, n_walks: int = 6) -> list[dict]:
    rng = random.Random(seed)
    seeds = hill.seed_layouts()
    base = seeds["baseline_example"]
    out = [{"name": f"seed:{k}", "layout": v, "modifiers": None} for k, v in sorted(seeds.items())]
    cur = base
    for i in range(n_walks):
        step = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5][i % 6]
        for _ in range(4):
            p = propose_layout(hill, cur, rng, step, tries=15)
            if p:
                cur = p[0]
        out.append({"name": f"walk{i}", "layout": cur, "modifiers": None})
        if i % 2 == 1:
            cur = base
    if hill.supports_modifiers:
        wl = hill.workloads

        def mods(supports, f, watts):
            hosts = {d: {"power_w": {w: watts for w in wl}, "traffic_scale": 0.0} for d in supports}
            rem = [d for d in hill.GPUS if d not in supports]
            return hill.build_modifiers(fractions={w: {d: f for d in rem} for w in wl}, dynamic_power_fraction=1.0,
                                        traffic_coupling=0.0, replaced_mode="redistributed", hosts=hosts)

        out.append({"name": "mods:f0.3", "layout": base, "modifiers": mods([], 0.3, 0.0)})
        out.append({"name": "mods:G3host90W", "layout": base, "modifiers": mods(["G3"], 0.2, 90.0)})
        walk = next((s for s in out if s["name"] == "walk2"), None)
        if walk:
            out.append({"name": "mods:G1host60W@walk2", "layout": walk["layout"], "modifiers": mods(["G1"], 0.1, 60.0)})
        out.append({"name": "mods:G0G2host40W", "layout": seeds.get("ring_spread", base), "modifiers": mods(["G0", "G2"], 0.25, 40.0)})
    return out


def run_calibration(concurrency: int = 2, grid: int = 64, seed: int = 7, n_walks: int = 6, out_path: Path = CAL_PATH,
                    runs_path: Path = RUNS_PATH, log=print) -> dict:
    hill = get_hill()
    if hill is None:
        raise RuntimeError("no hill directory found")
    runner = HotspotRunner(grid=grid, concurrency=concurrency)
    ok, why = runner.available()
    if not ok:
        raise RuntimeError(f"HotSpot unavailable, cannot calibrate: {why}")
    scs = scenarios(hill, seed, n_walks)
    log(f"calibration: {len(scs)} HotSpot runs ({grid}x{grid}), concurrency {concurrency}")
    jobs = [{"key": s["name"], "placements_mm": s["layout"], "modifiers": s["modifiers"]} for s in scs]
    t0 = time.perf_counter()
    done = runner.run_many(jobs)
    log(f"HotSpot finished in {time.perf_counter() - t0:.0f} s")
    runs = []
    for s in scs:
        rec = done[s["name"]]
        if not rec["ok"]:
            log(f"  {s['name']}: FAILED {rec.get('error')}")
            continue
        res = rec["result"]
        runs.append({"name": s["name"], "layout": s["layout"], "modifiers": s["modifiers"], "grid": grid,
                     "peaks": {w: v["per_die_peak_c"] for w, v in res["workloads"].items()},
                     "total_w": {w: v["total_w"] for w, v in res["workloads"].items()},
                     "worst_gpu_c": res["worst_gpu_c"], "worst_hbm_c": res["worst_hbm_c"], "seconds": rec["seconds"]})
    runs_path.write_text(json.dumps({"hotspot_sha256": res.get("hotspot_sha256"), "grid": grid, "runs": runs}, indent=1))
    return fit_from_runs(runs, hill, out_path, log)


def fit_from_runs(runs: list[dict], hill=None, out_path: Path = CAL_PATH, log=print) -> dict:
    hill = hill or get_hill()
    sur = ThermalSurrogate(hill)
    samples = []
    seen = set()
    for r in runs:
        key = json.dumps([r["layout"], r["modifiers"]], sort_keys=True)
        if key in seen:                       # identical problems would leak into the cross-validation
            continue
        seen.add(key)
        legal, _, routing = hill.legality(r["layout"])
        if not legal:
            continue
        samples.append({"layout": r["layout"], "heat": hill.heat(r["layout"], routing, r["modifiers"]),
                        "peaks": r["peaks"], "name": r["name"]})
    fit = sur.fit(samples)
    # per-run agreement of the headline metrics
    rows = []
    by_name = {r["name"]: r for r in runs}
    for s in samples:
        r = by_name[s["name"]]
        pred = sur.die_peaks(s["layout"], s["heat"])
        replaced = set((r["modifiers"] or {}).get("replaced_dies") or [])
        pg = max(dp[d] for dp in pred.values() for d in hill.GPUS if d not in replaced)
        ph = max(dp[d] for dp in pred.values() for d in dp if d.startswith("H"))
        og = max(dp[d] for dp in r["peaks"].values() for d in hill.GPUS if d not in replaced)
        oh = max(dp[d] for dp in r["peaks"].values() for d in dp if d.startswith("H"))
        rows.append({"name": r["name"], "hotspot_gpu": og, "surrogate_gpu": round(pg, 2), "hotspot_hbm": oh,
                     "surrogate_hbm": round(ph, 2)})
    fit["per_run_in_sample"] = rows
    fit["training_runs"] = [{"name": r["name"], "grid": r["grid"]} for r in runs]
    fit["note"] = ("Fitted to real HotSpot per-die peaks (pinned build) of the listed runs; leave-one-layout-out "
                   "cross-validation is the honest error estimate. Valid near the sampled layouts and power levels only.")
    out_path.write_text(json.dumps(fit, indent=1))
    log(f"surrogate fitted: in-sample RMSE {fit['fit']['rmse_c']:.2f} C, CV RMSE "
        f"{fit['cross_validation_leave_one_layout_out'].get('rmse_c', float('nan')):.2f} C -> {out_path}")
    return fit
