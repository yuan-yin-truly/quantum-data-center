# Design loop (`design_loop`)

An automated, iterative design study for the data-centre-of-2035 package: it proposes designs that **replace or add
quantum hardware** next to the classical GPU/HBM package, evaluates every design against **all task workloads**
(the five Beat-the-Hotspot package workloads, the whole `quantum_arch` quantum workload catalog, the data-centre job
mix and the GPU baseline workloads), keeps the non-dominated designs and breeds the next generation from them.

> **LOCAL ONLY.** Quantum hardware is not allowed on the official Beat the Hotspot hill and would be unfair there.
> Nothing produced here may be compared with, or submitted to, the leaderboard. Every output (config snapshot,
> `STATUS.txt`, `results.json`, `matrix.json`, `designs.csv`, the report) carries `leaderboard_comparable: false`.
> The loop never calls `autolab`, never commits, pushes or uploads, and only reads `.autolab/`.

```bash
cd chiplet-thermal-gui
.venv/bin/python -m design_loop status                      # which evaluators are real / surrogate / stub right now
.venv/bin/python -m design_loop run --config design_loop/example_config.json --out design_loop/example_runs/example_2035
.venv/bin/python -m design_loop resume design_loop/example_runs/example_2035 --generations 10 --extra-hotspot-runs 8
.venv/bin/python -m design_loop report design_loop/example_runs/example_2035
.venv/bin/python -m design_loop list
.venv/bin/python -m design_loop calibrate                   # refit the thermal surrogate to real HotSpot runs (Docker)
.venv/bin/python -m design_loop space --out my_space.json   # the default design space, to edit
.venv/bin/python -m pytest tests/test_design_loop.py -q     # 29 tests, ~90 s, no HotSpot needed
RUN_HOTSPOT=1 .venv/bin/python -m pytest tests/test_design_loop.py -q   # adds the real-HotSpot baseline check
```

Needs numpy, scipy and matplotlib (already in `requirements.txt`). PyYAML is optional (YAML spaces / configs).

## Launching the full run later

The checked-in `example_runs/smoke_surrogate/` is a 3-generation, seconds-long smoke run (calibrated surrogate, HotSpot off).
The full run (real HotSpot for the best screened designs, about 1-2 minutes per run with two containers in parallel) is:

```bash
cd chiplet-thermal-gui
docker info >/dev/null || open -a Docker                          # HotSpot needs the Docker daemon and the pinned image
.venv/bin/python -m design_loop status                           # package_hotspot must say "available"
.venv/bin/python -m design_loop run --config design_loop/example_config.json --out design_loop/example_runs/example_2035
# example_config.json: 8 generations x 28 candidates, <= 16 HotSpot runs (64 mesh), ~25-35 min. Interrupt freely, then:
.venv/bin/python -m design_loop resume design_loop/example_runs/example_2035 --generations 12 --extra-hotspot-runs 8
```

`--hotspot never` gives a screened-only run in seconds; `--hotspot always` in the config refuses to start without HotSpot.
The 128 mesh is not wired in (the surrogate and the score reference are calibrated at 64).
`design_loop/data/surrogate_calibration.json` and `hotspot_calibration_runs.json` hold the surrogate fit and its 15 real HotSpot
training runs; `python -m design_loop calibrate` redoes them (~15 min).

## What is evaluated, and what is real

| evaluator | what it does | source label |
| --- | --- | --- |
| `quantum` | `quantum_arch.evaluate` on the design's architecture: feasibility against the logical-error budget, rQOPS, energy/runtime of **every** catalog quantum workload, cryostat stage utilisation and fridge units, decoder sizing, power at module / system / facility boundary | `model` (illustrative catalogs, `mid2030s` scenario profile) |
| `package_legality` | the judge's own `geometry.validate_layout` (geometry, ports, routing, bandwidth budget) | `real` |
| `package_surrogate` | reduced thermal model on the judge's own heat maps, fitted to real HotSpot runs; **screening only** | `surrogate` |
| `package_hotspot` | the pinned HotSpot build through the judge pipeline in the pinned Docker image (`judge` for unmodified power, the LOCAL variant's `judge_modified` for hybrid power maps); the **only** source of thermal numbers allowed to back a claim | `real` |
| `datacentre` | adapter to `quantum_arch.datacenter` (hybrid GPU+QPU scheduler: energy per accepted answer, capacity, break-even). If that module is missing, a closed-form stand-in is used and every result is labelled `stub` | `model` / `stub` |

Every reported number carries its evaluator and its power boundary (`module`, `system`, `facility`, or `package` for
the package model's module-level watts). Energy numbers in objectives are **facility** boundary:
`(GPU servers + CPU hosts + quantum systems) x (1 + network) x PUE`.

Adapters degrade gracefully (and this is tested): no LOCAL variant of the hill -> only unmodified-power layouts can be
evaluated, hybrid designs stay `partial`; no hill at all -> legality and thermal are unavailable (`partial`); no Docker or
image -> no HotSpot, the run is "screened only" and the report says that no claim is HotSpot-backed; no scheduler ->
stand-in. The HotSpot runner never invents a temperature.

## The design space

Declarative JSON (YAML if PyYAML is installed); `python -m design_loop space` prints the default. Every gene has a
type (`cat`, `int`, `float`, `logint`, `logfloat`, `bool`), bounds or choices, a default, a group and a doc string.
`fixed` pins genes; `layout` configures the placement moves. Designs are **canonical**: genes are clamped and rounded
(`logint`/`logfloat` to two significant digits, layouts to 0.05 mm), incompatible combinations are repaired, and
genes that cannot matter in a mode are reset to their defaults, so two descriptions of the same design have the same
`id` (sha1 of the canonical JSON) and are evaluated once.

| group | genes | notes |
| --- | --- | --- |
| integration | `mode`, `offload_fraction`, `n_quantum_systems`, `support_G0..G3`, `devices_per_support_die`, `support_extra_w` | see below |
| quantum | `modality`, `scheme`, `n_qubits`, `cryostat_scale`, `profile`, `code`, `decoder`, `task` | `profile` is `mid2030s_low / mid2030s / mid2030s_high`; scheme, code, decoder are repaired to the modality (photonic -> fusion network, cat -> repetition code, ambient systems have no cryostat) |
| classical | `decoder_device`, `decoder_location` (`RT`, `4K`, `package`), `host_device`, `host_count`, `optimizer_device`, `optimizer_count`, `optimizer_location` | devices are `quantum_arch` catalog keys via `auto:<role>`; `4K` forces the cryo-CMOS ASIC and needs a 4 K stage |
| facility | `pue` | fixed at 1.15 in the default space |
| package | `layout` (die positions) | legality by the judge's own code; moves: shift 1-2 dies, mirror, swap two GPUs / two HBMs, random restarts, surrogate-guided local search |

**Integration modes** (the offload fraction is always an INPUT assumption, never derived from a claim of quantum speedup):

* `gpu_only` - baseline: 4 GPU + 4 HBM, no quantum subsystem.
* `add` - every GPU and HBM stays; `n_quantum_systems` quantum computers join the facility; a share `offload_fraction` of each
  GPU's work is assumed movable to them, which lowers the GPU power maps by exactly that share.
* `replace` - `k` (1-3) GPU dies are re-declared **quantum-support chiplets** (uniform power maps, original size and ports, so
  every geometry rule of the judge still holds). With `decoder_location = package` they host the decoder bank of one quantum
  machine (up to `devices_per_support_die` devices each, an assumption; leftovers stay at room temperature), plus
  `support_extra_w` of controller overhead. The replaced die's work is redistributed to the remaining GPUs (the variant's
  "redistributed" rule), GPU load is capped at the baseline per-die load, so a design that cannot carry the demand shows up
  in `served_fraction` / `capacity_rel`, not as a hotter-than-baseline package.
  HBM stacks are never re-declared: every GPU has a mandatory primary link to its HBM stack and the link topology is the judge's.

Movable share of the whole GPU demand: `phi = offload_fraction x (4 - k) / 4`. In the data-centre model, `add` is the scheduler's
`augment` scenario and `replace` its `replace` scenario with `k/4` of the GPU capacity removed.

## The workload matrix

Each fully evaluated design stores, in the archive and in `report/matrix.json`:

* `hill`: for each of `tensor_training, skewed_compute, attention_decode, memory_stream, mixed_serving`: GPU / HBM / support peak,
  per-die peaks, package watts, source (`hotspot` or `surrogate`);
* `quantum`: for each catalog workload (`shor_rsa2048, femoco_thc, chemistry_small, vqe_50q, vqe_20q, qla_*`): feasible, reason,
  runtime, energy (system and facility boundary), acceptance probability. `advantage_claimed` is always false and the
  catalog's classical-alternative energy is carried for reference only, never used in an objective;
* `datacentre_classes`: per job class routing, turnaround and facility joules per accepted answer;
* `gpu_baseline`: the LLM-inference, LLM-training-to-quality and dense-matmul baselines (module / system / facility).

A design for which any required evaluator is unavailable, failed or was skipped by a budget is **`partial`** and is excluded
from every Pareto front and ranking (it is still stored and listed). A design that violates a hard constraint is
`infeasible` (with reasons). Only `complete` designs are eligible.

## Objectives, constraints, ranking

Default objectives (all configurable in `objectives`): minimise worst GPU temperature and worst HBM temperature over the five
workloads (the hill's informational `score` is reported, flagged non-comparable), minimise facility joules per accepted
GPU-second of work over the data-centre mix, maximise sustained capacity relative to GPU-only.
Hard constraints: legal layout; the declared quantum task feasible within the logical-error budget (acceptance >= 0.5); decoder
keeps up with the syndrome stream; control lines fit one cryostat; fridge units <= `max_fridge_units` (the number is always
reported); support chiplet <= `support_max_junction_c`; served demand >= `min_served_fraction`.
The Pareto front uses fast non-dominated sorting (two fronts: **confirmed** = real-HotSpot thermal numbers, may support claims;
**screening** = surrogate thermal numbers, steers the search). The scalarised ranking is a weighted sum of min-max normalised
objectives (`weights` in the config).

## The loop

Each generation (`Random(seed x 1_000_003 + generation)`, so runs are deterministic given a seed):

1. **Propose**. Generation 0: the GPU-only baseline, ADD and REPLACE for every modality, a cold-decoder and a small-system variant,
   random restarts. Later: single-gene neighbours/ablations of the best designs, mutation and group-wise crossover of the
   screening front, random restarts (random walks from the known legal layouts), and surrogate-guided layout local search
   around the best feasible designs. Every child records parents, operator and the genes that changed.
2. **Stage A** (milliseconds): `quantum_arch` and layout legality; hard violations stop a design here.
3. **Stage B** (~0.2 s): thermal surrogate and the data-centre model for the survivors.
4. **Stage C** (~1 min each, successive halving): real HotSpot only for the best unconfirmed screening-front members
   (`population.hotspot_per_generation`), capped by `budget.max_hotspot_runs`, `evaluators.package.concurrency` containers at a time.
   A final confirmation pass covers the finalists. The GPU-only baseline is confirmed in generation 0 as the anchor.
5. Update fronts, ideal point and stagnation counter; append the generation summary.

Stops on: generation limit, design budget, wall clock, HotSpot-run budget, stagnation (no change of the screening front and no
improvement of any objective's best value for `stagnation_generations`), or no new designs.

**Resume / crash safety.** `archive.jsonl` is append-only, one fsynced line per design or evaluation (a truncated last line is
ignored); `state.json` is written atomically after every generation. `resume` re-reads the archive, never repeats a cached
evaluation (cache key per evaluator: identical thermal problems share one HotSpot run), and continues at the next generation.
A crash mid-generation re-runs that generation: its proposals are deterministic and already-stored results are reused.

## Run directory

```
<run>/config.json        config snapshot (+ leaderboard_comparable: false)   <run>/space.json   the design space
<run>/archive.jsonl      designs (genes, layout, parents, operator, changed genes) and every evaluator result
<run>/generations.jsonl  per-generation summaries    <run>/state.json  counters for resume    <run>/STATUS.txt
<run>/report/report.md   report    pareto.png  heatmap_hill_workloads.png  heatmap_quantum_workloads.png
                         convergence.png  best_design.png  matrix.json  designs.csv  results.json
```

## Config (`design_loop/example_config.json`, merged over `design_loop/config.py:DEFAULT_CONFIG`)

`name, seed, space ("default" | path | inline)`, `budget {max_generations, max_designs, max_wallclock_s, max_hotspot_runs,
stagnation_generations, hotspot_exhausted_stops}`, `population {candidates_per_generation, hotspot_per_generation,
layout_search_per_generation, layout_search_steps, operator_shares, p_layout_move}`, `objectives`, `weights`, `constraints`,
`evaluators {quantum, package {hotspot: auto|never|always, grid, concurrency, try_start_docker, max_gpu_load_factor, traffic_coupling,
mode: auto|stub}, datacentre {force_stand_in, gpu, cpu, facility, policy, mix, movable_class, ...}}`, `final {hotspot_finalists}`.

The data-centre inputs that matter most: `movable_class` (classical cost of the movable job in GPU-seconds, GPUs per job, mapping
quality, retries, host-side times) and `policy` (`always` routes the declared movable share to the quantum pool; `time_and_energy`
lets the scheduler refuse when quantum is not faster and cheaper). **Energy per accepted GPU-second of work is only as meaningful
as the classical cost declared for the movable class**; the report prints the break-even classical cost and a sensitivity.

## The thermal surrogate and its calibration

`surrogate.py`: heat from the judge's `combined_heat` on a 0.5 mm grid; local rise = cooler resistance (inside / outside the 44 x 34 mm
window) x two-kernel lateral spreading of die heat plus a share of interposer heat; plus bulk rise per watt entering inside / outside
the window. Eight parameters are fitted to the per-die peaks of the five workloads from real HotSpot runs
(`python -m design_loop calibrate`: the hill's example layouts, seeded random walks, hybrid power scenarios with uniform-map
support chiplets). The fit data, parameters and **leave-one-layout-out error** are stored in `design_loop/data/surrogate_calibration.json`
and reproduced in every report, with the surrogate-versus-HotSpot agreement measured in that run. The surrogate is trusted only near the
calibrated layouts and power levels; it ranks, it does not certify.

## Limits (read before quoting a number)

* Offload fraction, number of quantum systems, the movable job's classical cost and mapping quality, decoders per support die and the
  support junction limit are **inputs**. No quantum advantage is assumed, derived or reported.
* `quantum_arch` catalogs are illustrative, the `mid2030s` profile is a scenario, not a forecast; a 300k-qubit machine drawing
  megawatts next to a 350 W package is what the models say, not a claim about real systems.
* The package model (synthetic 350 W package) and the facility model (5 kW accelerator modules) are linked only through the design's genes.
* A hosting package is evaluated as the worst case (it hosts the decoder bank of one machine, quantum side always on); other packages
  of the facility are not modelled separately.
* HotSpot numbers are 64-mesh results of the judge's pipeline; hybrid power maps go through the LOCAL variant's `judge_modified`.
  Not comparable with any leaderboard number.
* The Pareto fronts say "not dominated by the other evaluated designs under these models and inputs". They do not say a design is better.
