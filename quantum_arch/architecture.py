"""Architecture description and the end-to-end evaluation.

An :class:`Architecture` names a qubit modality, a control scheme (which fixes
the wiring, the cold electronics and the cryostat), a qubit count, an error
correction setup and the classical hardware beside it. :func:`evaluate` turns
it into three families of numbers:

* computing power: error budget, logical qubits, logical clock, rQOPS, and the
  time to solution of concrete workloads;
* energy: wall-plug power split by consumer, energy per logical operation and
  per workload, against a classical alternative where one exists;
* heat: per-stage heat loads by source versus cooling capacity, stage
  temperatures, fridges needed, and spatial temperature maps of the cold
  electronics and the qubit chip.

Power is reported at three explicit boundaries (see :func:`power_boundaries`): the QPU
module, the complete computer (``total_power_w``) and the facility (system x PUE plus
network/support). Hardware profiles: ``today`` (calibration anchor), ``projected``, and the
mid-2030s scenarios ``mid2030s_low`` / ``mid2030s`` (default) / ``mid2030s_high``; they are
scenarios, not forecasts. Annealers are not gate-model QPUs and live in :mod:`quantum_arch.annealer`.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import catalog, classical, cryo, qec, thermal2d, wiring
from . import workloads as wl
from .classical import Block

#: Hardware profiles. ``today`` is the calibration anchor, ``projected`` the older near-term scenario,
#: ``mid2030s*`` the data-centre-of-2035 scenarios (slow / base / fast progress; not forecasts).
PROFILES = ("today", "projected", "mid2030s_low", "mid2030s", "mid2030s_high")
PROFILE_ALIASES = {"mid2030s_base": "mid2030s", "2035": "mid2030s", "2035_low": "mid2030s_low", "2035_high": "mid2030s_high"}

DEFAULTS: dict[str, Any] = {
    "name": "unnamed",
    "modality": "superconducting",
    "profile": "mid2030s",
    "scheme": None,
    "n_qubits": 1000,
    "qubit_overrides": {},
    "scheme_overrides": {},
    "cryostat": {},          # type, capacity_scale, targets_k
    "qpu_stage": None,
    # code=None -> the modality's default code (surface unless the catalog says otherwise);
    # decoder=None -> the code's default decoder; "auto:<role>" devices follow the hardware profile.
    "qec": {"code": None, "target_logical_error": 1e-12, "factory_fraction": 0.3,
            "decoder": None, "decoder_device": "auto:fpga", "decoder_location": "RT",
            "decoder_count": "auto", "decoder_sustained": 0.4},
    "classical": [{"role": "host", "device": "auto:cpu", "count": 1, "utilisation": 0.3, "location": "RT"}],
    "link": {"pj_per_bit": 10.0, "latency_ns": 100.0},
    # Three power-measurement boundaries (see README_QUANTUM.md): the QPU module, the complete computer
    # ("system", what evaluate() sums), and the facility = (system + network_support_w) x pue.
    # pue covers heat rejection incl. the chilled water the cryostat compressors need; it must NOT be
    # applied to numbers that already include facility cooling. include_server_overhead adds the
    # DRAM/NIC/fan/PSU power of classical servers (device.system_overhead_ratio) to the system boundary.
    "facility": {"pue": 1.2, "network_support_w": 0.0, "include_server_overhead": False},
    "workloads": None,       # None = all in the catalog
    "plates": True,
}


@dataclass
class Architecture:
    config: dict[str, Any]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Architecture":
        return cls(catalog.deep_merge(DEFAULTS, raw))

    @classmethod
    def from_file(cls, path: str | Path) -> "Architecture":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def __getitem__(self, key):
        return self.config[key]

    @property
    def name(self) -> str:
        return self.config["name"]

    def with_overrides(self, **changes) -> "Architecture":
        return Architecture(catalog.deep_merge(self.config, changes))


@dataclass
class Result:
    arch: Architecture
    modality: dict[str, Any]
    scheme_key: str
    scheme_label: str
    budget: qec.ErrorBudget
    code: qec.Code
    capability: qec.Capability
    cryo: cryo.CryoResult | None
    line_counts: dict[str, int]
    blocks: list[Block]
    power_w: dict[str, float]
    plates: list[thermal2d.PlateResult]
    plate_notes: list[str]
    workloads: dict[str, dict[str, Any]]
    metrics: dict[str, float]
    warnings: list[str]
    decoder_info: dict[str, Any] = field(default_factory=dict)
    #: power at the three measurement boundaries, see :func:`power_boundaries`
    boundaries: dict[str, Any] = field(default_factory=dict)

    @property
    def total_power_w(self) -> float:
        return sum(self.power_w.values())


def canonical_profile(profile: str) -> str:
    return PROFILE_ALIASES.get(profile, profile)


def _apply_profile_adjust(scheme: dict, profile: str) -> dict:
    """Scale a scheme's electronics, channel power and line counts for a scenario profile."""
    adj = scheme.get("profile_adjust", {}).get(profile)
    if not adj:
        return scheme
    for e in scheme.get("electronics", []):
        f = adj.get(e.get("scale_key", ""))
        if f is not None:
            for k in ("w_per_qubit", "w_fixed"):
                if k in e:
                    e[k] = e[k] * f
    for ln in scheme.get("lines", []):
        if "rt_w_per_channel" in ln and "rt_channel_w" in adj:
            ln["rt_w_per_channel"] = ln["rt_w_per_channel"] * adj["rt_channel_w"]
        f = adj.get("lines_scale", {}).get(ln["kind"])
        if f is not None:
            ln["per_qubit"] = ln["per_qubit"] * f
    scheme["applied_profile_adjust"] = {k: v for k, v in adj.items()}
    return scheme


def resolve_scheme(modality_key: str, scheme_key: str | None, overrides: dict | None = None,
                   profile: str | None = None):
    mod = catalog.entry("modalities", modality_key)
    key = scheme_key or mod["default_scheme"]
    if key not in mod["schemes"]:
        raise KeyError(f"modality {modality_key!r} has no scheme {key!r}; known: {', '.join(mod['schemes'])}")
    scheme = mod["schemes"][key]
    if "extends" in scheme:
        base = catalog.deep_merge(mod["schemes"][scheme["extends"]], {k: v for k, v in scheme.items()
                                                                       if k not in ("extends", "cable_swap")})
        for line in base["lines"]:
            cable = line["cable"]
            swap = scheme.get("cable_swap", {})
            line["cable"] = swap.get(cable, cable) if isinstance(cable, str) else {z: swap.get(c, c) for z, c in cable.items()}
        scheme = base
    scheme = copy.deepcopy(scheme)
    if profile:
        scheme = _apply_profile_adjust(scheme, canonical_profile(profile))
    return key, catalog.deep_merge(scheme, overrides)


def resolve_modality(modality_key: str, profile: str, overrides: dict | None) -> dict[str, Any]:
    mod = catalog.entry("modalities", modality_key)
    profile = canonical_profile(profile)
    profiles = mod.get("profiles", {})
    if profile not in profiles:
        raise KeyError(f"modality {modality_key!r} has no profile {profile!r}; known: {', '.join(profiles)}")
    flat = {k: v for k, v in mod.items() if k not in ("schemes", "profiles", "default_scheme")}
    return catalog.deep_merge(catalog.deep_merge(flat, profiles[profile]), overrides)


def power_boundaries(cfg: dict, power: dict[str, float], cry, total: float, apparatus_w: float,
                     cold_electrical_w: float) -> dict[str, Any]:
    """Power at the three measurement boundaries the overview insists on.

    1. ``module``: the QPU module itself. ``electrical_w`` = module apparatus (lasers, optics, traps) plus the
       supply power of electronics inside the cryostat. ``cold_heat_load_w`` is THERMAL power lifted by the
       cryostat stages (cable conduction, attenuators, cold electronics): a different quantity, never wall power.
    2. ``system``: the complete computer = sum of all consumers in ``power`` (cryostat compressors, room-temperature
       control, decoders, host, support apparatus). Excludes facility cooling, networking and building overhead.
    3. ``facility``: ``(system + network_support_w) * pue``.
    """
    fac = cfg["facility"]
    net = float(fac.get("network_support_w", 0.0))
    pue = float(fac["pue"])
    cold_heat = sum(r.load_w for r in cry.stages) if cry else 0.0
    return {
        "module": {"electrical_w": apparatus_w + cold_electrical_w, "cold_heat_load_w": cold_heat,
                   "note": "QPU apparatus + supply of electronics inside the cryostat (electrical); cold_heat_load_w is thermal "
                           "power at the cryostat stages and is NOT wall power"},
        "system": {"power_w": total, "cryostat_wall_w": cry.wall_power_w if cry else 0.0,
                   "note": "complete quantum computer incl. cryostat compressors, control electronics, decoders, host; "
                           "excludes facility cooling, networking and building overhead"},
        "facility": {"power_w": (total + net) * pue, "pue": pue, "network_support_w": net,
                     "note": "(system + network/support) x PUE; PUE covers heat rejection incl. chilled water for the compressors"},
    }


def _fmt_w(x: float) -> str:
    for scale, unit in ((1e9, "GW"), (1e6, "MW"), (1e3, "kW"), (1.0, "W"), (1e-3, "mW"), (1e-6, "µW"), (1e-9, "nW")):
        if abs(x) >= scale:
            return f"{x / scale:.3g} {unit}"
    return f"{x:.2g} W"


def evaluate(arch: Architecture) -> Result:
    cfg = arch.config
    warnings: list[str] = []
    n = int(cfg["n_qubits"])
    profile = canonical_profile(cfg["profile"])
    m = resolve_modality(cfg["modality"], profile, cfg["qubit_overrides"])
    scheme_key, scheme = resolve_scheme(cfg["modality"], cfg["scheme"], cfg["scheme_overrides"], profile)
    budget = qec.error_budget(m)

    # ---- cryostat and lines -------------------------------------------------------------------
    cry_cfg = cfg["cryostat"]
    fridge_key = cry_cfg.get("type") or scheme.get("profile_cryostat", {}).get(profile) or scheme["cryostat"]
    fridge = cryo.Fridge.from_catalog(fridge_key, cry_cfg.get("capacity_scale", 1.0), cry_cfg.get("targets_k"), profile)
    qpu_stage = cfg["qpu_stage"] or scheme.get("qpu_stage")
    lines = [wiring.with_reach(wiring.LineType.from_dict(d), qpu_stage or "") for d in scheme["lines"]]
    if fridge.stages and qpu_stage is None:
        raise ValueError("a cryostat needs a qpu_stage")
    counts = {ln.kind: ln.count(n) for ln in lines}
    n_lines = sum(ln.count(n) for ln in lines if ln.start is None)

    # ---- error correction ---------------------------------------------------------------------
    q = cfg["qec"]
    code = qec.Code(q["code"] or m.get("default_code", "surface"))
    if code.needs_nonlocal and not m["nonlocal_connectivity"]:
        cap = qec.Capability(False, f"{code.label} needs long-range connectivity, which {m['label']} lacks "
                             "(set qubit_overrides.nonlocal_connectivity=true to assume couplers)", code.key,
                             lam=code.threshold / budget.p_eff)
    else:
        cap = qec.capability(code, budget, n, q["target_logical_error"], q["factory_fraction"])

    # ---- classical blocks ---------------------------------------------------------------------
    blocks: list[Block] = []
    decoder_info: dict[str, Any] = {}
    reaction_s = (m["t_meas_ns"] * 1e-9) + 2 * cfg["link"]["latency_ns"] * 1e-9
    if cap.feasible:
        dec_key = q["decoder"] or code.default_decoder or ("union_find" if code.key == "surface" else "bp_osd")
        dec = catalog.entry("decoders", dec_key)
        if code.key not in dec["codes"]:
            raise ValueError(f"decoder {dec_key!r} does not support {code.key!r}")
        bits_s = qec.syndrome_bits_per_second(cap.active_physical_qubits, budget.cycle_s)
        ops_s = bits_s * dec["ops_per_bit_round"]
        count = None if q["decoder_count"] == "auto" else int(q["decoder_count"])
        blk = classical.size_decoder(ops_s, dec_key, q["decoder_device"], q["decoder_location"], count,
                                     q["decoder_sustained"], cap.distance, profile)
        if blk.location != "RT" and blk.location not in fridge.names:
            raise ValueError(f"decoder location {blk.location!r} is not a stage of {fridge.key!r}")
        blocks.append(blk)
        reaction_s += blk.latency_s
        decoder_info = {"decoder": dec_key, "syndrome_bits_per_s": bits_s, "required_ops_per_s": ops_s,
                        "latency_s": blk.latency_s, "reaction_time_s": reaction_s}
        if not blk.keeps_up:
            warnings.append(f"decoder bank cannot keep up: {blk.count} x {blk.device.label} at "
                            f"{ops_s:.2e} op/s needed (backlog grows without bound)")
    else:
        decoder_info = {"decoder": None}
    for c in cfg["classical"]:
        loc = c.get("location", "RT")
        blk = classical.fixed_block(c["role"], c["device"], int(c["count"]), loc, c.get("utilisation", 0.3), profile)
        if loc != "RT" and loc not in fridge.names:
            raise ValueError(f"classical block at {loc!r}: no such stage in {fridge.key!r}")
        blocks.append(blk)

    link_w = classical.link_power_w(decoder_info.get("syndrome_bits_per_s", 0.0), cfg["link"]["pj_per_bit"])

    # ---- heat loads and cryostat --------------------------------------------------------------
    def component_sources() -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {name: {} for name in fridge.names}
        for e in scheme["electronics"]:
            w = e.get("w_per_qubit", 0.0) * n + e.get("w_fixed", 0.0)
            out[e["stage"]]["component: " + e["name"]] = out[e["stage"]].get("component: " + e["name"], 0.0) + w
        chip_w = m["qpu_w_per_qubit"] * n + m["qpu_w_fixed"]
        if chip_w and qpu_stage:
            out[qpu_stage]["component: qubit chip"] = chip_w
        for blk in blocks:
            if blk.location != "RT":
                key = f"component: {blk.role} ({blk.device.label})"
                out[blk.location][key] = out[blk.location].get(key, 0.0) + blk.power_w
        if link_w and fridge.stages and blocks and blocks[0].role == "decoder" and blocks[0].location != "RT":
            out[blocks[0].location]["component: syndrome links"] = link_w
        return out

    def load_fn(temps: dict[str, float]) -> dict[str, dict[str, float]]:
        sources = component_sources()
        for ln in lines:
            cnt = ln.count(n)
            if not cnt:
                continue
            for stage, w in wiring.passive_per_line(ln, fridge, temps).items():
                key = f"passive: {ln.kind}"
                sources[stage][key] = sources[stage].get(key, 0.0) + w * cnt
            for stage, w in wiring.active_per_line(ln, fridge).items():
                if w:
                    key = f"active: {ln.kind}"
                    sources[stage][key] = sources[stage].get(key, 0.0) + w * cnt
        return sources

    cry = cryo.solve(fridge, load_fn, n_lines) if fridge.stages else None
    if cry:
        for r in cry.stages:
            if r.overloaded:
                warnings.append(f"{r.name} stage overloaded: {_fmt_w(r.load_w)} against {_fmt_w(r.capacity_w)} at "
                                f"{r.target_k:g} K (would settle at {r.temperature_k:.3g} K); needs "
                                f"{math.ceil(r.load_w / r.capacity_w)} fridge units")
        if cry.units_for_lines > 1:
            warnings.append(f"{n_lines:,} lines exceed the {fridge.max_coax_lines * fridge.capacity_scale:,.0f} a single fridge carries "
                            f"({cry.units_for_lines} units); superconducting qubits cannot be split across fridges "
                            "without a cryogenic interconnect")
        if cry.units_needed > 1 and cry.units_for_lines <= 1:
            warnings.append(f"heat load needs {cry.units_needed} fridge units for one processor")

    # ---- electrical power ---------------------------------------------------------------------
    rt_channels_w = sum(ln.count(n) * ln.rt_channels * ln.rt_w_per_channel for ln in lines)
    # Electronics inside the cryostat (cryo-CMOS, amplifiers, cold decoders, links) are powered from outside:
    # the cryostat's installed wall power covers cooling only, so their supply power is a separate consumer.
    cold_supply_w = sum(w for stage in component_sources().values() for k, w in stage.items()
                        if k.startswith("component: ") and k != "component: qubit chip")
    chip_w_elec = m["qpu_w_per_qubit"] * n + m["qpu_w_fixed"] if qpu_stage else 0.0
    apparatus_w = m.get("apparatus_w_fixed", 0.0) + m.get("apparatus_w_per_qubit", 0.0) * n
    support_w = m.get("rt_overhead_w_fixed", 0.0) + m.get("rt_overhead_w_per_qubit", 0.0) * n
    rt_blocks = [b for b in blocks if b.location == "RT"]
    server_overhead_w = sum(b.server_overhead_w for b in rt_blocks) if cfg["facility"].get("include_server_overhead") else 0.0
    power = {
        "cryostat (installed)": cry.wall_power_w if cry else 0.0,
        "room-temperature control electronics": rt_channels_w,
        "cold electronics supply (cryo-CMOS, amplifiers, cold decoders)": cold_supply_w + chip_w_elec,
        "decoders": sum(b.power_w for b in rt_blocks if b.role == "decoder"),
        "classical host / optimiser": sum(b.power_w for b in rt_blocks if b.role != "decoder"),
        "server overhead (DRAM, NICs, fans, PSU losses)": server_overhead_w,
        "QPU apparatus (lasers, optics, traps, sources)": apparatus_w,
        "support apparatus (vacuum, chillers, racks)": support_w,
        "data links": link_w if not (blocks and blocks[0].role == "decoder" and blocks[0].location != "RT") else 0.0,
    }
    power = {k: v for k, v in power.items() if v}
    total = sum(power.values())
    boundaries = power_boundaries(cfg, power, cry, total, apparatus_w, cold_supply_w + chip_w_elec)

    # ---- metrics ------------------------------------------------------------------------------
    pairs_rate = (n / 2) / (m["t_2q_ns"] * 1e-9)
    metrics: dict[str, float] = {
        "physical_qubits": n,
        "syndrome_cycle_s": budget.cycle_s,
        "p_eff": budget.p_eff,
        "lambda": cap.lam,
        "peak_2q_gate_rate_hz": pairs_rate,
        "energy_per_2q_gate_j": total / pairs_rate if pairs_rate else math.nan,
        "total_power_w": total,
        "system_power_w": total,
        "qpu_module_w": boundaries["module"]["electrical_w"],
        "cold_heat_load_w": boundaries["module"]["cold_heat_load_w"],
        "facility_power_w": boundaries["facility"]["power_w"],
        "logical_qubits": cap.logical_qubits,
        "code_distance": cap.distance or 0,
        "logical_clock_hz": cap.logical_clock_hz,
        "rqops": cap.rqops,
        "logical_error_per_op": cap.logical_error_per_op if cap.logical_error_per_op is not None else math.nan,
        "energy_per_logical_op_j": total / cap.rqops if cap.rqops else math.inf,
        "n_lines": n_lines,
        "fridge_units": cry.units_needed if cry else 0,
    }
    if not cap.feasible:
        warnings.append(f"no error-corrected computing: {cap.reason}")

    # ---- workloads ----------------------------------------------------------------------------
    blocked = None
    if budget.p_eff >= code.threshold or (code.needs_nonlocal and not m["nonlocal_connectivity"]):
        blocked = cap.reason
    wl_results = wl.run_all(cfg, m, budget, code, cap, blocks, total, reaction_s, cfg["workloads"], blocked)

    # ---- spatial thermal ----------------------------------------------------------------------
    plates: list[thermal2d.PlateResult] = []
    notes: list[str] = []
    if cfg["plates"] and cry:
        plates, notes = _plates(cfg, m, scheme, lines, n, qpu_stage, blocks, cry)
    return Result(arch=arch, modality=m, scheme_key=scheme_key, scheme_label=scheme["label"], budget=budget,
                  code=code, capability=cap, cryo=cry, line_counts=counts, blocks=blocks, power_w=power,
                  plates=plates, plate_notes=notes, workloads=wl_results, metrics=metrics,
                  warnings=warnings, decoder_info=decoder_info, boundaries=boundaries)


def _plates(cfg, m, scheme, lines, n, qpu_stage, blocks, cry):
    """Build and solve the spatial maps: cold electronics board and qubit chip."""
    plates: list[thermal2d.PlateResult] = []
    notes: list[str] = []
    contact = thermal2d.Contact(**cfg.get("contact", {}))

    # Cold electronics (cryo-CMOS / cold decoders) on the 4 K-class stage.
    by_stage: dict[str, float] = {}
    for e in scheme["electronics"]:
        if "CMOS" in e["name"] or "cryo" in e["name"].lower():
            by_stage[e["stage"]] = by_stage.get(e["stage"], 0.0) + e.get("w_per_qubit", 0.0) * n + e.get("w_fixed", 0.0)
    for b in blocks:
        if b.location != "RT":
            by_stage[b.location] = by_stage.get(b.location, 0.0) + b.power_w
    for stage, power in by_stage.items():
        res = cry.stage_result(stage)
        if power > 10 * res.capacity_w:
            notes.append(f"{stage}: cold electronics ({_fmt_w(power)}) exceed 10x the stage capacity; spatial map skipped")
            continue
        chips = min(16, max(1, math.ceil(power / 0.5)))
        side = math.ceil(math.sqrt(chips))
        pitch, size = 14.0, 10.0
        plate = thermal2d.Plate(
            name=f"cold electronics @ {stage}", stage=stage, t_stage_k=res.temperature_k,
            size_mm=(side * pitch + 6, side * pitch + 6), thickness_mm=0.3, material="silicon", contact=contact,
            sources=[thermal2d.Source(f"chip{i}", 3 + (i % side) * pitch, 3 + (i // side) * pitch, size, size,
                                      power / chips, hotspot=2.0) for i in range(chips)])
        plates.append(thermal2d.solve_plate(plate))
    # Qubit chip.
    chip_w = m["qpu_w_per_qubit"] * n + m["qpu_w_fixed"]
    for ln in lines:
        if ln.chip_power_dbm is not None and ln.count(n):
            chip_w += ln.count(n) * 1e-3 * 10 ** (ln.chip_power_dbm / 10)
    if chip_w > 0 and qpu_stage:
        area = n / m["qubit_density_per_mm2"]
        side = min(max(math.sqrt(area), 5.0), 100.0)
        res = cry.stage_result(qpu_stage)
        plate = thermal2d.Plate(
            name=f"qubit chip @ {qpu_stage}", stage=qpu_stage, t_stage_k=res.temperature_k,
            size_mm=(side + 4, side + 4), thickness_mm=0.5, material="silicon", contact=contact,
            sources=[thermal2d.Source("qubit array", 2, 2, side, side, chip_w, hotspot=0.5)])
        plates.append(thermal2d.solve_plate(plate))
    return plates, notes
