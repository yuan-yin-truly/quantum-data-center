"""A fast reduced thermal model of the package, calibrated against the judge's HotSpot results.

NOT a substitute for HotSpot: it is used only to screen and rank candidates cheaply. Final claims need real
HotSpot results (see ``PackageEvaluator``), and every surrogate number carries ``source = "surrogate"``.

Model (all heat comes from the judge's own ``interconnect.combined_heat``, so it follows the exact power maps,
interface heat and routed-wire heat of a layout and any hybrid power modifiers):

    q   = q_die + rho * q_interposer                       (W per cell on a 0.5 mm grid)
    loc = (1 - w2) * G_s1(q) + w2 * G_s2(q)                (two Gaussian lateral-spreading kernels)
    T   = T_amb + R(x, y) * loc / cell_area  +  c_in * Q_in + c_out * Q_out

R(x, y) is r_in inside the cooled 44 x 34 mm window and r_in * ratio outside it (the judge's uneven cooler),
c_in / c_out are the bulk (heat-sink) rises per watt entering through / outside the window. The die peak is the
maximum of T over the die footprint. Eight parameters are fitted to the per-die peaks of real HotSpot runs
(``python -m design_loop calibrate``); the fit data and the cross-validated error are stored with the
parameters in ``data/surrogate_calibration.json`` and reported by ``python -m design_loop report``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage, optimize

from .hill import HillAdapter
from .paths import DATA_DIR

CAL_PATH = DATA_DIR / "surrogate_calibration.json"
PITCH = 0.5          # mm

PARAM_NAMES = ["r_in", "ratio", "sigma1", "sigma2", "w2", "rho", "c_in", "c_out"]
DEFAULT_PARAMS = {"r_in": 12.0, "ratio": 3.0, "sigma1": 1.2, "sigma2": 6.0, "w2": 0.35, "rho": 0.5,
                  "c_in": 0.09, "c_out": 0.2}
BOUNDS = {"r_in": (1.0, 80.0), "ratio": (1.0, 12.0), "sigma1": (0.4, 4.0), "sigma2": (2.0, 20.0), "w2": (0.0, 0.9),
          "rho": (0.0, 2.0), "c_in": (0.0, 0.5), "c_out": (0.0, 1.0)}


class Rasteriser:
    """Heat -> fields on the 0.5 mm grid (cached geometry masks)."""

    def __init__(self, hill: HillAdapter):
        self.hill = hill
        W, H = hill.interposer
        self.nx, self.ny = int(round(W / PITCH)), int(round(H / PITCH))
        cx, cy, cw, ch = hill.spec["thermal_model"]["cooling_contact_rect_mm"]
        xs = (np.arange(self.nx) + 0.5) * PITCH
        ys = (np.arange(self.ny) + 0.5) * PITCH
        self.inside = ((xs[None, :] >= cx) & (xs[None, :] <= cx + cw) & (ys[:, None] >= cy) & (ys[:, None] <= cy + ch))
        self.xs, self.ys = xs, ys

    def die_slice(self, layout: dict, die: str):
        x0, y0, x1, y1 = self.hill.die_box(layout, die)
        ix0, ix1 = int(round(x0 / PITCH)), int(round(x1 / PITCH))
        iy0, iy1 = int(round(y0 / PITCH)), int(round(y1 / PITCH))
        return slice(iy0, iy1), slice(ix0, ix1)

    def fields(self, layout: dict, heat: dict) -> tuple[np.ndarray, np.ndarray]:
        q_die = np.zeros((self.ny, self.nx))
        for die, m in heat["die_maps_w"].items():
            sl = self.die_slice(layout, die)
            h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            m = np.asarray(m, dtype=float)
            z = ndimage.zoom(m, (h / m.shape[0], w / m.shape[1]), order=0)
            z = z[:h, :w]
            if z.sum() > 0:
                z = z * (m.sum() / z.sum())
            q_die[sl] += z
        tiles = np.asarray(heat["interposer_tiles_w"], dtype=float)           # [ny_t, nx_t], 1 mm tiles
        zy, zx = self.ny / tiles.shape[0], self.nx / tiles.shape[1]
        q_ip = ndimage.zoom(tiles, (zy, zx), order=0)[: self.ny, : self.nx]
        if q_ip.sum() > 0:
            q_ip = q_ip * (tiles.sum() / q_ip.sum())
        return q_die, q_ip


class ThermalSurrogate:
    def __init__(self, hill: HillAdapter, params: dict[str, float] | None = None, meta: dict | None = None):
        self.hill = hill
        self.ras = Rasteriser(hill)
        self.params = dict(DEFAULT_PARAMS if params is None else params)
        self.meta = meta or {"calibrated": False, "note": "default (uncalibrated) parameters"}
        self.ambient = hill.spec["thermal_model"]["ambient_c"]

    @property
    def calibrated(self) -> bool:
        return bool(self.meta.get("calibrated"))

    # ------------------------------------------------------------------------------------------------
    def field(self, layout: dict, heat_w: dict, p: dict | None = None) -> np.ndarray:
        p = p or self.params
        q_die, q_ip = self.ras.fields(layout, heat_w)
        q = q_die + p["rho"] * q_ip
        s1, s2 = p["sigma1"] / PITCH, p["sigma2"] / PITCH
        loc = (1 - p["w2"]) * ndimage.gaussian_filter(q, s1, mode="constant") + p["w2"] * ndimage.gaussian_filter(q, s2, mode="constant")
        r = np.where(self.ras.inside, p["r_in"], p["r_in"] * p["ratio"])
        q_in = float((q_die + q_ip)[self.ras.inside].sum())
        q_out = float((q_die + q_ip)[~self.ras.inside].sum())
        return self.ambient + r * loc / (PITCH * PITCH) + p["c_in"] * q_in + p["c_out"] * q_out

    def die_peaks(self, layout: dict, heat_by_wl: dict, p: dict | None = None) -> dict[str, dict[str, float]]:
        """``{workload: {die: peak temperature C}}``."""
        out = {}
        for w, heat in heat_by_wl.items():
            T = self.field(layout, heat, p)
            out[w] = {d: round(float(T[self.ras.die_slice(layout, d)].max()), 3) for d in self.hill.DIES}
        return out

    # ------------------------------------------------------------------------------------------------
    @classmethod
    def load(cls, hill: HillAdapter, path: Path = CAL_PATH) -> "ThermalSurrogate":
        if path.is_file():
            try:
                raw = json.loads(path.read_text())
                return cls(hill, raw["params"], {k: raw[k] for k in raw if k not in ("params", "training")} | {"calibrated": True})
            except (ValueError, KeyError):                        # pragma: no cover
                pass
        return cls(hill)

    def fit(self, samples: list[dict], grid_sigma1=(0.8, 1.5, 2.5), grid_sigma2=(5.0, 9.0, 15.0), grid_rho=(0.3, 0.8, 1.4),
            rng_seed: int = 0) -> dict[str, Any]:
        """Fit to HotSpot per-die peaks. ``samples``: dicts with ``layout``, ``heat`` (by workload, from
        ``HillAdapter.heat``) and ``peaks`` (``{workload: {die: C}}``).

        The model is linear in (a1, a2) = (r_in (1 - w2), r_in w2) for fixed kernel widths and interposer weight, so
        the widths (sigma1, sigma2, rho) are chosen on a small grid and the remaining five parameters by bounded
        least squares on fields cached per grid point. Leave-one-layout-out cross-validation repeats the whole
        procedure (grid choice included) with the held-out layout removed.
        """
        dies = list(self.hill.DIES)
        cases = []                                    # one per (sample, workload)
        for si, s in enumerate(samples):
            for w, heat in s["heat"].items():
                qd, qi = self.ras.fields(s["layout"], heat)
                cases.append({"sample": si, "qd": qd, "qi": qi, "layout": s["layout"],
                              "obs": np.array([s["peaks"][w][d] for d in dies])})
        n = len(cases)
        sample_of = np.array([c["sample"] for c in cases])
        obs = np.stack([c["obs"] for c in cases])                              # [case, die]
        qin = np.array([float(((c["qd"] + c["qi"])[self.ras.inside]).sum()) for c in cases])
        qout = np.array([float(((c["qd"] + c["qi"])[~self.ras.inside]).sum()) for c in cases])
        # die cell packing: [case, die, cell] with validity mask and outside-window flag
        slices = [[self.ras.die_slice(c["layout"], d) for d in dies] for c in cases]
        cmax = max((sl[0].stop - sl[0].start) * (sl[1].stop - sl[1].start) for row in slices for sl in row)
        valid = np.zeros((n, len(dies), cmax), bool)
        outm = np.zeros((n, len(dies), cmax), float)
        for i, row in enumerate(slices):
            for j, sl in enumerate(row):
                m = (~self.ras.inside[sl]).ravel().astype(float)
                valid[i, j, : m.size] = True
                outm[i, j, : m.size] = m

        def pack(field_list):
            out = np.zeros((n, len(dies), cmax))
            for i, row in enumerate(slices):
                for j, sl in enumerate(row):
                    v = field_list[i][sl].ravel()
                    out[i, j, : v.size] = v
            return out

        hyper = [(s1, s2, r) for s1 in grid_sigma1 for s2 in grid_sigma2 for r in grid_rho]
        cache = {}
        for (s1, s2, rho) in hyper:
            g1, g2 = [], []
            for c in cases:
                q = c["qd"] + rho * c["qi"]
                g1.append(ndimage.gaussian_filter(q, s1 / PITCH, mode="constant") / (PITCH * PITCH))
                g2.append(ndimage.gaussian_filter(q, s2 / PITCH, mode="constant") / (PITCH * PITCH))
            cache[(s1, s2, rho)] = (pack(g1), pack(g2))

        lo = np.array([0.0, 0.0, 1.0, 0.0, 0.0])
        hi = np.array([BOUNDS["r_in"][1], BOUNDS["r_in"][1], BOUNDS["ratio"][1], BOUNDS["c_in"][1], BOUNDS["c_out"][1]])
        x0 = np.array([8.0, 4.0, 3.0, 0.09, 0.2])

        def predict(h, theta, idx):
            G1, G2 = cache[h]
            a1, a2, ratio, cin, cout = theta
            f = (a1 * G1[idx] + a2 * G2[idx]) * (1.0 + (ratio - 1.0) * outm[idx])
            f = np.where(valid[idx], f, -1e9)
            return self.ambient + f.max(axis=2) + (cin * qin[idx] + cout * qout[idx])[:, None]

        def solve(idx):
            best = None
            for h in hyper:
                try:
                    sol = optimize.least_squares(lambda t: (predict(h, t, idx) - obs[idx]).ravel(), x0, bounds=(lo, hi),
                                                 x_scale=(hi - lo) / 10, max_nfev=60)
                except Exception:                                              # pragma: no cover
                    continue
                if best is None or sol.cost < best[0].cost:
                    best = (sol, h)
            return best

        all_idx = np.arange(n)
        sol, h = solve(all_idx)
        theta = sol.x
        res = (predict(h, theta, all_idx) - obs).ravel()
        cv_pred, cv_obs = [], []
        for si in range(len(samples)):
            tr, te = np.where(sample_of != si)[0], np.where(sample_of == si)[0]
            if len(tr) < 3 * 5:
                continue
            s2, h2 = solve(tr)
            cv_pred.append(predict(h2, s2.x, te))
            cv_obs.append(obs[te])
        cv = {}
        if cv_pred:
            a, b = np.concatenate(cv_pred).ravel(), np.concatenate(cv_obs).ravel()
            cv = {"rmse_c": float(np.sqrt(np.mean((a - b) ** 2))), "mae_c": float(np.mean(np.abs(a - b))),
                  "max_abs_c": float(np.max(np.abs(a - b))), "n_points": int(len(a)), "spearman_per_point": _spearman(a, b)}
            wg_p, wg_o, wh_p, wh_o = [], [], [], []
            for pr, ob in zip(cv_pred, cv_obs):                                  # [workload, die] per held-out layout
                wg_p.append(pr[:, :4].max()); wg_o.append(ob[:, :4].max())
                wh_p.append(pr[:, 4:].max()); wh_o.append(ob[:, 4:].max())
            cv["worst_gpu"] = {"mae_c": float(np.mean(np.abs(np.array(wg_p) - wg_o))), "spearman": _spearman(wg_p, wg_o)}
            cv["worst_hbm"] = {"mae_c": float(np.mean(np.abs(np.array(wh_p) - wh_o))), "spearman": _spearman(wh_p, wh_o)}
        a1, a2, ratio, cin, cout = [float(x) for x in theta]
        r_in = max(a1 + a2, 1e-6)
        self.params = {"r_in": r_in, "ratio": ratio, "sigma1": h[0], "sigma2": h[1], "w2": a2 / r_in, "rho": h[2],
                       "c_in": cin, "c_out": cout}
        fit_stats = {"rmse_c": float(np.sqrt(np.mean(res ** 2))), "max_abs_c": float(np.max(np.abs(res))),
                     "n_points": int(res.size), "n_layouts": len(samples)}
        self.meta = {"calibrated": True, "fit": fit_stats, "cross_validation_leave_one_layout_out": cv}
        return {"params": self.params, **self.meta}

    def _field_from(self, q_die, q_ip, p):
        q = q_die + p["rho"] * q_ip
        s1, s2 = p["sigma1"] / PITCH, p["sigma2"] / PITCH
        loc = (1 - p["w2"]) * ndimage.gaussian_filter(q, s1, mode="constant") + p["w2"] * ndimage.gaussian_filter(q, s2, mode="constant")
        r = np.where(self.ras.inside, p["r_in"], p["r_in"] * p["ratio"])
        q_all = q_die + q_ip
        return (self.ambient + r * loc / (PITCH * PITCH) + p["c_in"] * float(q_all[self.ras.inside].sum())
                + p["c_out"] * float(q_all[~self.ras.inside].sum()))


def _spearman(a, b) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3:
        return None
    ra, rb = np.argsort(np.argsort(a)).astype(float), np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def spearman(a, b):
    return _spearman(a, b)
