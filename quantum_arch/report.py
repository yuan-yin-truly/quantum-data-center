"""Tables, JSON and figures for one result or a comparison of several.

Figures follow one small style: light surface, thin marks, one hue for a single
series, a fixed categorical order (blue, orange, aqua, yellow, magenta, green)
whenever identity matters, direct labels instead of dense legends.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .architecture import Result, _fmt_w  # noqa: E402
from .workloads import human_energy, human_time  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
SEQ_CMAP = "Oranges"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK2)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=INK2, labelsize=9, length=3)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _fig(w, h):
    fig = plt.figure(figsize=(w, h), facecolor=SURFACE)
    return fig


def _eng(x: float, unit: str = "W") -> str:
    return _fmt_w(x) if unit == "W" else f"{x:.3g} {unit}"


# ---------------------------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------------------------
def _finite(x):
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


def to_dict(r: Result) -> dict:
    cap = r.capability
    out = {
        "name": r.arch.name,
        "modality": r.modality["label"],
        "scheme": r.scheme_label,
        "profile": r.arch["profile"],
        "n_qubits": r.arch["n_qubits"],
        "error_budget": {"syndrome_cycle_s": r.budget.cycle_s, "p_eff": r.budget.p_eff,
                         "lambda": r.capability.lam, "parts": r.budget.parts},
        "computing": {"feasible": cap.feasible, "reason": cap.reason, "code": r.code.label,
                      "distance": cap.distance, "logical_qubits": cap.logical_qubits,
                      "logical_clock_hz": cap.logical_clock_hz, "rqops": cap.rqops,
                      "logical_error_per_op": _finite(cap.logical_error_per_op),
                      "target_logical_error": r.arch["qec"]["target_logical_error"]},
        "decoder": {k: v for k, v in r.decoder_info.items()},
        "power_w": r.power_w,
        "total_power_w": r.total_power_w,
        "facility_power_w": r.metrics["facility_power_w"],
        "metrics": {k: _finite(v) for k, v in r.metrics.items()},
        "classical_blocks": [{"role": b.role, "device": b.device.label, "count": b.count, "location": b.location,
                              "utilisation": b.utilisation, "power_w": b.power_w, "keeps_up": b.keeps_up}
                             for b in r.blocks],
        "line_counts": r.line_counts,
        "workloads": r.workloads,
        "warnings": r.warnings,
    }
    if r.cryo:
        out["cryostat"] = {
            "type": r.cryo.fridge.label, "units_needed": r.cryo.units_needed,
            "units_for_heat": r.cryo.units_for_heat, "units_for_lines": r.cryo.units_for_lines,
            "n_lines": r.cryo.n_lines, "wall_power_w": r.cryo.wall_power_w,
            "carnot_floor_w": r.cryo.carnot_floor_w,
            "stages": [{"name": s.name, "target_k": s.target_k, "temperature_k": s.temperature_k,
                        "load_w": s.load_w, "capacity_w": s.capacity_w, "utilisation": _finite(s.utilisation),
                        "passive_w": s.passive_w, "active_w": s.active_w, "components_w": s.components_w,
                        "sources_w": s.by_source} for s in r.cryo.stages]}
    out["plates"] = [{"name": p.plate.name, "stage_k": p.plate.t_stage_k, "t_max_k": p.t_max_k,
                      "rise_max_k": p.rise_max_k, "rise_mean_k": p.rise_mean_k,
                      "peak_power_density_w_per_cm2": p.peak_power_density_w_per_cm2,
                      "injected_w": p.injected_w, "removed_w": p.removed_w} for p in r.plates]
    out["plate_notes"] = r.plate_notes
    return out


# ---------------------------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------------------------
def _table(headers: list[str], rows: Iterable[list[str]]) -> str:
    rows = list(rows)
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _advantage(ratio: float) -> str:
    """Quantum energy against the classical alternative; ratio = classical / quantum."""
    if ratio >= 1:
        return f" (quantum uses {ratio:.2g}× less)"
    return f" (quantum uses {1 / ratio:.2g}× more)"


def summary_markdown(r: Result) -> str:
    m, cap = r.metrics, r.capability
    L: list[str] = [f"# {r.arch.name}", "",
                    f"{r.modality['label']}, {r.arch['n_qubits']:,} physical qubits, `{r.arch['profile']}` "
                    f"hardware profile. Control scheme: {r.scheme_label}.", ""]
    L += ["## Computing power", "",
          _table(["quantity", "value"], [
              ["syndrome cycle", human_time(r.budget.cycle_s)],
              ["effective physical error p", f"{r.budget.p_eff:.2e}"],
              [f"error suppression Λ = p_th/p ({r.code.label})", f"{cap.lam:.2f}"
               + ("" if cap.lam > 1 else "  (above threshold)")],
              ["code distance for target", str(cap.distance) if cap.distance else "n/a"],
              ["logical qubits", f"{cap.logical_qubits:,}"],
              ["logical clock", f"{cap.logical_clock_hz:,.3g} Hz"],
              ["rQOPS", f"{cap.rqops:,.3g}"],
              ["logical error per op", f"{cap.logical_error_per_op:.1e} (target {r.arch['qec']['target_logical_error']:.0e})"
               if cap.logical_error_per_op is not None else "n/a"],
              ["peak physical 2-qubit gate rate", f"{m['peak_2q_gate_rate_hz']:.3g} /s"],
          ])]
    if not cap.feasible:
        L += ["", f"> No error-corrected computing: {cap.reason}"]
    if r.decoder_info.get("decoder"):
        d = r.decoder_info
        L += ["", f"Decoder `{d['decoder']}`: {d['syndrome_bits_per_s']:.3g} syndrome bits/s, "
                  f"{d['required_ops_per_s']:.3g} op/s, decode latency {human_time(d['latency_s'])}, "
                  f"control reaction time {human_time(d['reaction_time_s'])}."]

    L += ["", "## Energy", "",
          _table(["consumer", "power", "share"], [
              [k, _fmt_w(v), f"{100 * v / r.total_power_w:.1f} %"]
              for k, v in sorted(r.power_w.items(), key=lambda kv: -kv[1])]
              + [["**total (system)**", f"**{_fmt_w(r.total_power_w)}**", ""],
                 [f"with facility overhead (PUE {r.arch['facility']['pue']})", _fmt_w(m['facility_power_w']), ""]]),
          "",
          f"Energy per physical 2-qubit gate (all qubits busy): {m['energy_per_2q_gate_j']:.3g} J. "
          + (f"Energy per logical operation: {m['energy_per_logical_op_j']:.3g} J." if cap.rqops else "")]
    if r.cryo:
        L[-1] += (f" Thermodynamic (Carnot) floor for the cryostat heat loads: {_fmt_w(r.cryo.carnot_floor_w)}, "
                  f"against {_fmt_w(r.cryo.wall_power_w)} installed.")

    if r.cryo:
        c = r.cryo
        L += ["", "## Heat scheme", "",
              f"{c.fridge.label}: {c.units_needed} unit(s) needed ({c.units_for_heat} for heat, "
              f"{c.units_for_lines} for {c.n_lines:,} lines).", "",
              _table(["stage", "target", "settles at", "load", "capacity", "utilisation", "largest sources"], [
                  [s.name, f"{s.target_k:g} K", f"{s.temperature_k:.3g} K", _fmt_w(s.load_w), _fmt_w(s.capacity_w),
                   f"{s.utilisation:.0%}" + (" ⚠" if s.overloaded else ""),
                   ", ".join(f"{k.split(': ')[-1]} {_fmt_w(v)}" for k, v in
                             sorted(s.by_source.items(), key=lambda kv: -kv[1])[:3])]
                  for s in c.stages])]
    if r.plates or r.plate_notes:
        L += ["", "## Spatial thermal maps", ""]
        if r.plates:
            L += [_table(["plate", "stage T", "peak T", "max rise", "mean rise", "peak power density", "heat conserved"], [
                [p.plate.name, f"{p.plate.t_stage_k:.3g} K", f"{p.t_max_k:.4g} K", f"{p.rise_max_k * 1e3:.3g} mK",
                 f"{p.rise_mean_k * 1e3:.3g} mK", f"{p.peak_power_density_w_per_cm2:.3g} W/cm²",
                 f"{abs(p.removed_w - p.injected_w) / max(p.injected_w, 1e-30):.1e} rel. err."] for p in r.plates])]
        L += [f"- {n}" for n in r.plate_notes]

    L += ["", "## Workloads", "",
          _table(["workload", "result", "time", "energy", "classical alternative"], [
              [w["label"],
               (f"d={w['distance']}, {w['physical_qubits_used']:,} qubits ({w['bound']})" if w.get("feasible")
                and w["type"] == "fault_tolerant" else
                (f"fidelity {w['circuit_fidelity']:.2g}" if w.get("feasible") else "✗ " + w["reason"])),
               w.get("runtime", "—"), w.get("energy", "—"),
               (f"{w['classical_energy']}" + (_advantage(w["energy_advantage"]) if "energy_advantage" in w else "")
                if "classical_energy" in w else w.get("classical_note", "none feasible"))]
              for w in r.workloads.values()])]
    if r.warnings:
        L += ["", "## Warnings", ""] + [f"- {w}" for w in r.warnings]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------------------------
def fig_heat_budget(r: Result, path: Path) -> None:
    c = r.cryo
    names = [s.name for s in c.stages]
    util = np.maximum(np.array([s.utilisation for s in c.stages]), 1e-3)
    fig = _fig(11, 3.2 + 0.35 * len(names))
    ax = fig.add_axes([0.07, 0.2, 0.5, 0.62])
    y = np.arange(len(names))[::-1]
    ax.barh(y, util, color=CATEGORICAL[0], height=0.55)
    ax.axvline(1.0, color=INK, linewidth=1.0)
    ax.set_xscale("log")
    lo = max(1e-3, min(0.01, util.min() / 2))
    ax.set_xlim(lo, max(util.max() * 60, 100))
    ax.set_yticks(y, names)
    for yi, s in zip(y, c.stages):
        ax.text(max(s.utilisation, lo) * 1.15, yi, f"{_fmt_w(s.load_w)} / {_fmt_w(s.capacity_w)}"
                + ("  ⚠ over" if s.overloaded else ""), va="center", fontsize=8.5, color=INK)
    ax.set_xlabel("heat load / cooling capacity at the target temperature (1 = full)", color=INK2, fontsize=9)
    ax.set_title("Heat load against capacity", loc="left", color=INK, fontsize=11)
    _style(ax)

    ax2 = fig.add_axes([0.66, 0.2, 0.32, 0.62])
    parts = [("passive wiring", [s.passive_w for s in c.stages]), ("active dissipation", [s.active_w for s in c.stages]),
             ("electronics / chips", [s.components_w for s in c.stages])]
    tot = np.array([max(s.load_w, 1e-30) for s in c.stages])
    left = np.zeros(len(names))
    for (label, vals), colour in zip(parts, CATEGORICAL):
        share = np.array(vals) / tot
        ax2.barh(y, share, left=left, color=colour, height=0.55, label=label, edgecolor=SURFACE, linewidth=1.5)
        left += share
    ax2.set_yticks(y, [])
    ax2.set_xlim(0, 1)
    ax2.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax2.set_title("Where the heat comes from", loc="left", color=INK, fontsize=11)
    _style(ax2)
    handles, labels = ax2.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower right", ncol=3, frameon=False, fontsize=8.5, labelcolor=INK2,
               bbox_to_anchor=(0.99, 0.0))
    fig.suptitle(f"{r.arch.name}: heat budget", x=0.01, ha="left", color=INK, fontsize=12)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def fig_power(r: Result, path: Path) -> None:
    items = sorted(r.power_w.items(), key=lambda kv: kv[1])
    fig = _fig(8, 1.6 + 0.45 * len(items))
    ax = fig.add_axes([0.38, 0.18, 0.55, 0.62])
    y = np.arange(len(items))
    ax.barh(y, [v for _, v in items], color=CATEGORICAL[0], height=0.55)
    ax.set_yticks(y, [k for k, _ in items])
    top = max(v for _, v in items)
    for yi, (_, v) in zip(y, items):
        ax.text(v + top * 0.01, yi, f"{_fmt_w(v)}  ({100 * v / r.total_power_w:.0f} %)", va="center", fontsize=8.5, color=INK)
    ax.set_xlim(0, top * 1.35)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _fmt_w(v)))
    ax.set_title(f"{r.arch.name}: electrical power, total {_fmt_w(r.total_power_w)}", loc="left", color=INK, fontsize=11)
    _style(ax)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def fig_plate(res, path: Path) -> None:
    p = res.plate
    fig = _fig(5.6, 4.6)
    ax = fig.add_axes([0.1, 0.1, 0.72, 0.78])
    lx, ly = p.size_mm
    rise = (res.temperature_k - p.t_stage_k) * 1e3 if res.rise_max_k < 0.5 else res.temperature_k - p.t_stage_k
    unit = "mK" if res.rise_max_k < 0.5 else "K"
    im = ax.imshow(rise, origin="lower", extent=(0, lx, 0, ly), cmap=SEQ_CMAP, interpolation="nearest")
    for s in p.sources:
        ax.add_patch(plt.Rectangle((s.x_mm, s.y_mm), s.w_mm, s.h_mm, fill=False, edgecolor=INK, linewidth=0.7))
    ax.set_xlabel("mm", color=INK2, fontsize=9)
    ax.set_ylabel("mm", color=INK2, fontsize=9)
    ax.set_title(f"{p.name}: rise above the {p.t_stage_k:.3g} K plate", loc="left", color=INK, fontsize=10.5)
    ax.tick_params(colors=INK2, labelsize=8)
    cax = fig.add_axes([0.85, 0.1, 0.025, 0.78])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label(f"temperature rise ({unit})", color=INK2, fontsize=9)
    cb.ax.tick_params(colors=INK2, labelsize=8)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def write_report(r: Result, outdir: str | Path) -> Path:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(to_dict(r), indent=2, default=float), encoding="utf-8")
    (out / "summary.md").write_text(summary_markdown(r), encoding="utf-8")
    fig_power(r, out / "power.png")
    if r.cryo:
        fig_heat_budget(r, out / "heat_budget.png")
    for i, p in enumerate(r.plates):
        fig_plate(p, out / f"temperature_map_{i}.png")
    return out


# ---------------------------------------------------------------------------------------------
# comparison and sweeps
# ---------------------------------------------------------------------------------------------
def comparison_rows(results: list[Result]) -> list[dict]:
    rows = []
    for r in results:
        m, cap = r.metrics, r.capability
        worst = max((s.utilisation for s in r.cryo.stages), default=0.0) if r.cryo else 0.0
        rows.append({
            "architecture": r.arch.name, "modality": r.modality["label"], "qubits": r.arch["n_qubits"],
            "p_eff": r.budget.p_eff, "lambda": cap.lam, "cycle_s": r.budget.cycle_s,
            "logical_qubits": cap.logical_qubits, "distance": cap.distance or 0, "rqops": cap.rqops,
            "power_w": r.total_power_w, "energy_per_logical_op_j": m["energy_per_logical_op_j"],
            "energy_per_2q_gate_j": m["energy_per_2q_gate_j"],
            "fridge_units": m["fridge_units"], "worst_stage_utilisation": worst,
            "feasible_single_fridge": (not r.cryo) or r.cryo.feasible_single_unit,
        })
    return rows


def comparison_markdown(results: list[Result]) -> str:
    rows = comparison_rows(results)
    t = _table(["architecture", "qubits", "Λ", "logical qubits", "d", "rQOPS", "power", "J / logical op",
                "fridges", "worst stage util."], [[
        x["architecture"], f"{x['qubits']:,}", f"{x['lambda']:.2f}", f"{x['logical_qubits']:,}", x["distance"] or "—",
        f"{x['rqops']:.3g}" if x["rqops"] else "—", _fmt_w(x["power_w"]),
        f"{x['energy_per_logical_op_j']:.3g}" if math.isfinite(x["energy_per_logical_op_j"]) else "—",
        x["fridge_units"] or "none", f"{x['worst_stage_utilisation']:.0%}" if x["fridge_units"] else "—"] for x in rows])
    wl_keys = list(dict.fromkeys(k for r in results for k in r.workloads))
    wl = _table(["architecture"] + [results[0].workloads.get(k, {}).get("label", k) if k in results[0].workloads else k
                                    for k in wl_keys], [[r.arch.name] + [
        (f"{r.workloads[k]['runtime']}, {r.workloads[k]['energy']}" if r.workloads[k].get("feasible") else "✗")
        for k in wl_keys] for r in results])
    return f"# Architecture comparison\n\n{t}\n\n## Workloads (time, energy)\n\n{wl}\n"


def fig_comparison(results: list[Result], path: Path) -> None:
    n = len(results)
    cats = list(dict.fromkeys(k for r in results for k in r.power_w))[:6]
    fig = _fig(13, 2.6 + 0.5 * n)
    ax = fig.add_axes([0.17, 0.26, 0.36, 0.6])
    y = np.arange(n)[::-1]
    left = np.zeros(n)
    totals = np.array([r.total_power_w for r in results])
    for cat, colour in zip(cats, CATEGORICAL):
        share = np.array([r.power_w.get(cat, 0.0) for r in results]) / totals
        ax.barh(y, share, left=left, color=colour, height=0.55, label=cat, edgecolor=SURFACE, linewidth=1.5)
        left += share
    for yi, tot in zip(y, totals):
        ax.text(1.02, yi, _fmt_w(tot), va="center", fontsize=8.5, color=INK)
    ax.set_yticks(y, [r.arch.name for r in results])
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title("Who draws the power (share of system total)", loc="left", color=INK, fontsize=10.5)
    _style(ax)
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower left", ncol=3, frameon=False, fontsize=8, labelcolor=INK2,
               bbox_to_anchor=(0.04, 0.0))

    ax2 = fig.add_axes([0.68, 0.26, 0.29, 0.6])
    for r, colour in zip(results, CATEGORICAL * 2):
        if r.capability.rqops > 0:
            ax2.scatter(r.total_power_w, r.capability.rqops, s=60, color=colour, edgecolor=SURFACE, linewidth=1.5, zorder=3)
            ax2.annotate(r.arch.name, (r.total_power_w, r.capability.rqops), xytext=(6, 5),
                         textcoords="offset points", fontsize=8, color=INK)
    ax2.set_xscale("log")
    ax2.set_yscale("log")
    ax2.set_xlabel("system electrical power (W)", color=INK2, fontsize=9)
    ax2.set_ylabel("rQOPS (logical qubits × logical clock)", color=INK2, fontsize=9)
    ax2.set_title("Reliable computing against power", loc="left", color=INK, fontsize=10.5)
    ax2.grid(color=GRID, linewidth=0.6)
    _style(ax2)
    ax2.grid(axis="y", color=GRID, linewidth=0.6)
    if not any(r.capability.rqops > 0 for r in results):
        ax2.text(0.5, 0.5, "no architecture reaches\nerror-corrected operation", transform=ax2.transAxes,
                 ha="center", va="center", color=INK2, fontsize=10)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def fig_stage_heatmap(results: list[Result], path: Path) -> None:
    stages = ["50K", "4K", "Still", "CP", "MXC"]
    data = np.full((len(results), len(stages)), np.nan)
    for i, r in enumerate(results):
        if r.cryo:
            for s in r.cryo.stages:
                if s.name in stages:
                    data[i, stages.index(s.name)] = s.utilisation
    fig = _fig(7.5, 1.4 + 0.45 * len(results))
    ax = fig.add_axes([0.28, 0.2, 0.62, 0.62])
    im = ax.imshow(np.log10(np.clip(np.nan_to_num(data, nan=1e-3), 1e-3, None)), cmap=SEQ_CMAP, aspect="auto", vmin=-2, vmax=3)
    ax.set_xticks(range(len(stages)), stages)
    ax.set_yticks(range(len(results)), [r.arch.name for r in results])
    for i, r in enumerate(results):
        if not r.cryo:
            ax.text(len(stages) / 2 - 0.5, i, "no cryostat", ha="center", va="center", fontsize=8, color=INK2)
        for j in range(len(stages)):
            if not np.isnan(data[i, j]):
                ax.text(j, i, f"{data[i, j]:.0%}" if data[i, j] < 10 else f"{data[i, j]:.0f}×", ha="center",
                        va="center", fontsize=8, color=INK if data[i, j] < 100 else "#ffffff")
    ax.set_title("Stage utilisation (load / capacity), colour on a log scale", loc="left", color=INK, fontsize=10.5)
    ax.tick_params(colors=INK2, labelsize=8.5)
    for side in ax.spines.values():
        side.set_visible(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.set_ticks([-2, -1, 0, 1, 2, 3], labels=["1 %", "10 %", "100 %", "10×", "100×", "1000×"])
    cb.ax.tick_params(colors=INK2, labelsize=8)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def write_comparison(results: list[Result], outdir: str | Path) -> Path:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison.md").write_text(comparison_markdown(results), encoding="utf-8")
    rows = comparison_rows(results)
    with (out / "comparison.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    fig_comparison(results, out / "comparison.png")
    fig_stage_heatmap(results, out / "stage_utilisation.png")
    for r in results:
        write_report(r, out / "architectures" / _slug(r.arch.name))
    return out


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_").lower()


def fig_sweep(rows: list[dict], stage_names: list[str], title: str, path: Path) -> None:
    ns = np.array([r["n"] for r in rows])
    fig = _fig(12, 4.3)
    ax = fig.add_axes([0.07, 0.17, 0.38, 0.68])
    for name, colour in zip(stage_names, CATEGORICAL):
        ax.plot(ns, [r["utilisation"].get(name, np.nan) for r in rows], color=colour, linewidth=2, label=name)
    ax.axhline(1.0, color=INK, linewidth=1.0)
    ax.text(ns[0], 1.08, "capacity of one fridge", fontsize=8.5, color=INK2)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("physical qubits", color=INK2, fontsize=9)
    ax.set_ylabel("stage load / capacity", color=INK2, fontsize=9)
    ax.set_title("Which stage runs out first", loc="left", color=INK, fontsize=10.5)
    _style(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, loc="upper left")

    ax2 = fig.add_axes([0.58, 0.17, 0.38, 0.68])
    ax2.plot(ns, [r["power_w"] for r in rows], color=CATEGORICAL[0], linewidth=2)
    ax2.scatter(ns, [r["power_w"] for r in rows], color=CATEGORICAL[0], s=28, zorder=3, edgecolor=SURFACE, linewidth=1.2)
    ax2.set_xscale("log")
    ax2.set_yscale("log")
    ax2.set_xlabel("physical qubits", color=INK2, fontsize=9)
    ax2.set_ylabel("system electrical power (W)", color=INK2, fontsize=9)
    ax2.set_title("Wall-plug power (fridge units in labels)", loc="left", color=INK, fontsize=10.5)
    for r in rows[:: max(1, len(rows) // 6)]:
        ax2.annotate(f"{r['fridges']}", (r["n"], r["power_w"]), xytext=(0, 8), textcoords="offset points",
                     fontsize=8, color=INK2, ha="center")
    _style(ax2)
    ax2.grid(axis="y", color=GRID, linewidth=0.6)
    fig.suptitle(title, x=0.01, ha="left", color=INK, fontsize=12)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
