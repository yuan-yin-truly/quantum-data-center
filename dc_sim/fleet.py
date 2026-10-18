"""Fleet model: 6 Earth sites, their cooling, power caps, and nodes (GPU / LPU / prefill racks, QPUs, mixed nodes, context memory).

Boundaries (stated once, used everywhere): ``module`` = accelerator modules (+ QPU module apparatus), ``system`` = complete
servers/QPU systems (module x server overhead; QPU: cryostat wall power, control, host), ``facility`` = system x (1 + network
overhead) x PUE(site, ambient). Site power caps are FACILITY power. All energy and cap statements use the facility boundary
unless labelled otherwise.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field

import numpy as np
from pathlib import Path
from typing import Any

from . import qfeas
from .config import FLEET_FORMAT, DATA, assumptions, clean_json, deep_merge, rtt_s

POOL_OF_KIND = {"gpu": "gpu", "mixed": "gpu", "lpu": "lpu", "prefill": "prefill"}


@dataclass
class QpuState:
    """Runtime state and static power of the QPU part of a node."""
    kind: str                       # gate | annealer
    arch: str | None
    annealer: str | None
    label: str
    busy_w: float
    standby_w: float
    module_w: float
    queue_max: int
    cal_interval_s: float
    cal_duration_s: float
    cal_offset_s: float
    n_qubits: int = 0
    queue: list = field(default_factory=list)       # committed items: dict(unit, start, end)
    extra: list = field(default_factory=list)       # unscheduled calibration windows (start, end)
    free_at: float = 0.0
    busy_s_total: float = 0.0
    jobs_done: int = 0

    def cal_windows(self, t_from: float, t_to: float) -> list[tuple[float, float]]:
        """Calibration windows overlapping [t_from, t_to]; window k starts at offset + k * interval."""
        out = []
        if self.cal_interval_s > 0:
            k = max(0, int(math.floor((t_from - self.cal_offset_s - self.cal_duration_s) / self.cal_interval_s)))
            while True:
                s = self.cal_offset_s + k * self.cal_interval_s
                if s > t_to:
                    break
                if s + self.cal_duration_s >= t_from:
                    out.append((s, s + self.cal_duration_s))
                k += 1
        out += [w for w in self.extra if w[1] >= t_from and w[0] <= t_to]
        return out

    def in_calibration(self, t: float) -> bool:
        return any(a <= t < b for a, b in self.cal_windows(t, t))

    def earliest_slot(self, ready_t: float, dur: float, down_until: float = 0.0) -> float | None:
        """Earliest start >= ready_t, after the committed queue, outside calibration windows, with [start, start+dur] not
        straddling a window. None if the job can never fit between two windows."""
        t = max(ready_t, self.free_at, down_until)
        if self.cal_interval_s > 0 and dur > self.cal_interval_s - self.cal_duration_s:
            return None
        for _ in range(64):
            moved = False
            for a, b in self.cal_windows(t, t + dur):
                if t < b and t + dur > a:
                    t = b
                    moved = True
            if not moved:
                return t
        return None

    def busy_now(self, t: float) -> bool:
        return any(q["start"] <= t < q["end"] for q in self.queue)


@dataclass
class Node:
    id: str
    site: str
    type_key: str
    kind: str                       # gpu | lpu | prefill | qpu | annealer | mixed | ctxmem
    modules: int = 0
    prefill_speed: float = 0.0
    decode_speed: float = 0.0
    idle_sys_w: float = 0.0         # per module, system boundary
    dyn_sys_w: float = 0.0
    idle_mod_w: float = 0.0         # per module, module boundary
    dyn_mod_w: float = 0.0
    capex_usd: float = 0.0
    ctx_tb: float = 0.0
    fixed_sys_w: float = 0.0        # ctxmem pools
    link_us: float | None = None
    qpu: QpuState | None = None
    # runtime
    running: dict = field(default_factory=dict)     # unit id -> dict(m, duty, end)
    down_until: float = 0.0
    group: Any = None               # NodeGroup (vectorised reservations)
    gi: int = 0

    @property
    def reserved(self) -> float:
        """Modules reserved by discrete tasks (stored in the group array for vectorised candidate search)."""
        return float(self.group.res[self.gi]) if self.group is not None else 0.0

    @reserved.setter
    def reserved(self, v: float) -> None:
        if self.group is not None:
            self.group.res[self.gi] = v

    @property
    def pool(self) -> str | None:
        return POOL_OF_KIND.get(self.kind)

    @property
    def has_gpu(self) -> bool:
        return self.kind in ("gpu", "mixed")

    @property
    def has_qpu(self) -> bool:
        return self.qpu is not None

    def usable_modules(self, t: float) -> int:
        return 0 if t < self.down_until else self.modules

    def peak_sys_w(self) -> float:
        w = self.modules * (self.idle_sys_w + self.dyn_sys_w) + self.fixed_sys_w
        if self.qpu:
            w += self.qpu.busy_w
        return w

    def idle_sys_power_w(self) -> float:
        w = self.modules * self.idle_sys_w + self.fixed_sys_w
        if self.qpu:
            w += self.qpu.standby_w
        return w


class NodeGroup:
    """All nodes of one type at one site (identical hardware): arrays for fast best-fit search."""

    def __init__(self, site: str, type_key: str, nodes: list[Node]):
        self.site, self.type_key, self.nodes = site, type_key, nodes
        self.res = np.zeros(len(nodes))
        self.mod = np.array([n.modules for n in nodes], dtype=float)
        self.down = np.zeros(len(nodes))           # down_until
        for i, n in enumerate(nodes):
            n.group, n.gi = self, i

    def free(self, t: float, fluid_phi: float = 0.0) -> np.ndarray:
        """Modules free for a new discrete task, after the share the fluid traffic is estimated to use."""
        f = (self.mod - self.res) * (1.0 - fluid_phi)
        return np.where(self.down > t, 0.0, f)


@dataclass
class Pool:
    kind: str
    modules: float = 0.0
    failed: float = 0.0
    reserved: float = 0.0
    reserved_duty: float = 0.0
    idle_sys_w: float = 0.0
    dyn_sys_w: float = 0.0
    idle_mod_w: float = 0.0
    dyn_mod_w: float = 0.0
    prefill_speed: float = 0.0
    decode_speed: float = 0.0

    @property
    def avail(self) -> float:
        return max(0.0, self.modules - self.failed)


@dataclass
class Site:
    id: str
    name: str
    region: str
    lat: float
    lon: float
    utc_offset: float
    cap_w: float
    cooling: str
    ambient_mean_c: float
    ambient_amp_c: float
    price_usd_per_mwh: float
    wan_gbps: float
    nodes: list[Node] = field(default_factory=list)
    pools: dict[str, Pool] = field(default_factory=dict)
    ctx_tb_total: float = 0.0
    ctx_reserved_tb: float = 0.0
    cap_now_w: float = 0.0
    building_capex_usd: float = 0.0
    groups: dict = field(default_factory=dict)        # type_key -> NodeGroup (modules-bearing nodes)
    qpus: list = field(default_factory=list)          # nodes with a QPU
    spec: dict = field(default_factory=dict)

    def ambient_c(self, t_s: float, start_utc_hour: float = 0.0) -> float:
        local_h = (start_utc_hour + t_s / 3600.0 + self.utc_offset) % 24.0
        return self.ambient_mean_c + self.ambient_amp_c * math.cos(2 * math.pi * (local_h - 15.0) / 24.0)


class Fleet:
    """Immutable description + factory for runtime copies. Runtime state lives on Node/Site/Pool objects of the copy."""

    def __init__(self, spec: dict[str, Any]):
        self.spec = copy.deepcopy(spec)
        a = assumptions()
        self.A = a
        self.name = spec.get("name", "fleet")
        self.cooling = deep_merge(a["cooling"], spec.get("cooling_overrides"))
        self.node_cfg = deep_merge({k: v for k, v in a["node_types"].items() if not k.startswith("_")}, spec.get("node_types"))
        self.eng = deep_merge(a["engine"], spec.get("engine"))
        self.challenge = deep_merge(a["challenge"], spec.get("challenge"))
        self.regions = {k: v for k, v in deep_merge(a["regions"], spec.get("regions")).items() if not k.startswith("_")}
        self.grid_total_mw = float(spec.get("grid_total_mw", self.challenge["grid_total_mw"]))
        self.gpu = qfeas.gpu_module()
        self.sites: dict[str, Site] = {}
        self._build()
        self._rtt_cache: dict[tuple[str, str], float] = {}

    # ----------------------------------------------------------------------------------------------------------
    def _make_nodes(self, site: Site, counts: dict[str, int]) -> None:
        cool = self.cooling[site.cooling]
        g = self.gpu
        mod_sys_peak_kw = g["tdp_w"] * g["overhead"] / 1000.0
        for tkey, n in counts.items():
            if n <= 0:
                continue
            if tkey not in self.node_cfg:
                raise KeyError(f"unknown node type {tkey!r}; known: {', '.join(self.node_cfg)}")
            c = self.node_cfg[tkey]
            kind = c["kind"]
            for i in range(int(n)):
                nid = f"{site.id}/{tkey}/{i:03d}"
                node = Node(id=nid, site=site.id, type_key=tkey, kind=kind)
                if kind in ("gpu", "lpu", "prefill", "mixed"):
                    per_mod_kw = mod_sys_peak_kw * c["power_scale"]
                    node.modules = max(1, min(int(c["modules_max"]), int(math.floor(cool["rack_kw_limit"] / per_mod_kw))))
                    node.prefill_speed, node.decode_speed = c["prefill_speed"], c["decode_speed"]
                    node.idle_mod_w = g["idle_w"] * c["power_scale"]
                    node.dyn_mod_w = (g["tdp_w"] - g["idle_w"]) * c["power_scale"]
                    node.idle_sys_w = node.idle_mod_w * g["overhead"]
                    node.dyn_sys_w = node.dyn_mod_w * g["overhead"]
                    node.capex_usd = node.modules * c["capex_per_module_usd"]
                if kind == "ctxmem":
                    node.ctx_tb = float(c["capacity_tb"])
                    node.fixed_sys_w = float(c["system_power_w"])
                    node.capex_usd = float(c["capex_usd"])
                if kind in ("qpu", "mixed", "annealer"):
                    prof = qfeas.qpu_profile(c.get("architecture"), c.get("annealer"))
                    cal = c.get("calibration", {"interval_s": 0, "duration_s": 0})
                    # stagger calibration windows deterministically across nodes of the same type
                    off = (i * 0.37 + (hash_site(site.id) % 100) / 100.0) % 1.0 * cal["interval_s"] if cal["interval_s"] else 0.0
                    node.qpu = QpuState(kind="annealer" if kind == "annealer" else "gate", arch=c.get("architecture"),
                                        annealer=c.get("annealer"), label=prof["label"], busy_w=prof["busy_w"],
                                        standby_w=prof["standby_w"], module_w=prof["module_w"], queue_max=int(c.get("queue_max", 8)),
                                        cal_interval_s=float(cal["interval_s"]), cal_duration_s=float(cal["duration_s"]),
                                        cal_offset_s=off, n_qubits=int(prof["n_qubits"]))
                    node.capex_usd += float(c["capex_usd"]) if kind != "mixed" else float(c["capex_usd"])
                    node.link_us = c.get("link_us")
                site.nodes.append(node)

    def _build(self) -> None:
        for s in self.spec["sites"]:
            cool = self.cooling[s["cooling"]]
            site = Site(id=s["id"], name=s.get("name", s["id"]), region=s["region"], lat=float(s["lat"]), lon=float(s["lon"]),
                        utc_offset=float(s.get("utc_offset", self.regions[s["region"]]["utc_offset"])),
                        cap_w=float(s["power_cap_mw"]) * 1e6, cooling=s["cooling"],
                        ambient_mean_c=float(s.get("ambient_c_mean", 15)), ambient_amp_c=float(s.get("ambient_c_amp", 6)),
                        price_usd_per_mwh=float(s.get("energy_usd_per_mwh", 70)), wan_gbps=float(s.get("wan_gbps", 800)), spec=s)
            site.cap_now_w = site.cap_w
            site.building_capex_usd = site.cap_w / 1000.0 * cool["capex_usd_per_kw_it"]
            self._make_nodes(site, s.get("nodes", {}))
            for kind in ("gpu", "lpu", "prefill"):
                nodes = [n for n in site.nodes if n.pool == kind]
                if not nodes:
                    continue
                m = sum(n.modules for n in nodes)
                ref = nodes[0]
                site.pools[kind] = Pool(kind=kind, modules=m, idle_sys_w=ref.idle_sys_w, dyn_sys_w=ref.dyn_sys_w,
                                        idle_mod_w=ref.idle_mod_w, dyn_mod_w=ref.dyn_mod_w, prefill_speed=ref.prefill_speed,
                                        decode_speed=ref.decode_speed)
            site.ctx_tb_total = sum(n.ctx_tb for n in site.nodes)
            for tkey in dict.fromkeys(n.type_key for n in site.nodes):
                ns = [n for n in site.nodes if n.type_key == tkey]
                if ns[0].modules > 0:
                    site.groups[tkey] = NodeGroup(site.id, tkey, ns)
            site.qpus = [n for n in site.nodes if n.qpu is not None]
            self.sites[site.id] = site

    # ----------------------------------------------------------------------------------------------------------
    @classmethod
    def load(cls, path_or_dict: str | Path | dict | "Fleet" | None = None) -> "Fleet":
        if isinstance(path_or_dict, Fleet):
            return path_or_dict
        if path_or_dict is None:
            path_or_dict = DATA / "fleet_default.json"
        if isinstance(path_or_dict, dict):
            spec = path_or_dict
        else:
            p = Path(path_or_dict)
            if not p.is_file() and (DATA / str(path_or_dict)).is_file():
                p = DATA / str(path_or_dict)
            if not p.is_file() and (DATA / f"{path_or_dict}.json").is_file():
                p = DATA / f"{path_or_dict}.json"
            spec = json.loads(p.read_text(encoding="utf-8"))
        if spec.get("format", FLEET_FORMAT) != FLEET_FORMAT:
            raise ValueError(f"unsupported fleet format {spec.get('format')!r}")
        return cls(spec)

    def fresh(self) -> "Fleet":
        """A new runtime copy (all dynamic state reset)."""
        return Fleet(self.spec)

    def to_dict(self) -> dict:
        return copy.deepcopy(self.spec)

    # ----------------------------------------------------------------------------------------------------------
    @property
    def site_list(self) -> list[Site]:
        return list(self.sites.values())

    def all_nodes(self) -> list[Node]:
        return [n for s in self.site_list for n in s.nodes]

    def node_index(self) -> dict[str, Node]:
        return {n.id: n for n in self.all_nodes()}

    def pue(self, site: Site, t_s: float, start_utc_hour: float = 0.0) -> float:
        c = self.cooling[site.cooling]
        return c["pue_base"] + c["pue_per_k"] * max(0.0, site.ambient_c(t_s, start_utc_hour) - c["free_cooling_c"])

    def net_overhead(self) -> float:
        return float(self.eng["network_overhead_fraction"])

    def rtt(self, a: str, b: str) -> float:
        """Round-trip time in seconds between two sites or between a user region and a site (``region:<name>``)."""
        key = (a, b)
        if key in self._rtt_cache:
            return self._rtt_cache[key]

        def pos(x: str):
            if x.startswith("region:"):
                r = self.regions[x[7:]]
                return r["lat"], r["lon"]
            s = self.sites[x]
            return s.lat, s.lon
        if a == b:
            v = 0.0002
        else:
            la, lo = pos(a)
            lb, lob = pos(b)
            v = rtt_s(la, lo, lb, lob)
        self._rtt_cache[key] = v
        self._rtt_cache[(b, a)] = v
        return v

    def transfer_time_s(self, data_gb: float, src: str, dst: str) -> float:
        """Seconds to move ``data_gb`` between a region/site and a site. Same node-site: LAN; otherwise limited by the
        task's edge bandwidth and the destination site's WAN capacity; plus one RTT."""
        if data_gb <= 0:
            return 0.0
        if src == dst:
            return data_gb * 8.0 / float(self.eng["lan_gbps"])
        bw = min(float(self.eng["task_edge_gbps"]), self.sites[dst].wan_gbps if dst in self.sites else 1e9)
        if src in self.sites:
            bw = min(bw, self.sites[src].wan_gbps)
        return data_gb * 8.0 / bw + self.rtt(src, dst)

    def transfer_usd(self, data_gb: float, src: str, dst: str) -> float:
        if src == dst or data_gb <= 0:
            return 0.0
        return data_gb * float(self.eng["wan_usd_per_gb"])

    # ----------------------------------------------------------------------------------------------------------
    def capex_table(self) -> dict[str, Any]:
        rows = {}
        total = 0.0
        for s in self.site_list:
            by = {}
            for n in s.nodes:
                by[n.type_key] = by.get(n.type_key, 0.0) + n.capex_usd
            by["building+cooling"] = s.building_capex_usd
            rows[s.id] = by
            total += sum(by.values())
        return {"by_site": rows, "total_usd": total}

    def peak_facility_w(self, site: Site, t_s: float = 43200.0) -> float:
        """Facility power if every node ran at 100 % (all QPUs busy) at the site's PUE at time t_s."""
        sys_w = sum(n.peak_sys_w() for n in site.nodes)
        return sys_w * (1 + self.net_overhead()) * self.fleet_pue_max(site)

    def fleet_pue_max(self, site: Site) -> float:
        c = self.cooling[site.cooling]
        return c["pue_base"] + c["pue_per_k"] * max(0.0, site.ambient_mean_c + site.ambient_amp_c - c["free_cooling_c"])

    def idle_facility_w(self, site: Site, t_s: float = 0.0) -> float:
        sys_w = sum(n.idle_sys_power_w() for n in site.nodes)
        return sys_w * (1 + self.net_overhead()) * self.pue(site, t_s)

    def summary(self) -> dict[str, Any]:
        rows = []
        for s in self.site_list:
            counts: dict[str, int] = {}
            for n in s.nodes:
                counts[n.type_key] = counts.get(n.type_key, 0) + 1
            rows.append({"id": s.id, "name": s.name, "region": s.region, "cooling": s.cooling, "cap_mw": s.cap_w / 1e6,
                         "peak_facility_mw": self.peak_facility_w(s) / 1e6, "idle_facility_mw": self.idle_facility_w(s) / 1e6,
                         "nodes": counts, "gpu_modules": s.pools["gpu"].modules if "gpu" in s.pools else 0,
                         "lpu_modules": s.pools["lpu"].modules if "lpu" in s.pools else 0,
                         "prefill_modules": s.pools["prefill"].modules if "prefill" in s.pools else 0,
                         "ctx_pb": s.ctx_tb_total / 1000.0, "price": s.price_usd_per_mwh,
                         "modules_per_rack": next((n.modules for n in s.nodes if n.kind == "gpu"), 0)})
        return {"name": self.name, "sites": rows}

    # ----------------------------------------------------------------------------------------------------------
    def without_quantum(self, name: str | None = None) -> "Fleet":
        """The GPU-ONLY REFERENCE fleet: every QPU / annealer / mixed node is replaced by GPU racks of the same facility power
        (same site caps, same power boundary), so the comparison is at equal power. Capex follows from the GPU racks."""
        spec = copy.deepcopy(self.spec)
        spec["name"] = name or f"{self.name}__gpu_only_ref"
        for sd in spec["sites"]:
            site = self.sites[sd["id"]]
            nodes = dict(sd.get("nodes", {}))
            freed_sys_w = 0.0
            for tkey in list(nodes):
                kind = self.node_cfg[tkey]["kind"]
                if kind in ("qpu", "annealer"):
                    n = next(x for x in site.nodes if x.type_key == tkey)
                    freed_sys_w += nodes.pop(tkey) * n.qpu.busy_w
                elif kind == "mixed":
                    n = next(x for x in site.nodes if x.type_key == tkey)
                    freed_sys_w += nodes.pop(tkey) * n.qpu.busy_w
                    # the GPU part of a mixed node stays as plain GPU modules: keep the modules via an equivalent rack
                    freed_sys_w += 0.0
            rack_nodes = [n for n in site.nodes if n.kind == "gpu"]
            if rack_nodes:
                rack_sys_peak = rack_nodes[0].modules * (rack_nodes[0].idle_sys_w + rack_nodes[0].dyn_sys_w)
                nodes["gpu_rack"] = nodes.get("gpu_rack", 0) + int(round(freed_sys_w / rack_sys_peak))
            # mixed nodes' GPU partitions become gpu racks of the same module count
            for tkey, cnt in dict(sd.get("nodes", {})).items():
                if self.node_cfg[tkey]["kind"] == "mixed" and rack_nodes:
                    m = next(x for x in site.nodes if x.type_key == tkey).modules
                    nodes["gpu_rack"] = nodes.get("gpu_rack", 0) + int(round(cnt * m / rack_nodes[0].modules))
            sd["nodes"] = nodes
        return Fleet(spec)

    def has_quantum(self) -> bool:
        return any(n.has_qpu for n in self.all_nodes())


def hash_site(sid: str) -> int:
    return sum(ord(c) * (i + 3) for i, c in enumerate(sid))


# ---------------------------------------------------------------------------------------------------------------
def default_fleet_spec(target_fill: float = 0.97) -> dict[str, Any]:
    """Build the default 6-site fleet. GPU racks are sized so that the facility power with every node at 100 % is
    ``target_fill`` x the site cap at mean ambient PUE (the scheduler throttles when hot hours push PUE above that)."""
    sites = [
        dict(id="us_east", name="US East (Virginia)", region="americas", lat=38.9, lon=-77.4, power_cap_mw=85, cooling="liquid",
             ambient_c_mean=14, ambient_c_amp=9, energy_usd_per_mwh=78, wan_gbps=1200,
             fixed={"ctxmem_pool": 12, "lpu_rack": 10, "qpu_cat40k": 2, "mixed_cat": 3, "qpu_annealer": 1}),
        dict(id="us_south", name="US South (Texas)", region="americas", lat=32.8, lon=-97.0, power_cap_mw=80, cooling="liquid",
             ambient_c_mean=21, ambient_c_amp=10, energy_usd_per_mwh=52, wan_gbps=1000,
             fixed={"ctxmem_pool": 10, "lpu_rack": 8, "qpu_cat40k": 1, "qpu_sc300k": 1}),
        dict(id="eu_north", name="EU North (Sweden)", region="emea", lat=65.6, lon=22.1, power_cap_mw=85, cooling="immersion",
             ambient_c_mean=3, ambient_c_amp=8, energy_usd_per_mwh=36, wan_gbps=1000,
             fixed={"ctxmem_pool": 12, "lpu_rack": 6, "qpu_cat40k": 2, "mixed_cat": 3, "qpu_ion40k": 1}),
        dict(id="eu_west", name="EU West (Ireland, legacy air-cooled)", region="emea", lat=53.3, lon=-6.3, power_cap_mw=60, cooling="air",
             ambient_c_mean=10, ambient_c_amp=6, energy_usd_per_mwh=118, wan_gbps=800,
             fixed={"ctxmem_pool": 8, "prefill_rack": 60, "qpu_cat40k": 1}),
        dict(id="me_gulf", name="Gulf (UAE, solar-backed)", region="emea", lat=24.5, lon=54.4, power_cap_mw=85, cooling="immersion",
             ambient_c_mean=33, ambient_c_amp=7, energy_usd_per_mwh=40, wan_gbps=800,
             fixed={"ctxmem_pool": 10, "lpu_rack": 8, "qpu_cat40k": 1, "mixed_cat": 2, "qpu_annealer": 1}),
        dict(id="apac", name="APAC (Singapore/Japan)", region="apac", lat=1.35, lon=103.8, power_cap_mw=105, cooling="liquid",
             ambient_c_mean=28, ambient_c_amp=4, energy_usd_per_mwh=105, wan_gbps=1200,
             fixed={"ctxmem_pool": 14, "lpu_rack": 12, "qpu_cat40k": 2, "mixed_cat": 3, "qpu_annealer": 1}),
    ]
    base = {"format": FLEET_FORMAT, "name": "default_6site", "grid_total_mw": 500,
            "description": "6 Earth sites sharing a 500 MW grid (asymmetric split, different cooling and energy prices). ALL node counts, "
                           "prices and climates are ASSUMPTIONS; QPU/GPU power and QPU feasibility come from quantum_arch (mid2030s base).",
            "sites": []}
    for s in sites:
        fixed = s.pop("fixed")
        s["nodes"] = dict(fixed)
        base["sites"].append(s)
    # size GPU racks
    f0 = Fleet(base)
    for sd in base["sites"]:
        site = f0.sites[sd["id"]]
        used = sum(n.peak_sys_w() for n in site.nodes) * (1 + f0.net_overhead()) * f0.fleet_pue_max(site)
        rack_peak_sys = None
        # a probe rack at this site's cooling
        probe = Fleet({"sites": [dict(sd, nodes={"gpu_rack": 1})], "name": "probe"})
        pn = probe.site_list[0].nodes[0]
        rack_peak_sys = pn.modules * (pn.idle_sys_w + pn.dyn_sys_w)
        rack_fac = rack_peak_sys * (1 + f0.net_overhead()) * f0.fleet_pue_max(site)
        n_gpu = max(0, int((site.cap_w * target_fill - used) // rack_fac))
        sd["nodes"]["gpu_rack"] = n_gpu
    return base
