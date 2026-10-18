"""Cryostat model: stage cooling curves, equilibrium temperatures, wall-plug power.

A stage lifts heat ``Q`` at temperature ``T`` according to
``Q = a (T^alpha - Tbase^alpha)``: zero load sits at the base temperature, and the
catalog anchors the curve at one measured (T, power) point. ``alpha = 2`` suits
the dilution stages (cooling power ~ T^2), ``alpha = 1`` the pulse-tube stages.

Wall-plug power is reported two ways:

* **installed**: ``units * wall_power_w``. A commercial fridge draws roughly
  constant power whatever the load, so what matters is how many units the load
  needs.
* **Carnot floor**: ``sum_i Q_i (300/T_i - 1)``, the thermodynamic minimum for
  the same heat loads. The gap between the two is the headroom a better
  cryocooler could close; the floor grows by 4-5 orders of magnitude from the
  4 K stage to the mixing chamber, which is why mK heat budgets dominate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import catalog

T_ROOM = 300.0


@dataclass
class Stage:
    name: str
    t_ref_k: float
    cap_ref_w: float
    t_base_k: float
    alpha: float
    cable_len_mm: float

    @property
    def coeff(self) -> float:
        return self.cap_ref_w / (self.t_ref_k ** self.alpha - self.t_base_k ** self.alpha)

    def capacity(self, temperature_k: float) -> float:
        """Heat the stage can lift while held at ``temperature_k`` (W)."""
        if temperature_k <= self.t_base_k:
            return 0.0
        return self.coeff * (temperature_k ** self.alpha - self.t_base_k ** self.alpha)

    def temperature(self, load_w: float) -> float:
        """Equilibrium plate temperature under ``load_w`` (K)."""
        return (max(load_w, 0.0) / self.coeff + self.t_base_k ** self.alpha) ** (1.0 / self.alpha)


@dataclass
class Fridge:
    key: str
    label: str
    stages: list[Stage]
    wall_power_w: float
    max_coax_lines: int
    source: str = ""
    capacity_scale: float = 1.0
    #: Operating temperature the controller holds each stage at (K).
    targets_k: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_catalog(cls, key: str, capacity_scale: float = 1.0,
                     targets_k: dict[str, float] | None = None) -> "Fridge":
        raw = catalog.entry("fridges", key)
        fridge = cls(key=key, label=raw["label"],
                     stages=[Stage(**s) for s in raw["stages"]],
                     wall_power_w=float(raw["wall_power_w"]),
                     max_coax_lines=int(raw["max_coax_lines"]),
                     source=raw.get("source", ""),
                     capacity_scale=capacity_scale)
        for s in fridge.stages:
            fridge.targets_k[s.name] = s.t_ref_k
        for name, t in (targets_k or {}).items():
            if name not in fridge.targets_k:
                raise KeyError(f"cryostat {key!r} has no stage {name!r}")
            fridge.targets_k[name] = float(t)
        return fridge

    @property
    def names(self) -> list[str]:
        return [s.name for s in self.stages]

    def index(self, name: str) -> int:
        try:
            return self.names.index(name)
        except ValueError:
            raise KeyError(f"stage {name!r} not in cryostat {self.key!r} ({', '.join(self.names)})") from None

    def stage(self, name: str) -> Stage:
        return self.stages[self.index(name)]

    def capacity(self, name: str, temperature_k: float | None = None) -> float:
        t = self.targets_k[name] if temperature_k is None else temperature_k
        return self.stage(name).capacity(t) * self.capacity_scale


def carnot_floor_w(loads_w: dict[str, float], temps_k: dict[str, float]) -> float:
    """Minimum electrical power to lift ``loads_w`` from ``temps_k`` to 300 K."""
    return sum(q * (T_ROOM / temps_k[name] - 1.0) for name, q in loads_w.items() if q > 0)


@dataclass
class StageResult:
    name: str
    target_k: float
    temperature_k: float
    load_w: float
    capacity_w: float
    passive_w: float
    active_w: float
    components_w: float
    by_source: dict[str, float]

    @property
    def utilisation(self) -> float:
        return self.load_w / self.capacity_w if self.capacity_w > 0 else math.inf

    @property
    def overloaded(self) -> bool:
        return self.load_w > self.capacity_w * (1 + 1e-9)


@dataclass
class CryoResult:
    fridge: Fridge
    stages: list[StageResult]
    units_needed: int
    units_for_heat: int
    units_for_lines: int
    n_lines: int
    wall_power_w: float
    carnot_floor_w: float

    @property
    def feasible_single_unit(self) -> bool:
        return self.units_needed <= 1

    def stage_result(self, name: str) -> StageResult:
        return next(s for s in self.stages if s.name == name)


def solve(fridge: Fridge, load_fn, n_lines: int) -> CryoResult:
    """Heat budget at the design point and the plate temperatures it implies.

    ``load_fn(temps_k) -> {stage: {source_label: watts}}`` returns the loads with
    every stage held at its *target* temperature, which is what a designer
    budgets against. A stage with spare capacity stays at its target; an
    overloaded one would settle at ``Stage.temperature(load)``. That estimate is
    deliberately not fed back into the cable conduction (a warmer plate makes
    every cable conduct more), so it understates a runaway; the overload flag
    and the number of fridge units are the quantities to act on.
    """
    temps = dict(fridge.targets_k)
    sources = load_fn(temps)
    stage_temps = {}
    for i, st in enumerate(fridge.stages):
        q = sum(sources.get(st.name, {}).values())
        t_eq = st.temperature(q / fridge.capacity_scale)
        warmer = fridge.stages[i - 1].name if i else None
        ceiling = 0.95 * stage_temps[warmer] if warmer else T_ROOM
        stage_temps[st.name] = min(max(fridge.targets_k[st.name], t_eq), ceiling)
    temps = stage_temps

    results = []
    for st in fridge.stages:
        by_source = sources.get(st.name, {})
        passive = sum(v for k, v in by_source.items() if k.startswith("passive"))
        active = sum(v for k, v in by_source.items() if k.startswith("active"))
        total = sum(by_source.values())
        results.append(StageResult(
            name=st.name, target_k=fridge.targets_k[st.name], temperature_k=temps[st.name],
            load_w=total, capacity_w=fridge.capacity(st.name), passive_w=passive,
            active_w=active, components_w=total - passive - active, by_source=dict(by_source)))

    if fridge.stages:
        units_heat = max(1, *(math.ceil(r.load_w / r.capacity_w) if r.capacity_w > 0 else 1
                              for r in results))
        units_lines = max(1, math.ceil(n_lines / (fridge.max_coax_lines * fridge.capacity_scale))) if n_lines else 1
        units = max(units_heat, units_lines)
    else:
        units_heat = units_lines = units = 0
    loads = {r.name: r.load_w for r in results}
    # With ``units`` fridges each stage carries load/units at the target T.
    return CryoResult(
        fridge=fridge, stages=results, units_needed=units, units_for_heat=units_heat,
        units_for_lines=units_lines, n_lines=n_lines,
        wall_power_w=units * fridge.wall_power_w * fridge.capacity_scale,
        carnot_floor_w=carnot_floor_w(loads, {r.name: r.temperature_k for r in results}))
