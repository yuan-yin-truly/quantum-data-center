"""Option generation shared by every scheduling policy: where could this unit run, how long, at what energy and cost?

An :class:`Option` is one feasible (node, route) with its predicted start/end, transfer, energy to solution at the FACILITY
boundary and full resource cost (amortised capex of the occupied hardware + energy). Quantum options come from
``quantum_arch`` through :mod:`qfeas`; QPU queues and calibration windows are modelled exactly (``QpuState.earliest_slot``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import qfeas
from .fleet import Node
from .tasks import GpuWork, Unit, classical_alt
from quantum_arch.datacenter import _attempts  # expected attempts and failure probability for per-attempt acceptance p


@dataclass
class Option:
    unit: Unit
    node: Node
    route: str                      # classical | quantum
    modules: float = 0.0
    duty: float = 1.0
    start_t: float = 0.0
    end_t: float = 0.0
    dur_s: float = 0.0
    transfer_s: float = 0.0
    transfer_usd: float = 0.0
    energy_j: float = 0.0           # energy to solution, facility boundary
    cost_usd: float = 0.0           # full resource cost incl. expected fallback
    power_w: float = 0.0            # extra facility power while running
    ctx_gb: float = 0.0
    displaced: float = 0.0          # GPU modules the mass traffic is expected to lose
    displace_usd: float = 0.0
    opportunity_usd: float = 0.0     # keeping mixed nodes' GPU partition free for hybrid stages
    p_acc: float | None = None
    att_exp: float = 1.0
    att_plan: int = 1
    fail: float = 0.0
    slot: tuple[float, float] | None = None
    block_s: float = 0.0
    prep_s: float = 0.0
    post_s: float = 0.0
    wait_s: float = 0.0
    work: GpuWork | None = None
    speed: float = 1.0
    ok: bool = True
    why_not: str = ""
    note: str = ""
    classical_ref_cost: float = 0.0
    att_cost_usd: float = 0.0
    att_energy_j: float = 0.0
    occ_att_s: float = 0.0

    @property
    def site(self) -> str:
        return self.node.site

    @property
    def total_cost(self) -> float:
        return self.cost_usd + self.displace_usd + self.opportunity_usd

    def meets_deadline(self) -> bool:
        return self.end_t <= self.unit.deadline + 1e-9


class Planner:
    def __init__(self, eng: Any):
        self.eng = eng
        self.fl = eng.fleet
        yrs = float(self.fl.challenge["amortisation_years"])
        self.s_per_amort = yrs * 365.0 * 86400.0
        self._static: dict[tuple, dict] = {}
        self._free: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._free_t: float = -1.0
        self._cls_cost: dict[str, float] = {}

    # --- tick cache -------------------------------------------------------------------------------------
    def begin_tick(self, now: float) -> None:
        self._free.clear()
        self._free_t = now

    def invalidate_group(self, group: Any) -> None:
        self._free.pop(id(group), None)

    def free_arrays(self, group: Any, now: float) -> tuple[np.ndarray, np.ndarray]:
        key = id(group)
        if key not in self._free:
            site = self.fl.sites[group.site]
            pool = site.pools.get(group.nodes[0].pool)
            phi = self.eng.phi.get((group.site, pool.kind), 0.0) if pool else 0.0
            self._free[key] = (group.free(now, 0.0), group.free(now, phi))
        return self._free[key]

    # --- unit helpers -----------------------------------------------------------------------------------
    def src_of(self, unit: Unit) -> str:
        return unit.prev_site or f"region:{unit.task['home_region']}"

    def capex_mod_s(self, node: Node) -> float:
        c = self.fl.node_cfg[node.type_key]
        return float(c.get("capex_per_module_usd", 0.0)) / self.s_per_amort

    def capex_qpu_s(self, node: Node) -> float:
        return float(self.fl.node_cfg[node.type_key]["capex_usd"]) / self.s_per_amort

    def price_j(self, site_id: str) -> float:
        return self.fl.sites[site_id].price_usd_per_mwh / 3.6e9

    def site_k(self, site_id: str, now: float) -> float:
        return (1.0 + self.fl.net_overhead()) * self.fl.pue(self.fl.sites[site_id], now, self.eng.start_utc_hour)

    def speed_for(self, node: Node, need: str) -> float:
        if need == "prefill":
            return node.prefill_speed
        if need == "decode":
            return node.decode_speed
        return 1.0 if node.kind in ("gpu", "mixed") else 0.0

    # --- GPU options ------------------------------------------------------------------------------------
    def gpu_candidates(self, work: GpuWork, now: float, first_fit: bool = False, per_group: int = 2) -> list[tuple[Node, float, float, float]]:
        """Candidate (node, modules m, free_raw, free_protected) per node group, best-fit and most-free."""
        out = []
        for site in self.fl.site_list:
            for g in site.groups.values():
                n0 = g.nodes[0]
                if self.speed_for(n0, work.need) <= 0:
                    continue
                free_raw, free_prot = self.free_arrays(g, now)
                m_req = np.minimum(float(work.modules), g.mod)
                m_min = np.minimum(m_req, max(1.0, math.ceil(0.25 * work.modules)))
                feas = np.floor(free_raw) >= m_min
                if not feas.any():
                    continue
                if first_fit:
                    full = feas & (np.floor(free_raw) >= m_req)
                    idx = np.flatnonzero(full)
                    i = int(idx[0]) if idx.size else int(np.flatnonzero(feas)[0])
                    out.append((g.nodes[i], float(min(m_req[i], np.floor(free_raw[i]))), float(free_raw[i]), float(free_raw[i])))
                    continue
                chosen = []
                nodisp = feas & (free_prot >= m_req)
                if nodisp.any():
                    cand = np.flatnonzero(nodisp)
                    chosen.append(int(cand[np.argmin(free_prot[cand])]))               # best fit
                    chosen.append(int(cand[np.argmax(free_prot[cand])]))               # most free
                else:
                    cand = np.flatnonzero(feas)
                    chosen.append(int(cand[np.argmax(free_prot[cand])]))
                seen = set()
                for i in chosen:
                    if i in seen or len(seen) >= per_group:
                        continue
                    seen.add(i)
                    m = float(min(m_req[i], np.floor(free_raw[i])))
                    out.append((g.nodes[i], m, float(free_raw[i]), float(free_prot[i])))
        return out

    def gpu_option(self, unit: Unit, node: Node, m: float, work: GpuWork, route: str, now: float, free_prot: float,
                   latency: float, in_gb: float | None = None) -> Option:
        sp = self.speed_for(node, work.need)
        dur = work.module_s / (m * sp) + work.fixed_s
        gb = unit.in_gb if in_gb is None else in_gb
        src = self.src_of(unit)
        same_node = unit.prev_node == node.id
        t_s = 0.0 if same_node else self.fl.transfer_time_s(gb, src, node.site)
        t_usd = 0.0 if same_node else self.fl.transfer_usd(gb, src, node.site)
        k = self.site_k(node.site, now)
        busy_w = m * (node.idle_sys_w + node.dyn_sys_w * work.duty)
        dyn_w = m * node.dyn_sys_w * work.duty
        pj = self.price_j(node.site)
        e_j = busy_w * k * dur
        cost = m * dur * self.capex_mod_s(node) + e_j * pj + t_usd
        start = now + latency + t_s
        disp = max(0.0, m - free_prot) if free_prot < m else 0.0
        if self.eng.policy.protect_fluid:
            hp = self.eng.power_headroom_protected_w(node.site)
            if dyn_w * k > hp:
                disp = max(disp, min(m, (dyn_w * k - max(0.0, hp)) / max(node.dyn_sys_w * k, 1.0)))
        disp_usd = disp * dur * float(self.fl.eng["fluid_displace_usd_per_module_s"])
        opp = 0.0
        if node.kind == "mixed" and self.eng.policy.smart and unit.task["type"] != "hybrid_pipeline":
            opp = 0.5 * cost      # ASSUMPTION: a mixed node's GPUs are worth more kept free for co-located hybrid stages
        return Option(unit=unit, node=node, route=route, modules=m, duty=work.duty, start_t=start, end_t=start + dur, dur_s=dur,
                      transfer_s=t_s, transfer_usd=t_usd, energy_j=e_j, cost_usd=cost, power_w=dyn_w * k, ctx_gb=work.ctx_gb,
                      displaced=disp, displace_usd=disp_usd, opportunity_usd=opp, work=work, speed=sp, wait_s=0.0)

    def classical_options(self, unit: Unit, work: GpuWork, route: str, now: float, latency: float, first_fit: bool = False,
                          per_group: int = 2) -> list[Option]:
        opts = []
        for node, m, _fr, fp in self.gpu_candidates(work, now, first_fit, per_group):
            if work.ctx_gb > 0 and self.eng.ctx_free_tb(node.site) * 1000.0 < work.ctx_gb:
                continue
            opts.append(self.gpu_option(unit, node, m, work, route, now, fp, latency))
        return opts

    # --- quantum options --------------------------------------------------------------------------------
    def classical_cost_estimate(self, unit: Unit) -> tuple[float, float]:
        """Static estimate of the classical alternative (cost, energy J) on the cheapest GPU rack: for fallback expectation."""
        alt = classical_alt(unit)
        if alt is None:
            return 0.0, 0.0
        key = unit.uid
        if key in self._cls_cost:
            return self._cls_cost[key]
        best = None
        for site in self.fl.site_list:
            g = site.groups.get("gpu_rack")
            if not g:
                continue
            n = g.nodes[0]
            m = min(alt.modules, n.modules)
            dur = alt.module_s / m
            k = (1 + self.fl.net_overhead()) * self.fl.fleet_pue_max(site)
            e = m * (n.idle_sys_w + n.dyn_sys_w) * k * dur
            c = m * dur * self.capex_mod_s(n) + e * self.price_j(site.id)
            if best is None or c < best[0]:
                best = (c, e)
        self._cls_cost[key] = best or (0.0, 0.0)
        return self._cls_cost[key]

    def quantum_check_for(self, node: Node, q: dict) -> dict:
        return qfeas.quantum_check(self.fl.node_cfg[node.type_key], q)

    def quantum_option(self, unit: Unit, node: Node, now: float, latency: float) -> Option | None:
        q = unit.q
        chk = self.quantum_check_for(node, q)
        if not chk["feasible"]:
            return Option(unit=unit, node=node, route="quantum", ok=False, why_not=f"{self.fl.node_cfg[node.type_key]['label']}: {chk['reason']}")
        qp = node.qpu
        gate = q.get("kind", "gate") == "gate"
        rep = float(q.get("repeats", 1)) if gate else 1.0
        run_s = chk["runtime_s"] * rep
        setup = float(q.get("qpu_setup_s", 60.0)) if gate else 0.0
        prep, post = (float(q.get("prep_s", 0.0)), float(q.get("post_s", 0.0))) if gate else (0.0, 0.0)
        mq = float(q.get("mapping_quality", 1.0))
        p = min(1.0, chk["p_accept"] * mq)
        k_att = int(q.get("max_attempts", 2))
        att_exp, fail = _attempts(p, k_att)
        att_plan = max(1, int(math.ceil(att_exp - 1e-9)))
        mixed = node.kind == "mixed"
        occ_att = run_s + setup + (0.0 if mixed else prep + post)
        block = att_plan * occ_att
        src = self.src_of(unit)
        same_node = unit.prev_node == node.id
        t_s = 0.0 if same_node else self.fl.transfer_time_s(unit.in_gb, src, node.site)
        t_usd = 0.0 if same_node else self.fl.transfer_usd(unit.in_gb, src, node.site)
        ready = now + latency + t_s + (prep if mixed else 0.0)
        slot_start = qp.earliest_slot(ready, block, node.down_until)
        if slot_start is None:
            return Option(unit=unit, node=node, route="quantum", ok=False,
                          why_not=f"{node.id}: job of {block:.0f} s cannot fit between calibration windows")
        active = [x for x in qp.queue if x["end"] > now]
        if len(active) >= qp.queue_max:
            return Option(unit=unit, node=node, route="quantum", ok=False, why_not=f"{node.id}: queue full ({qp.queue_max})")
        end = slot_start + block + (post if mixed else 0.0)
        start = slot_start - (prep if mixed else 0.0)
        sysj_att = chk["energy_system_j"] * rep + qp.busy_w * (setup + (0.0 if mixed or not gate else prep + post)) if gate else chk["energy_system_j"]
        k = self.site_k(node.site, now)
        pj = self.price_j(node.site)
        e_att_fac = sysj_att * k
        cls_cost, cls_e = self.classical_cost_estimate(unit)
        cost = att_exp * (occ_att * self.capex_qpu_s(node) + e_att_fac * pj) + fail * cls_cost + t_usd
        energy = att_exp * e_att_fac + fail * cls_e
        return Option(unit=unit, node=node, route="quantum", modules=0.0, start_t=start, end_t=end, dur_s=end - start,
                      transfer_s=t_s, transfer_usd=t_usd, energy_j=energy, cost_usd=cost,
                      power_w=(qp.busy_w - qp.standby_w) * k, p_acc=p, att_exp=att_exp, att_plan=att_plan, fail=fail,
                      slot=(slot_start, slot_start + block), block_s=block, prep_s=prep, post_s=post, wait_s=max(0.0, slot_start - ready),
                      classical_ref_cost=cls_cost, att_cost_usd=occ_att * self.capex_qpu_s(node) + e_att_fac * pj, att_energy_j=e_att_fac, occ_att_s=occ_att, note=f"p={p:.3f}/attempt, {att_exp:.2f} expected attempts")

    def quantum_options(self, unit: Unit, now: float, latency: float, first_only: bool = False) -> tuple[list[Option], list[str]]:
        opts, why = [], []
        seen_types: set[str] = set()
        for site in self.fl.site_list:
            for node in site.qpus:
                o = self.quantum_option(unit, node, now, latency)
                if o is None:
                    continue
                if not o.ok:
                    if node.type_key not in seen_types:
                        why.append(o.why_not)
                        seen_types.add(node.type_key)
                    continue
                opts.append(o)
                if first_only:
                    return opts, why
        return opts, why

    # --- all options ------------------------------------------------------------------------------------
    def all_options(self, unit: Unit, now: float, latency: float, allow_quantum: bool = True, first_fit: bool = False,
                    per_group: int = 2) -> tuple[list[Option], list[str]]:
        opts: list[Option] = []
        why: list[str] = []
        if unit.kind == "gpu":
            opts += self.classical_options(unit, unit.gpu, "classical", now, latency, first_fit, per_group)
        else:
            alt = classical_alt(unit)
            if alt is not None:
                opts += self.classical_options(unit, alt, "classical", now, latency, first_fit, per_group)
            if allow_quantum and not unit.force_classical:
                qopts, why = self.quantum_options(unit, now, latency)
                qopts = [o for o in qopts if self._accuracy_ok(unit, o)]
                opts += qopts
        return opts, why

    def _accuracy_ok(self, unit: Unit, o: Option) -> bool:
        """The quantum route is accepted when the success probability over the allowed attempts meets ``min_success``, or when a
        classical fallback exists (then a failure costs time and money, not correctness)."""
        if classical_alt(unit) is not None:
            return True
        return (1.0 - o.fail) >= unit.task["min_success"] - 1e-12

    # --- static feasibility (policy independent admission control) ---------------------------------------
    def static_check(self, unit: Unit, allow_quantum: bool = True) -> dict[str, Any]:
        key = (unit.uid, unit.force_classical, allow_quantum)
        if key in self._static:
            return self._static[key]
        reasons: list[str] = []
        min_dur = math.inf
        c_dur = math.inf
        q_dur = math.inf
        works: list[GpuWork] = []
        if unit.kind == "gpu":
            works.append(unit.gpu)
        else:
            alt = classical_alt(unit)
            if alt is not None:
                works.append(alt)
            elif unit.fb is not None and not unit.fb["accuracy_ok"]:
                reasons.append("classical fallback cannot reach the required accuracy")
            else:
                reasons.append("no classical method exists at this accuracy")
        for w in works:
            for site in self.fl.site_list:
                for g in site.groups.values():
                    n0 = g.nodes[0]
                    sp = self.speed_for(n0, w.need)
                    if sp <= 0:
                        continue
                    m = min(w.modules, n0.modules)
                    c_dur = min(c_dur, w.module_s / (m * sp) + w.fixed_s)
        if works and not math.isfinite(c_dur):
            reasons.append("no node type in the fleet can run this classical work")
        why_q: list[str] = []
        if unit.kind == "quantum" and not unit.force_classical and allow_quantum:
            seen = set()
            for site in self.fl.site_list:
                for node in site.qpus:
                    if node.type_key in seen:
                        continue
                    seen.add(node.type_key)
                    chk = self.quantum_check_for(node, unit.q)
                    if not chk["feasible"]:
                        why_q.append(f"{self.fl.node_cfg[node.type_key]['label']}: {chk['reason']}")
                        continue
                    gate = unit.q.get("kind", "gate") == "gate"
                    run = chk["runtime_s"] * (float(unit.q.get("repeats", 1)) if gate else 1.0) + (float(unit.q.get("qpu_setup_s", 60.0)) if gate else 0.0)
                    if gate and node.kind != "mixed":
                        run += float(unit.q.get("prep_s", 0)) + float(unit.q.get("post_s", 0))
                    p = min(1.0, chk["p_accept"] * float(unit.q.get("mapping_quality", 1.0)))
                    if not works and (1.0 - (1.0 - p) ** int(unit.q.get("max_attempts", 2))) < unit.task["min_success"] - 1e-12:
                        why_q.append(f"{self.fl.node_cfg[node.type_key]['label']}: success probability over {unit.q.get('max_attempts', 2)} attempts "
                                     f"{1.0 - (1.0 - p) ** int(unit.q.get('max_attempts', 2)):.3f} below the required {unit.task['min_success']}")
                        continue
                    q_dur = min(q_dur, run)
            if not math.isfinite(q_dur) and not why_q:
                why_q.append("no quantum node in the fleet")
        if unit.kind == "quantum":
            if not allow_quantum:
                reasons.append("quantum route disabled by the policy")
            elif not self.fl.has_quantum() and not works:
                why_q.append("no quantum node in the fleet")
            reasons += (["quantum: " + "; ".join(why_q)] if why_q else [])
        min_dur = min(c_dur, q_dur)
        out = {"min_dur_s": min_dur, "classical_min_s": c_dur, "quantum_min_s": q_dur, "reasons": reasons, "possible": math.isfinite(min_dur)}
        self._static[key] = out
        return out

    def remaining_min_s(self, unit: Unit, units_of_task: list[Unit], allow_quantum: bool = True) -> float:
        tot = 0.0
        for u in units_of_task[unit.idx + 1:]:
            s = self.static_check(u, allow_quantum)
            tot += s["min_dur_s"] if s["possible"] else 0.0
        return tot
