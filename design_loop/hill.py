"""Adapter for the challenge judge's own Python modules (legality, power maps, interconnect heat).

The hill modules (``geometry``, ``interconnect``, ``generate_workloads``, ``verify_submission`` and, in the
LOCAL variant, ``hybrid_power``) are imported from ONE hill directory, never copied or re-implemented, and
never edited. The adapter degrades gracefully: without the variant there is no ``hybrid_power`` (so only
unmodified-power layouts can be evaluated); without any hill directory nothing package-related runs.
"""

from __future__ import annotations

import copy
import importlib
import json
import sys
import threading
from pathlib import Path

from .paths import find_hill

_LOCK = threading.Lock()
_HILL: "HillAdapter | None | bool" = False     # False = not tried yet


class HillUnavailable(RuntimeError):
    pass


class HillAdapter:
    DIES = ("G0", "G1", "G2", "G3", "H0", "H1", "H2", "H3")
    GPUS = ("G0", "G1", "G2", "G3")

    def __init__(self, root: Path):
        self.root = Path(root)
        sys.dont_write_bytecode = True       # never write __pycache__ into the (read-only by convention) hill directory
        self.flavor = "quantum-variant" if (self.root / "hybrid_power.py").is_file() else "original"
        if str(self.root) not in sys.path:
            sys.path.insert(0, str(self.root))
        try:
            self.geometry = importlib.import_module("geometry")
            self.interconnect = importlib.import_module("interconnect")
            self.generate_workloads = importlib.import_module("generate_workloads")
            self.verify_submission = importlib.import_module("verify_submission")
        except ImportError as exc:                               # pragma: no cover
            raise HillUnavailable(f"cannot import the hill modules from {self.root}: {exc}") from exc
        self.hybrid_power = None
        if self.flavor == "quantum-variant":
            try:
                self.hybrid_power = importlib.import_module("hybrid_power")
            except ImportError:                                  # pragma: no cover
                self.flavor = "original"
        self.spec = json.loads((self.root / "challenge_spec.json").read_text())
        self.portable = self.generate_workloads.generate(self.spec)
        self.workloads = list(self.spec["workloads"])
        self.interposer = tuple(self.spec["interposer_mm"])
        self.dir_baseline = self.root / "examples" / "baseline" / "submission.json"

    @property
    def supports_modifiers(self) -> bool:
        return self.hybrid_power is not None

    # ------------------------------------------------------------------ legality
    def legality(self, layout: dict) -> tuple[bool, str, dict | None]:
        """The judge's own ``validate_layout`` (geometry, ports, routing, bandwidth budget)."""
        try:
            lay = {d: [float(layout[d][0]), float(layout[d][1])] for d in self.DIES}
            routing = self.geometry.validate_layout(self.spec, lay)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            return False, str(exc), None
        return True, "ok", routing

    def die_box(self, layout: dict, die: str):
        return self.geometry.die_box(self.spec, layout, die)

    def seed_layouts(self) -> dict[str, dict]:
        """Known layouts: the hill's baseline example, the spec's example layouts and its random layout."""
        out: dict[str, dict] = {}
        if self.dir_baseline.is_file():
            out["baseline_example"] = json.loads(self.dir_baseline.read_text())["placements_mm"]
        for name, lay in self.spec.get("example_layouts_mm", {}).items():
            out[name] = lay
        rl = self.root / "random_layout.json"
        if rl.is_file():
            try:
                data = json.loads(rl.read_text())
                for k, v in data.items():
                    if isinstance(v, dict) and "placements_mm" in v:
                        out[k] = v["placements_mm"]
            except (ValueError, OSError):                        # pragma: no cover
                pass
        return {k: v for k, v in out.items() if self.legality(v)[0]}

    # ------------------------------------------------------------------ power
    def apply(self, modifiers: dict | None):
        """(spec, portable) with the modifiers applied (copies); identity when there are none."""
        if not modifiers or self.hybrid_power is None:
            return self.spec, self.portable
        return self.hybrid_power.apply_modifiers(self.spec, self.portable, modifiers)

    def heat(self, layout: dict, routing: dict, modifiers: dict | None = None) -> dict:
        """Per workload ``combined_heat`` (die maps in W, interposer tiles in W, totals)."""
        spec, portable = self.apply(modifiers)
        out = {}
        for w, data in portable["workloads"].items():
            out[w] = self.interconnect.combined_heat(spec, w, data["power_maps_w"], layout, routing)
        return out

    def build_modifiers(self, **kw) -> dict:
        if self.hybrid_power is None:
            raise HillUnavailable("the LOCAL quantum variant (hybrid_power.py) is not present")
        return self.hybrid_power.build_modifiers(self.spec, self.portable, **kw)

    def is_identity(self, modifiers: dict | None) -> bool:
        if self.hybrid_power is None:
            return not modifiers
        return self.hybrid_power.is_identity(modifiers)

    def base_die_totals(self) -> dict[str, dict[str, float]]:
        return copy.deepcopy({w: d["per_die_total_w"] for w, d in self.portable["workloads"].items()})


def get_hill() -> HillAdapter | None:
    """Singleton; ``None`` if no hill directory exists (callers then degrade)."""
    global _HILL
    with _LOCK:
        if _HILL is False:
            root = find_hill()
            try:
                _HILL = HillAdapter(root) if root else None
            except HillUnavailable:
                _HILL = None
        return _HILL                                              # type: ignore[return-value]


def reset_hill(value=False) -> None:
    """Test hook: forget (or force) the singleton."""
    global _HILL
    with _LOCK:
        _HILL = value
