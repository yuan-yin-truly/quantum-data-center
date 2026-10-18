# beat-the-hotspot-quantum (LOCAL-ONLY variant)

> **NOT FOR THE LEADERBOARD.** This variant lets a submission use quantum hardware. That is not allowed on
> the official hill and would be unfair there. Nothing produced here may be compared with, or submitted to,
> `czaja107/beat-the-hotspot`. Every output of `eval_quantum.py` carries `"leaderboard_comparable": false`
> and a notice saying so. The hill is never published, pushed or committed; it has no remote. The original
> pulled hill (`.autolab/hills/beat-the-hotspot`) is untouched, and so are `chiplet_thermal_continuous/` and
> the physics of `quantum_arch`.

## What this is

The original hill places 4 GPU dies and 4 HBM stacks on a 52 x 42 mm interposer and scores the hottest GPU
and HBM cell over five fixed workloads with a pinned HotSpot build. This variant keeps that judge as the
**classical core** and adds an optional `quantum` block to `submission.json`. With it you can

1. **Replace**: declare that a fraction of a workload's GPU compute (and optionally its link traffic) is
   offloaded to a quantum+classical subsystem, which lowers those GPU power maps by exactly that fraction.
2. **Augment**: re-declare a GPU die as a quantum-support chiplet (decoder/controller host) that carries the
   decoder bank of the quantum machine on the interposer, so its power lands in the package.
3. Evaluate the quantum subsystem with the existing `quantum_arch` simulator (modality, scheme, qubit
   count, QEC, decoders, cryostat) and report **whether it can actually run the offloaded task**, its
   rQOPS, runtime, energy, per-stage cryostat load and fridge units, and fold everything into one
   system-level number set.

With **no** `quantum` block the variant is the original hill: the same judge function is called, and the
baseline reproduces the official numbers (below).

## Files added or changed (everything else is the original, byte for byte)

| file | role |
|---|---|
| `eval_quantum.py` | CLI and `eval()` entry point; orchestration, report assembly |
| `quantum_block.py` | schema and validation of the `quantum` block (pure Python) |
| `quantum_eval.py` | runs `quantum_arch`; decoder placement on package hosts; feasibility |
| `hybrid_power.py` | builds and applies power-map and link-traffic modifiers (numpy only) |
| `thermal_job.py` | thermal runs inside the container; calls the original `judge` or its mirror |
| `reference/reference_{64,128}.json` | the published baseline peaks (original `private/` is empty here) |
| `eval.py` | now delegates to `eval_quantum.eval`; the original is verbatim in `eval_original.py` |
| `hill.yaml` | renamed `beat-the-hotspot-quantum`, version `0.2.0-quantum.local1`, same pinned image |
| `examples/` | `baseline`, `invalid` (originals) plus `replace_vqe`, `augment_decoder_host`, `combined`, `infeasible_task`, `invalid_quantum_block` |
| `tests/test_quantum_variant.py` | 54 tests (plus the original tests; `test_hill.py` reads `reference/` instead of the empty `private/`) |
| `local_runs/` | real HotSpot outputs of the examples |

The original `eval.py`, `verify_submission.py`, `verify_high_accuracy.py`, `geometry.py`, `interconnect.py`,
`generate_workloads.py`, `run_simulations.py`, `challenge_spec.json`, workloads and the HotSpot binary are not
edited. `.vc/` (the original's version-control state) was dropped from the copy so nothing here can be pushed.

## How a submission is evaluated

1. `quantum` is stripped; the rest goes to the **original** `verify` (validity first, same wording, fast).
   An illegal layout is rejected exactly as the original does (`passed: false`, 1,000,000 on all metrics),
   even when it carries a `quantum` block. Any other unknown top-level key is still rejected.
2. The `quantum` block is validated (clear error, no crash), then evaluated with `quantum_arch`.
3. The declared assumptions are turned into a small modifier document (per workload and die power factors,
   per-link utilisation factors, uniform power maps for support chiplets).
4. Thermal: the **classical** run (original workloads, original `judge`, unmodified) and, when the modifiers
   are not the identity, the **system** run (`judge_modified`, a line-for-line mirror of `judge` whose only
   difference is that the spec's link utilisation and the portable power maps come from the modifiers;
   `create_hotspot_files`, the HotSpot command, `parse_grid` and `die_peaks` are the original functions).
   A test proves the mirror gives bit-identical peaks to the original judge on the baseline.
5. The report is assembled and stamped not-comparable.

## Submission schema (optional `quantum` block)

```jsonc
{
  "placements_mm": { ... },            // unchanged
  "wire_routes_grid": { ... },         // unchanged, optional
  "quantum": {
    "schema_version": 1,
    // exactly one architecture source (required):
    "architecture": { ...quantum_arch Architecture dict... },
    "architecture_example": "sc_rt_direct_100q",     // name of quantum_arch/examples/*.json
    "architecture_file": "arch.json",                // relative path inside the submission dir
    "architecture_overrides": { },                   // deep-merged on top (optional)

    "task": {
      "workload": "vqe_50q",                         // required; key of quantum_arch/data/workloads.json
      "package_workload": "mixed_serving"            // hill workload the package runs meanwhile (default)
    },

    "offload": {                                     // INPUT ASSUMPTIONS
      "fractions": { "*": 0.10,                      // workload -> fraction | {die: fraction}; "*" = all
                     "memory_stream": {"G0": 0.2, "*": 0.1} },
      "dynamic_power_fraction": 1.0,                 // share of a GPU map that scales with the offload
      "traffic_coupling": 0.0,                       // link utilisation x (1 - coupling * fraction)
      "replaced_die_work": "redistributed",          // or "dropped"
      "active_in": ["tensor_training", "..."]        // workloads in which the quantum side runs (default all)
    },

    "package_hosts": {                               // GPU dies re-declared as quantum-support chiplets
      "device": "asic_decoder_rt",                   // quantum_arch classical-catalog device
      "dies": { "G3": { "max_devices": 8,            // required: devices the die can host (assumption)
                        "extra_power_w": 3.0,        // controller/IO overhead, always on
                        "traffic_scale": 0.0,        // scales the utilisation of its two links
                        "max_junction_c": 110 } }    // optional limit; exceeding it makes the hybrid infeasible
    },

    "limits": { "max_fridge_units": 30, "max_total_power_w": 5e6 }   // optional
  }
}
```

Rules: fractions are in [0, 1]; only GPU dies (G0-G3) can offload or become hosts; at least one GPU must
remain; a host cannot also offload; an offload fraction > 0 needs the workload to be in `active_in`.
Support chiplets keep the original die size and ports, so every original geometry constraint still applies
unchanged. Power maps of support chiplets are uniform.

### Power model of the declared assumptions

For a remaining GPU `i` in workload `w`, with original base power `P_i`, offload fraction `f_i`:

```
P_i' = P_i * (1 - dynamic_power_fraction * f_i)  +  [redistributed only]  P_i / sum_j P_j * R
```

`R` is the original base power of all replaced dies in `w`. With `replaced_die_work: "redistributed"`
(default, conservative) the remaining GPUs absorb the replaced GPU's work; `"dropped"` assumes that work
is part of the offloaded work and simply disappears (cooler, and a strong assumption). The utilisation of a
link with remaining GPU end `i` is multiplied by `(1 - traffic_coupling * f_i)` (and by the redistribution
factor), clipped to 1. A replaced die's links get `traffic_scale`. Interface (PHY) and wire heat are then
recomputed by the original `interconnect.combined_heat` from the new utilisations and the routed lengths.

A host die's power in workload `w` is `devices * device.power_w(utilisation) + extra_power_w` if `w` is in
`active_in`, else `devices * idle_w + extra_power_w`. `devices` is the number of decoder devices that
`quantum_arch` sizes for the syndrome stream, capped by `max_devices`, spread round-robin over host dies;
devices that do not fit stay at room temperature and are reported.

## Output

`python eval_quantum.py <dir>` prints JSON (and a short summary to stderr). Groups:

* `classical`: the unmodified judge on the original workloads: `score`, `worst_gpu_c`, `worst_hbm_c`,
  per-workload peaks and power. (This is what the official hill would report for the layout, for reference
  only.)
* `quantum`: `present`, `valid`, `feasible`, `infeasible_reasons`, `architecture`, `capability` (error
  corrected?, code distance, logical qubits, Lambda, logical clock, rQOPS, logical error per op), `task`
  (feasible, runtime, energy of the quantum_arch system, distance, factories, total logical error vs
  budget), `decoder` (algorithm, ops/s, latency, where the devices sit), `cryostat` (fridge units, wall
  power, Carnot floor, per-stage load / capacity / utilisation / overload), `power_w` breakdown, warnings.
* `system`: `hybrid_feasible`, `package` (peak temperatures **with the offload applied**: `worst_gpu_c`,
  `worst_hbm_c`, per-workload peaks, support-chiplet peaks vs their limit, an informational score against
  the official reference), `power_by_workload` (package W classical vs with offload, quantum side outside
  the package, total electrical, facility with PUE, energy per task), `task`.
* `leaderboard_comparable: false`, `notice`, `declared_assumptions`, `modifiers`, `thermal`.

`metrics` (hills-style: `score`, `worst_gpu_c`, `worst_hbm_c`) are the **system** numbers when the hybrid is
feasible and 1,000,000 when it is not, so an infeasible quantum block cannot buy a cooler package.
`system.package.credible` is false in that case and the temperatures are labelled hypothetical.

Status and exit codes: `ok` / `ok_no_thermal` 0, `invalid_layout`, `invalid_quantum_block`,
`quantum_unavailable` 2, `hybrid_infeasible` 3, `thermal_unavailable` 4.

Energy per task = (quantum-side electrical power outside the package + package power with offload for
`task.package_workload`) x the `quantum_arch` runtime of the task. No all-classical comparison is made: that
would need an assumed speedup (see honesty rule).

## Honesty rule and assumptions

* **The offload fraction is an input.** Nothing derives it from a speed-up claim. `quantum_arch` only decides
  feasibility and cost of the declared task. The classical-alternative energy and advantage fields that
  `quantum_arch` computes for some workloads are deliberately dropped and not used.
* The link between "x % of GPU compute" and "one run of workload `vqe_50q`" is **declared by whoever writes
  the submission**; the model has no physical mapping between them. The shipped examples are illustrative.
* Catalog values (qubit parameters, fridge wall power 10 kW per unit, decoder ops per bit, ASIC TDP of the
  `asic_decoder_rt` entry, cryo-CMOS power ...) are quantum_arch's illustrative assumptions; read its
  `README_QUANTUM.md` before quoting any number.
* Quantum-side power is treated as steady state and always on; only package-hosted decoders switch between
  active and idle power by workload. `quantum_arch` totals include its own host/optimiser devices (CPUs,
  GPUs at room temperature). Those are separate hardware from the package GPUs, and the optimiser step of
  variational tasks runs on them, not on the package.
* `quantum_arch` counts decoder power even for variational tasks that use no QEC (conservative).
* A quantum_arch warning of an overloaded stage means "needs N fridge units". That is feasible here unless
  `limits.max_fridge_units` is set, or the control lines exceed one fridge (`units_for_lines > 1`, which is
  always infeasible: no cryogenic interconnect is modelled).
* HBM stacks cannot be re-declared; only GPU dies can host. Redistributed load changes power and link
  utilisation of the remaining GPUs but not their die area, so it is optimistic about their thermal limits.
* The reference peaks for the score (104.59/97.68 on 64, 104.74/97.70 on 128) are the numbers published in
  the original README, stored in `reference/` because the pulled hill's `private/` directory is empty. The
  `score` in the system group is informational only.

## Running it

Python with numpy, scipy, matplotlib (the repo venv); HotSpot via Docker on macOS (needs the daemon, image
platform `linux/amd64` under emulation) or directly on Linux x86-64.

```bash
PY=../../.venv/bin/python            # the repo venv (numpy, scipy, matplotlib, pytest)
cd hill_variant/beat-the-hotspot-quantum

$PY eval_quantum.py examples/baseline                      # classical core: 104.59 / 97.68, score 1.0
$PY eval_quantum.py examples/combined --output out.json    # hybrid, 64 mesh, ~2 min under emulation
$PY eval_quantum.py examples/combined --grid 128           # finer mesh, compare only with other 128 runs
$PY eval_quantum.py examples/combined --no-thermal         # legality + quantum + power accounting, seconds
$PY -m pytest tests/test_quantum_variant.py -q             # 54 tests, ~1 s (HotSpot test opt-in)
RUN_HOTSPOT=1 $PY -m pytest tests/test_quantum_variant.py -q   # adds the HotSpot equivalence test
```

`quantum_arch` is found at `../..` (this variant lives in `<repo>/hill_variant/`), at a sibling
`../../../chiplet-thermal-gui` checkout, or at `$QUANTUM_ARCH_REPO`.

**`vendor/HotSpot` is not in this repo** (a 2 MB third-party source tree plus a Linux x86-64 binary, shipped by the
original hill). To run thermal evaluations, restore it from the original hill:
`autolab --url https://app.autolab.ai hills pull czaja107/beat-the-hotspot`, then copy its `vendor/` directory
next to `eval_quantum.py`. Everything else, including `--no-thermal`, works without it. If Docker is not running, `eval_quantum.py` reports `thermal_unavailable` (exit 4)
with the reason and prints no temperatures; `--no-thermal` still works. Start it with `open -a Docker`.

**`hills eval`**: not usable for this variant here. The variant is a structurally valid hill
(`hills check beat-the-hotspot-quantum --no-tests` passes), but `hills eval` only evaluates a *versioned*
hill, and the `.vc` directory was deliberately removed from the copy so that it can never be committed or
pushed (`hills eval --current` answers "has no version control"). It would also run the evaluator inside
the pinned image, which has no scipy. Use `eval_quantum.py` directly.

## Local results (64 mesh, real HotSpot, baseline layout, illustrative inputs)

| run | classical GPU / HBM (C) | system GPU / HBM (C) | quantum feasible | notes |
|---|---|---|---|---|
| `baseline` (no quantum) | 104.59 / 97.68 (score 1.0) | same | n/a | reproduces the official 64-mesh numbers |
| `baseline`, `--grid 128` | 104.74 / 97.70 (score 1.0) | same | n/a | reproduces the official 128-mesh numbers (~13 min under emulation) |
| `replace_vqe` | 104.59 / 97.68 | 98.62 / 95.53 | yes | 10 % of GPU compute offloaded; package 350 -> 328 W (mixed_serving); quantum side 23.9 kW, 2 fridges |
| `augment_decoder_host` | 104.59 / 97.68 | 121.48 / 105.91 | yes | G3 hosts 3 decoder ASICs (98 C), its GPU load redistributed |
| `combined` | 104.59 / 97.68 | 108.33 / 103.27 | yes | hosting plus 25 % offload on G0-G2: still hotter than the baseline |
| `infeasible_task` | 104.59 / 97.68 | (hypothetical) | **no** | chemistry_small needs ~588k physical qubits, has 100k; penalised |

What they say: offloading compute cools the package by a few degrees, but the quantum side draws
10^4 to 10^6 times the power saved (2.7 MW against ~360 W for the 100k-qubit cryo-CMOS machine, dominated
by 27 fridge units). Hosting decoders on the interposer costs a GPU slot and heats the rest of the package.
These are consequences of the declared inputs, not predictions.

Raw reports: `local_runs/*.json`.
