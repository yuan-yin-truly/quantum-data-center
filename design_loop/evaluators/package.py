"""PackageEvaluator: layout legality (always), thermal surrogate (screening), real HotSpot (confirmation).

Three evaluators share one :class:`PackageModel` that turns a design into the judge's inputs:

* ``package_legality``   the judge's own ``validate_layout``; fast; a hard constraint.
* ``package_surrogate``  calibrated reduced thermal model (``surrogate.py``); every number is labelled surrogate.
* ``package_hotspot``    the pinned HotSpot build through Docker (``hotspot.py``); the only source of thermal
                         numbers that may support a claim. Unavailable -> the design stays "screened".

Hybrid power: offloaded work lowers the remaining GPUs' power maps, replaced dies carry the decoder/controller
power of quantum-support chiplets (uniform maps), via the LOCAL variant's ``hybrid_power.build_modifiers``
(rule "redistributed": a replaced die's work moves to the remaining GPUs). The offload fraction is an INPUT.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .. import integration as I
from ..genes import Design
from ..hill import HillAdapter, HillUnavailable, get_hill
from ..hotspot import HotspotRunner
from ..surrogate import ThermalSurrogate
from .base import ERROR, MODEL, OK, REAL, SURROGATE, UNAVAILABLE, EvalResult, Timer, errored, unavailable

AMBIENT_C = 25.0


def _round(o, nd=6):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    return o


def distribute(n: int, k: int) -> list[int]:
    base, rem = divmod(n, k)
    return [base + (1 if i < rem else 0) for i in range(k)]


class PackageModel:
    """Design -> layout, modifiers, thermal key; plus the shared peak summarising."""

    def __init__(self, hill: HillAdapter | None = None, max_gpu_load_factor: float = 1.0, traffic_coupling: float = 0.0,
                 hotspot_grid: int = 64):
        self.hill = hill if hill is not None else get_hill()
        self.max_gpu_load_factor = max_gpu_load_factor
        self.traffic_coupling = traffic_coupling
        self.hotspot_grid = hotspot_grid
        self._ref: dict | None = None

    # ---- layout ---------------------------------------------------------------------------------------
    def layout_of(self, design: Design) -> dict:
        if design.layout:
            return design.layout
        seeds = self.hill.seed_layouts() if self.hill else {}
        return seeds.get("baseline_example") or next(iter(seeds.values()), {})

    # ---- modifiers ------------------------------------------------------------------------------------
    def modifiers(self, design: Design, qres: EvalResult | None) -> tuple[dict | None, dict]:
        """(modifier document or None for identity, info). Raises HillUnavailable without the LOCAL variant."""
        g = design.genes
        info: dict[str, Any] = {"mode": g["mode"], "offload_fraction": g["offload_fraction"], "hosts": {},
                                "support_dies": [], "decoder_devices_on_package": 0, "decoder_devices_total": 0}
        if g["mode"] == "gpu_only":
            return None, info
        supports = I.support_dies(g)
        f = float(g["offload_fraction"])
        info["support_dies"] = supports
        hosts: dict[str, dict] = {}
        if supports:
            qm = (qres.metrics if qres and qres.ok else {}) or {}
            n_dev = 0
            if g["decoder_location"] == "package":
                need = int(qm.get("decoder_devices", 0))
                n_dev = min(need, len(supports) * int(g["devices_per_support_die"]))
                info["decoder_devices_total"] = need
            info["decoder_devices_on_package"] = n_dev
            active_w = float(qm.get("decoder_device_active_w", 0.0))
            for die, nd in zip(supports, distribute(n_dev, len(supports))):
                w = nd * active_w + float(g["support_extra_w"])
                hosts[die] = {"power_w": {wl: w for wl in self.hill.workloads}, "traffic_scale": 0.0}
                info["hosts"][die] = {"devices": nd, "power_w": w}
        if not hosts and f == 0.0:
            return None, info
        if not self.hill.supports_modifiers:
            raise HillUnavailable("modified power maps need the LOCAL quantum variant of the hill (hybrid_power.py)")
        remaining = [d for d in self.hill.GPUS if d not in supports]
        fractions = {w: {d: f for d in remaining} for w in self.hill.workloads}
        mods = self.hill.build_modifiers(fractions=fractions, dynamic_power_fraction=1.0,
                                         traffic_coupling=self.traffic_coupling, replaced_mode="redistributed",
                                         hosts=hosts)
        cap = self.max_gpu_load_factor
        clipped = False
        for w, sc in mods["die_power_scale"].items():
            for d, v in sc.items():
                if v > cap:
                    sc[d] = cap
                    clipped = True
        info["gpu_load_clipped"] = clipped
        info["gpu_load_factor_mean"] = sum(v for sc in mods["die_power_scale"].values() for v in sc.values()) / max(
            1, sum(len(sc) for sc in mods["die_power_scale"].values()))
        return _round(mods), info

    def thermal_key(self, design: Design, mods: dict | None) -> str:
        blob = json.dumps({"layout": self.layout_of(design), "mods": mods}, sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:16]

    # ---- summaries ------------------------------------------------------------------------------------
    def reference(self) -> dict:
        if self._ref is None:
            from ..paths import DATA_DIR
            self._ref = json.loads((DATA_DIR / f"reference_{self.hotspot_grid}.json").read_text())
        return self._ref

    def summarise(self, peaks: dict[str, dict[str, float]], totals: dict[str, float], mods: dict | None,
                  source: str) -> tuple[dict, dict]:
        replaced = set((mods or {}).get("replaced_dies") or [])
        per_wl = {}
        worst_g, worst_h, worst_s = -1e9, -1e9, None
        for w, dp in peaks.items():
            gpus = [dp[d] for d in self.hill.GPUS if d not in replaced]
            hbms = [dp[d] for d in dp if d.startswith("H")]
            sup = [dp[d] for d in replaced]
            per_wl[w] = {"gpu_peak_c": max(gpus), "hbm_peak_c": max(hbms), "support_peak_c": (max(sup) if sup else None),
                         "package_w": totals.get(w), "per_die_peak_c": dp, "source": source,
                         "boundary": "package (module-level watts of the 8 dies + interposer heat)"}
            worst_g, worst_h = max(worst_g, per_wl[w]["gpu_peak_c"]), max(worst_h, per_wl[w]["hbm_peak_c"])
            if sup:
                worst_s = max(worst_s if worst_s is not None else -1e9, max(sup))
        ref = self.reference()
        score = max((worst_g - AMBIENT_C) / (ref["worst_gpu_c"] - AMBIENT_C),
                    (worst_h - AMBIENT_C) / (ref["worst_hbm_c"] - AMBIENT_C))
        pk = [v for v in totals.values() if v is not None]
        metrics = {"worst_gpu_c": worst_g, "worst_hbm_c": worst_h, "support_peak_c": worst_s,
                   "score_informational": score, "score_reference_mesh": self.hotspot_grid,
                   "package_w_mean": sum(pk) / len(pk) if pk else None, "package_w_max": max(pk) if pk else None,
                   "thermal_source": source, "replaced_dies": sorted(replaced)}
        return metrics, per_wl


# ----------------------------------------------------------------------------------------------------
class PackageLegalityEvaluator:
    name = "package_legality"

    def __init__(self, model: PackageModel):
        self.model = model

    def available(self):
        return (self.model.hill is not None, "ok" if self.model.hill else "no hill directory (judge modules) found")

    def cache_key(self, design, context=None):
        return json.dumps(self.model.layout_of(design), sort_keys=True)

    def evaluate(self, design: Design, context=None) -> EvalResult:
        ok, why = self.available()
        if not ok:
            return unavailable(self.name, why)
        with Timer() as t:
            layout = self.model.layout_of(design)
            legal, reason, routing = self.model.hill.legality(layout)
        m = {"legal": legal, "reason": reason}
        if legal:
            from ..hill import HillAdapter
            m.update(weighted_route_gb_s_mm=routing["weighted_route_gb_s_mm"],
                     route_limit_gb_s_mm=routing["route_limit_gb_s_mm"])
        r = EvalResult(self.name, OK, REAL, metrics=m, key=self.cache_key(design),
                       violations=[] if legal else [f"illegal layout: {reason}"], cost={"seconds": t.seconds},
                       notes=["judge validate_layout (geometry, ports, routing, bandwidth budget)"])
        return r


class PackageSurrogateEvaluator:
    name = "package_surrogate"

    def __init__(self, model: PackageModel, surrogate: ThermalSurrogate | None = None):
        self.model = model
        self.surrogate = surrogate
        if surrogate is None and model.hill is not None:
            self.surrogate = ThermalSurrogate.load(model.hill)

    def available(self):
        if self.model.hill is None:
            return False, "no hill directory (judge modules) found"
        return True, "ok" if self.surrogate.calibrated else "ok (uncalibrated default parameters)"

    def cache_key(self, design, context=None):
        qres = (context or {}).get("quantum")
        try:
            mods, _ = self.model.modifiers(design, qres)
        except HillUnavailable:
            mods = {"unavailable": True}
        return self.model.thermal_key(design, mods)

    def evaluate(self, design: Design, context=None) -> EvalResult:
        ok, why = self.available()
        if not ok:
            return unavailable(self.name, why, SURROGATE)
        qres = (context or {}).get("quantum")
        try:
            mods, info = self.model.modifiers(design, qres)
        except HillUnavailable as exc:
            return unavailable(self.name, str(exc), SURROGATE)
        layout = self.model.layout_of(design)
        legal, reason, routing = self.model.hill.legality(layout)
        if not legal:
            return EvalResult(self.name, OK, SURROGATE, metrics={"legal": False},
                              violations=[f"illegal layout: {reason}"], key=self.model.thermal_key(design, mods))
        with Timer() as t:
            try:
                heat = self.model.hill.heat(layout, routing, mods)
                peaks = self.surrogate.die_peaks(layout, heat)
            except Exception as exc:
                return errored(self.name, exc, SURROGATE)
        totals = {w: h["total_w"] for w, h in heat.items()}
        metrics, per_wl = self.model.summarise(peaks, totals, mods, "surrogate")
        metrics["surrogate_calibrated"] = self.surrogate.calibrated
        metrics.update(info=info)
        notes = [] if self.surrogate.calibrated else ["surrogate parameters are NOT calibrated"]
        return EvalResult(self.name, OK, SURROGATE, metrics=metrics, per_workload=per_wl, notes=notes,
                          key=self.model.thermal_key(design, mods), cost={"seconds": t.seconds},
                          boundary="package")

    # layout search uses the same machinery; returns the worst normalised temperature (lower = better)
    def layout_score_fn(self, design: Design, qres: EvalResult | None):
        mods, _ = self.model.modifiers(design, qres)
        hill = self.model.hill
        ref = self.model.reference()
        replaced = set((mods or {}).get("replaced_dies") or [])

        def score(layout: dict) -> float:
            legal, _, routing = hill.legality(layout)
            if not legal:
                return 1e9
            heat = hill.heat(layout, routing, mods)
            peaks = self.surrogate.die_peaks(layout, heat)
            g = max(dp[d] for dp in peaks.values() for d in hill.GPUS if d not in replaced)
            h = max(dp[d] for dp in peaks.values() for d in dp if d.startswith("H"))
            return max((g - AMBIENT_C) / (ref["worst_gpu_c"] - AMBIENT_C), (h - AMBIENT_C) / (ref["worst_hbm_c"] - AMBIENT_C))

        return score


class PackageHotspotEvaluator:
    """Real HotSpot. ``evaluate_many`` batches the heavy runs; cache hits are handled by the caller."""

    name = "package_hotspot"

    def __init__(self, model: PackageModel, runner: HotspotRunner | None = None, enabled: bool = True):
        self.model = model
        self.runner = runner or HotspotRunner(grid=model.hotspot_grid)
        self.enabled = enabled

    def available(self):
        if not self.enabled:
            return False, "disabled by configuration"
        if self.model.hill is None:
            return False, "no hill directory"
        return self.runner.available()

    def cache_key(self, design, context=None):
        qres = (context or {}).get("quantum")
        try:
            mods, _ = self.model.modifiers(design, qres)
        except HillUnavailable:
            mods = {"unavailable": True}
        return self.model.thermal_key(design, mods) + f"|g{self.model.hotspot_grid}"

    def job_for(self, design: Design, context) -> dict:
        mods, info = self.model.modifiers(design, (context or {}).get("quantum"))
        return {"key": self.cache_key(design, context), "placements_mm": self.model.layout_of(design), "modifiers": mods}

    def evaluate(self, design: Design, context=None) -> EvalResult:
        return self.evaluate_many([(design, context or {})])[0]

    def evaluate_many(self, items: list[tuple[Design, dict]]) -> list[EvalResult]:
        ok, why = self.available()
        if not ok:
            return [unavailable(self.name, why, REAL) for _ in items]
        jobs, order = [], []
        for d, ctx in items:
            try:
                jobs.append(self.job_for(d, ctx))
                order.append(None)
            except HillUnavailable as exc:
                jobs.append(None)
                order.append(unavailable(self.name, str(exc), REAL))
        todo = {}
        for j in jobs:
            if j is not None:
                todo[j["key"]] = j
        done = self.runner.run_many(list(todo.values())) if todo else {}
        out = []
        for (d, ctx), j, pre in zip(items, jobs, order):
            if pre is not None:
                out.append(pre)
                continue
            rec = done[j["key"]]
            if not rec["ok"]:
                out.append(EvalResult(self.name, ERROR, REAL, notes=[f"HotSpot run failed: {rec.get('error')}"],
                                      key=j["key"], cost={"seconds": rec.get("seconds", 0.0), "hotspot_runs": 0}))
                continue
            res = rec["result"]
            peaks = {w: v["per_die_peak_c"] for w, v in res["workloads"].items()}
            totals = {w: v["total_w"] for w, v in res["workloads"].items()}
            metrics, per_wl = self.model.summarise(peaks, totals, j["modifiers"], "hotspot")
            metrics.update(grid=self.model.hotspot_grid, hotspot_sha256=res.get("hotspot_sha256"),
                           judge_path=res.get("path"), judge_worst_gpu_c_raw=res.get("worst_gpu_c"),
                           judge_worst_hbm_c_raw=res.get("worst_hbm_c"), image=rec.get("image"))
            out.append(EvalResult(self.name, OK, REAL, metrics=metrics, per_workload=per_wl, key=j["key"],
                                  cost={"seconds": rec["seconds"], "hotspot_runs": 1}, boundary="package",
                                  notes=["pinned HotSpot build via the judge pipeline; NOT leaderboard comparable"]))
        return out
