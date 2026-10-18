"""Assessing a design from its evaluator results: objectives, hard constraints, partial flag, Pareto, ranking.

Statuses
--------
``complete``    every required evaluator answered for the full workload matrix -> eligible for fronts and ranking.
``infeasible``  evaluated far enough to violate a hard constraint (reasons listed) -> never eligible.
``partial``     a required evaluator was unavailable, failed or skipped (budget) -> NEVER eligible for the Pareto
                front or any ranking claim, whatever its other numbers look like.

Tiers (for complete designs)
----------------------------
``confirmed``   thermal numbers come from real HotSpot -> may support claims.
``screened``    thermal numbers come from the surrogate -> used only to steer the search.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

from .evaluators.base import OK, EvalResult

DEFAULT_OBJECTIVES = [
    {"name": "worst_gpu_c", "direction": "min", "label": "worst GPU temperature (C)", "source": "thermal", "weight": 1.0},
    {"name": "worst_hbm_c", "direction": "min", "label": "worst HBM temperature (C)", "source": "thermal", "weight": 1.0},
    {"name": "energy_j_per_work", "direction": "min", "label": "facility J per accepted GPU-second of work", "source": "datacentre",
     "weight": 1.0},
    {"name": "capacity_rel", "direction": "max", "label": "sustained capacity vs GPU-only", "source": "datacentre", "weight": 1.0},
]

DEFAULT_CONSTRAINTS = {"support_max_junction_c": 110.0, "min_served_fraction": 0.98, "max_fridge_units": 100,
                       "min_task_p_accept": 0.5}

REQUIRED = ("quantum", "package_legality", "datacentre")        # plus one thermal source (surrogate or hotspot)


@dataclass
class Assessment:
    design_id: str
    status: str = "partial"
    tier: str | None = None
    objectives: dict[str, float | None] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def eligible(self) -> bool:
        return self.status == "complete"

    def to_dict(self) -> dict:
        return {"design_id": self.design_id, "status": self.status, "tier": self.tier, "objectives": self.objectives,
                "extras": self.extras, "violations": self.violations, "missing": self.missing, "sources": self.sources}


def _num(x):
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


def pick_thermal(evals: dict[str, EvalResult]) -> EvalResult | None:
    """Real HotSpot beats the surrogate; None if neither answered."""
    for n in ("package_hotspot", "package_surrogate"):
        r = evals.get(n)
        if r is not None and r.ok and r.metrics.get("worst_gpu_c") is not None:
            return r
    return None


def assess(design_id: str, evals: dict[str, EvalResult], constraints: dict | None = None,
           objectives: list[dict] | None = None) -> Assessment:
    cons = {**DEFAULT_CONSTRAINTS, **(constraints or {})}
    a = Assessment(design_id)
    objectives = objectives or DEFAULT_OBJECTIVES
    q, dc, th = evals.get("quantum"), evals.get("datacentre"), pick_thermal(evals)
    # hard constraints reported by the evaluators themselves
    for n in ("quantum", "package_legality"):
        r = evals.get(n)
        if r is not None and r.ok:
            a.violations += list(r.violations)
    # constraints that need thermal / data-centre numbers
    if th is not None and th.metrics.get("support_peak_c") is not None:
        lim = cons["support_max_junction_c"]
        if th.metrics["support_peak_c"] > lim:
            a.violations.append(f"support chiplet reaches {th.metrics['support_peak_c']:.1f} C > {lim:g} C ({th.source})")
    if dc is not None and dc.ok and (_num(dc.metrics.get("served_fraction")) if dc.metrics.get("served_fraction") is not None else 1.0) < cons["min_served_fraction"] - 1e-6:
        a.violations.append(f"serves only {dc.metrics['served_fraction']:.0%} of the baseline demand "
                            f"(< {cons['min_served_fraction']:.0%})")
    for k, v in (cons.get("max_thermal") or {}).items():
        if th is not None and _num(th.metrics.get(k)) is not None and th.metrics[k] > v:
            a.violations.append(f"{k} {th.metrics[k]:.1f} > {v}")
    # missing evaluators (only matters when nothing already made the design infeasible)
    for n in REQUIRED:
        r = evals.get(n)
        if r is None or not r.ok:
            a.missing.append(n if r is None else f"{n} ({r.status}: {'; '.join(r.notes)[:80]})")
    if th is None:
        a.missing.append("thermal (neither HotSpot nor surrogate answered)")
    # numbers (reported for every design that has them; the status says whether they count)
    vals: dict[str, Any] = {}
    if th is not None:
        for k in ("worst_gpu_c", "worst_hbm_c", "support_peak_c", "score_informational", "package_w_mean", "package_w_max"):
            vals[k] = _num(th.metrics.get(k))
        a.sources["thermal"] = th.source
    if dc is not None and dc.ok:
        vals["energy_j_per_work"] = _num(dc.metrics.get("facility_j_per_work_unit"))
        vals["energy_ratio_vs_gpu_only"] = _num(dc.metrics.get("energy_ratio_vs_gpu_only"))
        vals["capacity_rel"] = _num(dc.metrics.get("capacity_rel"))
        vals["served_fraction"] = _num(dc.metrics.get("served_fraction"))
        vals["facility_power_w"] = _num(dc.metrics.get("power_facility_w"))
        vals["break_even_movable_share_energy"] = dc.metrics.get("break_even_movable_share_energy")
        a.sources["datacentre"] = "stub" if dc.source == "stub" else "model"
    if q is not None and q.ok:
        qm = q.metrics
        vals["n_quantum_workloads_feasible"] = qm.get("n_quantum_workloads_feasible") if qm.get("present") else None
        vals["quantum_system_power_w"] = _num(qm.get("power_system_w"))
        vals["quantum_facility_power_w"] = _num(qm.get("power_facility_w"))
        vals["fridge_units"] = qm.get("fridge_units")
        vals["rqops"] = _num(qm.get("rqops"))
        a.sources["quantum"] = "model"
    a.objectives = {o["name"]: vals.get(o["name"]) for o in objectives}
    a.extras = {k: v for k, v in vals.items() if k not in a.objectives}
    # status
    if a.violations:
        a.status = "infeasible"
    elif a.missing or any(v is None for v in a.objectives.values()):
        a.status = "partial"
        a.missing += [f"objective {k}" for k, v in a.objectives.items() if v is None]
    else:
        a.status = "complete"
    if th is not None and a.status in ("complete", "infeasible"):
        a.tier = "confirmed" if th.source == "real" else "screened"
    return a


# ------------------------------------------------------------------------------------------------------
# Pareto and ranking
# ------------------------------------------------------------------------------------------------------
def _vec(obj: dict[str, float], objectives: list[dict]) -> tuple[float, ...]:
    """All-minimise vector."""
    return tuple((obj[o["name"]] if o["direction"] == "min" else -obj[o["name"]]) for o in objectives)


def dominates(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def nondominated_sort(items: list[tuple[str, dict[str, float]]], objectives: list[dict] | None = None) -> list[list[str]]:
    """Fast non-dominated sorting. ``items`` = [(id, objective dict)]. Returns fronts (lists of ids), best first."""
    objectives = objectives or DEFAULT_OBJECTIVES
    vecs = {i: _vec(o, objectives) for i, o in items}
    ids = sorted(vecs)
    dominated_by = {i: 0 for i in ids}
    dom_set: dict[str, list[str]] = {i: [] for i in ids}
    for i in ids:
        for j in ids:
            if i != j and dominates(vecs[i], vecs[j]):
                dom_set[i].append(j)
            elif i != j and dominates(vecs[j], vecs[i]):
                dominated_by[i] += 1
    fronts, cur = [], [i for i in ids if dominated_by[i] == 0]
    while cur:
        fronts.append(cur)
        nxt = []
        for i in cur:
            for j in dom_set[i]:
                dominated_by[j] -= 1
                if dominated_by[j] == 0:
                    nxt.append(j)
        cur = sorted(nxt)
    return fronts


def pareto_front(assessments: Iterable[Assessment], objectives: list[dict] | None = None,
                 tier: str | None = None) -> list[str]:
    """Ids of the non-dominated ELIGIBLE (complete) designs; ``tier='confirmed'`` restricts to real-HotSpot designs.
    Partial and infeasible designs are excluded by construction."""
    objectives = objectives or DEFAULT_OBJECTIVES
    pool = [a for a in assessments if a.eligible and (tier is None or a.tier == tier)
            and all(a.objectives.get(o["name"]) is not None for o in objectives)]
    if not pool:
        return []
    return nondominated_sort([(a.design_id, a.objectives) for a in pool], objectives)[0]


def scalar_scores(assessments: list[Assessment], objectives: list[dict] | None = None,
                  weights: dict[str, float] | None = None) -> dict[str, float]:
    """Weighted sum of min-max normalised objectives over the eligible set (0 = best on every objective)."""
    objectives = objectives or DEFAULT_OBJECTIVES
    pool = [a for a in assessments if a.eligible and all(a.objectives.get(o["name"]) is not None for o in objectives)]
    if not pool:
        return {}
    w = {o["name"]: float((weights or {}).get(o["name"], o.get("weight", 1.0))) for o in objectives}
    tot = sum(w.values()) or 1.0
    lo = {o["name"]: min(a.objectives[o["name"]] for a in pool) for o in objectives}
    hi = {o["name"]: max(a.objectives[o["name"]] for a in pool) for o in objectives}
    out = {}
    for a in pool:
        s = 0.0
        for o in objectives:
            n = o["name"]
            span = hi[n] - lo[n]
            x = 0.0 if span <= 0 else (a.objectives[n] - lo[n]) / span
            s += w[n] * (x if o["direction"] == "min" else 1.0 - x)
        out[a.design_id] = s / tot
    return out


def ranking(assessments: list[Assessment], objectives: list[dict] | None = None, weights: dict | None = None,
            tier: str | None = None) -> list[tuple[str, float]]:
    pool = [a for a in assessments if tier is None or a.tier == tier]
    sc = scalar_scores(pool, objectives, weights)
    return sorted(sc.items(), key=lambda kv: (kv[1], kv[0]))
