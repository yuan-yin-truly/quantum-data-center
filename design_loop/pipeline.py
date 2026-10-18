"""Wires the evaluators into stages: cheap screening first, expensive HotSpot only for the most promising.

Stage A  quantum_arch + layout legality          (milliseconds)   -> hard-constraint filter
Stage B  thermal surrogate + data-centre model   (~0.2 s)         -> screening metrics for every survivor
Stage C  real HotSpot                            (~1 min each)    -> confirmation of the best screened designs

Results are cached by ``(evaluator, cache key)`` in the archive, so identical sub-problems are never re-run.
"""

from __future__ import annotations

import copy
import time
from typing import Any

from .archive import Archive
from .evaluators import (DataCentreEvaluator, PackageHotspotEvaluator, PackageLegalityEvaluator, PackageModel,
                         PackageSurrogateEvaluator, QuantumSystemEvaluator)
from .evaluators.base import OK, EvalResult, errored
from .evaluators.stub import StubLegalityEvaluator, StubThermalEvaluator
from .genes import Design
from .hill import get_hill
from .hotspot import HotspotRunner


class Pipeline:
    def __init__(self, cfg: dict[str, Any], hill=None, package_mode: str = "auto", evaluators: dict | None = None):
        ev = cfg["evaluators"]
        pk = ev["package"]
        cons = cfg.get("constraints", {})
        self.cfg = cfg
        self.hill = hill if hill is not None else get_hill()
        self.package_mode = package_mode if package_mode != "auto" else pk.get("mode", "auto")
        self.quantum = QuantumSystemEvaluator(max_fridge_units=cons.get("max_fridge_units", 100),
                                              min_task_p_accept=cons.get("min_task_p_accept", 0.5), **ev.get("quantum", {}))
        dcc = {k: v for k, v in ev["datacentre"].items() if k != "force_stand_in"}
        self.datacentre = DataCentreEvaluator(dcc, force_stand_in=ev["datacentre"].get("force_stand_in", False))
        self.model = PackageModel(self.hill, pk.get("max_gpu_load_factor", 1.0), pk.get("traffic_coupling", 0.0),
                                  pk.get("grid", 64))
        self.hotspot_mode = pk.get("hotspot", "auto")
        if self.package_mode == "stub":
            self.legality, self.surrogate, self.hotspot = StubLegalityEvaluator(), StubThermalEvaluator(), None
        else:
            self.legality = PackageLegalityEvaluator(self.model)
            self.surrogate = PackageSurrogateEvaluator(self.model)
            runner = HotspotRunner(grid=pk.get("grid", 64), concurrency=pk.get("concurrency", 2),
                                   try_start_docker=pk.get("try_start_docker", False))
            self.hotspot = PackageHotspotEvaluator(self.model, runner, enabled=self.hotspot_mode != "never")
        for name, obj in (evaluators or {}).items():                  # test hook: replace any evaluator
            setattr(self, name, obj)

    # ---- status ---------------------------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        """What is real, surrogate or stub in this run (reported and stored with the results)."""
        d = {"quantum": self.quantum.available(), "package_legality": self.legality.available(),
             "package_surrogate": self.surrogate.available(),
             "package_hotspot": self.hotspot.available() if self.hotspot else (False, "none (stub package mode)"),
             "datacentre": self.datacentre.available()}
        out = {k: {"available": v[0], "detail": v[1]} for k, v in d.items()}
        out["package_surrogate"]["calibrated"] = bool(getattr(getattr(self.surrogate, "surrogate", None), "calibrated", False))
        out["hill"] = {"dir": str(self.hill.root), "flavor": self.hill.flavor} if self.hill else None
        out["package_mode"] = self.package_mode
        return out

    def hotspot_ready(self) -> bool:
        return bool(self.hotspot) and self.hotspot.available()[0]

    # ---- cached evaluation ----------------------------------------------------------------------------
    @staticmethod
    def _run(ev, design: Design, ctx: dict[str, EvalResult], archive: Archive) -> EvalResult:
        try:
            key = ev.cache_key(design, ctx)
        except Exception as exc:                                       # a broken key must not kill the loop
            return errored(ev.name, exc)
        hit = archive.cached(ev.name, key)
        if hit is not None:
            r = copy.copy(hit)
            r.cost = {**hit.cost, "seconds": 0.0, "cache_hit": True}
            return r
        try:
            r = ev.evaluate(design, ctx)
        except Exception as exc:
            return errored(ev.name, exc)
        r.key = r.key or key
        return r

    def stage_a(self, design: Design, archive: Archive) -> dict[str, EvalResult]:
        have = archive.results(design.id)
        out: dict[str, EvalResult] = {}
        for ev in (self.quantum, self.legality):
            if ev.name in have and have[ev.name].ok:
                out[ev.name] = have[ev.name]
            else:
                out[ev.name] = self._run(ev, design, out, archive)
                archive.add_eval(design.id, out[ev.name])
        return out

    def stage_b(self, design: Design, archive: Archive) -> dict[str, EvalResult]:
        """Surrogate thermal + data centre, only for designs without a hard violation after stage A."""
        have = archive.results(design.id)
        ctx = dict(have)
        out: dict[str, EvalResult] = {}
        for ev in (self.surrogate, self.datacentre):
            if ev.name in have and have[ev.name].ok:
                continue
            r = self._run(ev, design, ctx, archive)
            out[ev.name] = r
            ctx[ev.name] = r
            archive.add_eval(design.id, r)
        return out

    def stage_c(self, designs: list[Design], archive: Archive) -> dict[str, EvalResult]:
        """Real HotSpot for ``designs`` (cache hits are free). Returns {design_id: result}."""
        if not self.hotspot:
            return {}
        todo, out = [], {}
        for d in designs:
            ctx = dict(archive.results(d.id))
            try:
                key = self.hotspot.cache_key(d, ctx)
            except Exception as exc:
                out[d.id] = errored(self.hotspot.name, exc)
                continue
            hit = archive.cached(self.hotspot.name, key)
            if hit is not None:
                r = copy.copy(hit)
                r.cost = {**hit.cost, "seconds": 0.0, "hotspot_runs": 0, "cache_hit": True}
                out[d.id] = r
            else:
                todo.append((d, ctx))
        # identical thermal problems are run once
        uniq: dict[str, tuple[Design, dict]] = {}
        for d, ctx in todo:
            uniq.setdefault(self.hotspot.cache_key(d, ctx), (d, ctx))
        results = self.hotspot.evaluate_many(list(uniq.values())) if uniq else []
        by_key = {k: r for k, r in zip(uniq, results)}
        for d, ctx in todo:
            k = self.hotspot.cache_key(d, ctx)
            r = by_key[k]
            if r.ok:
                archive.cache.setdefault((r.evaluator, r.key), r)
            if r is not by_key[k] or uniq[k][0] is not d:
                r = copy.copy(r)
                r.cost = {**r.cost, "hotspot_runs": 0, "cache_hit": True}
            out[d.id] = r
        for did, r in out.items():
            archive.add_eval(did, r)
        return out
