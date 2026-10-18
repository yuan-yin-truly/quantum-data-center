"""GPU / CPU baseline workloads with matched-quality metrics.

The yardstick for every comparison in this package is ENERGY (and time) PER ACCEPTED ANSWER at the
same problem, accuracy and latency, charged at an explicit boundary:

* ``module``   the accelerator modules only (boundary 1),
* ``system``   complete servers: modules x ``system_overhead_ratio`` (boundary 2),
* ``facility`` system x PUE, plus network/support (boundary 3).

Baselines provided: LLM inference (joules per token at matched model and latency SLO), LLM
training to a fixed quality target (energy and time), and dense matrix multiplication. There is no
quantum counterpart for any of them here, and none is implied: ordinary AI and dense linear algebra
are not accelerated by the quantum routines in this package (see ``quantum_linear_algebra`` in
``workloads.py`` for the explicit data-loading / read-out overhead).
"""

from __future__ import annotations

from typing import Any

from . import catalog, classical


def _facility(e_system: float, pue: float, network_fraction: float) -> float:
    return e_system * (1.0 + network_fraction) * pue


def llm_tokens_per_s(device: classical.Device, baseline: dict[str, Any] | None = None) -> float:
    """Tokens/s per module at the latency SLO (full load): memory-bound decode, compute-capped."""
    b = baseline or catalog.entry("baselines", "llm_inference_70b")
    mem_bound = device.hbm_tbps * b["tokens_per_s_per_tbps"]
    compute_cap = device.fp16_flops * b["low_precision_gain"] * b["inference_mfu"] / b["flops_per_token"]
    return min(mem_bound, compute_cap) if device.hbm_tbps > 0 else compute_cap


def llm_inference(device_key: str, profile: str | None = None, utilisation: float | None = None, pue: float = 1.0,
                  network_fraction: float = 0.0, baseline_key: str = "llm_inference_70b") -> dict[str, Any]:
    """Joules per token and per answer at module / system / facility boundary.

    ``utilisation`` is the served fraction of the SLO-limited throughput; idle power is paid
    regardless, so low utilisation raises the energy per token (energy proportionality).
    """
    b = catalog.entry("baselines", baseline_key)
    dev = classical.Device.from_catalog(device_key, profile)
    u = b["default_utilisation"] if utilisation is None else utilisation
    tok_s = llm_tokens_per_s(dev, b)
    served = u * tok_s
    p_module = dev.power_w(u)
    e_tok_module = p_module / served
    e_tok_system = e_tok_module * dev.system_overhead_ratio
    out = {
        "workload": b["label"], "device": dev.label, "utilisation": u, "tokens_per_s_per_module_at_slo": tok_s,
        "served_tokens_per_s": served,
        "j_per_token": {"module": e_tok_module, "system": e_tok_system,
                        "facility": _facility(e_tok_system, pue, network_fraction)},
        "j_per_answer": {}, "gpu_seconds_per_answer": b["tokens_per_answer"] / tok_s,
        "note": "same model (70B-class), same latency SLO and quality across devices is an assumption carried by the "
                "throughput anchor; module power is idle + (TDP - idle) x utilisation; rated power, not measured"}
    out["j_per_answer"] = {k: v * b["tokens_per_answer"] for k, v in out["j_per_token"].items()}
    return out


def llm_training(device_key: str, n_modules: int, profile: str | None = None, pue: float = 1.0,
                 network_fraction: float = 0.0, baseline_key: str = "llm_training_to_quality",
                 utilisation: float = 1.0) -> dict[str, Any]:
    """Time and energy to train to the baseline's fixed quality target (6 N D FLOPs at a given MFU)."""
    b = catalog.entry("baselines", baseline_key)
    dev = classical.Device.from_catalog(device_key, profile)
    flops = b["flops_per_param_token"] * b["params"] * b["tokens"]
    rate = n_modules * dev.rate(b["flops_kind"]) * b["mfu"]
    t = flops / rate
    e_module = n_modules * dev.power_w(utilisation) * t
    e_system = e_module * dev.system_overhead_ratio
    return {"workload": b["label"], "device": dev.label, "n_modules": n_modules, "total_flops": flops, "time_s": t,
            "time_days": t / 86400.0, "gpu_seconds": t * n_modules,
            "energy_j": {"module": e_module, "system": e_system, "facility": _facility(e_system, pue, network_fraction)},
            "note": "energy and time to a FIXED quality target (the loss reached by this N, D pair); a different training "
                    "recipe is comparable only if it reaches the same target"}


def dense_matmul(device_key: str, profile: str | None = None, pue: float = 1.0, network_fraction: float = 0.0,
                 baseline_key: str = "dense_matmul") -> dict[str, Any]:
    b = catalog.entry("baselines", baseline_key)
    dev = classical.Device.from_catalog(device_key, profile)
    flops = 2.0 * b["n"] ** 3
    t = flops / (dev.rate(b["flops_kind"]) * b["mfu"])
    e_module = dev.tdp_w * t
    e_system = e_module * dev.system_overhead_ratio
    return {"workload": b["label"], "device": dev.label, "flops": flops, "time_s": t,
            "energy_j": {"module": e_module, "system": e_system, "facility": _facility(e_system, pue, network_fraction)},
            "note": "No quantum counterpart is offered: loading N^2 inputs and reading N^2 outputs already costs as much as "
                    "the classical multiplication."}


def compare_devices(keys: list[str], profile: str | None = None, pue: float = 1.0, network_fraction: float = 0.0) -> list[dict]:
    """J/token (system boundary) and tokens/s of several devices at the baseline utilisation."""
    rows = []
    for k in keys:
        r = llm_inference(k, profile, pue=pue, network_fraction=network_fraction)
        rows.append({"device": r["device"], "tokens_per_s": r["tokens_per_s_per_module_at_slo"],
                     "j_per_token_module": r["j_per_token"]["module"], "j_per_token_system": r["j_per_token"]["system"],
                     "j_per_token_facility": r["j_per_token"]["facility"]})
    return rows

