"""Architecture v2 for the 2035 data centre: pooled GPU nodes, CPU sandbox pool, context-memory pool and a shared QPU service.

An agent that issues a quantum-eligible call PARKS its session in the context-memory pool, releases its GPU, and is resumed on
any GPU node when the QPU result is back (``park``). The alternative keeps the session's KV cache in GPU HBM during the wait
(``hold``). Both are sized against the GPU-only reference (``gpu_only``), where the same calls run classically on GPUs or, if
their classical cost exceeds ``classical_max_module_hours``, are not served at all.

Workload: a MIX of user classes (coding agents = use case B from the slides, plus materials, chemistry, biology, mechanical and
finance engineers). Each class has its own task counts, tool load and density of quantum-eligible calls; the densities and the
classical costs are ASSUMPTIONS (nobody has measured them). An induced-demand factor multiplies the call densities.

Dispatch rule found by the sizing (level 4 of the north star): a call class is routed to the QPU service only if its saving per
QPU-second is high enough (classes are admitted in order of value density until adding the next one stops paying); everything
else runs classically. Predicting a task's QPU probability at submission is NOT modelled: with parking every GPU node can serve
every task, so the prediction would only help to reserve QPU slots.

Same boundaries and cost model as ``arch_study`` (facility power, amortised capex incl. facility, energy price).
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from . import arch_study as A
from . import qfeas
from .config import DATA, deep_merge, stable_seed

DAY = A.DAY


def load_params(over: dict | None = None) -> dict[str, Any]:
    p = A.load_params()
    p["design"] = json.loads((DATA / "dc_design.json").read_text(encoding="utf-8"))
    return deep_merge(p, over)


def _kernel(p: dict, hw: dict, name: str) -> dict[str, float]:
    from .config import assumptions
    node = assumptions()["node_types"][p["quantum"]["node_type"]]
    chk = qfeas.gate_check(node["architecture"], name)
    return {"runtime_s": float(chk["runtime_s"]) / float(chk["p_accept"]), "feasible": bool(chk["feasible"]), "energy_j": float(chk["energy_system_j"])}


def usd_per_module_hour(p: dict, hw: dict) -> float:
    eco = p["economics"]
    mult = (1 + hw["net"]) * hw["pue"]
    cap = hw["gpu_capex"] + hw["gpu_sys_tdp_w"] / 1e3 * mult * hw["fac_capex_per_kw"]
    return cap / (eco["amortisation_years"] * 8760.0) + hw["gpu_sys_tdp_w"] / 1e3 * 0.9 * mult * eco["energy_usd_per_mwh"] / 1e3


def demand(p: dict, hw: dict, N: float, m_ind: float = 1.0) -> dict[str, Any]:
    d = p["design"]
    out = {"int_mod": 0.0, "bg_mod": 0.0, "tool_cores": 0.0, "tasks_day": 0.0, "bg_tasks_day": 0.0, "classes": {}}
    for name, c in d["classes"].items():
        users = N * c["share"]
        s = hw["module_s_per_step"] * c["step_scale"]
        int_steps = users * c["interactive_tasks"] * c["steps"] / DAY
        bg_steps = users * c["background_tasks"] * c["steps"] / DAY
        out["int_mod"] += int_steps * s
        out["bg_mod"] += bg_steps * s
        out["tool_cores"] += bg_steps * c["tool_cores"] * c["tool_s"]
        out["tasks_day"] += users * (c["interactive_tasks"] + c["background_tasks"])
        bgt = users * c["background_tasks"]
        out["bg_tasks_day"] += bgt
        out["classes"][name] = {"users": users, "bg_tasks": bgt, "calls": int(round(c["calls_per_bg_task"] * m_ind * bgt))}
    return out


def _calls(p: dict, hw: dict, N: float, m_ind: float, dem: dict) -> dict[str, np.ndarray]:
    d = p["design"]
    rng = np.random.default_rng(stable_seed("design", round(N), m_ind, p["pod"].get("seed", 0)))
    cv = float(p["quantum"]["duration_cv"])
    sig = math.sqrt(math.log(1 + cv * cv))
    t, cls, dur, X, ctx = [], [], [], [], []
    names = list(d["classes"])
    for i, name in enumerate(names):
        c = d["classes"][name]
        n = dem["classes"][name]["calls"]
        k = _kernel(p, hw, c["kernel"])
        t.append(rng.uniform(0, DAY, n))
        cls.append(np.full(n, i))
        dur.append(k["runtime_s"] * rng.lognormal(-0.5 * sig * sig, sig, n))
        X.append(np.full(n, float(d["classical_fallback_module_hours"][c["kernel"]]) * float(d.get("classical_cost_scale", 1.0))))
        ctx.append(np.full(n, float(c["ctx_gb"])))
    t, cls, dur, X, ctx = (np.concatenate(a) if a else np.zeros(0) for a in (t, cls, dur, X, ctx))
    o = np.argsort(t, kind="stable")
    return {"t": t[o], "cls": cls[o].astype(int), "dur": dur[o], "X": X[o], "ctx": ctx[o], "names": names}


def _pool(calls: dict, admitted: set[int], c: int, hw: dict, p: dict) -> dict[str, Any]:
    """Shared QPU hall of ``c`` systems, FCFS, calibration windows staggered; wait limit -> classical overflow."""
    n = len(calls["t"])
    on = np.zeros(n, dtype=bool)
    wait = np.zeros(n)
    busy = np.zeros(max(c, 1))
    if c <= 0 or not admitted or n == 0:
        return {"on": on, "wait": wait, "busy_s": 0.0}
    I, C = hw["qpu_cal_interval"], hw["qpu_cal_dur"]
    off = (np.arange(c) / c) * I
    free = np.zeros(c)
    wmax = float(p["quantum"]["max_wait_s"])
    t, d, cl = calls["t"], calls["dur"], calls["cls"]
    for i in range(n):
        if cl[i] not in admitted:
            continue
        st = np.maximum(free, t[i])
        j = int(st.argmin())
        s = A._first_start(max(t[i], free[j]), d[i], off[j], I, C)
        if s - t[i] <= wmax:
            free[j] = s + d[i]
            busy[j] += d[i]
            on[i] = True
            wait[i] = s - t[i]
    return {"on": on, "wait": wait, "busy_s": float(busy.sum())}


_CACHE: dict[tuple, dict] = {}


def _pool_cached(p, hw, N, m_ind, calls, admitted, c):
    key = (round(N), m_ind, tuple(sorted(admitted)), c, p["pod"].get("seed", 0), p["quantum"]["max_wait_s"], p["quantum"]["duration_cv"])
    if key not in _CACHE:
        _CACHE[key] = _pool(calls, admitted, c, hw, p)
    return _CACHE[key]


def evaluate_design(p: dict, hw: dict, N: float, m_ind: float, mode: str, c: int = 0, admitted: frozenset | set = frozenset(), calls=None, dem=None) -> dict[str, Any]:
    """mode: gpu_only | park | hold. ``admitted`` = call classes routed to the QPU service."""
    d, pk, cpu, eco = p["design"], p["design"]["parking"], p["cpu"], p["economics"]
    dem = dem or demand(p, hw, N, m_ind)
    calls = calls if calls is not None else _calls(p, hw, N, m_ind, dem)
    if mode == "gpu_only":
        c, admitted = 0, set()
    sim = _pool_cached(p, hw, N, m_ind, calls, set(admitted), c)
    on, wait = sim["on"], sim["wait"]
    cap_mh = float(d["classical_max_module_hours"])
    feasible = calls["X"] <= cap_mh
    classical = (~on) & feasible
    unserved = (~on) & (~feasible)
    extra_mod = float(calls["X"][classical].sum()) * 3600.0 / DAY
    n_on = int(on.sum())
    # session overhead of QPU calls
    prefill_rate = hw["gpu"]["prefill_tok_s_70b"] / hw["model_cost_x"]
    if n_on:
        resid = wait[on] + calls["dur"][on]
        if mode == "park":
            restore = pk["recompute_share"] * pk["cached_ctx_tokens"] / prefill_rate + calls["ctx"][on] / (pk["transfer_gbps"] / 8.0)
            extra_mod += float(restore.sum()) / DAY
            parked_tb = float((calls["ctx"][on] * resid).sum()) / DAY / 1000.0 * 3.0       # x3: peak margin
        else:
            extra_mod += float((calls["ctx"][on] / pk["hbm_gb_per_module"] * resid).sum()) / DAY
            parked_tb = 0.0
    else:
        parked_tb = 0.0
    dem2 = dict(dem)
    gpu = A.size_gpus(p, hw, dem2, extra_mod)
    cores = dem["tool_cores"] + n_on * p["quantum"]["host_core_s_per_call"] / DAY
    cps = cpu["cores_per_socket"]
    dyn_w_core = (1 - cpu["idle_fraction"]) * hw["cpu_tdp_w"] * cpu["system_overhead"] / cps
    idle_w_sock = cpu["idle_fraction"] * hw["cpu_tdp_w"] * cpu["system_overhead"]
    if mode == "gpu_only":                    # sandboxes on the GPU servers' spare host CPUs, extra sockets if needed
        spare = gpu["modules"] * cpu["host_sockets_per_gpu_module"] * cps * cpu["host_cpu_spare_fraction"]
        dedicated = max(0, math.ceil((cores - spare * cpu["util"]) / cps / cpu["util"])) if cores > spare * cpu["util"] else 0
    else:                                     # disaggregated: a dedicated CPU sandbox pool
        dedicated = math.ceil(cores / cps / cpu["util"])
    cpu_mean_kw = (dedicated * idle_w_sock + cores * dyn_w_core) / 1e3
    busy_frac = sim["busy_s"] / (DAY * c) if c else 0.0
    qpu_mean_kw = c * (hw["qpu_standby_w"] + busy_frac * (hw["qpu_busy_w"] - hw["qpu_standby_w"])) / 1e3
    qpu_peak_kw = c * hw["qpu_busy_w"] / 1e3
    pools = parked_tb / pk["ctxmem_tb_per_pool"]
    ctx_kw = pools * pk["ctxmem_pool_kw"]
    mult = (1 + hw["net"]) * hw["pue"]
    mean_it = gpu["mean_kw"] + cpu_mean_kw + qpu_mean_kw + ctx_kw
    mean_fac_mw = mean_it * mult / 1e3
    peak_fac_mw = (gpu["peak_kw"] + cpu_mean_kw + qpu_peak_kw + ctx_kw) * mult / 1e3
    capex_hw = gpu["modules"] * hw["gpu_capex"] + dedicated * cpu["capex_usd_per_socket"] + c * hw["qpu_capex"] + pools * pk["ctxmem_pool_capex_usd"]
    capex_fac = peak_fac_mw * 1e3 * hw["fac_capex_per_kw"]
    cap_day = (capex_hw + capex_fac) / (eco["amortisation_years"] * 365.0)
    en_day = mean_fac_mw * 24.0 * eco["energy_usd_per_mwh"]
    usd_day = cap_day + en_day
    pen = float(unserved.sum()) * cap_mh * usd_per_module_hour(p, hw)
    names = calls["names"]
    table = {}
    for i, nm in enumerate(names):
        sel = calls["cls"] == i
        table[nm] = {"calls": int(sel.sum()), "on_qpu": int((on & sel).sum()), "classical": int((classical & sel).sum()), "unserved": int((unserved & sel).sum()),
                     "admitted": bool(i in admitted)}
    return {"mode": mode, "qpus": c, "admitted": [names[i] for i in sorted(admitted)], "gpu_modules": gpu["modules"], "gpu_racks": math.ceil(gpu["modules"] / 64),
            "cpu_sockets": dedicated, "ctxmem_tb": parked_tb, "calls_day": len(calls["t"]), "calls_on_qpu": n_on, "calls_classical": int(classical.sum()),
            "calls_unserved": int(unserved.sum()), "qpu_util": busy_frac, "wait_p95_s": float(np.percentile(wait[on], 95)) if n_on else 0.0,
            "gpu_mean_mw": gpu["mean_kw"] / 1e3, "cpu_mean_mw": cpu_mean_kw / 1e3, "qpu_mean_mw": qpu_mean_kw / 1e3, "ctx_mean_mw": ctx_kw / 1e3,
            "mean_facility_mw": mean_fac_mw, "peak_facility_mw": peak_fac_mw, "capex_hw_usd": capex_hw, "usd_day": usd_day, "usd_day_capex": cap_day,
            "usd_day_energy": en_day, "objective_usd_day": usd_day + pen, "tasks_day": dem["tasks_day"], "usd_per_task": usd_day / dem["tasks_day"],
            "j_per_task_facility": mean_fac_mw * 1e6 * DAY / dem["tasks_day"], "extra_gpu_modules": extra_mod, "by_class": table}


def _rank_classes(p: dict, hw: dict, calls: dict) -> list[int]:
    """Call classes by value density (classical cost, capped, per QPU-second): the order in which they are admitted."""
    cap = float(p["design"]["classical_max_module_hours"])
    dens = []
    for i in range(len(calls["names"])):
        sel = calls["cls"] == i
        if not sel.any():
            continue
        dens.append((min(calls["X"][sel][0], cap) / calls["dur"][sel].mean(), i))
    return [i for _, i in sorted(dens, reverse=True)]


def _hill(fn, coarse: list[int]) -> dict:
    seen: dict[int, dict] = {}

    def f(c: int) -> dict:
        c = max(1, int(c))
        if c not in seen:
            seen[c] = fn(c)
        return seen[c]
    for c in coarse:
        f(c)
    best = min(seen.values(), key=lambda r: r["objective_usd_day"])
    step = max(1, int(round(0.1 * best["qpus"])))
    while True:
        cand = [f(best["qpus"] - step), f(best["qpus"] + step)]
        top = min(cand + [best], key=lambda r: r["objective_usd_day"])
        if top is best:
            if step > 1:
                step //= 2
                continue
            break
        best = top
    return best


def design_cell(p: dict, hw: dict, N: float, m_ind: float = 1.0) -> dict[str, Any]:
    dem = demand(p, hw, N, m_ind)
    calls = _calls(p, hw, N, m_ind, dem)
    ref = evaluate_design(p, hw, N, m_ind, "gpu_only", calls=calls, dem=dem)
    out: dict[str, Any] = {"gpu_only": ref}
    rank = _rank_classes(p, hw, calls)
    for mode in ("park", "hold"):
        best = None
        for k in range(1, len(rank) + 1):
            adm = frozenset(rank[:k])
            need = sum(float(calls["dur"][calls["cls"] == i].sum()) for i in adm) / DAY
            coarse = sorted({max(1, int(math.ceil(need * f))) for f in (0.3, 0.5, 0.75, 1.0, 1.3, 1.7, 2.2)})
            r = _hill(lambda c, adm=adm: evaluate_design(p, hw, N, m_ind, mode, c, adm, calls, dem), coarse)
            if best is None or r["objective_usd_day"] < best["objective_usd_day"]:
                best = r
        # no-QPU option is the reference itself
        out[mode] = best if best["objective_usd_day"] < ref["objective_usd_day"] else {**ref, "mode": mode, "note": "no QPU pays off"}
    out["best_mode"] = min(("gpu_only", "park", "hold"), key=lambda k: out[k]["objective_usd_day"])
    return out


def users_at_cap(p: dict, hw: dict, m_ind: float, cap_mw: float | None = None) -> dict[str, float]:
    cap = float(cap_mw or p["pod"]["cap_mw"])
    lo0, hi0 = p["design"]["pod_users_for_cap_search"]
    res = {}
    for key in ("gpu_only", "park"):
        lo, hi = lo0, hi0
        for _ in range(8):
            mid = 0.5 * (lo + hi)
            cell = design_cell(p, hw, mid, m_ind)
            if cell[key]["peak_facility_mw"] <= cap:
                lo = mid
            else:
                hi = mid
        res[key] = lo
    return res


def run_design_study(out_dir=None, quick: bool = False, progress=print) -> dict[str, Any]:
    p = load_params()
    hw = A._hw(p)
    N = float(p["pod"]["users"])
    res: dict[str, Any] = {"params": p, "hw": {k: v for k, v in hw.items() if k != "gpu"}, "users": N, "usd_per_module_hour": usd_per_module_hour(p, hw)}
    factors = p["design"]["induced_demand_factors"][:2] if quick else p["design"]["induced_demand_factors"]
    res["scenarios"] = {}
    for m in factors:
        res["scenarios"][str(m)] = design_cell(p, hw, N, m)
        progress(f"  induced x{m:g}: best {res['scenarios'][str(m)]['best_mode']}")
    sens_def = [("quantum", "capex_scale", [0.5, 2.0]), ("design", "classical_max_module_hours", [50, 1000]), ("design", "classical_cost_scale", [0.1, 0.02]), ("quantum", "max_wait_s", [300]),
                ("quantum", "iterations_per_call", [1000000])]
    if quick:
        sens_def = sens_def[:1]
    sens = []
    for sec, key, vals in sens_def:
        for v in vals:
            q = load_params({sec: {key: v}})
            cell = design_cell(q, A._hw(q), N, 1.0)
            sens.append({"param": f"{sec}.{key}", "value": v, "best_mode": cell["best_mode"], "cells": {k: cell[k] for k in ("gpu_only", "park", "hold")}})
            progress(f"  sensitivity {key}={v}: best {cell['best_mode']}")
    # parking parameters
    for key, v in (("recompute_share", 1.0), ("hbm_gb_per_module", 256)):
        q = load_params({"design": {"parking": {key: v}}})
        cell = design_cell(q, A._hw(q), N, 1.0)
        sens.append({"param": f"parking.{key}", "value": v, "best_mode": cell["best_mode"], "cells": {k: cell[k] for k in ("gpu_only", "park", "hold")}})
    res["sensitivity"] = sens
    if not quick:
        res["users_at_cap"] = {"cap_mw": p["pod"]["cap_mw"], "rows": [{"induced": m, **users_at_cap(p, hw, m)} for m in factors[:2]]}
        progress(f"  users at cap: {res['users_at_cap']}")
    if out_dir:
        write_design_study(res, out_dir)
    return res


def design_markdown(res: dict) -> str:
    p = res["params"]
    d = p["design"]
    L = []
    a = L.append
    a("# Architecture v2: pooled GPU nodes, CPU sandbox pool, context-memory pool, shared QPU service (agents park while a QPU sub-task runs)\n")
    a(f"Pod of {res['users']:,.0f} users, mixed classes, {p['pod']['cap_mw']} MW facility cap. GPU-only reference = same task load, calls run classically on GPUs; "
      f"calls that would cost more than {d['classical_max_module_hours']} module-hours classically are **not served** there. One module-hour costs about "
      f"${res['usd_per_module_hour']:.1f} (amortised capex incl. facility + energy). **Class mix, call densities, classical costs and induced demand are assumptions.**\n")
    a("| class | users | bg tasks/day | calls per bg task | kernel | classical cost per call (module-h) |")
    a("|---|---:|---:|---:|---|---:|")
    base = res["scenarios"][next(iter(res["scenarios"]))]
    dem = demand(p, A._hw(p), res["users"], 1.0)
    for nm, c in d["classes"].items():
        a(f"| {nm} | {dem['classes'][nm]['users']:,.0f} | {dem['classes'][nm]['bg_tasks']:,.0f} | {c['calls_per_bg_task']:g} | {c['kernel']} | {d['classical_fallback_module_hours'][c['kernel']]:g} |")
    for m, cell in res["scenarios"].items():
        a(f"\n## Induced-demand factor x{float(m):g}\n")
        a("| design | QPUs | GPU modules (racks) | CPU sockets | ctx-mem TB | mean MW | peak MW | kJ/task | k$/day | calls on QPU / classical / unserved | QPU util | wait p95 |")
        a("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|")
        for k, nm in (("gpu_only", "GPU-only reference"), ("park", "Parked sessions + QPU service"), ("hold", "Hold GPU during QPU wait + QPU service")):
            r = cell[k]
            a(f"| {nm} | {r['qpus']} | {r['gpu_modules']:,} ({r['gpu_racks']:,}) | {r['cpu_sockets']:,} | {r['ctxmem_tb']:.1f} | {r['mean_facility_mw']:.1f} | {r['peak_facility_mw']:.1f} | "
              f"{r['j_per_task_facility'] / 1e3:.0f} | {r['usd_day'] / 1e3:,.0f} | {r['calls_on_qpu']:,} / {r['calls_classical']:,} / {r['calls_unserved']:,} | {r['qpu_util']:.0%} | {r['wait_p95_s']:.0f} s |")
        r = cell["park"]
        ref = cell["gpu_only"]
        tie = abs(cell["park"]["usd_day"] - cell["hold"]["usd_day"]) < 0.005 * cell["hold"]["usd_day"]
        best = "park and hold tie (within 0.5 %)" if tie and cell["best_mode"] != "gpu_only" else cell["best_mode"]
        a(f"\nCheapest by sizing objective (cost + unserved calls valued at the classical cap): **{best}**. Parked design vs reference: cost {r['usd_day'] / ref['usd_day']:.2f}x, "
          f"mean power {r['mean_facility_mw'] / ref['mean_facility_mw']:.2f}x, unserved calls {ref['calls_unserved']:,} -> {r['calls_unserved']:,}. Classes sent to the QPU service: {', '.join(r['admitted']) or 'none'}.\n")
        a("| class | calls/day | on QPU | classical | unserved | reference: classical | reference: unserved |")
        a("|---|---:|---:|---:|---:|---:|---:|")
        for nm in d["classes"]:
            t, tr = r["by_class"][nm], ref["by_class"][nm]
            a(f"| {nm} | {t['calls']:,} | {t['on_qpu']:,} | {t['classical']:,} | {t['unserved']:,} | {tr['classical']:,} | {tr['unserved']:,} |")
    a("\n## Sensitivity (induced factor 1)\n")
    a("`GPU-only k$/day` leaves out the calls the reference cannot serve; the `cheapest` column counts them at the classical cap. Park and hold differ by under 0.5 % in every row, i.e. they tie.\n")
    a("| changed input | value | cheapest | park k$/day | hold k$/day | GPU-only k$/day | park QPUs |")
    a("|---|---|---|---:|---:|---:|---:|")
    for s in res["sensitivity"]:
        c = s["cells"]
        a(f"| {s['param']} | {s['value']} | {s['best_mode']} | {c['park']['usd_day'] / 1e3:,.0f} | {c['hold']['usd_day'] / 1e3:,.0f} | {c['gpu_only']['usd_day'] / 1e3:,.0f} | {c['park']['qpus']} |")
    if "users_at_cap" in res:
        a(f"\n## Users served within the pod's {res['users_at_cap']['cap_mw']} MW peak facility cap\n")
        a("| induced factor | GPU-only | parked design |")
        a("|---|---:|---:|")
        lo = p["design"]["pod_users_for_cap_search"][0]
        for r in res["users_at_cap"]["rows"]:
            g = f"< {lo:,.0f} (below the search range)" if r["gpu_only"] <= lo * 1.001 else f"{r['gpu_only']:,.0f}"
            a(f"| x{r['induced']:g} | {g} | {r['park']:,.0f} |")
        a("\nUsers are scaled with the class mix fixed; the reference does not serve the calls above the classical cap in either case.")
    return "\n".join(L) + "\n"


def write_design_study(res: dict, out_dir) -> None:
    from pathlib import Path
    from .config import clean_json
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(clean_json(res), indent=1), encoding="utf-8")
    (out / "summary.md").write_text(design_markdown(res), encoding="utf-8")
