"""Cost model transparency: capex, 5-year energy, the budget/power feasibility check, and the quantum break-even table.

All unit prices are ASSUMPTIONS (``data/assumptions.json`` and the fleet file); powers and quantum job costs come from quantum_arch.
"""

from __future__ import annotations

import math
from typing import Any

from . import qfeas
from .config import assumptions
from .fleet import Fleet
from .tasks import default_fallback


def budget_power_check(fleet: Fleet, mean_gpu_utilisation: float = 0.65, qpu_utilisation: float = 0.15) -> dict[str, Any]:
    """Is the fleet inside $30B and 500 MW? Energy over the life is estimated at the given mean utilisations (ASSUMPTION)."""
    ch = fleet.challenge
    yrs = float(ch["amortisation_years"])
    cap = fleet.capex_table()
    sum_caps = sum(s.cap_w for s in fleet.site_list) / 1e6
    energy_usd = 0.0
    rows = []
    for s in fleet.site_list:
        net = fleet.net_overhead()
        pue = fleet.pue(s, 12 * 3600.0)
        sys_idle = sum(n.idle_sys_power_w() for n in s.nodes)
        sys_dyn = sum(n.modules * n.dyn_sys_w for n in s.nodes) * mean_gpu_utilisation
        sys_q = sum((n.qpu.busy_w - n.qpu.standby_w) * qpu_utilisation for n in s.qpus)
        fac_mean = (sys_idle + sys_dyn + sys_q) * (1 + net) * pue
        usd = fac_mean / 1e6 * 8760.0 * yrs * s.price_usd_per_mwh
        energy_usd += usd
        peak = fleet.peak_facility_w(s)
        rows.append({"site": s.id, "cap_mw": s.cap_w / 1e6, "peak_all_nodes_mw": peak / 1e6, "mean_facility_mw": fac_mean / 1e6,
                     "overbuilt": peak > s.cap_w * 1.0001, "energy_usd_5y": usd, "capex_usd": sum(cap["by_site"][s.id].values())})
    total = cap["total_usd"] + energy_usd
    return {"grid_total_mw": fleet.grid_total_mw, "sum_site_caps_mw": sum_caps, "power_ok": sum_caps <= fleet.grid_total_mw + 1e-9,
            "capex_usd": cap["total_usd"], "energy_usd_5y_estimate": energy_usd, "total_5y_usd": total, "budget_usd": ch["budget_usd"],
            "budget_ok": total <= ch["budget_usd"], "budget_used_pct": 100.0 * total / ch["budget_usd"],
            "capex_by_type": _capex_by_type(fleet), "sites": rows,
            "assumed_mean_gpu_utilisation": mean_gpu_utilisation, "assumed_qpu_utilisation": qpu_utilisation,
            "note": "Earth-only: launch cost ($200/kg to orbit) is not used. Energy over 5 years at the assumed mean utilisation; "
                    "site 'peak_all_nodes' above the cap is allowed (the scheduler throttles) but is flagged as overbuilt."}


def _capex_by_type(fleet: Fleet) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in fleet.site_list:
        for n in s.nodes:
            out[n.type_key] = out.get(n.type_key, 0.0) + n.capex_usd
        out["building+cooling"] = out.get("building+cooling", 0.0) + s.building_capex_usd
    return out


def quantum_breakeven(fleet: Fleet) -> list[dict[str, Any]]:
    """For every QPU node type in the fleet and every quantum_arch workload with an assumed classical fallback: cost per job on the QPU
    (marginal energy only, and with amortised capex at full utilisation), the classical cost, and the jobs per day at which owning
    one QPU node pays off. FALLBACK COSTS ARE ASSUMPTIONS and decide the sign of the result."""
    a = assumptions()
    yrs = float(fleet.challenge["amortisation_years"])
    g = qfeas.gpu_module()
    # cheapest classical per module-hour: a liquid/immersion rack at the cheapest site
    best = None
    for s in fleet.site_list:
        grp = s.groups.get("gpu_rack")
        if not grp:
            continue
        n = grp.nodes[0]
        k = (1 + fleet.net_overhead()) * fleet.pue(s, 12 * 3600.0)
        per_mod_h = (n.idle_sys_w + n.dyn_sys_w) * k / 1000.0 * s.price_usd_per_mwh / 1000.0 + fleet.node_cfg[n.type_key]["capex_per_module_usd"] / (yrs * 8760.0)
        if best is None or per_mod_h < best[0]:
            best = (per_mod_h, s.id)
    rows = []
    seen = set()
    for s in fleet.site_list:
        for n in s.qpus:
            if n.type_key in seen or n.kind == "annealer":
                continue
            seen.add(n.type_key)
            cfg = fleet.node_cfg[n.type_key]
            k = (1 + fleet.net_overhead()) * fleet.pue(s, 12 * 3600.0)
            fixed_day = cfg["capex_usd"] / (yrs * 365.0) + n.qpu.standby_w * k / 1e6 * 24.0 * s.price_usd_per_mwh
            for wl in ("chemistry_small", "vqe_50q", "vqe_20q", "qla_scalar_explicit_1m"):
                chk = qfeas.gate_check(cfg["architecture"], wl)
                fb = default_fallback(wl)
                if not chk["feasible"] or fb is None or fb["module_hours"] is None:
                    continue
                occ = chk["runtime_s"] + 60.0
                marg_q = (n.qpu.busy_w - n.qpu.standby_w) * k * occ / 3.6e9 * s.price_usd_per_mwh
                cls = fb["module_hours"] * best[0]
                saving = cls - marg_q
                rows.append({"qpu": cfg["label"], "workload": wl, "occupancy_s": occ, "max_jobs_per_day": 86400.0 / occ,
                             "qpu_marginal_usd_per_job": marg_q, "classical_usd_per_job": cls, "fixed_usd_per_day": fixed_day,
                             "breakeven_jobs_per_day": (fixed_day / saving) if saving > 0 else math.inf,
                             "pays_off_at_capacity": saving * 86400.0 / occ > fixed_day,
                             "classical_assumption": f"{fb['module_hours']:g} module-hours on {fb['modules']} modules (ASSUMPTION)"})
    return rows
