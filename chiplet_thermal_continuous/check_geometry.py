#!/usr/bin/env python3
"""Small deterministic feasibility sweep around one continuous sample layout."""
import json
import random
from pathlib import Path
from geometry import validate_layout

spec = json.loads((Path(__file__).parent / 'challenge_spec.json').read_text())
base = spec['example_layouts_mm']['ring_center']
rng = random.Random(73)
for factor in (1.00, 1.08, 1.10, 1.12, 1.14):
    legal = 0
    for _ in range(30):
        proposal = {die: [round(26 + (origin[0] - 26) * factor + rng.uniform(-.25, .25), 3),
                          round(21 + (origin[1] - 21) * factor + rng.uniform(-.25, .25), 3)]
                    for die, origin in base.items()}
        try:
            validate_layout(spec, proposal)
        except ValueError:
            continue
        legal += 1
    print(f'scale {factor:.2f}: {legal}/30 legal')
