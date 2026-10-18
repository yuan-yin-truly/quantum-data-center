# Research notes

_Plan review from Sun Oct 18, 2026. The live numbers are on the team page (problem statement and status quo); the model behind them is `web/src/model/`. "Brief p.N" is a page of `data/data center design requirements.pdf`. "Deck s.N" is a slide of `data/145 - Chips and data center 2035.pptx`._

## Where we stand

- **Earth only.** No orbit, Moon or Mars.
- **Case B (agent developers)** is the working choice; the reasons are below. The comparison on the team page shows all three cases.
- **Demo is tonight at 8 PM, and slides aren't allowed** (Deck s.43–44). Our website is the pitch, so it should feel like a live tool, not a deck.
- **Scoring:** users served at the speed targets first, then dollars saved (Brief p.5). The speaker notes add: "The leaderboard rewards the best design; the pitch rewards the best idea" (Deck s.16).

## Gaps in our plan

1. **The fleet model covers decode only.** Prefill, buildings, energy cost and carbon need site prices the brief doesn't give.
2. **Quantum doesn't make tokens.** It needs its own slot and its own measure of value; see "Quantum" below. The team's `quantum_arch` simulator sizes the machines.
3. **The thermal tool is built for Track 2.** It needs a bridge to Track 1, which is cooling and PUE; see "Thermal" below. It now lives in this repo (`chiplet_gui/`, `chiplet_thermal_continuous/`).
4. **Don't project 2035 hardware for the design.** The brief fixes it for every team, so use trend lines only for credibility and for our what-if.

## The brief in numbers

**Hard limits** (Brief p.5): $30B over 5 years for chips, buildings and energy; 500 MW of grid across all Earth sites.

**Workloads** (Brief p.6)

| Request | Model | Reads | Writes | Deadline |
| --- | --- | --- | --- | --- |
| Chat prompt | Qwen3.5-397B | 64k (56k cached) | 3,500 | first token 0.6 s, 60 tok/s |
| Agent step, interactive | Kimi K3 | 256k (250k cached) | 500 × 80 steps | 2 s, 100 tok/s, task 25 min; tools take 8 s on a laptop |
| Agent step, background | Kimi K3 | 256k (250k cached) | 500 × 80 steps | 10 s, 30 tok/s, task 4 h; sandbox next door |

**Models** (Brief p.6). Kimi K3 and Qwen3.5 keep a KV cache in only 1 of 4 layers.

| Model | Total | Active | KV per token + state | Context |
| --- | --- | --- | --- | --- |
| Kimi K3 | 2.8T | 104B | 14 KB + 217 MB | 1M |
| Qwen3.5-397B | 397B | 17B | 15 KB + 94 MB | 262k |
| Qwen3.5-122B | 122B | 10B | 12 KB + 75 MB | 262k |
| gpt-oss-120b | 117B | 5.1B | 18 KB + 2 MB | 131k |

**Cases** (Brief p.7)

| Case | Users | Per day | Peak tokens/s per user |
| --- | --- | --- | --- |
| A Prompters | 4B | 30 chat prompts | 2.4 out + 5.6 in |
| B Agent developers | 50M | 12 interactive + 30 background tasks | 28 out + 333 in |
| C Knowledge workers | 400M | 20 prompts + 1 interactive + 4 background | 4.6 out + 40 in |

**2035 racks** (Brief p.8): GPU rack 792 kW, $23.8M, 144 chips (3 TB at 120 TB/s each). LPU rack 516 kW, $14.3M, 256 chips (160 GB at 200 TB/s). Air rack 37 kW, $0.5M, 32 cards. For scale, a 2025 GB200 NVL72 is 132 kW and about $3–5M.

**Cooling** (Deck s.15; not in the PDF). PUE = 1 + cooling + 0.04. Racks above 50 kW need liquid. Carbon costs $100/t; evaporative cooling uses 1.8 L of water per kWh.

| Cooling | Cold site | Desert site | Max rack |
| --- | --- | --- | --- |
| Air + chillers | 1.16 | 1.54 | 50 kW |
| Air + evaporative | 1.10 | 1.26 | 50 kW |
| Direct liquid | 1.07 | 1.14 | 1.5 MW |
| Immersion | 1.06 | 1.10 | 2 MW |

**Round trip to users** (Brief p.9): N. Virginia 25 ms, Midwest 35, West Texas 45, Nordics 70, Iceland 80, Gulf 110. Every Earth site passes even the 0.6 s chat deadline, so on Earth **latency isn't the constraint; power is**.

## Fleet model (status quo)

Method (Brief p.10): each decode step gives every user in the batch one token and reads that user's whole KV cache once. The speed target fixes the step time, and the batch fills the rest. Our per-step overhead is backed out of the brief's two published points: 2.2 ms for chat, 3.8 ms for Kimi K3. With those, the model reproduces them exactly (960 chat users per GPU; 117 agent users per GPU).

Results at direct liquid, cold site (PUE 1.07). The brief's levers ("efficiency settings" on the page) are the ones it lists on p.6; speculative decoding is our assumption of 2 accepted tokens per step.

| Case | Baseline | Brief's levers | + speculative decoding |
| --- | --- | --- | --- |
| A | 981 MW (196% of cap), $27.5B racks | none help; routing makes it worse: 1,029 MW | 456 MW (91%), $12.8B |
| B | 704 MW (141%), $19.8B | background at 30 tok/s + sub-agents: 306 MW (61%), $8.6B | 196 MW (39%), $5.5B |
| C | 734 MW (147%), $20.6B | background at 30 tok/s + sub-agents: 337 MW (67%), $9.5B | 217 MW (43%), $6.1B |

What this tells us:

- **Every case is over the 500 MW cap with a naive design.** At the cap, A serves 51% of users, B 71%, C 68%.
- **Routing chat to gpt-oss-120b doesn't help decode.** It stores 18 KB of cache per token against Qwen's 15 KB, so it reads more per token, not less. For C it adds ~2 MW (339 vs 337 MW), so the page leaves it off.
- **For B, the brief's own levers close the gap.** 71% of B's output is background agents, which only need 30 tok/s. Sub-agents shrink caches from 3.8 GB to 0.46 GB.
- **With speculative decoding, agents become limited by memory size, not bandwidth.** Caches parked during 8 s tool calls fill GPU memory. That is where LPUs and a context-memory tier come in.

## Why case B, and what it means for quantum

- **A has the biggest gap but no place for a QPU.** Its gap is pure chat decode: about 2× the cap, a 0.6 s deadline and no tool calls. The only lever that closes it is our assumption about speculative decoding.
- **B has the one slot a QPU can fill.** Background agents run their sandbox in our building, with a 10 s first-token deadline and 4 h per task. A QPU can sit there as a tool the agent calls, and that slack can absorb QPU job queues.
- **B leaves room to host it.** The brief's levers bring B to ~306 MW and ~$8.6B in racks. That leaves ~194 MW and ~$21B (before buildings and energy). In `quantum_arch`'s 2035 base scenario a QPU that runs small chemistry draws ~0.27 MW (40k cat qubits) to ~3.4 MW (300k transmons), so power doesn't limit the QPU wing; utilisation and the classical cost per call do.
- **Honest caveat:** a QPU won't lower decode MW. The quantum story has to be what agents can do with a QPU tool, not cheaper tokens.
- **Break-even:** with a $120M cat-qubit QPU doing 11.7 chemistry calls an hour, a QPU is cheaper only when the classical method costs more than ~55 GPU-hours per call (~4 GPU-hours on energy alone). We assume 768 (a `dc_sim` input). `dc_sim/arch_study` finds the same shape: for its faster `vqe_50q` kernel the crossover is 3–10 GPU-hours.

## Quantum: what we know

- **It can't help with token generation.** Decode streams 0.5–3.8 GB of cache per user per token; it is limited by memory bandwidth. There is no demonstrated quantum speedup for that, and getting classical data into qubits is itself the bottleneck.
- **Roadmap:** IBM Starling (2029): about 200 logical qubits, 100M gates. Blue Jay (2033+): about 2,000 logical qubits, 1B gates.
- **Power at today's scale.** A small system (one dilution refrigerator, ~100 qubits) draws about 10–26 kW (Google Sycamore paper).
- **2035 machines** (`quantum_arch` mid-2030s base scenario, system power; scenarios, not forecasts). The page uses the cat-qubit row.

  | QPU | Logical qubits | System power | Small chemistry job (100 logical qubits) |
  | --- | --- | --- | --- |
  | Superconducting, surface code, 300k | 99 | 2.9 MW | 11.8 min, 571 kWh |
  | Cat qubits, repetition code, 40k | 263 | 0.27 MW | 3.8 min, 17 kWh |
  | Trapped ions, qLDPC, 40k | 777 | 0.35 MW | 2.8 days |
  | Neutral atoms, surface code, 1M | 240 | 0.52 MW | 3.2 days |

- **Older numbers are superseded.** The first fleet card used the `projected` profile (~27 W per physical qubit, ~16 MW per small-chemistry machine, ~340 MW for FeMoco). The 2035 profile is 5–60× lower: better cryostats and, for cat qubits, a code that needs far fewer physical qubits.
- **FeMoco** (2,196 logical qubits, 6.7e9 Toffoli) is larger than any bundled 2035 example; it isn't sized yet.
- **Slow modalities:** ions and atoms avoid the dilution fridge but their logical clock is about 1,000× slower, so a chemistry job takes days instead of minutes.
- **Open research questions** are in `docs/workstreams/quantum.md`; details in `README_QUANTUM.md`.

## 2035 projections

- **The catalog implies** a 2035 GPU with 120 TB/s, 3 TB, about 5.5 kW and about $165k per chip (792 kW and $23.8M ÷ 144). An LPU is about 2 kW and $56k per chip.
- **The curve that matters is memory bandwidth, not FLOPs**, because decode is limited by bandwidth. A B200 (2025) has 8 TB/s; reaching 120 TB/s by 2035 is 15×, a doubling every ~2.6 years.
- **Epoch AI measured memory bandwidth doubling every ~4.1 years historically.** That trend gives about 43 TB/s in 2035, roughly 2.8× fewer users per GPU. This is a strong candidate for our what-if.
- **Compute:** FLOP/s doubles every ~2.2–2.8 years and FLOP/s per watt every ~1.7 years (Epoch). That mostly matters for prefill.

## Thermal tool (for the thermal owner)

- **What it is:** the organizer's [chiplet-thermal-gui](https://github.com/Czaja107/chiplet-thermal-gui), now in this repo as `chiplet_gui/` (the GUI, `python -m chiplet_gui`) and `chiplet_thermal_continuous/` (the Track 2 judge). It is a desktop GUI around that judge. It places 4 GPU + 4 HBM chiplets on a 52 × 42 mm interposer and runs HotSpot over 5 workloads. Its package is ~313–399 W with a fixed cooler (0.08 K/W, 25 °C ambient). The reference worst GPU peak is 104.6 °C.
- **Headless:** run `chiplet_thermal_continuous/run_simulations.py --hotspot <bin> --layouts <json> --grid 64 --output <dir>`. It only needs numpy and matplotlib; the GUI isn't required. HotSpot builds with `make`; clang is on our Macs.
- **Outputs:** `results.json` (per-die peaks), `power_budget.json`, and `hotspot_inputs/<layout>/<workload>.grid` (64×64 temperatures per layer, in Kelvin). The bundled `random_example/` is enough to build the web heatmap before any new runs.
- **Bridge to Track 1 (Earth):** scale the power maps toward the ~5.5 kW 2035 chip, then sweep the cooler's resistance and coolant temperature. The question is the highest coolant temperature that keeps chips in spec. That decides which cooling and climate row is real (desert direct liquid at 1.14 vs cold at 1.07: about 7% of facility power).
- **Shortcut:** if leakage modelling is off, steady state is linear. A coolant-temperature change shifts every temperature by the same amount, and power scaling multiplies the temperature rise. Check that with two runs, then compute the curves instead of re-running.

## Website roadmap

1. Problem statement and comparison (done): GPU sandbox vs QPU wing for agent science-tool calls; GPU-only vs GPU + QPU for all three cases with a tool-call frequency switch and key assumptions.
2. Workstream sections (filled from `docs/workstreams/`).
3. QC Hybrid Simulator (`thermal_lab/`): annual rollout, router comparison and playback.
4. Thermal: heatmaps from `.grid` files and a coolant-temperature sweep chart.
5. 2035 trend chart with the catalog point.
6. What-if sliders: bandwidth growth, grid cap, carbon price.

## Keeping the story consistent

Checked across the team page, `thermal_lab/` and `dc_sim/` on Oct 18:

- **One quantum story.** The QPU runs agents' science tool calls; the router that picks GPU or QPU is classical (as in `dc_sim`'s scheduler). The QC Hybrid Simulator's default "QC router" (an annealer credited with GPU savings, +10% assumed throughput on LLM work) is a different claim. By its own numbers, the brief's levers alone save $25B by 2034 for case B, and the QC-routed rollout is $13.5B worse than applying those levers classically. Suggested: default the simulator to the scientific-QPU pool against the optimised GPU fleet, and keep QC routing as a labelled what-if.
- **One status quo.** Case B is 306 MW with the brief's levers; speculative decoding (196 MW) is upside, not baseline. The simulator's ~208 MW adds speculative decoding, a 5% prefill allowance and 2 MW of support.
- **Token-serving rate.** `dc_sim/arch_study` and `dc_design_v2` size tokens with `dc_sim`'s own 70B-anchored estimate (`model_cost_x`), not the brief's per-GPU method: about 7× more GPUs per user (~55 MW per 1M developers vs ~6 MW). Use their ratios, not their absolute MW or users-per-pod figures.
- **Call density.** `dc_design_v2` assumes 1 chemistry call per 100 background tasks for chemist users; the page's headline uses 1 in a million across all of case B, so the headline is the conservative one.

## Open questions

- The brief doesn't say how sandbox compute (where a QPU would sit) is counted. We count it as extra load inside the 500 MW cap.
- How does peak demand split by workload? An older deck version said peak hour is 2× for chat, 2.5× for agents and 1× for background (Deck s.17).
- How much spare capacity do we need for failures?

## Sources

- Track 1 brief (PDF) and the full deck in `data/`
- [Czaja107/chiplet-thermal-gui](https://github.com/Czaja107/chiplet-thermal-gui)
- [Epoch AI: Trends in ML hardware](https://epoch.ai/blog/trends-in-machine-learning-hardware) · [compute doubling every 2.2 years](https://epoch.ai/data-insights/peak-performance-hardware-on-different-precisions)
- [HPCwire: IBM sets 2029 target for fault-tolerant quantum computing](https://www.hpcwire.com/2025/06/10/ibm-sets-2029-target-for-fault-tolerant-quantum-computing/)
- [Google Sycamore supplementary information (refrigerator power)](https://arxiv.org/pdf/1910.11333)
- `README_QUANTUM.md` and `quantum_arch/example_outputs/` in this repo (team's quantum simulator)
- [TrendForce: Rubin and Feynman roadmap](https://www.trendforce.com/news/2025/03/19/news-gtc-2025-nvidia-unveils-more-on-rubin-gpus-announces-feynman-for-2028-in-roadmap-update/)
