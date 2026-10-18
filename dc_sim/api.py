"""Public functions: ``simulate`` (for design_loop and other tools), ``run_policy`` and ``compare_policies``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import PRESET_DIR
from .engine import Engine
from .scheduler import POLICIES


def simulate(config: Any = None, tasks: Any = None, policy: str = "batch", seed: int | None = None, tick_s: float | None = None) -> dict[str, Any]:
    """Run one deterministic simulation and return the metrics dict.

    ``config`` = fleet (path, dict, ``Fleet`` or None for the default fleet), ``tasks`` = task-spec file/dict/preset name,
    ``policy`` in fifo|greedy|batch|gpu_only, ``seed`` overrides the task file's seed. Same inputs -> identical output.
    """
    return Engine(config, tasks, policy, seed=seed, tick_s=tick_s).run()


def run_policy(config: Any, tasks: Any, policy: str, seed: int | None = None, tick_s: float | None = None) -> Engine:
    eng = Engine(config, tasks, policy, seed=seed, tick_s=tick_s)
    eng.run()
    return eng


def compare_policies(config: Any, tasks: Any, policies: tuple[str, ...] = POLICIES, seed: int | None = None, tick_s: float | None = None,
                     reference: bool = True) -> dict[str, Any]:
    """All policies on the same tasks (+ the GPU-only reference fleet with the gpu_only policy) -> dict name -> Engine."""
    from .fleet import Fleet
    fleet = Fleet.load(config)
    engines: dict[str, Engine] = {}
    for p in policies:
        engines[p] = run_policy(fleet, tasks, p, seed, tick_s)
    if reference:
        engines["ref_gpu_only_fleet"] = run_policy(fleet.without_quantum(), tasks, "gpu_only", seed, tick_s)
    return engines


def list_presets() -> list[str]:
    return sorted(p.stem for p in PRESET_DIR.glob("*.json"))
