"""Time and energy to solution for concrete workloads.

*Fault-tolerant* workloads are costed with :func:`qec.plan_workload`: distance,
magic-state factories, runtime, physical qubits used. *Variational* workloads
run on the bare physical qubits (no error correction): the model checks that
the circuit fidelity is not buried in noise, then adds quantum shot time and
the classical optimiser step on the CPUs / GPUs of the architecture.

Energy to solution is wall-plug power times runtime at the SYSTEM boundary
(complete quantum computer; ``energy_j``), also reported at the FACILITY
boundary (``facility_energy_j`` = (system + network/support) x PUE x runtime).
The classical alternative, where the catalog quotes one, is costed on the
profile's reference GPU (B200-class today, the mid-2030s accelerator for the
``mid2030s*`` profiles) at 50 % of peak FP64, a deliberately generous baseline
for the classical side, at the same two boundaries (module power x server
overhead ratio = system). Energy ratios are therefore same-boundary ratios; they
are not "N GPUs per QPU" conversions and say nothing about other workloads.

``quantum_linear_algebra`` workloads carry an explicit data-loading and
read-out overhead and never claim a quantum advantage (``advantage_claimed`` is
False): see :func:`_quantum_linear_algebra`.
"""

from __future__ import annotations

import math
from typing import Any

from . import catalog, classical, qec

REFERENCE_GPU = "gpu_b200"
REFERENCE_GPU_BY_FAMILY = {"today": "gpu_b200", "projected": "gpu_b200", "mid2030s": "gpu_2035"}
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


def reference_gpu(profile: str | None = None) -> classical.Device:
    fam = classical.profile_family(profile)
    return classical.Device.from_catalog(REFERENCE_GPU_BY_FAMILY.get(fam, REFERENCE_GPU), profile)


def classical_energy_j(flops: float, profile: str | None = None, boundary: str = "system") -> float:
    """Energy of ``flops`` FP64 operations on the reference GPU at 50 % of peak.

    ``boundary``: ``module`` (device power only) or ``system`` (x server overhead ratio, the same
    boundary as the quantum ``energy_j``). Facility energy = system x PUE (applied by the caller).
    """
    dev = reference_gpu(profile)
    e_module = flops * dev.tdp_w / (dev.fp64_flops * REFERENCE_EFFICIENCY)
    return e_module * (dev.system_overhead_ratio if boundary == "system" else 1.0)


class _Ctx:
    """Per-evaluation context: profile and facility factors shared by the workload models."""

    def __init__(self, cfg: dict):
        self.profile = cfg.get("profile")
        fac = cfg.get("facility", {})
        self.pue = float(fac.get("pue", 1.0))
        self.network_w = float(fac.get("network_support_w", 0.0))

    def facility_energy(self, runtime_s: float, power_w: float) -> float:
        return (power_w + self.network_w) * self.pue * runtime_s

    def facility_factor(self) -> float:
        return self.pue


def _fault_tolerant(w, m, budget, code, cap, total_power, reaction_s, n, blocked, ctx=None):
    ctx = ctx or _Ctx({})
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
                   energy_j=energy, energy=human_energy(energy), power_w=total_power,
                   facility_energy_j=ctx.facility_energy(plan.runtime_s, total_power),
                   p_accept=max(0.0, 1.0 - plan.total_logical_error), boundary="system")
    if w.get("classical_ops"):
        e_cl = classical_energy_j(w["classical_ops"], ctx.profile)
        out.update(classical_ops=w["classical_ops"], classical_energy_j=e_cl, classical_energy=human_energy(e_cl),
                   classical_energy_module_j=classical_energy_j(w["classical_ops"], ctx.profile, "module"),
                   classical_facility_energy_j=e_cl * ctx.pue)
        if plan.feasible:
            out["energy_advantage"] = e_cl / out["energy_j"]
    return out


def _variational(w, m, budget, blocks, total_power, n_phys, ctx=None):
    ctx = ctx or _Ctx({})
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
               classical_duty=duty, power_w=power, energy_j=energy, energy=human_energy(energy),
               facility_energy_j=ctx.facility_energy(runtime, power), boundary="system",
               p_accept=1.0)
    sim_mem = 16.0 * 2.0 ** nq
    sim_flops = w["iterations"] * layers * 13.0 * nq * 2.0 ** nq
    out["classical_sim_memory_bytes"] = sim_mem
    if sim_mem <= REFERENCE_NODE_BYTES:
        e_cl = classical_energy_j(sim_flops, ctx.profile)
        out.update(classical_ops=sim_flops, classical_energy_j=e_cl, classical_energy=human_energy(e_cl),
                   classical_energy_module_j=classical_energy_j(sim_flops, ctx.profile, "module"),
                   classical_facility_energy_j=e_cl * ctx.pue, energy_advantage=e_cl / energy)
    else:
        out["classical_note"] = (f"state-vector simulation needs {sim_mem / 1e12:.3g} TB, "
                                 f"more than the {REFERENCE_NODE_BYTES / 1e12:.1f} TB reference node")
    return out


def _quantum_linear_algebra(w, m, budget, code, cap, total_power, reaction_s, n, blocked, ctx):
    """HHL / QSVT-style linear solve WITH its data-loading and read-out overhead (no advantage claimed).

    Cost model (order of magnitude, assumptions in ``workloads.json``):
    * block-encoding query: ``4 s log2 N`` Toffoli; inversion needs ``2 kappa ln(2/eps)`` queries;
    * loading an explicit vector: ``N x rot_bits`` Toffoli per run (zero for an efficient oracle);
    * scalar output: amplitude estimation, ``(loading + inversion) / eps`` Toffoli in one coherent run;
    * full-vector output: tomography, about ``N / eps^2`` independent runs, each ``loading + inversion``.
    The classical comparison is conjugate gradient, ``2 N s sqrt(kappa) ln(2/eps)`` FP64 flops, when the
    vectors fit one reference node.
    """
    out: dict[str, Any] = {"label": w["label"], "type": "quantum_linear_algebra", "advantage_claimed": False,
                           "output": w["output"], "input_model": w["input_model"]}
    N, s_, kappa, eps = w["n_dim"], w["sparsity"], w["kappa"], w["epsilon"]
    lg = math.log2(N)
    logical = int(3 * lg + 20)
    t_query = 4.0 * s_ * lg
    queries = 2.0 * kappa * math.log(2.0 / eps)
    t_inv = queries * t_query
    t_load = N * w.get("rot_bits", 16) if w["input_model"] == "explicit_loading" else 0.0
    if w["output"] == "scalar":
        runs, toffoli = 1, (t_load + t_inv) / eps
    else:
        runs, toffoli = N / eps ** 2, t_load + t_inv
    out.update(logical_qubits_needed=logical, toffoli_per_run=toffoli, runs=runs, loading_toffoli=t_load,
               inversion_toffoli=t_inv)
    if blocked:
        out.update(feasible=False, reason=blocked)
        return out
    plan = qec.plan_workload(code, budget, n, logical, toffoli, toffoli, w["error_budget"], reaction_s)
    out.update(feasible=plan.feasible, reason=plan.reason)
    if plan.feasible:
        runtime = plan.runtime_s * runs
        energy = runtime * total_power
        total_toff = toffoli * runs
        out.update(distance=plan.distance, factories=plan.factories, runtime_s=runtime, runtime=human_time(runtime),
                   runtime_per_run_s=plan.runtime_s, physical_qubits_used=plan.physical_qubits_used,
                   energy_j=energy, energy=human_energy(energy), power_w=total_power, boundary="system",
                   facility_energy_j=ctx.facility_energy(runtime, total_power),
                   p_accept=max(0.0, 1.0 - plan.total_logical_error),
                   io_overhead_share=1.0 - min(1.0, t_inv / total_toff),
                   readout_repetition_factor=(1.0 / eps if w["output"] == "scalar" else runs),
                   loading_share=(t_load * (1.0 / eps if w["output"] == "scalar" else runs)) / total_toff,
                   io_note="io_overhead_share = share of all Toffoli gates beyond ONE matrix inversion: data loading plus the "
                           "repetitions needed to read the answer out to precision eps (amplitude estimation: 1/eps coherent "
                           "rounds; full-vector tomography: about N/eps^2 runs)")
    flops = 2.0 * N * s_ * math.sqrt(kappa) * math.log(2.0 / eps)
    sim_mem = 8.0 * N * 5
    if sim_mem <= REFERENCE_NODE_BYTES:
        e_cl = classical_energy_j(flops, ctx.profile)
        out.update(classical_ops=flops, classical_energy_j=e_cl, classical_energy=human_energy(e_cl),
                   classical_facility_energy_j=e_cl * ctx.pue)
        if out.get("energy_j"):
            out["energy_ratio_quantum_over_classical"] = out["energy_j"] / e_cl
    else:
        out["classical_note"] = ("explicit vectors need more than one reference node; the comparison depends on structure "
                                 "(tensor-network or matrix-free methods) that is not assessed here")
    out["caveat"] = ("No quantum advantage is claimed. Loading and read-out are charged explicitly; ordinary dense matrix "
                     "multiplication and AI workloads are not accelerated by this routine.")
    return out


def run_all(cfg, m, budget, code, cap, blocks, total_power, reaction_s, names, blocked=None):
    catalog_w = catalog.load("workloads")
    keys = names if names is not None else [k for k in catalog_w if not k.startswith("_")]
    ctx = _Ctx(cfg)
    results = {}
    for key in keys:
        w = catalog_w[key]
        if w["type"] == "fault_tolerant":
            results[key] = _fault_tolerant(w, m, budget, code, cap, total_power, reaction_s,
                                           int(cfg["n_qubits"]), blocked, ctx)
        elif w["type"] == "quantum_linear_algebra":
            results[key] = _quantum_linear_algebra(w, m, budget, code, cap, total_power, reaction_s,
                                                   int(cfg["n_qubits"]), blocked, ctx)
        else:
            results[key] = _variational(w, m, budget, blocks, total_power, int(cfg["n_qubits"]), ctx)
    return results
