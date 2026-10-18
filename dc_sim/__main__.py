"""Command line: ``python -m dc_sim <command>``.

  run      one fleet + task file + policy      ->  JSON, markdown, figures
  compare  all policies on the same tasks       ->  score table, Pareto, SLO, waits, quantum offload
  presets  write/list the preset task files
  list     policies, presets, fleet summary
  fleet    describe a fleet and check it against 500 MW / 30 B USD
  serve    the visual simulation (127.0.0.1 only)
  replay   export a self-contained static HTML replay
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import api, costs, presets, report
from .config import EXAMPLE_RUNS, PRESET_DIR, DATA, fmt_usd
from .engine import Engine
from .fleet import Fleet, default_fleet_spec
from .scheduler import POLICIES


def _tasks_arg(a) -> str | None:
    return a.tasks


def cmd_run(a) -> int:
    eng = api.run_policy(a.fleet, a.tasks, a.policy, a.seed, a.tick)
    m = eng.metrics()
    if a.out:
        report.write_run(eng, Path(a.out))
    print(report.run_markdown(eng, m) if not a.quiet else json.dumps({"served_pct": m["served_pct"], "usd_per_day": m["cost"]["total_usd_per_day"]}))
    return 0


def cmd_compare(a) -> int:
    names = [a.tasks] if a.tasks else presets.NAMES
    for nm in names:
        engines = api.compare_policies(a.fleet, nm, tuple(a.policies) if a.policies else POLICIES, a.seed, a.tick)
        label = Path(nm).stem if nm.endswith(".json") else nm
        out_dir = Path(a.out) / label if a.out else None
        if out_dir:
            report.write_compare(engines, out_dir, label)
        rows = report.compare_rows(engines)
        print(f"\n== {label} ==")
        print(f"{'policy':34s} {'served%':>8s} {'A%':>6s} {'B%':>6s} {'C%':>6s} {'tasks%':>7s} {'MWh':>7s} {'total k$/day':>13s} {'saved vs ref k$/day (total/energy)':>36s}  QPU/cls/rej")
        for r in report.rank(rows):
            s = r["slo"]
            g = lambda v: "   -" if v is None else f"{v:6.1f}"
            sv = f"{r.get('saved_vs_ref_total_usd_day', 0) / 1e3:+9,.0f} / {r.get('saved_vs_ref_energy_usd_day', 0) / 1e3:+7,.1f}"
            print(f"{report.POLICY_NAME.get(r['policy'], r['policy'])[:34]:34s} {r['served']:8.2f} {g(s.get('A'))} {g(s.get('B'))} {g(s.get('C'))} {g(s.get('tasks')):>7s} {r['energy_mwh']:7.0f} {r['usd_day_m'] * 1e3:13,.0f} {sv:>36s}  {r['q_on_qpu']}/{r['q_classical']}/{r['q_rejected']}")
    return 0


def cmd_presets(a) -> int:
    if a.write:
        for p in presets.write_all():
            print("wrote", p)
    for n in api.list_presets():
        ts = json.loads((PRESET_DIR / f"{n}.json").read_text(encoding="utf-8"))
        print(f"{n:28s} {len(ts['tasks']):4d} tasks, {len(ts['events'])} events, {ts['horizon_s'] / 3600:4.0f} h, case {ts['case']}: {ts['description'][:90]}")
    return 0


def cmd_list(a) -> int:
    print("policies:", ", ".join(POLICIES))
    print("presets :", ", ".join(api.list_presets()))
    f = Fleet.load(a.fleet)
    for r in f.summary()["sites"]:
        print(f"  {r['id']:9s} cap {r['cap_mw']:5.0f} MW  {r['cooling']:9s} price {r['price']:4.0f}  GPU modules {r['gpu_modules']:6.0f} ({r['modules_per_rack']}/rack)  nodes {r['nodes']}")
    return 0


def cmd_fleet(a) -> int:
    f = Fleet.load(a.fleet)
    b = costs.budget_power_check(f)
    print(f"fleet {f.name}: sum of site caps {b['sum_site_caps_mw']:.0f} MW (grid {b['grid_total_mw']:.0f} MW) -> power {'OK' if b['power_ok'] else 'EXCEEDED'}")
    print(f"capex {fmt_usd(b['capex_usd'])} + 5-year energy {fmt_usd(b['energy_usd_5y_estimate'])} = {fmt_usd(b['total_5y_usd'])} of {fmt_usd(b['budget_usd'])} "
          f"({b['budget_used_pct']:.0f} %) -> budget {'OK' if b['budget_ok'] else 'EXCEEDED'}")
    for k, v in sorted(b["capex_by_type"].items(), key=lambda kv: -kv[1]):
        print(f"   capex {k:18s} {fmt_usd(v)}")
    for s in b["sites"]:
        print(f"   {s['site']:9s} cap {s['cap_mw']:5.1f} MW, all nodes at 100 % {s['peak_all_nodes_mw']:5.1f} MW{' (overbuilt: throttled)' if s['overbuilt'] else ''}, mean {s['mean_facility_mw']:5.1f} MW")
    if a.write_default:
        Path(DATA / "fleet_default.json").write_text(json.dumps(default_fleet_spec(), indent=1), encoding="utf-8")
        print("rewrote data/fleet_default.json")
    return 0


def cmd_serve(a) -> int:
    from . import server
    server.serve(a.port, a.fleet)
    return 0


def cmd_replay(a) -> int:
    from . import replay
    out = replay.export_html(a.fleet, a.tasks, a.policy, a.out, a.seed, a.every)
    print("wrote", out)
    return 0


def cmd_arch_study(a) -> int:
    from . import arch_study
    res = arch_study.run_study(a.out, quick=a.quick)
    print(arch_study.study_markdown(res))
    if a.out:
        print(f"wrote result.json, summary.md and figures to {a.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dc_sim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, tasks_req=False):
        sp.add_argument("--fleet", default=None, help="fleet JSON (default: data/fleet_default.json)")
        sp.add_argument("--tasks", default=None, required=tasks_req, help="task-spec JSON or preset name")
        sp.add_argument("--seed", type=int, default=None)
        sp.add_argument("--tick", type=float, default=None, help="tick in seconds (default 60)")
    r = sub.add_parser("run", help="one run")
    common(r, True)
    r.add_argument("--policy", default="batch", choices=POLICIES)
    r.add_argument("--out", default=None)
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("compare", help="all policies on the same tasks (all presets if --tasks is omitted)")
    common(c)
    c.add_argument("--policies", nargs="*", default=None)
    c.add_argument("--out", default=None)
    c.set_defaults(fn=cmd_compare)
    pr = sub.add_parser("presets", help="list / regenerate preset task files")
    pr.add_argument("--write", action="store_true")
    pr.set_defaults(fn=cmd_presets)
    l = sub.add_parser("list", help="policies, presets, fleet")
    l.add_argument("--fleet", default=None)
    l.set_defaults(fn=cmd_list)
    fl = sub.add_parser("fleet", help="fleet description and feasibility check against 500 MW / 30 B USD")
    fl.add_argument("--fleet", default=None)
    fl.add_argument("--write-default", action="store_true")
    fl.set_defaults(fn=cmd_fleet)
    s = sub.add_parser("serve", help="visual app on 127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--fleet", default=None)
    s.set_defaults(fn=cmd_serve)
    rp = sub.add_parser("replay", help="static HTML replay with an embedded trace")
    common(rp, True)
    rp.add_argument("--policy", default="batch", choices=POLICIES)
    rp.add_argument("--out", required=True)
    rp.add_argument("--every", type=int, default=5, help="record a frame every N ticks")
    rp.set_defaults(fn=cmd_replay)
    st = sub.add_parser("arch-study", help="use case B: specialised vs integrated vs mixed GPU/CPU/QPU nodes against the GPU-only reference (about 10 min; --quick about 1.5 min)")
    st.add_argument("--out", default=None)
    st.add_argument("--quick", action="store_true")
    st.set_defaults(fn=cmd_arch_study)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
