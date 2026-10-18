"""Steady-state heat spreading on a cold plate or chip, with k(T) and boundary resistance.

HotSpot assumes temperature-independent material constants, which is fine at
300 K and wrong at cryogenic temperatures, where silicon conductivity changes by
orders of magnitude between 20 mK and 25 K. This solver keeps the repo's
spirit (power maps in, temperature map out) with:

* one conducting layer (a die, board or plate) of thickness ``t`` meshed in
  square cells;
* conductivity ``k(T)`` from :mod:`materials`, face values by harmonic mean;
* heat leaving through a boundary contact to the stage at ``T_stage``, with a
  differential conductance ``h(T) = h0 (T/T0)^n`` (so the heat flux is
  ``q = h0/(T0^n (n+1)) (T^(n+1) - Ts^(n+1))``; ``n = 3`` is Kapitza-like,
  pressed joints are closer to ``n = 1..2``);
* Picard iteration on the nonlinearities and a sparse direct solve.

Total heat leaving through the contact equals the injected power, which the
result reports as a conservation check.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

from . import materials


@dataclass
class Source:
    name: str
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float
    power_w: float
    #: Relative amplitude of a Gaussian hot spot at the source centre (0 = uniform).
    hotspot: float = 0.0


@dataclass
class Contact:
    #: Differential conductance per area at ``t0_k`` in W/(K cm^2).
    h0_w_per_k_cm2: float = 1.0
    t0_k: float = 4.0
    exponent: float = 2.0

    def flux(self, t, t_stage):
        """Heat flux (W/m^2) through the contact at plate temperature ``t``."""
        a = self.h0_w_per_k_cm2 * 1e4 / (self.t0_k ** self.exponent * (self.exponent + 1))
        return a * (np.power(t, self.exponent + 1) - t_stage ** (self.exponent + 1))

    def effective_h(self, t, t_stage):
        """Secant conductance q/(T - Ts) in W/(K m^2)."""
        dt = t - t_stage
        small = np.abs(dt) < 1e-9 * max(t_stage, 1e-6)
        safe = np.where(small, 1.0, dt)
        secant = self.flux(t, t_stage) / safe
        tangent = self.h0_w_per_k_cm2 * 1e4 * (np.maximum(t_stage, 1e-9) / self.t0_k) ** self.exponent
        return np.where(small, tangent, secant)


@dataclass
class Plate:
    name: str
    stage: str
    t_stage_k: float
    size_mm: tuple[float, float]
    thickness_mm: float
    material: str
    contact: Contact = field(default_factory=Contact)
    sources: list[Source] = field(default_factory=list)


@dataclass
class PlateResult:
    plate: Plate
    temperature_k: np.ndarray
    power_density_w_per_cm2: np.ndarray
    ds_mm: float
    injected_w: float
    removed_w: float
    iterations: int

    @property
    def t_max_k(self) -> float:
        return float(self.temperature_k.max())

    @property
    def rise_max_k(self) -> float:
        return self.t_max_k - self.plate.t_stage_k

    @property
    def rise_mean_k(self) -> float:
        return float(self.temperature_k.mean() - self.plate.t_stage_k)

    @property
    def peak_power_density_w_per_cm2(self) -> float:
        return float(self.power_density_w_per_cm2.max())


def rasterise(plate: Plate, nx: int, ny: int) -> np.ndarray:
    """Power (W) per cell; each source deposits exactly its ``power_w``."""
    lx, ly = plate.size_mm
    dx, dy = lx / nx, ly / ny
    xe = np.arange(nx + 1) * dx
    ye = np.arange(ny + 1) * dy
    xc = (xe[:-1] + xe[1:]) / 2
    yc = (ye[:-1] + ye[1:]) / 2
    power = np.zeros((ny, nx))
    for s in plate.sources:
        ox = np.clip(np.minimum(s.x_mm + s.w_mm, xe[1:]) - np.maximum(s.x_mm, xe[:-1]), 0, None)
        oy = np.clip(np.minimum(s.y_mm + s.h_mm, ye[1:]) - np.maximum(s.y_mm, ye[:-1]), 0, None)
        area = np.outer(oy, ox)
        if area.sum() <= 0:
            raise ValueError(f"source {s.name!r} lies outside plate {plate.name!r}")
        weights = area.copy()
        if s.hotspot:
            cx, cy = s.x_mm + s.w_mm / 2, s.y_mm + s.h_mm / 2
            sigma = 0.15 * max(s.w_mm, s.h_mm)
            g = np.exp(-((xc[None, :] - cx) ** 2 + (yc[:, None] - cy) ** 2) / (2 * sigma ** 2))
            weights = area * (1.0 + s.hotspot * g)
        power += weights / weights.sum() * s.power_w
    return power


def solve_plate(plate: Plate, n_max: int = 64, tol: float = 1e-7, max_iter: int = 200) -> PlateResult:
    lx, ly = plate.size_mm
    ds = max(lx, ly) / n_max
    nx, ny = max(4, round(lx / ds)), max(4, round(ly / ds))
    cell_w = lx / nx * 1e-3
    cell_h = ly / ny * 1e-3
    power = rasterise(plate, nx, ny)
    material = materials.get(plate.material)
    t_m = plate.thickness_mm * 1e-3
    area = cell_w * cell_h
    ts = plate.t_stage_k
    idx = np.arange(nx * ny).reshape(ny, nx)

    temp = np.full((ny, nx), ts) + 1e-3 * ts
    it = 0
    for it in range(1, max_iter + 1):
        k = material.k(temp.ravel()).reshape(ny, nx)
        kx = 2 * k[:, :-1] * k[:, 1:] / (k[:, :-1] + k[:, 1:])
        ky = 2 * k[:-1, :] * k[1:, :] / (k[:-1, :] + k[1:, :])
        gx = kx * t_m * cell_h / cell_w
        gy = ky * t_m * cell_w / cell_h
        gc = plate.contact.effective_h(temp, ts) * area

        rows = np.concatenate([idx[:, :-1].ravel(), idx[:, 1:].ravel(), idx[:-1, :].ravel(), idx[1:, :].ravel()])
        cols = np.concatenate([idx[:, 1:].ravel(), idx[:, :-1].ravel(), idx[1:, :].ravel(), idx[:-1, :].ravel()])
        vals = -np.concatenate([gx.ravel(), gx.ravel(), gy.ravel(), gy.ravel()])
        diag = gc.copy()
        diag[:, :-1] += gx
        diag[:, 1:] += gx
        diag[:-1, :] += gy
        diag[1:, :] += gy
        a = coo_matrix((np.concatenate([vals, diag.ravel()]),
                        (np.concatenate([rows, idx.ravel()]), np.concatenate([cols, idx.ravel()]))),
                       shape=(nx * ny, nx * ny)).tocsc()
        b = (power + gc * ts).ravel()
        new = spsolve(a, b).reshape(ny, nx)
        change = np.max(np.abs(new - temp))
        temp = 0.5 * temp + 0.5 * new if it > 3 else new
        if change <= tol * max(ts, new.max() - ts, 1e-12):
            temp = new
            break

    removed = float((plate.contact.flux(temp, ts) * area).sum())
    return PlateResult(plate=plate, temperature_k=temp, power_density_w_per_cm2=power / (area * 1e4),
                       ds_mm=lx / nx, injected_w=float(power.sum()), removed_w=removed, iterations=it)
