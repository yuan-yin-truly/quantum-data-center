# Thermal + router lab (local only)

Uses the repository's `pyproject.toml`, Python 3.12 and `uv.lock`. No additional dependency or lockfile changes.

```sh
cd ~/Documents/quantum-data-center
uv sync --locked --group dev
uv run python -m thermal_lab --port 5175
```

Open http://127.0.0.1:5175/thermal/ . If `uv` is not on PATH but was installed with pip, use `python3 -m uv` instead of `uv`. In PyCharm choose this repository's `.venv/bin/python`.

The combined localhost server adds the thermal page while reusing `dc_sim.server` for the original router UI and all its APIs. The embedded router is at `/router/`. Existing `dc_sim`, quantum packages, main website, package requirements and deployment files are unchanged. The old static server on 5174 supports manual forecasting only.

## Engine comparison

Run the same task preset and seed through FIFO, greedy, batch, no-quantum policy and a GPU-only reference fleet via `dc_sim.api.compare_policies`. The on-page table distinguishes:

- Policy differences on identical hardware versus FIFO (routing effect).
- Differences versus the GPU-only reference (includes hardware capital).
- Energy consumed versus electricity cost (site prices differ).
- Service targets and power limits, so fewer completed tasks cannot masquerade as savings.

These are fresh simulator outputs, not hardware measurements. Comparisons are cached for identical preset+seed until restart. The embedded router has a separate interactive session; injected tasks there do not alter the preset comparison or annual forecast.

## Links to the annual forecast

1. **Use hardware in rollout:** imports one QPU type plus workload from `dc_sim`/`quantum_arch`: price, busy system power, workload feasibility, matched classical GPU-hours, and estimated accepted jobs/hour. Throughput accounts for gate-check acceptance, a 60-second host allowance and scheduled calibration downtime. It is not a queue benchmark. Prices/classical fallback remain assumptions. The source is anchored at 2035 and earliest availability is 2035. Imported workload feasibility replaces the manual logical-qubit threshold. Future growth remains a user hypothesis.
2. **Use energy effect in rollout:** opt-in extrapolation of selected-policy versus FIFO energy and electricity-cost ratios. Each annual hybrid energy total and energy bill is multiplied once by its own ratio. This avoids double-counting amortised capex and does not infer a reduction in GPUs, peak grid demand, or cooling needs. It is a sensitivity calculation across different annual fleets, not ten engine reruns. Incomplete full service in the source comparison marks the annual scenario unvalidated. Applying hardware clears this link.
3. Export includes the input assumptions, source comparison and annual results. Clear engine links restores manual hardware defaults and removes the energy adjustment.

## Forecast boundaries

Both fleets start greenfield in 2030. LLM rack counts reproduce the original fleet model with background speed + sub-agents enabled, speculative decode + chat routing disabled. Scientific tools are additional work; no LLM tokens are offloaded. Annual GPU throughput improvements are a fleet-wide assumption, not modeled refresh purchases. Existing QPU cohorts retain purchase-year attributes.

Costs accumulate purchases, networking, cooling/buildings, energy and maintenance. QPU purchase/system power includes internal refrigeration; facility overhead is applied once. Retired GPUs receive no refund. The 2030–2034 cap is $30B; later years are an extension. Fixed QPU/support draw is deducted before computing grid-limited GPU capacity. Manual temperatures are a steady-state RC estimate, not HotSpot or cryogenic-stage predictions. Official scorer, detailed service validation and thermal calibration are still needed.

## Checks

```sh
uv run pytest thermal_lab/test_bridge.py tests/test_dc_sim.py -q
node --test web/thermal/model.test.mjs
```
