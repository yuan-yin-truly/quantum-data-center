"""Evaluate the quantum side of a hybrid submission with the existing ``quantum_arch``.

LOCAL-ONLY VARIANT. ``quantum_arch`` (chiplet-thermal-gui/quantum_arch) is imported
and used unmodified. It decides only feasibility and cost of the offloaded task; it
never decides how much work is offloaded (that is a declared input) and no
quantum-advantage figure is produced or forwarded (the classical-alternative energy
that quantum_arch reports for some workloads is deliberately dropped).

Needs numpy and scipy (via quantum_arch), so it runs on the host, not in the
HotSpot container.
"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Repo layout: <repo>/hill_variant/beat-the-hotspot-quantum (this file's dir) and, for a copy kept
# under .autolab/hills/, a sibling checkout named chiplet-thermal-gui three levels up.
DEFAULT_REPO_RELS = (Path("..") / "..", Path("..") / ".." / ".." / "chiplet-thermal-gui")


class QuantumUnavailable(RuntimeError):
    """quantum_arch cannot be imported (missing repo path or scipy)."""


def find_quantum_repo() -> Path:
    candidates = []
    if os.environ.get("QUANTUM_ARCH_REPO"):
        candidates.append(Path(os.environ["QUANTUM_ARCH_REPO"]))
    candidates.extend((HERE / rel).resolve() for rel in DEFAULT_REPO_RELS)
    for c in candidates:
        if (c / "quantum_arch" / "__init__.py").is_file():
            return c
    raise QuantumUnavailable(
        "cannot find the quantum_arch package; set QUANTUM_ARCH_REPO to the chiplet-thermal-gui directory "
        f"(tried: {[str(c) for c in candidates]})")


def import_quantum():
    repo = find_quantum_repo()
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    try:
        import quantum_arch
        from quantum_arch import catalog, report
    except ModuleNotFoundError as exc:  # scipy / numpy / matplotlib missing
        raise QuantumUnavailable(f"quantum_arch needs numpy, scipy and matplotlib ({exc}); "
                                 "run with the chiplet-thermal-gui venv python") from exc
    return repo, quantum_arch, catalog, report


def catalog_names() -> tuple[set[str], set[str]]:
    """(quantum_arch workload keys, example names) for schema validation."""
    repo, _, catalog, _ = import_quantum()
    examples = {p.stem for p in (repo / "quantum_arch" / "examples").glob("*.json")}
    return set(catalog.keys("workloads")), examples


class QuantumEvalError(ValueError):
    """quantum_arch rejected the architecture (unknown catalog key, invalid combination ...)."""


@dataclass
class QuantumOutcome:
    feasible: bool
    reasons: list[str]
    summary: dict
    #: watts the quantum subsystem draws outside the package (cryostat, RT electronics, RT decoders, host...)
    external_power_w: float
    #: {die: {"devices": k, "active_w": W, "idle_w": W, "extra_w": W}} for package-hosted decoders
    host_power: dict = field(default_factory=dict)
    task_runtime_s: float | None = None
    warnings: list[str] = field(default_factory=list)


def _clean(obj):
    """JSON-safe copy: non-finite floats become None."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def allocate_devices(needed: int, capacities: dict[str, int]) -> dict[str, int]:
    """Spread ``needed`` devices round-robin over dies without exceeding any capacity."""
    placed = {die: 0 for die in capacities}
    left = min(needed, sum(capacities.values()))
    while left > 0:
        progressed = False
        for die in sorted(capacities):
            if left > 0 and placed[die] < capacities[die]:
                placed[die] += 1
                left -= 1
                progressed = True
        if not progressed:
            break
    return placed


def build_architecture_dict(nb: dict) -> dict:
    """Resolve the normalised block to a quantum_arch architecture dict."""
    repo, _, catalog, _ = import_quantum()
    arch = copy.deepcopy(nb["architecture"])
    if "__example__" in arch:
        path = repo / "quantum_arch" / "examples" / f"{arch['__example__']}.json"
        arch = json.loads(path.read_text(encoding="utf-8"))
    arch = catalog.deep_merge(arch, nb["architecture_overrides"])
    arch["workloads"] = [nb["task"]["workload"]]   # evaluate only the offloaded task
    arch["plates"] = False                         # spatial cryo maps are not needed here
    hosts = nb["package_hosts"]
    if hosts["dies"]:
        loc = arch.get("qec", {}).get("decoder_location", "RT")
        if loc != "RT":
            raise QuantumEvalError(
                f"package_hosts places decoders on the package, but the architecture sets decoder_location={loc!r}; "
                "a decoder bank cannot be both on a cold stage and on the interposer")
        arch.setdefault("qec", {})
        arch["qec"]["decoder_device"] = hosts["device"]
        arch["qec"]["decoder_location"] = "RT"
    for c in arch.get("classical", []) or []:
        if c.get("location") == "package":
            raise QuantumEvalError("classical[].location 'package' is not supported; declare package hosting "
                                   "with quantum.package_hosts (decoders only)")
    return arch


def evaluate_quantum(nb: dict) -> QuantumOutcome:
    _, qa, _, report = import_quantum()
    try:
        arch_dict = build_architecture_dict(nb)
        result = qa.evaluate(qa.Architecture.from_dict(arch_dict))
    except QuantumEvalError:
        raise
    except (KeyError, ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
        raise QuantumEvalError(f"quantum_arch rejected the architecture: {type(exc).__name__}: {exc}") from exc
    raw = report.to_dict(result)
    cap = result.capability
    task_key = nb["task"]["workload"]
    task = dict(result.workloads[task_key])
    # Drop every classical-alternative / advantage field: not used, not forwarded (honesty rule).
    for key in ("classical_ops", "classical_energy_j", "classical_energy", "energy_advantage",
                "classical_sim_memory_bytes", "classical_note"):
        task.pop(key, None)
    reasons: list[str] = []
    warnings = list(result.warnings)
    if not task.get("feasible"):
        reasons.append(f"task {task_key!r} cannot run: {task.get('reason')}")

    decoder_block = next((b for b in result.blocks if b.role == "decoder"), None)
    if decoder_block is not None and task.get("type") == "fault_tolerant" and not decoder_block.keeps_up:
        reasons.append("decoder bank cannot keep up with the syndrome stream")
    cry = result.cryo
    if cry is not None:
        if cry.units_for_lines > 1:
            reasons.append(f"{raw['cryostat']['n_lines']:,} control lines need {cry.units_for_lines} fridges; "
                           "a processor cannot be split across fridges (no cryogenic interconnect modelled)")
        limit = nb["limits"]["max_fridge_units"]
        if limit is not None and cry.units_needed > limit:
            reasons.append(f"cryostat needs {cry.units_needed} units, limit is {limit:g}")

    # ---- decoder hosting on the package ----
    host_power: dict = {}
    hosted_w = 0.0
    placement = {"room_temperature": 0, "package": {}, "total_devices": 0}
    hosts = nb["package_hosts"]["dies"]
    if decoder_block is not None:
        per_device_w = decoder_block.power_w / decoder_block.count if decoder_block.count else 0.0
        placement["total_devices"] = decoder_block.count
        placement["location_in_quantum_arch"] = decoder_block.location
        if hosts and decoder_block.location == "RT":
            alloc = allocate_devices(decoder_block.count, {d: h["max_devices"] for d, h in hosts.items()})
            placement["package"] = {d: n for d, n in alloc.items() if n}
            placement["room_temperature"] = decoder_block.count - sum(alloc.values())
            hosted_w = sum(alloc.values()) * per_device_w
            idle_w = decoder_block.device.idle_w
            for die, host in hosts.items():
                k = alloc.get(die, 0)
                host_power[die] = {"devices": k, "active_w": k * per_device_w + host["extra_power_w"],
                                   "idle_w": k * idle_w + host["extra_power_w"], "extra_w": host["extra_power_w"],
                                   "device": decoder_block.device.label, "device_utilisation": decoder_block.utilisation}
            if placement["room_temperature"]:
                warnings.append(f"{placement['room_temperature']} of {decoder_block.count} decoder devices do not "
                                "fit on the declared package hosts and stay at room temperature")
        else:
            placement["room_temperature"] = decoder_block.count if decoder_block.location == "RT" else 0
    if hosts and not host_power:
        # no decoder block (e.g. no error-corrected capability): hosts carry only their declared overhead
        for die, host in hosts.items():
            host_power[die] = {"devices": 0, "active_w": host["extra_power_w"], "idle_w": host["extra_power_w"],
                               "extra_w": host["extra_power_w"], "device": None, "device_utilisation": None}
        warnings.append("no decoder bank was sized (no error-corrected capability): package hosts idle")

    external_w = result.total_power_w - hosted_w
    limit_w = nb["limits"]["max_total_power_w"]
    if limit_w is not None and external_w > limit_w:
        reasons.append(f"quantum-side power {external_w:.3g} W exceeds limit {limit_w:g} W")

    stages = []
    if cry is not None:
        for s in raw["cryostat"]["stages"]:
            stages.append({"stage": s["name"], "target_k": s["target_k"], "settles_at_k": s["temperature_k"],
                           "load_w": s["load_w"], "capacity_w": s["capacity_w"],
                           "utilisation": s["utilisation"],
                           "overloaded": bool(s["utilisation"] is not None and s["utilisation"] > 1.0),
                           "fridge_units_for_this_stage": (math.ceil(s["utilisation"]) if s["utilisation"] else 0)})
    summary = {
        "architecture": {"name": result.arch.name, "source": nb["architecture_source"],
                         "modality": raw["modality"], "scheme": raw["scheme"], "profile": raw["profile"],
                         "n_physical_qubits": raw["n_qubits"], "code": raw["computing"]["code"]},
        "capability": {"error_corrected": cap.feasible, "reason": cap.reason, "code_distance": cap.distance,
                       "logical_qubits": cap.logical_qubits, "lambda": cap.lam,
                       "logical_clock_hz": cap.logical_clock_hz, "rqops": cap.rqops,
                       "logical_error_per_op": cap.logical_error_per_op,
                       "target_logical_error": raw["computing"]["target_logical_error"]},
        "task": {"workload": task_key, **task},
        "decoder": {**raw["decoder"], "placement": placement},
        "cryostat": ({"type": raw["cryostat"]["type"], "fridge_units": cry.units_needed,
                      "units_for_heat": cry.units_for_heat, "units_for_lines": cry.units_for_lines,
                      "n_lines": cry.n_lines, "wall_power_w": cry.wall_power_w,
                      "carnot_floor_w": cry.carnot_floor_w, "stages": stages} if cry else None),
        "power_w": {"quantum_arch_total": result.total_power_w, "hosted_on_package": hosted_w,
                    "outside_package": external_w, "breakdown": raw["power_w"],
                    "pue": result.arch["facility"]["pue"],
                    "facility_power_w_quantum_arch": raw["facility_power_w"]},
        "classical_blocks": raw["classical_blocks"],
        "warnings": warnings,
    }
    runtime = task.get("runtime_s") if task.get("feasible") else None
    return QuantumOutcome(feasible=not reasons, reasons=reasons, summary=_clean(summary),
                          external_power_w=external_w, host_power=_clean(host_power),
                          task_runtime_s=runtime, warnings=warnings)
