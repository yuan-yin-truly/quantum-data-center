"""Quantum feasibility, time and energy of a job on a QPU node type: a thin cached layer over ``quantum_arch``.

Nothing here invents a speed-up. Feasibility, runtime, energy and acceptance probability of a gate-model job come from
``quantum_arch.datacenter.quantum_job_check`` (-> ``quantum_arch.evaluate``); annealer jobs come from
``quantum_arch.annealer.solve_cost``. Results are cached per (architecture, workload) because the call costs ~10 ms.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

# make the sibling package importable when dc_sim is run from anywhere
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from quantum_arch import annealer as _an  # noqa: E402
from quantum_arch import baselines as _bl  # noqa: E402
from quantum_arch import catalog as _cat  # noqa: E402
from quantum_arch import classical as _cl  # noqa: E402
from quantum_arch import datacenter as _dc  # noqa: E402

PROFILE = "mid2030s"


@lru_cache(maxsize=None)
def gate_check(arch: str, workload: str) -> dict[str, Any]:
    """Feasibility/time/energy of a gate-model workload on a quantum_arch architecture (system boundary)."""
    return _dc.quantum_job_check(arch, workload)


@lru_cache(maxsize=None)
def annealer_result(name: str):
    return _an.evaluate_annealer({"annealer": name, "profile": PROFILE})


@lru_cache(maxsize=None)
def anneal_check(name: str, p_success: float, confidence: float, max_reads: int, pre_s: float, post_s: float) -> dict[str, Any]:
    res = annealer_result(name)
    sc = _an.solve_cost(res, p_success, confidence, max_reads, pre_s, post_s)
    return {"feasible": True, "reason": "ok", "runtime_s": sc["time_to_target_s"], "energy_system_j": sc["energy_system_j"],
            "p_accept": sc["accept_probability"], "system_power_w": res.system_power_w, "detail": sc}


@lru_cache(maxsize=None)
def qpu_profile(arch: str | None, annealer: str | None = None) -> dict[str, Any]:
    """Power of one QPU system: busy and standby (cryostat, vacuum, lasers stay on) at the SYSTEM boundary, plus module power."""
    if annealer:
        res = annealer_result(annealer)
        of = 0.2
        standby = sum(v * (1.0 if ("cryostat" in k or "support" in k) else of) for k, v in res.power_w.items())
        return {"label": res.name, "busy_w": res.system_power_w, "standby_w": standby, "module_w": 0.0, "n_qubits": res.spec["n_qubits"],
                "source": "quantum_arch.annealer (advantage2_class, mid2030s)"}
    chk = gate_check(arch, "vqe_20q")
    a = _dc.load_architecture(arch)
    return {"label": a.name, "busy_w": chk["system_power_w"], "standby_w": chk["standby_w"], "module_w": chk["module_power_w"],
            "n_qubits": a["n_qubits"], "source": f"quantum_arch.evaluate({arch}, mid2030s base scenario)"}


@lru_cache(maxsize=None)
def gpu_module() -> dict[str, Any]:
    """The 2035 accelerator module from quantum_arch (FROM quantum_arch): power, server overhead, LLM token rates."""
    dev = _cl.Device.from_catalog("gpu_2035", PROFILE)
    b = _cat.entry("baselines", "llm_inference_70b")
    decode = _bl.llm_tokens_per_s(dev, b)
    prefill = dev.fp16_flops * b["low_precision_gain"] * b["inference_mfu"] / b["flops_per_token"]
    return {"label": dev.label, "tdp_w": dev.tdp_w, "idle_w": dev.idle_w, "overhead": dev.system_overhead_ratio,
            "decode_tok_s_70b": decode, "prefill_tok_s_70b": prefill, "hbm_tbps": dev.hbm_tbps,
            "source": "quantum_arch classical.gpu_2035; decode: baselines.llm_tokens_per_s (memory-bound); prefill: fp16_flops x low_precision_gain x inference_mfu / flops_per_token (compute-bound, same constants as the decode cap)"}


def quantum_check(node_type_cfg: dict, qspec: dict) -> dict[str, Any]:
    """Check for a task's quantum spec on a node type config: returns the dict of the gate/annealer check
    (feasible, reason, runtime_s, energy_system_j, p_accept ...). ``qspec`` is the task's ``quantum`` dict."""
    kind = qspec.get("kind", "gate")
    if node_type_cfg["kind"] == "annealer":
        if kind != "annealer":
            return {"feasible": False, "reason": "annealers only run annealing/optimisation jobs"}
        return anneal_check(node_type_cfg["annealer"], float(qspec["p_success_per_read"]), float(qspec.get("confidence", 0.99)),
                            int(qspec.get("max_reads", 100000)), float(qspec.get("prep_s", 1.0)), float(qspec.get("post_s", 0.5)))
    if kind == "annealer":
        return {"feasible": False, "reason": "gate-model QPUs do not run annealing jobs in this model"}
    return gate_check(node_type_cfg["architecture"], qspec["workload"])
