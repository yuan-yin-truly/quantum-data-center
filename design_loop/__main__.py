"""CLI: ``python -m design_loop {run,resume,report,list,calibrate,space,status}``.

LOCAL ONLY. Every output carries ``leaderboard_comparable: false``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import NOTICE
from .paths import PKG_DIR

EXAMPLE_CONFIG = PKG_DIR / "example_config.json"


def _cmd_run(a) -> int:
    from .config import load_config
    from .loop import DesignLoop
    cfg = load_config(a.config or EXAMPLE_CONFIG)
    if a.seed is not None:
        cfg["seed"] = a.seed
    if a.generations is not None:
        cfg["budget"]["max_generations"] = a.generations
    if a.max_designs is not None:
        cfg["budget"]["max_designs"] = a.max_designs
    if a.hotspot is not None:
        cfg["evaluators"]["package"]["hotspot"] = a.hotspot
    if a.max_hotspot_runs is not None:
        cfg["budget"]["max_hotspot_runs"] = a.max_hotspot_runs
    if a.package_mode:
        cfg["evaluators"]["package"]["mode"] = a.package_mode
    out = Path(a.out or PKG_DIR / "example_runs" / cfg["name"])
    if (out / "archive.jsonl").exists() and not a.force:
        print(f"{out} already holds a run; use `resume` to continue it or --force to append to it", file=sys.stderr)
        return 2
    loop = DesignLoop(cfg, out)
    loop.run()
    if not a.no_report:
        from .report import write_report
        print("report:", write_report(out))
    return 0


def _cmd_resume(a) -> int:
    from .loop import DesignLoop
    run_dir = Path(a.run_dir)
    cfg_file = run_dir / "config.json"
    if not cfg_file.is_file():
        print(f"no config.json in {run_dir}", file=sys.stderr)
        return 2
    cfg = json.loads(cfg_file.read_text())
    for k in ("leaderboard_comparable", "notice"):
        cfg.pop(k, None)
    if a.generations is not None:
        cfg["budget"]["max_generations"] = a.generations
    if a.extra_hotspot_runs:
        cfg["budget"]["max_hotspot_runs"] += a.extra_hotspot_runs
    if a.extra_designs:
        cfg["budget"]["max_designs"] += a.extra_designs
    if a.extra_wallclock:
        cfg["budget"]["max_wallclock_s"] += a.extra_wallclock
    loop = DesignLoop(cfg, run_dir)
    loop.state["stagnant"] = 0
    loop.state["stop_reason"] = None
    loop.run()
    if not a.no_report:
        from .report import write_report
        print("report:", write_report(run_dir))
    return 0


def _cmd_report(a) -> int:
    from .report import write_report
    print("report:", write_report(a.run_dir, a.out))
    return 0


def _cmd_list(a) -> int:
    root = Path(a.root or PKG_DIR / "example_runs")
    if not root.is_dir():
        print("no runs")
        return 0
    for d in sorted(p for p in root.iterdir() if (p / "archive.jsonl").is_file()):
        st = json.loads((d / "state.json").read_text()) if (d / "state.json").is_file() else {}
        n = sum(1 for _ in (d / "archive.jsonl").open() if '"t": "design"' in _)
        print(f"{d.name:40s} designs {n:4d}  generations {st.get('generation_done', -1) + 1:3d}  "
              f"hotspot runs {st.get('hotspot_runs', 0):3d}  stop: {st.get('stop_reason')}")
    return 0


def _cmd_calibrate(a) -> int:
    from .calibrate import run_calibration
    run_calibration(concurrency=a.concurrency, grid=a.grid, seed=a.seed, n_walks=a.walks)
    return 0


def _cmd_space(a) -> int:
    from . import integration as I
    sp = I.make_space()
    text = json.dumps(sp.to_dict(), indent=1)
    if a.out:
        Path(a.out).write_text(text)
        print("wrote", a.out)
    else:
        print(text)
    return 0


def _cmd_status(a) -> int:
    from .config import load_config
    from .pipeline import Pipeline
    cfg = load_config(a.config or EXAMPLE_CONFIG)
    print(json.dumps(Pipeline(cfg).describe(), indent=1, default=str))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m design_loop", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="start a new run")
    r.add_argument("--config"); r.add_argument("--out"); r.add_argument("--seed", type=int)
    r.add_argument("--generations", type=int); r.add_argument("--max-designs", type=int)
    r.add_argument("--hotspot", choices=["auto", "never", "always"])
    r.add_argument("--max-hotspot-runs", type=int)
    r.add_argument("--package-mode", choices=["auto", "stub"], help="stub = made-up temperatures, for tests only")
    r.add_argument("--no-report", action="store_true"); r.add_argument("--force", action="store_true")
    r.set_defaults(fn=_cmd_run)
    s = sub.add_parser("resume", help="continue a run from its directory")
    s.add_argument("run_dir"); s.add_argument("--generations", type=int, help="new TOTAL generation limit")
    s.add_argument("--extra-hotspot-runs", type=int); s.add_argument("--extra-designs", type=int)
    s.add_argument("--extra-wallclock", type=float); s.add_argument("--no-report", action="store_true")
    s.set_defaults(fn=_cmd_resume)
    p = sub.add_parser("report", help="(re)build the markdown report and figures")
    p.add_argument("run_dir"); p.add_argument("--out"); p.set_defaults(fn=_cmd_report)
    l = sub.add_parser("list", help="list runs"); l.add_argument("--root"); l.set_defaults(fn=_cmd_list)
    c = sub.add_parser("calibrate", help="fit the thermal surrogate to real HotSpot runs (needs Docker)")
    c.add_argument("--concurrency", type=int, default=2); c.add_argument("--grid", type=int, default=64)
    c.add_argument("--seed", type=int, default=7); c.add_argument("--walks", type=int, default=6)
    c.set_defaults(fn=_cmd_calibrate)
    sp = sub.add_parser("space", help="print the default design space as JSON"); sp.add_argument("--out"); sp.set_defaults(fn=_cmd_space)
    st = sub.add_parser("status", help="show which evaluators are real / surrogate / stub right now")
    st.add_argument("--config"); st.set_defaults(fn=_cmd_status)
    a = ap.parse_args(argv)
    print(NOTICE, file=sys.stderr)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
