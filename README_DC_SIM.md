# `dc_sim`: mixed GPU/QPU data-centre operations simulator with a scheduling node

A discrete-event simulator of six Earth data centres (500 MW grid in total) with GPU, LPU, prefill-card, QPU, annealer and mixed
GPU+QPU nodes, context-memory pools, and ONE scheduling node ("automated quantum Slurm"). It exists in two forms that share one
engine (`dc_sim/engine.py`): a numerical CLI and a visual local web app. Same task file + same fleet + same seed + same policy =
same result, in the CLI, through the API and in the visual app (a test enforces it).

**Everything in the outputs is the result of an illustrative model.** Demand, prices, capex and node counts are ASSUMPTIONS
(`dc_sim/data/assumptions.json`, `dc_sim/data/fleet_default.json`, flagged there). Only the following come from `quantum_arch`
(mid-2030s base scenario): accelerator module power, server overhead and LLM token rates (`gpu_2035`), QPU system/standby power,
QPU feasibility, runtime, energy and acceptance probability per workload (`quantum_arch.datacenter.quantum_job_check`), annealer
sample times and power. No quantum speed-up is assumed anywhere: quantum versus classical is decided from those numbers plus the
flagged classical-fallback cost of each task.

## Quick start (everything local; the server binds 127.0.0.1 only)

```bash
cd chiplet-thermal-gui
.venv/bin/python -m dc_sim presets                 # list the preset task sets (add --write to regenerate the JSON files)
.venv/bin/python -m dc_sim list                    # policies, presets, fleet summary
.venv/bin/python -m dc_sim fleet                   # fleet vs 500 MW and 30 B USD (capex + 5-year energy)
.venv/bin/python -m dc_sim run --tasks ui_demo --policy batch --out dc_sim/example_runs/ui_demo_batch
.venv/bin/python -m dc_sim compare --tasks ui_demo --out dc_sim/example_runs      # all policies + GPU-only reference fleet
.venv/bin/python -m dc_sim serve                   # visual app at http://127.0.0.1:8765/   (--port N)
.venv/bin/python -m dc_sim replay --tasks ui_demo --policy batch --out replay.html --every 6   # static, opens without a server
.venv/bin/python -m pytest tests/test_dc_sim.py -q                                  # the dc_sim tests (about 15 s)
```

### Launching the full runs later (deliberately not run yet)

```bash
# every preset x every policy, outputs under dc_sim/example_runs/<preset>/ (each preset takes seconds to a minute)
.venv/bin/python -m dc_sim compare --out dc_sim/example_runs
# a single large scenario
.venv/bin/python -m dc_sim compare --tasks mixed_hybrid_day --out dc_sim/example_runs
# your own fleet / task files
.venv/bin/python -m dc_sim run --fleet my_fleet.json --tasks my_tasks.json --policy greedy --out out/
```

From Python (e.g. for `design_loop`): `from dc_sim import simulate; simulate(config, tasks, policy, seed) -> metrics dict`
(`config` = fleet path/dict/None for the default fleet, `tasks` = task-spec path/dict/preset name).

## Model

**Scale decision (two-level demand).** Billions of users are not simulated one by one. (a) The mass LLM traffic of case A
(prompters, 4 B users), B (agent developers, 50 M) and C (knowledge workers, 400 M) is an aggregate FLUID token-rate model per
user region: requests/s from users x requests/user/day x diurnal curve (time zones), prefill/decode tokens, cached context that must be
recomputed on a context-memory miss, KV memory per live session, TTFT and tokens/s SLOs. It consumes prefill/decode capacity,
power and context memory of the sites. (b) DISCRETE tasks (task-spec files) are everything the user injects and the "interesting"
jobs: LLM batches, agent jobs, knowledge-work jobs, quantum jobs, hybrid pipelines. Both compete for the same racks, power and memory.

**Fleet** (`dc_sim/fleet.py`). 6 sites with a power cap each (default 85/80/85/60/85/105 MW = 500 MW), cooling (air / liquid /
immersion: PUE depends on ambient temperature; the rack power limit sets modules per rack, e.g. 14 in the air-cooled site, 64 in
liquid/immersion), energy price, WAN. Node types: GPU rack, LPU rack (decode only), prefill-card rack, context-memory pool, QPU
(40k cat qubits, 300k transmons MW-scale cryo, 40k ions), annealer, mixed node (16 GPU modules + cat QPU on a 10 us link).
QPUs have calibration windows (jobs never straddle one) and a committed job queue. Power boundaries: module (accelerators and QPU
module apparatus), system (complete server / QPU system incl. cryostat), facility = system x (1 + network 5 %) x PUE; caps and
all headline energy figures are at the facility boundary.

**Engine** (`dc_sim/engine.py`). Fixed ticks of 60 s; arrivals, completions, QPU attempts, failures, cap changes, forced
calibrations and surges are exact-time events from a heap. Per tick: events -> admission control (reject what cannot meet its SLO even on
an idle fleet or has no feasible route, with the reason) -> scheduler -> fluid routing of the mass traffic on what is left -> power and
energy accounting. The power cap is enforced by construction: discrete work is admitted only if idle + discrete + QPU power fits under
the cap; the elastic mass traffic is throttled (shed) to fit; a cap drop preempts the lowest-priority discrete work. QPU attempt outcomes
are seeded draws per (seed, unit), so runs are deterministic.

**Scheduling node** (`dc_sim/scheduler.py`, `placement.py`, `fluid.py`). One component with a modelled decision latency. Policies:
`fifo` (first-fit, home region first, quantum-eligible work goes to the first feasible QPU), `greedy` (priority/deadline order,
cheapest option meeting the SLO, compares quantum with classical per task, fluid traffic routed greedily by RTT feasibility and
energy price), `batch` (every tick a MILP, `scipy.optimize.milp`, over all pending tasks and candidate nodes: priority-weighted tasks
within SLO first, then dollars; constraints: module capacity, QPU queue time with EDF-prefix feasibility and calibration windows, power
headroom, context memory; mass traffic by a max-min LP over (class, region, site) with RTT, pool and power-cap constraints),
`gpu_only` (the batch machinery with the quantum route off: the reference policy). Every decision carries a reason string and the
best alternatives; hybrid pipelines are scheduled stage by stage (data transfer, co-location on mixed nodes).

**Cost and score** (`dc_sim/costs.py`, `report.py`). Capex per node type, building+cooling per kW and cooling type, energy by site price,
amortised over 5 years; `python -m dc_sim fleet` checks the fleet against 500 MW and 30 B USD (capex + estimated 5-year energy).
Score as in the challenge: users served within SLO at the constraints (per case A, B, C; headline = the worst of the three and the
discrete tasks), then dollars per day (energy actually used + amortised capex) against the GPU-only reference (same site caps,
QPU/mixed power replaced by GPU racks, policy `gpu_only`). `compare` also prints a per-QPU break-even table (jobs per day needed for a
QPU node to pay for itself, from the ASSUMED classical fallback costs).

## Visual app

`python -m dc_sim serve` then open the printed URL. Sites as cards (cooling, power gauge against the cap, PUE, tiles per node coloured
by type with brightness = utilisation, outline = calibrating, red = failed), the scheduling node in the middle (pending queue), animated
dots from the scheduler to the chosen node (magenta = quantum, blue = classical, red x = rejected), play/pause/step/speed, scenario and
policy selectors (policy can be switched mid-run), metrics tab (users within SLO per case, tasks, power, energy, dollars, QPU use,
offloads), Inject tab (type/size/count, paste/upload task JSON, download task file/trace, export static replay HTML), Assignments tab (all
decisions with reasons, filterable), Compare tab (all policies on the same tasks from t=0). JSON API: `GET /api/meta|state|decisions|node|taskset|trace`,
`POST /api/reset|step|advance|inject|policy|compare|import|replay`. No CDN or framework; works offline. Requests whose Host header is not
localhost are refused.

## Task-spec file (`dc_sim.tasks/1`)

See `dc_sim/tasks.py` and `dc_sim/presets/*.json`. Task types: `llm_prefill_batch`, `llm_decode_batch`, `agent_job`, `knowledge_job`,
`quantum_fault_tolerant`, `quantum_variational`, `quantum_linear_algebra`, `quantum_optimisation` (annealer), `hybrid_pipeline` (stages
GPU -> QPU -> GPU). Fields: id, arrival_s, type, case, priority 1-5, deadline_s (or slo_s), home_region, data_gb, min_success, size,
`quantum` (quantum_arch workload, repeats, host times, mapping quality, attempts) and `classical_fallback` (GPU-module-hours at the same accuracy:
ASSUMED, defaults per workload in `assumptions.json`; `null` = no classical method). Optional `events`: `site_power_cap`, `node_failure`,
`qpu_calibration`, `demand_surge`. Presets: ui_demo (3 h, light), morning_peak, quantum_heavy_research, mixed_hybrid_day,
failure_overload_stress, qpu_contention_burst, case_A_prompters, case_B_agents, case_C_knowledge.

## Limits (read before trusting any number)

- All demand, price, capex, node-count, calibration-window and classical-fallback numbers are assumptions; the classical-fallback cost
  decides whether a QPU pays off and is the largest single uncertainty. QPU capex is also assumed.
- Fluid traffic is aggregate (request-share served within SLO; SLO = RTT limit + utilisation cap); no per-request queueing, no network
  congestion between sites, no WAN contention for discrete transfers, KV hit rate lags one tick.
- Dollars: capex is fixed by the fleet, so policy differences in energy are small against it; the fleet design (QPU count) dominates.
  Per-day cost extrapolates the simulated window. Tasks unfinished at the horizon count as misses.
- LLM, LPU and prefill-card speeds use quantum_arch's 70B-class throughput scaled by an assumed model-cost factor (10); LPU and prefill
  cards are assumption-only classes. Mid-2030s hardware is a scenario, not a forecast.
- The batch MILP is myopic (one tick at a time); on the shipped presets it matches greedy for discrete tasks and wins mainly through the
  fluid LP under overload.
- Earth only; orbit, Moon and Mars are not modelled (config kept extensible). Launch cost is unused.

## Use case B node-composition study (`python -m dc_sim arch-study`)

Question: for agent developers, are specialised GPU / CPU / QPU nodes, integrated nodes that split sub-tasks internally, or a mix the better 2035 design, always against a GPU-only reference. `dc_sim/arch_study.py` is a **sizing study**, not a run of the event engine: GPUs are sized on a diurnal grid (interactive first, background work fills the valleys with a bounded wait), CPU sandboxes from the background tool load (interactive tools run on the user's laptop, as on the slides), and every quantum-eligible tool call is queued on QPUs one by one (calibration windows, lognormal durations, wait limit with classical overflow). Topologies: `specialised` = one shared QPU hall, `integrated` = each node owns one QPU and its tasks may use only that one, `mix` = node QPUs first, hall as spill-over; a pooled QPU pays an extra network round trip per optimiser iteration. Inputs are in `dc_sim/data/arch_study.json`; QPU power, runtime and acceptance come from `quantum_arch`.

The two numbers nobody knows are swept instead of chosen: quantum-eligible calls per background task, and the cost of the best classical method for such a call (GPU module-hours). Stored run: `dc_sim/example_runs/arch_study_case_b/` (about 15 min; `--quick` about 1.5 min). Limits: per-step compute uses dc_sim's `model_cost_x` proxy, not the slides' bandwidth model; a single site slice with all three regions mixed; one day of calls; unit costs, QPU capex ($120M) and host-CPU sharing are assumptions; differences between the three QPU topologies of a few percent are about one QPU and are not significant.

## Architecture v2: mixed user classes, parked sessions, shared QPU service (`python -m dc_sim dc-design`)

Replaces the "hybrid hall" idea: GPU nodes are identical and pooled, background tool calls run in a dedicated CPU sandbox pool, session context lives in a context-memory pool, and quantum-eligible sub-tasks go to a shared QPU service while the agent's session is parked and the GPU is released. `dc_sim/dc_design.py` sizes it against a GPU-only reference on the same task load: a mix of six user classes (coding agents = use case B, materials, chemistry, biology, mechanical, finance), each with its own quantum-eligible call density and classical cost (`data/dc_design.json`, all assumptions), an induced-demand factor (x1, x3, x10), and a dispatch rule found by the sizing (call classes enter the QPU service in order of saving per QPU-second until more QPUs stop paying). Calls whose classical cost exceeds `classical_max_module_hours` are not served at all by the reference. Park is compared with hold (the session keeps its KV cache in GPU HBM). `dc_sim/arch_picture.py` draws the building blocks from a stored result. Stored run, with pictures: `dc_sim/example_runs/dc_design_v2/` (about 12 min; `--quick` about 1 min).

Limits: sizing study of one site slice and one day; the prediction of a task's QPU probability at submission is not modelled; scheduling-as-optimisation on a QPU is not modelled; the class mix, call densities, classical costs, induced demand and QPU capex are assumptions, and the reference's size is dominated by the assumed classical price of the expensive calls.
