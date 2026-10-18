"""Schema and validation of the optional ``quantum`` block of ``submission.json``.

LOCAL-ONLY VARIANT. Pure Python (no numpy, no quantum_arch import), so a malformed
block is rejected in microseconds, before any simulation.

Schema (every key optional unless marked required)::

    "quantum": {
      "schema_version": 1,
      # exactly one architecture source (required):
      "architecture":          {...quantum_arch Architecture dict...},
      "architecture_example":  "sc_rt_direct_100q",     # a quantum_arch/examples/*.json name
      "architecture_file":     "arch.json",             # relative path inside the submission dir
      "architecture_overrides": {...},                  # deep-merged on top (optional)

      "task": {                                         # the offloaded work, as a quantum_arch workload
        "workload": "vqe_50q",                          # required; key of quantum_arch/data/workloads.json
        "package_workload": "mixed_serving"             # hill workload the package runs meanwhile (energy/task)
      },

      "offload": {                                      # INPUT assumptions, never derived from a speedup claim
        "fractions": {"*": 0.10,                        # workload -> fraction | {die: fraction}; "*" = all
                      "memory_stream": {"G0": 0.2, "*": 0.1}},
        "dynamic_power_fraction": 1.0,                  # share of a GPU map that scales with the offload
        "traffic_coupling": 0.0,                        # link utilisation falls by coupling * fraction
        "replaced_die_work": "redistributed",           # or "dropped" (see README)
        "active_in": ["tensor_training", ...]           # hill workloads during which the quantum side runs
      },

      "package_hosts": {                                # dies re-declared as quantum-support chiplets
        "device": "asic_decoder_rt",                    # quantum_arch classical-catalog device
        "dies": {"G3": {"max_devices": 8, "extra_power_w": 2.0,
                        "traffic_scale": 0.0, "max_junction_c": 105}}
      },

      "limits": {"max_fridge_units": 30, "max_total_power_w": 5e6}
    }

``validate_quantum_block`` returns a normalised copy with every default made explicit.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

SCHEMA_VERSION = 1
TOP_KEYS = {"schema_version", "architecture", "architecture_example", "architecture_file",
            "architecture_overrides", "task", "offload", "package_hosts", "limits"}
SOURCE_KEYS = ("architecture", "architecture_example", "architecture_file")
OFFLOAD_KEYS = {"fractions", "dynamic_power_fraction", "traffic_coupling", "replaced_die_work", "active_in"}
HOST_DIE_KEYS = {"max_devices", "extra_power_w", "traffic_scale", "max_junction_c"}
MAX_ARCH_FILE_BYTES = 128_000


class QuantumBlockError(ValueError):
    """The quantum block is malformed; the message says what to fix."""


def _num(value, label, *, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise QuantumBlockError(f"{label} must be a finite number")
    if lo is not None and value < lo:
        raise QuantumBlockError(f"{label} must be >= {lo}")
    if hi is not None and value > hi:
        raise QuantumBlockError(f"{label} must be <= {hi}")
    return float(value)


def _obj(value, label):
    if not isinstance(value, dict):
        raise QuantumBlockError(f"{label} must be an object")
    return value


def _unknown(keys, allowed, label):
    extra = sorted(set(keys) - set(allowed))
    if extra:
        raise QuantumBlockError(f"{label}: unknown key(s) {extra}; allowed: {sorted(allowed)}")


def _resolve_fractions(raw, workloads, gpu_dies, hosts, label="offload.fractions"):
    """Expand the compact ``fractions`` form to ``{workload: {gpu_die: f}}`` (all pairs, remaining GPUs)."""
    raw = _obj(raw, label)
    for key in raw:
        if key != "*" and key not in workloads:
            raise QuantumBlockError(f"{label}: unknown workload {key!r}; known: {list(workloads)} or '*'")
    out = {w: {d: 0.0 for d in gpu_dies if d not in hosts} for w in workloads}

    def spread(value, target, where):
        if isinstance(value, dict):
            for key in value:
                if key != "*" and key not in gpu_dies:
                    raise QuantumBlockError(f"{where}: {key!r} is not a GPU die (G0-G3) or '*'")
            per_die = {d: None for d in out[target]}
            if "*" in value:
                for d in per_die:
                    per_die[d] = _num(value["*"], f"{where}['*']", lo=0, hi=1)
            for d, f in value.items():
                if d == "*":
                    continue
                if d in hosts:
                    raise QuantumBlockError(f"{where}: {d} is re-declared as a package host and cannot offload")
                per_die[d] = _num(f, f"{where}[{d}]", lo=0, hi=1)
            for d, f in per_die.items():
                if f is not None:
                    out[target][d] = f
        else:
            f = _num(value, where, lo=0, hi=1)
            for d in out[target]:
                out[target][d] = f

    if "*" in raw:
        for w in workloads:
            spread(raw["*"], w, f"{label}['*']")
    for w, value in raw.items():
        if w != "*":
            spread(value, w, f"{label}[{w}]")
    return out


def validate_quantum_block(raw, *, spec: dict, submission_dir: Path | None = None,
                           known_tasks: set[str] | None = None,
                           known_examples: set[str] | None = None) -> dict:
    """Validate and normalise. Raises :class:`QuantumBlockError` with a clear message."""
    block = _obj(raw, "quantum")
    _unknown(block, TOP_KEYS, "quantum")
    version = block.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise QuantumBlockError(f"quantum.schema_version must be {SCHEMA_VERSION}")
    workloads = list(spec["workloads"])
    gpu_dies = [d for d, v in spec["dies"].items() if v["kind"] == "GPU"]

    # ---- architecture source ----
    given = [k for k in SOURCE_KEYS if k in block]
    if len(given) != 1:
        raise QuantumBlockError(f"quantum needs exactly one of {list(SOURCE_KEYS)}, got {given or 'none'}")
    source = given[0]
    if source == "architecture":
        architecture = _obj(block["architecture"], "quantum.architecture")
        source_desc = "inline"
    elif source == "architecture_example":
        name = block["architecture_example"]
        if not isinstance(name, str) or not name.replace("_", "").isalnum():
            raise QuantumBlockError("quantum.architecture_example must be a plain example name")
        if known_examples is not None and name not in known_examples:
            raise QuantumBlockError(f"quantum.architecture_example {name!r} is not a quantum_arch example; "
                                    f"known: {sorted(known_examples)}")
        architecture, source_desc = {"__example__": name}, f"example:{name}"
    else:
        rel = block["architecture_file"]
        if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise QuantumBlockError("quantum.architecture_file must be a relative path inside the submission dir")
        if submission_dir is None:
            raise QuantumBlockError("quantum.architecture_file needs a submission directory")
        path = (Path(submission_dir) / rel).resolve()
        if Path(submission_dir).resolve() not in path.parents or not path.is_file():
            raise QuantumBlockError(f"quantum.architecture_file {rel!r} not found inside the submission dir")
        if path.stat().st_size > MAX_ARCH_FILE_BYTES:
            raise QuantumBlockError(f"quantum.architecture_file exceeds {MAX_ARCH_FILE_BYTES} bytes")
        try:
            architecture = _obj(json.loads(path.read_text(encoding="utf-8")), "architecture_file content")
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise QuantumBlockError(f"quantum.architecture_file is not valid JSON: {exc}") from exc
        source_desc = f"file:{rel}"
    overrides = _obj(block.get("architecture_overrides", {}), "quantum.architecture_overrides")

    # ---- task ----
    task = _obj(block.get("task", {}), "quantum.task")
    _unknown(task, {"workload", "package_workload"}, "quantum.task")
    if "workload" not in task or not isinstance(task["workload"], str):
        raise QuantumBlockError("quantum.task.workload (a quantum_arch workload key) is required")
    if known_tasks is not None and task["workload"] not in known_tasks:
        raise QuantumBlockError(f"quantum.task.workload {task['workload']!r} is not in the quantum_arch "
                                f"workload catalog; known: {sorted(known_tasks)}")
    package_workload = task.get("package_workload", "mixed_serving")
    if package_workload not in workloads:
        raise QuantumBlockError(f"quantum.task.package_workload must be one of {workloads}")

    # ---- package hosts (needed before fractions: hosts cannot offload) ----
    hosts_raw = _obj(block.get("package_hosts", {}), "quantum.package_hosts")
    _unknown(hosts_raw, {"device", "dies"}, "quantum.package_hosts")
    host_dies_raw = _obj(hosts_raw.get("dies", {}), "quantum.package_hosts.dies")
    hosts = {}
    if host_dies_raw:
        if not isinstance(hosts_raw.get("device"), str):
            raise QuantumBlockError("quantum.package_hosts.device (a classical-catalog key) is required")
        for die, cfg in host_dies_raw.items():
            if die not in gpu_dies:
                raise QuantumBlockError(f"quantum.package_hosts.dies: {die!r} must be a GPU die {gpu_dies} "
                                        "(HBM stacks cannot be re-declared in this variant)")
            cfg = _obj(cfg, f"quantum.package_hosts.dies.{die}")
            _unknown(cfg, HOST_DIE_KEYS, f"quantum.package_hosts.dies.{die}")
            if "max_devices" not in cfg:
                raise QuantumBlockError(f"quantum.package_hosts.dies.{die}.max_devices is required "
                                        "(how many catalog devices the die can host: an input assumption)")
            md = _num(cfg["max_devices"], f"{die}.max_devices", lo=0)
            if md != int(md):
                raise QuantumBlockError(f"{die}.max_devices must be an integer")
            hosts[die] = {"max_devices": int(md),
                          "extra_power_w": _num(cfg.get("extra_power_w", 0.0), f"{die}.extra_power_w", lo=0),
                          "traffic_scale": _num(cfg.get("traffic_scale", 0.0), f"{die}.traffic_scale", lo=0, hi=1),
                          "max_junction_c": (None if cfg.get("max_junction_c") is None
                                             else _num(cfg["max_junction_c"], f"{die}.max_junction_c", lo=0))}
        if len(hosts) >= len(gpu_dies):
            raise QuantumBlockError("at least one GPU die must remain a GPU")

    # ---- offload ----
    off = _obj(block.get("offload", {}), "quantum.offload")
    _unknown(off, OFFLOAD_KEYS, "quantum.offload")
    fractions = _resolve_fractions(off.get("fractions", {}), workloads, gpu_dies, hosts)
    mode = off.get("replaced_die_work", "redistributed")
    if mode not in ("redistributed", "dropped"):
        raise QuantumBlockError("quantum.offload.replaced_die_work must be 'redistributed' or 'dropped'")
    any_fraction = any(f > 0 for per in fractions.values() for f in per.values())
    if "active_in" in off:
        active = off["active_in"]
        if (not isinstance(active, list) or any(w not in workloads for w in active)):
            raise QuantumBlockError(f"quantum.offload.active_in must be a list of hill workloads {workloads}")
        active = [w for w in workloads if w in active]
    else:
        active = list(workloads)
    for w, per in fractions.items():
        if w not in active and any(f > 0 for f in per.values()):
            raise QuantumBlockError(f"offload fraction > 0 declared for {w!r}, which is not in offload.active_in")

    limits = _obj(block.get("limits", {}), "quantum.limits")
    _unknown(limits, {"max_fridge_units", "max_total_power_w"}, "quantum.limits")
    out_limits = {k: (None if limits.get(k) is None else _num(limits[k], f"quantum.limits.{k}", lo=0))
                  for k in ("max_fridge_units", "max_total_power_w")}

    return {
        "schema_version": SCHEMA_VERSION,
        "architecture_source": source_desc,
        "architecture": architecture,
        "architecture_overrides": overrides,
        "task": {"workload": task["workload"], "package_workload": package_workload},
        "offload": {"fractions": fractions,
                    "dynamic_power_fraction": _num(off.get("dynamic_power_fraction", 1.0),
                                                   "offload.dynamic_power_fraction", lo=0, hi=1),
                    "traffic_coupling": _num(off.get("traffic_coupling", 0.0), "offload.traffic_coupling",
                                             lo=0, hi=1),
                    "replaced_die_work": mode, "active_in": active, "any_fraction": any_fraction},
        "package_hosts": {"device": hosts_raw.get("device"), "dies": hosts},
        "limits": out_limits,
    }
