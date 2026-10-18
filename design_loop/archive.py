"""Crash-safe run directory: append-only JSONL archive of designs and evaluations, state file, snapshots.

Every record is written and fsynced as one line, so a crash loses at most the line being written (a truncated last
line is ignored on load). Evaluations are cached by ``(evaluator, cache key)``: an identical sub-problem is never
evaluated twice, within a run or after a resume.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import LEADERBOARD_COMPARABLE, NOTICE
from .evaluators.base import EvalResult
from .genes import Design


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class Archive:
    def __init__(self, run_dir: str | Path):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "archive.jsonl"
        self._lock = threading.Lock()
        self.designs: dict[str, Design] = {}
        self.meta: dict[str, dict[str, Any]] = {}
        self.evals: dict[str, dict[str, EvalResult]] = {}
        self.cache: dict[tuple[str, str], EvalResult] = {}
        self.n_lines = 0
        self._fh = None
        if self.path.is_file():
            self._load()

    # ---- persistence ---------------------------------------------------------------------------------
    def _load(self) -> None:
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:                      # truncated last line after a crash
                    continue
                self._apply(rec)
                self.n_lines += 1

    def _apply(self, rec: dict) -> None:
        if rec["t"] == "design":
            d = Design.from_dict(rec["design"])
            self.designs[d.id] = d
            self.meta.setdefault(d.id, {k: rec.get(k) for k in ("parents", "operator", "changed", "generation")})
        elif rec["t"] == "eval":
            r = EvalResult.from_dict(rec["result"])
            self.evals.setdefault(rec["id"], {})[r.evaluator] = r
            if r.status == "ok" and r.key:
                self.cache.setdefault((r.evaluator, r.key), r)

    def _write(self, rec: dict) -> None:
        with self._lock:
            if self._fh is None:
                self._fh = self.path.open("a", encoding="utf-8")
            self._fh.write(json.dumps(rec, default=str) + "\n")
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self.n_lines += 1

    def close(self) -> None:
        with self._lock:
            if self._fh:
                self._fh.close()
                self._fh = None

    # ---- designs and evaluations ---------------------------------------------------------------------
    def __contains__(self, design_id: str) -> bool:
        return design_id in self.designs

    def add_design(self, d: Design, parents: list[str] | None = None, operator: str = "seed",
                   changed: list[str] | None = None, generation: int = 0) -> bool:
        """Register a design; returns False (and writes nothing) if it is already known."""
        if d.id in self.designs:
            return False
        rec = {"t": "design", "design": d.to_dict(), "parents": parents or [], "operator": operator,
               "changed": changed or [], "generation": generation, "time": time.time()}
        self._apply(rec)
        self._write(rec)
        return True

    def add_eval(self, design_id: str, r: EvalResult) -> None:
        rec = {"t": "eval", "id": design_id, "result": r.to_dict(), "time": time.time()}
        self._apply(rec)
        self._write(rec)

    def cached(self, evaluator: str, key: str) -> EvalResult | None:
        return self.cache.get((evaluator, key))

    def results(self, design_id: str) -> dict[str, EvalResult]:
        return self.evals.get(design_id, {})

    # ---- state ----------------------------------------------------------------------------------------
    def save_state(self, state: dict) -> None:
        _atomic_write(self.dir / "state.json", json.dumps(state, indent=1, default=str))

    def load_state(self) -> dict | None:
        p = self.dir / "state.json"
        return json.loads(p.read_text()) if p.is_file() else None

    def append_generation(self, summary: dict) -> None:
        with (self.dir / "generations.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(summary, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def generations(self) -> list[dict]:
        p = self.dir / "generations.jsonl"
        if not p.is_file():
            return []
        out = {}
        for line in p.read_text().splitlines():
            try:
                g = json.loads(line)
                out[g["generation"]] = g                  # a re-run generation after a crash overrides
            except (json.JSONDecodeError, KeyError):
                continue
        return [out[k] for k in sorted(out)]

    def snapshot_config(self, config: dict, space: dict) -> None:
        stamp = {"leaderboard_comparable": LEADERBOARD_COMPARABLE, "notice": NOTICE}
        _atomic_write(self.dir / "config.json", json.dumps({**config, **stamp}, indent=1, default=str))
        _atomic_write(self.dir / "space.json", json.dumps(space, indent=1, default=str))
