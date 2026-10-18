"""The iterative design loop: propose -> pre-filter -> screen -> confirm -> archive, generation after generation.

Deterministic given the seed (each generation draws from ``Random(seed * 1_000_003 + generation)``), resumable from
the run directory (cached evaluations are never repeated; a generation interrupted by a crash is re-run and its
candidates, being deterministic, hit the cache), and crash-safe (append-only, fsynced archive).
"""

from __future__ import annotations

import json
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

from . import LEADERBOARD_COMPARABLE, NOTICE
from . import integration as I
from . import layout as L
from .archive import Archive
from .config import load_config
from .evaluators.base import EvalResult
from .genes import Design, Space
from .hill import get_hill
from .objectives import (Assessment, assess, nondominated_sort, pareto_front, scalar_scores)
from .pipeline import Pipeline


class DesignLoop:
    def __init__(self, config: dict | str | Path | None, run_dir: str | Path, space: Space | None = None,
                 pipeline: Pipeline | None = None, log=print):
        self.cfg = load_config(config)
        self.run_dir = Path(run_dir)
        self.archive = Archive(self.run_dir)
        self.space = space or self._load_space()
        self.pipe = pipeline or Pipeline(self.cfg)
        self.log = log
        self.objectives = self.cfg["objectives"]
        self.constraints = self.cfg["constraints"]
        self.hill = self.pipe.hill
        self.state = self.archive.load_state() or {"generation_done": -1, "hotspot_runs": 0, "elapsed_s": 0.0,
                                                   "stop_reason": None, "stagnant": 0, "ideal": None, "front_ids": []}
        self._seed_layouts: dict[str, dict] | None = None

    # ---- setup ----------------------------------------------------------------------------------------
    def _load_space(self) -> Space:
        sp = self.cfg["space"]
        if sp == "default" or sp is None:
            return I.make_space()
        if isinstance(sp, dict):
            return I.make_space(sp)
        s = Space.load(sp)
        defaults = s.defaults()
        s.repair = lambda g: I.repair(g, defaults)
        return s

    def seed_layouts(self) -> dict[str, dict]:
        if self._seed_layouts is None:
            self._seed_layouts = self.hill.seed_layouts() if self.hill else {}
        return self._seed_layouts

    def base_layout(self) -> dict | None:
        sl = self.seed_layouts()
        pref = (self.space.layout_cfg.get("seeds") or ["baseline_example"])[0]
        return sl.get(pref) or (next(iter(sl.values())) if sl else None)

    # ---- assessment helpers ---------------------------------------------------------------------------
    def assess_design(self, did: str) -> Assessment:
        return assess(did, self.archive.results(did), self.constraints, self.objectives)

    def assess_all(self, before_gen: int | None = None) -> dict[str, Assessment]:
        """Assessments of all designs (optionally only those registered before generation ``before_gen``)."""
        return {did: self.assess_design(did) for did in self.archive.designs
                if before_gen is None or (self.archive.meta[did].get("generation") or 0) < before_gen}

    def fronts(self, assessments: dict[str, Assessment] | None = None) -> dict[str, list[str]]:
        a = list((assessments or self.assess_all()).values())
        return {"screening": pareto_front(a, self.objectives), "confirmed": pareto_front(a, self.objectives, "confirmed")}

    # ---- proposals ------------------------------------------------------------------------------------
    def _mk(self, genes: dict, layout: dict | None) -> Design:
        return self.space.canonicalize(genes, layout or self.base_layout())

    def seed_designs(self) -> list[tuple[Design, list[str], str, list[str]]]:
        out = []
        base = self.base_layout()
        out.append((self._mk({"mode": "gpu_only"}, base), [], "seed:gpu_only", []))
        mods = list(self.space.genes["modality"].choices) if "modality" in self.space.genes else []
        for mode in ("add", "replace"):
            for m in mods:
                g = {"mode": mode, "modality": m}
                if mode == "replace":
                    g.update(decoder_location="package", offload_fraction=0.3, decoder_device="auto:asic_rt")
                out.append((self._mk(g, base), [], f"seed:{mode}:{m}", ["mode", "modality"]))
        # a few alternative integration choices on the default modality
        out.append((self._mk({"mode": "add", "decoder_location": "4K", "n_qubits": 20000}, base), [], "seed:add:cold_decoder", ["decoder_location"]))
        out.append((self._mk({"mode": "add", "n_qubits": 5000, "cryostat_scale": 4, "n_quantum_systems": 1,
                              "offload_fraction": 0.05, "task": "vqe_20q"}, base), [], "seed:add:small", ["n_qubits"]))
        seen, uniq = set(), []
        for s in out:
            if s[0].id not in seen:
                seen.add(s[0].id)
                uniq.append(s)
        return uniq

    def _parents(self, assessments: dict[str, Assessment]) -> list[str]:
        fr = self.fronts(assessments)["screening"]
        sc = scalar_scores([a for a in assessments.values()], self.objectives, self.cfg.get("weights"))
        best = [i for i, _ in sorted(sc.items(), key=lambda kv: (kv[1], kv[0]))[:4]]
        parents = list(dict.fromkeys(sorted(fr) + best))
        if parents:
            return parents
        # nothing feasible yet: learn from the least-violating designs
        bad = sorted(assessments.values(), key=lambda a: (len(a.violations), a.design_id))
        return [a.design_id for a in bad[:6]]

    def propose(self, gen: int, rng: random.Random, assessments: dict[str, Assessment]) -> list[tuple[Design, list[str], str, list[str]]]:
        self._gen = gen
        n = int(self.cfg["population"]["candidates_per_generation"])
        out: list[tuple[Design, list[str], str, list[str]]] = []
        if gen == 0:
            out = self.seed_designs()
        parents = self._parents(assessments) if assessments else []
        shares = self.cfg["population"]["operator_shares"]
        plm = float(self.cfg["population"]["p_layout_move"])
        step = float(self.space.layout_cfg.get("step_mm", 1.5))
        grid = float(self.space.layout_cfg.get("grid_mm", 0.05))
        quota = {k: int(round(v * n)) for k, v in shares.items()}
        seen = {c[0].id for c in out}

        def add(c: Design, par: list[str], op: str, changed: list[str]):
            if c.id not in seen and (c.id not in self.archive.designs or self.archive.meta[c.id].get("generation") == gen):
                seen.add(c.id)
                out.append((c, par, op, changed))

        def pick() -> Design:
            return self.archive.designs[rng.choice(parents)]

        if parents:
            best = sorted(scalar_scores(list(assessments.values()), self.objectives, self.cfg.get("weights")).items(),
                          key=lambda kv: (kv[1], kv[0]))
            # single-gene ablations / neighbours of the best design(s)
            for did, _ in best[:2]:
                nb = self.space.neighbours(self.archive.designs[did])
                rng.shuffle(nb)
                for c, gene in nb[: quota.get("neighbour", 0) // 2 + 1]:
                    add(c, [did], f"neighbour:{gene}", [gene])
            for _ in range(quota.get("mutate", 0) * 3):
                if sum(1 for o in out if o[2] == "mutate") >= quota.get("mutate", 0):
                    break
                p = pick()
                c, ch = self.space.mutate(p, rng)
                if ch and self.hill and rng.random() < plm:
                    lay = L.propose_layout(self.hill, c.layout or self.base_layout(), rng, step, grid)
                    if lay:
                        c, ch = c.with_layout(lay[0]), ch + [lay[1]]
                        c = self.space.recanonicalize(c)
                if ch:
                    add(c, [p.id], "mutate", ch)
            if len(parents) >= 2:
                for _ in range(quota.get("crossover", 0) * 3):
                    if sum(1 for o in out if o[2] == "crossover") >= quota.get("crossover", 0):
                        break
                    a, b = rng.sample(parents, 2)
                    c, ch = self.space.crossover(self.archive.designs[a], self.archive.designs[b], rng)
                    add(c, [a, b], "crossover", ch)
        for _ in range(max(quota.get("restart", 0), 1) * 3):
            if sum(1 for o in out if o[2] == "restart") >= max(quota.get("restart", 0), 1):
                break
            g = self.space.random_genes(rng)
            lay = None
            if self.hill and self.seed_layouts():
                r = L.random_layout(self.hill, self.seed_layouts(), rng, step * 1.5, grid)
                lay = r[0] if r else None
            add(self._mk(g, lay), [], "restart", ["*"])
        # layout local search (surrogate guided) around the best feasible designs
        k_ls = int(self.cfg["population"]["layout_search_per_generation"])
        if parents and self.hill and k_ls and getattr(self.pipe.surrogate, "surrogate", None) is not None:
            ranked = [i for i in parents if assessments[i].status == "complete"][:k_ls]
            for did in ranked:
                d = self.archive.designs[did]
                try:
                    score = self.pipe.surrogate.layout_score_fn(d, self.archive.results(did).get("quantum"))
                    lay, s1, ev = L.local_search(self.hill, d.layout or self.base_layout(), score, rng,
                                                 int(self.cfg["population"]["layout_search_steps"]), step, grid)
                except Exception as exc:                         # never let a search kill the generation
                    self.log(f"  layout search skipped for {did}: {exc}")
                    continue
                if lay != (d.layout or self.base_layout()):
                    add(self.space.canonicalize(d.genes, lay), [did], "layout_search",
                        [f"layout (surrogate score {s1:.4f}, {ev} evals)"])
        # fill up with random restarts if the operators produced too few
        guard = 0
        while len(out) < n and guard < 200:
            guard += 1
            g = self.space.random_genes(rng)
            add(self._mk(g, self.base_layout()), [], "restart", ["*"])
        return out[: max(n, len(out)) if gen == 0 else n]

    # ---- one generation -------------------------------------------------------------------------------
    def run_generation(self, gen: int, t_start: float) -> dict:
        rng = random.Random(int(self.cfg["seed"]) * 1_000_003 + gen)
        assessments = self.assess_all(before_gen=gen)
        cands = self.propose(gen, rng, assessments)
        budget = self.cfg["budget"]
        room = budget["max_designs"] - len(self.archive.designs)
        gen_ids = []
        n_new = 0
        for c, par, op, ch in cands:
            if c.id in self.archive.designs:
                gen_ids.append(c.id)                  # re-run after a crash
                continue
            if room <= 0:
                break
            self.archive.add_design(c, par, op, ch, gen)
            gen_ids.append(c.id)
            n_new += 1
            room -= 1
        # Stage A: quantum + legality
        for did in gen_ids:
            self.pipe.stage_a(self.archive.designs[did], self.archive)
        # Stage B: surrogate + data centre for survivors
        skipped_budget = 0
        for did in gen_ids:
            a = self.assess_design(did)
            if a.violations:
                continue
            if self._time_left(t_start) <= 0:
                skipped_budget += 1                   # left partial on purpose: reported, never ranked
                continue
            self.pipe.stage_b(self.archive.designs[did], self.archive)
        # Stage C: HotSpot for the best screened front members
        hs = self._confirm(gen)
        assessments = self.assess_all()
        fr = self.fronts(assessments)
        ideal = self._ideal(assessments)
        ops = Counter(self.archive.meta[d]["operator"].split(":")[0] for d in gen_ids)
        stat = Counter(assessments[d].status for d in gen_ids)
        summary = {"generation": gen, "candidates": len(cands), "new_designs": n_new, "operators": dict(ops),
                   "status": dict(stat), "designs_total": len(self.archive.designs),
                   "front_screening": len(fr["screening"]), "front_confirmed": len(fr["confirmed"]),
                   "ideal_point": ideal, "hotspot_runs_this_gen": hs, "hotspot_runs_total": self.state["hotspot_runs"],
                   "skipped_by_wallclock": skipped_budget, "time": time.time(),
                   "leaderboard_comparable": LEADERBOARD_COMPARABLE}
        scal = scalar_scores(list(assessments.values()), self.objectives, self.cfg.get("weights"))
        if scal:
            best = min(scal.items(), key=lambda kv: (kv[1], kv[0]))
            summary["best_scalar"] = {"id": best[0], "score": best[1]}
        # stagnation
        sig = sorted(fr["screening"])
        improved = (sig != self.state.get("front_ids")) or self._ideal_improved(self.state.get("ideal"), ideal)
        self.state["stagnant"] = 0 if improved else self.state.get("stagnant", 0) + 1
        self.state["front_ids"], self.state["ideal"] = sig, ideal
        return summary

    def _time_left(self, t_start: float) -> float:
        used = self.state["elapsed_s"] + (time.time() - t_start)
        return self.cfg["budget"]["max_wallclock_s"] - used

    def _ideal(self, assessments: dict[str, Assessment]) -> dict[str, float] | None:
        pool = [a for a in assessments.values() if a.eligible]
        if not pool:
            return None
        out = {}
        for o in self.objectives:
            vals = [a.objectives[o["name"]] for a in pool if a.objectives.get(o["name"]) is not None]
            out[o["name"]] = (min(vals) if o["direction"] == "min" else max(vals)) if vals else None
        return out

    def _ideal_improved(self, old, new) -> bool:
        if new is None:
            return False
        if old is None:
            return True
        for o in self.objectives:
            n, p = new.get(o["name"]), old.get(o["name"])
            if n is None or p is None:
                continue
            if (o["direction"] == "min" and n < p - 1e-9 * max(1.0, abs(p))) or (o["direction"] == "max" and n > p + 1e-9 * max(1.0, abs(p))):
                return True
        return False

    # ---- HotSpot confirmation ---------------------------------------------------------------------------
    def _confirm(self, gen: int, limit: int | None = None, force_baseline: bool = True) -> int:
        """Run real HotSpot for the best unconfirmed designs of the screening front. Returns runs used."""
        if self.pipe.hotspot_mode == "never" or not self.pipe.hotspot_ready():
            return 0
        budget = self.cfg["budget"]["max_hotspot_runs"] - self.state["hotspot_runs"]
        k = min(limit if limit is not None else int(self.cfg["population"]["hotspot_per_generation"]), budget)
        if k <= 0:
            return 0
        assessments = self.assess_all()
        fr = self.fronts(assessments)["screening"]
        sc = scalar_scores(list(assessments.values()), self.objectives, self.cfg.get("weights"))
        todo = [i for i in sorted(fr, key=lambda i: (sc.get(i, 9e9), i)) if assessments[i].tier != "confirmed"]
        if force_baseline and gen == 0:
            base = [d for d in self.archive.designs.values() if d.genes["mode"] == "gpu_only"]
            for d in base[:1]:
                if d.id not in todo and assessments[d.id].tier != "confirmed" and assessments[d.id].eligible:
                    todo.insert(0, d.id)
        picks = todo[:k]
        if not picks:
            return 0
        designs = [self.archive.designs[i] for i in picks]
        self.log(f"  HotSpot: confirming {len(designs)} design(s) {picks}")
        res = self.pipe.stage_c(designs, self.archive)
        used = sum(int(r.cost.get("hotspot_runs", 0)) for r in res.values())
        self.state["hotspot_runs"] += used
        return used

    # ---- main driver ----------------------------------------------------------------------------------
    def run(self, max_generations: int | None = None) -> dict:
        """Run (or resume) until a budget, stagnation or the generation limit stops it."""
        bud = self.cfg["budget"]
        t_start = time.time()
        self.archive.snapshot_config(self.cfg, self.space.to_dict())
        self._write_status("running")
        gen = self.state["generation_done"] + 1
        limit = max_generations if max_generations is not None else bud["max_generations"]
        self.log(f"design loop '{self.cfg['name']}' seed {self.cfg['seed']} in {self.run_dir}")
        self.log("evaluators: " + json.dumps({k: (v.get("available"), v.get("detail")) if isinstance(v, dict) and 'available' in v else v
                                              for k, v in self.pipe.describe().items()}, default=str))
        reason = None
        if self.pipe.hotspot_mode == "always" and not self.pipe.hotspot_ready():
            raise RuntimeError("evaluators.package.hotspot = 'always' but HotSpot is unavailable: "
                               + str(self.pipe.hotspot.available()[1] if self.pipe.hotspot else "no package evaluator"))
        try:
            while True:
                if gen >= limit:
                    reason = "generation limit"
                    break
                if len(self.archive.designs) >= bud["max_designs"] and gen > 0:
                    reason = "design budget"
                    break
                if self._time_left(t_start) <= 0:
                    reason = "wall-clock budget"
                    break
                if (bud.get("hotspot_exhausted_stops") and self.pipe.hotspot_ready()
                        and self.state["hotspot_runs"] >= bud["max_hotspot_runs"]):
                    reason = "HotSpot-run budget"
                    break
                if self.state.get("stagnant", 0) >= bud["stagnation_generations"]:
                    reason = "stagnation"
                    break
                g0 = time.time()
                s = self.run_generation(gen, t_start)
                s["seconds"] = time.time() - g0
                self.archive.append_generation(s)
                self.state["generation_done"] = gen
                self.state["elapsed_s"] += time.time() - g0
                t_start = time.time()
                self.archive.save_state(self.state)
                self._log_generation(s)
                if s["new_designs"] == 0 and gen > 0:
                    reason = "no new designs (space exhausted for the operators used)"
                    break
                gen += 1
            # final confirmation of the screening front
            fin = int(self.cfg["final"]["hotspot_finalists"])
            if fin and self.pipe.hotspot_ready():
                left = bud["max_hotspot_runs"] - self.state["hotspot_runs"]
                used = self._confirm(gen, limit=min(fin, left), force_baseline=False)
                if used:
                    self.log(f"  final confirmation: {used} HotSpot run(s)")
        finally:
            self.state["stop_reason"] = reason
            self.archive.save_state(self.state)
            self._write_status("stopped: " + str(reason))
            self.archive.close()
        self.log(f"stopped: {reason}")
        return self.state

    def _log_generation(self, s: dict) -> None:
        self.log(f"gen {s['generation']:>2}: +{s['new_designs']} designs ({s['designs_total']} total), status {s['status']}, "
                 f"front {s['front_screening']} screened / {s['front_confirmed']} confirmed, "
                 f"HotSpot {s['hotspot_runs_this_gen']} (total {s['hotspot_runs_total']}), {s['seconds']:.1f}s")

    def _write_status(self, text: str) -> None:
        (self.run_dir / "STATUS.txt").write_text(f"{text}\n{NOTICE}\nleaderboard_comparable: false\n")
