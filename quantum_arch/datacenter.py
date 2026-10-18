"""Hybrid CPU + GPU + QPU data centre: scheduler model and scenario comparison.

A classical scheduler (running on CPUs) routes each job to a GPU partition or to a quantum pool.
For every job class it compares

    queue time + preparation / transfer + computation (+ retries) + measurement / post-processing

subject to accuracy (the quantum answer is accepted only with the success probability implied by the
logical-error budget of the quantum_arch plan and by the "mapping quality" of the algorithm) and to energy.
Three facility scenarios are compared on the SAME workload mix:

* ``gpu_only``  the baseline facility;
* ``augment``   keep every GPU and add quantum systems;
* ``replace``   remove a fraction of the GPUs and spend (part of) the freed facility power on quantum systems.

There is deliberately no "1 QPU = N GPUs" conversion. A quantum system helps only for the jobs that
have a validated quantum implementation (``eligible_fraction`` x ``mapping_quality``), at the job's own
runtime, energy and acceptance probability computed by :func:`quantum_arch.evaluate` (or the annealer
model), and the answer is the capacity and the energy per ACCEPTED answer of the whole facility.

Main entry points

* :func:`run_datacenter` / :func:`load_config` / :func:`datacenter_markdown`: whole-facility comparison;
* :func:`movable_sweep` and :func:`break_even`: capacity and energy against the movable-work fraction;
* :func:`quantum_job_check`: the per-job feasibility check delegated to ``quantum_arch.evaluate``;
* :func:`offload_decision`: ONE job, GPU or QPU, with times and energies; a clean function for other tools;
* :func:`replace_capacity_ratio` / :func:`break_even_moved_fraction`: the closed-form limit of the argument.

Modelling assumptions (all configurable, none validated against a real facility)

* each GPU job class runs on a proportional partition of the GPU pool (waits from Erlang-C with the
  class's own servers); the quantum pool is M/G/c (Allen-Cunneen); arrivals are Poisson;
* a quantum system runs one job at a time (``concurrency``);
* power: GPUs / CPUs linear between idle and TDP, times the server overhead ratio; a quantum system draws
  its busy power while running and a standby fraction otherwise (cryostat, vacuum and lasers stay on);
* facility power = IT power x (1 + network fraction) x PUE; energy per accepted answer attributes pool energy
  to classes by busy time.
"""

from __future__ import annotations

import copy
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import annealer as an
from . import baselines, catalog, classical
from .architecture import Architecture, canonical_profile, evaluate

EXAMPLES = Path(__file__).resolve().parent / "examples"
DC_EXAMPLES = EXAMPLES / "datacenter"

DEFAULT_CONFIG: dict[str, Any] = {
    "name": "datacenter",
    "profile": "mid2030s",
    "facility": {"pue": 1.15, "network_overhead_fraction": 0.08, "rho_max": 0.85},
    "gpu": {"device": "gpu_2035", "count": 1000, "baseline_utilisation": 0.7},
    "cpu": {"device": "cpu_2035", "count": 200, "utilisation": 0.5},
    "quantum_pools": {},
    "quantum_standby_others_fraction": 0.2,   # control electronics / decoders / host draw this fraction of busy power when idle
    "mix": [],
    "policy": "time_and_energy",               # time_and_energy | time | energy | always
    "scenarios": {},
}


# ----------------------------------------------------------------------------------------------
# queueing helpers
# ----------------------------------------------------------------------------------------------
def erlang_c(c: int, a: float) -> float:
    """Probability that an arrival has to wait in an M/M/c queue with offered load ``a`` (Erlang)."""
    if c < 1:
        return 1.0
    if a >= c:
        return 1.0
    b = 1.0
    for k in range(1, c + 1):
        b = a * b / (k + a * b)
    return b / (1.0 - (a / c) * (1.0 - b))


def mean_wait_s(c: int, a: float, mean_service_s: float, cs2: float = 1.0) -> float:
    """Mean queueing delay of an M/G/c queue (Allen-Cunneen); ``inf`` when unstable."""
    if a >= c:
        return math.inf
    if a <= 0:
        return 0.0
    return erlang_c(c, a) / (c - a) * mean_service_s * (1.0 + cs2) / 2.0


# ----------------------------------------------------------------------------------------------
# closed-form limit of the replace-versus-augment argument
# ----------------------------------------------------------------------------------------------
def replace_capacity_ratio(moved_fraction: float, removed_fraction: float) -> float:
    """Capacity for ordinary (non-movable) work after removing ``removed_fraction`` of the GPUs when a
    fraction ``moved_fraction`` of the GPU demand is moved to quantum systems (quantum capacity assumed
    sufficient): ``(1 - removed) / (1 - moved)``. Below 1 means ordinary AI capacity drops."""
    if moved_fraction >= 1.0:
        return math.inf if removed_fraction < 1.0 else 1.0
    return (1.0 - removed_fraction) / (1.0 - moved_fraction)


def break_even_moved_fraction(removed_fraction: float) -> float:
    """Movable-work fraction at which replacing ``removed_fraction`` of the GPUs breaks even on capacity
    (quantum capacity assumed sufficient): equal to the fraction of GPUs removed."""
    return removed_fraction


# ----------------------------------------------------------------------------------------------
# per-job quantum feasibility, delegated to quantum_arch.evaluate
# ----------------------------------------------------------------------------------------------
def load_architecture(spec: str | dict | Path | Architecture) -> Architecture:
    if isinstance(spec, Architecture):
        return spec
    if isinstance(spec, dict):
        return Architecture.from_dict(spec)
    path = Path(spec)
    for cand in (path, EXAMPLES / str(spec), EXAMPLES / f"{spec}.json"):
        if cand.is_file():
            return Architecture.from_file(cand)
    raise FileNotFoundError(f"architecture {spec!r} not found (path or quantum_arch/examples name)")


def quantum_job_check(arch: str | dict | Architecture, workload: str, overrides: dict | None = None) -> dict[str, Any]:
    """Can this quantum architecture run ``workload``, and at what time, energy and acceptance probability?

    This is the single place where the data-centre model asks ``quantum_arch.evaluate`` about a job: it
    checks the logical-error budget (via the workload plan), the runtime (factory- or reaction-limited) and
    the energy at system and facility boundaries.
    """
    a = load_architecture(arch)
    a = a.with_overrides(workloads=[workload], plates=False, **(overrides or {}))
    res = evaluate(a)
    w = res.workloads[workload]
    out = {"architecture": res.arch.name, "workload": workload, "feasible": bool(w.get("feasible")),
           "reason": w.get("reason", ""), "system_power_w": res.total_power_w,
           "facility_power_w": res.boundaries["facility"]["power_w"], "module_power_w": res.boundaries["module"]["electrical_w"],
           "pue": res.boundaries["facility"]["pue"], "warnings": list(res.warnings)}
    if out["feasible"]:
        out.update(runtime_s=w["runtime_s"], energy_system_j=w["energy_j"], energy_facility_j=w["facility_energy_j"],
                   total_logical_error=w.get("total_logical_error", 0.0), p_accept=w.get("p_accept", 1.0),
                   distance=w.get("distance"), physical_qubits_used=w.get("physical_qubits_used"),
                   io_overhead_share=w.get("io_overhead_share"))
    out["standby_w"] = _standby_power(res)
    return out


def _standby_power(res, others_fraction: float = 0.2) -> float:
    """Power while idle: the cryostat, vacuum, lasers and support stay on; control electronics idle down."""
    always = ("cryostat (installed)", "QPU apparatus (lasers, optics, traps, sources)", "support apparatus (vacuum, chillers, racks)")
    on = sum(v for k, v in res.power_w.items() if k in always)
    rest = sum(v for k, v in res.power_w.items() if k not in always)
    return on + others_fraction * rest


# ----------------------------------------------------------------------------------------------
# configuration
# ----------------------------------------------------------------------------------------------
def load_config(spec: str | dict | Path) -> dict[str, Any]:
    if isinstance(spec, dict):
        raw = spec
    else:
        path = Path(spec)
        for cand in (path, DC_EXAMPLES / str(spec), DC_EXAMPLES / f"{spec}.json"):
            if cand.is_file():
                raw = json.loads(cand.read_text(encoding="utf-8"))
                break
        else:
            raise FileNotFoundError(f"data-centre config {spec!r} not found (path or quantum_arch/examples/datacenter name)")
    cfg = catalog.deep_merge(DEFAULT_CONFIG, {k: v for k, v in raw.items() if k != "mix"})
    cfg["mix"] = copy.deepcopy(raw.get("mix", []))
    tot = sum(c["demand_share"] for c in cfg["mix"])
    if cfg["mix"] and abs(tot - 1.0) > 1e-6:
        raise ValueError(f"mix demand_share must sum to 1 (got {tot:.4f})")
    return cfg


# ----------------------------------------------------------------------------------------------
# pools
# ----------------------------------------------------------------------------------------------
class _QPool:
    """A kind of quantum system (gate-model architecture or annealer), evaluated once."""

    def __init__(self, name: str, spec: dict, cfg: dict, workloads: list[str]):
        self.name = name
        self.kind = spec["kind"]
        self.concurrency = int(spec.get("concurrency", 1))
        pue = cfg["facility"]["pue"]
        net = cfg["facility"]["network_overhead_fraction"]
        self.fac_factor = (1.0 + net) * pue
        if self.kind == "gate":
            arch = load_architecture(spec["architecture"]).with_overrides(workloads=sorted(set(workloads)) or None, plates=False)
            self.result = evaluate(arch)
            self.label = self.result.arch.name
            self.busy_w = self.result.total_power_w
            self.standby_w = _standby_power(self.result, cfg["quantum_standby_others_fraction"])
            self.module_w = self.result.boundaries["module"]["electrical_w"]
            self.checks: dict[str, dict] = {}
            for wk in set(workloads):
                self.checks[wk] = quantum_job_check(arch, wk)
            self.warnings = list(self.result.warnings)
        elif self.kind == "annealer":
            acfg = catalog.deep_merge({"profile": cfg["profile"], "name": name}, spec["annealer"])
            acfg.setdefault("facility", {})
            acfg["facility"] = catalog.deep_merge({"pue": pue, "network_support_w": 0.0}, acfg["facility"])
            self.result = an.evaluate_annealer(acfg)
            self.label = self.result.name
            self.busy_w = self.result.system_power_w
            of = cfg["quantum_standby_others_fraction"]
            self.standby_w = sum(v * (1.0 if ("cryostat" in k or "support" in k) else of) for k, v in self.result.power_w.items())
            self.module_w = 0.0
            self.checks = {}
            self.warnings = []
        else:
            raise ValueError(f"unknown quantum pool kind {self.kind!r}")

    def facility_busy_w(self) -> float:
        return self.busy_w * self.fac_factor


def _class_gpu_seconds(cls: dict, gpu: classical.Device, cfg: dict) -> tuple[float, float]:
    """(service time on the GPU partition in seconds, GPUs per job) of a class."""
    g = float(cls.get("gpus_per_job", 1))
    if cls.get("kind") == "llm_inference":
        tok_s = baselines.llm_tokens_per_s(gpu)
        t = cls.get("tokens_per_answer", 600) / tok_s / g
    else:
        t = float(cls["gpu_seconds"]) / g
    return t, g


def _attempts(p: float, k: int) -> tuple[float, float]:
    """(expected attempts, probability that all k attempts fail) for per-attempt acceptance ``p``."""
    if p <= 0:
        return float(k), 1.0
    fail = (1.0 - p) ** k
    return (1.0 - fail) / p, fail


# ----------------------------------------------------------------------------------------------
# one scenario
# ----------------------------------------------------------------------------------------------
def _simulate(cfg: dict, scenario: dict, pools: dict[str, _QPool], gpu: classical.Device,
              cpu: classical.Device, dscale: float = 1.0) -> dict[str, Any]:
    fac = cfg["facility"]
    pue, net, rho_max = fac["pue"], fac["network_overhead_fraction"], fac["rho_max"]
    fac_factor = (1.0 + net) * pue
    n0 = int(cfg["gpu"]["count"])
    removed = float(scenario.get("gpu_fraction_removed", 0.0))
    n_gpu = max(0.0, n0 * (1.0 - removed))
    rho0 = cfg["gpu"]["baseline_utilisation"]
    policy = scenario.get("policy", cfg["policy"])
    gpu_busy_fac_w = gpu.tdp_w * gpu.system_overhead_ratio * fac_factor

    # ---- quantum system counts ---------------------------------------------------------------
    freed_fac_w = (n0 - n_gpu) * gpu_busy_fac_w
    counts: dict[str, int] = {}
    for pname, spec in scenario.get("quantum_systems", {}).items():
        pool = pools[pname]
        if isinstance(spec, dict) and "power_share" in spec:
            counts[pname] = int(math.floor(spec["power_share"] * freed_fac_w / pool.facility_busy_w()))
        else:
            counts[pname] = int(spec)

    # ---- classes -----------------------------------------------------------------------------
    classes = []
    total_gpu_demand = sum(c["demand_share"] for c in cfg["mix"])
    for c in cfg["mix"]:
        t_gpu, g = _class_gpu_seconds(c, gpu, cfg)
        lam = dscale * c["demand_share"] / total_gpu_demand * rho0 * n0 / (g * t_gpu)  # jobs/s from the baseline load
        q = c.get("quantum")
        e = float(c.get("eligible_fraction", 0.0)) if q else 0.0
        info = {"name": c["name"], "cls": c, "t_gpu": t_gpu, "g": g, "lam": lam, "e": e, "q": q, "x": 0.0,
                "ordinary_ai": bool(c.get("ordinary_ai", False)), "pool": None, "feasible": False, "why": "",
                "fallback": 0.0, "post_gpu_s": 0.0, "attempts": 1.0, "occ_s": 0.0, "host_s": 0.0}
        if q and e > 0:
            pool = pools.get(q["pool"])
            info["pool"] = pool
            if pool is None or counts.get(q["pool"], 0) < 1:
                info["why"] = "no quantum system of this kind in the scenario"
            elif pool.kind == "gate":
                chk = pool.checks[q["workload"]]
                info["chk"] = chk
                if not chk["feasible"]:
                    info["why"] = f"quantum job infeasible: {chk['reason']}"
                else:
                    p = chk["p_accept"] * float(q.get("mapping_quality", 1.0))
                    att, fail = _attempts(p, int(q.get("max_attempts", 2)))
                    occ = chk["runtime_s"] + q.get("qpu_setup_s", 0.0)
                    host = q.get("prep_s", 0.0) + q.get("transfer_s", 0.0) + q.get("post_s", 0.0)
                    info.update(feasible=True, p_acc=p, attempts=att, fallback=fail, occ_s=occ * att, host_s=host * att,
                                e_marg_fac=(pool.busy_w * occ * att + cpu.tdp_w * cpu.system_overhead_ratio * host * att) * fac_factor,
                                post_gpu_s=q.get("post_gpu_seconds", 0.0))
            else:
                res = pool.result
                solve = an.solve_cost(res, q["p_success_per_read"], q.get("confidence", 0.99), q.get("max_reads", 100000),
                                           q.get("prep_s", 0.0), q.get("post_s", 0.0))
                p = solve["accept_probability"] * float(q.get("mapping_quality", 1.0))
                att, fail = _attempts(p, int(q.get("max_attempts", 2)))
                host = q.get("prep_s", 0.0) + q.get("post_s", 0.0) + q.get("transfer_s", 0.0)
                info.update(feasible=True, p_acc=p, attempts=att, fallback=fail, occ_s=solve["qpu_time_s"] * att,
                            host_s=host * att,
                            e_marg_fac=solve["energy_system_j"] * solve["accept_probability"] * att * fac_factor,
                            post_gpu_s=q.get("post_gpu_seconds", 0.0), chk={"runtime_s": solve["qpu_time_s"], "reason": "",
                                                                          "annealer": solve})
        info["e_gpu_marg_fac"] = g * t_gpu * gpu_busy_fac_w
        if info.get("feasible"):
            # classical cost (GPU-module hours per job) above which the quantum route is cheaper in facility energy
            info["breakeven_gpu_hours"] = info["e_marg_fac"] / (gpu.tdp_w * gpu.system_overhead_ratio * fac_factor) / 3600.0
        classes.append(info)

    def loads(x_by_class: dict[str, float]) -> dict[str, Any]:
        """Pool loads, waits and per-class turnaround for given routed fractions."""
        gpu_load = 0.0
        occ_pool: dict[str, float] = {p: 0.0 for p in counts}
        s2_pool: dict[str, float] = {p: 0.0 for p in counts}
        for k in classes:
            x = x_by_class.get(k["name"], 0.0)
            gpu_load += k["lam"] * ((1 - x) + (x * k["fallback"] if x else 0.0)) * k["g"] * k["t_gpu"]
            if x and k["feasible"]:
                gpu_load += k["lam"] * x * k["post_gpu_s"]
                pn = k["q"]["pool"]
                occ_pool[pn] += k["lam"] * x * k["occ_s"]
                s2_pool[pn] += k["lam"] * x * k["occ_s"] ** 2
        out = {"gpu_load": gpu_load, "occ": occ_pool}
        out["rho_gpu"] = gpu_load / n_gpu if n_gpu > 0 else math.inf
        rho_loc = out["rho_gpu"]
        waits_gpu, waits_q = {}, {}
        for k in classes:
            x = x_by_class.get(k["name"], 0.0)
            c_srv = max(1, int(round(n_gpu * min(1.0, k["lam"] * k["g"] * k["t_gpu"] / max(gpu_load, 1e-30)) / k["g"])))
            a = k["lam"] * ((1 - x) + x * k["fallback"]) * k["t_gpu"]
            waits_gpu[k["name"]] = mean_wait_s(c_srv, a, k["t_gpu"]) if n_gpu > 0 else math.inf
        for pn, occ in occ_pool.items():
            cap = counts[pn] * pools[pn].concurrency
            lam_q = sum(k["lam"] * x_by_class.get(k["name"], 0.0) for k in classes if k["feasible"] and k["q"]["pool"] == pn)
            mean_s = occ / lam_q if lam_q > 0 else 0.0
            cs2 = (s2_pool[pn] / lam_q) / mean_s ** 2 - 1.0 if lam_q > 0 and mean_s > 0 else 1.0
            waits_q[pn] = mean_wait_s(cap, occ, mean_s, max(cs2, 0.0)) if lam_q > 0 else 0.0
        out.update(waits_gpu=waits_gpu, waits_q=waits_q, rho_loc=rho_loc)
        return out

    # ---- routing -------------------------------------------------------------------------------
    cands = [k for k in classes if k["feasible"]]
    for k in cands:
        k["benefit"] = k["g"] * k["t_gpu"] / max(k["occ_s"], 1e-9)
    cands.sort(key=lambda k: -k["benefit"])
    x = {k["name"]: 0.0 for k in classes}
    notes: dict[str, str] = {k["name"]: k["why"] for k in classes if k["why"]}
    st = loads(x)
    for _ in range(16):
        cap_left = {p: rho_max * counts[p] * pools[p].concurrency for p in counts}
        new = {k["name"]: 0.0 for k in classes}
        for k in cands:
            pn = k["q"]["pool"]
            w_gpu = st["waits_gpu"][k["name"]]
            w_q = st["waits_q"][pn]
            w_gpu = 0.0 if not math.isfinite(w_gpu) else w_gpu
            t_q = (w_q if math.isfinite(w_q) else 1e12) + k["host_s"] + k["occ_s"] + k["fallback"] * (w_gpu + k["t_gpu"])
            t_g = w_gpu + k["t_gpu"]
            ok_time = t_q < t_g
            ok_energy = k["e_marg_fac"] < k["e_gpu_marg_fac"]
            go = {"always": True, "time": ok_time, "energy": ok_energy, "time_and_energy": ok_time and ok_energy}[policy]
            if not go:
                notes[k["name"]] = ("stays on GPU: quantum turnaround not shorter" if not ok_time else
                                    "stays on GPU: quantum energy per answer not lower") if policy != "always" else ""
                continue
            want = k["e"]
            demand_occ = k["lam"] * want * k["occ_s"]
            share = min(1.0, cap_left[pn] / demand_occ) if demand_occ > 0 else 0.0
            new[k["name"]] = want * share
            cap_left[pn] -= demand_occ * share
            if share < 1.0:
                notes[k["name"]] = "quantum pool capacity (utilisation cap) limits the routed fraction"
            else:
                notes.pop(k["name"], None)
        change = max(abs(new[n] - x[n]) for n in x) if x else 0.0
        x = {n: 0.5 * x[n] + 0.5 * new[n] for n in x}
        st = loads(x)
        if change < 1e-4:
            break

    # ---- final accounting ----------------------------------------------------------------------
    st = loads(x)
    rho_gpu = st["rho_gpu"]
    gpu_sys_w = n_gpu * gpu.system_power_w(min(rho_gpu, 1.0)) if n_gpu > 0 else 0.0
    cpu_sys_w = cfg["cpu"]["count"] * cpu.system_power_w(cfg["cpu"]["utilisation"])
    q_rows, q_power = {}, 0.0
    q_module = 0.0
    for pn, cnt in counts.items():
        pool = pools[pn]
        cap = cnt * pool.concurrency
        rho_q = st["occ"][pn] / cap if cap else 0.0
        p_sys = cnt * (pool.standby_w + (pool.busy_w - pool.standby_w) * min(rho_q, 1.0))
        q_power += p_sys
        q_module += cnt * pool.module_w
        q_rows[pn] = {"systems": cnt, "label": pool.label, "utilisation": rho_q, "wait_s": st["waits_q"][pn],
                      "system_power_w": p_sys, "busy_power_per_system_w": pool.busy_w, "standby_power_per_system_w": pool.standby_w,
                      "facility_power_w": p_sys * fac_factor}
    it_w = gpu_sys_w + cpu_sys_w + q_power
    fac_w = it_w * fac_factor
    module_w = n_gpu * gpu.power_w(min(rho_gpu, 1.0)) + cfg["cpu"]["count"] * cpu.power_w(cfg["cpu"]["utilisation"]) + q_module

    # energy per accepted answer: attribute pool energy to classes by busy time
    gpu_fac_w = gpu_sys_w * fac_factor
    rows = []
    gpu_busy_total = st["gpu_load"]
    total_work = 0.0
    ai_load = 0.0
    nonai_load = 0.0
    for k in classes:
        xi = x[k["name"]]
        lam = k["lam"]
        g_load = lam * ((1 - xi) + (xi * k["fallback"] if xi else 0.0)) * k["g"] * k["t_gpu"] + (lam * xi * k["post_gpu_s"] if xi and k["feasible"] else 0.0)
        e_gpu_part = gpu_fac_w * g_load / gpu_busy_total if gpu_busy_total else 0.0
        e_q_part = 0.0
        if xi and k["feasible"]:
            pn = k["q"]["pool"]
            e_q_part = q_rows[pn]["facility_power_w"] * (lam * xi * k["occ_s"]) / st["occ"][pn] if st["occ"][pn] else 0.0
        e_per_answer = (e_gpu_part + e_q_part) / lam if lam else math.nan
        w_gpu = st["waits_gpu"][k["name"]]
        t_gpu_turn = w_gpu + k["t_gpu"]
        t_q_turn = None
        if xi and k["feasible"]:
            w_q = st["waits_q"][k["q"]["pool"]]
            t_q_turn = w_q + k["host_s"] + k["occ_s"] + k["fallback"] * (w_gpu + k["t_gpu"])
        mean_turn = ((1 - xi) * t_gpu_turn + xi * t_q_turn) if t_q_turn is not None else t_gpu_turn
        rows.append({"class": k["name"], "demand_share": k["cls"]["demand_share"], "answers_per_s": lam,
                     "routed_to_quantum": xi, "eligible_fraction": k["e"], "ordinary_ai": k["ordinary_ai"],
                     "gpu_turnaround_s": t_gpu_turn, "quantum_turnaround_s": t_q_turn, "mean_turnaround_s": mean_turn,
                     "facility_j_per_accepted_answer": e_per_answer,
                     "gpu_only_marginal_j_per_answer": k["e_gpu_marg_fac"],
                     "quantum_marginal_j_per_answer": k.get("e_marg_fac"),
                     "p_accept_quantum": k.get("p_acc"), "expected_attempts": k.get("attempts"),
                     "classical_gpu_hours_per_job": k["g"] * k["t_gpu"] / 3600.0,
                     "breakeven_classical_gpu_hours": k.get("breakeven_gpu_hours"),
                     "note": notes.get(k["name"], "")})
        total_work += lam * k["g"] * k["t_gpu"]
        if k["ordinary_ai"]:
            ai_load += g_load
        else:
            nonai_load += g_load
    # capacity (maximum sustainable demand multiplier at utilisation cap), ordinary AI headroom
    cap_scale = min([rho_max * n_gpu / gpu_busy_total if gpu_busy_total else math.inf]
                    + [rho_max * counts[p] * pools[p].concurrency / st["occ"][p] if st["occ"][p] > 0 else math.inf for p in counts])
    ai_demand_gpu = sum(k["lam"] * k["g"] * k["t_gpu"] for k in classes if k["ordinary_ai"])
    headroom = rho_max * n_gpu - nonai_load
    ai_scale = headroom / ai_load if ai_load > 0 else math.inf
    out = {
        "scenario": scenario.get("label", ""), "gpus": n_gpu, "gpu_fraction_removed": removed,
        "gpu_utilisation": rho_gpu, "gpu_stable": rho_gpu < 1.0,
        "quantum_pools": q_rows,
        "power_w": {
            "module": module_w, "system": it_w, "facility": fac_w,
            "by_pool_system_w": {"gpu": gpu_sys_w, "cpu": cpu_sys_w, **{f"quantum:{p}": r["system_power_w"] for p, r in q_rows.items()}},
        },
        "capacity": {"max_demand_scale": cap_scale, "ordinary_ai_scale": ai_scale,
                     "ordinary_ai_headroom_gpus": headroom, "ordinary_ai_demand_gpus": ai_load},
        "classes": rows,
        "work_gpu_seconds_per_s": total_work,
        "facility_j_per_baseline_gpu_second": fac_w / total_work if total_work else math.nan,
        "added_facility_power_w_vs_gpu_only": None,
        "movable_share_of_demand": sum(k["lam"] * x[k["name"]] * k["g"] * k["t_gpu"] for k in classes) / total_work if total_work else 0.0,
    }
    return out


# ----------------------------------------------------------------------------------------------
# public driver
# ----------------------------------------------------------------------------------------------
_POOL_CACHE: dict[str, _QPool] = {}


def _build(cfg: dict) -> tuple[dict[str, _QPool], classical.Device, classical.Device]:
    profile = canonical_profile(cfg["profile"])
    gpu = classical.Device.from_catalog(cfg["gpu"]["device"], profile)
    cpu = classical.Device.from_catalog(cfg["cpu"]["device"], profile)
    need: dict[str, list[str]] = {}
    for c in cfg["mix"]:
        q = c.get("quantum")
        if q and q.get("workload"):
            need.setdefault(q["pool"], []).append(q["workload"])
    pools = {}
    for name, spec in cfg["quantum_pools"].items():
        key = json.dumps([name, spec, sorted(set(need.get(name, []))), profile, cfg["facility"],
                          cfg["quantum_standby_others_fraction"]], sort_keys=True, default=str)
        if key not in _POOL_CACHE:
            _POOL_CACHE[key] = _QPool(name, spec, cfg, need.get(name, []))
        pools[name] = _POOL_CACHE[key]
    return pools, gpu, cpu


def _capacity_scale(cfg, scenario, pools, gpu, cpu, r1) -> float:
    """Largest demand multiplier (same mix, routing re-optimised at every level) for which the GPU pool stays at or
    below the utilisation cap; quantum pools are capped by the router itself, the rest of the demand falls back to GPUs."""
    rho_max = cfg["facility"]["rho_max"]
    if not scenario.get("quantum_systems") or r1["movable_share_of_demand"] <= 0:
        return rho_max / r1["gpu_utilisation"] if r1["gpus"] > 0 and r1["gpu_utilisation"] > 0 else 0.0
    lo, hi = 0.0, 60.0
    for _ in range(28):
        mid = 0.5 * (lo + hi)
        if _simulate(cfg, scenario, pools, gpu, cpu, dscale=mid)["gpu_utilisation"] <= rho_max:
            lo = mid
        else:
            hi = mid
    return lo


def _run_scenario(cfg, scenario, pools, gpu, cpu) -> dict[str, Any]:
    """Evaluate a scenario; if it cannot carry the baseline demand at the utilisation cap, re-evaluate the demand it CAN
    serve (``served_fraction`` < 1) so that energy and turnaround are those of a stable facility."""
    r1 = _simulate(cfg, scenario, pools, gpu, cpu)
    cap = _capacity_scale(cfg, scenario, pools, gpu, cpu, r1)
    r1["capacity"]["max_demand_scale"] = cap
    if cap < 1.0 - 1e-9:
        r2 = _simulate(cfg, scenario, pools, gpu, cpu, dscale=cap)
        r2["capacity"] = r1["capacity"]
        r2["served_fraction"] = cap
        r2["unserved_note"] = (f"cannot carry the baseline demand at the {cfg['facility']['rho_max']:.0%} utilisation cap; "
                               f"figures below are for the {cap:.0%} of the demand it can serve")
        return r2
    r1["served_fraction"] = 1.0
    return r1


def run_datacenter(config: str | dict | Path, scenarios: list[str] | None = None) -> dict[str, Any]:
    """Evaluate every scenario of a data-centre configuration on the same workload mix."""
    cfg = load_config(config)
    pools, gpu, cpu = _build(cfg)
    names = scenarios or list(cfg["scenarios"])
    results = {}
    for n in names:
        s = dict(cfg["scenarios"][n])
        s.setdefault("label", n)
        results[n] = _run_scenario(cfg, s, pools, gpu, cpu)
    base = results.get("gpu_only")
    for n, r in results.items():
        r["added_facility_power_w_vs_gpu_only"] = r["power_w"]["facility"] - base["power_w"]["facility"] if base else None
        if base:
            r["comparison"] = _compare(r, base)
    return {"name": cfg["name"], "profile": canonical_profile(cfg["profile"]), "policy": cfg["policy"],
            "facility": cfg["facility"], "gpu_device": gpu.label, "cpu_device": cpu.label,
            "gpu_module_w": gpu.tdp_w, "gpu_system_overhead_ratio": gpu.system_overhead_ratio,
            "pools": {p: {"kind": q.kind, "label": q.label, "busy_power_w": q.busy_w, "standby_power_w": q.standby_w,
                          "facility_busy_power_w": q.facility_busy_w(), "warnings": q.warnings} for p, q in pools.items()},
            "scenarios": results, "config": cfg,
            "assumption_note": "Scenario analysis, not a forecast: job classes, classical costs, mapping quality and hardware profile are inputs. "
                               "No GPU-per-QPU conversion exists in this model."}


def _compare(r: dict, base: dict) -> dict[str, Any]:
    ai0, ai = base["capacity"]["ordinary_ai_scale"], max(0.0, r["capacity"]["ordinary_ai_scale"])
    c0, c1 = base["capacity"]["max_demand_scale"], r["capacity"]["max_demand_scale"]
    gain_gpus = r["capacity"]["ordinary_ai_headroom_gpus"] - base["capacity"]["ordinary_ai_headroom_gpus"]
    return {
        "ordinary_ai_capacity_ratio": (ai / ai0) if (ai0 > 0 and math.isfinite(ai0)) else math.nan,
        "ordinary_ai_capacity_change_gpus": gain_gpus,
        "max_total_demand_ratio": c1 / c0 if c0 else math.nan,
        "facility_power_ratio": r["power_w"]["facility"] / base["power_w"]["facility"],
        "energy_per_baseline_gpu_second_ratio": r["facility_j_per_baseline_gpu_second"] / base["facility_j_per_baseline_gpu_second"],
        "movable_share_actually_moved": r["movable_share_of_demand"],
    }


# ----------------------------------------------------------------------------------------------
# movable-work sweep and break-even
# ----------------------------------------------------------------------------------------------
def with_movable_share(cfg: dict, m: float) -> dict:
    """Copy of ``cfg`` whose quantum-eligible, mapped demand is exactly the fraction ``m`` of the total.

    Every capable class is split into an eligible part (demand_share x eligible_fraction, forced eligible_fraction = 1)
    and a rest; eligible parts are scaled to sum to ``m`` and the rest to ``1 - m``, keeping their proportions.
    """
    out = copy.deepcopy(cfg)
    elig, rest = [], []
    for c in cfg["mix"]:
        q = c.get("quantum")
        e = float(c.get("eligible_fraction", 0.0)) if q else 0.0
        if e > 0:
            a = copy.deepcopy(c)
            a["name"] = c["name"] + " (movable)"
            a["demand_share"] = c["demand_share"] * e
            a["eligible_fraction"] = 1.0
            elig.append(a)
        if e < 1.0:
            b = copy.deepcopy(c)
            b["demand_share"] = c["demand_share"] * (1 - e)
            b["eligible_fraction"] = 0.0
            b.pop("quantum", None)
            rest.append(b)
    m0 = sum(a["demand_share"] for a in elig)
    r0 = sum(b["demand_share"] for b in rest)
    if m0 <= 0:
        raise ValueError("the mix has no quantum-eligible class to sweep")
    for a in elig:
        a["demand_share"] *= m / m0
    for b in rest:
        b["demand_share"] *= (1 - m) / r0 if r0 else 0.0
    out["mix"] = [c for c in elig + rest if c["demand_share"] > 0]
    return out


def movable_sweep(config: str | dict | Path, shares: list[float] | None = None,
                  scenarios: tuple[str, ...] = ("augment", "replace")) -> dict[str, Any]:
    """Capacity, energy and turnaround against the movable-work fraction for the quantum scenarios."""
    cfg = load_config(config)
    shares = shares or [i / 20 for i in range(0, 21)]
    rows = []
    for m in shares:
        c2 = with_movable_share(cfg, min(max(m, 1e-6), 1 - 1e-6))
        pools, gpu, cpu = _build(c2)
        res = {n: _run_scenario(c2, dict(c2["scenarios"][n], label=n), pools, gpu, cpu) for n in ("gpu_only",) + tuple(scenarios)}
        base = res["gpu_only"]
        row = {"movable_share": m}
        for n in scenarios:
            cmp_ = _compare(res[n], base)
            row[n] = {"ordinary_ai_capacity_ratio": cmp_["ordinary_ai_capacity_ratio"],
                      "energy_ratio": cmp_["energy_per_baseline_gpu_second_ratio"],
                      "facility_power_ratio": cmp_["facility_power_ratio"],
                      "moved": cmp_["movable_share_actually_moved"],
                      "max_demand_ratio": cmp_["max_total_demand_ratio"]}
        rows.append(row)
    return {"rows": rows, "break_even": break_even_from_rows(rows, scenarios)}


def _cross(xs: list[float], ys: list[float], level: float) -> float | None:
    """Smallest x at which the (piecewise-linear) curve reaches ``level`` from below; None if never."""
    for i in range(len(xs)):
        y = ys[i]
        if y is None or (isinstance(y, float) and math.isnan(y)):
            continue
        if y >= level:
            if i == 0:
                return xs[0]
            y0 = ys[i - 1]
            if y0 is None or not math.isfinite(y0):
                return xs[i]
            return xs[i - 1] + (level - y0) / (y - y0) * (xs[i] - xs[i - 1])
    return None


def break_even_from_rows(rows: list[dict], scenarios: tuple[str, ...]) -> dict[str, Any]:
    xs = [r["movable_share"] for r in rows]
    out = {}
    for n in scenarios:
        cap = [min(r[n]["max_demand_ratio"], 1e6) for r in rows]
        eng = [-r[n]["energy_ratio"] for r in rows]       # energy ratio <= 1 is better: look for -ratio >= -1
        out[n] = {"movable_share_for_capacity_parity": _cross(xs, cap, 1.0),
                  "movable_share_for_energy_parity": _cross(xs, eng, -1.0)}
    return out


def break_even(config: str | dict | Path, scenarios: tuple[str, ...] = ("augment", "replace")) -> dict[str, Any]:
    """Smallest movable-work fraction at which each scenario matches the GPU-only facility on ordinary-AI
    capacity and on facility energy per baseline GPU-second of accepted work."""
    return movable_sweep(config, scenarios=scenarios)["break_even"]


# ----------------------------------------------------------------------------------------------
# a single job
# ----------------------------------------------------------------------------------------------
def offload_decision(job: dict[str, Any], quantum_architecture: str | dict | Architecture, gpu_device: str = "gpu_2035",
                     profile: str = "mid2030s", pue: float = 1.15, network_overhead_fraction: float = 0.08,
                     queue_wait_gpu_s: float = 0.0, queue_wait_quantum_s: float = 0.0,
                     policy: str = "time_and_energy") -> dict[str, Any]:
    """Should ONE job go to the GPUs or to a quantum system? A documented hook for other tools.

    ``job`` keys: ``workload`` (a ``workloads.json`` key the quantum architecture must run), ``gpu_seconds`` (module-seconds
    the best classical method needs at the SAME accuracy), ``gpus_per_job`` (default 1), ``mapping_quality`` in [0, 1] (chance that the
    quantum formulation yields an acceptable answer, default 1), ``max_attempts`` (2), ``prep_s``, ``transfer_s``, ``post_s`` (host
    seconds, default 0), ``qpu_setup_s`` (QPU-occupied seconds besides the run). Returns the route and the numbers behind it:
    turnaround (queue + prep/transfer + compute + post) and facility-boundary energy per accepted answer for both options,
    the feasibility check from ``quantum_arch.evaluate`` and the reasons. Energies are job-marginal (devices at full load),
    include PUE and network overhead and exclude standby power; waits are inputs.
    """
    profile = canonical_profile(profile)
    gpu = classical.Device.from_catalog(gpu_device, profile)
    fac = (1.0 + network_overhead_fraction) * pue
    g = float(job.get("gpus_per_job", 1))
    t_gpu = float(job["gpu_seconds"]) / g
    chk = quantum_job_check(quantum_architecture, job["workload"])
    cpu_w = classical.Device.from_catalog("auto:cpu", profile)
    gpu_opt = {"turnaround_s": queue_wait_gpu_s + t_gpu,
               "energy_facility_j": g * t_gpu * gpu.tdp_w * gpu.system_overhead_ratio * fac}
    reasons = []
    if not chk["feasible"]:
        reasons.append(f"quantum job infeasible: {chk['reason']}")
        return {"route": "gpu", "feasible_on_quantum": False, "reasons": reasons, "gpu": gpu_opt, "quantum": None, "check": chk}
    p = chk["p_accept"] * float(job.get("mapping_quality", 1.0))
    att, fail = _attempts(p, int(job.get("max_attempts", 2)))
    host = job.get("prep_s", 0.0) + job.get("transfer_s", 0.0) + job.get("post_s", 0.0)
    occ = chk["runtime_s"] + job.get("qpu_setup_s", 0.0)
    t_q = queue_wait_quantum_s + (host + occ) * att + fail * (queue_wait_gpu_s + t_gpu)
    e_q = ((chk["system_power_w"] * occ + cpu_w.tdp_w * cpu_w.system_overhead_ratio * host) * att) * fac + fail * gpu_opt["energy_facility_j"]
    q_opt = {"turnaround_s": t_q, "energy_facility_j": e_q, "accept_probability_per_attempt": p, "expected_attempts": att,
             "fallback_probability": fail, "quantum_runtime_s": chk["runtime_s"], "total_logical_error": chk.get("total_logical_error")}
    ok_t, ok_e = t_q < gpu_opt["turnaround_s"], e_q < gpu_opt["energy_facility_j"]
    go = {"always": True, "time": ok_t, "energy": ok_e, "time_and_energy": ok_t and ok_e}[policy]
    if not ok_t:
        reasons.append("quantum turnaround is not shorter")
    if not ok_e:
        reasons.append("quantum energy per accepted answer is not lower")
    return {"route": "quantum" if go else "gpu", "feasible_on_quantum": True, "reasons": reasons, "gpu": gpu_opt,
            "quantum": q_opt, "check": chk,
            "note": "same accepted answer on both sides; classical cost (gpu_seconds) is the caller's claim for the best classical method"}


# ----------------------------------------------------------------------------------------------
# text report
# ----------------------------------------------------------------------------------------------
def _fw(x: float) -> str:
    for scale, unit in ((1e6, "MW"), (1e3, "kW"), (1.0, "W")):
        if abs(x) >= scale:
            return f"{x / scale:.3g} {unit}"
    return f"{x:.3g} W"


def _ft(s: float | None) -> str:
    if s is None:
        return "—"
    if not math.isfinite(s):
        return "unstable"
    for limit, div, unit in ((1.0, 1e-3, "ms"), (120.0, 1.0, "s"), (7200.0, 60.0, "min"), (172800.0, 3600.0, "h")):
        if s < limit:
            return f"{s / div:.3g} {unit}"
    return f"{s / 86400.0:.3g} d"


def _fj(j: float | None) -> str:
    if j is None or (isinstance(j, float) and not math.isfinite(j)):
        return "—"
    kwh = j / 3.6e6
    if kwh >= 1e3:
        return f"{kwh / 1e3:.3g} MWh"
    if kwh >= 0.1:
        return f"{kwh:.3g} kWh"
    return f"{j:.3g} J"


def datacenter_markdown(res: dict[str, Any], sweep: dict | None = None) -> str:
    from .report import _table
    L = [f"# {res['name']}: hybrid CPU + GPU + QPU data centre", "",
         f"Hardware profile `{res['profile']}` (a SCENARIO, not a forecast). GPUs: {res['gpu_device']} "
         f"({_fw(res['gpu_module_w'])} per module, server overhead x{res['gpu_system_overhead_ratio']:g}); PUE "
         f"{res['facility']['pue']}, network overhead {res['facility']['network_overhead_fraction']:.0%}. "
         f"Routing policy: `{res['policy']}`.", "",
         "There is no GPU-per-QPU conversion in this model. Quantum systems only take jobs that have a validated quantum "
         "implementation, at their own runtime, energy and acceptance probability. Power boundaries: module = accelerator "
         "modules / QPU module; system = complete servers and quantum computers; facility = system x network x PUE.", ""]
    if res["pools"]:
        L += ["## Quantum system types", "",
              _table(["pool", "kind", "system", "busy power (system)", "standby", "busy power (facility)"],
                     [[p, q["kind"], q["label"], _fw(q["busy_power_w"]), _fw(q["standby_power_w"]), _fw(q["facility_busy_power_w"])]
                      for p, q in res["pools"].items()]), ""]
    sc = res["scenarios"]
    L += ["## Scenarios on the same workload mix", ""]
    head = ["quantity"] + list(sc)
    rows = [
        ["GPU modules", *[f"{r['gpus']:.0f}" for r in sc.values()]],
        ["quantum systems", *[", ".join(f"{p}: {v['systems']}" for p, v in r["quantum_pools"].items()) or "none" for r in sc.values()]],
        ["GPU utilisation (at the served demand)", *[f"{r['gpu_utilisation']:.0%}" for r in sc.values()]],
        ["power, module boundary", *[_fw(r["power_w"]["module"]) for r in sc.values()]],
        ["power, system boundary (IT)", *[_fw(r["power_w"]["system"]) for r in sc.values()]],
        ["power, facility boundary", *[_fw(r["power_w"]["facility"]) for r in sc.values()]],
        ["share of GPU demand moved to quantum", *[f"{r['movable_share_of_demand']:.1%}" for r in sc.values()]],
        ["capacity: max sustainable demand vs GPU-only (same mix, scaled)", *[(f"{r['comparison']['max_total_demand_ratio']:.2f}x" if 'comparison' in r else "1.00x") for r in sc.values()]],
        ["ordinary-AI headroom if other classes keep their demand (GPU modules)", *[f"{r['capacity']['ordinary_ai_headroom_gpus']:.0f}" for r in sc.values()]],
        ["... as a ratio to GPU-only", *[(f"{r['comparison']['ordinary_ai_capacity_ratio']:.2f}x" if 'comparison' in r else "1.00x") for r in sc.values()]],
        ["share of the baseline demand actually served", *[f"{r['served_fraction']:.0%}" for r in sc.values()]],
        ["facility J per baseline GPU-second of accepted work", *[f"{r['facility_j_per_baseline_gpu_second']:.4g}" for r in sc.values()]],
        ["... relative to GPU-only", *[(f"{r['comparison']['energy_per_baseline_gpu_second_ratio']:.3f}" if 'comparison' in r else "1.000") for r in sc.values()]],
    ]
    L += [_table(head, rows), ""]
    for n, r in sc.items():
        L += [f"### {n}: job classes", "",
              _table(["class", "demand share", "moved to quantum", "GPU turnaround", "quantum turnaround", "mean turnaround",
                      "facility energy per accepted answer", "classical cost / break-even (GPU-module h per job)", "note"],
                     [[c["class"], f"{c['demand_share']:.0%}", f"{c['routed_to_quantum']:.1%}" if c["eligible_fraction"] else "—",
                       _ft(c["gpu_turnaround_s"]), _ft(c["quantum_turnaround_s"]), _ft(c["mean_turnaround_s"]),
                       _fj(c["facility_j_per_accepted_answer"]),
                       (f"{c['classical_gpu_hours_per_job']:.3g} / {c['breakeven_classical_gpu_hours']:.3g}"
                        if c["breakeven_classical_gpu_hours"] else "—"), c["note"]] for c in r["classes"]])]
        if r.get("unserved_note"):
            L += ["", f"> {r['unserved_note']}", ""]
        if r["quantum_pools"]:
            L += ["", _table(["quantum pool", "systems", "utilisation", "queue wait", "system power", "facility power"],
                             [[p, v["systems"], f"{v['utilisation']:.0%}", _ft(v["wait_s"]), _fw(v["system_power_w"]),
                               _fw(v["facility_power_w"])] for p, v in r["quantum_pools"].items()])]
        L += [""]
    if sweep:
        be = sweep["break_even"]
        L += ["## Break-even movable-work fraction", "",
              "Smallest share of the GPU demand that must be movable (eligible AND mapped) for a scenario to match the GPU-only "
              "facility. The closed-form limit for REPLACE is: break-even = fraction of GPUs removed, when quantum capacity suffices.", "",
              _table(["scenario", "movable share for capacity parity", "movable share for energy parity"],
                     [[n, "never (in range)" if v["movable_share_for_capacity_parity"] is None else f"{v['movable_share_for_capacity_parity']:.1%}",
                       "never (in range)" if v["movable_share_for_energy_parity"] is None else f"{v['movable_share_for_energy_parity']:.1%}"]
                      for n, v in be.items()]), "",
              _table(["movable share"] + [f"{n}: capacity / energy (vs GPU-only)" for n in be],
                     [[f"{r['movable_share']:.0%}"] + [f"{r[n]['max_demand_ratio']:.2f}x / {r[n]['energy_ratio']:.3f}" for n in be]
                      for r in sweep["rows"][::2]]), "",
              "Capacity = largest demand (same mix, scaled) the facility sustains at the utilisation cap, relative to GPU-only. Energy = facility "
              "joules per baseline GPU-second of accepted work, relative to GPU-only (below 1 is better).", ""]
    L += [f"> {res['assumption_note']}"]
    return "\n".join(L) + "\n"


def write_datacenter_report(res: dict, sweep: dict | None, outdir: str | Path) -> Path:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(_clean({"result": res, "sweep": sweep}), indent=2, default=str), encoding="utf-8")
    (out / "summary.md").write_text(datacenter_markdown(res, sweep), encoding="utf-8")
    if sweep:
        _fig_sweep(sweep, res["name"], out / "movable_sweep.png")
    return out


def _clean(o):
    """Replace nan / inf by None so the output is valid JSON."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def _fig_sweep(sweep: dict, name: str, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .report import CATEGORICAL, GRID, INK, INK2, SURFACE, _fig, _style
    xs = [r["movable_share"] for r in sweep["rows"]]
    fig = _fig(11, 4.0)
    ax = fig.add_axes([0.07, 0.18, 0.38, 0.65])
    ax2 = fig.add_axes([0.57, 0.18, 0.38, 0.65])
    for n, col in zip(sweep["break_even"], CATEGORICAL):
        ax.plot(xs, [min(r[n]["max_demand_ratio"], 5) for r in sweep["rows"]], color=col, linewidth=2, label=n)
        ax2.plot(xs, [min(r[n]["energy_ratio"], 3) for r in sweep["rows"]], color=col, linewidth=2, label=n)
    for a, ttl, yl in ((ax, "Sustainable demand against GPU-only", "capacity ratio (1 = parity)"),
                       (ax2, "Facility energy per unit of accepted work", "energy ratio (1 = parity; lower is better)")):
        a.axhline(1.0, color=INK, linewidth=1.0)
        a.set_xlabel("share of GPU demand that is movable to quantum (eligible and mapped)", color=INK2, fontsize=9)
        a.set_ylabel(yl, color=INK2, fontsize=9)
        a.set_title(ttl, loc="left", color=INK, fontsize=10.5)
        _style(a)
        a.grid(axis="y", color=GRID, linewidth=0.6)
        a.legend(frameon=False, fontsize=8.5, labelcolor=INK2)
    fig.suptitle(f"{name}: what must be movable for quantum to pay off", x=0.01, ha="left", color=INK, fontsize=12)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
