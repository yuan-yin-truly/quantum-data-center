"""Runs INSIDE the pinned HotSpot container (python + numpy only). Not imported by the host code.

Job file (JSON): {"hill": "/hill", "reference_dir": "/work", "grid": 64, "out": "/work/out.jsonl",
                  "runs": [{"key": ..., "placements_mm": {...}, "modifiers": {...} | null}, ...]}
Each run appends one JSON line {"key", "ok", "result"|"error"} to ``out`` as soon as it finishes.
Uses the LOCAL variant's ``thermal_job.run_one`` when present, else the original judge (identity power only).
"""

import json
import sys
import tempfile
import traceback
from pathlib import Path

job = json.loads(Path(sys.argv[1]).read_text())
hill = Path(job["hill"])
sys.path.insert(0, str(hill))
grid = int(job["grid"])
variant = (hill / "thermal_job.py").is_file()
if variant:
    import thermal_job
else:
    import stat
    from verify_high_accuracy import judge
    hotspot = hill / "vendor/HotSpot/hotspot"
    hotspot.chmod(hotspot.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

out = Path(job["out"])
for run in job["runs"]:
    rec = {"key": run["key"]}
    try:
        with tempfile.TemporaryDirectory(prefix="dl_") as tmp:
            sub = Path(tmp) / "submission.json"
            sub.write_text(json.dumps({"placements_mm": run["placements_mm"]}))
            if variant:
                res = thermal_job.run_one(sub, grid, run.get("modifiers"))
            else:
                if run.get("modifiers"):
                    raise RuntimeError("modified power maps need the LOCAL quantum variant (hybrid_power.py)")
                res = judge(sub, hotspot, grid=grid, reference_file=Path(job["reference_dir"]) / f"reference_{grid}.json")
        rec.update(ok=True, result=res)
    except Exception as exc:                                     # report, keep going
        rec.update(ok=False, error=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc()[-1500:])
    with out.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
