Place eight chiplets on a 52 by 42 mm silicon interposer so the hottest spot on any GPU and any memory stack stays as cool as possible across five fixed workloads.

# Beat the Hotspot

A modern accelerator package is several separate pieces of silicon sitting side by side
on an interposer: compute dies and stacks of memory, wired together by short
high-bandwidth links. Where you put them decides how hot they run. Crowd the compute
dies together and their heat pools. Spread them apart and the links between them get
longer, which burns more power in the wires and the interface circuits, and pushes dies
toward the edge of the package where the cooler makes poorer contact. This hill asks you
to find the placement that wins that trade.

You place four GPU dies (G0 to G3, each 11.5 by 10.5 mm) and four memory stacks (H0 to
H3, each 10.5 by 10.2 mm). Together they cover 911 mm2 of a 2184 mm2 interposer, so
there is room to move but not room to be careless. Eight links are mandatory and each
one has a reach limit, so no placement can simply scatter the dies into the corners.

Everything else is fixed and owned by the evaluator: the five workloads and their
per-die power maps, the link topology and bandwidths, the port allocation rule, the wire
router, the thermal stack, the cooler, and the HotSpot build that computes the
temperatures. You choose coordinates, and optionally the wire routes.

## What you submit

A submission is a directory holding one UTF-8 JSON file:

```
submission.json
```

It contains `placements_mm`, and nothing else is required:

```json
{
  "placements_mm": {
    "G0": [7.563, 3.259], "G1": [33.272, 2.856],
    "G2": [33.072, 27.366], "G3": [7.994, 27.611],
    "H0": [20.934, 3.584], "H1": [34.12, 15.888],
    "H2": [20.77, 27.311], "H3": [8.748, 15.163]
  }
}
```

Each value is the lower-left corner of that die in millimetres, measured from the
lower-left corner of the interposer. Coordinates are continuous. All eight dies must
appear exactly once. Orientations and die dimensions are fixed, so you cannot rotate or
resize anything.

You may add one optional key, `wire_routes_grid`, to route a link yourself instead of
letting the evaluator's router do it:

```json
{"wire_routes_grid": {"P0": [[12, 7], [13, 7], [13, 8]]}}
```

Each entry is a list of adjacent `[column, row]` cells on a 0.5 mm grid, where cell
`(i, j)` is centred at `((i+0.5)*0.5, (j+0.5)*0.5)` mm. The path must start and end on
the two access cells the port allocator assigned to that link, and every step must move
to a neighbouring cell. Omit the key and the evaluator routes all eight links by
shortest path, which is usually what you want. List only some links to hand-route those
and leave the rest automatic.

Any other file in the submission directory is ignored. A power map, a trace, a claimed
temperature or a claimed score has no effect: the evaluator generates its own workload
traces from its own frozen data and runs its own simulation.

## Metric

| metric | direction | meaning |
|---|---|---|
| `score` | min | worst-case temperature rise over ambient, as a fraction of the seeded random baseline's rise at the same mesh |
| `worst_gpu_c` | min | hottest GPU cell in Celsius, across every workload and every GPU |
| `worst_hbm_c` | min | hottest memory-stack cell in Celsius, across every workload and every stack |

`score` ranks first and the two raw peaks break ties. With ambient at 25 C,

```text
score = max((worst_gpu_c - 25) / (gpu_reference - 25),
            (worst_hbm_c - 25) / (hbm_reference - 25))
```

It is the maximum, not the average, so a layout improves only by cooling whichever of
the two is currently worse. Trading a cooler GPU for a hotter memory stack buys nothing.

Below 1.0 means the layout beats the baseline on both objectives at that mesh. The
baseline is a seeded random legal layout, and its peaks are published here:

| mesh | GPU reference | memory reference |
|---|---|---|
| 64 by 64 | 104.59 C | 97.68 C |
| 128 by 128 | 104.74 C | 97.70 C |

An illegal layout reports `passed: false`, scores 1000000 on all three metrics and does
not rank. Validity is checked before any simulation runs, so a broken submission comes
back in seconds with the reason.

## Constraints a layout must satisfy

Geometry. At least 1 mm between any two dies, at least 1 mm from the interposer
boundary, and no overlap.

Links. Four primary links carry 600 GB/s and may route at most 5 mm: P0 joins G0 to H0,
P1 joins G1 to H1, P2 joins G2 to H2, P3 joins G3 to H3. Four secondary links carry
300 GB/s and may route at most 6 mm: S0 joins G0 to H3, S1 joins G1 to H0, S2 joins G2
to H1, S3 joins G3 to H2. All eight are compulsory, so every die terminates one primary
and one secondary link.

Ports. A link needs reserved edge length at both ends, at 150 GB/s per mm: 4 mm for a
primary link, 2 mm for a secondary. Each die has 6 mm of port length to find, and only
the middle 60% of each side is usable. Two ports on the same side need 0.4 mm between
them. The evaluator's allocator picks the side facing the partner die from the
centre-to-centre displacement, then places ports in sorted link order, so port positions
follow from your coordinates rather than being yours to set.

Routing. Paths run on a 0.5 mm grid, keep 0.2 mm clear of every die, avoid cells
occupied by other routes, and respect the per-link reach above. Across all eight links
the bandwidth-weighted total must satisfy
`sum(bandwidth_GB_s * routed_length_mm) <= 13500`. That budget is the usual reason a
spread-out layout fails, because long routes on the 600 GB/s links consume it fast.

## Where the heat comes from

Three sources add up, and only the first is independent of your layout.

Base die activity. Each die has a 16 by 16 power map per workload that sums to its base
watts. Row zero is the bottom of the die. The maps are fixed and travel with the die.

Interface circuits at each end of a link. The energy is 0.20 pJ per bit of traffic,
split evenly between the two endpoints. At each endpoint that power spreads uniformly
over a rectangle as long as the reserved port length and 2 mm deep, reaching 1 mm into
the die and 1 mm out past its edge. Half the endpoint's watts land in the die plane and
half in the interposer.

The wires. 0.08 pJ per bit per mm of routed length, spread uniformly along the route
into the interposer, so a long route costs power everywhere it goes. A fully used
600 GB/s link over 4 mm produces 0.96 W of interface heat plus 1.54 W along the wire.

Link traffic varies by workload. `tensor_training` and `skewed_compute` lean on the
compute dies, with average primary-link utilization near 39% and 37%.
`attention_decode` and `memory_stream` lean on memory and drive the links far harder, at
84% and 94%. `mixed_serving` sits between them at 61% with asymmetric per-die load. Base
totals range between 313 W and 399 W. A layout that suits only the compute-heavy cases
gives its gains back on the memory-heavy ones, because the metric takes the worst case
over all five.

The workloads are in `workloads.json`. `agent_workloads.json` documents every field and
is the file to read if you want to drive a different simulator with the same power maps
while searching.

## Cooling

The stack is a 500 micron silicon interposer carrying the wire and outside-port heat, a
150 micron die layer plus passive gap plane carrying base and inside-port heat, and a
20 micron thermal interface layer under a fixed spreader and sink.

The cooler contact is uneven on purpose and does not move when you move the dies. A
central 44 by 34 mm window, spanning x from 4 to 48 mm and y from 4 to 38 mm, has good
contact at 0.25 m K/W resistivity. Outside that window the resistivity is 2.0 m K/W,
eight times worse. The unit is metre-kelvin per watt, not milli. Pushing a hot die past
that boundary to gain separation is usually a bad trade, and finding where the trade
flips is part of the problem.

## Validation and final scoring

Routine evaluation simulates on a 64 by 64 mesh and scores against the 64 reference. The
final pass, `hills eval <dir> -H beat-the-hotspot --final`, re-runs the same layout on a
128 by 128 mesh and scores against the 128 reference. The physical sources, geometry,
thermal stack and simulator are identical, and only the numerical mesh changes. The
finer mesh catches layouts that look good because of coarse-grid averaging, so iterate
on the 64 mesh and treat the 128 result as the claim.

The mesh size and the simulator's SHA-256 are both primary configuration, so reports
from different meshes never rank against each other. Do not compare a 64 score to a 128
score, and do not divide a 128 temperature by a 64 reference.

## What is held out

No workloads are hidden. All five, their power maps and their link utilizations ship in
this hill, and both baseline references appear in the table above. This hill has no
secret test set, and the guard against overfitting is the finer mesh in `--final`
together with the fact that the five workloads pull in different directions while the
metric takes the worst of them.

`private/` holds the two reference files the judge divides by, so nothing in a submission
directory can shadow the baseline a score is measured against. Those values are not a
secret; they are in this README.

## Parameters

None. The mesh follows from whether the run is final, and every other quantity is fixed
in `challenge_spec.json`.

## Running it locally

Scoring happens inside a pinned container image, `ghcr.io/czaja107/beat-the-hotspot-eval`,
built from the `Dockerfile` in this hill. The image exists because the HotSpot build
shipped here needs glibc 2.34 or newer and will not load on an older Linux. You do not
have to think about it when submitting; it only matters if you want to reproduce a score
yourself, in which case use that image rather than your own Python.

Checking a layout's legality needs none of that. It is pure Python and runs anywhere:

```bash
python3 verify_submission.py submission.json --output feasibility.json
```

That reports every constraint above, plus the port centres, the chosen routes, the edge
capacity used per die and the remaining route budget. Run it before spending time on
thermal simulation. For a full score on a Linux machine:

```bash
python3 verify_high_accuracy.py submission.json --hotspot vendor/HotSpot/hotspot --grid 64
python3 verify_high_accuracy.py submission.json --hotspot vendor/HotSpot/hotspot --grid 128
```

A 256 mesh also runs and is useful as a numerical check, but it has no calibrated
reference and produces no official score.

`examples/baseline/submission.json` is a legal layout to start from. It is the seeded
random baseline, so it scores 1.0 by construction.

## Scope, and honesty about the model

These numbers are relative benchmark values, not calibrated junction temperature
predictions. The cooling model, the package gaps, the board heat path, the interface
energy and the wire energy are all simplified, and the coefficients are benchmark
assumptions rather than measured silicon. The router ignores wire width, layer
congestion, IR drop, latency, crosstalk, vias and signal integrity. The per-die wattages
are plausible assumptions, not measurements of any real part.

What the hill does measure honestly is the placement trade: heat pooling against
interconnect power and cooler contact, under hard geometric and bandwidth constraints,
judged the same way for everyone.

HotSpot itself is external: https://github.com/uvahotspot/HotSpot . Its source at the
pinned revision and its license ship under `vendor/HotSpot`.

## What the evaluator will not do

- It will not run any code from your submission. It reads `submission.json` as data.
- It will not read a temperature, power map or score your search produced. It computes
  the metric itself, from its own traces, with its own simulator.
- It will not accept a layout that breaks a constraint. Illegal is rejected, not
  penalized.
