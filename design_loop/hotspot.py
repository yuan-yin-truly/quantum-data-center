"""Real HotSpot runs through the judge's pinned container image (Docker), capped concurrency.

The runner never fakes a temperature: if Docker, the image or the hill is missing, :meth:`available` says why and
the package evaluator falls back to the (clearly labelled) surrogate. A run is the judge's own pipeline
(``thermal_job.run_one`` of the LOCAL variant: ``judge`` for unmodified power, ``judge_modified``, a line-for-line
mirror, for modified power maps) on the pinned HotSpot build; results are NOT leaderboard comparable.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .paths import PKG_DIR, find_hill

CONTAINER_JOB = PKG_DIR / "evaluators" / "container_job.py"
DATA = PKG_DIR / "data"


def docker_bin() -> str | None:
    return shutil.which("docker") or ("/usr/local/bin/docker" if Path("/usr/local/bin/docker").exists() else None)


class HotspotRunner:
    def __init__(self, grid: int = 64, concurrency: int = 2, hill_dir: Path | None = None, timeout_s: int = 3600,
                 try_start_docker: bool = False, work_root: Path | None = None):
        self.grid = grid
        self.concurrency = max(1, int(concurrency))
        self.hill = Path(hill_dir) if hill_dir else find_hill()
        self.timeout_s = timeout_s
        self.try_start_docker = try_start_docker
        self.work_root = Path(work_root) if work_root else None
        self._checked: tuple[bool, str] | None = None
        self._lock = threading.Lock()
        self.runs_done = 0

    # ------------------------------------------------------------------------------------------------
    def image(self) -> str:
        text = (self.hill / "hill.yaml").read_text()
        m = re.search(r"^\s*image:\s*(\S+)", text, re.M)
        return m.group(1) if m else ""

    def _docker_up(self, docker: str) -> bool:
        try:
            return subprocess.run([docker, "info"], capture_output=True, timeout=30).returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def available(self, refresh: bool = False) -> tuple[bool, str]:
        if self._checked is not None and not refresh:
            return self._checked
        self._checked = self._probe()
        return self._checked

    def _probe(self) -> tuple[bool, str]:
        if self.hill is None or not (self.hill / "vendor" / "HotSpot" / "hotspot").is_file():
            return False, "no hill directory with the pinned HotSpot binary"
        if not (self.hill / "hill.yaml").is_file():
            return False, "hill.yaml missing (cannot read the pinned image)"
        docker = docker_bin()
        if not docker:
            return False, "docker is not installed"
        if not self._docker_up(docker):
            if self.try_start_docker and shutil.which("open"):
                subprocess.run(["open", "-a", "Docker"], capture_output=True)
                for _ in range(40):                         # ~2 minutes
                    time.sleep(3)
                    if self._docker_up(docker):
                        break
            if not self._docker_up(docker):
                return False, "the Docker daemon is not running (start Docker Desktop: `open -a Docker`)"
        image = self.image()
        if not image:
            return False, "no pinned image in hill.yaml"
        have = subprocess.run([docker, "image", "inspect", image], capture_output=True).returncode == 0
        if not have:
            return False, f"pinned image not present locally ({image}); `docker pull` it first"
        return True, f"docker + pinned image ({image.split('@')[0]}), hill {self.hill.name}"

    # ------------------------------------------------------------------------------------------------
    def run_many(self, jobs: list[dict[str, Any]]) -> dict[str, dict]:
        """``jobs``: ``[{"key", "placements_mm", "modifiers"}]`` -> ``{key: {"ok", "result"|"error", "seconds"}}``."""
        ok, why = self.available()
        if not ok:
            return {j["key"]: {"ok": False, "error": f"unavailable: {why}", "seconds": 0.0} for j in jobs}
        results: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            for key, out in zip([j["key"] for j in jobs], pool.map(self._one, jobs)):
                results[key] = out
        return results

    def _one(self, job: dict) -> dict:
        docker = docker_bin()
        root = self.work_root or Path(tempfile.gettempdir())
        root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="hs_", dir=root))
        t0 = time.perf_counter()
        try:
            shutil.copy(CONTAINER_JOB, work / "container_job.py")
            for g in (64, 128):
                shutil.copy(DATA / f"reference_{g}.json", work / f"reference_{g}.json")
            spec = {"hill": "/hill", "reference_dir": "/work", "grid": self.grid, "out": "/work/out.jsonl",
                    "runs": [{"key": job["key"], "placements_mm": job["placements_mm"], "modifiers": job.get("modifiers")}]}
            (work / "job.json").write_text(json.dumps(spec))
            cmd = [docker, "run", "--rm", "--platform", "linux/amd64", "-u", f"{os.getuid()}:{os.getgid()}",
                   "-e", "PYTHONDONTWRITEBYTECODE=1", "-v", f"{self.hill}:/hill", "-v", f"{work}:/work", "-w", "/hill",
                   self.image(), "python", "/work/container_job.py", "/work/job.json"]
            err = ""
            for attempt in range(2):
                (work / "out.jsonl").unlink(missing_ok=True)
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s)
                out = work / "out.jsonl"
                if proc.returncode == 0 and out.is_file() and out.read_text().strip():
                    rec = json.loads(out.read_text().strip().splitlines()[-1])
                    if rec.get("ok"):
                        with self._lock:
                            self.runs_done += 1
                        return {"ok": True, "result": rec["result"], "seconds": time.perf_counter() - t0,
                                "image": self.image(), "attempts": attempt + 1}
                    err = rec.get("error", "?")
                else:
                    err = (proc.stderr or proc.stdout)[-800:]
            return {"ok": False, "error": err, "seconds": time.perf_counter() - t0}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout", "seconds": time.perf_counter() - t0}
        finally:
            shutil.rmtree(work, ignore_errors=True)
