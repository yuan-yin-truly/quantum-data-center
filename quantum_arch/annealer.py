"""Quantum annealers as their OWN class, with their own metrics.

An annealer is a special-purpose sampler for optimisation problems (Ising / QUBO). It is not a
universal gate-based QPU: it has no logical qubits, no error-correcting code and no rQOPS, and its
qubit count cannot be compared with gate-model qubits. So this module deliberately does not go
through :func:`quantum_arch.evaluate`. Its metrics are:

* samples per second (anneal + readout) and the per-problem programming time;
* **time-to-target** and **energy-to-target**: what it takes to obtain, with a stated confidence,
  at least one sample that meets a stated solution quality, charged at the module, system and
  facility boundaries together with the classical host that embeds the problem and post-processes.

The probability that one read reaches the target quality is a property of the PROBLEM and the
target, not of the hardware alone; it is an input (``p_success_per_read``) and must come from a
benchmark of that problem class. Nothing here asserts that an annealer beats a classical solver.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from . import catalog, classical
from .architecture import canonical_profile

DEFAULT_ANNEALER_CONFIG: dict[str, Any] = {
    "name": "unnamed_annealer",
    "annealer": "advantage2_class",
    "profile": "mid2030s",
    "overrides": {},
    "host": {"device": "auto:cpu", "count": 1, "utilisation": 0.3},
    "facility": {"pue": 1.2, "network_support_w": 0.0, "include_server_overhead": False},
}


@dataclass
class AnnealerResult:
    name: str
    spec: dict[str, Any]
    profile: str
    sample_time_s: float
    samples_per_s: float
    power_w: dict[str, float]
    boundaries: dict[str, Any]
    host_device: classical.Device
    host_count: int
    host_utilisation: float
    host_power_w: float
    include_server_overhead: bool = False
    metrics_family: str = "annealing (NOT comparable with rQOPS or logical-qubit metrics)"

    @property
    def system_power_w(self) -> float:
        return sum(self.power_w.values())

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "annealer": self.spec["label"], "profile": self.profile, "n_qubits": self.spec["n_qubits"],
                "metrics_family": self.metrics_family, "sample_time_s": self.sample_time_s,
                "samples_per_s": self.samples_per_s, "power_w": self.power_w, "system_power_w": self.system_power_w,
                "power_boundaries": self.boundaries, "host": {"device": self.host_device.label, "count": self.host_count,
                                                            "power_w": self.host_power_w}}


def resolve_annealer(key: str, profile: str, overrides: dict | None = None) -> dict[str, Any]:
    raw = catalog.entry("annealers", key)
    profile = canonical_profile(profile)
    if profile not in raw["profiles"]:
        raise KeyError(f"annealer {key!r} has no profile {profile!r}; known: {', '.join(raw['profiles'])}")
    flat = {k: v for k, v in raw.items() if k != "profiles"}
    return catalog.deep_merge(catalog.deep_merge(flat, raw["profiles"][profile]), overrides)


def evaluate_annealer(config: dict[str, Any]) -> AnnealerResult:
    cfg = catalog.deep_merge(DEFAULT_ANNEALER_CONFIG, config)
    profile = canonical_profile(cfg["profile"])
    spec = resolve_annealer(cfg["annealer"], profile, cfg["overrides"])
    sample_s = (spec["anneal_time_us"] + spec["readout_us"]) * 1e-6
    power = {k: spec["system_power_w"] * f for k, f in spec["power_split"].items()}
    host = cfg["host"]
    dev = classical.Device.from_catalog(host["device"], profile)
    host_w = host["count"] * dev.power_w(host["utilisation"])
    pue = float(cfg["facility"]["pue"])
    net = float(cfg["facility"].get("network_support_w", 0.0))
    server_over = host["count"] * dev.power_w(host["utilisation"]) * (dev.system_overhead_ratio - 1.0) \
        if cfg["facility"].get("include_server_overhead") else 0.0
    system = sum(power.values()) + host_w + server_over
    boundaries = {
        "module": {"cold_heat_load_w": spec["cold_heat_w"], "temperature_k": spec["temperature_k"],
                   "note": "the QPU chip dissipates far less than a milliwatt at ~mK (assumption); this is thermal, not wall power"},
        "system": {"power_w": system, "qpu_system_w": spec["system_power_w"], "host_w": host_w + server_over,
                   "note": "vendor-reported system consumption (compressors, control electronics, support) + the user's classical host"},
        "facility": {"power_w": (system + net) * pue, "pue": pue, "network_support_w": net,
                     "note": "(system + network/support) x PUE"},
    }
    return AnnealerResult(name=cfg["name"], spec=spec, profile=profile, sample_time_s=sample_s, samples_per_s=1.0 / sample_s,
                          power_w=power, boundaries=boundaries, host_device=dev, host_count=host["count"],
                          host_utilisation=host["utilisation"], host_power_w=host_w + server_over,
                          include_server_overhead=bool(cfg["facility"].get("include_server_overhead")))


def solve_cost(res: AnnealerResult, p_success_per_read: float, confidence: float = 0.99, max_reads: int = 100_000,
               host_pre_s: float = 1.0, host_post_s: float = 0.5) -> dict[str, Any]:
    """Time and energy to obtain, with ``confidence``, at least one sample at the target quality.

    ``p_success_per_read`` is the per-read probability of reaching the target solution quality (problem
    dependent). Reads needed: ``ceil(ln(1 - confidence) / ln(1 - p))``, capped at ``max_reads`` (then the
    achieved confidence is reported and may be lower). Energy per accepted answer divides the energy of
    one attempt by the probability that the attempt succeeds.
    """
    if not 0.0 < p_success_per_read <= 1.0:
        raise ValueError("p_success_per_read must be in (0, 1]")
    reads = 1 if p_success_per_read >= 1.0 else max(1, math.ceil(math.log(1 - confidence) / math.log(1 - p_success_per_read)))
    capped = reads > max_reads
    reads = min(reads, max_reads)
    achieved = 1.0 - (1.0 - p_success_per_read) ** reads
    qpu_s = res.spec["programming_ms"] * 1e-3 + reads * res.sample_time_s
    wall_s = host_pre_s + qpu_s + host_post_s
    ratio = res.host_device.system_overhead_ratio if res.include_server_overhead else 1.0
    host_busy_w = res.host_count * res.host_device.power_w(1.0) * ratio
    # The annealer is charged for the time the problem occupies it (its power is drawn all the time; a busy
    # queue is assumed). The host is charged for pre- and post-processing.
    e_sys = sum(res.power_w.values()) * qpu_s + host_busy_w * (host_pre_s + host_post_s)
    pue = res.boundaries["facility"]["pue"]
    net = res.boundaries["facility"]["network_support_w"]
    e_fac = (e_sys + net * wall_s) * pue
    return {"reads": reads, "confidence_requested": confidence, "confidence_achieved": achieved, "capped": capped,
            "qpu_time_s": qpu_s, "time_to_target_s": wall_s,
            "energy_system_j": e_sys / achieved, "energy_facility_j": e_fac / achieved,
            "accept_probability": achieved, "boundary": "system and facility; per ACCEPTED solution",
            "note": "energy-to-target for ONE problem instance at the stated quality; not a rate and not comparable with rQOPS"}
