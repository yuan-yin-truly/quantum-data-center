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
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import catalog, classical, cryo, qec, thermal2d, wiring
from . import workloads as wl
from .classical import Block

DEFAULTS: dict[str, Any] = {
    "name": "unnamed",
    "modality": "superconducting",
    "profile": "today",
    "scheme": None,
    "n_qubits": 1000,
    "qubit_overrides": {},
    "scheme_overrides": {},
    "cryostat": {},          # type, capacity_scale, targets_k
    "qpu_stage": None,
    "qec": {"code": "surface", "target_logical_error": 1e-12, "factory_fraction": 0.3,
            "decoder": None, "decoder_device": "fpga_large", "decoder_location": "RT",
            "decoder_count": "auto", "decoder_sustained": 0.4},
    "classical": [{"role": "host", "device": "cpu_epyc_96c", "count": 1, "utilisation": 0.3, "location": "RT"}],
    "link": {"pj_per_bit": 10.0, "latency_ns": 100.0},
    "facility": {"pue": 1.2},
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

    @property
    def total_power_w(self) -> float:
        return sum(self.power_w.values())


def resolve_scheme(modality_key: str, scheme_key: str | None, overrides: dict | None = None):
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
    return key, catalog.deep_merge(scheme, overrides)


def resolve_modality(modality_key: str, profile: str, overrides: dict | None) -> dict[str, Any]:
    mod = catalog.entry("modalities", modality_key)
    profiles = mod.get("profiles", {})
    if profile not in profiles:
        raise KeyError(f"modality {modality_key!r} has no profile {profile!r}; known: {', '.join(profiles)}")
    flat = {k: v for k, v in mod.items() if k not in ("schemes", "profiles", "default_scheme")}
    return catalog.deep_merge(catalog.deep_merge(flat, profiles[profile]), overrides)


def _fmt_w(x: float) -> str:
    for scale, unit in ((1e9, "GW"), (1e6, "MW"), (1e3, "kW"), (1.0, "W"), (1e-3, "mW"), (1e-6, "µW"), (1e-9, "nW")):
        if abs(x) >= scale:
            return f"{x / scale:.3g} {unit}"
    return f"{x:.2g} W"


def evaluate(arch: Architecture) -> Result:
    cfg = arch.config
    warnings: list[str] = []
    n = int(cfg["n_qubits"])
    m = resolve_modality(cfg["modality"], cfg["profile"], cfg["qubit_overrides"])
    scheme_key, scheme = resolve_scheme(cfg["modality"], cfg["scheme"], cfg["scheme_overrides"])
    budget = qec.error_budget(m)

    # ---- cryostat and lines -------------------------------------------------------------------
    cry_cfg = cfg["cryostat"]
    fridge_key = cry_cfg.get("type", scheme["cryostat"])
    fridge = cryo.Fridge.from_catalog(fridge_key, cry_cfg.get("capacity_scale", 1.0), cry_cfg.get("targets_k"))
    qpu_stage = cfg["qpu_stage"] or scheme.get("qpu_stage")
    lines = [wiring.with_reach(wiring.LineType.from_dict(d), qpu_stage or "") for d in scheme["lines"]]
    if fridge.stages and qpu_stage is None:
        raise ValueError("a cryostat needs a qpu_stage")
    counts = {ln.kind: ln.count(n) for ln in lines}
    n_lines = sum(ln.count(n) for ln in lines if ln.start is None)

    # ---- error correction ---------------------------------------------------------------------
    q = cfg["qec"]
    code = qec.Code(q["code"])
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
        dec_key = q["decoder"] or ("union_find" if code.key == "surface" else "bp_osd")
        dec = catalog.entry("decoders", dec_key)
        if code.key not in dec["codes"]:
            raise ValueError(f"decoder {dec_key!r} does not support {code.key!r}")
        bits_s = qec.syndrome_bits_per_second(cap.active_physical_qubits, budget.cycle_s)
        ops_s = bits_s * dec["ops_per_bit_round"]
        count = None if q["decoder_count"] == "auto" else int(q["decoder_count"])
        blk = classical.size_decoder(ops_s, dec_key, q["decoder_device"], q["decoder_location"], count,
                                     q["decoder_sustained"], cap.distance)
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
        blk = classical.fixed_block(c["role"], c["device"], int(c["count"]), loc, c.get("utilisation", 0.3))
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
    power = {
        "cryostat (installed)": cry.wall_power_w if cry else 0.0,
        "room-temperature control electronics": rt_channels_w,
        "decoders": sum(b.power_w for b in blocks if b.role == "decoder" and b.location == "RT"),
        "classical host / optimiser": sum(b.power_w for b in blocks if b.role != "decoder" and b.location == "RT"),
        "lasers, vacuum, apparatus": m["rt_overhead_w_fixed"] + m["rt_overhead_w_per_qubit"] * n,
        "data links": link_w if not (blocks and blocks[0].role == "decoder" and blocks[0].location != "RT") else 0.0,
    }
    power = {k: v for k, v in power.items() if v}
    total = sum(power.values())

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
        "facility_power_w": total * cfg["facility"]["pue"],
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
                  warnings=warnings, decoder_info=decoder_info)


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
