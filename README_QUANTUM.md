# Quantum Architecture Simulator (`quantum_arch`)

A simulator for quantum processors **together with the classical hardware around
them**, built on the idea behind the chiplet thermal studio: describe a system,
compute the heat it injects, and see whether the cooling scheme holds. Here the
"chiplets" are qubit arrays, cryogenic controllers, decoders, CPUs and GPUs, and
the "package" is a dilution refrigerator whose five stages (50 K down to 10 mK)
have cooling powers that differ by six orders of magnitude.

This version is set up for designing **the data centre of 2035**: all hardware
defaults (quantum and classical) are *mid-2030s scenarios*, with the October-2026
state kept only as a calibration anchor (see [Profiles](#hardware-profiles-today-is-an-anchor-2035-is-the-default)).
It also contains a hybrid CPU + GPU + QPU scheduler model
([Hybrid data centre](#hybrid-data-centre-gpu-only-augment-replace)).

For one architecture description it reports three things:

| | What you get |
| --- | --- |
| **Computing power** | physical error budget, error-suppression factor Λ, code distance, logical qubits, logical clock, **rQOPS**, time to solution of concrete workloads |
| **Energy** | power at three explicit boundaries (QPU module, complete computer, facility), energy per logical operation, energy to solution against a classical alternative at the same boundary |
| **Heat scheme** | per-stage heat load by source (cable conduction, attenuators, cold electronics, decoders) against cooling capacity, stage temperatures, fridges needed, spatial temperature maps of the cold electronics and the qubit chip |

```bash
python -m pip install -r requirements.txt            # numpy, scipy, matplotlib (+ PySide6 for the chiplet GUI)
python -m quantum_arch list                           # examples, profiles, catalogs
python -m quantum_arch evaluate dc2035_cat_40k --out out/cat40k
python -m quantum_arch compare dc2035_sc_surface_300k dc2035_cat_40k dc2035_ions_40k dc2035_atoms_surface_1m dc2035_photonic_6m --out out/cmp2035
python -m quantum_arch datacenter dc2035_research --out out/dc      # gpu_only vs augment vs replace + break-even
python -m quantum_arch calibrate --out out/cal                      # today profile against published power figures
python -m quantum_arch baselines                                    # LLM-inference joules per token, module/system/facility
python -m quantum_arch annealer --profile today --p-success 0.01    # annealers are a separate class (own metrics)
python -m quantum_arch sweep sc_rt_direct_100q --min 10 --max 1e5 --out out/sweep
python -m pytest tests                                # 73 tests
```

Reports from the bundled examples are in [quantum_arch/example_outputs/](quantum_arch/example_outputs/).
No HotSpot binary is needed: the chiplet GUI's solver assumes temperature-independent
materials, which fails at cryogenic temperatures (silicon conducts 10⁹ times better
at 25 K than at 10 mK), so `quantum_arch` has its own solver for that regime.

## Read this first: terminology and what is NOT claimed

- **Power (W) is a rate; energy (J, kWh) = average power × time.** A 12.5 kW machine that
  finishes in a tenth of the time uses less energy per answer. **Temperature does not specify
  electricity consumption**: a 10 mK chip sits behind a refrigerator that draws kilowatts,
  and a quantum system drawing 12.5 kW does not deposit 12.5 kW into its millikelvin stage.
- **Three measurement boundaries, never mixed** (every number in a report names its boundary):

  | boundary | name in the code | contains | does not contain |
  | --- | --- | --- | --- |
  | 1. processor / module | `boundaries.module` | for a QPU: module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat; for a GPU: the accelerator module (`tdp_w`). The cold-stage heat load is reported beside it as *thermal* power. | cryostat compressors, host servers, cooling plant |
  | 2. complete computer / server | `total_power_w`, `power_w`, "system" | cryostat wall power, room-temperature control, decoders, host, support apparatus; for GPUs: modules × `system_overhead_ratio` (CPUs, DRAM, NICs, fans, PSU losses) | facility cooling, networking, building |
  | 3. complete facility | `facility_power_w`, "facility" | `(system + network/support) × PUE` | – |

  The audit fixed three places that blurred these: the cryostat's installed wall power (compressors)
  is system-level and its heat rejection is in PUE (not added twice); supply power of electronics *inside*
  the fridge is now a system consumer (it used to be missing); and the room-temperature "apparatus" of
  ions and atoms is split into module-level (lasers, optics, traps) and support-level (vacuum, chillers, racks).
  The classical alternative in a workload comparison is costed at the same boundary as the quantum energy.
- **Physical versus logical qubits.** Qubit counts are not comparable across platforms like core
  counts. Compare logical qubits, logical error rates, reliable operation counts, execution speed,
  data-movement / I/O overhead and **whole-system energy per useful answer**.
- **There is no meaningful conversion such as "1 QPU = N GPUs"**: none exists in this package, and no law says when
  quantum replaces GPU work. The only comparison made is **energy and time per accepted answer** for the
  *same problem, accuracy, success probability and required outputs*, including preparation, repetitions,
  classical support and cooling. Ordinary AI (training, LLM inference) and dense matrix multiplication
  have **no** quantum counterpart in this package: loading the data and reading the result out costs at
  least as much as the classical computation (see the `qla_*` workloads, which charge that overhead
  explicitly and set `advantage_claimed = false`).
- **Results such as Google's "Quantum Echoes" (a particular out-of-time-order-correlator calculation on
  Willow, about 2 hours against an estimated 3.2 years on Frontier, roughly 13,000×) are not energy
  comparisons**: the baseline is an estimate of classical runtime for that one calculation, nothing was
  metered, and it says nothing about general computing, AI or efficiency.
- **Annealers are a different class**: special-purpose samplers for optimisation problems, not universal
  gate-based QPUs. They have no logical qubits and no rQOPS and live in their own module with their own
  metrics. They are never mixed into rQOPS or logical-qubit comparisons.

## Hardware profiles: `today` is an anchor, 2035 is the default

| profile | meaning |
| --- | --- |
| `today` | October-2026 calibration anchor (published power figures; error rates in the range of 2024-26 demonstrations). Not a design basis. |
| `projected` | the original near-term scenario, kept working unchanged |
| `mid2030s_low` / `mid2030s` / `mid2030s_high` | **scenarios** for the mid-2030s: slow / base / fast progress. *Scenario, not forecast.* `mid2030s` (base) is the **default for new architectures** and for the bundled 2035 examples. |

A profile changes qubit error rates and times, the power of the apparatus per qubit, cryo-CMOS and
amplifier power, room-temperature channel power, readout multiplexing, the cryostat platform
(`dilution_2035`, Bluefors-KIDE-class) and its wall power, and the classical devices (`gpu_2035`,
`cpu_2035`, `fpga_2035`, decoder ASICs, with `_low` / `_high` variants resolved from the profile).
The rationale, anchors and verification level of every group are in
[`data/scenarios_mid2030s.json`](quantum_arch/data/scenarios_mid2030s.json); each profile also carries a
`profile_note` naming its sources. **Every catalog number has a source or is marked "assumption"**
(a test enforces that each entry carries one of the two). Company roadmaps (IBM Starling 2029 / Blue Jay
2033+, Quantinuum Apollo 2029, IonQ 2030, Pasqal, QuEra, Atom Computing, Alice & Bob, PsiQuantum) are
quoted as *targets*, not delivered results.

Error suppression Λ (surface code on that platform) per scenario: superconducting 1.9 today → 4.0 / 12.7 / 27.7;
cat qubits 0.95 → 2.8 / 8.1 / 24.5; photonics (coarse) 0.17 → 1.2 / 3.1 / 6.7; trapped ions 4.6 → 13 / 43 / 94.

GPU modules (rated power, not measured): H200 700 W, B200 1.0 kW, MI355X 1.4 kW today (confirmed or
agreed by several sources); mid-2030s accelerator module 4.0 / 5.0 / 6.5 kW with 48 / 96 / 190 TB/s of HBM
(about 75 W per HBM4 stack today to ~150 W per HBM6/7-class stack in the base scenario: KAIST's *hypothetical*
roadmap, not a vendor plan), server overhead ×1.5 / 1.35 / 1.25 (DGX B200 today: ×1.79 = 14.3 kW / 8 kW), racks
toward 0.5-1 MW (NVIDIA Rubin Ultra Kyber about 600 kW planned for 2H 2027; Google > 500 kW by 2030; OCP 1 MW).
LLM inference energy at the system boundary, 70B-class model, matched latency SLO, utilisation 70 %:
B200 0.152 J/token, 2035 slow / base / fast 0.085 / 0.048 / 0.029 J/token.

## What the first results say

These come from the bundled examples with the catalog's parameters, so read them as a
demonstration of the method, not as predictions.

**Wiring and cryostat limits (unchanged by the 2035 work, `today` / `projected` profiles).**
- **The wiring wall comes first.** With one 0.085" stainless coax per control line, a
  single XLD-class fridge serves about **64 transmons** (limit: the 200 µW cold plate). Thinner
  0.047" coax gives ~124; moving control into 4 K cryo-CMOS gives ~374, then the 1.5 W
  4 K stage (4 mW/qubit) is the limit; with a 10× larger cryoplatform, ~3,700.
- **Heat sets the fridge count, and the fridge sets the power.** A commercial fridge draws
  roughly constant power, so a processor needing 27 units draws 27× as much, while the
  Carnot floor for the same heat is 200–1000× lower than the installed power.
- **Error-corrected computing needs both quality and scale.** Today's superconducting
  parameters give Λ ≈ 1.9, and a 10⁻¹² logical error then needs distance ~90: no logical
  qubits from 1,000 physical ones. The projected profile (Λ ≈ 6.6) gets 18 logical qubits
  and 7.5·10⁵ rQOPS out of 100,000 physical qubits at d = 31, for 2.7 MW.
- **Slow modalities trade logical clock for gate quality.** Ions and neutral atoms reach
  higher Λ but their syndrome cycle is ~1–2 ms against 0.8 µs.
- **Decoders are real hardware.** 100,000 qubits at a 0.77 µs cycle is 6.5·10¹⁰ syndrome
  bits/s and ~2·10¹³ decoder op/s.

**2035 QPUs, base scenario (`quantum_arch/examples/dc2035_*.json`, 300 k transmons / 40 k cat qubits / 40 k ions /
1 M atoms / 6 M photonic generators).** System boundary unless stated; every row is a SCENARIO.

| QPU | Λ | logical qubits (target 1e-12) | system power | facility power (PUE 1.15) | 100-logical-qubit chemistry job (1e8 Toffoli) |
| --- | --- | --- | --- | --- | --- |
| superconducting surface code, 300 k | 12.7 | 99 (d = 23) | 2.91 MW | 3.35 MW | 11.8 min, 571 kWh |
| cat qubits, repetition code, 40 k | 8.1 | 263 (d = 27) | 270 kW | 310 kW | 3.8 min, 17 kWh |
| trapped ions, qLDPC, 40 k | 35 | 777 (d = 12) | 352 kW | 404 kW | 2.8 days, 23.9 MWh |
| neutral atoms, surface code, 1 M | 8.0 | 240 (d = 27) | 517 kW | 594 kW | 3.2 days, 39.6 MWh |
| photonic fusion network (coarse), 6 M | 3.1 | 124 (d = 53) | 6.0 MW | 6.9 MW | 2.9 h, 21.8 MWh |

The superconducting row is cryostat-dominated (98 % of the power is cryostat wall power for 112 unit-equivalents, a single
cryoplatform assumed: no cryogenic interconnect is modelled); cat qubits look much better because their code needs
~20× fewer physical qubits, which is exactly what the coarse cat model assumes (largest uncertainty, see below).

## Calibration against published power figures

`python -m quantum_arch calibrate` (also [example_outputs/calibration](quantum_arch/example_outputs/calibration/calibration.md);
a test pins it). Published figures are a **mix of ratings, maxima, averages and vendor claims**, not matched
benchmarks; "anchored" rows hold by construction.

| reference (boundary) | published | model, `today` | note |
| --- | --- | --- | --- |
| Quantinuum Helios, 98 qubits (base unit, no support infrastructure) | < 40 kW (vendor page) | 34 kW (0.85) | old default 3 kW + 40 W/qubit = 6.9 kW was 5.8× too low. Oracle announcement: about 60 kW without HVAC (discrepancy, scope differs) |
| QuEra Aquila as fitted in PaQit (arXiv:2608.02815) | 6.92 kW + 0.308 W/qubit | same | old default 5 kW + 1.5 W/qubit was 23 % low at 256 qubits and 2× high at 10,000 |
| D-Wave Advantage2 (system) | 12.5 kW "average power" | 12.5 kW | anchored; 12.5 kW = 208 V × 60 A, so it may be a circuit rating |
| Quandela Ascella, 6 qubits, cryostat in the rack | 3 kW | 3 kW | anchored |
| Pasqal "about 2.6 kW" | secondary article only | 6.9 kW at 100 atoms | **not confirmed**; Pasqal's brochure lists 3.5 kW *average laser power alone* (10 kW installed), 380 V 32 A supply |
| DGX B200 (system, max) | 14.3 kW | 14.3 kW | anchored: overhead ratio 1.79 derived from it; table header in NVIDIA's guide is ambiguous |
| 8 × MI355X GPUs only | 11.2 kW | 11.2 kW | server around them adds power, not stated |
| H200 SXM / MI350X / MI355X module | 700 W / 1.0 kW / 1.4 kW | same | |

## Verification of the overview note (October 2026)

The note `notes/quantum_hardware_overview_2026-10.md` is another model's summary. Checked against
primary or reputable sources during the audit (details and URLs in [`data/references.json`](quantum_arch/data/references.json)):

- **Confirmed:** Helios "less than 40 kW" (base unit, support excluded; vendor page); D-Wave 12.5 kW (data sheet);
  Quandela Ascella 3 kW (vendor; includes its built-in cryostat); DGX B200 up to 14.3 kW (NVIDIA guide, ambiguous table
  header); H200 up to 700 W (NVIDIA); MI355X up to 1.4 kW and MI350X 1.0 kW (agreeing secondary sources); the
  MLPerf 97 / ~100 / 119 % figures (AMD's own single-node comparison, throughput only, not independently reproduced);
  Quantum Echoes ~13,000× (Google/Nature claim, estimated baseline, not an energy comparison); IBM Nighthawk (120 qubits),
  Atom Computing AC1000.
- **Discrepancy / incomplete:** Helios is also reported at **about 60 kW without HVAC** in the Oracle announcement (the
  overview omits it). **"Pasqal about 2.6 kW" could not be confirmed** from a primary source.
- **Partly confirmed:** IonQ–Oxford Ionics (single secondary source), D-Wave–Quantum Circuits (agreement announced
  Jan 2026, closing not verified), IQM (Spark, Radiance found; Garnet only in an older report).
- **Not verified:** Rigetti Cepheus, Origin Wukong, Xanadu Aurora, Intel Tunnel Falls, Diraq, Quantum Brilliance, QuEra
  Gemini, Pasqal Orion generation, Alice & Bob Boson; the Fermilab "Colossus" platform and a KIDE power draw (nothing found).
- The "80 workstations" and "18 H200 modules" statements are correct arithmetic (40 kW / 500 W; 12.5 kW / 700 W) and the
  overview itself says they are not capability equivalences.

## Modalities

| modality (`modality=`) | model | status |
| --- | --- | --- |
| `superconducting` transmons | surface or qLDPC code, cryo-CMOS or room-temperature control | Krinner-validated cabling; mid-2030s scenarios |
| `spin_silicon` | surface code, cryo-CMOS | scenarios |
| `trapped_ion` | QCCD, qLDPC possible (long-range) | power calibrated to Helios; scenarios |
| `neutral_atom` | tweezer arrays, surface or qLDPC | power calibrated to Aquila fit; scenarios |
| `cat_superconducting` (new) | bias-preserving **repetition code**, 2d − 1 qubits per logical qubit, uncorrectable residual bit-flip floor | anchored to AWS Ocelot / Alice & Bob / Gouzien et al.; **coarse, assumption-heavy** |
| `photonic` (new) | **fusion-network code** (not a surface code), room-temperature optics + cryogenic detectors in cryo cabinets | today anchored to Quandela Ascella power; **fusion overhead and clock are assumptions** |
| annealers (`quantum_arch.annealer`) | samples/s, time-to-target, energy-to-target at module/system/facility; no QEC, no rQOPS | D-Wave Advantage2 power anchored; separate class |
| diamond defects, topological | **not modelled**: see [`data/excluded_modalities.json`](quantum_arch/data/excluded_modalities.json) for why | |

## How a system is described

An architecture is a JSON file ([examples](quantum_arch/examples/)); anything omitted takes
the default from `quantum_arch/architecture.py`.

```json
{
  "name": "dc2035_cat_40k",
  "modality": "cat_superconducting",  // superconducting | spin_silicon | trapped_ion | neutral_atom | cat_superconducting | photonic
  "profile": "mid2030s",              // today | projected | mid2030s_low | mid2030s | mid2030s_high   (default mid2030s)
  "scheme": "cryo_cmos_4k",           // control and wiring scheme of that modality
  "n_qubits": 40000,
  "qubit_overrides": {},               // any modality parameter
  "scheme_overrides": {},              // any scheme parameter (line counts, electronics power)
  "cryostat": {"capacity_scale": 10.0},
  "qec": {"code": null, "target_logical_error": 1e-12, "decoder": null, "decoder_device": "auto:fpga"},
  "classical": [{"role": "optimizer", "device": "auto:gpu", "count": 4, "utilisation": 0.3}],
  "facility": {"pue": 1.15, "network_support_w": 0, "include_server_overhead": false},
  "workloads": ["chemistry_small", "qla_scalar_explicit_1m"]
}
```

`code: null` takes the modality's default code (surface, `cat_repetition`, `fusion_network`); `auto:<role>`
devices (`cpu|gpu|fpga|asic_rt|asic_4k`) follow the profile (B200-class today, `gpu_2035` for mid-2030s);
`facility.include_server_overhead` adds the DRAM/NIC/fan/PSU power of classical servers to the system boundary.

Catalogs live in [quantum_arch/data/](quantum_arch/data/) as plain JSON, each entry with its
source or a statement that it is an assumption: `modalities.json`, `fridges.json`, `codes.json`,
`decoders.json`, `classical.json`, `workloads.json`, plus the new `annealers.json`, `baselines.json`,
`references.json` (published figures and the verdict on each overview claim), `scenarios_mid2030s.json`
(rationale) and `excluded_modalities.json`.

## The models

**Error budget** (`qec.py`). Syndrome cycle = 4·t₂q + 2·t₁q + t_meas + t_reset + overhead
(overhead carries shuttling in ions and atoms). Effective physical error
p = e₂q + ¼(2e₁q + e_meas + e_reset) + ¼e_idle, with e_idle from T₂ over the non-gate part of the
cycle. A code turns p and a distance d into a logical error per round,
p_L = A (p/p_th)^e(d) (surface code: A = 0.1, p_th = 1 %, e = (d+1)/2), plus for biased-noise codes
the uncorrectable floor (2d−1)·p_bitflip, and into qubits per logical qubit (2d²−1 for the rotated surface
code, 2d−1 for the cat repetition code, 6d² for the fusion network). Capability mode finds the smallest d
meeting the target, then logical qubits (after layout overhead and a factory share), logical clock
1/(d·t_cycle) and **rQOPS** = logical qubits × clock. Workload mode plans a Toffoli-counted
algorithm: smallest d whose total volume error fits the budget, CCZ factories from the spare
qubits, and a runtime bounded by factory throughput or by the control reaction time
(measurement + link + decode latency). The acceptance probability of a job is 1 − total logical error.

**Wiring and cryostat** (`wiring.py`, `cryo.py`, `materials.py`). Passive conduction is the
integral of k(T) over each cable segment with every stage thermalising the line,
`Q = A/L ∫k dT`, from tabulated conductivities of stainless steel, CuNi, NbTi, copper, PTFE,
polyimide and silica. Active heat follows the signal: launched power is attenuated stage by
stage and each attenuator dissipates its share; cable loss is split between the two end stages;
DC lines dissipate I²R. Stages have cooling curves Q = a(T^α − T_base^α) anchored at measured
points. The wall-plug figure is `units × unit power`, because a dry fridge's compressor runs
whatever the load; the Carnot floor Σ Q(300/T − 1) is reported beside it. Cold electronics
(cryo-CMOS, HEMTs, decoders at 4 K) enter as stage loads *and* as a system consumer (their supply power).

**Classical hardware** (`classical.py`, `workloads.py`, `baselines.py`). Decoder algorithms need an assumed
number of operations per syndrome bit per round; the model sizes a bank of the chosen device
to sustain that, powers it linearly between idle and TDP, adds its decode latency to the
reaction time, and flags a bank that cannot keep up. Variational workloads run on the bare
qubits, checked against a circuit-fidelity floor, with the optimiser step on the architecture's
GPUs; the classical alternative is exact state-vector simulation on the profile's reference GPU node, at the
same boundary as the quantum energy. `baselines.py` provides the matched-quality GPU baselines:
**LLM inference** (joules per token at the same model and latency SLO, anchored to AMD's MLPerf 6.0
Llama 2 70B Server throughput, memory-bandwidth-scaled, compute-capped, idle power paid), **LLM training to a
fixed quality target** (6·N·D FLOPs at an MFU: time and energy) and dense matrix multiplication.

**Quantum linear algebra with explicit I/O overhead** (`workloads.py`, type `quantum_linear_algebra`). An
HHL/QSVT-style solve costs: block-encoding queries (2κ ln(2/ε)), data loading (N × bits Toffoli per run unless the
input is an efficient oracle), and read-out (amplitude estimation, 1/ε coherent rounds for one number; about N/ε² runs
for the full vector). The default is *no quantum advantage claimed*: for N = 2²⁰ the model finds the quantum solve costs
10¹¹ (scalar) to 10¹⁹ (full vector) times the energy of conjugate gradient on a GPU; only the structured, implicit-input,
scalar-output regime is left open, and even there no classical comparison is made.

**Annealers** (`annealer.py`). Samples per second (anneal + readout), programming time, system power at the three
boundaries, and `solve_cost`: reads needed for a stated per-read success probability and confidence, time-to-target and
energy per accepted solution including the classical host. The per-read success probability is a property of the problem
class and must come from a benchmark; nothing asserts an advantage over classical solvers.

**Spatial maps** (`thermal2d.py`). One conducting layer meshed in square cells, k(T) from the
same tables (harmonic-mean faces), heat leaving through a boundary contact to the stage with
h(T) = h₀(T/T₀)ⁿ, Picard iteration, sparse direct solve. Power maps accept the same
"uniform plus Gaussian hot spot" shape as the challenge's workload generator. Total heat out
equals heat in (reported per plate).

## Hybrid data centre: GPU-only, augment, replace

`quantum_arch/datacenter.py` models a facility of CPUs, GPUs and QPUs with a classical scheduler. For every job class
it compares **queue time + preparation/transfer + computation (+ retries) + measurement/post-processing**, subject to
accuracy (acceptance probability from the logical-error budget × the algorithm's *mapping quality*) and energy, routes
the job to a GPU partition or a quantum pool, and reports for three scenarios on the **same** workload mix:
**GPU-only**, **AUGMENT** (keep the GPUs, add quantum systems) and **REPLACE** (remove a fraction of the GPUs, add quantum
systems). Outputs: capacity lost or gained (largest sustainable demand and ordinary-AI headroom), queue and turnaround
per class, power at the three boundaries, facility energy per accepted answer per class and per unit of accepted
work, and the **break-even movable-work fraction** (sweep over the share of demand that is quantum-eligible *and*
mapped). The per-job feasibility check (logical error budget, runtime, energy) is delegated to `quantum_arch.evaluate`
(`datacenter.quantum_job_check`). Configs: [examples/datacenter/](quantum_arch/examples/datacenter/), results in
[example_outputs/datacenter/](quantum_arch/example_outputs/datacenter/).

Headline results of the bundled 2035 examples (1,600 GPU modules of the base scenario, 70 % utilisation, PUE 1.15, network
+8 %; a conservative 300 k-transmon surface-code QPU and a D-Wave-class annealer; **all job costs and mapping qualities are
illustrative assumptions**). Capacity = largest demand the facility sustains at the 85 % utilisation cap, same mix,
relative to GPU-only; energy = facility joules per baseline GPU-second of accepted work (below 1 is better):

| facility mix | movable share of demand | AUGMENT capacity / energy | REPLACE 50 % of GPUs: capacity / energy / demand served |
| --- | --- | --- | --- |
| AI-serving-dominated (`dc2035_ai_serving`) | 1.9 % | 1.02× / 1.33 | **0.51× / 1.54 / 62 %** |
| research mix, superconducting QPU (`dc2035_research`) | 23 % | 1.26× / 1.19 | **0.63× / 1.24 / 76 %** |
| research mix, cat-qubit QPU (`dc2035_research_cat`) | 23 % | 1.26× / 0.90 | **0.63× / 0.87 / 76 %** |

- **Replacing GPUs only helps if enough work can move; otherwise ordinary AI capacity drops.** The closed form
  (`replace_capacity_ratio`) is (1 − removed)/(1 − moved): replacing half the GPUs breaks even on capacity at about 50 %
  movable work (57 % in the research mix once failures, retries and finite quantum capacity are included; 94 % in the AI
  mix, where one QPU cannot absorb that much). **Augmenting is the more plausible first step.**
- The energy side is a separate break-even: a MW-scale cryogenic QPU draws almost its busy power while idle (standby
  2.87 of 2.91 MW), so a lightly used superconducting QPU *raises* facility energy per answer (augment 1.19-1.33×) until about
  50 % of the work is movable; the cat-qubit QPU (0.27 MW) pays off from about 9 % movable work; REPLACE reaches energy
  parity at about 41 % (superconducting) or 10 % (cat). Utilisation, not peak efficiency, decides.
- The report prints, per eligible class, the **classical cost above which quantum wins on energy** (here 121 GPU-module hours per
  job for the superconducting QPU, 4.3 for the cat QPU, against an assumed 768): the conclusion is carried by that assumption and
  by the existence of a validated quantum implementation of the job, not by a hardware ratio.
- Queue model: Poisson arrivals, each GPU class on a proportional partition (Erlang-C), quantum pool M/G/c (Allen-Cunneen),
  one job per quantum system. Quantum systems draw busy power while running and standby power otherwise.

For other tools (for example a local "replace/augment offload" variant), the clean entry points are
`datacenter.offload_decision(job, quantum_architecture, ...)` (one job: route, turnaround and facility energy of both options, with the
feasibility check and reasons), `datacenter.quantum_job_check(arch, workload)`, `datacenter.run_datacenter(config)`,
`datacenter.movable_sweep(config)` / `datacenter.break_even(config)` and the closed forms `replace_capacity_ratio` /
`break_even_moved_fraction`. They take and return plain dictionaries.

## Validation

`tests/test_quantum_arch.py` pins the physics to published data and to analytic limits:

- the passive load of a 0.085" stainless coax through a Bluefors XLD400 agrees with
  Krinner et al., EPJ Quantum Technol. 6, 2 (2019) at every stage: 26.5 mW / 0.39 mW /
  2.1 µW / 0.32 µW / 3.4 nW against their predicted 24–27 mW / 0.4–1.7 mW / 1.9–2.1 µW /
  0.33–0.43 µW / 4 nW;
- their 10 dBm attenuator experiment (10 mW, 100 µW, 1 µW on 4 K, cold plate, MXC);
- conservation of launched signal power, of heat in the 2D solver, and of the cooling-curve
  round trip; uniform power gives the uniform solution of the contact law; better conductors
  lower the peak;
- the scaling result above is reproduced from first principles (4 K limit = 1.5 W / 4 mW).

`tests/test_quantum_arch_2035.py` adds: ordering of the low/base/high scenarios, the three boundaries
(module < system < facility, cold-stage heat is thermal and not wall power, PUE applied once), the calibration table,
the cat bit-flip floor and the 2d − 1 qubit count (Ocelot: 9 qubits at d = 5), the separate annealer class, the I/O overhead
and `advantage_claimed = false`, the GPU baselines (J/token boundaries, MLPerf anchor), Erlang-C values, the closed-form replace limit,
energy conservation across job classes, the qualitative replace-versus-augment result, the absence of any "1 QPU = N GPU"
statement, and the hill-facing API (`Architecture`, `evaluate`, `report.to_dict`).

The stage specs in `fridges.json` for the XLD are Krinner's measured Table 1; the 2035 platform is a scenario.

## Assumptions and limits

Read these before quoting a number. **The mid-2030s numbers are scenarios; the largest uncertainties are listed first.**

- **Cat-qubit and photonic overhead** (code threshold, 2d − 1 and 6d² qubits per logical qubit, factory cost, 1 µs fusion
  layer clock, bit-flip floor of 1e-16 per qubit-cycle): coarse, anchored only loosely (Ocelot, Alice & Bob, Gouzien et al.,
  Bartolucci et al.). A circuit-level or fusion-lattice simulation is needed before any design decision. Dual-rail
  qubits are not modelled.
- **Cryoplatform scaling**: a 300 k-transmon machine is treated as one 112-unit-equivalent platform (wall power
  scales linearly; heat and 4 K budgets are met by assumption, no cryogenic interconnect or helium inventory). `dilution_2035`
  is the XLD curves scaled to Bluefors KIDE's published > 3 mW at 100 mK and a modelled 6 W at 4 K; its 30 kW wall power is an
  assumption. Cryo-CMOS power per qubit (1 mW base) is an assumption.
- **Ion and atom power per qubit at 10⁴-10⁶ qubits** (Helios and Aquila anchors are single machines of 98-256 qubits); the
  split between module-level apparatus and support is an assumption except the 3.5 kW Pasqal laser share.
- **GPU module power, HBM bandwidth and efficiency in 2035** (Rubin Ultra rumours, KAIST's hypothetical HBM roadmap); LLM
  tokens/s per module follows memory bandwidth from one AMD-reported MLPerf anchor.
- **Job classes of the data-centre model**: classical cost at matched accuracy, mapping quality, share of demand are inputs,
  not measurements; the quantum job is one of the catalog workloads (`chemistry_small` = 100 logical qubits, 1e8 Toffoli).
- **Qubit parameters are illustrative round numbers** in the range of 2022–26 demonstrations, not a specific device.
- **Resource estimates are closed-form** (Fowler-style surface-code scaling, a fit for the bivariate-bicycle codes), not
  circuit-level simulations. They do not include yoked codes or magic-state cultivation, so qubit counts for Shor are
  conservative against recent papers (Gidney 2025: under a million noisy qubits in under a week).
- **NbTi and PTFE below 4 K use a linear extrapolation** (an upper bound), and cables are assumed
  fully thermalised at every stage. For stainless lines this matches Krinner's predictions; for
  their NbTi output line the model underestimates by about 2× at the cold plate.
- **Loads are budgeted at the target temperatures.** An overloaded stage reports the temperature it
  would settle at, but that is not fed back into cable conduction, so runaway is understated;
  act on the overload flag and the fridge count.
- **Steady state only**: no cooldown, transients, vibration, stray radiation or helium-3 inventory.
- **Classical devices are power-and-throughput models.** Their own die temperatures at room
  temperature are not simulated; the chiplet studio and HotSpot remain the tool for that.
- Several resource counts for Shor and FeMoco come from secondary summaries and are marked in `workloads.json`.
- **Behaviour changes of this version**: ion and atom `today` power defaults were recalibrated (see the calibration table; this
  also changes `ion_*` and `atoms_*` example outputs); the default profile is `mid2030s`; power breakdown keys were renamed
  ("lasers, vacuum, apparatus" became "QPU apparatus" and "support apparatus"); cold-electronics supply power and server
  overhead (opt-in) are system consumers; the classical energy alternative is at the system boundary (it used to be module
  power only, which flattered the classical side by up to 1.8×).

## Layout

```
quantum_arch/
  materials.py    k(T) tables and ∫k dT
  wiring.py       cables, passive conduction, attenuator and DC dissipation
  cryo.py         stage cooling curves, heat budget, fridge count, wall power, Carnot floor
  qec.py          error budget, codes, capability (rQOPS), workload planning
  classical.py    CPU / GPU / FPGA / ASIC sizing and power, decoder latency, scenario resolution
  workloads.py    time and energy to solution, classical comparison, quantum linear algebra with I/O overhead
  baselines.py    GPU baselines: LLM inference J/token, training to a quality target, dense matmul
  annealer.py     annealers as a separate class (samples/s, time- and energy-to-target)
  datacenter.py   hybrid CPU+GPU+QPU scheduler model: gpu_only / augment / replace, break-even, offload_decision
  calibration.py  model against published power figures
  thermal2d.py    spatial heat spreading with k(T) and boundary resistance
  architecture.py the description, defaults, profiles, power boundaries and evaluate()
  report.py       markdown, JSON, figures; comparisons and sweeps
  sweep.py        qubit-count sweeps and the single-fridge limit
  data/           catalogs (JSON)      examples/ (+ examples/datacenter/)      example_outputs/
tests/test_quantum_arch.py  tests/test_quantum_arch_2035.py
```
