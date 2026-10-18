"""The scheduling node ("automated quantum Slurm"): one component, pluggable policies.

Inputs each tick: the pending units (tasks or hybrid-pipeline stages) and the live fleet state (free modules per node after the
share the mass traffic uses, QPU queues and calibration windows, power headroom of each site, context-memory pools, data-transfer
cost and latency between regions and sites). Output: for every pending unit an assignment to a node, or defer, or (admission
control, shared by all policies) reject, each with a short reason string.

Policies (same tasks, same engine, different decisions):

* ``fifo``      first-fit in arrival order. Home-region sites first, no deadline, cost or queue-time awareness; quantum-eligible work
                goes to the first feasible QPU ("quantum first"), the mass traffic is routed first-fit too.
* ``greedy``    priority/deadline-ordered, picks per unit the cheapest option that meets the SLO (cost = amortised capex of the
                occupied hardware + energy + transfer + displaced mass traffic); compares quantum with classical per unit; fluid traffic
                routed greedily by RTT feasibility and energy price.
* ``batch``     every tick a MILP (``scipy.optimize.milp``) over all pending units and candidate nodes: maximise priority-weighted
                tasks served within SLO, then minimise dollars, subject to node module capacity, QPU queue time (EDF prefix feasibility,
                calibration windows), power headroom per site and context memory; fluid traffic routed by an LP.
* ``gpu_only``  the reference: the ``batch`` machinery with the quantum route switched off (QPUs are never used).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds

from . import fluid
from .config import fmt_energy, fmt_time, fmt_usd
from .placement import Option, Planner
from .tasks import Unit, classical_alt

POLICIES = ("fifo", "greedy", "batch", "gpu_only")
POLICY_LABELS = {"fifo": "FIFO / first-fit", "greedy": "Greedy cost/time-aware", "batch": "Batch optimiser (MILP + LP)",
                 "gpu_only": "GPU-only reference (batch, no QPU)"}


@dataclass
class Decision:
    unit: Unit
    action: str                    # assign | defer | reject
    option: Option | None = None
    reason: str = ""
    alts: list[dict] = field(default_factory=list)


def tv_usd_per_s(unit: Unit) -> float:
    """Value of finishing one second earlier, used as a tie-breaker between options. ASSUMPTION (about 7 USD/h at priority 1)."""
    return 0.002 * unit.priority


def opt_summary(o: Option) -> dict:
    return {"node": o.node.id, "site": o.node.site, "route": o.route, "end_t": round(o.end_t, 1), "cost_usd": round(o.total_cost, 2),
            "energy_kwh": round(o.energy_j / 3.6e6, 3), "wait_s": round(o.wait_s, 1)}


class Policy:
    name = "base"
    allow_quantum = True
    protect_fluid = True
    smart = True
    sort_by_priority = True

    def __init__(self):
        self.eng: Any = None

    def bind(self, eng: Any) -> None:
        self.eng = eng
        self.planner = Planner(eng)

    # ---- fluid routing ---------------------------------------------------------------------------------
    def route_fluid(self, chunks: list, sfs: dict) -> dict:
        raise NotImplementedError

    # ---- discrete scheduling ---------------------------------------------------------------------------
    def latency_s(self, n_units: int, n_vars: int = 0) -> float:
        d = self.eng.fleet.eng["decision_latency"]
        return d["base_s"] + d["per_task_s"] * n_units

    def schedule(self, pending: list[Unit], now: float) -> list[Decision]:
        raise NotImplementedError

    # ---- shared helpers --------------------------------------------------------------------------------
    def power_ok(self, o: Option, taken: dict[str, float]) -> bool:
        return self.eng.power_headroom_w(o.node.site) - taken.get(o.node.site, 0.0) >= o.power_w - 1e-6

    def lookahead_usd(self, o: Option) -> float:
        """Pipeline lookahead: moving this stage's output to a site without a feasible QPU for the next stage costs transfer."""
        u = o.unit
        if u.out_gb <= 0 or u.is_last:
            return 0.0
        nxt = self.eng.units_of[u.task["id"]][u.idx + 1]
        wan = float(self.eng.fleet.eng["wan_usd_per_gb"])
        if nxt.kind == "quantum":
            for n in self.eng.fleet.sites[o.node.site].qpus:
                if self.planner.quantum_check_for(n, nxt.q)["feasible"]:
                    return 0.0
            return u.out_gb * wan
        return 0.0

    def explain(self, o: Option, opts: list[Option], head: str) -> str:
        u = o.unit
        dl = u.deadline
        t = fmt_time
        parts = [head]
        if o.route == "quantum":
            parts.append(f"quantum on {o.node.id} ({o.node.qpu.label}), queue wait {t(o.wait_s)}, run {t(o.block_s)}, "
                         f"{o.att_exp:.2f} expected attempts (p={o.p_acc:.3f}), ends t+{t(o.end_t - self.eng.t)} (SLO in {t(dl - self.eng.t)})")
        else:
            alt = "classical fallback of a quantum job" if u.kind == "quantum" else "GPU job"
            parts.append(f"{alt} on {o.node.id}: {o.modules:.0f} modules x {t(o.dur_s)}"
                         + (f", transfer {t(o.transfer_s)}" if o.transfer_s > 1 else "")
                         + f", ends t+{t(o.end_t - self.eng.t)} (SLO in {t(dl - self.eng.t)})")
        parts.append(f"cost {fmt_usd(o.total_cost)}, energy {fmt_energy(o.energy_j)} (facility)")
        if o.displaced > 0:
            parts.append(f"displaces {o.displaced:.0f} modules of mass traffic (priority {u.priority})")
        other = [x for x in opts if x.route != o.route]
        if other:
            bo = min(other, key=lambda x: x.total_cost)
            parts.append(f"best {bo.route} alternative: {fmt_usd(bo.total_cost)}, {fmt_energy(bo.energy_j)}, ends t+{t(bo.end_t - self.eng.t)}"
                         + ("" if bo.meets_deadline() else " (misses SLO)"))
        elif u.kind == "quantum":
            why = self.planner.static_check(u)["reasons"]
            if o.route == "classical":
                parts.append("no feasible quantum option: " + ("; ".join(why) if why else "none available now"))
            else:
                parts.append("no classical alternative at this accuracy")
        return " | ".join(parts)

    def defer_reason(self, unit: Unit, opts: list[Option], why_q: list[str], taken: dict[str, float]) -> str:
        if not opts:
            r = "no node with free capacity now (modules after the mass-traffic share, context memory or QPU queue)"
            if why_q:
                r += "; quantum: " + "; ".join(why_q[:2])
            return r
        if not any(self.power_ok(o, taken) for o in opts):
            return "site power headroom too small for every candidate node (cap respected, waiting)"
        best = min(opts, key=lambda o: o.end_t)
        return (f"cannot meet SLO with current queues (earliest finish t+{fmt_time(best.end_t - self.eng.t)}, "
                f"SLO in {fmt_time(unit.deadline - self.eng.t)}); waiting for capacity")


# ===================================================================================================================
class FifoPolicy(Policy):
    name = "fifo"
    protect_fluid = False
    smart = False
    sort_by_priority = False

    def route_fluid(self, chunks, sfs):
        return fluid.route_first_fit(self.eng, chunks, sfs)

    def schedule(self, pending, now):
        eng = self.eng
        lat = self.latency_s(len(pending))
        out: list[Decision] = []
        taken: dict[str, float] = {}
        for u in sorted(pending, key=lambda x: (x.task["arrival_s"], x.uid)):
            opts: list[Option] = []
            why: list[str] = []
            head = "FIFO first-fit"
            if u.kind == "quantum" and self.allow_quantum and not u.force_classical:
                qo, why = self.planner.quantum_options(u, now, lat, first_only=True)
                qo = [o for o in qo if self.planner._accuracy_ok(u, o) and self.power_ok(o, taken)]
                if qo:
                    o = qo[0]
                    out.append(self._assign(u, o, [o], head + ": first QPU node with a feasible slot (no cost or deadline comparison)", taken))
                    continue
            work = u.gpu if u.kind == "gpu" else classical_alt(u)
            if work is not None:
                opts = self.planner.classical_options(u, work, "classical", now, lat, first_fit=True)
                opts = [o for o in opts if self.power_ok(o, taken)]
            if opts:
                o = opts[0]
                tail = ": first node with enough free modules" if u.kind == "gpu" else ": no feasible QPU slot now, classical fallback on the first GPU node that fits"
                out.append(self._assign(u, o, opts, head + tail, taken))
            else:
                out.append(Decision(u, "defer", None, self.defer_reason(u, opts, why, taken)))
        return out

    def _assign(self, u, o, opts, head, taken):
        taken[o.node.site] = taken.get(o.node.site, 0.0) + o.power_w
        self.eng.apply_option(o)
        self.planner.invalidate_group(o.node.group) if o.node.group is not None else None
        return Decision(u, "assign", o, self.explain(o, opts, head), [opt_summary(x) for x in opts[:3]])


class GreedyPolicy(Policy):
    name = "greedy"

    def route_fluid(self, chunks, sfs):
        return fluid.route_greedy(self.eng, chunks, sfs)

    def _score(self, o: Option) -> float:
        return o.total_cost + self.lookahead_usd(o) + (o.end_t - self.eng.t) * tv_usd_per_s(o.unit)

    def schedule(self, pending, now):
        lat = self.latency_s(len(pending))
        out: list[Decision] = []
        taken: dict[str, float] = {}
        for u in sorted(pending, key=lambda x: (-x.priority, x.deadline, x.uid)):
            opts, why_q = self.planner.all_options(u, now, lat, allow_quantum=self.allow_quantum)
            feas = [o for o in opts if o.meets_deadline() and self.power_ok(o, taken)]
            if not feas:
                out.append(Decision(u, "defer", None, self.defer_reason(u, opts, why_q, taken)))
                continue
            o = min(feas, key=self._score)
            feas_sorted = sorted(feas, key=self._score)
            taken[o.node.site] = taken.get(o.node.site, 0.0) + o.power_w
            self.eng.apply_option(o)
            if o.node.group is not None:
                self.planner.invalidate_group(o.node.group)
            out.append(Decision(u, "assign", o, self.explain(o, feas, "Greedy: cheapest option meeting the SLO"),
                                [opt_summary(x) for x in feas_sorted[:3]]))
        return out


class BatchPolicy(Policy):
    name = "batch"
    max_units = 60

    def route_fluid(self, chunks, sfs):
        return fluid.route_lp(self.eng, chunks, sfs)

    def schedule(self, pending, now):
        eng = self.eng
        units = sorted(pending, key=lambda x: (-x.priority, x.deadline, x.uid))
        rest = units[self.max_units:]
        units = units[:self.max_units]
        out: list[Decision] = [Decision(u, "defer", None, "batch window full; considered next tick") for u in rest]
        # options per unit
        cand: list[tuple[Unit, list[Option]]] = []
        n_opt = 0
        for u in units:
            opts, why_q = self.planner.all_options(u, now, 0.0, allow_quantum=self.allow_quantum)
            feas = [o for o in opts if o.meets_deadline() and o.power_w <= eng.power_headroom_w(o.node.site) + 1e-6]
            if not feas:
                out.append(Decision(u, "defer", None, self.defer_reason(u, opts, why_q, {})))
                continue
            feas.sort(key=lambda o: o.total_cost + (o.end_t - now) * tv_usd_per_s(u))
            q = [o for o in feas if o.route == "quantum"][:8]
            c = [o for o in feas if o.route == "classical"][:12]
            keep = q + c
            cand.append((u, keep))
            n_opt += len(keep)
        lat = self.latency_s(len(units), n_opt)
        if cand:
            lat_extra = eng.fleet.eng["decision_latency"]["milp_base_s"] + eng.fleet.eng["decision_latency"]["milp_per_option_s"] * n_opt
            lat = lat + lat_extra - 0.0
        # shift all options by the decision latency (they were built with 0)
        for u, opts in cand:
            for o in opts:
                o.start_t += lat
                o.end_t += lat
                if o.slot is not None:
                    o.slot = (o.slot[0] + lat, o.slot[1] + lat)
        chosen = self._solve(cand, now) if cand else {}
        order = sorted(cand, key=lambda uo: (-uo[0].priority, uo[0].deadline, uo[0].uid))
        taken: dict[str, float] = {}
        for u, opts in order:
            oi = chosen.get(u.uid)
            if oi is None:
                out.append(Decision(u, "defer", None, "optimiser: no capacity-feasible assignment this tick (higher-value tasks took the slots); waiting"))
                continue
            o = opts[oi]
            # re-plan against the state after earlier assignments of this tick (queues, free modules, power)
            o2 = self._replan(o, now, lat)
            if o2 is None or not o2.meets_deadline() or not self.power_ok(o2, taken):
                out.append(Decision(u, "defer", None, "optimiser choice no longer feasible after earlier assignments this tick; re-solved next tick"))
                continue
            taken[o2.node.site] = taken.get(o2.node.site, 0.0) + o2.power_w
            eng.apply_option(o2)
            if o2.node.group is not None:
                self.planner.invalidate_group(o2.node.group)
            allopts = opts
            head = "Batch MILP: min cost subject to SLO, capacity, power, queue-time" if self.allow_quantum else "GPU-only reference (quantum route disabled)"
            out.append(Decision(u, "assign", o2, self.explain(o2, allopts, head), [opt_summary(x) for x in sorted(allopts, key=lambda x: x.total_cost)[:3]]))
        return out

    def _replan(self, o: Option, now: float, lat: float) -> Option | None:
        u = o.unit
        if o.route == "quantum":
            n = self.planner.quantum_option(u, o.node, now, lat)
            return n if n is not None and n.ok else None
        node = o.node
        g = node.group
        free_raw, free_prot = self.planner.free_arrays(g, now)
        fr = float(free_raw[node.gi])
        work = o.work
        m_req = min(float(work.modules), node.modules)
        m_min = min(m_req, max(1.0, math.ceil(0.25 * work.modules)))
        if math.floor(fr) < m_min:
            return None
        m = min(m_req, math.floor(fr))
        if work.ctx_gb > 0 and self.eng.ctx_free_tb(node.site) * 1000.0 < work.ctx_gb:
            return None
        return self.planner.gpu_option(u, node, m, work, o.route, now, float(free_prot[node.gi]), lat)

    # ---- the MILP ----------------------------------------------------------------------------------------
    def _solve(self, cand: list[tuple[Unit, list[Option]]], now: float) -> dict[str, int]:
        eng = self.eng
        var: list[tuple[int, int]] = []
        for ui, (u, opts) in enumerate(cand):
            for oi in range(len(opts)):
                var.append((ui, oi))
        n = len(var)
        c = np.zeros(n)
        for j, (ui, oi) in enumerate(var):
            u, opts = cand[ui]
            o = opts[oi]
            value = 1e5 * u.priority
            c[j] = -(value - self._score_milp(o, now))
        rows, ub = [], []

        def add(coefs: dict[int, float], bound: float) -> None:
            r = np.zeros(n)
            for j, v in coefs.items():
                r[j] = v
            rows.append(r)
            ub.append(bound)
        by_unit: dict[int, dict[int, float]] = {}
        by_gnode: dict[str, dict[int, float]] = {}
        by_qnode: dict[str, list[int]] = {}
        by_site_p: dict[str, dict[int, float]] = {}
        by_site_c: dict[str, dict[int, float]] = {}
        for j, (ui, oi) in enumerate(var):
            o = cand[ui][1][oi]
            by_unit.setdefault(ui, {})[j] = 1.0
            if o.route == "classical":
                by_gnode.setdefault(o.node.id, {})[j] = o.modules
            else:
                by_qnode.setdefault(o.node.id, []).append(j)
            if o.power_w > 0:
                by_site_p.setdefault(o.node.site, {})[j] = o.power_w
            if o.ctx_gb > 0:
                by_site_c.setdefault(o.node.site, {})[j] = o.ctx_gb
        for d in by_unit.values():
            add(d, 1.0)
        idx = eng.fleet.node_index()
        for nid, d in by_gnode.items():
            node = idx[nid]
            fr, _ = self.planner.free_arrays(node.group, now)
            add(d, float(math.floor(fr[node.gi])))
        for nid, js in by_qnode.items():
            node = idx[nid]
            qp = node.qpu
            active = len([x for x in qp.queue if x["end"] > now])
            add({j: 1.0 for j in js}, float(qp.queue_max - active))
            # EDF prefix feasibility on the QPU: sum of blocks of jobs with earlier-or-equal deadline fits before each deadline
            items = sorted(js, key=lambda j: cand[var[j][0]][0].deadline)
            base_start = min(cand[var[j][0]][1][var[j][1]].slot[0] for j in js)
            for k, jk in enumerate(items):
                dl = cand[var[jk][0]][0].deadline
                pref = {j: cand[var[j][0]][1][var[j][1]].block_s for j in items if cand[var[j][0]][0].deadline <= dl + 1e-9}
                add(pref, max(0.0, dl - base_start))
        for sid, d in by_site_p.items():
            add(d, max(0.0, eng.power_headroom_w(sid)))
        for sid, d in by_site_c.items():
            add(d, max(0.0, eng.ctx_free_tb(sid) * 1000.0))
        A = np.array(rows)
        cons = LinearConstraint(A, -np.inf, np.array(ub))
        res = milp(c, constraints=cons, integrality=np.ones(n), bounds=Bounds(0, 1), options={"time_limit": 3.0, "mip_rel_gap": 1e-4})
        chosen: dict[str, int] = {}
        if res.x is None:
            return chosen
        for j, (ui, oi) in enumerate(var):
            if res.x[j] > 0.5:
                chosen[cand[ui][0].uid] = oi
        return chosen

    def _score_milp(self, o: Option, now: float) -> float:
        return o.total_cost + self.lookahead_usd(o) + (o.end_t - now) * tv_usd_per_s(o.unit)


class GpuOnlyPolicy(BatchPolicy):
    name = "gpu_only"
    allow_quantum = False


def make_policy(name: str) -> Policy:
    if name == "fifo":
        return FifoPolicy()
    if name == "greedy":
        return GreedyPolicy()
    if name == "batch":
        return BatchPolicy()
    if name == "gpu_only":
        return GpuOnlyPolicy()
    raise KeyError(f"unknown policy {name!r}; known: {', '.join(POLICIES)}")
