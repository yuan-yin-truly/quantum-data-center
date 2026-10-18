"""Temperature-dependent thermal conductivity of cryogenic materials.

The tables are engineering approximations of handbook data (NIST / Cryogenic
Materials Data Handbook style curves), good to roughly +-30 % above 4 K. Below
the first tabulated point conductivity is extrapolated as ``k0 * (T/T0)**exp``;
``exp = 1`` (metals, and the upper bound used by Krinner et al., EPJ Quantum
Technology 6, 2 (2019)) is used throughout. Real superconductors and insulators
fall faster (T^2..T^3), so sub-kelvin conduction here is conservative.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Material:
    name: str
    #: ((T_kelvin, k_W_per_m_K), ...) with ascending T.
    points: tuple[tuple[float, float], ...]
    low_exp: float = 1.0
    note: str = ""

    def k(self, temperature) -> np.ndarray:
        """Thermal conductivity in W/(m K); vectorised, log-log interpolated."""
        t = np.atleast_1d(np.asarray(temperature, dtype=float))
        ts = np.array([p[0] for p in self.points])
        ks = np.array([p[1] for p in self.points])
        out = np.empty_like(t)
        low = t < ts[0]
        out[low] = ks[0] * (np.maximum(t[low], 0.0) / ts[0]) ** self.low_exp
        mid = ~low
        tm = np.minimum(t[mid], ts[-1])
        out[mid] = np.exp(np.interp(np.log(tm), np.log(ts), np.log(ks)))
        return out if np.ndim(temperature) else out[0]


def conductivity_integral(material: Material, t_cold: float, t_hot: float,
                          n: int = 800) -> float:
    """Integral of k dT from ``t_cold`` to ``t_hot`` in W/m (log-spaced trapezoid)."""
    if t_hot <= t_cold:
        return 0.0
    grid = np.geomspace(max(t_cold, 1e-5), t_hot, n)
    return float(np.trapezoid(material.k(grid), grid))


def _m(name, points, low_exp=1.0, note=""):
    return Material(name, tuple(points), low_exp, note)


MATERIALS: dict[str, Material] = {m.name: m for m in [
    _m("ss304", [(4, 0.27), (10, 0.8), (20, 2.0), (40, 4.3), (77, 7.9), (100, 9.4),
                 (150, 11.4), (200, 12.6), (300, 14.9)],
       note="AISI 304 stainless steel"),
    _m("cuni", [(4, 1.0), (10, 2.4), (20, 4.3), (77, 14.0), (150, 21.0), (300, 29.0)],
       note="Cupronickel 70/30"),
    _m("nbti", [(4, 0.15), (9, 0.5), (10, 0.7), (20, 1.6), (77, 4.8), (150, 6.3), (300, 7.5)],
       note="NbTi alloy, superconducting below ~9 K"),
    _m("cu_rrr100", [(4, 570), (10, 1000), (20, 1100), (40, 800), (77, 540), (100, 480),
                     (200, 420), (300, 400)],
       note="OFHC copper, RRR~100; k = L0*T/rho0 below 4 K"),
    _m("phosphor_bronze", [(4, 0.9), (10, 2.8), (20, 6.5), (77, 24.0), (150, 36.0), (300, 48.0)],
       note="Phosphor bronze (DC twisted pairs)"),
    _m("ptfe", [(4, 0.045), (10, 0.09), (20, 0.15), (77, 0.23), (150, 0.26), (300, 0.27)],
       note="PTFE coax dielectric"),
    _m("polyimide", [(4, 0.04), (20, 0.1), (77, 0.2), (300, 0.14)],
       note="Kapton / polyimide flex substrate"),
    _m("silica", [(4, 0.04), (20, 0.2), (77, 0.55), (300, 1.38)],
       note="Fused silica optical fibre"),
    _m("silicon", [(0.01, 1.2e-6), (0.1, 1.2e-3), (1, 1.2), (4, 70), (10, 900), (25, 3500),
                   (50, 2000), (77, 1000), (150, 400), (300, 150)],
       note="Float-zone silicon, mm-scale sample (boundary-limited phonons, k ~ T^3 below ~4 K)"),
]}


def get(name: str) -> Material:
    try:
        return MATERIALS[name]
    except KeyError:
        raise KeyError(f"unknown material {name!r}; known: {', '.join(MATERIALS)}") from None
