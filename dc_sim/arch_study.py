"""Use case B node-composition study: GPU-only reference vs specialised pools vs integrated nodes vs a mix.

Question (level 3 and 4 of the project north star): for the agent-developer case, is it better to build specialised
GPU, CPU and QPU nodes, or nodes that carry all three and split sub-tasks internally, or a mixture?

Model (a SIZING study, not a task-by-task event simulation; the numerical engine in ``engine.py`` is not used here):

* Demand per user and day: 12 interactive and 30 background agent tasks of 80 steps each (slides). Every step costs
  accelerator time (prefill of the new tokens, decode of the written tokens). Interactive tools run on the user's laptop;
  background tools run in a data-centre sandbox (CPU cores).
* GPUs are sized on a diurnal time grid: interactive load first, background load served from the remaining capacity with a
  bounded wait. CPU sandboxes are sized from the tool load.
* A **quantum-eligible call** is a tool call inside a background task that a QPU can answer. Its density per background
  task and the cost of the best classical alternative (GPU module-hours) are INPUTS (nobody knows them for agent
  workloads); the study sweeps them. QPU runtime, power and acceptance come from ``quantum_arch`` via ``qfeas``.
* QPU calls are simulated one by one (queues, calibration windows, lognormal durations). The topology decides who may use
  which QPU: ``specialised`` = one shared hall, ``integrated`` = every node owns one QPU and its tasks may use only that
  one, ``mix`` = node-local QPUs first, shared hall as spill-over. A call that would wait longer than ``max_wait_s`` runs
  classically on the GPUs instead (the scheduler's overflow rule). A pooled QPU pays an extra network round trip per
  optimiser iteration; a node-local one does not.
* Reported at the facility boundary: peak and mean power, energy per task, cost per task (amortised capex incl. facility
  plus energy), always next to the GPU-only reference.

No quantum speed-up is assumed anywhere: a call only moves to a QPU in the cost-optimal configuration if that is cheaper.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import Any

import numpy as np

from . import qfeas
from .config import DATA, assumptions, deep_merge, stable_seed
from .demand import diurnal_factor

DAY = 86400.0


def load_params(over: dict | None = None) -> dict[str, Any]:
    base = json.loads((DATA / "arch_study.json").read_text(encoding="utf-8"))
    return deep_merge(base, over)


# ---------------------------------------------------------------- derived constants
def _hw(p: dict) -> dict[str, Any]:
    a = assumptions()
    g = qfeas.gpu_module()
    eng = a["engine"]
    nt = a["node_types"]
    cool = a["cooling"][p["economics"]["cooling"]]
    q = nt[p["quantum"]["node_type"]]
    prof = qfeas.qpu_profile(q["architecture"])
    chk = qfeas.gate_check(q["architecture"], p["quantum"]["workload"])
    cb = p["case_b"]
    mc = float(eng["model_cost_x"])
    s_step = cb["prefill_new_tokens_per_step"] / (g["prefill_tok_s_70b"] / mc) + cb["decode_tokens_per_step"] / (g["decode_tok_s_70b"] / mc)
    from quantum_arch import classical as _cl
    cpu = _cl.Device.from_catalog(p["cpu"]["device"], qfeas.PROFILE)
    pue = cool["pue_base"]  # the pod is modelled at its design-day PUE (no ambient swing)
    return {
        "gpu": g, "gpu_capex": float(nt["gpu_rack"]["capex_per_module_usd"]),
        "gpu_sys_idle_w": g["idle_w"] * g["overhead"], "gpu_sys_tdp_w": g["tdp_w"] * g["overhead"],
        "module_s_per_step": s_step, "model_cost_x": mc,
        "cpu_tdp_w": cpu.tdp_w, "pue": pue, "net": p["economics"]["network_overhead"],
        "fac_capex_per_kw": float(cool["capex_usd_per_kw_it"]),
        "qpu_busy_w": prof["busy_w"], "qpu_standby_w": prof["standby_w"], "qpu_capex": float(q["capex_usd"]) * float(p["quantum"].get("capex_scale", 1.0)),
        "qpu_cal_interval": float(q["calibration"]["interval_s"]), "qpu_cal_dur": float(q["calibration"]["duration_s"]),
        "qpu_runtime_s": float(chk["runtime_s"]), "qpu_p_accept": float(chk["p_accept"]), "qpu_energy_j": float(chk["energy_system_j"]),
        "qpu_feasible": bool(chk["feasible"]), "qpu_label": prof["label"],
    }


def _curve(p: dict, dt: float) -> np.ndarray:
    """Interactive diurnal factor (mean 1) of the pod's user mix, one value per tick for 3 days."""
    a = assumptions()
    cfg = a["demand"]
    shape = cfg["diurnal"][cfg["B"]["diurnal"]]
    off = {k: v["utc_offset"] for k, v in a["regions"].items() if not k.startswith("_")}
    n = int(DAY / dt)
    day = np.zeros(n)
    for r, share in cfg["B"]["region_share"].items():
        for k in range(n):
            day[k] += share * diurnal_factor(shape, ((k + 0.5) * dt / 3600.0 + off[r]) % 24.0)
    day /= day.mean()
    return np.tile(day, 3)


def _demand(p: dict, hw: dict, N: float) -> dict[str, Any]:
    cb = p["case_b"]
    steps = cb["steps_per_task"]
    int_steps_s = N * cb["interactive_tasks_per_user_day"] * steps / DAY
    bg_steps_s = N * cb["background_tasks_per_user_day"] * steps / DAY
    bg_tasks_day = N * cb["background_tasks_per_user_day"]
    return {"int_mod": int_steps_s * hw["module_s_per_step"], "bg_mod": bg_steps_s * hw["module_s_per_step"], "bg_steps_s": bg_steps_s,
            "bg_tasks_day": bg_tasks_day, "tasks_day": N * (cb["interactive_tasks_per_user_day"] + cb["background_tasks_per_user_day"]),
            "tool_cores": bg_steps_s * cb["bg_tool_s_per_step"] * cb["bg_tool_cores"]}


# ---------------------------------------------------------------- GPU sizing on the diurnal grid
def size_gpus(p: dict, hw: dict, dem: dict, extra_mod: float = 0.0) -> dict[str, Any]:
    """Smallest GPU module count such that interactive load fits (rho) and background work waits at most bg_wait_slo_s."""
    cb = p["case_b"]
    dt, rho, wmax = float(cb["tick_s"]), float(cb["rho"]), float(cb["bg_wait_slo_s"])
    f = _curve(p, dt)
    I = dem["int_mod"] * f
    bg = dem["bg_mod"] + extra_mod
    n = len(I)
    day0 = n - int(DAY / dt)
    A = np.cumsum(np.full(n, bg * dt))

    def run(G: int):
        cap = G * rho
        if cap < I.max() or cap < I.mean() + bg:          # peak fits, and the average load is sustainable (no endless backlog)
            return None
        left = cap - I
        S = np.empty(n)
        prev = 0.0
        for k in range(n):
            prev = min(A[k], prev + left[k] * dt)
            S[k] = prev
        j = np.searchsorted(S, A[day0:] - 1e-6, side="left")
        wait = (j - np.arange(day0, n)) * dt
        if wait.max() > wmax:
            return None
        served_bg = np.diff(np.concatenate(([S[day0 - 1]], S[day0:]))) / dt
        util = (I[day0:] + served_bg) / G
        return util

    lo = max(1, int(math.ceil((I.max()) / rho)))
    hi = max(lo * 2, int(math.ceil((I.max() + bg) / rho * 1.5)) + 2)
    while run(hi) is None:
        hi *= 2
    while lo < hi:
        mid = (lo + hi) // 2
        if run(mid) is None:
            lo = mid + 1
        else:
            hi = mid
    util = run(lo)
    sysw = lo * (hw["gpu_sys_idle_w"] + util * (hw["gpu_sys_tdp_w"] - hw["gpu_sys_idle_w"]))
    return {"modules": lo, "mean_kw": float(sysw.mean() / 1e3), "peak_kw": float(sysw.max() / 1e3), "util_mean": float(util.mean()),
            "util_peak": float(util.max())}


# ---------------------------------------------------------------- QPU call simulation
def _first_start(t: float, dur: float, off: float, interval: float, cal: float) -> float:
    r = (t - off) % interval
    if r < cal:
        t += cal - r
        r = cal
    if r + dur > interval:
        t += (interval - r) + cal
    return t


def simulate_calls(hw: dict, p: dict, n_calls: int, topo: str, n_local: int, c_pool: int, seed: int) -> dict[str, Any]:
    """Queue simulation of ``n_calls`` quantum-eligible calls over one day. topo: specialised | integrated | mix."""
    q = p["quantum"]
    rng = np.random.default_rng(seed)
    if n_calls <= 0 or (n_local + c_pool) == 0:
        return {"calls": n_calls, "qpu": 0, "overflow": n_calls, "busy_s": 0.0, "wait": np.zeros(0), "busy_by_qpu": []}
    arr = np.sort(rng.uniform(0.0, DAY, n_calls))
    cv = float(q["duration_cv"])
    sig = math.sqrt(math.log(1 + cv * cv))
    base = hw["qpu_runtime_s"] / hw["qpu_p_accept"]
    pen = q["iterations_per_call"] * (q["pool_rtt_s"] - q["local_rtt_s"])
    dur_loc = base * rng.lognormal(-0.5 * sig * sig, sig, n_calls)
    I, C = hw["qpu_cal_interval"], hw["qpu_cal_dur"]
    nloc, cp = (n_local, c_pool)
    n_tot = nloc + cp
    off = (np.arange(n_tot) / max(1, n_tot)) * I
    free = np.zeros(n_tot)
    busy = np.zeros(n_tot)
    node = rng.integers(0, max(1, nloc), n_calls) if nloc else np.zeros(n_calls, dtype=int)
    wmax, lok = float(q["max_wait_s"]), float(q["local_ok_wait_s"])
    waits, over = [], 0
    for i in range(n_calls):
        t, d = arr[i], dur_loc[i]
        choice, start, dd = -1, 0.0, d
        if topo in ("integrated", "mix") and nloc:
            j = int(node[i])
            s = _first_start(max(t, free[j]), d, off[j], I, C)
            if topo == "integrated" or s - t <= lok:
                if s - t <= wmax:
                    choice, start, dd = j, s, d
        if choice < 0 and topo in ("specialised", "mix") and cp:
            dp = d + pen
            st = np.maximum(free[nloc:], t)
            j = nloc + int(st.argmin())
            s = _first_start(max(t, free[j]), dp, off[j], I, C)
            if s - t <= wmax:
                choice, start, dd = j, s, dp
        if choice < 0:
            over += 1
            continue
        free[choice] = start + dd
        busy[choice] += dd
        waits.append(start - t)
    w = np.array(waits)
    return {"calls": n_calls, "qpu": len(waits), "overflow": over, "busy_s": float(busy.sum()), "wait": w, "busy_by_qpu": busy.tolist()}


# ---------------------------------------------------------------- evaluation of one configuration
_SIM_CACHE: dict[tuple, dict] = {}


def _sim(p: dict, hw: dict, key: tuple, n_calls: int, topo: str, n_local: int, c_pool: int) -> dict:
    k = (key, p["pod"].get("seed", 0), n_calls, topo, n_local, c_pool, p["quantum"]["workload"], p["quantum"]["node_type"], p["quantum"]["iterations_per_call"],
         p["quantum"]["pool_rtt_s"], p["quantum"]["local_rtt_s"], p["quantum"]["max_wait_s"], p["quantum"]["duration_cv"])
    if k not in _SIM_CACHE:
        # common random numbers: every sizing and topology sees the same call arrivals, durations and node bindings
        _SIM_CACHE[k] = simulate_calls(hw, p, n_calls, topo, n_local, c_pool, stable_seed("arch", key, n_calls, p["pod"].get("seed", 0)))
    return _SIM_CACHE[k]


def evaluate(p: dict, hw: dict, N: float, lam: float, X: float, topo: str, n_local: int = 0, c_pool: int = 0, tag: str = "") -> dict[str, Any]:
    """One configuration: ``topo`` gpu_only | specialised | integrated | mix."""
    cb, cpu, eco = p["case_b"], p["cpu"], p["economics"]
    dem = _demand(p, hw, N)
    n_calls = int(round(lam * dem["bg_tasks_day"]))
    if topo == "gpu_only":
        n_local = c_pool = 0
    sim = _sim(p, hw, (round(N), tag), n_calls, "specialised" if topo == "gpu_only" else topo, n_local, c_pool)
    n_q = n_local + c_pool
    extra_mod = sim["overflow"] * X * 3600.0 / DAY               # classical fallback load (module-equivalents, flat)
    gpu = size_gpus(p, hw, dem, extra_mod)
    # CPU sandboxes: tool load + host work of the calls that run on a QPU
    cores = dem["tool_cores"] + sim["qpu"] * p["quantum"]["host_core_s_per_call"] / DAY
    cps = cpu["cores_per_socket"]
    dyn_w_core = (1 - cpu["idle_fraction"]) * hw["cpu_tdp_w"] * cpu["system_overhead"] / cps
    idle_w_sock = cpu["idle_fraction"] * hw["cpu_tdp_w"] * cpu["system_overhead"]
    if topo == "specialised" or topo == "gpu_only_dedicated":
        host_sockets, spare = 0, 0.0
        dedicated = math.ceil(cores / cps / cpu["util"])
    else:
        # sandboxes share the GPU servers' host CPUs (integrated nodes, mixed nodes and the GPU-only reference alike)
        spare = gpu["modules"] * cpu["host_sockets_per_gpu_module"] * cps * cpu["host_cpu_spare_fraction"]
        dedicated = max(0, math.ceil((cores - spare * cpu["util"]) / cps / cpu["util"])) if cores > spare * cpu["util"] else 0
    cpu_mean_kw = (dedicated * idle_w_sock + cores * dyn_w_core) / 1e3
    cpu_peak_kw = cpu_mean_kw                                    # sandbox load is flat in this model
    # QPU power: standby always, busy share on top; peak = all busy (conservative)
    busy_frac = sim["busy_s"] / (DAY * n_q) if n_q else 0.0
    qpu_mean_kw = n_q * (hw["qpu_standby_w"] + busy_frac * (hw["qpu_busy_w"] - hw["qpu_standby_w"])) / 1e3
    qpu_peak_kw = n_q * hw["qpu_busy_w"] / 1e3
    mult = (1 + hw["net"]) * hw["pue"]
    mean_fac_mw = (gpu["mean_kw"] + cpu_mean_kw + qpu_mean_kw) * mult / 1e3
    peak_fac_mw = (gpu["peak_kw"] + cpu_peak_kw + qpu_peak_kw) * mult / 1e3
    capex_hw = gpu["modules"] * hw["gpu_capex"] + dedicated * cpu["capex_usd_per_socket"] + n_q * hw["qpu_capex"]
    capex_fac = peak_fac_mw * 1e3 * hw["fac_capex_per_kw"]
    cap_day = (capex_hw + capex_fac) / (eco["amortisation_years"] * 365.0)
    en_day = mean_fac_mw * 24.0 * eco["energy_usd_per_mwh"]
    tasks = dem["tasks_day"]
    w = sim["wait"]
    return {"topo": topo, "n_local": n_local, "c_pool": c_pool, "qpus": n_q, "gpu_modules": gpu["modules"], "dedicated_cpu_sockets": dedicated,
            "calls_day": n_calls, "calls_on_qpu": sim["qpu"], "calls_classical": sim["overflow"],
            "qpu_share": (sim["qpu"] / n_calls) if n_calls else 0.0, "qpu_util": busy_frac,
            "wait_p50_s": float(np.percentile(w, 50)) if len(w) else 0.0, "wait_p95_s": float(np.percentile(w, 95)) if len(w) else 0.0,
            "gpu_util_mean": gpu["util_mean"], "gpu_mean_mw": gpu["mean_kw"] / 1e3, "cpu_mean_mw": cpu_mean_kw / 1e3, "qpu_mean_mw": qpu_mean_kw / 1e3,
            "mean_facility_mw": mean_fac_mw, "peak_facility_mw": peak_fac_mw, "capex_hw_usd": capex_hw, "capex_facility_usd": capex_fac,
            "usd_day": cap_day + en_day, "usd_day_capex": cap_day, "usd_day_energy": en_day,
            "usd_per_task": (cap_day + en_day) / tasks, "j_per_task_facility": mean_fac_mw * 1e6 * DAY / tasks,
            "tasks_day": tasks, "classical_extra_modules": extra_mod}


# ---------------------------------------------------------------- search over configurations
def _pool_candidates(p: dict, hw: dict, N: float, lam: float) -> list[int]:
    dem = _demand(p, hw, N)
    need = lam * dem["bg_tasks_day"] * hw["qpu_runtime_s"] / hw["qpu_p_accept"] / DAY
    out = {0}
    for f in (0.3, 0.5, 0.75, 1.0, 1.3, 1.7, 2.2, 3.0):
        c = int(math.ceil(need * f))
        if c >= 1:
            out.add(c)
    return sorted(out)


def _hill(fn, coarse: list[int], lo: int = 1) -> dict:
    """Cheapest integer size: coarse scan, then +-step refinement around the best (results cached per size)."""
    seen: dict[int, dict] = {}

    def f(c: int) -> dict:
        c = max(lo, int(c))
        if c not in seen:
            seen[c] = fn(c)
        return seen[c]
    for c in coarse:
        f(c)
    best = min(seen.values(), key=lambda r: r["usd_day"])
    step = max(1, int(round(0.1 * best["qpus"])))
    while True:
        c0 = best["c_pool"] or best["n_local"]
        cand = [f(c0 - step), f(c0 + step)] if step else []
        top = min(cand + [best], key=lambda r: r["usd_day"])
        if top is best:
            if step > 1:
                step = max(1, step // 2)
                continue
            break
        best = top
    return best


def study_cell(p: dict, hw: dict, N: float, lam: float, X: float) -> dict[str, Any]:
    """All topologies for one (calls per task, classical cost) cell; each topology takes its cheapest tested sizing."""
    ref = evaluate(p, hw, N, lam, X, "gpu_only")
    rows: dict[str, dict] = {"gpu_only": ref}
    if lam > 0:
        coarse = [c for c in _pool_candidates(p, hw, N, lam) if c > 0]
        G0 = size_gpus(p, hw, _demand(p, hw, N), 0.0)["modules"]
        rows["specialised"] = _hill(lambda c: evaluate(p, hw, N, lam, X, "specialised", 0, c), coarse)
        rows["integrated"] = _hill(lambda n: evaluate(p, hw, N, lam, X, "integrated", n, 0), coarse)
        for k in ("integrated",):
            rows[k]["modules_per_node"] = G0 / max(1, rows[k]["n_local"])
        for m in (16, 64):                                           # server-scale integration: one QPU per m GPU modules
            r = evaluate(p, hw, N, lam, X, "integrated", max(1, int(math.ceil(G0 / m))), 0)
            r["modules_per_node"] = m
            rows[f"integrated_{m}"] = r
        star = rows["specialised"]["c_pool"]
        mix = []
        for nl in (1, 2, 3, 4, 6, 8, 12):
            if nl > max(star, 2):
                continue
            mix.append(_hill(lambda c, nl=nl: evaluate(p, hw, N, lam, X, "mix", nl, c), sorted({max(1, int(round(star * f))) for f in (0.3, 0.5, 0.75, 1.0, 1.3)})))
        rows["mix"] = min(mix, key=lambda r: r["usd_day"])
        rows["mix"]["modules_per_node"] = G0 / max(1, rows["mix"]["n_local"])
    best = min((r for k, r in rows.items() if k in ("gpu_only", "specialised", "integrated", "mix")), key=lambda r: r["usd_day"])
    rows["best_topology"] = best["topo"]
    for k in [k for k in rows if k in ("specialised", "integrated", "mix") or k.startswith("integrated_")]:
        if k in rows:
            rows[k]["cost_vs_gpu_only"] = rows[k]["usd_day"] / ref["usd_day"]
            rows[k]["energy_vs_gpu_only"] = rows[k]["mean_facility_mw"] / ref["mean_facility_mw"]
            rows[k]["peak_vs_gpu_only"] = rows[k]["peak_facility_mw"] / ref["peak_facility_mw"]
    return rows


def sweep(p: dict | None = None, lams: list | None = None, Xs: list | None = None, N: float | None = None, progress=None) -> dict[str, Any]:
    p = p or load_params()
    hw = _hw(p)
    N = float(N or p["pod"]["users"])
    lams = lams if lams is not None else p["grid"]["calls_per_bg_task"]
    Xs = Xs if Xs is not None else p["grid"]["classical_module_hours"]
    cells = {}
    for lam in lams:
        for X in Xs:
            cells[(lam, X)] = study_cell(p, hw, N, lam, X)
            if progress:
                progress(lam, X)
    return {"params": p, "hw": {k: v for k, v in hw.items() if k != "gpu"}, "users": N, "cells": cells}


def max_users(p: dict, hw: dict, lam: float, X: float, cap_mw: float | None = None, lo: float = 2e5, hi: float = 3e6) -> dict[str, Any]:
    """Largest user count whose cheapest sizing of each topology stays within the pod's peak facility power cap."""
    cap = float(cap_mw or p["pod"]["cap_mw"])
    out = {}
    for topo in ("gpu_only", "best_hybrid"):
        a, b = lo, hi
        for _ in range(9):
            mid = 0.5 * (a + b)
            cell = study_cell(p, hw, mid, lam, X)
            r = cell["gpu_only"] if topo == "gpu_only" else min((cell[k] for k in ("gpu_only", "specialised", "integrated", "mix") if k in cell), key=lambda r: r["usd_day"])
            if r["peak_facility_mw"] <= cap:
                a = mid
            else:
                b = mid
        out[topo] = a
    return out


# ---------------------------------------------------------------- the full study (what the CLI runs)
TOPOS = ("gpu_only", "specialised", "integrated", "mix")
TOPO_LABEL = {"gpu_only": "GPU-only reference", "specialised": "Specialised pools (shared QPU hall)", "integrated": "Integrated nodes (one QPU per node)",
              "mix": "Mix (node QPUs + shared hall)"}


def _row(r: dict) -> dict:
    keys = ("topo", "qpus", "n_local", "c_pool", "modules_per_node", "gpu_modules", "dedicated_cpu_sockets", "calls_day", "calls_on_qpu", "calls_classical",
            "qpu_util", "wait_p50_s", "wait_p95_s", "gpu_mean_mw", "cpu_mean_mw", "qpu_mean_mw", "mean_facility_mw", "peak_facility_mw", "capex_hw_usd",
            "usd_day", "usd_per_task", "j_per_task_facility", "cost_vs_gpu_only", "energy_vs_gpu_only", "peak_vs_gpu_only")
    return {k: r[k] for k in keys if k in r}


def _cell_summary(cell: dict) -> dict:
    out = {k: _row(cell[k]) for k in cell if k in TOPOS or k.startswith("integrated_")}
    out["best_topology"] = cell["best_topology"]
    return out


def run_study(out_dir=None, quick: bool = False, progress=print) -> dict[str, Any]:
    """The whole study. ``quick`` uses a smaller grid (for tests and a first look)."""
    p = load_params()
    hw = _hw(p)
    lams = [0.0, 3e-4, 1e-3, 3e-3] if quick else p["grid"]["calls_per_bg_task"]
    Xs = [0.3, 3.0, 30.0] if quick else p["grid"]["classical_module_hours"]
    N = float(p["pod"]["users"])
    res: dict[str, Any] = {"params": p, "hw": {k: v for k, v in hw.items() if k != "gpu"}, "users": N, "grid": {"lams": lams, "Xs": Xs}}
    # 1. map
    grid = {}
    for lam in lams:
        for X in Xs:
            cell = study_cell(p, hw, N, lam, X)
            grid[f"{lam}|{X}"] = _cell_summary(cell)
            progress(f"  map lam={lam:g} X={X:g}: best {cell['best_topology']}")
    res["map"] = grid
    # 2. headline cells
    heads = [(1e-3, 1.0), (1e-3, 10.0), (1e-3, 100.0)] if not quick else [(1e-3, 10.0)]
    res["headline"] = {f"{l}|{x}": _cell_summary(study_cell(p, hw, N, l, x)) for l, x in heads}
    base = (1e-3, 10.0)
    # 3. sensitivities at the base cell
    sens_def = [("iterations_per_call", "quantum", [1e3, 1e5, 1e6]), ("capex_scale", "quantum", [0.25, 0.5, 2.0]),
                ("max_wait_s", "quantum", [300, 7200]), ("workload", "quantum", ["vqe_20q", "chemistry_small"]),
                ("host_cpu_spare_fraction", "cpu", [0.0, 0.9]), ("duration_cv", "quantum", [0.0, 1.0])]
    if quick:
        sens_def = sens_def[:1]
    sens = []
    for key, sec, vals in sens_def:
        for v in vals:
            q = load_params({sec: {key: v}})
            qh = _hw(q)
            cell = study_cell(q, qh, N, *base)
            sens.append({"param": f"{sec}.{key}", "value": v, "best": cell["best_topology"], "rows": _cell_summary(cell)})
            progress(f"  sensitivity {key}={v}: best {cell['best_topology']}")
    res["sensitivity"] = sens
    # 4. seed robustness at the base cell
    seeds = []
    for sd in (range(1, 3) if quick else range(1, 6)):
        q = load_params({"pod": {"seed": sd}})
        cell = study_cell(q, hw, N, *base)
        seeds.append({"seed": sd, "usd_day": {k: cell[k]["usd_day"] for k in TOPOS}, "mean_mw": {k: cell[k]["mean_facility_mw"] for k in TOPOS}, "best": cell["best_topology"]})
    res["seeds"] = seeds
    # 5. users served at the pod's power cap
    nstar = []
    for l, x in ([(1e-3, 3.0), (1e-3, 10.0), (3e-4, 30.0)] if not quick else [(1e-3, 10.0)]):
        nstar.append({"lam": l, "X": x, **max_users(p, hw, l, x)})
        progress(f"  users at cap lam={l:g} X={x:g}: {nstar[-1]}")
    res["users_at_cap"] = {"cap_mw": p["pod"]["cap_mw"], "rows": nstar}
    if out_dir:
        write_study(res, out_dir)
    return res


def study_markdown(res: dict) -> str:
    p, hw = res["params"], res["hw"]
    L = []
    a = L.append
    a("# Use case B: specialised vs integrated vs mixed nodes (GPU-only reference always shown)\n")
    a(f"Pod of {res['users']:,.0f} agent developers (12 interactive + 30 background tasks of 80 steps per user and day), cap {p['pod']['cap_mw']} MW facility. "
      f"QPU = {hw['qpu_label']} ({hw['qpu_busy_w'] / 1e3:.0f} kW busy, {hw['qpu_standby_w'] / 1e3:.0f} kW standby, ${hw['qpu_capex'] / 1e6:.0f}M assumed), "
      f"kernel {p['quantum']['workload']} ({hw['qpu_runtime_s']:.1f} s per call, {hw['qpu_energy_j'] / 1e6:.1f} MJ). **All unit costs, call densities and classical "
      f"costs are assumptions; the quantum side is read from quantum_arch.**\n")
    a("`calls/task` = quantum-eligible tool calls per background task; `X` = cost of the best classical method for such a call at equal accuracy, GPU module-hours.\n")
    # headline
    for key, cell in res["headline"].items():
        lam, X = key.split("|")
        a(f"\n## Base comparison: {float(lam):g} calls per background task, X = {float(X):g} module-hours\n")
        a("| design | QPUs (node + hall) | GPU modules | mean MW (GPU / CPU / QPU, IT) | peak MW | kJ/task | k$/day | $/day vs GPU-only | calls on QPU | QPU util | wait p95 |")
        a("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for k in list(TOPOS) + [x for x in cell if x.startswith("integrated_")]:
            if k not in cell:
                continue
            r = cell[k]
            name = TOPO_LABEL.get(k, f"Integrated at {r.get('modules_per_node', 0):.0f} GPU modules per QPU (server scale)")
            qs = f"{r['qpus']} ({r['n_local']}+{r['c_pool']})" if r["qpus"] else "0"
            a(f"| {name} | {qs} | {r['gpu_modules']:,} | {r['mean_facility_mw']:.1f} ({r['gpu_mean_mw']:.1f} / {r['cpu_mean_mw']:.1f} / {r['qpu_mean_mw']:.1f}) | {r['peak_facility_mw']:.1f} | {r['j_per_task_facility'] / 1e3:.0f} | "
              f"{r['usd_day'] / 1e3:,.0f} | {r.get('cost_vs_gpu_only', 1.0):.2f} | {r['calls_on_qpu']:,}/{r['calls_day']:,} | {r['qpu_util']:.0%} | {r['wait_p95_s']:.0f} s |")
        a(f"\nCheapest: **{TOPO_LABEL[cell['best_topology']]}**.")
    # map
    a("\n## Which design wins, over the unknowns (cheapest total cost per day)\n")
    lams, Xs = res["grid"]["lams"], res["grid"]["Xs"]
    a("| calls/task \\ X (module-h) | " + " | ".join(f"{x:g}" for x in Xs) + " |")
    a("|---|" + "---|" * len(Xs))
    short = {"gpu_only": "GPU", "specialised": "pool", "integrated": "node", "mix": "mix"}
    for lam in lams:
        cells = []
        for X in Xs:
            c = res["map"][f"{lam}|{X}"]
            b = c["best_topology"]
            cells.append(f"{short[b]} ({c[b].get('cost_vs_gpu_only', 1.0):.2f})" if b != "gpu_only" else "GPU")
        a(f"| {lam:g} | " + " | ".join(cells) + " |")
    a("\nCell = cheapest design (ratio of its cost to the GPU-only reference in brackets). `GPU` = no QPU pays off; `pool` = shared QPU hall; `node` = one QPU per node; `mix` = both.\n")
    # sensitivity
    a("\n## Sensitivity at the base cell (1e-3 calls per task, X = 10)\n")
    a("| changed input | value | cheapest | pool k$/day | node k$/day | mix k$/day | GPU-only k$/day |")
    a("|---|---|---|---:|---:|---:|---:|")
    for s in res["sensitivity"]:
        r = s["rows"]
        a(f"| {s['param']} | {s['value']} | {short[s['best']]} | {r['specialised']['usd_day'] / 1e3:,.0f} | {r['integrated']['usd_day'] / 1e3:,.0f} | {r['mix']['usd_day'] / 1e3:,.0f} | {r['gpu_only']['usd_day'] / 1e3:,.0f} |")
    a("\n## Robustness to the random call stream (base cell, 5 seeds)\n")
    a("| seed | cheapest | pool | node | mix | GPU-only (k$/day) |")
    a("|---|---|---:|---:|---:|---:|")
    for s in res["seeds"]:
        u = s["usd_day"]
        a(f"| {s['seed']} | {short[s['best']]} | {u['specialised'] / 1e3:,.0f} | {u['integrated'] / 1e3:,.0f} | {u['mix'] / 1e3:,.0f} | {u['gpu_only'] / 1e3:,.0f} |")
    a(f"\n## Users served within the pod's {res['users_at_cap']['cap_mw']} MW peak facility cap\n")
    a("| calls/task | X | GPU-only | cheapest hybrid |")
    a("|---|---|---:|---:|")
    for r in res["users_at_cap"]["rows"]:
        a(f"| {r['lam']:g} | {r['X']:g} | {r['gpu_only']:,.0f} | {r['best_hybrid']:,.0f} |")
    a("\nBisection on the user count, each point re-sized; the answer is the largest tested user count under the cap.")
    return "\n".join(L) + "\n"


def write_study(res: dict, out_dir) -> None:
    from pathlib import Path
    from .config import clean_json
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(clean_json(res), indent=1), encoding="utf-8")
    (out / "summary.md").write_text(study_markdown(res), encoding="utf-8")
    try:
        _figures(res, out)
    except Exception as e:                                         # figures are optional
        (out / "figures_error.txt").write_text(str(e), encoding="utf-8")


def _figures(res: dict, out) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lams, Xs = res["grid"]["lams"], res["grid"]["Xs"]
    Z = np.ones((len(lams), len(Xs)))
    lab = [[""] * len(Xs) for _ in lams]
    short = {"gpu_only": "GPU", "specialised": "pool", "integrated": "node", "mix": "mix"}
    for i, lam in enumerate(lams):
        for j, X in enumerate(Xs):
            c = res["map"][f"{lam}|{X}"]
            b = c["best_topology"]
            Z[i, j] = c[b].get("cost_vs_gpu_only", 1.0) if b != "gpu_only" else 1.0
            lab[i][j] = short[b]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    im = ax.imshow(np.log10(Z), cmap="viridis_r", vmin=-1.3, vmax=0.0, aspect="auto", origin="lower")
    ax.set_xticks(range(len(Xs)), [f"{x:g}" for x in Xs])
    ax.set_yticks(range(len(lams)), [f"{l:g}" for l in lams])
    ax.set_xlabel("classical cost of one eligible call, GPU module-hours")
    ax.set_ylabel("eligible calls per background task")
    for i in range(len(lams)):
        for j in range(len(Xs)):
            ax.text(j, i, f"{lab[i][j]}\n{Z[i, j]:.2f}", ha="center", va="center", fontsize=7, color="white" if np.log10(Z[i, j]) > -0.7 else "black")
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("cost vs GPU-only (log10)")
    ax.set_title("Cheapest design vs GPU-only reference (1.0 = no QPU pays off)")
    fig.tight_layout()
    fig.savefig(out / "map.png", dpi=140)
    plt.close(fig)
    for key, cell in res["headline"].items():
        lam, X = key.split("|")
        fig, axs = plt.subplots(1, 3, figsize=(10, 3.4))
        names = [k for k in TOPOS if k in cell]
        cols = {"gpu_only": "#7f7f7f", "specialised": "#1f77b4", "integrated": "#d55e00", "mix": "#009e73"}
        for ax, (m, t, sc) in zip(axs, (("usd_day", "cost, k$/day", 1e3), ("mean_facility_mw", "mean facility power, MW", 1.0), ("j_per_task_facility", "energy per task, kJ", 1e3))):
            ax.bar([short[n] for n in names], [cell[n][m] / sc for n in names], color=[cols[n] for n in names])
            ax.set_title(t, fontsize=9)
            ax.tick_params(labelsize=8)
        fig.suptitle(f"{float(lam):g} calls/task, X = {float(X):g} module-hours", fontsize=10)
        fig.tight_layout()
        fig.savefig(out / f"headline_{lam}_{X}.png", dpi=140)
        plt.close(fig)
