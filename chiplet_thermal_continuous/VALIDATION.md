# Validation and example results: rectangular port heat

## Source placement

The challenge model defines a PHY rectangle at every link endpoint with area `2 × d × L_port` mm², where `d=1 mm` each side of the chiplet edge and `L_port=4 mm` for a 600 GB/s link or `2 mm` for a 300 GB/s link. Endpoint power density is its PHY watts divided by this area. The area inside its die is `d × L_port` and the equal-area strip outside is deposited into silicon interposer tiles. The generator computes **geometric intersections**, not nearest-pixel or Gaussian weighting, so splitting a rectangle across cell borders conserves power. Wire power follows rectilinear centerline length, subdivided precisely at tile borders. Port heat and wire heat add where their exterior areas intersect. Routes and source rectangles can be inspected in `random_example/results.json` and `random_example/hotspot_inputs/random_layout/power_budget.json`.

At fully active 600 GB/s on a 4 mm route, the model yields 0.96 W PHY total: 0.48 W per endpoint, with 0.24 W inside and 0.24 W outside each die. It yields 1.536 W wire heat along 4 mm. The PHY rectangle area is 8 mm² per endpoint, so its uniform source density is 0.06 W/mm², independently of die-pixel size. A 300 GB/s port is 2 mm long and its rectangle is 4 mm². All numbers are synthetic.

## Reproducible random layout

`python3 generate_random_layout.py --seed 20261017 --jitter-mm 0.65` independently samples die origins around the central feasible ring, rejects illegal proposals, and accepts the second candidate. It is not an optimized placement. All eight dies and legal default wire routes are in `random_layout.json`. The aggregate route use is **8,728.5 GB/s·mm** against a 13,500 limit. The geometry validator checks die-edge capacity at **both** endpoints, >=1 mm die gaps and package margins, all required links, obstacle-free paths, max 5/6 mm reach, and total route budget.

`python3 run_simulations.py --hotspot ../vendor/HotSpot/hotspot --grid 64 --layouts random_layout.json --output random_example` builds and runs all five steady-state cases. The precomputed output uses upstream HotSpot commit `f18831e48cef5d62580585cca0d7fab6c71bc3cc`. The script's complete `.flp`, `.lcf`, `.ptrace`, `.grid`, `.steady`, config, hash, and `power_budget.json` appear in `random_example/hotspot_inputs/random_layout/`.

| Workload | Base W | PHY W (inside / outside) | Wire W | Total W | GPU peak °C | HBM peak °C |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `tensor_training` | 399 | 1.8192 (0.9096 / 0.9096) | 1.8156 | 402.6348 | 102.21 | 87.05 |
| `skewed_compute` | 342 | 1.6848 (0.8424 / 0.8424) | 1.6212 | 345.3060 | **104.59** | 81.97 |
| `attention_decode` | 313 | 4.2960 (2.1480 / 2.1480) | 4.2407 | 321.5367 | 86.01 | 79.73 |
| `memory_stream` | 383 | 4.9392 (2.4696 / 2.4696) | 4.8157 | 392.7549 | 96.89 | **97.68** |
| `mixed_serving` | 344 | 3.1536 (1.5768 / 1.5768) | 3.0866 | 350.2402 | 94.23 | 83.77 |

This random placement becomes the scalar-score reference (`104.59 °C GPU`, `97.68 °C HBM`, score 1.0). GPU and HBM objectives peak under different workloads, so the benchmark keeps two distinct thermal goals. These example values supersede older results from the Gaussian-port source model; old outputs are excluded from the current archive.

## Integrity checks and limits

`python3 validate_package.py` checks layout legality; equality of the two workload formats to regenerated data; all five HotSpot trace sums against their predicted total watts; port rectangle areas; and conservation of PHY watts across the two vertical layers. No power is created or lost by partially covered pixels/tiles. Re-running `--reuse-existing` uses a hashed cache only when simulator inputs match.

The 64 × 64 HotSpot mesh has cells about 0.81 × 0.66 mm, while inside port rectangles have 1 mm normal depth. Inside-port fractions are allocated to 16 × 16 chiplet pixel blocks; outside fractions and routes to 1 × 1 mm interposer blocks. HotSpot then projects both layers onto the thermal mesh. The 1 mm geometry is defined exactly in source-area calculations, but gradients smaller than the thermal mesh cannot be resolved. Before fixing prize rankings, run promising and close-scoring layouts at 128 and 256 and freeze the chosen resolution. Absolute temperatures, electrical coefficients and top cooling contact are synthetic; the package does not model metal stack layer assignment, joule-current waveforms, congestion, signal integrity or real-package calibration.
