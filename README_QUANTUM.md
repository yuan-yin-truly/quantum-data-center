# Quantum Architecture Simulator (`quantum_arch`)

A simulator for quantum processors **together with the classical hardware around
them**, built on the idea behind the chiplet thermal studio: describe a system,
compute the heat it injects, and see whether the cooling scheme holds. Here the
"chiplets" are qubit arrays, cryogenic controllers, decoders, CPUs and GPUs, and
the "package" is a dilution refrigerator whose five stages (50 K down to 10 mK)
have cooling powers that differ by six orders of magnitude.

For one architecture description it reports three things:

| | What you get |
| --- | --- |
| **Computing power** | physical error budget, error-suppression factor Λ, code distance, logical qubits, logical clock, **rQOPS**, time to solution of concrete workloads |
| **Energy** | wall-plug power split by consumer, energy per logical operation, energy to solution against a classical alternative |
| **Heat scheme** | per-stage heat load by source (cable conduction, attenuators, cold electronics, decoders) against cooling capacity, stage temperatures, fridges needed, spatial temperature maps of the cold electronics and the qubit chip |

```bash
python -m pip install -r requirements.txt            # numpy, scipy, matplotlib (+ PySide6 for the chiplet GUI)
python -m quantum_arch list                           # examples and catalogs
python -m quantum_arch evaluate sc_rt_direct_100q --out out/sc100
python -m quantum_arch compare sc_rt_direct_100q sc_cryo_cmos_100k spin_cmos_10k ion_qccd_100q atoms_surface_10k --out out/cmp
python -m quantum_arch sweep sc_rt_direct_100q --min 10 --max 1e5 --out out/sweep
python -m pytest tests                                # 29 tests
```

Reports from the bundled examples are in [quantum_arch/example_outputs/](quantum_arch/example_outputs/).
No HotSpot binary is needed: the chiplet GUI's solver assumes temperature-independent
materials, which fails at cryogenic temperatures (silicon conducts 10⁹ times better
at 25 K than at 10 mK), so `quantum_arch` has its own solver for that regime.

## What the first results say

These come from the bundled examples with the catalog's illustrative parameters, so
read them as a demonstration of the method, not as predictions.

- **The wiring wall comes first.** With one 0.085" stainless coax per control line, a
  single XLD-class fridge serves about **64 transmons** (limit: the 200 µW cold plate). Thinner
  0.047" coax gives ~124; moving control into 4 K cryo-CMOS gives ~374, then the 1.5 W
  4 K stage (4 mW/qubit) is the limit; with a 10× larger cryoplatform, ~3,700.
- **Heat sets the fridge count, and the fridge sets the power.** A commercial fridge draws
  roughly constant power, so a processor needing 27 units draws 27× as much, while the
  Carnot floor for the same heat is 200–1000× lower than the installed power.
  The gap is the room for better cryocoolers.
- **Error-corrected computing needs both quality and scale.** Today's superconducting
  parameters give Λ ≈ 1.9, and a 10⁻¹² logical error then needs distance ~90: no logical
  qubits from 1,000 physical ones. The projected profile (Λ ≈ 6.6) gets 18 logical qubits
  and 7.5·10⁵ rQOPS out of 100,000 physical qubits at d = 31, for 2.7 MW.
- **Slow modalities trade logical clock for gate quality.** Ions and neutral atoms reach
  higher Λ but their syndrome cycle is ~1–2 ms against 0.8 µs, so the same code gives a
  logical clock a thousand times lower. They need no cryostat, so their power is lasers
  and apparatus.
- **Decoders are real hardware.** 100,000 qubits at a 0.77 µs cycle is 6.5·10¹⁰ syndrome
  bits/s and ~2·10¹³ decoder op/s, which the model maps onto FPGAs, GPUs or ASICs (placed
  at room temperature or at 4 K, where their power becomes part of the cryogenic heat load).

## How a system is described

An architecture is a JSON file ([examples](quantum_arch/examples/)); anything omitted takes
the default from `quantum_arch/architecture.py`.

```json
{
  "name": "sc_cryo_cmos_100k",
  "modality": "superconducting",      // superconducting | spin_silicon | trapped_ion | neutral_atom
  "profile": "projected",             // today | projected
  "scheme": "cryo_cmos_4k",           // control and wiring scheme of that modality
  "n_qubits": 100000,
  "qubit_overrides": {"err_2q": 4e-4},          // any modality parameter
  "scheme_overrides": {},                        // any scheme parameter (line counts, electronics power)
  "cryostat": {"capacity_scale": 10.0, "targets_k": {"MXC": 0.015}},
  "qpu_stage": "MXC",                 // where the qubits sit
  "qec": {"code": "surface", "target_logical_error": 1e-12,
          "decoder": "union_find", "decoder_device": "fpga_large", "decoder_location": "RT"},
  "classical": [{"role": "optimizer", "device": "gpu_h100", "count": 4, "utilisation": 0.3}],
  "workloads": ["shor_rsa2048", "vqe_50q"]
}
```

Catalogs live in [quantum_arch/data/](quantum_arch/data/) as plain JSON, each entry with its
source or a statement that it is an assumption: `modalities.json` (qubits, control schemes,
wiring), `fridges.json`, `codes.json`, `decoders.json`, `classical.json`, `workloads.json`.
Add a modality or a CPU/GPU by adding an entry.

## The models

**Error budget** (`qec.py`). Syndrome cycle = 4·t₂q + 2·t₁q + t_meas + t_reset + overhead
(overhead carries shuttling in ions and atoms). Effective physical error
p = e₂q + ¼(2e₁q + e_meas + e_reset) + ¼e_idle, with e_idle from T₂ over the non-gate part of the
cycle. A code turns p and a distance d into a logical error per round,
p_L = A (p/p_th)^((d+1)/2) (surface code, A = 0.1, p_th = 1 %), and into qubits per logical
qubit (2d²−1 for the rotated surface code). Capability mode finds the smallest d meeting the
target, then logical qubits (after layout overhead and a factory share), logical clock
1/(d·t_cycle) and **rQOPS** = logical qubits × clock. Workload mode plans a Toffoli-counted
algorithm: smallest d whose total volume error fits the budget, CCZ factories from the spare
qubits, and a runtime bounded by factory throughput or by the control reaction time
(measurement + link + decode latency).

**Wiring and cryostat** (`wiring.py`, `cryo.py`, `materials.py`). Passive conduction is the
integral of k(T) over each cable segment with every stage thermalising the line,
`Q = A/L ∫k dT`, from tabulated conductivities of stainless steel, CuNi, NbTi, copper, PTFE,
polyimide and silica. Active heat follows the signal: launched power is attenuated stage by
stage and each attenuator dissipates its share; cable loss is split between the two end stages;
DC lines dissipate I²R. Stages have cooling curves Q = a(T^α − T_base^α) anchored at measured
points. The wall-plug figure is `units × unit power`, because a dry fridge's compressor runs
whatever the load; the Carnot floor Σ Q(300/T − 1) is reported beside it. Cold electronics
(cryo-CMOS, HEMTs, decoders at 4 K) enter as stage loads.

**Classical hardware** (`classical.py`, `workloads.py`). Decoder algorithms need an assumed
number of operations per syndrome bit per round; the model sizes a bank of the chosen device
to sustain that, powers it linearly between idle and TDP, adds its decode latency to the
reaction time, and flags a bank that cannot keep up. Variational workloads run on the bare
qubits, checked against a circuit-fidelity floor, with the optimiser step on the architecture's
GPUs and the classical alternative costed as exact state-vector simulation on a B200-class node.

**Spatial maps** (`thermal2d.py`). One conducting layer meshed in square cells, k(T) from the
same tables (harmonic-mean faces), heat leaving through a boundary contact to the stage with
h(T) = h₀(T/T₀)ⁿ, Picard iteration, sparse direct solve. Power maps accept the same
"uniform plus Gaussian hot spot" shape as the challenge's workload generator. Total heat out
equals heat in (reported per plate).

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

The stage specs in `fridges.json` are Krinner's measured Table 1.

## Assumptions and limits

Read these before quoting a number.

- **Qubit parameters are illustrative round numbers** in the range of 2022–25 demonstrations,
  not a specific device. `projected` is a scenario of improved hardware, not a forecast, and it
  changes only the qubit parameters, not electronics power.
- **Fridge wall power (10 kW per XLD-class unit), line capacity per fridge, cryo-CMOS power per
  qubit, laser and apparatus power for ions and atoms, and decoder operation counts are
  assumptions.** The first two I could not source from a datasheet.
- **Resource estimates are closed-form** (Fowler-style surface-code scaling, a fit for the
  bivariate-bicycle codes), not circuit-level simulations. They do not include yoked codes or
  magic-state cultivation, so qubit counts for Shor are conservative against recent papers.
- **NbTi and PTFE below 4 K use a linear extrapolation** (an upper bound), and cables are assumed
  fully thermalised at every stage. For stainless lines this matches Krinner's predictions; for
  their NbTi output line the model gives 0.2 µW at the cold plate and 2 nW at the mixing chamber
  against their 0.29–0.39 µW and 12–23 nW (they bracket this with a non-thermalised dielectric),
  i.e. it underestimates NbTi lines by about 2× and 6–10× at those stages.
- **Loads are budgeted at the target temperatures.** An overloaded stage reports the temperature it
  would settle at, but that is not fed back into cable conduction, so runaway is understated;
  act on the overload flag and the fridge count.
- **Steady state only**: no cooldown, transients, pulse duty cycles beyond the averages given,
  vibration, stray radiation or helium-3 inventory. Multiple fridge units are counted for power,
  but coupling processors across fridges is not modelled.
- **Classical devices are power-and-throughput models.** Their own die temperatures at room
  temperature are not simulated; the chiplet studio and HotSpot remain the tool for that.
- Several resource counts for Shor and FeMoco come from secondary summaries and are marked
  "verify" in `workloads.json`.

## Layout

```
quantum_arch/
  materials.py    k(T) tables and ∫k dT
  wiring.py       cables, passive conduction, attenuator and DC dissipation
  cryo.py         stage cooling curves, heat budget, fridge count, wall power, Carnot floor
  qec.py          error budget, codes, capability (rQOPS), workload planning
  classical.py    CPU / GPU / FPGA / ASIC sizing and power, decoder latency
  workloads.py    time and energy to solution, classical comparison
  thermal2d.py    spatial heat spreading with k(T) and boundary resistance
  architecture.py the description, defaults and evaluate()
  report.py       markdown, JSON, figures; comparisons and sweeps
  sweep.py        qubit-count sweeps and the single-fridge limit
  data/           catalogs (JSON)      examples/   architectures      example_outputs/
tests/test_quantum_arch.py
```
