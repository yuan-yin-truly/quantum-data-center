"""Task model and the shared task-spec file format (JSON, ``dc_sim.tasks/1``).

One file feeds the numerical simulator, the CLI, the API and the visual app. Layout::

    {"format": "dc_sim.tasks/1", "name": ..., "description": ..., "seed": 1, "horizon_s": 43200,
     "start_utc_hour": 6.0, "case": "mix", "demand_scale": 1.0,
     "tasks":  [ {id, arrival_s, type, case, priority, deadline_s, home_region, data_gb, min_success,
                  size{...}, quantum{...}, classical_fallback{...}, stages[...]} ],
     "events": [ {t, type: site_power_cap | node_failure | qpu_calibration | demand_surge, ...} ]}

Task types: ``llm_prefill_batch``, ``llm_decode_batch``, ``agent_job``, ``knowledge_job``, ``quantum_fault_tolerant``,
``quantum_variational``, ``quantum_linear_algebra``, ``quantum_optimisation`` (annealer) and ``hybrid_pipeline`` (stages:
GPU prep -> QPU -> GPU post). Quantum tasks carry a ``quantum`` block (the quantum_arch workload and host times) and a
``classical_fallback`` (best classical method at the same accuracy, in GPU-module-hours: an ASSUMPTION, flagged), so the
scheduler can decide quantum versus classical on time, energy and cost - never on an assumed speed-up.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import qfeas
from .config import TASKS_FORMAT, assumptions

TASK_TYPES = ("llm_prefill_batch", "llm_decode_batch", "agent_job", "knowledge_job", "quantum_fault_tolerant",
              "quantum_variational", "quantum_linear_algebra", "quantum_optimisation", "hybrid_pipeline")
QUANTUM_TYPES = ("quantum_fault_tolerant", "quantum_variational", "quantum_linear_algebra", "quantum_optimisation")
DEFAULT_CASE = {"llm_prefill_batch": "A", "llm_decode_batch": "A", "agent_job": "B", "knowledge_job": "C"}
#: default SLO (seconds after arrival) per type when a task gives none. ASSUMPTION.
DEFAULT_SLO_S = {"llm_prefill_batch": 7200, "llm_decode_batch": 7200, "agent_job": 14400, "knowledge_job": 43200,
                 "quantum_fault_tolerant": 21600, "quantum_variational": 14400, "quantum_linear_algebra": 21600,
                 "quantum_optimisation": 3600, "hybrid_pipeline": 21600}
EVENT_TYPES = ("site_power_cap", "node_failure", "qpu_calibration", "demand_surge")
REGIONS = ("americas", "emea", "apac")


class TaskError(ValueError):
    pass


def _num(d: dict, k: str, default: float | None = None, lo: float | None = None) -> float:
    v = d.get(k, default)
    if v is None:
        raise TaskError(f"missing numeric field {k!r}")
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise TaskError(f"field {k!r} must be a number, got {v!r}")
    if lo is not None and v < lo:
        raise TaskError(f"field {k!r} must be >= {lo}, got {v}")
    return v


def default_fallback(workload: str) -> dict | None:
    fb = assumptions()["classical_fallback_defaults"].get(workload)
    if fb is None:
        return None
    if fb["module_hours"] is None:
        return {"module_hours": None, "modules": 1, "accuracy_ok": False, "note": fb["note"]}
    return dict(fb)


def normalise_task(raw: dict, index: int = 0) -> dict:
    """Validate and complete a task dict (defaults filled; unknown keys kept). Raises TaskError."""
    t = copy.deepcopy(raw)
    ty = t.get("type")
    if ty not in TASK_TYPES:
        raise TaskError(f"task {t.get('id', index)!r}: unknown type {ty!r}; known: {', '.join(TASK_TYPES)}")
    t.setdefault("id", f"t{index + 1:04d}")
    t["id"] = str(t["id"])
    t["arrival_s"] = _num(t, "arrival_s", 0.0, 0.0)
    t["priority"] = int(_num(t, "priority", 3, 1))
    if t["priority"] > 5:
        raise TaskError(f"task {t['id']}: priority must be 1..5")
    t["case"] = t.get("case") or DEFAULT_CASE.get(ty, "Q")
    if t["case"] not in ("A", "B", "C", "Q"):
        raise TaskError(f"task {t['id']}: case must be A, B, C or Q")
    if "slo_s" in t and t.get("deadline_s") is None:
        t["deadline_s"] = t["arrival_s"] + _num(t, "slo_s")
    t.pop("slo_s", None)
    if t.get("deadline_s") is None:
        t["deadline_s"] = t["arrival_s"] + DEFAULT_SLO_S[ty]
    t["deadline_s"] = float(t["deadline_s"])
    if t["deadline_s"] <= t["arrival_s"]:
        raise TaskError(f"task {t['id']}: deadline_s must be after arrival_s")
    t["home_region"] = t.get("home_region", "emea")
    if t["home_region"] not in REGIONS:
        raise TaskError(f"task {t['id']}: home_region must be one of {REGIONS}")
    t["data_gb"] = _num(t, "data_gb", 0.0, 0.0)
    t["min_success"] = _num(t, "min_success", 0.95, 0.0)
    size = t.setdefault("size", {})
    if ty == "llm_prefill_batch":
        _num(size, "requests", lo=1)
        _num(size, "prefill_tokens", 2000, 1)
        size.setdefault("max_modules", 64)
    elif ty == "llm_decode_batch":
        _num(size, "requests", lo=1)
        _num(size, "decode_tokens", 800, 1)
        size.setdefault("max_modules", 64)
    elif ty == "agent_job":
        _num(size, "steps", lo=1)
        size.setdefault("prefill_tokens_per_step", 6000)
        size.setdefault("decode_tokens_per_step", 700)
        size.setdefault("tool_wait_s_per_step", 8.0)
        size.setdefault("modules", 8)
        size.setdefault("ctx_gb", 60.0)
    elif ty == "knowledge_job":
        _num(size, "module_hours", lo=0.01)
        size.setdefault("modules", 16)
        size.setdefault("ctx_gb", 20.0)
    elif ty in QUANTUM_TYPES:
        _normalise_quantum(t, t, ty)
    elif ty == "hybrid_pipeline":
        stages = t.get("stages")
        if not isinstance(stages, list) or len(stages) < 2:
            raise TaskError(f"task {t['id']}: hybrid_pipeline needs 'stages' (at least two)")
        for i, st in enumerate(stages):
            st.setdefault("name", f"stage{i + 1}")
            st.setdefault("out_gb", 0.0)
            if st.get("kind") == "gpu":
                _num(st, "module_hours", lo=0.001)
                st.setdefault("modules", 16)
                st.setdefault("ctx_gb", 0.0)
            elif st.get("kind") == "quantum":
                _normalise_quantum(st, t, "hybrid_pipeline")
            else:
                raise TaskError(f"task {t['id']} stage {i}: kind must be 'gpu' or 'quantum'")
        if not any(s["kind"] == "quantum" for s in stages):
            raise TaskError(f"task {t['id']}: a hybrid pipeline needs at least one quantum stage")
    return t


def _normalise_quantum(holder: dict, task: dict, ty: str) -> None:
    q = holder.get("quantum")
    if not isinstance(q, dict):
        raise TaskError(f"task {task['id']}: needs a 'quantum' block")
    q.setdefault("kind", "annealer" if ty == "quantum_optimisation" else "gate")
    if q["kind"] == "gate":
        wl = q.get("workload")
        from quantum_arch import catalog
        if wl not in catalog.keys("workloads"):
            raise TaskError(f"task {task['id']}: unknown quantum_arch workload {wl!r}; known: {', '.join(catalog.keys('workloads'))}")
        q.setdefault("repeats", 1)
        q.setdefault("prep_s", 120.0)
        q.setdefault("post_s", 120.0)
        q.setdefault("mapping_quality", 0.9)
        q.setdefault("max_attempts", 2)
        if "classical_fallback" not in holder:
            holder["classical_fallback"] = default_fallback(wl)
    else:
        _num(q, "p_success_per_read", lo=1e-9)
        q.setdefault("confidence", 0.99)
        q.setdefault("prep_s", 1.0)
        q.setdefault("post_s", 0.5)
        q.setdefault("mapping_quality", 0.8)
        q.setdefault("max_attempts", 2)
        holder.setdefault("classical_fallback", {"module_hours": 0.03, "modules": 8, "accuracy_ok": True,
                                                  "note": "ASSUMPTION: strong classical solver reaches the target quality in about 10 s on 8 modules"})
    fb = holder.get("classical_fallback")
    if fb is not None:
        fb.setdefault("modules", 8)
        fb.setdefault("accuracy_ok", True)


def normalise_events(events: list[dict]) -> list[dict]:
    out = []
    for i, e in enumerate(events or []):
        e = copy.deepcopy(e)
        if e.get("type") not in EVENT_TYPES:
            raise TaskError(f"event {i}: unknown type {e.get('type')!r}; known: {', '.join(EVENT_TYPES)}")
        e["t"] = _num(e, "t", lo=0.0)
        out.append(e)
    return sorted(out, key=lambda e: (e["t"], e["type"], str(e.get("site", ""))))


def normalise_taskset(raw: dict) -> dict:
    if raw.get("format", TASKS_FORMAT) != TASKS_FORMAT:
        raise TaskError(f"unsupported task format {raw.get('format')!r}; expected {TASKS_FORMAT}")
    ts = copy.deepcopy(raw)
    ts["format"] = TASKS_FORMAT
    ts.setdefault("name", "taskset")
    ts.setdefault("description", "")
    ts["seed"] = int(ts.get("seed", 0))
    ts["horizon_s"] = float(ts.get("horizon_s", 43200.0))
    ts["start_utc_hour"] = float(ts.get("start_utc_hour", 0.0))
    ts["case"] = ts.get("case", "mix")
    ts["demand_scale"] = float(ts.get("demand_scale", 1.0))
    ts["tasks"] = [normalise_task(t, i) for i, t in enumerate(ts.get("tasks", []))]
    ids = [t["id"] for t in ts["tasks"]]
    if len(set(ids)) != len(ids):
        raise TaskError("duplicate task ids")
    ts["tasks"].sort(key=lambda t: (t["arrival_s"], t["id"]))
    ts["events"] = normalise_events(ts.get("events", []))
    return ts


def load_taskset(path_or_dict: str | Path | dict) -> dict:
    from .config import PRESET_DIR
    if isinstance(path_or_dict, dict):
        return normalise_taskset(path_or_dict)
    p = Path(path_or_dict)
    if not p.is_file():
        for cand in (PRESET_DIR / str(path_or_dict), PRESET_DIR / f"{path_or_dict}.json"):
            if cand.is_file():
                p = cand
                break
        else:
            raise FileNotFoundError(f"task file or preset {path_or_dict!r} not found")
    return normalise_taskset(json.loads(p.read_text(encoding="utf-8")))


def save_taskset(ts: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(ts, indent=1, sort_keys=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------
# Units: the schedulable items (a task, or one stage of a pipeline)
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class GpuWork:
    module_s: float            # GPU-module-seconds at speed 1.0
    modules: int               # parallelism requested
    need: str                  # prefill | decode | any
    fixed_s: float = 0.0       # sequential time that does not shrink with more modules (tool waits)
    ctx_gb: float = 0.0
    duty: float = 1.0          # dynamic-power duty while the modules are reserved


@dataclass
class Unit:
    uid: str
    task: dict
    idx: int
    n_units: int
    kind: str                           # gpu | quantum
    gpu: GpuWork | None = None
    q: dict | None = None
    fb: dict | None = None              # classical fallback: dict(module_s, modules, accuracy_ok, note) or None
    in_gb: float = 0.0
    out_gb: float = 0.0
    name: str = ""
    # dynamic
    state: str = "waiting"              # waiting | pending | running | done | rejected
    ready_t: float = 0.0
    prev_site: str | None = None        # where the previous stage ran (data location)
    prev_node: str | None = None
    node: str | None = None
    route: str | None = None
    start_t: float | None = None
    end_t: float | None = None
    decided_t: float | None = None
    reason: str = ""
    force_classical: bool = False
    attempts_used: int = 0
    n_defer: int = 0
    first_pending_t: float | None = None
    energy_fac_j: float = 0.0
    cost_usd: float = 0.0
    fallback_used: bool = False
    quantum_fail: bool = False
    transfer_usd: float = 0.0

    @property
    def priority(self) -> int:
        return self.task["priority"]

    @property
    def deadline(self) -> float:
        return self.task["deadline_s"]

    @property
    def is_last(self) -> bool:
        return self.idx == self.n_units - 1


def _fb_to_work(fb: dict | None) -> dict | None:
    if fb is None or fb.get("module_hours") is None:
        return None
    return {"module_s": float(fb["module_hours"]) * 3600.0, "modules": int(fb.get("modules", 8)), "accuracy_ok": bool(fb.get("accuracy_ok", True)),
            "note": fb.get("note", "")}


def make_units(task: dict, P: float, D: float) -> list[Unit]:
    """Turn a normalised task into units. ``P``/``D`` = prefill/decode tokens per GPU module and second of the served model."""
    ty, sz = task["type"], task["size"]
    base_in = task["data_gb"]
    if ty == "llm_prefill_batch":
        w = GpuWork(module_s=sz["requests"] * sz["prefill_tokens"] / P, modules=int(sz["max_modules"]), need="prefill", ctx_gb=float(sz.get("ctx_gb", 0)))
        return [Unit(task["id"], task, 0, 1, "gpu", gpu=w, in_gb=base_in, name="prefill batch")]
    if ty == "llm_decode_batch":
        w = GpuWork(module_s=sz["requests"] * sz["decode_tokens"] / D, modules=int(sz["max_modules"]), need="decode", ctx_gb=float(sz.get("ctx_gb", 0)))
        return [Unit(task["id"], task, 0, 1, "gpu", gpu=w, in_gb=base_in, name="decode batch")]
    if ty == "agent_job":
        work = sz["steps"] * (sz["prefill_tokens_per_step"] / P + sz["decode_tokens_per_step"] / D)
        m = int(sz["modules"])
        fixed = sz["steps"] * float(sz["tool_wait_s_per_step"])
        busy = work / m
        duty = busy / (busy + fixed) if busy + fixed > 0 else 1.0
        w = GpuWork(module_s=work, modules=m, need="any", fixed_s=fixed, ctx_gb=float(sz["ctx_gb"]), duty=duty)
        return [Unit(task["id"], task, 0, 1, "gpu", gpu=w, in_gb=base_in, name="agent job")]
    if ty == "knowledge_job":
        w = GpuWork(module_s=sz["module_hours"] * 3600.0, modules=int(sz["modules"]), need="any", ctx_gb=float(sz["ctx_gb"]))
        return [Unit(task["id"], task, 0, 1, "gpu", gpu=w, in_gb=base_in, name="knowledge job")]
    if ty in QUANTUM_TYPES:
        return [Unit(task["id"], task, 0, 1, "quantum", q=task["quantum"], fb=_fb_to_work(task.get("classical_fallback")),
                     in_gb=base_in, out_gb=float(task.get("out_gb", 0.0)), name=ty.replace("quantum_", "quantum "))]
    stages = task["stages"]
    out = []
    for i, st in enumerate(stages):
        uid = f"{task['id']}#{i + 1}"
        in_gb = base_in if i == 0 else float(stages[i - 1].get("out_gb", 0.0))
        if st["kind"] == "gpu":
            w = GpuWork(module_s=st["module_hours"] * 3600.0, modules=int(st["modules"]), need="any", ctx_gb=float(st.get("ctx_gb", 0)))
            out.append(Unit(uid, task, i, len(stages), "gpu", gpu=w, in_gb=in_gb, out_gb=float(st.get("out_gb", 0.0)), name=st["name"]))
        else:
            out.append(Unit(uid, task, i, len(stages), "quantum", q=st["quantum"], fb=_fb_to_work(st.get("classical_fallback")),
                            in_gb=in_gb, out_gb=float(st.get("out_gb", 0.0)), name=st["name"]))
    return out


def classical_alt(unit: Unit) -> GpuWork | None:
    """The classical (GPU) alternative of a quantum unit as a GpuWork, or None if there is no method at the required accuracy."""
    if unit.fb is None or not unit.fb["accuracy_ok"]:
        return None
    return GpuWork(module_s=unit.fb["module_s"], modules=unit.fb["modules"], need="any", ctx_gb=0.0)


def quantum_summary(unit: Unit) -> str:
    q = unit.q
    return q.get("workload", f"annealing p={q.get('p_success_per_read')}") if q else ""
