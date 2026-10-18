# spin_cmos_10k

Silicon spin qubits, 10,000 physical qubits, `projected` hardware profile. Control scheme: Cryo-CMOS controller at 4 K, flex cabling to the cold plate.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 2.6 µs |
| effective physical error p | 3.35e-03 |
| error suppression Λ = p_th/p (Rotated surface code) | 2.99 |
| code distance for target | 53 |
| logical qubits | 0 |
| logical clock | 0 Hz |
| rQOPS | 0 |
| logical error per op | n/a |
| peak physical 2-qubit gate rate | 5e+10 /s |

> No error-corrected computing: 10,000 physical qubits are fewer than one logical qubit at d=53 (5617 each, x2.0 layout)

## Energy

| consumer | power | share |
|---|---|---|
| cryostat (installed) | 700 kW | 99.2 % |
| room-temperature control electronics | 3.76 kW | 0.5 % |
| classical host / optimiser | 1.45 kW | 0.2 % |
| cold electronics supply (cryo-CMOS, amplifiers, cold decoders) | 90 W | 0.0 % |
| **total, complete computer (system boundary)** | **705 kW** |  |

Power at the three measurement boundaries (they are different quantities; never compare numbers across them):

| boundary | power | what it contains |
|---|---|---|
| 1. QPU module (electrical) | 90 W | module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat |
|    cold-stage heat load (thermal, not wall power) | 90 W | heat lifted by the cryostat stages: cable conduction, attenuators, cold electronics |
| 2. Complete computer (system) | 705 kW | everything above incl. cryostat compressors, room-temperature control, decoders, host; no facility cooling |
| 3. Facility (PUE 1.2) | 846 kW | (system + network/support) x PUE; includes heat rejection and chilled water |

Energy per physical 2-qubit gate (all qubits busy, system boundary): 1.41e-05 J.  Thermodynamic (Carnot) floor for the cryostat heat loads: 2.38 kW, against 700 kW installed.

## Heat scheme

Dry dilution refrigerator (XLD400-class): 7 unit(s) needed (7 for heat, 1 for 313 lines).

| stage | target | settles at | load | capacity | utilisation | largest sources |
|---|---|---|---|---|---|---|
| 50K | 45 K | 45 K | 16 mW | 300 W | 0% | digital_link 16 mW |
| 4K | 4.2 K | 11 K | 90 W | 15 W | 600% ⚠ | cryo-CMOS controller (gate DACs + MW + readout) 80 W, cryogenic RF amplifiers (reflectometry) 10 W, digital_link 571 µW |
| Still | 1.2 K | 1.2 K | 3.99 mW | 400 mW | 1% | readout_out 3.58 mW, dc_gates 364 µW, mw_drive 30.4 µW |
| CP | 0.14 K | 0.14 K | 0 W | 2 mW | 0% |  |
| MXC | 0.02 K | 0.02 K | 0 W | 190 µW | 0% |  |

## Spatial thermal maps

| plate | stage T | peak T | max rise | mean rise | peak power density | heat conserved |
|---|---|---|---|---|---|---|
| cold electronics @ 4K | 11 K | 11.81 K | 860 mK | 300 mK | 13.1 W/cm² | 2.7e-08 rel. err. |
| qubit chip @ Still | 1.2 K | 1.2 K | 0.00176 mK | 0.000844 mK | 1.75e-07 W/cm² | 5.6e-10 rel. err. |

## Workloads (energy at the system boundary; classical alternative at the same boundary)

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Shor, RSA-2048 | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 2,800 plus a 15-tile factory; a reference design (10 factories) needs about 23,414,150 physical qubits | — | — | 1.49e+13 GWh |
| FeMoco ground-state energy (THC qubitization) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 4,392 plus a 15-tile factory; a reference design (10 factories) needs about 36,049,854 physical qubits | — | — | none feasible |
| Small active-space chemistry (100 logical qubits) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 200 plus a 15-tile factory; a reference design (10 factories) needs about 1,820,350 physical qubits | — | — | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.45 | 75.2 s | 14.7 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Variational solver, 20 qubits, GPU optimiser | fidelity 0.84 | 24.2 s | 4.73 kWh | 122 J (this job: quantum 1.4e+05× more energy) |
| Quantum linear solve, N = 2^20, full solution vector read out | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 160 plus a 15-tile factory | — | — | 0.0994 J |
| Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 160 plus a 15-tile factory | — | — | 0.0994 J |
| Quantum linear solve, N = 2^40, scalar observable, input given by an efficient oracle (no explicit loading) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 280 plus a 15-tile factory | — | — | explicit vectors need more than one reference node; the comparison depends on structure (tensor-network or matrix-free methods) that is not assessed here |

## Warnings

- 4K stage overloaded: 90 W against 15 W at 4.2 K (would settle at 11 K); needs 7 fridge units
- heat load needs 7 fridge units for one processor
- no error-corrected computing: 10,000 physical qubits are fewer than one logical qubit at d=53 (5617 each, x2.0 layout)
