"""Scaling sweeps: how an architecture behaves as the qubit count grows."""

from __future__ import annotations

import numpy as np

from .architecture import Architecture, Result, evaluate


def _row(res: Result) -> dict:
    return {
        "n": res.arch["n_qubits"],
        "power_w": res.total_power_w,
        "fridges": res.metrics["fridge_units"],
        "utilisation": {s.name: s.utilisation for s in res.cryo.stages} if res.cryo else {},
        "line_units": res.cryo.units_for_lines if res.cryo else 0,
        "logical_qubits": res.capability.logical_qubits,
        "rqops": res.capability.rqops,
        "energy_per_logical_op_j": res.metrics["energy_per_logical_op_j"],
    }


def sweep_qubits(arch: Architecture, counts) -> list[dict]:
    return [_row(evaluate(arch.with_overrides(n_qubits=int(n), plates=False))) for n in counts]


def log_counts(lo: float, hi: float, per_decade: int = 4) -> list[int]:
    decades = np.log10(hi) - np.log10(lo)
    return sorted({int(round(v)) for v in np.geomspace(lo, hi, max(2, int(decades * per_decade) + 1))})


def fits_single_fridge(res: Result) -> bool:
    return bool(res.cryo) and res.cryo.feasible_single_unit


def max_qubits_single_fridge(arch: Architecture, lo: int = 4, hi: int = 10_000_000) -> dict:
    """Largest qubit count one fridge can serve (bisection; load grows monotonically with N).

    Returns the count and the stage (or "lines") that gives out first beyond it.
    """
    def ok(n: int) -> bool:
        return fits_single_fridge(evaluate(arch.with_overrides(n_qubits=n, plates=False)))

    if not ok(lo):
        return {"max_qubits": 0, "limit": _limit(arch, lo)}
    if ok(hi):
        return {"max_qubits": hi, "limit": "none below the search ceiling"}
    while hi - lo > max(1, lo // 200):
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return {"max_qubits": lo, "limit": _limit(arch, hi)}


def _limit(arch: Architecture, n: int) -> str:
    res = evaluate(arch.with_overrides(n_qubits=n, plates=False))
    if not res.cryo:
        return "no cryostat"
    worst = max(res.cryo.stages, key=lambda s: s.utilisation)
    if res.cryo.units_for_lines > 1 and res.cryo.units_for_lines >= res.cryo.units_for_heat:
        return "line count"
    return worst.name
