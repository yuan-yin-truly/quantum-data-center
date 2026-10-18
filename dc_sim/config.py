"""Loading of the assumptions file and small shared helpers (no state)."""

from __future__ import annotations

import copy
import json
import math
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parent
DATA = PKG / "data"
PRESET_DIR = PKG / "presets"
EXAMPLE_RUNS = PKG / "example_runs"

FLEET_FORMAT = "dc_sim.fleet/1"
TASKS_FORMAT = "dc_sim.tasks/1"
TRACE_FORMAT = "dc_sim.trace/1"


@lru_cache(maxsize=None)
def _assumptions() -> dict[str, Any]:
    return json.loads((DATA / "assumptions.json").read_text(encoding="utf-8"))


def assumptions() -> dict[str, Any]:
    """A private copy of data/assumptions.json."""
    return copy.deepcopy(_assumptions())


def deep_merge(base: dict, over: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def stable_seed(*parts: Any) -> int:
    """Deterministic 32-bit seed from arbitrary parts (independent of PYTHONHASHSEED and of call order)."""
    return zlib.crc32("|".join(str(p) for p in parts).encode("utf-8")) & 0xFFFFFFFF


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def rtt_s(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Round-trip time: 4 ms switching + great-circle distance at ~66 km per ms (fibre, 1.5 route factor)."""
    return 0.004 + haversine_km(lat1, lon1, lat2, lon2) / 66.0 / 1000.0


def clean_json(o: Any) -> Any:
    """Make numpy / inf / nan values JSON-safe."""
    import numpy as np
    if isinstance(o, dict):
        return {str(k): clean_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_json(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float):
        if math.isnan(o):
            return None
        if math.isinf(o):
            return 1e308 if o > 0 else -1e308
    return o


def fmt_time(s: float) -> str:
    s = float(s)
    if s < 120:
        return f"{s:.0f} s"
    if s < 7200:
        return f"{s / 60:.1f} min"
    if s < 172800:
        return f"{s / 3600:.1f} h"
    return f"{s / 86400:.1f} d"


def fmt_energy(j: float) -> str:
    kwh = j / 3.6e6
    for scale, unit in ((1e6, "GWh"), (1e3, "MWh"), (1.0, "kWh")):
        if kwh >= scale:
            return f"{kwh / scale:.3g} {unit}"
    return f"{j:.3g} J" if j < 3.6e3 else f"{kwh * 1000:.3g} Wh"


def fmt_usd(x: float) -> str:
    a = abs(x)
    for scale, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= scale:
            return f"${x / scale:.3g}{unit}"
    return f"${x:.3g}"
