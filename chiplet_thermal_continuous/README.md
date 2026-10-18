# SUNDAI Beat the Hotspot: continuous chiplet placement and routed link heat

Place four 11.5 × 10.5 mm GPU chiplets and four 10.5 × 10.2 mm HBM chiplets anywhere legal on a 52 × 42 mm silicon interposer. Each die has a fixed orientation. Minimize the worst GPU and worst HBM temperatures over five workload patterns, while satisfying edge-bandwidth and routed-wire constraints. Participants may optimize with AI agents, surrogate models or autoresearch loops; the common judge evaluates the submitted coordinates and optional explicit routes with HotSpot.

## Package contents

| File | Use |
| --- | --- |
| `challenge_spec.json` | Authoritative rules, die dimensions, thermal stack, links and workload-generation parameters. |
| `workloads.json` | Universal numerical workload maps: 5 workloads × 8 dies × 16 × 16 base W/cell, plus traffic fractions. |
| `agent_workloads.json` | Full duplicate numerical payload with field-by-field descriptions, coordinate conventions, units and solver instructions; directly usable by an AI agent or other solver. |
| `random_layout.json` | Seeded random legal layout, seed 20261017; reproducible with `generate_random_layout.py`. |
| `random_example/` | Complete five-workload run: `results.json`, plots, thermal grids, HotSpot floorplans/traces, and `power_budget.json`. |
| `geometry.py`, `interconnect.py`, `generate_workloads.py`, `generate_agent_workloads.py`, `run_simulations.py` | Judge geometry, source rasterization, workload generation and HotSpot integration. |
| `VALIDATION.md` | Numerical checks, random example, score and model limits. |

The archive does not bundle the external HotSpot source. On Linux or WSL, from the extracted package directory:

```bash
git clone https://github.com/uvahotspot/HotSpot.git ../vendor/HotSpot
git -C ../vendor/HotSpot checkout f18831e48cef5d62580585cca0d7fab6c71bc3cc
make -C ../vendor/HotSpot -j2
python3 -m pip install numpy matplotlib
python3 generate_workloads.py
python3 generate_agent_workloads.py
python3 generate_random_layout.py
python3 run_simulations.py --hotspot ../vendor/HotSpot/hotspot --layouts random_layout.json --grid 64 --output my_random_run
```

`--layouts` accepts a JSON mapping from layout names to either bare die-origin dictionaries or objects with `placements_mm` plus optional `wire_routes_grid`. `--inputs-only` exports HotSpot inputs; `--disable-interconnect` is a zero-link-heat A/B control. Run `python3 run_simulations.py --hotspot ../vendor/HotSpot/hotspot --layouts random_layout.json --grid 128 --output my_128_run` to explore grid sensitivity.

The precomputed HotSpot example is under `random_example/hotspot_inputs/random_layout/`. To run one trace directly, use the `hotspot` executable with `-c benchmark.config -f chiplets.flp -p memory_stream.ptrace -materials_file <HotSpot>/examples/example3/example.materials -model_type grid -detailed_3D on -grid_layer_file stack.lcf -grid_steady_file memory_stream.grid -steady_file memory_stream.steady` from that directory.

## Base workloads and traffic

All wattage below excludes interconnect additions. Each die's 16 × 16 numerical map sums to its base watts; row zero is at the **bottom** of the die. Maps are in W/cell and cover the physical die footprint. In every workload, each of the eight links has a separate utilization fraction in `workloads.json`.

| Workload | GPUs G0–G3 (W) | HBMs H0–H3 (W) | Base total (W) |
| --- | --- | --- | ---: |
| `tensor_training` | 88, 94, 86, 90 | 10, 11, 10, 10 | 399 |
| `skewed_compute` | 104, 56, 92, 48 | 12, 10, 11, 9 | 342 |
| `attention_decode` | 53, 57, 50, 55 | 24, 26, 25, 23 | 313 |
| `memory_stream` | 44, 46, 42, 48 | 51, 49, 50, 53 | 383 |
| `mixed_serving` | 72, 79, 54, 63 | 18, 15, 24, 19 | 344 |

The first two emphasize compute, the next two memory, and the last mixes asymmetric loads. The heat-map shapes vary by die and workload. These values are benchmark assumptions, not measured GPU/HBM data.

## Exact heat-source definition

For link `l` in workload `w`, let `B_l` be peak provisioned bandwidth in GB/s, `u_wl` its utilization fraction in [0,1], and `L_l` routed Manhattan length in mm, including both port-to-track accesses:

```text
active_bits_per_s = 8e9 * B_l * u_wl
P_PHY_total_W = active_bits_per_s * 0.20e-12
P_wire_W      = active_bits_per_s * L_l * 0.08e-12
```

Half of `P_PHY_total_W` belongs to the GPU endpoint and half to the HBM endpoint. **At each endpoint**, its PHY heat is uniformly distributed over a rectangle whose tangential length is the reserved port length `B_l / 150` mm, centered on that port segment, and whose perpendicular extent is **1.0 mm into the chiplet plus 1.0 mm outward** from its edge. For an edge port `(x_p,y_p)` with a right/left outward normal, the rectangle is `[x_p-1, x_p+1] × [y_p-length/2, y_p+length/2]` mm; for a top/bottom port, exchange x and y. The local area density is endpoint PHY W divided by `2 mm × length`. Exactly half its watts lie inside the chiplet and enter the **die plane**; the other half lie outside and enter the **silicon interposer layer**. Adjacent PHY rectangles on the same side are separated by at least 0.4 mm. Rasterization uses the *intersection area* with each die power pixel and each 1 × 1 mm interposer tile, conserving watts even if boundaries cut cells. The outside-port source is a simplified vertical-layer representation of the fan-out/edge region.

`P_wire_W` is uniform per mm along the specified obstacle-free **Manhattan** route; all wire watts enter the silicon interposer layer. Every track segment and each orthogonal port-access leg is split at tile boundaries by length; its tile receives its fraction of total routed wire watts. Its centerline has no width and no additional source at the die edge. Port heat and wire heat may share an interposer tile: their watts add; they represent distinct electronic losses. `power_budget.json` reports total PHY, its die/interposer halves, wire watts and endpoint rectangles for each workload. The HotSpot trace includes base + inside PHY in die pixel entries and outside PHY + wire in the interposer tile entries.

For example, a fully utilized 600 GB/s link at 4 mm generates 0.96 W PHY total (0.48 W at each endpoint, 0.24 W inside and 0.24 W outside that endpoint), plus 1.536 W along its route. A fixed W/□ cannot describe this whole bundle: Ω/□ is material sheet resistance and Joule heating depends on conductor currents and activity. The technology energy coefficients are common across links, while utilization, port locations and routed lengths create workload and layout dependence. These coefficients and the two-layer heat assignment are illustrative.

## Placement, interconnects and scoring

All eight links are compulsory. Primary `P0`–`P3` connect matching G/H indices at 600 GB/s and max 5 mm routed reach. Secondary `S0`–`S3` connect G0→H3, G1→H0, G2→H1, G3→H2 at 300 GB/s and max 6 mm. Both endpoints need nonoverlapping reserved edge length at 150 GB/s/mm: 4 mm primary, 2 mm secondary. The middle 60% of each die side is usable; same-side ports need 0.4 mm between them. The deterministic port allocator picks the side facing the partner from die-center displacement, then places ports by sorted link ID. Geometric separation is ≥1 mm die to die and ≥1 mm from the interposer boundary.

The router uses 0.5 mm pitch grid cells with 0.2 mm die clearance; all chosen paths must avoid occupied cells, satisfy per-link reach, and satisfy `sum(B_l × L_l) ≤ 13,500 GB/s·mm`. Coordinates are continuous, but the reference route track coordinates are cell centers `((i+0.5)*0.5,(j+0.5)*0.5)` mm. Explicit paths in `wire_routes_grid` are arrays of adjacent `[i,j]` cells with prescribed start and end access cells. If omitted, the judge uses its deterministic shortest-path router. Its `results.json` exposes accepted paths.

Objective 1 is the maximum GPU die-plane temperature across all workloads and GPU grid cells; objective 2 is the analogous HBM maximum. Keep both in results and Pareto views. For a scalar leaderboard, after rejecting illegal submissions, the reference score is

```text
score = max((T_GPU - ambient) / (T_GPU_reference - ambient),
            (T_HBM - ambient) / (T_HBM_reference - ambient))
```

The reference is the provided seeded random layout and is recorded in `challenge_spec.json` and `random_example/results.json`. A score below one improves **both** objectives relative to that reference. The judge uses 64 × 64 steady-state HotSpot cells in this example; organizer should check 128/256 before freezing scoring. An alternate simulator can use `agent_workloads.json` to explore designs, but final comparisons require the same judge.

## Thermal boundary and scope

The HotSpot stack is a 500 µm silicon interposer (wire and outside-port sources), a 150 µm silicon die plus passive gap plane (base and inside-port sources), and a 20 µm TIM under a fixed spreader and sink. A central 44 × 34 mm good-contact region from x=4…48 and y=4…38 mm has TIM material resistivity 0.25 **m·K/W**; the peripheral region has 2.0 m·K/W. Here `m` means metres, not milli. The cooler stays fixed as dies move. No separate side-edge or bottom convection is imposed. Cooling, gaps, PCB path, PHY losses and route energy are intentionally simplified, so the outputs are relative benchmark values, not calibrated junction predictions. The router does not model wire width, layer congestion, IR drop, latency, crosstalk, vias or signal integrity.

External simulator: https://github.com/uvahotspot/HotSpot . Illustrative short-reach energy context: https://research.nvidia.com/publication/2024-04_0190-pjbit-252-gbswire-inverter-based-ac-coupled-transceiver-short-reach-die and https://ieeexplore.ieee.org/document/10919466 . Those reports do not determine this benchmark's PHY/wire split.
