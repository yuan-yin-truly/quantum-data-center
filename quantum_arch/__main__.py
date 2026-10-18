"""Command line: ``python -m quantum_arch {list,evaluate,compare,sweep,datacenter,calibrate,annealer,baselines} ...``"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import catalog, report, sweep
from .architecture import Architecture, evaluate

EXAMPLES = Path(__file__).resolve().parent / "examples"


def _load(spec: str) -> Architecture:
    path = Path(spec)
    if not path.exists() and (EXAMPLES / spec).exists():
        path = EXAMPLES / spec
    if not path.exists() and (EXAMPLES / f"{spec}.json").exists():
        path = EXAMPLES / f"{spec}.json"
    return Architecture.from_file(path)


def cmd_list(_args) -> int:
    print("Examples (quantum_arch/examples):")
    for p in sorted(EXAMPLES.glob("*.json")):
        raw = json.loads(p.read_text())
        print(f"  {p.stem:38s} {raw.get('modality', ''):15s} {raw.get('n_qubits', ''):>9} qubits  {raw.get('description', '')}")
    mods = catalog.load("modalities")
    print("\nModalities and control schemes (default profile for new architectures: mid2030s):")
    for k, v in mods.items():
        if k.startswith("_"):
            continue
        print(f"  {k}: profiles {', '.join(v['profiles'])}; schemes {', '.join(v['schemes'])}")
    print("\nAnnealers (separate class, own metrics, never in rQOPS comparisons):")
    for k in catalog.keys("annealers"):
        print(f"  {k}: profiles {', '.join(catalog.entry('annealers', k)['profiles'])}")
    print("\nNot modelled (see data/excluded_modalities.json): " + ", ".join(catalog.keys("excluded_modalities")))
    print("\nData-centre examples (quantum_arch/examples/datacenter):")
    for p in sorted((EXAMPLES / "datacenter").glob("*.json")):
        print(f"  {p.stem:38s} {json.loads(p.read_text()).get('description', '')[:90]}")
    for name in ("fridges", "codes", "decoders", "classical", "workloads", "baselines"):
        print(f"\n{name}: {', '.join(catalog.keys(name))}")
    return 0


def cmd_evaluate(args) -> int:
    res = evaluate(_load(args.architecture))
    print(report.summary_markdown(res))
    if args.out:
        out = report.write_report(res, args.out)
        print(f"Wrote result.json, summary.md and figures to {out}")
    return 0


def cmd_compare(args) -> int:
    results = [evaluate(_load(a)) for a in args.architectures]
    print(report.comparison_markdown(results))
    if args.out:
        out = report.write_comparison(results, args.out)
        print(f"Wrote comparison tables, figures and per-architecture reports to {out}")
    return 0


def cmd_sweep(args) -> int:
    arch = _load(args.architecture)
    counts = sweep.log_counts(args.min, args.max, args.per_decade)
    rows = sweep.sweep_qubits(arch, counts)
    limit = sweep.max_qubits_single_fridge(arch)
    print(f"{arch.name}: largest processor one fridge can serve: {limit['max_qubits']:,} qubits (first limit: {limit['limit']})\n")
    print(f"{'qubits':>10} {'power':>12} {'fridges':>8} {'logical':>9} {'rQOPS':>10}  worst stage")
    for r in rows:
        worst = max(r["utilisation"].items(), key=lambda kv: kv[1], default=("-", 0))
        print(f"{r['n']:>10,} {report._eng(r['power_w']):>12} {r['fridges']:>8} {r['logical_qubits']:>9,} "
              f"{r['rqops']:>10.3g}  {worst[0]} {worst[1]:.0%}")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        names = list(rows[0]["utilisation"]) if rows[0]["utilisation"] else []
        if names:
            report.fig_sweep(rows, names, f"{arch.name}: scaling", out / "sweep.png")
        (out / "sweep.json").write_text(json.dumps({"rows": rows, "single_fridge_limit": limit}, indent=2, default=float))
        print(f"\nWrote sweep.json and sweep.png to {out}")
    return 0


def cmd_datacenter(args) -> int:
    from . import datacenter as dc
    res = dc.run_datacenter(args.config)
    sweep = dc.movable_sweep(args.config) if not args.no_sweep else None
    print(dc.datacenter_markdown(res, sweep))
    if args.out:
        out = dc.write_datacenter_report(res, sweep, args.out)
        print(f"Wrote result.json, summary.md and movable_sweep.png to {out}")
    return 0


def cmd_calibrate(args) -> int:
    from . import calibration
    rows = calibration.run_calibration()
    md = calibration.calibration_markdown(rows)
    print(md)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "calibration.md").write_text(md, encoding="utf-8")
        (out / "calibration.json").write_text(json.dumps(rows, indent=2, default=float), encoding="utf-8")
        print(f"Wrote calibration.md and calibration.json to {out}")
    return 0


def cmd_annealer(args) -> int:
    from . import annealer
    res = annealer.evaluate_annealer({"name": args.name, "annealer": args.annealer, "profile": args.profile})
    print(json.dumps(res.to_dict(), indent=2, default=float))
    if args.p_success:
        print(json.dumps(annealer.solve_cost(res, args.p_success, args.confidence), indent=2, default=float))
    return 0


def cmd_baselines(args) -> int:
    from . import baselines
    rows = baselines.compare_devices(args.devices, args.profile, pue=args.pue)
    print(f"LLM inference, 70B-class, matched latency SLO; profile {args.profile or 'per-device'} (rated power, not measured)\n")
    print(f"{'device':50s} {'tokens/s':>10} {'J/token module':>15} {'system':>9} {'facility':>9}")
    for r in rows:
        print(f"{r['device']:50s} {r['tokens_per_s']:>10,.0f} {r['j_per_token_module']:>15.4f} {r['j_per_token_system']:>9.4f} "
              f"{r['j_per_token_facility']:>9.4f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="quantum_arch", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show examples and catalogs").set_defaults(fn=cmd_list)
    p = sub.add_parser("evaluate", help="evaluate one architecture (file path or example name)")
    p.add_argument("architecture")
    p.add_argument("--out", help="directory for result.json, summary.md and figures")
    p.set_defaults(fn=cmd_evaluate)
    p = sub.add_parser("compare", help="evaluate several architectures side by side")
    p.add_argument("architectures", nargs="+")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("sweep", help="sweep the qubit count of one architecture")
    p.add_argument("architecture")
    p.add_argument("--min", type=float, default=1e2)
    p.add_argument("--max", type=float, default=1e6)
    p.add_argument("--per-decade", type=int, default=3)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_sweep)
    p = sub.add_parser("datacenter", help="hybrid CPU+GPU+QPU data centre: gpu_only vs augment vs replace (name in examples/datacenter or path)")
    p.add_argument("config")
    p.add_argument("--out")
    p.add_argument("--no-sweep", action="store_true", help="skip the movable-work sweep and break-even")
    p.set_defaults(fn=cmd_datacenter)
    p = sub.add_parser("calibrate", help="compare the today profile with published power figures")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_calibrate)
    p = sub.add_parser("annealer", help="evaluate a quantum annealer (own metrics, not rQOPS)")
    p.add_argument("--annealer", default="advantage2_class")
    p.add_argument("--profile", default="mid2030s")
    p.add_argument("--name", default="annealer")
    p.add_argument("--p-success", type=float, help="per-read probability of reaching the target quality, for time/energy-to-target")
    p.add_argument("--confidence", type=float, default=0.99)
    p.set_defaults(fn=cmd_annealer)
    p = sub.add_parser("baselines", help="GPU LLM-inference joules per token at module / system / facility boundary")
    p.add_argument("devices", nargs="*", default=["gpu_h200", "gpu_b200", "gpu_mi355x", "gpu_2035_low", "gpu_2035", "gpu_2035_high"])
    p.add_argument("--profile", default=None)
    p.add_argument("--pue", type=float, default=1.0)
    p.set_defaults(fn=cmd_baselines)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
