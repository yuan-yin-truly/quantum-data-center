## Thermal & cooling

**Status:** local rollout + connected router simulation · **Start:** 2030

**Question:** When does gradually adding quantum capacity let the same fleet serve its users with less cost or grid demand, while staying inside thermal limits?

**Local simulation:** `uv sync --locked --group dev`, then `uv run python -m thermal_lab --port 5175`. Open http://127.0.0.1:5175/thermal/ . Uses the existing Python 3.12 project and lockfile, with no new dependencies. `python3 -m uv` is equivalent if the uv executable is not on PATH. The main page and deployment remain unchanged.

**Restrictions:** six Earth sites; at most 500 MW combined grid demand; $30B over 2030–2034; serve the selected user case at its required quality and deadlines before minimizing costs. The optional 2035–2039 forecast is outside that original budget window. Space locations and launch costs are excluded in line with the repository's Earth-only scope.

**What people can explore**

- Cases A/B/C, annual demand and GPU throughput growth.
- Gradual quantum purchases, logical-qubit thresholds, workload eligibility and conservative/moderate/optimistic sensitivity scenarios.
- GPU-only versus hybrid capacity, with an adjustable retained GPU provisioning level.
- A separate simulated quantum-scheduler gain and latency; no quantum scheduling advantage is presumed. Classical systems still perform I/O and enact assignments.
- Cooling method, climate, coolant temperature and chip thermal resistance.
- Annual purchases, infrastructure, networking, electricity, maintenance, cumulative five-year costs, peak grid demand and annual energy.
- Timeline playback, six-site rack heat view, per-year results and JSON export.

**Model boundaries**

The existing fleet model provides LLM rack demand. Scientific tool work is additional demand; only its eligible portion can move to a QPU. Quantum throughput is specific to one matched scientific workload, never a general GPU-to-QPU conversion. Quantum scheduler mode reserves one capable system and defaults to zero scheduling gain.

Quantum purchase costs and progress are explicit editable assumptions. Defaults use the quantum workstream's illustrative ~16 MW small-chemistry system, not a current product quote. Existing quantum cohorts retain purchase-year capability. Retiring GPU capacity does not refund capital. Refrigeration is included in QPU wall power; facility PUE adds external overhead once.

The heat view is an illustrative steady-state resistance model, not a HotSpot solve. Air cooling fails the catalog's 792 kW rack density limit. Quantum cold-stage temperatures cannot be inferred from wall-plug power and are not presented as measured results.

**Validation still required:** official scorer and catalog, QPU prices and matched-task throughput, detailed prefill/context-memory capacity, end-to-end deadline and quality evidence, thermal calibration, site-level grid limits. A modeled pass is a necessary feasibility screen, not proof of challenge compliance. Projected spending differences from infeasible configurations must not be described as savings.

**Router integration:** the page embeds the existing `dc_sim` visual simulator. A separate preset comparison calls `dc_sim.api.compare_policies` for identical task sets and seeds. It shows policy differences versus FIFO on the same fleet separately from total cost differences versus a GPU-only reference fleet. These are classical scheduling algorithms assigning GPU/QPU work, not quantum scheduling algorithms.

**Forecast links:** import QPU price, wall power, workload feasibility and estimated accepted jobs/hour from the shared 2035 model; availability starts no earlier than 2035. Optionally extrapolate a chosen policy's same-fleet energy and electricity-cost ratios into annual operating totals. Capital is not reduced again, and no peak-power or capacity benefit is inferred. Incomplete service in the source comparison blocks the forecast's feasibility claim. The imported source and assumptions are included in exported JSON. The live router's injected tasks remain a separate session.

**Next:** replace the thermal proxy with exported HotSpot/quantum stage results where valid, and rerun the router engine for explicitly matched annual fleets before claiming calibrated annual savings. The existing simulators remain unchanged. No main-page integration or deployment is part of this local prototype.

Details and model tests: `web/thermal/README.md` and `web/thermal/model.test.mjs`.
