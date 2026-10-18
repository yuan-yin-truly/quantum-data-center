"""Command line: ``python -m quantum_arch {list,evaluate,compare,sweep} ...``"""

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
    print("\nModalities and control schemes:")
    for k, v in mods.items():
        if k.startswith("_"):
            continue
        print(f"  {k}: profiles {', '.join(v['profiles'])}; schemes {', '.join(v['schemes'])}")
    for name in ("fridges", "codes", "decoders", "classical", "workloads"):
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
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
