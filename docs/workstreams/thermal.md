## Thermal Lab

**Status:** integrated Thermal Lab workstream. **Timeline:** 2030–2040 inclusive.

**Open:** [Thermal Lab](./thermal_lab/) in the top navigation. Workstream source, adapters, tests and saved reference runs are in `thermal_lab/`.

**Fixed source inputs:** `docs/research-notes.md` and the shared `web/src/model/brief.ts` / `fleet.ts`. Cases remain A: 4B prompters; B: 50M agent developers; C: 400M knowledge workers. The source table preserves the existing baseline, brief-policy and speculative-decoding values; no shared model logic is changed.

**Reference amounts:** A baseline 981 MW / $27.5B racks; B 704 MW / $19.8B → 306 MW / $8.6B; C 734 MW / $20.6B → 339 MW / $9.5B. The source's speculative-decoding assumption gives 456/196/218 MW respectively. These are decode/rack estimates, not complete deployed systems.

**Case-specific scenarios:** changing the case or routing preset reloads a complete profile. Reference is classical source-policy optimization; conservative/moderate/optimistic QC cases assume 0/5/10% extra throughput on covered work. Recommended profiles enable the existing speculative-decoding assumption. The default Annual deployment goal chooses a passing first-year assignment adoption share and initial routing fleet, then migrates assignments through 2040, capped by installed hardware. The alternative lowest-five-year-cost goal compares initial routing fleets of one through four systems and can deploy everything up front. This is a documented candidate search, not a global hardware optimizer.

**Separate quantum roles:** routing QPUs plan assignments and change the assumed GPU requirement; scientific QPUs execute eligible tool jobs. Each has its own controls, counts, price, power and workload contribution. GPU execution, scientific execution and unserved work share one workload denominator and sum to 100%. Routing coverage is a planning metric, not additional completed work. Counts and cards use the selected inspection year.

**Complete inputs and errors:** recommended profiles fill all active numeric fields. Removing a required field names it in a warning and hides stale graphs/results; export and playback pause until restored. Valid zero allowances remain valid. Optional scientific price and throughput inputs become required only when that pool is enabled.

**Evidence and assumptions:** `thermal_lab/page/sources.mjs` links vendor hardware/transaction proxies, electricity statistics, construction cost context and roadmap information. Thermal resistance (0.009 K/W), temperature limit (85°C), dispatch latency (50 ms), 5% prefill power allowance, 2 MW support allowance, routing coverage and extra QC throughput are explicit scenario assumptions. These are not new measurements, complete prefill/memory sizing, or proof of quantum advantage over classical scheduling.

**Constraints:** 500 MW across six Earth sites; $30B over 2030–2034; all users served at required quality and deadlines. Passing the entered numerical screens does not certify end-to-end compliance; the official scorer, site data and hardware/workload measurements are still needed. Orbit, Moon, Mars and launch costs remain outside the notes' Earth-only scope. Annual technology trends default to zero; neither Moore's nor Neven's law automatically reduces demand.

**Reproduce:** `node thermal_lab/export-reference.mjs`, `uv sync --locked --group dev`, `uv run python -m thermal_lab.snapshot`. Optional live mode: `uv run python -m thermal_lab --port 5175`. No package or lockfile changes. See `thermal_lab/README.md`.


**Annual deployment update:** the default view migrates a case-specific share of assignments to QC routing each year through 2040, limited by installed routing capacity. First-year adoption is selected to pass the entered numerical screens. This is an explicit commissioning schedule, not a technology-growth forecast. Power and annual running costs decline in the default QC scenarios; cumulative spending still accumulates. Lowest-cost upfront deployment remains selectable. Routing and scientific QPUs have independent enable switches and workload roles.
