"""Picture of the architecture-v2 pod: its building blocks, sized by a design-study result (``dc_design``).

``python -m dc_sim.arch_picture <result.json> <out.png> [induced-factor]``. Block sizes and counts come from the stored result;
the drawing is a schematic (not a floor plan). Colours are categorical (blue GPU, green CPU, orange memory, vermillion QPU,
slate control) and every block carries a direct label, so identity never depends on colour alone.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, FancyArrowPatch, FancyBboxPatch, Rectangle

C = {"gpu": "#0072B2", "cpu": "#009E73", "mem": "#E69F00", "qpu": "#D55E00", "ctl": "#44546A", "ink": "#1b2733", "mute": "#5b6773",
     "bg": "#fbfbfa", "panel": "#f1f3f4", "line": "#c9ced3"}


def _box(ax, x, y, w, h, fc, ec=None, r=0.12, lw=1.2, alpha=1.0, z=1):
    p = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec or fc, lw=lw, alpha=alpha, zorder=z)
    ax.add_patch(p)
    return p


def _arrow(ax, a, b, color, text=None, rad=0.0, lw=1.8, both=False, tx=0.0, ty=0.12):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="<|-|>" if both else "-|>", mutation_scale=13, lw=lw, color=color, connectionstyle=f"arc3,rad={rad}", zorder=5))
    if text:
        ax.text((a[0] + b[0]) / 2 + tx, (a[1] + b[1]) / 2 + ty, text, ha="center", va="bottom", fontsize=8.2, color=color, zorder=6,
                bbox=dict(fc=C["bg"], ec="none", pad=1.0, alpha=0.9))


def _grid(ax, x, y, w, h, n, color, per_row=None, gap=0.05):
    """n small rectangles (capped at 140) filling a w x h area."""
    n = max(1, min(int(n), 140))
    per_row = per_row or max(1, int(round((n * w / h) ** 0.5)))
    rows = -(-n // per_row)
    cw, ch = w / per_row, h / rows
    for i in range(n):
        r, c = divmod(i, per_row)
        ax.add_patch(Rectangle((x + c * cw + gap * cw, y + h - (r + 1) * ch + gap * ch), cw * (1 - 2 * gap), ch * (1 - 2 * gap), fc=color, ec="white", lw=0.4, zorder=3))


def _cryo(ax, x, y, w, h, color):
    ax.add_patch(Rectangle((x, y), w, h, fc=color, ec=C["ink"], lw=0.6, zorder=3))
    ax.add_patch(Ellipse((x + w / 2, y + h), w, h * 0.22, fc="#f2b48b", ec=C["ink"], lw=0.6, zorder=4))
    ax.add_patch(Ellipse((x + w / 2, y), w, h * 0.22, fc=color, ec=C["ink"], lw=0.6, zorder=3))


def _disk_stack(ax, x, y, w, h, color, n=4):
    for i in range(n):
        yy = y + i * h / n
        ax.add_patch(Rectangle((x, yy), w, h / n * 0.8, fc=color, ec=C["ink"], lw=0.6, zorder=3))
        ax.add_patch(Ellipse((x + w / 2, yy + h / n * 0.8), w, h / n * 0.5, fc=color, ec=C["ink"], lw=0.6, zorder=4))


def render(result_json, out_png, induced: str | None = None, mode: str = "park") -> Path:
    res = json.loads(Path(result_json).read_text(encoding="utf-8"))
    key = induced or next(iter(res["scenarios"]))
    cell = res["scenarios"][key]
    d, ref = cell[mode], cell["gpu_only"]
    p = res["params"]
    cap = p["pod"]["cap_mw"]
    classes = list(p["design"]["classes"])
    n_q, n_gpu, n_rack, n_cpu = d["qpus"], d["gpu_modules"], d["gpu_racks"], d["cpu_sockets"]
    fig, ax = plt.subplots(figsize=(16, 9.4), dpi=140)
    fig.patch.set_facecolor(C["bg"])
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 9.4)
    ax.axis("off")
    ax.text(0.35, 9.0, "2035 data-centre pod: pooled GPU nodes, shared QPU service, agents park while quantum sub-tasks run", fontsize=15, fontweight="bold", color=C["ink"], va="center")
    ax.text(0.35, 8.62, f"{res['users']:,.0f} users in a mix of 6 classes · {cap:.0f} MW facility cap · scenario: induced QPU demand x{float(key):g} · "
            "schematic, counts from the simulation, all unit costs and call densities are assumptions", fontsize=9.2, color=C["mute"], va="center")

    # --- users and scheduler
    _box(ax, 0.35, 5.0, 2.6, 3.2, C["panel"], C["line"])
    ax.text(1.65, 7.95, "Users and agents", ha="center", fontsize=10.5, fontweight="bold", color=C["ink"])
    cls_txt = {"coding_agents": "coding agents (use case B)", "materials": "materials engineers", "chemistry": "chemists", "biology": "biologists",
               "mechanical": "mechanical engineers", "finance": "financial engineers"}
    for i, nm in enumerate(classes):
        ax.add_patch(Ellipse((0.72, 7.5 - i * 0.43), 0.2, 0.2, fc=C["ctl"], ec="none", zorder=3))
        ax.text(0.95, 7.5 - i * 0.43, f"{cls_txt.get(nm, nm)}  {p['design']['classes'][nm]['share']:.0%}", fontsize=8.6, va="center", color=C["ink"])
    _box(ax, 0.35, 2.85, 2.6, 1.7, C["ctl"], r=0.14)
    ax.text(1.65, 4.18, "Login + scheduling node", ha="center", fontsize=10.5, fontweight="bold", color="white")
    ax.text(1.65, 3.62, "classifies tasks, keeps the\nrunning dispatch optimisation,\nsends work to a free node", ha="center", va="center", fontsize=8.4, color="white")
    ax.text(1.65, 3.05, "hybrid: may use a QPU", ha="center", fontsize=7.8, color="#d7dde5", style="italic")
    _arrow(ax, (1.65, 5.0), (1.65, 4.57), C["ctl"], lw=2.0)

    # --- pod frame
    _box(ax, 3.45, 0.95, 12.2, 7.45, "#ffffff", C["line"], r=0.2, lw=1.5)
    ax.text(3.7, 8.12, f"Pod: one site slice, liquid cooled (PUE {res['hw']['pue']:.2f})", fontsize=10.5, fontweight="bold", color=C["ink"], va="center")

    # GPU pool
    _box(ax, 3.75, 4.35, 5.1, 3.5, "#e6f0f8", C["gpu"], r=0.14)
    ax.text(3.95, 7.55, "GPU node pool", fontsize=11, fontweight="bold", color=C["gpu"], va="center")
    ax.text(3.95, 7.2, f"{n_gpu:,} accelerator modules in {n_rack:,} racks · {d['gpu_mean_mw']:.1f} MW (IT)", fontsize=8.8, color=C["ink"], va="center")
    _grid(ax, 4.0, 4.6, 4.6, 2.15, n_rack, C["gpu"], per_row=int(max(1, round((n_rack * 4.6 / 2.15) ** 0.5))))
    ax.text(8.7, 4.47, f"1 square = {max(1, -(-n_rack // 140))} rack(s) of 64 modules", fontsize=7, color=C["mute"], ha="right")
    ax.text(3.95, 6.9, "all nodes identical: prefill, decode, any user class", fontsize=8, color=C["mute"], va="center", style="italic")

    # CPU sandbox pool
    _box(ax, 9.15, 5.7, 3.1, 2.15, "#e5f4ee", C["cpu"], r=0.14)
    ax.text(9.35, 7.55, "CPU sandbox pool", fontsize=11, fontweight="bold", color=C["cpu"], va="center")
    ax.text(9.35, 7.2, f"{n_cpu:,} sockets · {d['cpu_mean_mw']:.1f} MW", fontsize=8.8, color=C["ink"], va="center")
    _grid(ax, 9.4, 6.05, 2.6, 0.85, max(1, n_cpu // 32), C["cpu"], per_row=16)
    ax.text(9.35, 5.78, "background tool calls run here", fontsize=7.6, color=C["mute"], va="bottom", style="italic")

    # Context memory
    _box(ax, 12.55, 5.7, 2.85, 2.15, "#fbf0d9", C["mem"], r=0.14)
    ax.text(12.75, 7.55, "Context-memory pool", fontsize=11, fontweight="bold", color="#8a5a00", va="center")
    ax.text(12.75, 7.2, "parked agent sessions", fontsize=8.8, color=C["ink"], va="center")
    _disk_stack(ax, 13.0, 5.85, 0.9, 1.1, C["mem"])
    ax.text(14.05, 6.4, f"{d['ctxmem_tb']:.1f} TB parked\n(peak margin incl.)\n{('<1' if d['ctx_mean_mw'] * 1000 < 0.5 else format(d['ctx_mean_mw'] * 1000, '.0f'))} kW", fontsize=8.2, color=C["ink"], va="center")

    # QPU service
    _box(ax, 9.65, 2.0, 5.75, 3.4, "#fbe7dc", C["qpu"], r=0.14)
    ax.text(9.85, 5.08, "Shared QPU service", fontsize=11, fontweight="bold", color="#a13f00", va="center")
    ax.text(9.85, 4.73, f"{n_q} QPU systems (cat qubits, 270 kW each) · {d['qpu_mean_mw']:.1f} MW (IT) · {d['qpu_util']:.0%} busy", fontsize=8.6, color=C["ink"], va="center")
    per_row = 21
    unit = max(1, -(-n_q // 63))
    nshow = -(-n_q // unit)
    for i in range(nshow):
        r, c = divmod(i, per_row)
        _cryo(ax, 9.9 + c * 0.25, 3.85 - r * 0.62, 0.19, 0.48, C["qpu"])
    ax.text(9.85, 2.12, f"classes sent here: {', '.join(cls_txt.get(c, c).split(' (')[0] for c in d['admitted']) or 'none'}", fontsize=8.2, color=C["ink"], va="bottom")
    ax.text(15.25, 5.08, f"1 cylinder = {unit} QPU", fontsize=7.4, color=C["mute"], ha="right", va="center")

    # fabric + power/cooling
    _box(ax, 3.75, 3.55, 5.1, 0.5, C["ctl"], r=0.1, alpha=0.92)
    ax.text(6.3, 3.8, "Network fabric (400 Gbit/s per node)", ha="center", va="center", fontsize=9, color="white", fontweight="bold")
    _box(ax, 3.75, 1.2, 11.65, 0.6, "#e9edf0", C["line"], r=0.1)
    over = d["mean_facility_mw"] - (d["gpu_mean_mw"] + d["cpu_mean_mw"] + d["qpu_mean_mw"] + d["ctx_mean_mw"])
    ax.text(9.57, 1.5, f"Power, cooling and network overhead: {over:.1f} MW  ·  total {d['mean_facility_mw']:.1f} MW mean, {d['peak_facility_mw']:.1f} MW peak (cap {cap:.0f} MW)", ha="center", va="center", fontsize=9, color=C["ink"])

    # --- flows
    _arrow(ax, (2.95, 3.7), (3.75, 5.3), C["ctl"], "tasks", rad=-0.15, lw=2.2, tx=-0.15, ty=0.05)
    _arrow(ax, (8.85, 6.8), (9.15, 6.8), C["cpu"], None, both=True, lw=2.0)
    ax.text(9.0, 7.0, "tool\ncalls", ha="center", fontsize=7.4, color=C["cpu"], va="bottom")
    _arrow(ax, (8.85, 7.72), (12.55, 7.72), C["mem"], None, rad=-0.1, both=True, lw=2.0)
    ax.text(10.7, 8.0, "park / resume session", ha="center", fontsize=8.3, color="#8a5a00", bbox=dict(fc="white", ec="none", pad=0.8))
    _arrow(ax, (8.85, 4.75), (9.65, 4.75), C["qpu"], None, lw=2.2)
    ax.text(9.25, 4.88, "quantum\nsub-task", ha="center", fontsize=7.4, color="#a13f00", va="bottom")
    _arrow(ax, (14.0, 5.7), (13.6, 5.4), C["mem"], None, lw=1.6)
    ax.text(14.2, 5.56, "session state", fontsize=7, color="#8a5a00", va="center")

    # --- bottom strip: key numbers
    cp = d
    txt = [("Calls to QPU service", f"{cp['calls_on_qpu']:,} / day", C["qpu"]), ("Calls run classically", f"{cp['calls_classical']:,} / day", C["gpu"]),
           ("Calls unserved", f"{cp['calls_unserved']:,} / day  (ref {ref['calls_unserved']:,})", C["ctl"]),
           ("Cost", f"\\${cp['usd_day'] / 1e3:,.0f}k / day  (ref \\${ref['usd_day'] / 1e3:,.0f}k)", C["ctl"]),
           ("Energy per task", f"{cp['j_per_task_facility'] / 1e3:.0f} kJ  (ref {ref['j_per_task_facility'] / 1e3:,.0f} kJ)", C["ctl"])]
    x = 0.35
    for lab, val, col in txt:
        w = {"Calls to QPU service": 2.65, "Calls run classically": 2.65, "Calls unserved": 3.1, "Cost": 3.7, "Energy per task": 3.2}[lab]
        _box(ax, x, 0.12, w - 0.1, 0.62, C["panel"], C["line"], r=0.08)
        ax.text(x + 0.12, 0.55, lab, fontsize=7.8, color=C["mute"], va="center")
        ax.text(x + 0.12, 0.3, val, fontsize=8.6, color=C["ink"], va="center", fontweight="bold")
        x += w
    ax.text(0.35, 0.88, f"GPU-only reference for the same task load: {ref['gpu_modules']:,} modules, {ref['mean_facility_mw']:.0f} MW (its cost is dominated by the assumed classical price of the quantum-eligible calls).",
            fontsize=8, color=C["mute"], va="center", style="italic")
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return out


if __name__ == "__main__":
    a = sys.argv
    print(render(a[1], a[2], a[3] if len(a) > 3 else None))
