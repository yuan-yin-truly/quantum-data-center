"""Reports: markdown, JSON/CSV tables of the full design x workload matrix, and figures.

Figures follow the style of ``quantum_arch/report.py`` (light surface, thin marks, fixed categorical order, direct
labels). Every output carries ``leaderboard_comparable: false`` and states, per number, the evaluator (real HotSpot,
surrogate, model, stub) and the power boundary.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from . import LEADERBOARD_COMPARABLE, NOTICE, __version__
from . import integration as I
from .archive import Archive
from .config import load_config
from .objectives import Assessment, assess, nondominated_sort, pareto_front, ranking, scalar_scores
from .paths import DATA_DIR

try:                                         # same look as quantum_arch.report
    from quantum_arch.report import CATEGORICAL, GRID, INK, INK2, SURFACE
except Exception:                            # pragma: no cover
    SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]

MODE_COLOR = {"gpu_only": INK2, "add": CATEGORICAL[0], "replace": CATEGORICAL[1]}
MODE_LABEL = {"gpu_only": "GPU-only", "add": "ADD", "replace": "REPLACE"}
SEQ = "Oranges"
HILL_WL = ["tensor_training", "skewed_compute", "attention_decode", "memory_stream", "mixed_serving"]


# ------------------------------------------------------------------------------------------------------
# data
# ------------------------------------------------------------------------------------------------------
def _style(ax, grid="both"):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK2)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=INK2, labelsize=8.5, length=3)
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _fig(w, h):
    return plt.figure(figsize=(w, h), facecolor=SURFACE)


def _short(did: str, g: dict) -> str:
    return f"{did[:6]} {MODE_LABEL[g['mode']]}" + ("" if g["mode"] == "gpu_only" else f" {g['modality'][:5]}")


class RunData:
    """Everything a report needs, loaded from a run directory."""

    def __init__(self, run_dir: str | Path):
        self.dir = Path(run_dir)
        self.archive = Archive(self.dir)
        self.cfg = json.loads((self.dir / "config.json").read_text()) if (self.dir / "config.json").is_file() else load_config(None)
        self.state = self.archive.load_state() or {}
        self.objectives = self.cfg.get("objectives")
        self.constraints = self.cfg.get("constraints", {})
        self.assess: dict[str, Assessment] = {d: assess(d, self.archive.results(d), self.constraints, self.objectives)
                                              for d in self.archive.designs}
        al = list(self.assess.values())
        self.front_screen = pareto_front(al, self.objectives)
        self.front_conf = pareto_front(al, self.objectives, "confirmed")
        self.scal = scalar_scores(al, self.objectives, self.cfg.get("weights"))
        self.scal_conf = scalar_scores([a for a in al if a.tier == "confirmed"], self.objectives, self.cfg.get("weights"))
        self.generations = self.archive.generations()

    def design(self, did):
        return self.archive.designs[did]

    def ev(self, did, name):
        return self.archive.results(did).get(name)

    def thermal(self, did):
        for n in ("package_hotspot", "package_surrogate"):
            r = self.ev(did, n)
            if r is not None and r.ok and r.metrics.get("worst_gpu_c") is not None:
                return r
        return None

    def baseline_id(self) -> str | None:
        for did, d in self.archive.designs.items():
            if d.genes["mode"] == "gpu_only" and self.assess[did].eligible:
                return did
        return None

    def surrogate_vs_hotspot(self) -> list[dict]:
        rows = []
        for did in self.archive.designs:
            s, h = self.ev(did, "package_surrogate"), self.ev(did, "package_hotspot")
            if s is not None and s.ok and h is not None and h.ok and s.metrics.get("worst_gpu_c") is not None:
                rows.append({"id": did, "surrogate_gpu": s.metrics["worst_gpu_c"], "hotspot_gpu": h.metrics["worst_gpu_c"],
                             "surrogate_hbm": s.metrics["worst_hbm_c"], "hotspot_hbm": h.metrics["worst_hbm_c"],
                             "surrogate_calibrated": s.metrics.get("surrogate_calibrated")})
        return rows


def matrix_for(rd: RunData, did: str) -> dict[str, Any]:
    th, q, dc = rd.thermal(did), rd.ev(did, "quantum"), rd.ev(did, "datacentre")
    a = rd.assess[did]
    m: dict[str, Any] = {"status": a.status, "tier": a.tier, "thermal_source": th.source if th else None}
    m["hill"] = {w: {k: v for k, v in rec.items() if k != "per_die_peak_c"} | {"per_die_peak_c": rec.get("per_die_peak_c")}
                 for w, rec in (th.per_workload.items() if th else [])}
    m["quantum"] = q.per_workload if q and q.ok else {}
    if dc and dc.ok:
        m["datacentre_classes"] = dc.per_workload.get("dc_class", {})
        m["gpu_baseline"] = dc.per_workload.get("gpu_baseline", {})
    return m


# ------------------------------------------------------------------------------------------------------
# tables
# ------------------------------------------------------------------------------------------------------
def _f(x, nd=2, unit=""):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    if abs(x) >= 1e4 or (0 < abs(x) < 1e-2):
        return f"{x:.3g}{unit}"
    return f"{x:.{nd}f}{unit}"


def _w(x):
    if x is None:
        return "n/a"
    for s, u in ((1e9, "GW"), (1e6, "MW"), (1e3, "kW"), (1.0, "W")):
        if abs(x) >= s:
            return f"{x / s:.3g} {u}"
    return f"{x:.3g} W"


def _table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def genes_summary(g: dict) -> str:
    if g["mode"] == "gpu_only":
        return "4 GPU + 4 HBM, no quantum"
    s = (f"{g['modality']} / {g['scheme']}, {g['n_qubits']:,} qubits, {g['code']}+{g['decoder']} on {g['decoder_device'][5:]}"
         f"@{g['decoder_location']}, task {g['task']}, f={g['offload_fraction']:.2f}, {g['n_quantum_systems']} systems, "
         f"cryostat x{g['cryostat_scale']:g}")
    sup = I.support_dies(g)
    if sup:
        s += f", support dies {'+'.join(sup)}"
    return s


def design_table(rd: RunData, ids: list[str]) -> str:
    obj = [o["name"] for o in rd.objectives]
    head = ["design", "origin", "mode", "configuration", "tier / thermal source"] + [
        f"{o['label'] if 'label' in o else o['name']} [{'min' if o['direction']=='min' else 'max'}]" for o in rd.objectives]
    rows = []
    for did in ids:
        a, g = rd.assess[did], rd.design(did).genes
        mt = rd.archive.meta[did]
        rows.append([f"`{did}`", f"g{mt.get('generation')} {str(mt.get('operator')).split(':')[0]}", MODE_LABEL[g["mode"]],
                     genes_summary(g) + (" (non-baseline layout)" if rd.design(did).layout != rd.design(rd.baseline_id() or did).layout else ""),
                     f"{a.tier} / {a.sources.get('thermal', 'n/a')}"] +
                    [_f(a.objectives.get(n)) for n in obj])
    return _table(head, rows)


# ------------------------------------------------------------------------------------------------------
# figures
# ------------------------------------------------------------------------------------------------------
def _scatter_pairs(rd: RunData, path: Path) -> None:
    objs = rd.objectives
    pairs = [(0, 2), (0, 3), (1, 0), (2, 3)] if len(objs) >= 4 else [(0, 1)]
    elig = [a for a in rd.assess.values() if a.eligible and all(a.objectives.get(o["name"]) is not None for o in objs)]
    fig = _fig(11.5, 8.2)
    fig.suptitle("Design space against the evaluated workloads: objective trade-offs", x=0.02, ha="left", color=INK,
                 fontsize=12.5)
    fig.text(0.02, 0.93, "Each dot = one fully evaluated design. Ringed = confirmed non-dominated (real HotSpot); "
             "cross = non-dominated on surrogate numbers only. Local only, not leaderboard comparable.", color=INK2, fontsize=8.5)
    n = len(pairs)
    cols = 2
    rows = math.ceil(n / cols)
    for k, (i, j) in enumerate(pairs):
        ax = fig.add_axes([0.07 + (k % cols) * 0.49, 0.54 - (k // cols) * 0.45, 0.40, 0.33])
        oi, oj = objs[i], objs[j]
        for mode in ("gpu_only", "add", "replace"):
            pts = [a for a in elig if rd.design(a.design_id).genes["mode"] == mode]
            if not pts:
                continue
            xs = [a.objectives[oi["name"]] for a in pts]
            ys = [a.objectives[oj["name"]] for a in pts]
            marker = ["o" if a.tier == "confirmed" else "s" for a in pts]
            for x, y, mk in zip(xs, ys, marker):
                ax.scatter(x, y, s=26 if mode != "gpu_only" else 60, color=MODE_COLOR[mode], marker=mk,
                           edgecolor=SURFACE, linewidth=0.8, alpha=0.9, zorder=3)
            ax.scatter([], [], s=30, color=MODE_COLOR[mode], label=MODE_LABEL[mode])
        for did in rd.front_screen:
            a = rd.assess[did]
            ax.scatter(a.objectives[oi["name"]], a.objectives[oj["name"]], s=90, marker="x", color=INK, linewidth=1.2, zorder=4)
        for did in rd.front_conf:
            a = rd.assess[did]
            ax.scatter(a.objectives[oi["name"]], a.objectives[oj["name"]], s=150, facecolor="none", edgecolor=INK,
                       linewidth=1.3, zorder=4)
        b = rd.baseline_id()
        if b:
            ab = rd.assess[b]
            ax.annotate("GPU-only baseline", (ab.objectives[oi["name"]], ab.objectives[oj["name"]]), xytext=(6, 8),
                        textcoords="offset points", fontsize=8, color=INK)
        ax.set_xlabel(oi.get("label", oi["name"]) + (" (lower is better)" if oi["direction"] == "min" else " (higher is better)"),
                      color=INK2, fontsize=8.5)
        ax.set_ylabel(oj.get("label", oj["name"]) + (" (lower is better)" if oj["direction"] == "min" else " (higher is better)"),
                      color=INK2, fontsize=8.5)
        _style(ax)
        if oi["name"].startswith("energy") or oj["name"].startswith("energy"):
            if oi["name"].startswith("energy"):
                ax.set_xscale("log")
            else:
                ax.set_yscale("log")
        if k == 0:
            ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, loc="best")
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def _top_ids(rd: RunData, k: int = 12) -> list[str]:
    conf = sorted(rd.scal_conf, key=lambda i: (rd.scal_conf[i], i))
    rest = [i for i, _ in sorted(rd.scal.items(), key=lambda kv: (kv[1], kv[0])) if i not in conf]
    ids = (conf + rest)[:k]
    b = rd.baseline_id()
    if b and b not in ids:
        ids = ids[: k - 1] + [b]
    return ids


def _heat_hill(rd: RunData, path: Path) -> None:
    ids = _top_ids(rd)
    if not ids:
        return
    M = np.full((len(ids), len(HILL_WL)), np.nan)
    src = []
    for r, did in enumerate(ids):
        th = rd.thermal(did)
        src.append(th.source if th else "n/a")
        if th:
            for c, w in enumerate(HILL_WL):
                rec = th.per_workload.get(w)
                if rec:
                    M[r, c] = max(rec["gpu_peak_c"], rec["hbm_peak_c"])
    fig = _fig(9.5, 0.6 * len(ids) + 2.4)
    ax = fig.add_axes([0.30, 0.16, 0.62, 0.70])
    im = ax.imshow(M, cmap=SEQ, aspect="auto", vmin=np.nanmin(M) - 2, vmax=np.nanmax(M) + 1)
    ax.set_xticks(range(len(HILL_WL)), [w.replace("_", "\n") for w in HILL_WL], fontsize=8.5, color=INK2)
    ax.set_yticks(range(len(ids)), [f"{_short(i, rd.design(i).genes)} [{'HS' if s == 'hotspot' else 'surr' if s == 'surrogate' else s}]"
                                    for i, s in zip(ids, src)], fontsize=8, color=INK)
    for r in range(len(ids)):
        for c in range(len(HILL_WL)):
            if not np.isnan(M[r, c]):
                ax.text(c, r, f"{M[r, c]:.1f}", ha="center", va="center", fontsize=8,
                        color=INK if M[r, c] < np.nanmax(M) - 4 else "white")
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label("hottest GPU/HBM cell (C)", color=INK2, fontsize=8.5)
    cb.ax.tick_params(colors=INK2, labelsize=8)
    fig.suptitle("Design x hill workload: peak temperature (package, local power model)", x=0.02, ha="left", color=INK, fontsize=12)
    fig.text(0.02, 0.93, "[HS] real HotSpot, [surr] calibrated reduced model. Replaced dies are excluded from the GPU peak. "
             "Not leaderboard comparable.", color=INK2, fontsize=8.5)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def _heat_quantum(rd: RunData, path: Path) -> None:
    ids = [i for i in _top_ids(rd) if rd.design(i).genes["mode"] != "gpu_only"]
    if not ids:
        return
    ids = [i for i in ids if rd.ev(i, "quantum") is not None and rd.ev(i, "quantum").per_workload]
    if not ids:
        return
    wl = list(rd.ev(ids[0], "quantum").per_workload)
    M = np.full((len(ids), len(wl)), np.nan)
    feas = np.zeros((len(ids), len(wl)), bool)
    for r, did in enumerate(ids):
        q = rd.ev(did, "quantum")
        for c, w in enumerate(wl):
            rec = q.per_workload.get(w) if q else None
            if rec and rec["feasible"] and rec.get("energy_facility_j"):
                M[r, c] = math.log10(rec["energy_facility_j"])
                feas[r, c] = True
    fig = _fig(11, 0.6 * len(ids) + 2.6)
    ax = fig.add_axes([0.24, 0.20, 0.68, 0.66])
    cm = plt.get_cmap(SEQ).with_extremes(bad=GRID)
    im = ax.imshow(np.ma.masked_invalid(M), cmap=cm, aspect="auto")
    ax.set_xticks(range(len(wl)), [w.replace("_", "\n") for w in wl], fontsize=8, color=INK2)
    ax.set_yticks(range(len(ids)), [_short(i, rd.design(i).genes) for i in ids], fontsize=8, color=INK)
    for r in range(len(ids)):
        for c in range(len(wl)):
            if feas[r, c]:
                ax.text(c, r, f"{M[r, c]:.1f}", ha="center", va="center", fontsize=7.5,
                        color="white" if M[r, c] > np.nanmin(M) + 0.65 * (np.nanmax(M) - np.nanmin(M) + 1e-9) else INK)
            else:
                ax.text(c, r, "infeasible", ha="center", va="center", fontsize=6.5, color=INK2)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cb.set_label("log10 energy per task (J), FACILITY boundary", color=INK2, fontsize=8.5)
    cb.ax.tick_params(colors=INK2, labelsize=8)
    fig.suptitle("Design x quantum workload: energy per task where the logical-error budget is met", x=0.02, ha="left",
                 color=INK, fontsize=12)
    fig.text(0.02, 0.93, "quantum_arch model with illustrative catalogs. Grey = the workload does not fit the design. "
             "No classical comparison is implied.", color=INK2, fontsize=8.5)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def _convergence(rd: RunData, path: Path) -> None:
    gens = rd.generations
    if not gens:
        return
    x = [g["generation"] for g in gens]
    fig = _fig(11, 4.4)
    ax = fig.add_axes([0.07, 0.17, 0.40, 0.64])
    ax.plot(x, [g["designs_total"] for g in gens], color=CATEGORICAL[0], linewidth=2, marker="o", markersize=5,
            markeredgecolor=SURFACE, label="designs evaluated (cumulative)")
    ax.plot(x, [g["front_screening"] for g in gens], color=CATEGORICAL[1], linewidth=2, marker="o", markersize=5,
            markeredgecolor=SURFACE, label="screening front size")
    ax.plot(x, [g["front_confirmed"] for g in gens], color=CATEGORICAL[2], linewidth=2, marker="o", markersize=5,
            markeredgecolor=SURFACE, label="confirmed front size")
    ax.set_xlabel("generation", color=INK2, fontsize=9)
    ax.set_title("Archive growth and Pareto fronts", loc="left", color=INK, fontsize=10.5)
    ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2)
    _style(ax, "y")
    ax.set_xticks(x)
    ax2 = fig.add_axes([0.57, 0.17, 0.40, 0.64])
    objs = rd.objectives
    for k, o in enumerate(objs):
        series = [(g["generation"], (g.get("ideal_point") or {}).get(o["name"])) for g in gens]
        series = [(a, b) for a, b in series if b is not None]
        if not series:
            continue
        base = series[0][1]
        vals = [(b / base) if base else 1.0 for _, b in series]
        ax2.plot([a for a, _ in series], vals, color=CATEGORICAL[k % len(CATEGORICAL)], linewidth=2, marker="o", markersize=4,
                 markeredgecolor=SURFACE, label=o.get("label", o["name"]) + (" (min)" if o["direction"] == "min" else " (max)"))
    ax2.axhline(1.0, color=INK2, linewidth=0.8)
    ax2.set_xlabel("generation", color=INK2, fontsize=9)
    ax2.set_title("Best value found so far, relative to generation 0", loc="left", color=INK, fontsize=10.5)
    ax2.legend(frameon=False, fontsize=7.5, labelcolor=INK2, loc="best")
    _style(ax2, "y")
    ax2.set_xticks(x)
    fig.suptitle("Convergence of the design loop", x=0.02, ha="left", color=INK, fontsize=12)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def _best_design_fig(rd: RunData, did: str, path: Path) -> None:
    d, g = rd.design(did), rd.design(did).genes
    th, q = rd.thermal(did), rd.ev(did, "quantum")
    fig = _fig(11.5, 5.2)
    ax = fig.add_axes([0.05, 0.12, 0.45, 0.72])
    W, H = 52.0, 42.0
    ax.add_patch(Rectangle((0, 0), W, H, facecolor="none", edgecolor=INK2, linewidth=1.0))
    ax.add_patch(Rectangle((4, 4), 44, 34, facecolor="none", edgecolor=CATEGORICAL[2], linewidth=1.0, linestyle="--"))
    ax.text(4.6, 38.6, "cooled window", color=CATEGORICAL[2], fontsize=7.5)
    sizes = {"G": (11.5, 10.5), "H": (10.5, 10.2)}
    sup = set(I.support_dies(g))
    peaks = {}
    if th:
        for w, rec in th.per_workload.items():
            for die, t in (rec.get("per_die_peak_c") or {}).items():
                peaks[die] = max(peaks.get(die, 0), t)
    for die, (x, y) in d.layout.items():
        w, h = sizes[die[0]]
        col = CATEGORICAL[1] if die in sup else (CATEGORICAL[0] if die[0] == "G" else CATEGORICAL[2])
        ax.add_patch(Rectangle((x, y), w, h, facecolor=col, alpha=0.30, edgecolor=col, linewidth=1.3))
        lab = die + (" (quantum support)" if die in sup else "")
        ax.text(x + w / 2, y + h / 2 + 1.2, lab, ha="center", va="center", fontsize=8, color=INK)
        if die in peaks:
            ax.text(x + w / 2, y + h / 2 - 1.4, f"{peaks[die]:.1f} C", ha="center", va="center", fontsize=8.5, color=INK)
    ax.set_xlim(-1, W + 1)
    ax.set_ylim(-1, H + 1)
    ax.set_aspect("equal")
    ax.set_xlabel("mm", color=INK2, fontsize=8.5)
    _style(ax, None)
    src = th.source if th else "n/a"
    ax.set_title(f"Package layout, hottest value over the five workloads ({src})", loc="left", color=INK, fontsize=10)
    ax2 = fig.add_axes([0.60, 0.12, 0.36, 0.72])
    if q and q.ok and q.metrics.get("cryostat_stages"):
        st = q.metrics["cryostat_stages"]
        names = [s["stage"] for s in st]
        util = [min(s["utilisation"] or 0.0, 1e4) for s in st]
        cols = [CATEGORICAL[1] if s["overloaded"] else CATEGORICAL[0] for s in st]
        ax2.barh(names, [max(u, 1e-6) for u in util], color=cols, height=0.55)
        ax2.axvline(1.0, color=INK, linewidth=1.0)
        ax2.set_xscale("log")
        ax2.set_xlabel("heat load / cooling capacity of one cryostat (1 = full)", color=INK2, fontsize=8.5)
        for n, u in zip(names, util):
            ax2.text(max(u, 1e-6) * 1.15, n, f"{u:.2g}", va="center", fontsize=8, color=INK2)
        ax2.set_title(f"Cryostat stage utilisation ({q.metrics['fridge_units']} fridge unit(s) needed)", loc="left",
                      color=INK, fontsize=10)
        ax2.invert_yaxis()
        _style(ax2, "x")
    else:
        ax2.axis("off")
        ax2.text(0, 0.5, "no cryostat in this design", color=INK2)
    fig.suptitle(f"Best design {did}: {MODE_LABEL[g['mode']]}", x=0.02, ha="left", color=INK, fontsize=12)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


# ------------------------------------------------------------------------------------------------------
# markdown
# ------------------------------------------------------------------------------------------------------
def best_design_section(rd: RunData, did: str) -> list[str]:
    d, g = rd.design(did), rd.design(did).genes
    a = rd.assess[did]
    th, q, dc = rd.thermal(did), rd.ev(did, "quantum"), rd.ev(did, "datacentre")
    L = [f"### Design `{did}` ({MODE_LABEL[g['mode']]}), tier {a.tier}", "", f"Configuration: {genes_summary(g)}.", ""]
    meta = rd.archive.meta[did]
    L.append(f"Provenance: generation {meta.get('generation')}, operator `{meta.get('operator')}`, parents "
             f"{', '.join('`'+p+'`' for p in meta.get('parents') or []) or 'none'}, changed {meta.get('changed')}.")
    L.append("")
    if th:
        L += [f"**Package thermal ({th.source}, {rd.cfg['evaluators']['package']['grid']}x{rd.cfg['evaluators']['package']['grid']} mesh, "
              f"boundary: package)**", "",
              _table(["workload", "GPU peak C", "HBM peak C", "support peak C", "package W"],
                     [[w, _f(r['gpu_peak_c']), _f(r['hbm_peak_c']), _f(r.get('support_peak_c')), _f(r.get('package_w'), 1)]
                      for w, r in th.per_workload.items()]), "",
              f"Informational score vs the published 64-mesh baseline reference: {_f(th.metrics.get('score_informational'), 3)} "
              f"(NOT leaderboard comparable).", ""]
    if q and q.ok and q.metrics.get("present"):
        m = q.metrics
        L += ["**Quantum subsystem (quantum_arch model)**", "",
              _table(["quantity", "value", "boundary"],
                     [["task / feasible", f"{m['task']} / {m['task_feasible']}", ""],
                      ["task runtime", _f(m.get("task_runtime_s"), 1, " s"), ""],
                      ["task energy", _f(m.get("task_energy_system_j"), 1, " J"), "system"],
                      ["task energy", _f(m.get("task_energy_facility_j"), 1, " J"), "facility"],
                      ["logical qubits / code distance / rQOPS", f"{m['logical_qubits']} / {m['code_distance']} / {_f(m['rqops'])}", ""],
                      ["decoder devices (keeps up)", f"{m['decoder_devices']} x {m['decoder_device']} ({m['decoder_keeps_up']})", ""],
                      ["power, QPU module (electrical)", _w(m["power_module_w"]), "module"],
                      ["power, whole quantum computer", _w(m["power_system_w"]), "system"],
                      ["power incl. PUE", _w(m["power_facility_w"]), "facility"],
                      ["fridge units / lines-limited units", f"{m['fridge_units']} / {m['units_for_lines']}", ""],
                      ["quantum workloads feasible", f"{m['n_quantum_workloads_feasible']} of {m['n_quantum_workloads']}", ""]]), "",
              ("Cryostat stage load / capacity: " + "; ".join(f"{s['stage']} {s['utilisation']:.2g}x" + (" (overloaded)" if s["overloaded"] else "")
                                                         for s in m["cryostat_stages"] if s["utilisation"] is not None)
               if m["cryostat_stages"] else "No cryostat (ambient-temperature system)."), ""]
    if dc and dc.ok:
        m = dc.metrics
        L += [f"**Data centre ({'STAND-IN' if m.get('stand_in') else 'quantum_arch.datacenter scheduler'}, boundary: facility)**", "",
              _table(["quantity", "value"],
                     [["facility J per accepted GPU-second of work", _f(m.get("facility_j_per_work_unit"), 1)],
                      ["... GPU-only", _f(m.get("facility_j_per_work_unit_gpu_only"), 1)],
                      ["energy ratio vs GPU-only", _f(m.get("energy_ratio_vs_gpu_only"), 3)],
                      ["capacity vs GPU-only (max sustainable demand)", _f(m.get("capacity_rel"), 3)],
                      ["ordinary-AI capacity ratio", _f(m.get("ordinary_ai_capacity_ratio"), 3)],
                      ["movable share of demand (INPUT)", _f(m.get("movable_share"), 3)],
                      ["break-even movable share, energy / capacity", f"{_f(m.get('break_even_movable_share_energy'), 3)} / "
                                                                    f"{_f(m.get('break_even_movable_share_capacity'), 3)}"],
                      ["facility power", _w(m.get("power_facility_w"))]]), ""]
        rows = dc.per_workload.get("dc_class", {})
        be = [(k, v) for k, v in rows.items()]
        if be:
            L += [_table(["job class", "demand share", "routed to quantum", "J per accepted answer (facility)", "note"],
                         [[k, _f(v["demand_share"], 2), _f(v["routed_to_quantum"], 3), _f(v["facility_j_per_accepted_answer"], 1), v.get("note", "")]
                          for k, v in be]), ""]
    if a.violations:
        L += ["Violations: " + "; ".join(a.violations), ""]
    return L


def dc_sensitivity(rd: RunData, did: str) -> list[str]:
    """Energy / capacity of one design when the classical cost of the movable job class (an INPUT) is scaled."""
    from .evaluators.datacentre import DataCentreEvaluator, deep_merge
    g = rd.design(did).genes
    if g["mode"] == "gpu_only":
        return []
    base_cfg = {k: v for k, v in rd.cfg["evaluators"]["datacentre"].items() if k != "force_stand_in"}
    q = rd.ev(did, "quantum")
    rows, scales = [], [0.1, 0.3, 1.0, 3.0, 10.0]
    probe = DataCentreEvaluator(base_cfg)
    if not probe.uses_scheduler:
        return []
    gs0 = probe.cfg["movable_class"]["gpu_seconds"]
    min_served = rd.constraints.get("min_served_fraction", 0.98)

    def run(scale):
        ev = DataCentreEvaluator(deep_merge(base_cfg, {"movable_class": {"gpu_seconds": gs0 * scale}}))
        r = ev.evaluate(rd.design(did), {"quantum": q})
        return r.metrics if r.ok else {}

    for sc in scales:
        m = run(sc)
        rows.append([f"x{sc:g} ({gs0 * sc / 3600:,.0f} GPU-module-hours per job)", _f(m.get("energy_ratio_vs_gpu_only"), 3),
                     _f(m.get("capacity_rel"), 3), _f(m.get("served_fraction"), 3)])
    ok_scale = None
    for k in range(0, 41):
        sc = 0.01 * (10 ** (k / 10.0))
        m = run(sc)
        if (m.get("energy_ratio_vs_gpu_only") or 9) <= 1.0 and (m.get("served_fraction") or 0) >= min_served - 1e-6:
            ok_scale = sc
            break
    out = ["**Sensitivity to the classical cost of the movable job class (INPUT assumption; facility boundary)**", "",
           _table(["classical cost of the movable job (x config value)", "energy ratio vs GPU-only", "capacity vs GPU-only",
                   "served demand"], rows), ""]
    if ok_scale:
        out += [f"Smallest classical cost (scan x0.01 to x100) at which this design both matches GPU-only energy and serves the "
                f"demand: about x{ok_scale:.3g} = {ok_scale * gs0 / 3600:,.0f} GPU-module-hours per job (configured: {gs0 / 3600:,.0f}). "
                "This is what the quantum side would have to be worth for parity, not a statement that it is.", ""]
    else:
        out += ["No classical cost within x0.01 to x100 of the configured value gives both energy parity and the required served demand.", ""]
    return out


def write_report(run_dir: str | Path, out_dir: str | Path | None = None, top_k: int = 8) -> Path:
    rd = RunData(run_dir)
    out = Path(out_dir) if out_dir else rd.dir / "report"
    out.mkdir(parents=True, exist_ok=True)
    al = list(rd.assess.values())
    n_by = {s: sum(1 for a in al if a.status == s) for s in ("complete", "infeasible", "partial")}
    conf_n = sum(1 for a in al if a.tier == "confirmed" and a.eligible)
    pk = rd.cfg["evaluators"]["package"]

    # ---- full matrix (design x workload) as JSON + a flat CSV
    matrix = {did: matrix_for(rd, did) for did in rd.archive.designs}
    (out / "matrix.json").write_text(json.dumps({"leaderboard_comparable": LEADERBOARD_COMPARABLE, "notice": NOTICE,
                                                 "matrix": matrix}, indent=1, default=str))
    with (out / "designs.csv").open("w", newline="") as fh:
        wr = csv.writer(fh)
        obj = [o["name"] for o in rd.objectives]
        wr.writerow(["id", "generation", "operator", "status", "tier", "thermal_source", "mode", "modality", "n_qubits", "task",
                     "offload_fraction", "decoder_location", "support_dies", "layout_changed"] + obj +
                    ["energy_ratio_vs_gpu_only", "violations", "leaderboard_comparable"])
        for did, d in rd.archive.designs.items():
            a, g, mt = rd.assess[did], d.genes, rd.archive.meta[did]
            wr.writerow([did, mt.get("generation"), mt.get("operator"), a.status, a.tier, a.sources.get("thermal"), g["mode"],
                         g["modality"], g["n_qubits"], g["task"], g["offload_fraction"], g["decoder_location"],
                         "+".join(I.support_dies(g)), "layout" in (mt.get("changed") or []) or str(mt.get("operator")) == "layout_search"] +
                        [a.objectives.get(n) for n in obj] + [a.extras.get("energy_ratio_vs_gpu_only"), "; ".join(a.violations), False])

    # ---- figures
    figs = []
    if any(a.eligible for a in al):
        _scatter_pairs(rd, out / "pareto.png"); figs.append("pareto.png")
        _heat_hill(rd, out / "heatmap_hill_workloads.png"); figs.append("heatmap_hill_workloads.png")
        _heat_quantum(rd, out / "heatmap_quantum_workloads.png"); figs.append("heatmap_quantum_workloads.png")
    _convergence(rd, out / "convergence.png"); figs.append("convergence.png")

    # ---- which designs to describe
    ranked_conf = sorted(rd.scal_conf.items(), key=lambda kv: (kv[1], kv[0]))
    ranked_all = sorted(rd.scal.items(), key=lambda kv: (kv[1], kv[0]))
    pool = ranked_conf or ranked_all
    best_id = pool[0][0] if pool else None
    hybrid_id = next((i for i, _ in pool if rd.design(i).genes["mode"] != "gpu_only"), None)
    show_id = hybrid_id or best_id
    if show_id:
        _best_design_fig(rd, show_id, out / "best_design.png"); figs.append("best_design.png")
    base_id = rd.baseline_id()

    # ---- surrogate vs HotSpot
    pairs = rd.surrogate_vs_hotspot()
    cal_path = DATA_DIR / "surrogate_calibration.json"
    cal = json.loads(cal_path.read_text()) if cal_path.is_file() else None

    L: list[str] = [f"# Design loop report: {rd.cfg.get('name')}", "",
                    f"> **{NOTICE}**", "", "`leaderboard_comparable: false`", "",
                    f"Generated by `design_loop` {__version__}. Seed {rd.cfg.get('seed')}. Run directory `{rd.dir.name}`.", "",
                    "## 1. What was evaluated, and by what", ""]
    ev_rows = [["quantum_arch (error budget, rQOPS, cryostat, power)", "model (illustrative catalogs, mid-2030s scenario profile)"],
               ["layout legality", "judge's own `validate_layout` (real)"],
               ["package temperatures, screening", "reduced thermal model fitted to HotSpot" + (" (calibrated)" if cal else " (UNCALIBRATED)") +
                " : SURROGATE, steers the search only"],
               ["package temperatures, confirmation", f"real HotSpot via the pinned container, {pk['grid']}x{pk['grid']} mesh" if conf_n
                else "NOT RUN in this run: no design is confirmed, so no claim below is backed by HotSpot"],
               ["facility energy / capacity / break-even", "`quantum_arch.datacenter` scheduler (model)" if not any(
                   (rd.ev(d, "datacentre") and rd.ev(d, "datacentre").metrics.get("stand_in")) for d in rd.archive.designs)
                else "STAND-IN closed form (scheduler unavailable)"]]
    L += [_table(["view", "evaluator / source"], ev_rows), "",
          f"Designs: {len(al)} registered, {n_by['complete']} complete, {n_by['infeasible']} infeasible (hard constraint violated), "
          f"{n_by['partial']} partial (excluded from fronts and rankings). Confirmed by real HotSpot: {conf_n}. "
          f"HotSpot runs used: {rd.state.get('hotspot_runs', 0)}. Stop reason: {rd.state.get('stop_reason')}.", ""]

    L += ["## 2. Surrogate versus HotSpot", ""]
    if cal:
        cv = cal.get("cross_validation_leave_one_layout_out", {})
        L += [f"Calibration ({len(cal.get('training_runs', []))} real HotSpot runs of layouts / power scenarios): in-sample RMSE "
              f"{_f(cal['fit']['rmse_c'])} C over {cal['fit']['n_points']} die peaks; leave-one-layout-out RMSE "
              f"{_f(cv.get('rmse_c'))} C, MAE {_f(cv.get('mae_c'))} C, worst error {_f(cv.get('max_abs_c'))} C. "
              f"For the headline metrics, leave-one-out MAE is {_f(cv.get('worst_gpu', {}).get('mae_c'))} C (worst GPU, Spearman "
              f"{_f(cv.get('worst_gpu', {}).get('spearman'))}) and {_f(cv.get('worst_hbm', {}).get('mae_c'))} C (worst HBM, Spearman "
              f"{_f(cv.get('worst_hbm', {}).get('spearman'))}). The model is only trusted near the calibrated layouts and power levels.", ""]
    else:
        L += ["The surrogate was NOT calibrated (no HotSpot runs available): its temperatures are uncalibrated and carry "
              "no quantitative meaning.", ""]
    if pairs:
        err_g = [abs(p["surrogate_gpu"] - p["hotspot_gpu"]) for p in pairs]
        err_h = [abs(p["surrogate_hbm"] - p["hotspot_hbm"]) for p in pairs]
        L += [f"Agreement in THIS run on {len(pairs)} designs that have both: mean |error| {np.mean(err_g):.2f} C (worst GPU), "
              f"{np.mean(err_h):.2f} C (worst HBM); max {max(err_g):.2f} / {max(err_h):.2f} C. These designs were chosen because the surrogate "
              "ranked them well, so the sample is biased.", "",
              _table(["design", "worst GPU surrogate", "worst GPU HotSpot", "worst HBM surrogate", "worst HBM HotSpot"],
                     [[f"`{p['id']}`", _f(p["surrogate_gpu"]), _f(p["hotspot_gpu"]), _f(p["surrogate_hbm"]), _f(p["hotspot_hbm"])]
                      for p in pairs]), ""]
    else:
        L += ["No design of this run has both a surrogate and a HotSpot result, so no in-run agreement could be measured.", ""]

    obj_names = [o["name"] for o in rd.objectives]
    L += ["## 3. Pareto fronts", "",
          f"Objectives: " + ", ".join(f"{o['label']} ({o['direction']})" for o in rd.objectives) + ". Non-dominated sorting over designs that are "
          "complete (every evaluator answered for the full workload matrix) and satisfy all hard constraints; partial and infeasible designs "
          "cannot enter. Energy is at the FACILITY boundary; temperatures are package-level; capacity is relative to the GPU-only facility.", ""]
    L += ["### 3.1 Confirmed front (real HotSpot thermal numbers; the only one that may support claims)", ""]
    L += [design_table(rd, sorted(rd.front_conf, key=lambda i: rd.scal_conf.get(i, 9))) if rd.front_conf else "_empty: no design was confirmed by real HotSpot._", ""]
    L += ["### 3.2 Screening front (surrogate thermal numbers; steers the search, NOT a claim)", ""]
    L += [design_table(rd, sorted(rd.front_screen, key=lambda i: rd.scal.get(i, 9))[:20]) if rd.front_screen else "_empty_", ""]
    L += ["### 3.3 Scalarised ranking", "",
          f"Weights {rd.cfg.get('weights') or 'as in the objective definitions (all 1)'}; min-max normalised over the eligible set (0 = best on every objective).", ""]
    rk = ranked_conf[:top_k] if ranked_conf else ranked_all[:top_k]
    L += [("Confirmed designs only." if ranked_conf else "No confirmed design: ranking on SCREENED (surrogate) numbers, not a claim."), "",
          _table(["rank", "design", "score", "mode", "configuration"],
                 [[i + 1, f"`{d}`", _f(s, 3), MODE_LABEL[rd.design(d).genes["mode"]], genes_summary(rd.design(d).genes)] for i, (d, s) in enumerate(rk)]), ""]

    if best_id:
        L += ["## 4. Designs in detail", "",
              f"Best ranked overall: `{best_id}` ({MODE_LABEL[rd.design(best_id).genes['mode']]}). "
              + (f"Best ranked quantum-hybrid design: `{hybrid_id}`." if hybrid_id and hybrid_id != best_id else ""), ""]
        if hybrid_id:
            L += ["### Best quantum-hybrid design", ""] + best_design_section(rd, hybrid_id) + dc_sensitivity(rd, hybrid_id)
            L += ["![best hybrid design](best_design.png)", ""]
        if base_id:
            L += ["### Reference: GPU-only baseline", ""] + best_design_section(rd, base_id)

    L += ["## 5. Findings (what these models say, not predictions)", ""]
    L += findings(rd, base_id, best_id)

    L += ["## 6. Figures", "", "\n\n".join(f"![{f}]({f})" for f in figs if f != "best_design.png"), "",
          "Full design x workload matrix: `matrix.json` (hill workloads with per-die peaks, all quantum workloads, data-centre job "
          "classes, GPU baseline workloads) and `designs.csv`.", ""]

    L += ["## 7. Limits", "",
          "- The offload fraction, the number of quantum systems, the classical cost of the movable job class, mapping quality and all catalog "
          "parameters are INPUT assumptions. Nothing here is derived from, or evidence of, a quantum speedup or advantage.",
          "- `quantum_arch` is an illustrative resource model with a mid-2030s scenario profile; it is not a forecast.",
          "- The package model (about 350 W synthetic packages) and the facility model (5 kW accelerator modules) live at different scales and "
          "are linked only through the design's genes (offload share, replaced dies, quantum architecture).",
          "- HotSpot confirmation uses the judge's pipeline on a 64 mesh; hybrid power maps use the LOCAL variant's `judge_modified`. "
          "Support-chiplet junction temperature limits and decoders-per-die are assumptions.",
          "- Surrogate numbers are labelled everywhere; only real-HotSpot numbers are eligible for the confirmed front.",
          "- LOCAL ONLY. Results use quantum hardware and must never be compared with or submitted to the Beat the Hotspot leaderboard.", ""]
    (out / "report.md").write_text("\n".join(L), encoding="utf-8")
    summary = {"leaderboard_comparable": LEADERBOARD_COMPARABLE, "notice": NOTICE, "run": rd.cfg.get("name"),
               "designs": len(al), "status": n_by, "confirmed_designs": conf_n, "hotspot_runs": rd.state.get("hotspot_runs"),
               "stop_reason": rd.state.get("stop_reason"), "front_confirmed": rd.front_conf, "front_screening": rd.front_screen,
               "best": best_id, "baseline": base_id,
               "assessments": {k: v.to_dict() for k, v in rd.assess.items()}}
    (out / "results.json").write_text(json.dumps(summary, indent=1, default=str))
    return out


def findings(rd: RunData, base_id: str | None, best_id: str | None) -> list[str]:
    out = []
    al = list(rd.assess.values())
    elig = [a for a in al if a.eligible]
    if not elig:
        return ["No design satisfied all constraints with a full evaluation; see the violations in `designs.csv`.", ""]
    inf = [a for a in al if a.status == "infeasible"]
    reasons: dict[str, int] = {}
    for a in inf:
        for v in a.violations:
            key = v.split(":")[0].split(" (")[0][:70]
            reasons[key] = reasons.get(key, 0) + 1
    if reasons:
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:5]
        out.append("Most common hard-constraint violations among the infeasible designs: " + "; ".join(f"{k} ({n})" for k, n in top) + ".")
    b = rd.assess.get(base_id) if base_id else None
    by_mode = {m: [a for a in elig if rd.design(a.design_id).genes["mode"] == m] for m in ("gpu_only", "add", "replace")}
    out.append("Eligible designs per mode: " + ", ".join(f"{MODE_LABEL[m]} {len(v)}" for m, v in by_mode.items()) + ".")
    if b:
        for m in ("add", "replace"):
            pts = by_mode[m]
            if not pts:
                continue
            def best(n, d):
                vals = [a.objectives[n] for a in pts if a.objectives.get(n) is not None]
                return (min(vals) if d == "min" else max(vals)) if vals else None
            bg, bh, be, bc = best("worst_gpu_c", "min"), best("worst_hbm_c", "min"), best("energy_j_per_work", "min"), best("capacity_rel", "max")
            out.append(f"{MODE_LABEL[m]}: best worst-GPU temperature {_f(bg)} C (GPU-only {_f(b.objectives.get('worst_gpu_c'))}), best HBM "
                       f"{_f(bh)} C (GPU-only {_f(b.objectives.get('worst_hbm_c'))}), lowest facility energy per work {_f(be, 0)} J/GPU-s "
                       f"(GPU-only {_f(b.objectives.get('energy_j_per_work'), 0)}), highest capacity {_f(bc, 3)}x. Temperature numbers are from "
                       f"{'real HotSpot' if any(a.tier == 'confirmed' for a in pts) else 'the surrogate'} where marked in the tables.")
    nd = [i for i in rd.front_conf] or rd.front_screen
    modes_on_front = {MODE_LABEL[rd.design(i).genes["mode"]] for i in nd}
    out.append(f"The {'confirmed' if rd.front_conf else 'screening'} front has {len(nd)} member(s) spanning: {', '.join(sorted(modes_on_front))}.")
    for a in elig:
        be = a.extras.get("break_even_movable_share_energy")
        if be is not None and a.design_id in nd:
            out.append(f"Design `{a.design_id}` reaches energy parity with GPU-only at a movable share of {be:.2f} (input assumption scale).")
            break
    out.append("")
    out.append("All of this is conditional on the declared inputs (offload share, classical cost of the movable job class, mapping quality) "
               "and the illustrative catalogs; the loop explores a model, it does not establish that any quantum system helps.")
    out.append("")
    return out
