"""Time and energy to solution for concrete workloads.

*Fault-tolerant* workloads are costed with :func:`qec.plan_workload`: distance,
magic-state factories, runtime, physical qubits used. *Variational* workloads
run on the bare physical qubits (no error correction): the model checks that
the circuit fidelity is not buried in noise, then adds quantum shot time and
the classical optimiser step on the CPUs / GPUs of the architecture.

Energy to solution is wall-plug power times runtime. The classical alternative,
where the catalog quotes one, is costed on a B200-class GPU at 50 % of peak
FP64, a deliberately generous baseline for the classical side.
"""

from __future__ import annotations

import math
from typing import Any

from . import catalog, classical, qec

REFERENCE_GPU = "gpu_b200"
REFERENCE_EFFICIENCY = 0.5
#: Memory of the reference classical node for state-vector simulation (8 GPUs x 192 GB).
REFERENCE_NODE_BYTES = 8 * 192e9


def human_time(seconds: float) -> str:
    if not math.isfinite(seconds):
        return "∞"
    for limit, div, unit in ((1e-3, 1e-6, "µs"), (1.0, 1e-3, "ms"), (120.0, 1.0, "s"), (7200.0, 60.0, "min"),
                             (172800.0, 3600.0, "h"), (86400.0 * 400, 86400.0, "days")):
        if seconds < limit:
            return f"{seconds / div:.3g} {unit}"
    return f"{seconds / (86400.0 * 365.25):.3g} years"


def human_energy(joules: float) -> str:
    if not math.isfinite(joules):
        return "∞"
    kwh = joules / 3.6e6
    if kwh >= 1e6:
        return f"{kwh / 1e6:.3g} GWh"
    if kwh >= 1e3:
        return f"{kwh / 1e3:.3g} MWh"
    if kwh >= 0.1:
        return f"{kwh:.3g} kWh"
    return f"{joules:.3g} J"


def classical_energy_j(flops: float) -> float:
    dev = classical.Device.from_catalog(REFERENCE_GPU)
    return flops * dev.tdp_w / (dev.fp64_flops * REFERENCE_EFFICIENCY)


def _fault_tolerant(w, m, budget, code, cap, total_power, reaction_s, n, blocked):
    out: dict[str, Any] = {"label": w["label"], "type": "fault_tolerant"}
    if blocked:
        out.update(feasible=False, reason=blocked)
        return out
    plan = qec.plan_workload(code, budget, n, w["logical_qubits"], w["toffoli_count"], w["toffoli_depth"],
                             w["error_budget"], reaction_s)
    reason = plan.reason
    if not plan.feasible and plan.reference_qubits:
        reason += f"; a reference design (10 factories) needs about {plan.reference_qubits:,} physical qubits"
    out.update(feasible=plan.feasible, reason=reason, reference_qubits=plan.reference_qubits)
    if plan.feasible:
        energy = plan.runtime_s * total_power
        out.update(distance=plan.distance, factories=plan.factories, runtime_s=plan.runtime_s,
                   runtime=human_time(plan.runtime_s), physical_qubits_used=plan.physical_qubits_used,
                   total_logical_error=plan.total_logical_error, bound=plan.bound,
                   energy_j=energy, energy=human_energy(energy), power_w=total_power)
    if w.get("classical_ops"):
        e_cl = classical_energy_j(w["classical_ops"])
        out.update(classical_ops=w["classical_ops"], classical_energy_j=e_cl, classical_energy=human_energy(e_cl))
        if plan.feasible:
            out["energy_advantage"] = e_cl / out["energy_j"]
    return out


def _variational(w, m, budget, blocks, total_power, n_phys):
    out: dict[str, Any] = {"label": w["label"], "type": "variational"}
    nq, layers = w["n_qubits"], w["layers"]
    if nq > n_phys:
        out.update(feasible=False, reason=f"needs {nq} qubits, architecture has {n_phys}")
        return out
    n2q = layers * (nq // 2)
    fidelity = ((1 - m["err_2q"]) ** n2q) * ((1 - m["err_1q"]) ** (layers * nq)) * ((1 - m["err_meas"]) ** nq)
    out["circuit_fidelity"] = fidelity
    if fidelity < w["min_circuit_fidelity"]:
        out.update(feasible=False, reason=f"circuit fidelity {fidelity:.2e} is below the usable floor "
                   f"{w['min_circuit_fidelity']:.0e} ({n2q} two-qubit gates at {m['err_2q']:.1e} error)")
        return out
    layer_s = (m["t_2q_ns"] + m["t_1q_ns"] + m.get("cycle_overhead_ns", 0.0) / 4) * 1e-9
    shot_s = layers * layer_s + (m["t_meas_ns"] + m["t_reset_ns"]) * 1e-9
    quantum_s = w["shots_per_iteration"] * shot_s
    opt = [b for b in blocks if b.role == "optimizer"] or [b for b in blocks if b.role == "host"]
    flops = sum(b.count * b.device.fp64_flops for b in opt) * REFERENCE_EFFICIENCY
    classical_s = w["classical_flops_per_iteration"] / flops if flops else math.inf
    iter_s = quantum_s + classical_s + 1e-3  # 1 ms host round trip
    runtime = w["iterations"] * iter_s
    # Optimiser devices run at their duty cycle, the rest of the system stays on.
    base_opt = sum(b.power_w for b in opt)
    duty = classical_s / iter_s
    actual_opt = sum(b.count * b.device.power_w(duty) for b in opt)
    power = total_power - base_opt + actual_opt
    energy = runtime * power
    out.update(feasible=True, reason="ok", shot_time_s=shot_s, quantum_time_per_iter_s=quantum_s,
               classical_time_per_iter_s=classical_s, runtime_s=runtime, runtime=human_time(runtime),
               classical_duty=duty, power_w=power, energy_j=energy, energy=human_energy(energy))
    sim_mem = 16.0 * 2.0 ** nq
    sim_flops = w["iterations"] * layers * 13.0 * nq * 2.0 ** nq
    out["classical_sim_memory_bytes"] = sim_mem
    if sim_mem <= REFERENCE_NODE_BYTES:
        e_cl = classical_energy_j(sim_flops)
        out.update(classical_ops=sim_flops, classical_energy_j=e_cl, classical_energy=human_energy(e_cl),
                   energy_advantage=e_cl / energy)
    else:
        out["classical_note"] = (f"state-vector simulation needs {sim_mem / 1e12:.3g} TB, "
                                 f"more than the {REFERENCE_NODE_BYTES / 1e12:.1f} TB reference node")
    return out


def run_all(cfg, m, budget, code, cap, blocks, total_power, reaction_s, names, blocked=None):
    catalog_w = catalog.load("workloads")
    keys = names if names is not None else [k for k in catalog_w if not k.startswith("_")]
    results = {}
    for key in keys:
        w = catalog_w[key]
        if w["type"] == "fault_tolerant":
            results[key] = _fault_tolerant(w, m, budget, code, cap, total_power, reaction_s,
                                           int(cfg["n_qubits"]), blocked)
        else:
            results[key] = _variational(w, m, budget, blocks, total_power, int(cfg["n_qubits"]))
    return results
