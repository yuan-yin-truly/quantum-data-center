"""Physical error budget, error-correcting codes and logical computing power.

Everything here is a closed-form resource model, in the spirit of the Azure
Quantum Resource Estimator, not a circuit-level simulation:

* the effective physical error ``p_eff`` combines gate, measurement, reset and
  idle errors of one syndrome cycle;
* a code turns ``p_eff`` and a distance ``d`` into a logical error per round,
  ``p_L = A (p/p_th)^e(d)``, and into physical qubits per logical qubit;
* *capability* mode asks what a chip of N physical qubits offers
  (logical qubits, logical clock, rQOPS);
* *workload* mode asks what a given algorithm needs (distance, factories,
  runtime) on that chip.

rQOPS (reliable quantum operations per second) is logical qubits times logical
clock rate, quoted together with the logical error rate it was reached at.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import catalog


@dataclass
class ErrorBudget:
    cycle_s: float
    p_eff: float
    e_idle: float
    parts: dict[str, float]
    #: Per-qubit, per-cycle probability of an error the code cannot correct (residual bit flips of
    #: biased-noise qubits). Zero for ordinary qubits.
    p_bitflip: float = 0.0


def error_budget(m: dict) -> ErrorBudget:
    """Syndrome-cycle time and effective physical error rate of a modality dict.

    ``p_eff = e_2q + 0.25 (2 e_1q + e_meas + e_reset) + 0.25 e_idle``: the two-qubit
    gate enters in full (four per cycle, each able to flip a syndrome), the
    single-qubit, measurement and reset errors at quarter weight, matching how
    often they touch the same check. ``e_idle`` is half the non-gate part of the
    cycle divided by T2. Calibrated so that today's best superconducting
    parameters give an error-suppression factor Lambda of about 2.
    """
    ns = 1e-9
    cycle = (4 * m["t_2q_ns"] + 2 * m["t_1q_ns"] + m["t_meas_ns"] + m["t_reset_ns"]
             + m.get("cycle_overhead_ns", 0.0)) * ns
    idle_window = (m["t_meas_ns"] + m["t_reset_ns"] + m.get("cycle_overhead_ns", 0.0)) * ns
    e_idle = 0.5 * idle_window / (m["t2_us"] * 1e-6)
    parts = {
        "two_qubit": m["err_2q"],
        "single_qubit": 0.25 * 2 * m["err_1q"],
        "measurement": 0.25 * m["err_meas"],
        "reset": 0.25 * m["err_reset"],
        "idle": 0.25 * e_idle,
    }
    return ErrorBudget(cycle_s=cycle, p_eff=sum(parts.values()), e_idle=e_idle, parts=parts,
                       p_bitflip=float(m.get("err_bitflip", 0.0)))


def _eval_d(expr: str, d: int) -> float:
    """Evaluate a catalog formula in the distance ``d`` (arithmetic only)."""
    if not set(expr) <= set("0123456789+-*/(). d"):
        raise ValueError(f"unsafe formula {expr!r}")
    return float(eval(expr, {"__builtins__": {}}, {"d": d}))  # noqa: S307 - character-whitelisted


class Code:
    def __init__(self, key: str):
        raw = catalog.entry("codes", key)
        self.key = key
        self.raw = raw
        self.label = raw["label"]
        self.threshold = raw["threshold"]
        self.prefactor = raw["prefactor"]
        self.needs_nonlocal = raw["needs_nonlocal"]
        self.layout_overhead = raw["layout_overhead"]
        self.factory_tiles = raw["ccz_factory_tiles"]
        self.factory_cycles_per_d = raw["ccz_factory_cycles_per_d"]
        self.bitflip_floor = bool(raw.get("bitflip_floor", False))
        self.default_decoder = raw.get("default_decoder")

    def distances(self, d_max: int = 101) -> list[int]:
        d = self.raw["distances"]
        if d == "odd":
            return list(range(3, d_max + 1, 2))
        return list(d)

    def tile_qubits(self, d: int) -> float:
        """Physical qubits per logical qubit (one patch / share of a block)."""
        if self.key == "surface":
            return 2.0 * d * d - 1
        if "tile_formula" in self.raw:
            return _eval_d(self.raw["tile_formula"], d)
        block = self.raw["blocks"][str(d)]
        return 2.0 * block["n"] / block["k"]

    def logical_error_per_round(self, p: float, d: int, p_bitflip: float = 0.0) -> float:
        """``A (p/p_th)^e(d)``, plus for biased-noise codes the uncorrectable floor ``tile * p_bitflip``."""
        ratio = p / self.threshold
        exp = _eval_d(self.raw["exponent"], d) if self.key not in ("surface", "bivariate_bicycle") else (
            (d + 1) / 2 if self.key == "surface" else d / 2)
        floor = self.tile_qubits(d) * p_bitflip if self.bitflip_floor else 0.0
        return min(1.0, self.prefactor * ratio ** exp + floor)


@dataclass
class Capability:
    feasible: bool
    reason: str
    code: str
    distance: int | None = None
    logical_qubits: int = 0
    tile_qubits: float = 0.0
    logical_error_per_op: float | None = None
    logical_clock_hz: float = 0.0
    rqops: float = 0.0
    factories: int = 0
    lam: float = 0.0
    active_physical_qubits: int = 0


def capability(code: Code, budget: ErrorBudget, n_phys: int, target_error: float = 1e-12,
               factory_fraction: float = 0.3, d_max: int = 101) -> Capability:
    """What a chip with ``n_phys`` physical qubits offers at ``target_error`` per logical op.

    A logical operation lasts ``d`` rounds, so its error is ``d * p_L(round)``.
    """
    lam = code.threshold / budget.p_eff
    if budget.p_eff >= code.threshold:
        return Capability(False, f"p_eff={budget.p_eff:.2e} is not below the {code.label} threshold "
                          f"({code.threshold:.1e}); error correction cannot help", code.key, lam=lam)
    for d in code.distances(d_max):
        if d * code.logical_error_per_round(budget.p_eff, d, budget.p_bitflip) <= target_error:
            break
    else:
        why = f"needs a distance above {d_max}"
        if code.bitflip_floor and budget.p_bitflip > 0:
            why += f" (or the residual bit-flip floor {budget.p_bitflip:.0e} per qubit-cycle is too high for this target)"
        return Capability(False, f"target {target_error:.0e} {why}", code.key, lam=lam)
    tile = code.tile_qubits(d)
    tiles = int(n_phys // tile)
    logical = int(tiles * (1.0 - factory_fraction) // code.layout_overhead)
    if logical < 1:
        return Capability(False, f"{n_phys:,} physical qubits are fewer than one logical qubit at d={d} "
                          f"({tile:.0f} each, x{code.layout_overhead} layout)", code.key, distance=d,
                          tile_qubits=tile, lam=lam)
    clock = 1.0 / (d * budget.cycle_s)
    factories = int(tiles * factory_fraction // code.factory_tiles)
    return Capability(True, "ok", code.key, distance=d, logical_qubits=logical, tile_qubits=tile,
                      logical_error_per_op=d * code.logical_error_per_round(budget.p_eff, d, budget.p_bitflip),
                      logical_clock_hz=clock, rqops=logical * clock, factories=factories, lam=lam,
                      active_physical_qubits=int(tiles * tile))


@dataclass
class WorkloadPlan:
    feasible: bool
    reason: str
    distance: int | None = None
    algorithm_tiles: int = 0
    factories: int = 0
    runtime_s: float = 0.0
    physical_qubits_used: int = 0
    total_logical_error: float = 0.0
    reference_qubits: int = 0
    toffoli_time_s: float = 0.0
    bound: str = ""


def plan_workload(code: Code, budget: ErrorBudget, n_phys: int, logical_qubits: int,
                  toffoli_count: float, toffoli_depth: float, error_budget: float,
                  reaction_time_s: float, d_max: int = 101) -> WorkloadPlan:
    """Smallest-distance plan for a fault-tolerant algorithm on ``n_phys`` qubits.

    The algorithm occupies ``logical_qubits * layout_overhead`` tiles; every
    remaining tile group of ``factory_tiles`` is a CCZ factory yielding one
    Toffoli per ``factory_cycles_per_d * d`` rounds. A Toffoli also cannot
    finish faster than the control reaction time (measure, decode, feed
    forward). Total error is tiles x rounds x p_L(round).
    """
    if budget.p_eff >= code.threshold:
        return WorkloadPlan(False, f"p_eff={budget.p_eff:.2e} is not below threshold {code.threshold:.1e}")
    alg_tiles = math.ceil(logical_qubits * code.layout_overhead)
    reference_qubits = 0
    last_reason = "no distance satisfies the error budget"
    for d in code.distances(d_max):
        p_round = code.logical_error_per_round(budget.p_eff, d, budget.p_bitflip)
        tile = code.tile_qubits(d)
        total_tiles = int(n_phys // tile)
        # Qubits needed for a reference design with 10 factories at the distance the error budget wants.
        if not reference_qubits:
            ref_rounds = toffoli_count * code.factory_cycles_per_d * d / 10
            if (alg_tiles + 10 * code.factory_tiles) * ref_rounds * p_round <= error_budget:
                reference_qubits = int((alg_tiles + 10 * code.factory_tiles) * tile)
        factories = (total_tiles - alg_tiles) // code.factory_tiles
        if factories < 1:
            last_reason = (f"{n_phys:,} qubits hold only {total_tiles:,} tiles at d={d}; the algorithm needs "
                           f"{alg_tiles:,} plus a {code.factory_tiles}-tile factory")
            continue
        per_toffoli = code.factory_cycles_per_d * d * budget.cycle_s / factories
        factory_bound = toffoli_count * per_toffoli
        reaction_bound = toffoli_depth * reaction_time_s
        runtime = max(factory_bound, reaction_bound)
        rounds = runtime / budget.cycle_s
        error = (alg_tiles + factories * code.factory_tiles) * rounds * p_round
        if error <= error_budget:
            return WorkloadPlan(True, "ok", distance=d, algorithm_tiles=alg_tiles, factories=factories,
                                runtime_s=runtime, physical_qubits_used=int(
                                    (alg_tiles + factories * code.factory_tiles) * tile),
                                total_logical_error=error, reference_qubits=reference_qubits,
                                toffoli_time_s=runtime / toffoli_count,
                                bound="reaction time" if reaction_bound > factory_bound else "factory throughput")
        last_reason = f"d={d}: total logical error {error:.2e} exceeds the budget {error_budget:.0e}"
    return WorkloadPlan(False, last_reason, reference_qubits=reference_qubits)


def syndrome_bits_per_second(n_active_phys: int, cycle_s: float) -> float:
    """Ancilla measurement outcomes produced per second (about half the qubits are checks)."""
    return 0.5 * n_active_phys / cycle_s
