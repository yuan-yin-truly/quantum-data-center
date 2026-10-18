"""Outputs of the numerical simulator: JSON, markdown and figures (same look as ``quantum_arch/report.py``).

Style: light surface, thin marks, a fixed categorical order for identity (a policy keeps its colour in every figure), direct labels
plus a legend (identity is never colour alone), no dual axes, recessive grid. The palette is the one validated for ``quantum_arch``.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from . import costs
from .config import clean_json, fmt_energy, fmt_time, fmt_usd
from .engine import Engine
from .scheduler import POLICY_LABELS

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
POLICY_COLOR = {"batch": CAT[0], "greedy": CAT[2], "fifo": CAT[1], "gpu_only": INK2, "ref_gpu_only_fleet": CAT[4]}
POLICY_NAME = {**POLICY_LABELS, "ref_gpu_only_fleet": "GPU-only reference fleet + policy"}
SITE_COLOR = {}


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK2)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=INK2, labelsize=8, length=3)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def _fig(w, h):
    return plt.figure(figsize=(w, h), facecolor=SURFACE)


def _save(fig, path: Path):
    fig.savefig(path, dpi=140, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def _hist(eng: Engine) -> np.ndarray:
    return np.array(eng.hist, dtype=float)


def fig_site_power(eng: Engine, path: Path) -> None:
    h = _hist(eng)
    sites = eng.fleet.site_list
    n = len(sites)
    fig = _fig(11, 6.2)
    t = h[:, 0] / 3600.0 + eng.start_utc_hour
    for i, s in enumerate(sites):
        ax = fig.add_subplot(2, 3, i + 1)
        _style(ax)
        p, cap, u = h[:, 1 + 3 * i], h[:, 2 + 3 * i], h[:, 3 + 3 * i]
        ax.plot(t, cap, color=INK2, lw=1.0, ls=(0, (4, 3)), label="power cap")
        ax.plot(t, p, color=CAT[0], lw=1.4, label="facility power")
        ax2 = None
        ax.set_title(f"{s.name.split('(')[0].strip()}  ({s.cooling})", fontsize=9, color=INK, loc="left")
        ax.set_ylim(0, max(cap.max(), p.max()) * 1.15)
        if i % 3 == 0:
            ax.set_ylabel("MW (facility boundary)", fontsize=8, color=INK2)
        if i >= 3:
            ax.set_xlabel("UTC hour", fontsize=8, color=INK2)
        ax.text(0.99, 0.04, f"GPU util mean {100 * u.mean():.0f} %", transform=ax.transAxes, ha="right", fontsize=7.5, color=INK2)
        if i == 0:
            ax.legend(frameon=False, fontsize=7.5, loc="lower left")
    fig.suptitle(f"Site facility power vs cap, policy {eng.policy.name}, task set {eng.ts['name']}", fontsize=10, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, path)


def fig_site_util(eng: Engine, path: Path) -> None:
    h = _hist(eng)
    sites = eng.fleet.site_list
    fig = _fig(8, 3.6)
    ax = fig.add_subplot(111)
    _style(ax)
    t = h[:, 0] / 3600.0 + eng.start_utc_hour
    for i, s in enumerate(sites):
        ax.plot(t, 100 * h[:, 3 + 3 * i], color=CAT[i % 6], lw=1.3)
        ax.text(t[-1] + 0.05, 100 * h[-1, 3 + 3 * i], s.id, fontsize=7.5, color=INK2, va="center")
    ax.set_ylabel("GPU module utilisation, %", fontsize=8, color=INK2)
    ax.set_xlabel("UTC hour", fontsize=8, color=INK2)
    ax.set_title(f"Per-site GPU utilisation (mass traffic + discrete tasks), {eng.policy.name}", fontsize=9, color=INK, loc="left")
    ax.set_xlim(t[0], t[-1] + 0.1 * (t[-1] - t[0]))
    fig.tight_layout()
    _save(fig, path)


def fig_waits(engines: dict[str, Engine], path: Path) -> None:
    fig = _fig(7.5, 3.8)
    ax = fig.add_subplot(111)
    _style(ax)
    mx = 1.0
    for name, e in engines.items():
        w = np.array(sorted(r["wait_s"] for r in e.task_rec.values() if r["wait_s"] is not None)) / 60.0
        if not len(w):
            continue
        y = np.arange(1, len(w) + 1) / len(w)
        ax.step(w, y, where="post", color=POLICY_COLOR.get(name, INK2), lw=1.4, label=POLICY_NAME.get(name, name))
        mx = max(mx, w.max())
    ax.set_xlabel("wait from first becoming schedulable to start, minutes", fontsize=8, color=INK2)
    ax.set_ylabel("share of tasks (cumulative)", fontsize=8, color=INK2)
    ax.set_xscale("symlog", linthresh=1.0)
    ax.set_title("Queue waits per policy (same tasks)", fontsize=9, color=INK, loc="left")
    ax.legend(frameon=False, fontsize=7.5, loc="lower right")
    fig.tight_layout()
    _save(fig, path)


def fig_slo(rows: list[dict], path: Path) -> None:
    keys = [("A", "A prompters"), ("B", "B agent devs"), ("C", "C knowledge"), ("tasks", "discrete tasks")]
    fig = _fig(8.5, 3.9)
    ax = fig.add_subplot(111)
    _style(ax)
    n = len(rows)
    w = 0.8 / n
    for j, r in enumerate(rows):
        vals = [r["slo"].get(k) if r["slo"].get(k) is not None else np.nan for k, _ in keys]
        x = np.arange(len(keys)) + (j - (n - 1) / 2) * w
        ax.bar(x, vals, width=w * 0.9, color=POLICY_COLOR.get(r["policy"], INK2), label=POLICY_NAME.get(r["policy"], r["policy"]))
        for xi, v in zip(x, vals):
            if not np.isnan(v):
                ax.text(xi, v + 0.5, f"{v:.0f}", ha="center", fontsize=6.5, color=INK2)
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels([k for _, k in keys], fontsize=8, color=INK2)
    ax.set_ylim(0, 108)
    ax.set_ylabel("served within SLO, %", fontsize=8, color=INK2)
    ax.set_title("SLO attainment per case (mass traffic) and discrete tasks", fontsize=9, color=INK, loc="left")
    ax.legend(frameon=False, fontsize=7, loc="lower left", ncol=2)
    fig.tight_layout()
    _save(fig, path)


def fig_pareto(rows: list[dict], path: Path) -> None:
    fig = _fig(7.5, 4.2)
    ax = fig.add_subplot(111)
    _style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    for r in rows:
        c = POLICY_COLOR.get(r["policy"], INK2)
        ax.scatter([r["usd_day_m"]], [r["served"]], s=60, color=c, edgecolor=SURFACE, linewidth=1.5, zorder=3)
        ax.annotate(POLICY_NAME.get(r["policy"], r["policy"]).split(" (")[0], (r["usd_day_m"], r["served"]), xytext=(6, 5), textcoords="offset points", fontsize=7.5, color=INK2)
    ax.set_xlabel("total cost, million USD per day (amortised capex + facility energy)", fontsize=8, color=INK2)
    ax.set_ylabel("served within SLO, % (worst case of A/B/C and tasks)", fontsize=8, color=INK2)
    ax.set_title("Score: served first (up), then dollars (left)", fontsize=9, color=INK, loc="left")
    fig.tight_layout()
    _save(fig, path)


def fig_quantum(engines: dict[str, Engine], path: Path) -> None:
    cats = ["on QPU", "classical (chosen)", "classical (QPU failed)", "rejected", "open"]
    fig = _fig(8, 3.8)
    ax = fig.add_subplot(111)
    _style(ax)
    names = list(engines)
    bottoms = np.zeros(len(names))
    data = []
    for e in engines.values():
        qd = [u for u in e.units.values() if u.kind == "quantum"]
        on_q = sum(1 for u in qd if u.route == "quantum" and u.state in ("running", "done"))
        fb = sum(1 for u in qd if u.fallback_used)
        cl = sum(1 for u in qd if u.route == "classical" and not u.fallback_used and u.state in ("running", "done"))
        rj = sum(1 for u in qd if u.state == "rejected")
        op = len(qd) - on_q - fb - cl - rj
        data.append([on_q, cl, fb, rj, max(0, op)])
    arr = np.array(data, dtype=float)
    cols = [CAT[0], CAT[2], CAT[3], INK2, GRID]
    for k, cat in enumerate(cats):
        ax.bar(range(len(names)), arr[:, k], bottom=bottoms, color=cols[k], edgecolor=SURFACE, linewidth=1.5, width=0.62, label=cat)
        bottoms += arr[:, k]
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([POLICY_NAME.get(n, n).split(" (")[0].replace(" + policy", "") for n in names], fontsize=7, color=INK2, rotation=12)
    ax.set_ylabel("quantum-eligible task units", fontsize=8, color=INK2)
    ax.set_title("Where quantum-eligible work went", fontsize=9, color=INK, loc="left")
    ax.legend(frameon=False, fontsize=7, ncol=2)
    fig.tight_layout()
    _save(fig, path)


# ---------------------------------------------------------------------------------------------------------------
def quantum_reason_table(eng: Engine, limit: int = 12) -> list[dict]:
    rows = []
    for d in eng.decisions:
        if d["action"] in ("assign", "reject", "fallback") and d.get("type", "").startswith(("quantum", "hybrid")):
            rows.append(d)
    # prefer variety: one example per (type, route/action, first 30 chars of reason)
    seen, out = set(), []
    for d in rows:
        key = (d["type"], d["action"], d.get("route"), d["reason"][:50])
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
        if len(out) >= limit:
            break
    return out


def run_markdown(eng: Engine, m: dict) -> str:
    L = []
    L.append(f"# dc_sim run: {m['taskset']} / policy {m['policy']}\n")
    L.append("*Results of an illustrative model; every demand, cost and node-count number not taken from `quantum_arch` is an ASSUMPTION "
             "(see `dc_sim/data/assumptions.json`).*\n")
    L.append(f"- fleet `{m['fleet']}`, seed {m['seed']}, simulated {fmt_time(m['t_s'])} in ticks of {m['tick_s']:.0f} s, case `{m['case']}`")
    L.append(f"- power boundary of all energy numbers: **{m['energy']['boundary']}**")
    L.append("\n## Users served within SLO\n")
    L.append("| case | users | requests served within SLO | worst tick | mean RTT |")
    L.append("|---|---|---|---|---|")
    for c, v in m["users"].items():
        if v["slo_pct"] is None:
            continue
        L.append(f"| {c} | {v['users'] / 1e6:,.0f} M | {v['slo_pct']:.2f} % | {v['worst_tick_slo_pct']:.1f} % | {v['mean_rtt_ms']:.0f} ms |")
    t = m["tasks"]
    L.append(f"\nDiscrete tasks: {t['all']['ok']}/{t['all']['n']} within SLO ({t['all']['slo_pct']:.1f} %), late {t['all']['late']}, "
             f"rejected {t['all']['rejected']}, failed {t['all']['failed']}, open at horizon {t['all']['open']}.")
    L.append(f"Headline `served` = worst of (A, B, C users within SLO, tasks within SLO) = **{m['served_pct']:.2f} %**.")
    e = m["energy"]
    L.append("\n## Energy, power, dollars\n")
    L.append(f"- facility energy {e['facility_mwh']:.1f} MWh (system {e['system_mwh']:.1f}, module {e['module_mwh']:.1f}); mean {e['mean_facility_mw']:.1f} MW, peak {e['peak_total_facility_mw']:.1f} MW of {m['power_cap']['sum_caps_mw']:.0f} MW")
    L.append(f"- site power cap never exceeded: **{m['power_cap']['never_exceeded']}** (max site ratio {m['power_cap']['max_site_ratio']:.3f})")
    c = m["cost"]
    L.append(f"- energy {fmt_usd(c['energy_usd_per_day'])}/day + capex amortised {fmt_usd(c['capex_amortised_usd_per_day'])}/day = **{fmt_usd(c['total_usd_per_day'])}/day** (5-year {fmt_usd(c['five_year_usd'])})")
    q = m["quantum"]
    L.append("\n## Quantum offload\n")
    L.append(f"- {q['units']} quantum-eligible units: {q['on_qpu']} ran on a QPU, {q['classical_alt']} classical, {q['rejected']} rejected; "
             f"QPU utilisation {q['utilisation_pct']:.1f} % over {q['n_qpu_nodes']} QPU nodes; fallbacks after failed attempts {q['fallbacks']}")
    L.append("\n| time | task | action | where | reason |")
    L.append("|---|---|---|---|---|")
    for d in quantum_reason_table(eng):
        L.append(f"| {fmt_time(d['t'])} | {d['uid']} ({d['type']}) | {d['action']} | {d['node'] or '-'} | {d['reason'][:300].replace('|', '/')} |")
    return "\n".join(L) + "\n"


def write_run(eng: Engine, out_dir: Path, figures: bool = True) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    m = eng.metrics()
    res = {"metrics": m, "decisions": eng.decisions, "units": eng.unit_table(), "tasks": list(eng.task_rec.values()),
           "history_columns": ["t_s"] + [f"{s.id}_{k}" for s in eng.fleet.site_list for k in ("facility_mw", "cap_mw", "gpu_util")] + ["slo_A", "slo_B", "slo_C", "pending", "running", "qpu_busy"],
           "history": eng.hist, "assumptions_note": "illustrative model; see dc_sim/data/assumptions.json"}
    (out_dir / "result.json").write_text(json.dumps(clean_json(res)), encoding="utf-8")
    (out_dir / "report.md").write_text(run_markdown(eng, m), encoding="utf-8")
    with open(out_dir / "assignments.csv", "w", newline="", encoding="utf-8") as f:
        rows = eng.unit_table()
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    if figures and eng.hist:
        fig_site_power(eng, out_dir / "site_power.png")
        fig_site_util(eng, out_dir / "site_util.png")
    return m


# ---------------------------------------------------------------------------------------------------------------
def compare_rows(engines: dict[str, Engine]) -> list[dict]:
    ref = engines.get("ref_gpu_only_fleet")
    same = engines.get("gpu_only")
    rows = []
    for name, e in engines.items():
        m = e.metrics()
        c = m["cost"]
        slo = {k: v["slo_pct"] for k, v in m["users"].items() if v["slo_pct"] is not None}
        slo["tasks"] = m["tasks"]["all"]["slo_pct"]
        r = {"policy": name, "served": m["served_pct"], "users_slo": m["users_slo_pct"], "tasks_slo": m["tasks"]["all"]["slo_pct"],
             "slo": slo, "energy_mwh": m["energy"]["facility_mwh"], "peak_mw": m["energy"]["peak_total_facility_mw"],
             "usd_day_m": c["total_usd_per_day"] / 1e6, "energy_usd_day": c["energy_usd_per_day"], "capex_usd": c["capex_usd"],
             "q_on_qpu": m["quantum"]["on_qpu"], "q_classical": m["quantum"]["classical_alt"], "q_rejected": m["quantum"]["rejected"],
             "q_util": m["quantum"]["utilisation_pct"], "never_exceeded": m["power_cap"]["never_exceeded"],
             "tasks_n": m["tasks"]["all"]["n"], "tasks_ok": m["tasks"]["all"]["ok"], "wait_p95_s": m["task_wait_s"]["p95"]}
        if ref is not None:
            rm = ref.metrics()["cost"]
            r["saved_vs_ref_total_usd_day"] = rm["total_usd_per_day"] - c["total_usd_per_day"]
            r["saved_vs_ref_energy_usd_day"] = rm["energy_usd_per_day"] - c["energy_usd_per_day"]
        if same is not None and name != "ref_gpu_only_fleet":
            sm = same.metrics()["cost"]
            r["saved_vs_gpu_only_policy_energy_usd_day"] = sm["energy_usd_per_day"] - c["energy_usd_per_day"]
        rows.append(r)
    return rows


def rank(rows: list[dict]) -> list[dict]:
    """Challenge score order: users served at constraints first (to 0.1 %), then dollars."""
    return sorted(rows, key=lambda r: (-round(r["served"] or 0.0, 1), r["usd_day_m"]))


def compare_markdown(engines: dict[str, Engine], rows: list[dict], name: str) -> str:
    L = [f"# dc_sim compare: {name}\n",
         "*Illustrative model. Score structure of the challenge: users served within SLO at the constraints (500 MW grid, 30 B USD), then dollars "
         "saved against the GPU-only reference (same site power caps, QPU power replaced by GPU racks, policy `gpu_only`).*\n",
         f"Power boundary of all energy figures: facility (system x (1 + network) x PUE). Dollars: capex amortised over 5 years + energy actually used, per simulated-day equivalent.\n",
         "| rank | policy | served % (worst of A/B/C/tasks) | A % | B % | C % | tasks % | facility MWh | energy USD/day | total USD/day | saved vs GPU-only ref, USD/day (total / energy only) | on QPU / classical / rejected | cap held |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rank(rows), 1):
        s = r["slo"]
        f = lambda v: "-" if v is None else f"{v:.1f}"
        sv = ""
        if "saved_vs_ref_total_usd_day" in r:
            sv = f"{r['saved_vs_ref_total_usd_day'] / 1e3:+,.0f}k / {r['saved_vs_ref_energy_usd_day'] / 1e3:+,.1f}k"
        L.append(f"| {i} | {POLICY_NAME.get(r['policy'], r['policy'])} | {r['served']:.2f} | {f(s.get('A'))} | {f(s.get('B'))} | {f(s.get('C'))} | {f(s.get('tasks'))} | "
                 f"{r['energy_mwh']:.0f} | {r['energy_usd_day'] / 1e3:,.0f}k | {r['usd_day_m'] * 1e3:,.0f}k | {sv} | {r['q_on_qpu']} / {r['q_classical']} / {r['q_rejected']} | {r['never_exceeded']} |")
    first = next(iter(engines.values()))
    be = costs.quantum_breakeven(first.fleet)
    L.append("\n## QPU break-even (what has to be true for a QPU node to pay for itself)\n")
    L.append("Per QPU node: fixed cost per day = amortised capex + standby energy; saving per job = assumed classical cost minus the QPU's marginal energy cost. "
             "The classical costs are ASSUMPTIONS (largest uncertainty).\n")
    L.append("| QPU node | workload | job occupancy | max jobs/day | classical USD/job | QPU marginal USD/job | fixed USD/day | break-even jobs/day | pays off at capacity |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for b in be:
        be_j = "never" if b["breakeven_jobs_per_day"] == float("inf") else f"{b['breakeven_jobs_per_day']:.1f}"
        L.append(f"| {b['qpu']} | {b['workload']} | {fmt_time(b['occupancy_s'])} | {b['max_jobs_per_day']:.0f} | {b['classical_usd_per_job']:.2f} | {b['qpu_marginal_usd_per_job']:.3f} | {b['fixed_usd_per_day']:,.0f} | {be_j} | {b['pays_off_at_capacity']} |")
    return "\n".join(L) + "\n"


def write_compare(engines: dict[str, Engine], out_dir: Path, name: str) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = compare_rows(engines)
    order = rank(rows)
    first = next(iter(engines.values()))
    be = costs.quantum_breakeven(first.fleet)
    bp = costs.budget_power_check(first.fleet)
    out = {"taskset": name, "ranking": order, "rows": rows, "breakeven": be, "budget_power": bp,
           "per_policy": {k: e.metrics() for k, e in engines.items()}}
    (out_dir / "compare.json").write_text(json.dumps(clean_json(out)), encoding="utf-8")
    (out_dir / "compare.md").write_text(compare_markdown(engines, rows, name), encoding="utf-8")
    fig_pareto(rows, out_dir / "score_pareto.png")
    fig_slo(rows, out_dir / "slo_per_case.png")
    fig_waits(engines, out_dir / "queue_waits.png")
    fig_quantum(engines, out_dir / "quantum_offload.png")
    best = next((e for k, e in engines.items() if k == "batch"), first)
    fig_site_power(best, out_dir / "site_power_batch.png")
    fig_site_util(best, out_dir / "site_util_batch.png")
    for k, e in engines.items():
        (out_dir / f"decisions_{k}.json").write_text(json.dumps(clean_json(e.decisions)), encoding="utf-8")
    return out
