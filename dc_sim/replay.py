"""Self-contained static HTML replay: the whole run is recorded with the same engine and embedded in one file (no server needed)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import api, report
from .config import PKG, clean_json
from .engine import Engine
from .fleet import Fleet
from .scheduler import POLICIES, POLICY_LABELS


def record(fleet: Any, tasks: Any, policy: str, seed: int | None = None, every: int = 10) -> dict:
    eng = Engine(fleet, tasks, policy, seed=seed)
    frames = []
    pending_dec: list[dict] = []
    k = 0
    while not eng.done:
        r = eng.step()
        pending_dec += r["decisions"]
        k += 1
        if k % every == 0 or eng.done:
            st = eng.state(nodes=True, recent=0)
            st["recent"] = pending_dec
            pending_dec = []
            frames.append(st)
    return {"format": "dc_sim.trace/1", "policy": policy, "taskset": eng.ts["name"], "seed": eng.seed, "layout": eng.layout(), "frames": frames,
            "every": every, "tick_s": eng.tick, "final": eng.metrics(), "n_decisions": len(eng.decisions)}


def build_html(fleet: Any, tasks: Any, policy: str, seed: int | None = None, every: int = 10) -> str:
    fleet = Fleet.load(fleet)
    trace = record(fleet, tasks, policy, seed, every)
    engines = api.compare_policies(fleet, tasks, POLICIES, seed)
    rows = report.rank(report.compare_rows(engines))
    trace["compare_rows"] = rows
    trace["labels"] = {k: report.POLICY_NAME.get(k, k) for k in engines}
    web = PKG / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    css = (web / "style.css").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    data = json.dumps(clean_json(trace), separators=(",", ":")).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="/style.css">', f"<style>{css}</style>")
    html = html.replace('<script src="/app.js"></script>', f"<script>window.DC_REPLAY={data};</script><script>{js}</script>")
    return html


def export_html(fleet: Any, tasks: Any, policy: str, out: str | Path, seed: int | None = None, every: int = 10) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(fleet, tasks, policy, seed, every), encoding="utf-8")
    return out
