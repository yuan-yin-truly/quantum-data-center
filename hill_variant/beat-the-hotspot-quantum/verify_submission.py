#!/usr/bin/env python3
"""Independent, deterministic feasibility gate for one chiplet-layout submission.

Usage: python3 verify_submission.py submission.json [--output report.json]
The submission may only contain placements_mm and optional wire_routes_grid.
This validator uses the organizer's immutable challenge_spec.json, never a
workload/spec copied into the participant's submission directory.
"""

import argparse
import json
import math
from pathlib import Path

from geometry import die_box, validate_layout

HERE = Path(__file__).resolve().parent
MAX_SUBMISSION_BYTES = 64_000


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def parse_submission(path, spec):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_SUBMISSION_BYTES:
        raise ValueError("submission.json is missing or exceeds 64,000 bytes")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    except (json.JSONDecodeError, UnicodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) not in ({"placements_mm"}, {"placements_mm", "wire_routes_grid"}):
        raise ValueError("top-level keys must be placements_mm and optional wire_routes_grid")
    placements = raw["placements_mm"]
    if not isinstance(placements, dict) or set(placements) != set(spec["dies"]):
        raise ValueError("placements_mm must contain exactly G0–G3 and H0–H3")
    normalized = {}
    for die, xy in placements.items():
        if not isinstance(xy, list) or len(xy) != 2:
            raise ValueError(f"{die} must have a two-number [x,y] lower-left origin")
        normalized[die] = [_number(v, f"{die}[{i}]") for i, v in enumerate(xy)]
    paths = raw.get("wire_routes_grid", {})
    if not isinstance(paths, dict):
        raise ValueError("wire_routes_grid must be an object keyed by link ID")
    known = {link["id"] for link in spec["links"]}
    if set(paths) - known:
        raise ValueError(f"unknown wire link IDs: {sorted(set(paths)-known)}")
    max_steps = 1 + math.ceil(max(link["max_route_mm"] for link in spec["links"]) /
                              spec["port_rule"]["route_grid_pitch_mm"])
    for link, cells in paths.items():
        if not isinstance(cells, list) or not 1 <= len(cells) <= max_steps:
            raise ValueError(f"{link} path needs 1–{max_steps} track cells")
        for k, cell in enumerate(cells):
            if not (isinstance(cell, list) and len(cell) == 2 and
                    all(type(v) is int for v in cell)):
                raise ValueError(f"{link}[{k}] must be two integer track indices")
    return normalized, paths


def verify(path, spec_path=HERE / "challenge_spec.json"):
    spec = json.loads(Path(spec_path).read_text())
    try:
        layout, paths = parse_submission(path, spec)
        routing = validate_layout(spec, layout, wire_routes_grid=paths)
    except (ValueError, TypeError, OverflowError) as exc:
        return {"passed": False, "reason": str(exc)}
    W, H = spec["interposer_mm"]
    boxes = {die: die_box(spec, layout, die) for die in layout}
    edge = min(min(x0, y0, W-x1, H-y1) for x0, y0, x1, y1 in boxes.values())
    separation = min(max(b[0]-a[2], a[0]-b[2], 0, b[1]-a[3], a[1]-b[3])
                     for i, a in enumerate(boxes.values()) for b in list(boxes.values())[i+1:])
    return {"passed": True, "die_edge_margin_mm": round(edge, 6),
            "minimum_die_separation_mm": round(separation, 6),
            "weighted_route_gb_s_mm": routing["weighted_route_gb_s_mm"],
            "route_limit_gb_s_mm": routing["route_limit_gb_s_mm"],
            "die_edge_capacity": routing["die_edge_capacity"],
            "links": {link: {"route_length_mm": r["route_length_mm"],
                             "max_route_mm": r["limit_mm"],
                             "required_port_each_end_mm": r["required_port_mm"],
                             "from_port_mm": r["from_port"], "to_port_mm": r["to_port"],
                             "route_grid": r["path_grid"]}
                      for link, r in routing["routes"].items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.submission)
    formatted = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(formatted)
    print(formatted, end="")
    raise SystemExit(0 if report["passed"] else 2)


if __name__ == "__main__":
    main()
