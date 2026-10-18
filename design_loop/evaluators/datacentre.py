"""DataCentreEvaluator: facility-level energy per accepted answer, capacity versus GPU-only, break-even.

Primary implementation: an adapter to the hybrid data-centre scheduler ``quantum_arch.datacenter`` (a classical
scheduler routes jobs to a GPU partition or a quantum pool; acceptance probability and energy per accepted answer
come from ``quantum_arch.evaluate``). If that module is missing or fails to import, a minimal closed-form STAND-IN
is used and every result is marked ``source = "stub"``.

How a design maps onto the scheduler (all of it INPUT assumptions, nothing derived from a speedup claim):

* ``offload_fraction`` f is the share of each remaining GPU's work assumed movable; the movable share of the whole
  GPU demand is  phi = f * (4 - k) / 4  with k support dies replaced (so the share of the demand that is moved is
  exactly what the package model unloads from the GPUs).
* ``add``      -> scenario ``augment``: keep every GPU, ``n_quantum_systems`` systems added.
* ``replace``  -> scenario ``replace``: the fraction k/4 of GPU capacity is removed (those dies became
  quantum-support chiplets), ``n_quantum_systems`` systems added.
* the movable job class carries the classical cost, mapping quality and host-side times given in the run config
  (``datacentre.movable_class``); the scheduler itself has NO "1 QPU = N GPUs" conversion.
* policy ``always`` (default) routes the declared movable share to the quantum pool, limited only by the pool's
  utilisation cap, so the offload really is the stated input; ``time_and_energy`` lets the scheduler refuse.

Power boundary of the energy numbers: FACILITY = (GPU servers + CPU hosts + quantum systems) x (1 + network) x PUE.
This is a different model, at a different scale (5 kW accelerator modules), than the package model (roughly 350 W
packages); the two are linked only through the design's genes.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .. import integration as I
from ..genes import Design
from .base import MODEL, OK, STUB, EvalResult, Timer, errored, unavailable

try:
    from quantum_arch import baselines as _baselines
    from quantum_arch import datacenter as _dc
    _DC_ERROR = None
except Exception as exc:                                 # pragma: no cover - exercised by the fallback test
    _dc = _baselines = None
    _DC_ERROR = exc


DEFAULT_CONFIG: dict[str, Any] = {
    "gpu": {"device": "gpu_2035", "count": 1600, "baseline_utilisation": 0.7},
    "cpu": {"device": "cpu_2035", "count": 400, "utilisation": 0.5},
    "facility": {"pue": 1.15, "network_overhead_fraction": 0.08, "rho_max": 0.85},
    "policy": "always",
    "quantum_standby_others_fraction": 0.2,
    "mix": [
        {"name": "llm_serving", "kind": "llm_inference", "tokens_per_answer": 600, "demand_share": 0.35, "ordinary_ai": True},
        {"name": "llm_training", "gpu_seconds": 66355200, "gpus_per_job": 256, "demand_share": 0.30, "ordinary_ai": True},
        {"name": "engineering_simulation", "gpu_seconds": 460800, "gpus_per_job": 16, "demand_share": 0.15},
    ],
    # The class whose movable part the offload fraction moves. classical cost = INPUT (best classical method at the
    # same accuracy); mapping quality / retries / host times = INPUT.
    "movable_class": {"name": "movable_task", "gpu_seconds": 2764800, "gpus_per_job": 64, "demand_share": 0.20,
                      "eligible_fraction": 0.5,
                      "quantum": {"mapping_quality": 0.7, "max_attempts": 2, "prep_s": 600, "transfer_s": 60,
                                  "post_s": 300, "qpu_setup_s": 60}},
    "sweep_points": 13,
    "baseline_device": "gpu_2035",
}


def deep_merge(a: dict, b: dict | None) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def _clean(x):
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


class DataCentreEvaluator:
    name = "datacentre"

    def __init__(self, config: dict | None = None, force_stand_in: bool = False):
        self.cfg = deep_merge(DEFAULT_CONFIG, config)
        self.force_stand_in = force_stand_in

    @property
    def uses_scheduler(self) -> bool:
        return _dc is not None and not self.force_stand_in

    def available(self) -> tuple[bool, str]:
        if self.uses_scheduler:
            return True, "quantum_arch.datacenter scheduler"
        return True, f"STAND-IN (scheduler unavailable: {_DC_ERROR})" if not self.force_stand_in else "STAND-IN (forced)"

    def cache_key(self, design: Design, context=None) -> str:
        g = design.genes
        keys = ("mode", "offload_fraction", "n_quantum_systems", "support_G0", "support_G1", "support_G2", "support_G3", "pue")
        return I.quantum_key(g) + "|" + "|".join(f"{k}={g[k]}" for k in keys) + f"|task={g['task']}|" + ("sched" if self.uses_scheduler else "stub")

    # ------------------------------------------------------------------------------------------------
    def _phi(self, g: dict) -> tuple[float, int]:
        k = len(I.support_dies(g))
        return float(g["offload_fraction"]) * (4 - k) / 4.0, k

    def build_config(self, g: dict, phi: float, k: int) -> dict:
        cfg = deep_merge(DEFAULT_CONFIG, self.cfg)
        cfg["facility"]["pue"] = float(g["pue"])
        cfg["profile"] = g["profile"]
        mc = copy.deepcopy(cfg["movable_class"])
        q = mc.pop("quantum")
        q.update(pool="pool", workload=g["task"])
        mc["quantum"] = q
        cfg["mix"] = copy.deepcopy(cfg["mix"]) + [mc]
        arch = I.architecture_dict(g, name="dc_pool")
        arch["workloads"] = [g["task"]]
        cfg["quantum_pools"] = {"pool": {"kind": "gate", "architecture": arch, "concurrency": 1}}
        scen: dict[str, Any] = {"quantum_systems": {"pool": int(g["n_quantum_systems"])}}
        if g["mode"] == "replace":
            scen["gpu_fraction_removed"] = k / 4.0
            scen["label"] = "replace"
        else:
            scen["label"] = "augment"
        cfg["scenarios"] = {"gpu_only": {}, "design": scen}
        for kk in ("sweep_points", "baseline_device", "movable_class"):
            cfg.pop(kk, None)
        return cfg

    # ------------------------------------------------------------------------------------------------
    def evaluate(self, design: Design, context=None) -> EvalResult:
        g = design.genes
        key = self.cache_key(design, context)
        if g["mode"] == "gpu_only":
            return self._gpu_only(design, key)
        qres = (context or {}).get("quantum")
        with Timer() as t:
            try:
                res = self._scheduler(g, key) if self.uses_scheduler else self._stand_in(g, key, qres)
            except Exception as exc:
                return errored(self.name, exc)
        res.cost["seconds"] = t.seconds
        res.per_workload["gpu_baseline"] = self._baselines(g)
        return res

    # ---- GPU-only reference: the baseline against which everything is relative -------------------------
    def _gpu_only(self, design: Design, key: str) -> EvalResult:
        g = design.genes
        if not self.uses_scheduler:
            return EvalResult(self.name, OK, STUB, metrics={"energy_ratio_vs_gpu_only": 1.0, "capacity_rel": 1.0,
                                                            "served_fraction": 1.0, "stand_in": True, "movable_share": 0.0,
                                                            "facility_j_per_work_unit": 5000.0 * 1.3 * float(g["pue"]) * (1 + float(self.cfg["facility"]["network_overhead_fraction"]))},
                              key=key, boundary="facility", notes=["STAND-IN: GPU-only baseline is 1.0 by definition"])
        with Timer() as t:
            ref = dict(g, mode="add", task="vqe_20q", n_quantum_systems=1, modality="superconducting",
                       scheme="cryo_cmos_4k", code="surface", decoder="union_find", decoder_device="auto:asic_rt",
                       decoder_location="RT", host_device="auto:cpu", host_count=1, optimizer_device="auto:gpu",
                       optimizer_count=1, optimizer_location="RT", n_qubits=1000, cryostat_scale=1.0)
            cfg = self.build_config(ref, 0.0, 0)     # a pool is configured only so the mix is valid; it gets no systems
            cfg["scenarios"] = {"gpu_only": {}}
            cfg = _dc.with_movable_share(_dc.load_config(cfg), 1e-6)
            out = _dc.run_datacenter(cfg)["scenarios"]["gpu_only"]
        m = {"facility_j_per_work_unit": out["facility_j_per_baseline_gpu_second"], "energy_ratio_vs_gpu_only": 1.0,
             "capacity_rel": 1.0, "ordinary_ai_capacity_ratio": 1.0, "served_fraction": out["served_fraction"],
             "power_facility_w": out["power_w"]["facility"], "power_system_w": out["power_w"]["system"],
             "power_module_w": out["power_w"]["module"], "gpu_utilisation": out["gpu_utilisation"],
             "movable_share": 0.0, "quantum_systems": 0, "stand_in": False,
             "break_even_movable_share_energy": None, "break_even_movable_share_capacity": None}
        r = EvalResult(self.name, OK, MODEL, metrics=m, key=key, boundary="facility",
                       per_workload={"dc_class": self._class_rows(out)}, cost={"seconds": t.seconds},
                       notes=["GPU-only facility baseline from quantum_arch.datacenter"])
        r.per_workload["gpu_baseline"] = self._baselines(g)
        return r

    def _class_rows(self, scen: dict) -> dict:
        return {c["class"]: {"demand_share": c["demand_share"], "routed_to_quantum": c["routed_to_quantum"],
                             "facility_j_per_accepted_answer": c["facility_j_per_accepted_answer"],
                             "mean_turnaround_s": c["mean_turnaround_s"], "gpu_turnaround_s": c["gpu_turnaround_s"],
                             "quantum_turnaround_s": c["quantum_turnaround_s"], "note": c["note"]}
                for c in _clean(scen["classes"])}

    # ---- scheduler adapter ----------------------------------------------------------------------------
    def _scheduler(self, g: dict, key: str) -> EvalResult:
        phi, k = self._phi(g)
        cfg = self.build_config(g, phi, k)
        cfg2 = _dc.with_movable_share(_dc.load_config(cfg), min(max(phi, 1e-6), 1 - 1e-6))
        out = _dc.run_datacenter(cfg2)
        base, des = out["scenarios"]["gpu_only"], out["scenarios"]["design"]
        cmp_ = des.get("comparison", {})
        pool = next(iter(des["quantum_pools"].values()), {})
        sweep = _dc.movable_sweep(cfg, shares=[i / 20 for i in range(0, 13)], scenarios=("design",))
        be = sweep["break_even"].get("design", {})
        m = {"facility_j_per_work_unit": des["facility_j_per_baseline_gpu_second"],
             "facility_j_per_work_unit_gpu_only": base["facility_j_per_baseline_gpu_second"],
             "energy_ratio_vs_gpu_only": cmp_.get("energy_per_baseline_gpu_second_ratio"),
             "capacity_rel": cmp_.get("max_total_demand_ratio"),
             "ordinary_ai_capacity_ratio": cmp_.get("ordinary_ai_capacity_ratio"),
             "served_fraction": des["served_fraction"], "movable_share": phi, "movable_share_moved": des["movable_share_of_demand"],
             "power_facility_w": des["power_w"]["facility"], "power_facility_w_gpu_only": base["power_w"]["facility"],
             "power_system_w": des["power_w"]["system"], "power_module_w": des["power_w"]["module"],
             "gpu_utilisation": des["gpu_utilisation"], "gpu_modules": des["gpus"],
             "quantum_systems": int(g["n_quantum_systems"]), "quantum_pool_utilisation": pool.get("utilisation"),
             "quantum_pool_wait_s": pool.get("wait_s"), "quantum_pool_facility_w": pool.get("facility_power_w"),
             "break_even_movable_share_energy": be.get("movable_share_for_energy_parity"),
             "break_even_movable_share_capacity": be.get("movable_share_for_capacity_parity"),
             "break_even_note": "smallest movable share in [0, 0.6] at which THIS design (same hardware, same removed GPU "
                                "fraction) matches GPU-only; None = not reached in range",
             "unserved_note": des.get("unserved_note"), "stand_in": False}
        return EvalResult(self.name, OK, MODEL, metrics=_clean(m), key=key, boundary="facility",
                          per_workload={"dc_class": self._class_rows(des)},
                          notes=["quantum_arch.datacenter scheduler; classical cost of the movable class, mapping quality "
                                 "and offload share are INPUT assumptions; no GPU-per-QPU conversion"])

    # ---- minimal stand-in -----------------------------------------------------------------------------
    def _stand_in(self, g: dict, key: str, qres) -> EvalResult:
        """Closed-form stand-in (NOT the scheduler): capacity from the replace argument, energy from rated power.

        capacity_rel = (1 - removed) / (1 - phi) (quantum capacity assumed sufficient when the task is feasible);
        energy: GPU pool at rated utilisation + n quantum systems at facility power, per unit of accepted work.
        """
        phi, k = self._phi(g)
        removed = k / 4.0
        qm = (qres.metrics if qres is not None and qres.ok else {}) or {}
        feasible = bool(qm.get("task_feasible"))
        gpu_w = 5000.0 * 1.3                                   # documented placeholder: 5 kW module x server overhead
        n = float(self.cfg["gpu"]["count"])
        util = float(self.cfg["gpu"]["baseline_utilisation"])
        pue = float(g["pue"]) * (1 + float(self.cfg["facility"]["network_overhead_fraction"]))
        phi_eff = phi if feasible else 0.0
        cap = (1 - removed) / (1 - phi_eff) if phi_eff < 1 else math.inf
        gpu_pool_w = n * (1 - removed) * gpu_w * min(1.0, util * (1 - phi_eff) / (1 - removed))
        q_w = int(g["n_quantum_systems"]) * float(qm.get("power_system_w", 0.0)) * pue
        base_w = n * gpu_w * util * pue
        served = min(1.0, cap)
        e_ratio = ((gpu_pool_w * pue + q_w) / base_w) / served if base_w else math.nan
        m = {"energy_ratio_vs_gpu_only": e_ratio, "capacity_rel": cap, "served_fraction": served, "movable_share": phi,
             "power_facility_w": gpu_pool_w * pue + q_w, "power_facility_w_gpu_only": base_w, "stand_in": True,
             "break_even_movable_share_capacity": removed, "break_even_movable_share_energy": None,
             "facility_j_per_work_unit": e_ratio * gpu_w * pue}
        return EvalResult(self.name, OK, STUB, metrics=m, key=key, boundary="facility",
                          notes=["STAND-IN closed form, not the hybrid scheduler: capacity = (1-removed)/(1-phi); "
                                 "energy from rated powers; break-even capacity share = removed GPU fraction"])

    # ---- GPU baseline workloads (design-independent except PUE / profile) -----------------------------
    def _baselines(self, g: dict) -> dict:
        out: dict[str, Any] = {}
        if _baselines is None:
            return {"unavailable": "quantum_arch.baselines not importable"}
        dev, prof, pue = self.cfg["baseline_device"], g["profile"], float(g["pue"])
        try:
            r = _baselines.llm_inference(dev, prof, pue=pue)
            out["llm_inference_70b"] = {"j_per_answer": r["j_per_answer"], "tokens_per_s_per_module": r["tokens_per_s_per_module_at_slo"],
                                        "boundary": "module/system/facility as keyed"}
            t = _baselines.llm_training(dev, 1024, prof, pue=pue)
            out["llm_training_to_quality"] = {"energy_j": t["energy_j"], "time_days": t["time_days"], "n_modules": 1024}
            mm = _baselines.dense_matmul(dev, prof, pue=pue)
            out["dense_matmul"] = {"energy_j": mm["energy_j"], "time_s": mm["time_s"]}
        except Exception as exc:                          # pragma: no cover
            out["error"] = f"{type(exc).__name__}: {exc}"
        return _clean(out)
