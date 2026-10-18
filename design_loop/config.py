"""Run configuration: defaults, merging, loading, snapshots."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .objectives import DEFAULT_CONSTRAINTS, DEFAULT_OBJECTIVES

DEFAULT_CONFIG: dict[str, Any] = {
    "name": "design_loop_run",
    "seed": 2035,
    "space": "default",                        # "default" | path to a JSON/YAML space | inline space dict
    "budget": {
        "max_generations": 6,
        "max_designs": 200,                     # designs registered in the archive
        "max_wallclock_s": 3600,
        "max_hotspot_runs": 12,                 # real HotSpot runs (each ~1 min under emulation)
        "stagnation_generations": 3,            # stop after this many generations without front/ideal-point progress
        "hotspot_exhausted_stops": True,
    },
    "population": {
        "candidates_per_generation": 24,
        "hotspot_per_generation": 3,            # successive halving: only the best screened front members get HotSpot
        "layout_search_per_generation": 2,      # surrogate-guided local search around legal layouts
        "layout_search_steps": 30,
        "operator_shares": {"mutate": 0.35, "crossover": 0.15, "neighbour": 0.25, "restart": 0.10, "layout": 0.15},
        "p_layout_move": 0.25,                  # chance that a mutation also moves a die
    },
    "objectives": copy.deepcopy(DEFAULT_OBJECTIVES),
    "constraints": dict(DEFAULT_CONSTRAINTS),
    "weights": {},                              # scalarised-ranking weights per objective (default: the objectives' own)
    "evaluators": {
        "quantum": {},                           # max_fridge_units, min_task_p_accept (also read from constraints)
        "package": {"hotspot": "auto",           # auto | never | always
                    "grid": 64, "concurrency": 2, "try_start_docker": False,
                    "max_gpu_load_factor": 1.0, "traffic_coupling": 0.0},
        "datacentre": {"force_stand_in": False},   # plus any key of evaluators.datacentre.DEFAULT_CONFIG
    },
    "final": {"hotspot_finalists": 6},
}


def deep_merge(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def load_config(path_or_dict: str | Path | dict | None) -> dict[str, Any]:
    if path_or_dict is None:
        return copy.deepcopy(DEFAULT_CONFIG)
    if isinstance(path_or_dict, dict):
        raw = path_or_dict
    else:
        p = Path(path_or_dict)
        text = p.read_text(encoding="utf-8")
        if p.suffix in (".yaml", ".yml"):
            import yaml                                     # type: ignore
            raw = yaml.safe_load(text)
        else:
            raw = json.loads(text)
    cfg = deep_merge(DEFAULT_CONFIG, {k: v for k, v in raw.items() if k not in ("objectives",)})
    if "objectives" in raw:
        cfg["objectives"] = raw["objectives"]
    return cfg
