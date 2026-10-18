"""QuantumSystemEvaluator: ``quantum_arch.evaluate`` on the design's architecture.

Reports feasibility against the logical-error budget, rQOPS, energy/runtime of EVERY quantum workload in the
catalog (the design x quantum-workload matrix), cryostat stage utilisation and fridge units, decoder sizing, and
power at the three boundaries (module / system / facility). Hard constraints are reported as violations; the
objective layer decides what is eligible.
"""

from __future__ import annotations

import math
from typing import Any

from .. import integration as I
from ..genes import Design
from .base import MODEL, OK, REAL, EvalResult, Timer, errored, unavailable

try:
    from quantum_arch import Architecture, evaluate
    _IMPORT_ERROR = None
except Exception as exc:                                # pragma: no cover
    Architecture = evaluate = None
    _IMPORT_ERROR = exc


def _finite(x):
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


class QuantumSystemEvaluator:
    name = "quantum"

    def __init__(self, max_fridge_units: int = 100, min_task_p_accept: float = 0.5):
        self.max_fridge_units = max_fridge_units
        self.min_task_p_accept = min_task_p_accept

    def available(self) -> tuple[bool, str]:
        return (evaluate is not None, "ok" if evaluate is not None else f"quantum_arch not importable: {_IMPORT_ERROR}")

    def cache_key(self, design: Design, context: dict[str, EvalResult] | None = None) -> str:
        g = design.genes
        return "gpu_only" if g["mode"] == "gpu_only" else I.quantum_key(g) + f"|task={g['task']}"

    # ------------------------------------------------------------------------------------------------
    def evaluate(self, design: Design, context: dict[str, EvalResult] | None = None) -> EvalResult:
        g = design.genes
        key = self.cache_key(design, context)
        if g["mode"] == "gpu_only":
            return EvalResult(self.name, OK, MODEL, metrics={"present": False}, key=key,
                              notes=["GPU-only baseline: no quantum subsystem"], cost={"seconds": 0.0})
        ok, why = self.available()
        if not ok:
            return unavailable(self.name, why)
        with Timer() as t:
            try:
                arch = Architecture.from_dict(I.architecture_dict(g, name=f"d{design.id}"))
                res = evaluate(arch)
            except (ValueError, KeyError) as exc:               # structurally invalid combination of catalog entries
                r = EvalResult(self.name, OK, REAL, metrics={"present": True, "valid": False, "task_feasible": False},
                               violations=[f"invalid architecture: {exc}"], key=key, boundary="system")
                r.cost = {"seconds": 0.0}
                return r
            except Exception as exc:                            # unexpected -> reported, design becomes partial
                return errored(self.name, exc)
        return self._summarise(design, res, key, t.seconds)

    # ------------------------------------------------------------------------------------------------
    def _summarise(self, design: Design, res, key: str, seconds: float) -> EvalResult:
        g = design.genes
        cap, cry = res.capability, res.cryo
        dec = next((b for b in res.blocks if b.role == "decoder"), None)
        per_wl: dict[str, dict[str, Any]] = {}
        for wk, w in res.workloads.items():
            per_wl[wk] = {"feasible": bool(w.get("feasible")), "reason": w.get("reason", ""),
                          "runtime_s": _finite(w.get("runtime_s")), "energy_system_j": _finite(w.get("energy_j")),
                          "energy_facility_j": _finite(w.get("facility_energy_j")), "p_accept": _finite(w.get("p_accept")),
                          "type": w.get("type"), "boundary": "system (energy_system_j) / facility (energy_facility_j)",
                          "catalog_classical_energy_j": _finite(w.get("classical_energy_j")),
                          "advantage_claimed": False}
            rec = per_wl[wk]
            if rec["feasible"] and rec["runtime_s"] is None:       # quantum_arch calls an unbounded runtime "feasible"
                rec["feasible"] = False
                rec["reason"] = "runtime unbounded: the classical optimiser device supplies no FP64 throughput"
        task = per_wl.get(g["task"], {"feasible": False, "reason": "task not in catalog"})
        stages = []
        if cry:
            for s in cry.stages:
                stages.append({"stage": s.name, "load_w": s.load_w, "capacity_w": s.capacity_w,
                               "utilisation": (s.load_w / s.capacity_w) if s.capacity_w else None,
                               "overloaded": bool(s.overloaded)})
        max_util = max([s["utilisation"] for s in stages if s["utilisation"] is not None], default=0.0)
        fridge_units = int(cry.units_needed) if cry else 0
        units_for_lines = int(cry.units_for_lines) if cry else 0
        decoder_dev_w = dec.power_w / dec.count if dec and dec.count else 0.0
        metrics = {
            "present": True, "valid": True,
            "task": g["task"], "task_feasible": bool(task.get("feasible")), "task_reason": task.get("reason", ""),
            "task_runtime_s": task.get("runtime_s"), "task_energy_system_j": task.get("energy_system_j"),
            "task_energy_facility_j": task.get("energy_facility_j"), "task_p_accept": task.get("p_accept"),
            "n_quantum_workloads_feasible": sum(1 for w in per_wl.values() if w["feasible"]),
            "n_quantum_workloads": len(per_wl),
            "error_corrected": bool(cap.feasible), "logical_qubits": cap.logical_qubits, "rqops": cap.rqops,
            "code_distance": cap.distance or 0, "lambda": _finite(cap.lam),
            "logical_error_per_op": _finite(cap.logical_error_per_op),
            "fridge_units": fridge_units, "units_for_lines": units_for_lines, "max_stage_utilisation": max_util,
            "n_lines": res.metrics.get("n_lines"), "cryostat_stages": stages,
            "decoder_keeps_up": bool(dec.keeps_up) if dec else True,
            "decoder_devices": int(dec.count) if dec else 0, "decoder_device": dec.device.key if dec else None,
            "decoder_device_active_w": decoder_dev_w, "decoder_device_idle_w": dec.device.idle_w if dec else 0.0,
            "decoder_total_w": dec.power_w if dec else 0.0,
            "decoder_location_costed": dec.location if dec else None,
            # power at the three boundaries (see quantum_arch README)
            "power_module_w": res.boundaries["module"]["electrical_w"],
            "power_system_w": res.total_power_w,
            "power_facility_w": res.boundaries["facility"]["power_w"],
            "cryostat_wall_w": res.boundaries["system"]["cryostat_wall_w"],
            "pue": res.boundaries["facility"]["pue"],
            "power_by_consumer_w": dict(res.power_w),
            "warnings": list(res.warnings),
            "architecture_name": res.arch.name,
        }
        v: list[str] = []
        if not metrics["task_feasible"]:
            v.append(f"quantum task {g['task']} not feasible: {metrics['task_reason']}")
        elif (metrics["task_p_accept"] or 0.0) < self.min_task_p_accept:
            v.append(f"task acceptance probability {metrics['task_p_accept']:.2f} below {self.min_task_p_accept}")
        if not metrics["decoder_keeps_up"]:
            v.append("decoder bank cannot keep up with the syndrome stream")
        if units_for_lines > 1:
            v.append(f"control lines exceed one cryostat ({units_for_lines} units; no cryogenic interconnect modelled)")
        if fridge_units > self.max_fridge_units:
            v.append(f"{fridge_units} fridge units exceed the limit {self.max_fridge_units}")
        r = EvalResult(self.name, OK, REAL, metrics=metrics, per_workload=per_wl, violations=v, key=key,
                       boundary="module/system/facility, stated per field",
                       cost={"seconds": seconds}, notes=["catalog classical-alternative energies are carried for reference "
                                                       "only; no quantum advantage is claimed or used in any objective"])
        return r
