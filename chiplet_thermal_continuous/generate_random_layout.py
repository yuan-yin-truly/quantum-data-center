#!/usr/bin/env python3
"""Generate one seeded random legal layout by rejection sampling."""

import argparse
import json
import random
from pathlib import Path

from geometry import validate_layout

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261017)
    parser.add_argument("--jitter-mm", type=float, default=0.65)
    parser.add_argument("--output", type=Path, default=HERE / "random_layout.json")
    args = parser.parse_args()
    spec = json.loads((HERE / "challenge_spec.json").read_text())
    rng = random.Random(args.seed)
    base = spec["example_layouts_mm"]["ring_center"]
    for attempt in range(1, 10001):
        layout = {die: [round(x+rng.uniform(-args.jitter_mm, args.jitter_mm), 3),
                        round(y+rng.uniform(-args.jitter_mm, args.jitter_mm), 3)]
                  for die, (x, y) in base.items()}
        try:
            routing = validate_layout(spec, layout)
        except ValueError:
            continue
        args.output.write_text(json.dumps({"random_layout": {
            "random_seed": args.seed,
            "sampling": f"uniform ±{args.jitter_mm} mm per coordinate around ring_center; reject illegal layouts",
            "attempt": attempt,
            "placements_mm": layout,
            "weighted_route_gb_s_mm": routing["weighted_route_gb_s_mm"]}}, indent=2)+"\n")
        print(f"Wrote {args.output}: attempt {attempt}, route budget {routing['weighted_route_gb_s_mm']} GB/s·mm")
        return
    raise RuntimeError("No legal layout in 10,000 trials; change seed or jitter")


if __name__ == "__main__":
    main()
