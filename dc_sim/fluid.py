"""Site-level fluid capacity model and the three fluid-routing algorithms (first-fit, greedy, LP).

Capacity units are GPU-module-equivalents (``modeq``) at 100 % utilisation. A site has up to three pools: GPU modules (both
phases), LPU modules (decode only, ``decode_speed`` times a GPU module) and prefill-card modules (prefill only). The mass LLM
traffic of a (class, region) chunk adds ``PF/P + DC/D`` modeq; prefill goes to prefill cards first, decode to LPUs first, the
rest to GPU modules. Power is linear in busy module-equivalents; the facility cap constrains the sum (throttling = shedding).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import linprog


def _solve_x(pts: list[float], vals: list[float], limit: float) -> float:
    """Largest x in [0,1] with piecewise-linear nondecreasing f(x) <= limit given f at sorted breakpoints."""
    if vals[0] > limit + 1e-9:
        return 0.0
    for i in range(1, len(pts)):
        if vals[i] > limit + 1e-9:
            x0, x1, y0, y1 = pts[i - 1], pts[i], vals[i - 1], vals[i]
            return x0 + (limit - y0) / (y1 - y0) * (x1 - x0) if y1 > y0 else x0
    return 1.0


class SiteFluid:
    """Capacity and power state of one site for the current tick, with demand accumulated by a routing algorithm."""

    def __init__(self, eng: Any, site: Any, t: float):
        fl = eng.fleet
        net = fl.net_overhead()
        self.site = site
        self.pue = fl.pue(site, t, eng.start_utc_hour)
        self.k = (1.0 + net) * self.pue
        self.cap = site.cap_now_w
        g, lp, pc = site.pools.get("gpu"), site.pools.get("lpu"), site.pools.get("prefill")
        rho, P, D = eng.rho, eng.P, eng.D
        self.P, self.D, self.rho = P, D, rho
        self.mg = max(0.0, g.avail - g.reserved) if g else 0.0
        self.ml = max(0.0, lp.avail - lp.reserved) if lp else 0.0
        self.mc = max(0.0, pc.avail - pc.reserved) if pc else 0.0
        self.pf_speed = pc.prefill_speed if pc else 0.0
        self.dc_speed = lp.decode_speed if lp else 0.0
        self.capPC = rho * self.mc * self.pf_speed * P          # prefill tokens/s on cards
        self.capLPU = rho * self.ml * self.dc_speed * D         # decode tokens/s on LPUs
        self.capG = rho * self.mg                               # GPU modeq
        self.dynG = g.dyn_sys_w * self.k if g else 0.0          # facility watts per busy modeq
        self.dynC = pc.dyn_sys_w * self.k if pc else 0.0
        self.dynL = lp.dyn_sys_w * self.k if lp else 0.0
        self.base = eng.site_base_power_w(site, t, self.pue)
        self.price = site.price_usd_per_mwh
        self.hit = eng.hit.get(site.id, 1.0)
        self.PF = 0.0
        self.DC = 0.0
        self.ctx_need_tb = 0.0

    # --- usage / power ----------------------------------------------------------------------------------
    def usage(self, PF: float, DC: float) -> tuple[float, float, float]:
        """(prefill tokens/s on cards, decode tokens/s on LPUs, GPU modeq) for loads PF, DC."""
        a = min(PF, self.capPC)
        b = min(DC, self.capLPU)
        gq = (PF - a) / self.P + (DC - b) / self.D
        return a, b, gq

    def fluid_power_w(self, PF: float, DC: float) -> float:
        a, b, gq = self.usage(PF, DC)
        card = a / (self.P * self.pf_speed) if self.pf_speed > 0 else 0.0
        lpu = b / (self.D * self.dc_speed) if self.dc_speed > 0 else 0.0
        return self.dynG * gq + self.dynC * card + self.dynL * lpu

    def max_fraction(self, dPF: float, dDC: float, pf0: float | None = None, dc0: float | None = None) -> float:
        """Largest x in [0,1] such that adding x*(dPF, dDC) to the current loads respects pool capacity and the power cap."""
        PF0 = self.PF if pf0 is None else pf0
        DC0 = self.DC if dc0 is None else dc0
        if dPF <= 0 and dDC <= 0:
            return 1.0
        pts = {0.0, 1.0}
        if dPF > 0:
            x = (self.capPC - PF0) / dPF
            if 0 < x < 1:
                pts.add(x)
        if dDC > 0:
            x = (self.capLPU - DC0) / dDC
            if 0 < x < 1:
                pts.add(x)
        xs = sorted(pts)
        gq = [self.usage(PF0 + x * dPF, DC0 + x * dDC)[2] for x in xs]
        pw = [self.base + self.fluid_power_w(PF0 + x * dPF, DC0 + x * dDC) for x in xs]
        x1 = _solve_x(xs, gq, self.capG)
        x2 = _solve_x(xs, pw, self.cap)
        return max(0.0, min(x1, x2))

    def add(self, x: float, dPF: float, dDC: float, ctx_tb: float = 0.0) -> None:
        self.PF += x * dPF
        self.DC += x * dDC
        self.ctx_need_tb += x * ctx_tb


# ---------------------------------------------------------------------------------------------------------------
def _chunk_site_pf(ch: Any, sf: SiteFluid) -> float:
    return ch.prefill_tok_s(sf.hit)


def route_first_fit(eng: Any, chunks: list, sfs: dict[str, SiteFluid]) -> dict[tuple[int, str], float]:
    """FIFO / first-fit: chunks in arrival order (class, region); sites in the user's home region first, then in
    configuration order; no latency or cost awareness beyond that, so overflow can land on a site too far for the SLO."""
    alloc: dict[tuple[int, str], float] = {}
    order_all = list(sfs)
    for ci, ch in enumerate(chunks):
        left = 1.0
        order = [s for s in order_all if sfs[s].site.region == ch.region] + [s for s in order_all if sfs[s].site.region != ch.region]
        for sid in order:
            if left <= 1e-9:
                break
            sf = sfs[sid]
            x = sf.max_fraction(ch.prefill_tok_s(sf.hit), ch.decode_tok_s)
            take = min(left, x)
            if take > 1e-9:
                alloc[(ci, sid)] = take
                sf.add(take, ch.prefill_tok_s(sf.hit), ch.decode_tok_s, ch.ctx_need_tb)
                left -= take
    return alloc


def route_greedy(eng: Any, chunks: list, sfs: dict[str, SiteFluid]) -> dict[tuple[int, str], float]:
    """Cost/latency-aware greedy: chunks with the tightest RTT allowance first; each takes the cheapest RTT-feasible sites
    (marginal energy price per module-equivalent) until its demand is placed."""
    alloc: dict[tuple[int, str], float] = {}
    fl = eng.fleet
    order = sorted(range(len(chunks)), key=lambda i: (chunks[i].allowed_rtt_s, -chunks[i].weight, i))
    for ci in order:
        ch = chunks[ci]
        feas = [s for s in sfs if fl.rtt(f"region:{ch.region}", s) <= ch.allowed_rtt_s]
        feas.sort(key=lambda s: (sfs[s].dynG * sfs[s].price, fl.rtt(f"region:{ch.region}", s)))
        left = 1.0
        for sid in feas:
            if left <= 1e-9:
                break
            sf = sfs[sid]
            x = sf.max_fraction(ch.prefill_tok_s(sf.hit), ch.decode_tok_s)
            take = min(left, x)
            if take > 1e-9:
                alloc[(ci, sid)] = alloc.get((ci, sid), 0.0) + take
                sf.add(take, ch.prefill_tok_s(sf.hit), ch.decode_tok_s, ch.ctx_need_tb)
                left -= take
    return alloc


def route_lp(eng: Any, chunks: list, sfs: dict[str, SiteFluid]) -> dict[tuple[int, str], float]:
    """Joint LP over all (chunk, site) fractions: maximise weighted served demand within RTT limits, then minimise the
    marginal energy cost, subject to pool capacity and the facility power cap of every site."""
    fl = eng.fleet
    sids = list(sfs)
    pairs = [(ci, s) for ci, ch in enumerate(chunks) for s in sids if fl.rtt(f"region:{ch.region}", s) <= ch.allowed_rtt_s]
    if not pairs:
        return {}
    nP, nS = len(pairs), len(sids)
    sidx = {s: i for i, s in enumerate(sids)}
    cls_list = sorted({ch.cls for ch in chunks})
    nv = nP + 2 * nS + 1     # f_pairs, a_s (prefill modeq on cards), b_s (decode modeq on LPUs), t (min served share over classes)
    it = nv - 1
    P, D = eng.P, eng.D
    work = [ch.prefill_tok_s(1.0) / P + ch.decode_tok_s / D for ch in chunks]
    tot_req = {c: sum(ch.req_rate for ch in chunks if ch.cls == c) or 1.0 for c in cls_list}
    share = [ch.req_rate / tot_req[ch.cls] for ch in chunks]
    price_max = max((sf.dynG * sf.price * w for sf in sfs.values() for w in work), default=1.0) or 1.0
    c = np.zeros(nv)
    c[it] = -1000.0                      # first: maximise the worst class's served share ("serve 100% of every case")
    for j, (ci, s) in enumerate(pairs):
        sf = sfs[s]
        # then: maximise the weighted served shares, then (tiny) minimise the energy price of the work
        c[j] = -chunks[ci].weight * share[ci] + 1e-4 * work[ci] * sf.dynG * sf.price / price_max
    A, b = [], []
    for ci in range(len(chunks)):
        row = np.zeros(nv)
        for j, (cj, s) in enumerate(pairs):
            if cj == ci:
                row[j] = 1.0
        if row.any():
            A.append(row)
            b.append(1.0)
    for cn in cls_list:
        row = np.zeros(nv)
        row[it] = 1.0
        for j, (ci, s) in enumerate(pairs):
            if chunks[ci].cls == cn:
                row[j] = -share[ci]
        A.append(row)
        b.append(0.0)
    for s in sids:
        sf = sfs[s]
        si = sidx[s]
        pf = np.zeros(nv)
        dc = np.zeros(nv)
        for j, (ci, ss) in enumerate(pairs):
            if ss == s:
                pf[j] = chunks[ci].prefill_tok_s(sf.hit) / P
                dc[j] = chunks[ci].decode_tok_s / D
        ia, ib = nP + si, nP + nS + si
        # a <= prefill modeq routed here ; a <= card capacity (modeq of prefill work the cards can absorb)
        row = -pf.copy(); row[ia] = 1.0; A.append(row); b.append(0.0)
        row = np.zeros(nv); row[ia] = 1.0; A.append(row); b.append(sf.capPC / P)
        row = -dc.copy(); row[ib] = 1.0; A.append(row); b.append(0.0)
        row = np.zeros(nv); row[ib] = 1.0; A.append(row); b.append(sf.capLPU / D)
        # GPU modeq: (pf - a) + (dc - b) <= capG
        row = pf + dc; row[ia] = -1.0; row[ib] = -1.0; A.append(row); b.append(sf.capG)
        # power: base + dynG*gq + dynC*a/pf_speed + dynL*b/dc_speed <= cap   (all in modeq)
        row = sf.dynG * (pf + dc)
        row[ia] = -sf.dynG + (sf.dynC / sf.pf_speed if sf.pf_speed > 0 else 0.0)
        row[ib] = -sf.dynG + (sf.dynL / sf.dc_speed if sf.dc_speed > 0 else 0.0)
        A.append(row); b.append(max(0.0, sf.cap - sf.base))
        # cards / LPUs are cheaper per unit of work than GPU modules: a tiny reward for using them
        if sf.pf_speed > 0:
            c[ia] -= 1e-7
        if sf.dc_speed > 0:
            c[ib] -= 1e-7
    bounds = [(0, 1)] * nP + [(0, None)] * (2 * nS) + [(0, 1)]
    res = linprog(c, A_ub=np.array(A), b_ub=np.array(b), bounds=bounds, method="highs")
    if not res.success:
        return route_greedy(eng, chunks, sfs)
    alloc = {}
    for j, (ci, s) in enumerate(pairs):
        x = float(res.x[j])
        if x > 1e-9:
            alloc[(ci, s)] = x
            sfs[s].add(x, chunks[ci].prefill_tok_s(sfs[s].hit), chunks[ci].decode_tok_s, chunks[ci].ctx_need_tb)
    return alloc
