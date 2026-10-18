# Thermal Lab data consistency audit — 18 October 2026

The main site fleet model and docs/research-notes.md remain the source of GPU rack and workload figures. No new measured quantum advantage is claimed.

- Case C has two source settings: notes enable chat routing (339.47554 MW), while the current main website disables it (337.092547 MW), before speculative decoding. Both variants are exported from the shared model. Recommended scenarios use website settings; the control can select research-note settings.
- Every primary savings card, graph and annual row uses the selected GPU comparison. The original unoptimized and optimized fleets remain separately labelled reference rows.
- Fixed support and powered quantum equipment use continuous annual energy in all comparators. Average GPU utilization applies to peak LLM serving; scientific demand is already expressed as daily GPU-hours.
- Extra scientific demand is normalized to baseline LLM work, so changing LLM policies cannot silently change scientific jobs/day. Future GPU throughput changes GPU capacity per scientific job, not the underlying number of jobs.
- Infrastructure sizing includes entered prefill power and fixed support. Thermal density includes that same prefill allowance. The allowance is not a detailed memory/prefill model.
- The component ledger reconciles facility MW, annual GWh and accumulated purchases plus operating costs. GPU retirement produces no refund. Physical rack diagrams round up; costs use continuous rack equivalents, matching the shared source model.
- The budget window is 2030–2034. The selected year and all-year screen through 2040 are distinguished. Tool-pool quantum scheduling must also meet the entered latency screen.

External prices and power figures in sources.mjs are proxies. Quantum assignment coverage, extra throughput, dispatch latency, thermal resistance and commissioning schedules remain explicit assumptions. Declining default curves reflect assumed deployment, not Moore’s or Neven’s law. Saved Python router results remain separate classical simulation evidence.
