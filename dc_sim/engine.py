"""The simulation engine: ONE implementation behind the CLI, the API and the visual app.

Time resolution: fixed ticks of ``tick_s`` (default 60 s). Between ticks, discrete EVENTS (task arrivals, task/stage completions,
QPU attempts, node failures and recoveries, power-cap changes, forced calibrations, demand surges) are processed in exact time
order from a heap, up to and including the tick time; resources are released at the exact event time. At each tick the
scheduler runs (decisions take effect after a modelled decision latency), the mass LLM traffic is routed and the site power and
energy are sampled (piecewise constant over the tick). Everything is deterministic: random draws (QPU attempt outcomes) are seeded
from (seed, unit id).

Per tick order: events -> admission control (reject the impossible) -> scheduler (discrete units) -> fluid routing of the mass
traffic on what is left -> power/energy accounting. The facility power cap is enforced by construction: discrete work is only
admitted when the non-elastic power (idle + discrete + QPU) fits under the cap, and the mass traffic is throttled (shed) to fit.
"""

from __future__ import annotations

import copy
import heapq
import json
import math
from typing import Any

import numpy as np

from . import fluid
from .config import clean_json, fmt_time, stable_seed
from .demand import FluidDemand
from .fleet import Fleet, Node, Site
from .placement import Option, Planner
from .scheduler import Decision, Policy, make_policy
from .tasks import Unit, load_taskset, make_units, normalise_task, normalise_taskset, classical_alt

CASE_LIST = ("A", "B", "C", "Q")


class Engine:
    def __init__(self, fleet: Any = None, taskset: Any = None, policy: str | Policy = "batch", seed: int | None = None,
                 tick_s: float | None = None):
        base = Fleet.load(fleet)
        self.fleet = base.fresh()
        self.fleet_spec_src = base.spec
        self.ts = load_taskset(taskset) if taskset is not None else normalise_taskset({"tasks": []})
        self.seed = int(self.ts["seed"] if seed is None else seed)
        self.tick = float(tick_s or self.fleet.eng["tick_s"])
        self.rho = float(self.fleet.eng["rho_slo"])
        self.horizon = float(self.ts["horizon_s"])
        self.start_utc_hour = float(self.ts["start_utc_hour"])
        self.demand = FluidDemand(self.ts["case"], self.ts["demand_scale"], self.fleet.eng, self.start_utc_hour, self.fleet.regions)
        self.P, self.D = self.demand.P, self.demand.D
        self.policy = make_policy(policy) if isinstance(policy, str) else policy
        self.policy.bind(self)
        self.planner: Planner = self.policy.planner
        self._nidx = self.fleet.node_index()
        self.t = 0.0
        self.heap: list = []
        self._seq = 0
        self.units: dict[str, Unit] = {}
        self.units_of: dict[str, list[Unit]] = {}
        self.tasks: dict[str, dict] = {}
        self.task_rec: dict[str, dict] = {}
        self.pending: list[Unit] = []
        self.token: dict[str, int] = {}
        self.hit: dict[str, float] = {s: 1.0 for s in self.fleet.sites}
        self.phi: dict[tuple[str, str], float] = {}
        self.fl_used: dict[str, dict[str, float]] = {s: {} for s in self.fleet.sites}
        self.fl_power_w: dict[str, float] = {s: 0.0 for s in self.fleet.sites}
        self.last_site: dict[str, dict] = {}
        self.decisions: list[dict] = []
        self.recent: list[dict] = []
        self.policy_log: list[tuple[float, str]] = [(0.0, self.policy.name)]
        self.injected: list[dict] = []
        self.surges: list[dict] = []
        self.floor_clamped: dict[str, bool] = {}
        self.cap_violation_w = 0.0
        self.hist: list[list[float]] = []
        sids = list(self.fleet.sites)
        self.acc = {
            "fac_j": {s: 0.0 for s in sids}, "sys_j": {s: 0.0 for s in sids}, "mod_j": {s: 0.0 for s in sids},
            "usd": {s: 0.0 for s in sids}, "peak_fac_w": {s: 0.0 for s in sids}, "peak_ratio": {s: 0.0 for s in sids},
            "req_demand": {c: 0.0 for c in "ABC"}, "req_served": {c: 0.0 for c in "ABC"}, "req_slo": {c: 0.0 for c in "ABC"},
            "worst_tick": {c: 1.0 for c in "ABC"}, "rtt_w": {c: 0.0 for c in "ABC"},
            "shed_power": 0.0, "q_busy_s": 0.0, "n_preempt": 0, "n_fallback": 0, "n_attempt_fail": 0,
            "util_gpu_sum": {s: 0.0 for s in sids}, "ticks": 0,
        }
        self.q_stats: dict[str, dict] = {}
        self._active_surges: list[dict] = []
        self.n_events = 0
        self._load_arrivals(self.ts["tasks"])
        for e in self.ts["events"]:
            self._push(e["t"], "event", e)

    # ==================================================================================================
    # event heap
    # ==================================================================================================
    def _push(self, t: float, kind: str, data: Any) -> None:
        self._seq += 1
        heapq.heappush(self.heap, (float(t), self._seq, kind, data))

    def _load_arrivals(self, tasks: list[dict]) -> None:
        for tk in tasks:
            self.tasks[tk["id"]] = tk
            self._push(tk["arrival_s"], "arrive", tk["id"])

    def inject(self, tasks: list[dict]) -> list[str]:
        """Add tasks at run time (the visual app / API). Arrival defaults to NOW; arrivals in the past are moved to now."""
        ids = []
        base = len(self.tasks)
        out = []
        for i, raw in enumerate(tasks):
            raw = copy.deepcopy(raw)
            raw["arrival_s"] = max(self.t, float(raw.get("arrival_s", self.t)))
            if "id" not in raw or raw["id"] in self.tasks:
                raw["id"] = f"u{base + i + 1:04d}"
                while raw["id"] in self.tasks:
                    raw["id"] += "x"
            if raw.get("deadline_s") is None and "slo_s" not in raw:
                raw["deadline_s"] = None
            tk = normalise_task({k: v for k, v in raw.items() if not (k == "deadline_s" and v is None)}, base + i)
            self.injected.append(copy.deepcopy(tk))
            out.append(tk)
            ids.append(tk["id"])
        self._load_arrivals(out)
        return ids

    def export_taskset(self) -> dict:
        ts = copy.deepcopy(self.ts)
        ts["tasks"] = sorted(ts["tasks"] + copy.deepcopy(self.injected), key=lambda t: (t["arrival_s"], t["id"]))
        return ts

    # ==================================================================================================
    # helpers used by policies
    # ==================================================================================================
    def pue_now(self, site: Site) -> float:
        return self.fleet.pue(site, self.t, self.start_utc_hour)

    def ctx_tb_avail(self, site: Site) -> float:
        return sum(n.ctx_tb for n in site.nodes if n.kind == "ctxmem" and self.t >= n.down_until)

    def ctx_free_tb(self, site_id: str) -> float:
        s = self.fleet.sites[site_id]
        return max(0.0, self.ctx_tb_avail(s) - s.ctx_reserved_tb)

    def site_power(self, site: Site, t: float, pue: float, fl: dict | None = None) -> tuple[float, float, float]:
        """(module W, system W, facility W) of a site with discrete reservations and optional fluid usage ``fl`` (modeq per pool)."""
        mod = sys_ = 0.0
        for kind, pool in site.pools.items():
            used = pool.reserved_duty + (fl.get(kind, 0.0) if fl else 0.0)
            used = min(used, pool.avail)
            sys_ += pool.avail * pool.idle_sys_w + pool.dyn_sys_w * used
            mod += pool.avail * pool.idle_mod_w + pool.dyn_mod_w * used
        for n in site.nodes:
            if n.kind == "ctxmem" and t >= n.down_until:
                sys_ += n.fixed_sys_w
        for n in site.qpus:
            if t >= n.down_until:
                busy = n.qpu.busy_now(t)
                sys_ += n.qpu.busy_w if busy else n.qpu.standby_w
                mod += n.qpu.module_w
        fac = sys_ * (1.0 + self.fleet.net_overhead()) * pue
        return mod, sys_, fac

    def site_base_power_w(self, site: Site, t: float, pue: float) -> float:
        return self.site_power(site, t, pue)[2]

    def power_headroom_w(self, site_id: str) -> float:
        s = self.fleet.sites[site_id]
        return s.cap_now_w - self.site_base_power_w(s, self.t, self.pue_now(s))

    def power_headroom_protected_w(self, site_id: str) -> float:
        return self.power_headroom_w(site_id) - self.fl_power_w.get(site_id, 0.0)

    # ==================================================================================================
    # unit lifecycle
    # ==================================================================================================
    def _on_arrival(self, tid: str) -> None:
        tk = self.tasks[tid]
        us = make_units(tk, self.P, self.D)
        self.units_of[tid] = us
        for u in us:
            self.units[u.uid] = u
        self.task_rec[tid] = {"id": tid, "type": tk["type"], "case": tk["case"], "priority": tk["priority"], "arrival": tk["arrival_s"],
                              "deadline": tk["deadline_s"], "state": "pending", "finish": None, "slo_ok": None, "reason": "",
                              "cost_usd": 0.0, "energy_j": 0.0, "route": None, "sites": [], "n_units": len(us), "wait_s": 0.0}
        u0 = us[0]
        u0.state = "pending"
        u0.ready_t = self.t
        u0.first_pending_t = self.t
        self.pending.append(u0)

    def _release_next(self, u: Unit) -> None:
        us = self.units_of[u.task["id"]]
        if u.idx + 1 < len(us):
            n = us[u.idx + 1]
            n.state = "pending"
            n.ready_t = self.t
            n.first_pending_t = self.t
            n.prev_site = u.node.split("/")[0] if u.node else None
            n.prev_node = u.node
            self.pending.append(n)

    def _finish_task(self, u: Unit, ok_state: str, reason: str = "") -> None:
        rec = self.task_rec[u.task["id"]]
        rec["state"] = ok_state
        rec["finish"] = self.t if ok_state == "done" else None
        rec["reason"] = reason or rec["reason"]
        rec["slo_ok"] = (ok_state == "done" and self.t <= u.deadline + 1e-6)

    def apply_option(self, o: Option) -> None:
        """Commit an option: reserve resources, fix the (seeded) QPU attempt outcomes, schedule the completion event."""
        u, node = o.unit, o.node
        if u in self.pending:
            self.pending.remove(u)
        u.state = "running"
        u.node = node.id
        u.route = o.route
        u.decided_t = self.t
        tok = self.token.get(u.uid, 0) + 1
        self.token[u.uid] = tok
        site = self.fleet.sites[node.site]
        rec = self.task_rec[u.task["id"]]
        if site.id not in rec["sites"]:
            rec["sites"].append(site.id)
        if o.route == "classical":
            m = o.modules
            node.reserved = node.reserved + m
            node.running[u.uid] = {"m": m, "duty": o.duty, "end": o.end_t, "ctx": o.ctx_gb}
            pool = site.pools[node.pool]
            pool.reserved += m
            pool.reserved_duty += m * o.duty
            site.ctx_reserved_tb += o.ctx_gb / 1000.0
            u.start_t, u.end_t = o.start_t, o.end_t
            u.energy_fac_j += o.energy_j
            u.cost_usd += o.cost_usd
            u.transfer_usd += o.transfer_usd
            if node.group is not None:
                self.planner.invalidate_group(node.group)
        else:
            qp = node.qpu
            gate = u.q.get("kind", "gate") == "gate"
            k_att = int(u.q.get("max_attempts", 2))
            rng = np.random.default_rng(stable_seed(self.seed, u.uid, "qatt", u.attempts_used))
            p = o.p_acc or 0.0
            draws = rng.random(k_att)
            succ = [i for i, d in enumerate(draws) if d < p]
            n_att = (succ[0] + 1) if succ else k_att
            u.quantum_fail = not succ
            block = n_att * o.occ_att_s
            s0 = o.slot[0]
            mixed = node.kind == "mixed"
            end = s0 + block + (o.post_s if mixed else 0.0)
            u.start_t = s0 - (o.prep_s if mixed else 0.0)
            u.end_t = end
            qp.queue.append({"uid": u.uid, "start": s0, "end": s0 + block, "wall_end": end})
            qp.free_at = s0 + block
            u.attempts_used += n_att
            u.energy_fac_j += n_att * o.att_energy_j
            u.cost_usd += n_att * o.att_cost_usd + o.transfer_usd
            u.transfer_usd += o.transfer_usd
            self.acc["q_busy_s"] += block
            st = self.q_stats.setdefault(node.id, {"busy_s": 0.0, "jobs": 0, "attempts": 0, "fails": 0})
            st["busy_s"] += block
            st["jobs"] += 1
            st["attempts"] += n_att
            st["fails"] += 1 if u.quantum_fail else 0
            if succ is not None and n_att > 1:
                self.acc["n_attempt_fail"] += n_att - 1
        u.reason = u.reason or ""
        rec["wait_s"] = max(rec["wait_s"], (u.start_t or self.t) - (u.first_pending_t or self.t))
        self._push(u.end_t, "end", (u.uid, tok))

    def _release_resources(self, u: Unit) -> None:
        node = self._nidx.get(u.node) if u.node else None
        if node is None:
            return
        site = self.fleet.sites[node.site]
        if u.route == "classical":
            info = node.running.pop(u.uid, None)
            if info:
                node.reserved = max(0.0, node.reserved - info["m"])
                pool = site.pools[node.pool]
                pool.reserved = max(0.0, pool.reserved - info["m"])
                pool.reserved_duty = max(0.0, pool.reserved_duty - info["m"] * info["duty"])
                site.ctx_reserved_tb = max(0.0, site.ctx_reserved_tb - info["ctx"] / 1000.0)
                if node.group is not None:
                    self.planner.invalidate_group(node.group)
        elif node.qpu is not None:
            node.qpu.queue = [x for x in node.qpu.queue if x["uid"] != u.uid]
            node.qpu.free_at = max([x["end"] for x in node.qpu.queue] + [self.t])

    def _on_end(self, uid: str, tok: int) -> None:
        if self.token.get(uid) != tok:
            return
        u = self.units[uid]
        if u.state != "running":
            return
        rec = self.task_rec[u.task["id"]]
        node = self._nidx[u.node]
        self._release_resources(u)
        if u.route == "quantum":
            node.qpu.jobs_done += 1
            node.qpu.busy_s_total += 0.0
        if u.route == "quantum" and u.quantum_fail:
            alt = classical_alt(u)
            self.acc["n_fallback"] += 1
            u.force_classical = True
            u.fallback_used = True
            u.state = "pending"
            u.ready_t = self.t
            u.first_pending_t = self.t
            u.prev_site, u.prev_node = node.site, node.id
            u.route = None
            u.reason = "quantum attempts failed: classical fallback"
            rec["reason"] = u.reason
            if alt is None:
                u.state = "rejected"
                self._finish_task(u, "failed", "quantum attempts failed and no classical fallback exists at this accuracy")
                self._log(u, "reject", None, "quantum attempts failed and no classical fallback exists at this accuracy")
                return
            self.pending.append(u)
            self._log(u, "fallback", None, f"all {u.q.get('max_attempts', 2)} quantum attempts failed (seeded draw): re-queued as classical")
            return
        u.state = "done"
        rec["cost_usd"] += u.cost_usd
        rec["energy_j"] += u.energy_fac_j
        rec["route"] = "quantum" if (u.route == "quantum" or rec["route"] == "quantum") else "classical"
        if u.is_last:
            rec["finish"] = self.t
            rec["state"] = "done"
            rec["slo_ok"] = self.t <= u.deadline + 1e-6
        else:
            self._release_next(u)

    def _preempt(self, u: Unit, reason: str) -> None:
        if u.state != "running":
            return
        self.token[u.uid] = self.token.get(u.uid, 0) + 1
        self._release_resources(u)
        u.state = "pending"
        u.ready_t = self.t
        u.first_pending_t = self.t
        u.route = None
        u.node = None
        u.reason = reason
        self.acc["n_preempt"] += 1
        self.pending.append(u)
        self._log(u, "preempt", None, reason)

    # ==================================================================================================
    # events
    # ==================================================================================================
    def _on_event(self, e: dict) -> None:
        ty = e["type"]
        fl = self.fleet
        if ty == "site_power_cap":
            s = fl.sites[e["site"]]
            mw = float(e["mw"])
            s.cap_now_w = mw * 1e6
            self._log_sys(f"site {s.id}: power cap set to {mw:g} MW (grid curtailment)")
        elif ty == "node_failure":
            idx = self._nidx
            nid = e.get("node")
            if nid is None:
                s = fl.sites[e["site"]]
                cands = [n for n in s.nodes if (e.get("node_type") in (None, n.type_key)) and self.t >= n.down_until]
                k = int(e.get("count", 1))
                nodes = cands[:k] if e.get("node_type") else [n for n in cands if n.kind == "gpu"][:k]
            else:
                nodes = [idx[nid]]
            dur = float(e.get("duration_s", 3600))
            for n in nodes:
                self._node_down(n, self.t + dur)
            self._log_sys(f"node failure: {', '.join(n.id for n in nodes)} down for {fmt_time(dur)}")
        elif ty == "qpu_calibration":
            idx = self._nidx
            targets = [idx[e["node"]]] if e.get("node") else [n for n in fl.sites[e["site"]].qpus if e.get("node_type") in (None, n.type_key)]
            dur = float(e.get("duration_s", 1800))
            for n in targets:
                n.qpu.extra.append((self.t, self.t + dur))
                for it in list(n.qpu.queue):
                    if it["end"] > self.t and it["start"] < self.t + dur:
                        self._preempt(self.units[it["uid"]], "aborted by unscheduled QPU calibration")
            self._log_sys(f"unscheduled calibration on {', '.join(n.id for n in targets)} for {fmt_time(dur)}")
        elif ty == "demand_surge":
            self._active_surges.append({"t0": self.t, "t1": self.t + float(e.get("duration_s", 3600)), "mult": float(e.get("multiplier", 1.5)),
                                        "cls": e.get("class")})
            self._log_sys(f"demand surge x{float(e.get('multiplier', 1.5)):g} for {fmt_time(float(e.get('duration_s', 3600)))}"
                          + (f" (class {e['class']})" if e.get("class") else ""))

    def _node_down(self, n: Node, until: float) -> None:
        n.down_until = until
        if n.group is not None:
            n.group.down[n.gi] = until
        site = self.fleet.sites[n.site]
        if n.pool:
            site.pools[n.pool].failed += n.modules
        for uid in list(n.running):
            self._preempt(self.units[uid], f"node {n.id} failed")
        if n.qpu is not None:
            for it in list(n.qpu.queue):
                self._preempt(self.units[it["uid"]], f"QPU node {n.id} failed")
        self._push(until, "node_up", n.id)

    def _on_node_up(self, nid: str) -> None:
        n = self._nidx[nid]
        if self.t >= n.down_until - 1e-9:
            site = self.fleet.sites[n.site]
            if n.pool:
                site.pools[n.pool].failed = max(0.0, site.pools[n.pool].failed - n.modules)
            self._log_sys(f"node {nid} back in service")

    def _log_sys(self, msg: str) -> None:
        e = {"t": self.t, "uid": "-", "task": "-", "action": "event", "reason": msg, "node": None, "site": None}
        self.recent.append(e)
        self.decisions.append(e)

    def _log(self, u: Unit, action: str, o: Option | None, reason: str, alts: list | None = None) -> None:
        e = {"t": round(self.t, 1), "uid": u.uid, "task": u.task["id"], "type": u.task["type"], "name": u.name, "case": u.task["case"],
             "priority": u.priority, "action": action, "reason": reason, "policy": self.policy.name,
             "node": o.node.id if o else None, "site": o.node.site if o else None, "route": o.route if o else None,
             "start": round(o.start_t, 1) if o else None, "end": round(o.end_t, 1) if o else None, "deadline": round(u.deadline, 1),
             "cost_usd": round(o.total_cost, 2) if o else None, "energy_j": o.energy_j if o else None,
             "modules": o.modules if o else None, "alts": alts or []}
        self.recent.append(e)
        self.decisions.append(e)

    # ==================================================================================================
    # admission control (shared by all policies)
    # ==================================================================================================
    def _admission(self) -> None:
        for u in list(self.pending):
            st = self.planner.static_check(u, self.policy.allow_quantum)
            rest = self.planner.remaining_min_s(u, self.units_of[u.task["id"]], self.policy.allow_quantum)
            if not st["possible"]:
                why = "; ".join(st["reasons"]) or "no feasible route"
                self._reject(u, f"no feasible route: {why}")
            elif self.t + st["min_dur_s"] + rest > u.deadline + 1e-6:
                self._reject(u, f"SLO cannot be met even on an idle fleet: fastest route needs {fmt_time(st['min_dur_s'] + rest)}, "
                                f"{fmt_time(max(0.0, u.deadline - self.t))} left")

    def _reject(self, u: Unit, why: str) -> None:
        if u in self.pending:
            self.pending.remove(u)
        u.state = "rejected"
        u.reason = why
        for x in self.units_of[u.task["id"]]:
            if x.state in ("waiting", "pending") and x is not u:
                x.state = "rejected"
                if x in self.pending:
                    self.pending.remove(x)
        self._finish_task(u, "rejected", why)
        self._log(u, "reject", None, why)

    # ==================================================================================================
    # per-tick fluid
    # ==================================================================================================
    def _surge_mult(self, cls: str | None = None) -> float:
        m = 1.0
        for s in self._active_surges:
            if s["t0"] <= self.t < s["t1"] and (s["cls"] is None or s["cls"] == cls):
                m *= s["mult"]
        return m

    def _fluid_step(self, dt: float) -> dict[str, dict]:
        t = self.t
        act = [x for x in self._active_surges if x["t0"] <= t < x["t1"]]
        self.demand.surge = math.prod([x["mult"] for x in act if x["cls"] is None])
        self.demand.surge_by_class = {c: math.prod([x["mult"] for x in act if x["cls"] == c]) for c in "ABC"}
        chunks = self.demand.chunks(t)
        sfs = {s.id: fluid.SiteFluid(self, s, t) for s in self.fleet.site_list}
        alloc = self.policy.route_fluid(chunks, sfs) if chunks else {}
        # --- enforce: recompute loads from the allocation and clamp per site to capacity and power cap ---------
        PF = {s: 0.0 for s in sfs}
        DC = {s: 0.0 for s in sfs}
        for (ci, sid), f in alloc.items():
            PF[sid] += f * chunks[ci].prefill_tok_s(sfs[sid].hit)
            DC[sid] += f * chunks[ci].decode_tok_s
        kappa = {}
        for sid, sf in sfs.items():
            kappa[sid] = min(1.0, sf.max_fraction(PF[sid], DC[sid], 0.0, 0.0)) if (PF[sid] > 0 or DC[sid] > 0) else 1.0
        res: dict[str, dict] = {}
        ctx_need = {s: 0.0 for s in sfs}
        for sid, sf in sfs.items():
            pf, dc = PF[sid] * kappa[sid], DC[sid] * kappa[sid]
            a, b, gq = sf.usage(pf, dc)
            used = {"gpu": gq, "lpu": b / (self.D * sf.dc_speed) if sf.dc_speed > 0 else 0.0,
                    "prefill": a / (self.P * sf.pf_speed) if sf.pf_speed > 0 else 0.0}
            res[sid] = {"PF": pf, "DC": dc, "used": used, "sf": sf}
        # --- accounting per class ------------------------------------------------------------------------------
        by_c_dem = {c: 0.0 for c in "ABC"}
        by_c_srv = {c: 0.0 for c in "ABC"}
        by_c_slo = {c: 0.0 for c in "ABC"}
        for ci, ch in enumerate(chunks):
            by_c_dem[ch.cls] += ch.req_rate * dt
        for (ci, sid), f in alloc.items():
            ch = chunks[ci]
            x = f * kappa[sid]
            req = ch.req_rate * dt * x
            by_c_srv[ch.cls] += req
            rtt = self.fleet.rtt(f"region:{ch.region}", sid)
            if rtt <= ch.allowed_rtt_s + 1e-9:
                by_c_slo[ch.cls] += req
            self.acc["rtt_w"][ch.cls] += req * rtt
            ctx_need[sid] += x * ch.ctx_need_tb
        for c in "ABC":
            self.acc["req_demand"][c] += by_c_dem[c]
            self.acc["req_served"][c] += by_c_srv[c]
            self.acc["req_slo"][c] += by_c_slo[c]
            if by_c_dem[c] > 0:
                self.acc["worst_tick"][c] = min(self.acc["worst_tick"][c], by_c_slo[c] / by_c_dem[c])
        self.acc["shed_power"] += sum(1 for sid in sfs if kappa[sid] < 0.999 and sfs[sid].base + sfs[sid].fluid_power_w(PF[sid], DC[sid]) >= sfs[sid].cap - 1)
        # --- context hit rates for the next tick --------------------------------------------------------------
        for sid, sf in sfs.items():
            site = self.fleet.sites[sid]
            free = max(1e-9, self.ctx_free_tb(sid))
            new = 1.0 if ctx_need[sid] <= 1e-9 else min(1.0, free / ctx_need[sid])
            self.hit[sid] = 0.5 * self.hit[sid] + 0.5 * new
        for sid, r in res.items():
            site = self.fleet.sites[sid]
            for kind, pool in site.pools.items():
                avail = max(1e-9, pool.avail - pool.reserved)
                self.phi[(sid, kind)] = min(1.0, r["used"][kind] / avail)
            self.fl_power_w[sid] = r["sf"].fluid_power_w(r["PF"], r["DC"])
            self.fl_used[sid] = r["used"]
        self._chunk_info = {"dem": by_c_dem, "srv": by_c_srv, "slo": by_c_slo}
        return res

    # ==================================================================================================
    # the tick
    # ==================================================================================================
    def _process_events(self) -> None:
        while self.heap and self.heap[0][0] <= self.t + 1e-9:
            te, _, kind, data = heapq.heappop(self.heap)
            saved = self.t
            self.t = te if kind in ("end",) else self.t   # completions are processed at their own time
            if kind == "arrive":
                self._on_arrival(data)
            elif kind == "end":
                self._on_end(*data)
            elif kind == "event":
                self._on_event(data)
            elif kind == "node_up":
                self._on_node_up(data)
            self.t = saved
            self.n_events += 1

    def _enforce_caps(self) -> None:
        """If a cap drop makes the non-elastic load exceed the cap, preempt the lowest-priority discrete GPU work."""
        for site in self.fleet.site_list:
            pue = self.pue_now(site)
            guard = 0
            while self.site_base_power_w(site, self.t, pue) > site.cap_now_w + 1.0 and guard < 10000:
                guard += 1
                running = [self.units[uid] for n in site.nodes for uid in n.running]
                if not running:
                    self.floor_clamped[site.id] = True
                    break
                v = sorted(running, key=lambda x: (x.priority, -x.end_t if x.end_t else 0))[0]
                self._preempt(v, f"preempted: site power cap {site.cap_now_w / 1e6:.1f} MW")

    def step(self) -> dict:
        t = self.t
        dt = self.tick
        self.recent = []
        self._process_events()
        self._enforce_caps()
        self._admission()
        # --- scheduler -----------------------------------------------------------------------------------------
        self.planner.begin_tick(t)
        decisions: list[Decision] = []
        if self.pending:
            decisions = self.policy.schedule(list(self.pending), t)
        for d in decisions:
            u = d.unit
            if d.action == "assign":
                self._log(u, "assign", d.option, d.reason, d.alts)
                u.reason = d.reason
            else:
                u.n_defer += 1
                if u.n_defer == 1 or u.reason != d.reason:
                    self._log(u, "defer", None, d.reason)
                u.reason = d.reason
        # --- fluid + power -------------------------------------------------------------------------------------
        res = self._fluid_step(dt)
        rec: list[float] = [t]
        tot_mod = tot_sys = tot_fac = 0.0
        site_state = {}
        for site in self.fleet.site_list:
            sid = site.id
            pue = self.pue_now(site)
            mod, sys_, fac = self.site_power(site, t, pue, res[sid]["used"])
            if fac > site.cap_now_w + 1.0:
                self.cap_violation_w = max(self.cap_violation_w, fac - site.cap_now_w)
            self.acc["fac_j"][sid] += fac * dt
            self.acc["sys_j"][sid] += sys_ * dt
            self.acc["mod_j"][sid] += mod * dt
            self.acc["usd"][sid] += fac * dt / 3.6e9 * site.price_usd_per_mwh
            self.acc["peak_fac_w"][sid] = max(self.acc["peak_fac_w"][sid], fac)
            self.acc["peak_ratio"][sid] = max(self.acc["peak_ratio"][sid], fac / site.cap_now_w)
            g = site.pools.get("gpu")
            gu = ((g.reserved + res[sid]["used"]["gpu"]) / g.avail) if g and g.avail > 0 else 0.0
            self.acc["util_gpu_sum"][sid] += gu
            site_state[sid] = {"fac_w": fac, "sys_w": sys_, "mod_w": mod, "pue": pue, "gpu_util": gu}
            rec += [fac / 1e6, site.cap_now_w / 1e6, gu]
            tot_fac += fac
        dem = self._chunk_info["dem"]
        slo = self._chunk_info["slo"]
        for c in "ABC":
            rec.append(slo[c] / dem[c] if dem[c] > 0 else 1.0)
        rec += [len(self.pending), sum(1 for u in self.units.values() if u.state == "running"),
                sum(1 for s in self.fleet.site_list for n in s.qpus if n.qpu.busy_now(t))]
        self.hist.append(rec)
        self.acc["ticks"] += 1
        self.last_site = site_state
        self.t = t + dt
        return {"t": self.t, "decisions": [x for x in self.recent]}

    def advance(self, seconds: float) -> None:
        n = int(round(seconds / self.tick))
        for _ in range(max(1, n)):
            if self.t >= self.horizon - 1e-9:
                break
            self.step()

    def run(self) -> dict:
        while self.t < self.horizon - 1e-9:
            self.step()
        return self.metrics()

    @property
    def done(self) -> bool:
        return self.t >= self.horizon - 1e-9

    # ==================================================================================================
    # metrics
    # ==================================================================================================
    def task_outcome(self, rec: dict) -> str:
        """ok | late | rejected | failed | open (unfinished at the horizon counts against the policy)."""
        if rec["state"] == "rejected":
            return "rejected"
        if rec["state"] == "failed":
            return "failed"
        if rec["state"] == "done":
            return "ok" if rec["slo_ok"] else "late"
        # unfinished: use the planned end of running last unit when known
        us = self.units_of.get(rec["id"], [])
        last = us[-1] if us else None
        if last is not None and last.state == "running" and last.end_t is not None and last.end_t <= rec["deadline"] + 1e-6 and all(x.state in ("done", "running") for x in us):
            return "ok"
        return "open"

    def metrics(self) -> dict[str, Any]:
        a = self.acc
        fl = self.fleet
        elapsed = max(self.t, self.tick)
        days = elapsed / 86400.0
        out: dict[str, Any] = {"policy": self.policy.name, "fleet": fl.name, "taskset": self.ts["name"], "seed": self.seed, "case": self.ts["case"],
                               "t_s": self.t, "horizon_s": self.horizon, "tick_s": self.tick}
        # --- users / fluid ---
        users = self.demand.users()
        served = {}
        for c in "ABC":
            d = a["req_demand"][c]
            served[c] = {"demand_req": d, "served_pct": 100.0 * a["req_served"][c] / d if d > 0 else None,
                         "slo_pct": 100.0 * a["req_slo"][c] / d if d > 0 else None,
                         "worst_tick_slo_pct": 100.0 * a["worst_tick"][c] if d > 0 else None,
                         "mean_rtt_ms": 1000.0 * a["rtt_w"][c] / a["req_served"][c] if a["req_served"][c] > 0 else None,
                         "users_served": users.get(c, 0.0) * (a["req_slo"][c] / d) if d > 0 else 0.0, "users": users.get(c, 0.0)}
        out["users"] = served
        # --- discrete tasks ---
        outc: dict[str, dict[str, int]] = {c: {"ok": 0, "late": 0, "rejected": 0, "failed": 0, "open": 0} for c in CASE_LIST}
        wait = []
        for r in self.task_rec.values():
            o = self.task_outcome(r)
            outc[r["case"]][o] += 1
            if r["wait_s"] is not None:
                wait.append(r["wait_s"])
        # tasks that never arrived (arrival after the horizon) are ignored
        tasks = {}
        for c in CASE_LIST:
            n = sum(outc[c].values())
            tasks[c] = {**outc[c], "n": n, "slo_pct": 100.0 * outc[c]["ok"] / n if n else None}
        n_all = sum(tasks[c]["n"] for c in CASE_LIST)
        ok_all = sum(tasks[c]["ok"] for c in CASE_LIST)
        tasks["all"] = {"n": n_all, "ok": ok_all, "slo_pct": 100.0 * ok_all / n_all if n_all else None,
                        **{k: sum(outc[c][k] for c in CASE_LIST) for k in ("late", "rejected", "failed", "open")}}
        out["tasks"] = tasks
        out["task_wait_s"] = {"mean": float(np.mean(wait)) if wait else 0.0, "p95": float(np.percentile(wait, 95)) if wait else 0.0,
                              "max": float(max(wait)) if wait else 0.0}
        # --- headline per case: users served at constraints (mass traffic AND tasks) ---
        case_sets = {"A": ("A",), "B": ("B",), "C": ("C",), "mix": ("A", "B", "C")}
        heads = {}
        for name, cs in case_sets.items():
            act = [c for c in cs if c in self.demand.classes]
            if not act:
                continue
            dem = sum(a["req_demand"][c] for c in act)
            slo_users = min((served[c]["slo_pct"] for c in act if served[c]["slo_pct"] is not None), default=None)   # 100 % of EVERY case
            u_served = sum(served[c]["users_served"] for c in act)
            u_tot = sum(served[c]["users"] for c in act)
            tk = [tasks[c] for c in act + (["Q"] if name == "mix" else [])]
            nt = sum(x["n"] for x in tk)
            tpct = 100.0 * sum(x["ok"] for x in tk) / nt if nt else None
            comp = [x for x in (slo_users, tpct) if x is not None]
            heads[name] = {"users_slo_pct": slo_users, "users_served": u_served, "users_total": u_tot, "tasks_slo_pct": tpct,
                           "n_tasks": nt, "served_pct": min(comp) if comp else None}
        out["case_scores"] = heads
        main = "mix" if "mix" in heads else next(iter(heads), None)
        out["served_pct"] = heads[main]["served_pct"] if main else None
        out["users_slo_pct"] = heads[main]["users_slo_pct"] if main else None
        out["tasks_slo_pct"] = tasks["all"]["slo_pct"]
        # --- energy, power boundaries ---
        fac_j = sum(a["fac_j"].values())
        out["energy"] = {"boundary": "facility = system x (1 + network overhead) x PUE(site, ambient)",
                         "facility_mwh": fac_j / 3.6e9, "system_mwh": sum(a["sys_j"].values()) / 3.6e9,
                         "module_mwh": sum(a["mod_j"].values()) / 3.6e9,
                         "mean_facility_mw": fac_j / max(self.t, 1e-9) / 1e6,
                         "peak_site_facility_mw": {s: a["peak_fac_w"][s] / 1e6 for s in a["peak_fac_w"]},
                         "peak_total_facility_mw": max((r_sum for r_sum in self._total_fac_series()), default=0.0)}
        out["power_cap"] = {"sum_caps_mw": sum(s.cap_w for s in fl.site_list) / 1e6, "grid_total_mw": fl.grid_total_mw,
                            "max_site_ratio": max(a["peak_ratio"].values()) if a["peak_ratio"] else 0.0,
                            "max_exceedance_w": self.cap_violation_w, "floor_clamped_sites": sorted(self.floor_clamped),
                            "never_exceeded": self.cap_violation_w <= 1.0}
        # --- dollars ---
        yrs = float(fl.challenge["amortisation_years"])
        capex = fl.capex_table()["total_usd"]
        energy_usd = sum(a["usd"].values())
        usd_day_energy = energy_usd / days
        usd_day_capex = capex / (yrs * 365.0)
        out["cost"] = {"energy_usd_sim": energy_usd, "energy_usd_per_day": usd_day_energy, "capex_usd": capex,
                       "capex_amortised_usd_per_day": usd_day_capex, "total_usd_per_day": usd_day_energy + usd_day_capex,
                       "five_year_usd": (usd_day_energy + usd_day_capex) * 365.0 * yrs,
                       "note": "dollars per day = energy actually used (extrapolated from the simulated window) + capex amortised over the "
                               f"{yrs:g}-year life; the simulated window is assumed representative"}
        # --- quantum ---
        q_nodes = [n for s in fl.site_list for n in s.qpus]
        qu = {"n_qpu_nodes": len(q_nodes), "busy_s": a["q_busy_s"],
              "utilisation_pct": 100.0 * a["q_busy_s"] / max(1e-9, len(q_nodes) * self.t) if q_nodes else 0.0,
              "fallbacks": a["n_fallback"], "failed_attempts": a["n_attempt_fail"], "preemptions": a["n_preempt"]}
        qd = [u for u in self.units.values() if u.kind == "quantum"]
        qu["units"] = len(qd)
        qu["on_qpu"] = sum(1 for u in qd if u.route == "quantum" and u.state in ("running", "done"))
        qu["classical_alt"] = sum(1 for u in qd if u.route == "classical" or u.fallback_used)
        qu["rejected"] = sum(1 for u in qd if u.state == "rejected")
        qu["energy_on_qpu_mwh"] = sum(u.energy_fac_j for u in qd if u.route == "quantum") / 3.6e9
        qu["per_node"] = {nid: {**st, "util_pct": 100.0 * st["busy_s"] / max(self.t, 1e-9)} for nid, st in self.q_stats.items()}
        out["quantum"] = qu
        out["decisions"] = {"assign": sum(1 for d in self.decisions if d["action"] == "assign"),
                            "defer": sum(1 for d in self.decisions if d["action"] == "defer"),
                            "reject": sum(1 for d in self.decisions if d["action"] == "reject")}
        out["gpu_util_mean"] = {s: a["util_gpu_sum"][s] / max(1, a["ticks"]) for s in a["util_gpu_sum"]}
        return clean_json(out)

    def _total_fac_series(self):
        n = len(self.fleet.sites)
        for r in self.hist:
            yield sum(r[1 + 3 * i] for i in range(n))

    # ==================================================================================================
    # snapshot for the visual app
    # ==================================================================================================
    TYPE_CODE = {"gpu": 0, "lpu": 1, "prefill": 2, "qpu": 3, "annealer": 4, "mixed": 5, "ctxmem": 6}

    def layout(self) -> dict:
        """Static description of the fleet for the front end (node order is the order of the per-tick arrays)."""
        sites = []
        for s in self.fleet.site_list:
            sites.append({"id": s.id, "name": s.name, "region": s.region, "lat": s.lat, "lon": s.lon, "cooling": s.cooling,
                          "cap_mw": s.cap_w / 1e6, "price": s.price_usd_per_mwh,
                          "nodes": [[n.id, self.TYPE_CODE[n.kind], n.type_key, n.modules] for n in s.nodes]})
        return {"sites": sites, "type_names": ["GPU", "LPU", "Prefill card", "QPU", "Annealer", "Mixed GPU+QPU", "Context memory"],
                "node_cfg_labels": {k: v["label"] for k, v in self.fleet.node_cfg.items()}}

    def state(self, nodes: bool = True, recent: int = 40) -> dict[str, Any]:
        t = self.t
        sites = []
        for s in self.fleet.site_list:
            sid = s.id
            st = self.last_site.get(sid, {"fac_w": 0.0, "sys_w": 0.0, "mod_w": 0.0, "pue": self.pue_now(s), "gpu_util": 0.0})
            d = {"id": sid, "power_mw": st["fac_w"] / 1e6, "cap_mw": s.cap_now_w / 1e6, "pue": st["pue"], "gpu_util": st["gpu_util"],
                 "hit": self.hit[sid], "ctx_free_pb": self.ctx_free_tb(sid) / 1000.0,
                 "fluid": {k: v for k, v in self.fl_used[sid].items()},
                 "pools": {k: {"modules": p.modules, "failed": p.failed, "reserved": p.reserved} for k, p in s.pools.items()},
                 "qpu_queue": sum(len([x for x in n.qpu.queue if x["end"] > t]) for n in s.qpus),
                 "running": sum(len(n.running) for n in s.nodes)}
            if nodes:
                arr = []
                for n in s.nodes:
                    flag = 0
                    if t < n.down_until:
                        flag |= 4
                    if n.pool:
                        phi = self.phi.get((sid, n.pool), 0.0)
                        u = min(1.0, (n.reserved + phi * max(0.0, n.modules - n.reserved)) / max(1, n.modules))
                    elif n.kind == "ctxmem":
                        u = 1.0 - (self.ctx_free_tb(sid) / max(1e-9, self.ctx_tb_avail(s)))
                    else:
                        u = 0.0
                    if n.qpu is not None:
                        if n.qpu.busy_now(t):
                            flag |= 1
                            if n.pool is None:
                                u = 1.0
                        if n.qpu.in_calibration(t):
                            flag |= 2
                    arr.append(int(round(min(1.0, max(0.0, u)) * 100)) + 1000 * flag)
                d["nodes"] = arr
            sites.append(d)
        pend = [{"uid": u.uid, "task": u.task["id"], "type": u.task["type"], "name": u.name, "prio": u.priority, "deadline": u.deadline,
                 "reason": u.reason[:200]} for u in self.pending[:60]]
        di = getattr(self, "_chunk_info", None)
        tick_slo = {c: (di["slo"][c] / di["dem"][c] if di and di["dem"][c] > 0 else None) for c in "ABC"} if di else {}
        return clean_json({"t": t, "tick_s": self.tick, "horizon_s": self.horizon, "done": self.done, "policy": self.policy.name,
                           "taskset": self.ts["name"], "sites": sites, "pending": pend, "n_pending": len(self.pending),
                           "recent": self.recent[-recent:] if recent else [], "metrics": self.ui_metrics(), "start_utc_hour": self.start_utc_hour,
                           "n_tasks": len(self.tasks), "n_injected": len(self.injected), "tick_slo": tick_slo,
                           "total_mw": sum(x["power_mw"] for x in sites), "cap_mw": sum(x["cap_mw"] for x in sites),
                           "classes": list(self.demand.classes)})

    def ui_metrics(self) -> dict:
        m = self.metrics()
        return {"served_pct": m["served_pct"], "users": {c: {"slo_pct": v["slo_pct"], "worst": v["worst_tick_slo_pct"], "users": v["users"],
                                                            "users_served": v["users_served"]} for c, v in m["users"].items() if v["slo_pct"] is not None},
                "tasks": m["tasks"]["all"], "tasks_by_case": {c: m["tasks"][c] for c in CASE_LIST}, "energy": m["energy"], "cost": m["cost"],
                "quantum": {k: v for k, v in m["quantum"].items() if k != "per_node"}, "power_cap": m["power_cap"], "decisions": m["decisions"],
                "task_wait_s": m["task_wait_s"]}

    def node_detail(self, nid: str) -> dict:
        n = self._nidx[nid]
        run = [{"uid": uid, "task": self.units[uid].task["id"], "name": self.units[uid].name, "modules": v["m"], "end": v["end"]} for uid, v in n.running.items()]
        q = []
        if n.qpu is not None:
            q = [{"uid": x["uid"], "start": x["start"], "end": x["end"]} for x in n.qpu.queue if x["end"] > self.t]
        out = {"id": n.id, "type": n.type_key, "kind": n.kind, "modules": n.modules, "reserved": n.reserved, "running": run[:12], "n_running": len(run),
               "down_until": n.down_until if n.down_until > self.t else None, "queue": q}
        if n.qpu is not None:
            out["qpu"] = {"label": n.qpu.label, "busy_kw": n.qpu.busy_w / 1e3, "standby_kw": n.qpu.standby_w / 1e3, "calibrating": n.qpu.in_calibration(self.t),
                          "next_windows": [list(w) for w in n.qpu.cal_windows(self.t, self.t + 86400)][:3], "jobs_done": n.qpu.jobs_done}
        return clean_json(out)

    def set_policy(self, name: str) -> None:
        """Switch the scheduling policy mid-run (the visual app). Running work stays; the new policy decides from the next tick."""
        pol = make_policy(name)
        pol.bind(self)
        self.policy = pol
        self.planner = pol.planner
        self.policy_log.append((self.t, name))

    def unit_table(self) -> list[dict]:
        rows = []
        for u in self.units.values():
            rows.append({"uid": u.uid, "task": u.task["id"], "type": u.task["type"], "name": u.name, "case": u.task["case"], "prio": u.priority,
                         "arrival": u.task["arrival_s"], "deadline": u.deadline, "state": u.state, "node": u.node, "route": u.route,
                         "start": u.start_t, "end": u.end_t, "cost_usd": u.cost_usd, "energy_kwh": u.energy_fac_j / 3.6e6, "reason": u.reason})
        return clean_json(rows)
