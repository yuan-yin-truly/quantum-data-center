"""Placement moves on the interposer. Every proposal is checked with the judge's own ``validate_layout``."""

from __future__ import annotations

import random
from typing import Callable

from .genes import DIES
from .hill import HillAdapter

GPUS = ("G0", "G1", "G2", "G3")
HBMS = ("H0", "H1", "H2", "H3")


def _clip(hill: HillAdapter, layout: dict, die: str, x: float, y: float, grid: float):
    W, H = hill.interposer
    w, h = hill.spec["dies"][die]["size_mm"]
    e = hill.spec["edge_clearance_mm"]
    x = min(max(x, e), W - e - w)
    y = min(max(y, e), H - e - h)
    return [round(round(x / grid) * grid, 6), round(round(y / grid) * grid, 6)]


def move_dies(hill: HillAdapter, layout: dict, rng: random.Random, step: float, n_dies: int | None = None,
              grid: float = 0.05) -> tuple[dict, str]:
    """Shift 1-2 dies by a Gaussian step (mm)."""
    n = n_dies or rng.choice([1, 1, 2])
    dies = rng.sample(DIES, n)
    new = {d: list(v) for d, v in layout.items()}
    for d in dies:
        new[d] = _clip(hill, new, d, new[d][0] + rng.gauss(0, step), new[d][1] + rng.gauss(0, step), grid)
    return new, "move:" + "+".join(sorted(dies))


def mirror(hill: HillAdapter, layout: dict, axis: str, grid: float = 0.05) -> tuple[dict, str]:
    """Mirror the whole layout (dies keep their identity and fixed internal power-map orientation)."""
    W, H = hill.interposer
    new = {}
    for d, (x, y) in layout.items():
        w, h = hill.spec["dies"][d]["size_mm"]
        new[d] = [round(round((W - x - w if axis == "x" else x) / grid) * grid, 6),
                  round(round((H - y - h if axis == "y" else y) / grid) * grid, 6)]
    return new, f"mirror_{axis}"


def swap(layout: dict, a: str, b: str) -> tuple[dict, str]:
    new = {d: list(v) for d, v in layout.items()}
    new[a], new[b] = list(layout[b]), list(layout[a])
    return new, f"swap:{a}{b}"


def propose_layout(hill: HillAdapter, layout: dict, rng: random.Random, step: float = 1.5, grid: float = 0.05,
                   tries: int = 25) -> tuple[dict, str] | None:
    """A LEGAL neighbour of ``layout`` (None if none found within ``tries``)."""
    for _ in range(tries):
        r = rng.random()
        if r < 0.80:
            cand, how = move_dies(hill, layout, rng, step * rng.choice([0.4, 1.0, 1.0, 2.0]), grid=grid)
        elif r < 0.88:
            cand, how = mirror(hill, layout, rng.choice("xy"), grid)
        elif r < 0.94:
            cand, how = swap(layout, *rng.sample(GPUS, 2))
        else:
            cand, how = swap(layout, *rng.sample(HBMS, 2))
        if cand != layout and hill.legality(cand)[0]:
            return cand, how
    return None


def random_layout(hill: HillAdapter, seeds: dict[str, dict], rng: random.Random, step: float = 2.5,
                  grid: float = 0.05, moves: int = 6) -> tuple[dict, str] | None:
    """Random-restart layout: a short random walk from a known legal layout."""
    if not seeds:
        return None
    name = rng.choice(sorted(seeds))
    cur = seeds[name]
    for _ in range(moves):
        p = propose_layout(hill, cur, rng, step, grid, tries=10)
        if p:
            cur = p[0]
    return cur, f"restart_from:{name}"


def local_search(hill: HillAdapter, layout: dict, score: Callable[[dict], float], rng: random.Random,
                 steps: int = 40, step: float = 1.2, grid: float = 0.05) -> tuple[dict, float, int]:
    """Greedy hill climb on ``score`` (lower is better) over legal neighbours.

    Returns ``(best layout, best score, evaluations)``. Step size halves when no improvement is found.
    """
    best, best_s = layout, score(layout)
    evals = 1
    cur_step = step
    for _ in range(steps):
        p = propose_layout(hill, best, rng, cur_step, grid, tries=8)
        if not p:
            cur_step *= 0.7
            continue
        s = score(p[0])
        evals += 1
        if s < best_s - 1e-9:
            best, best_s = p[0], s
        else:
            cur_step = max(0.25, cur_step * 0.93)
    return best, best_s, evals
