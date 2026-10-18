# ion_cryo4k_2k

Trapped ions (QCCD, shuttling), 2,000 physical qubits, `projected` hardware profile. Control scheme: Cryogenic (4 K) surface trap in a pulse-tube cryostat.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 720 µs |
| effective physical error p | 4.72e-04 |
| error suppression Λ = p_th/p (Rotated surface code) | 21.16 |
| code distance for target | 19 |
| logical qubits | 0 |
| logical clock | 0 Hz |
| rQOPS | 0 |
| logical error per op | n/a |
| peak physical 2-qubit gate rate | 2e+07 /s |

> No error-corrected computing: 2,000 physical qubits are fewer than one logical qubit at d=19 (721 each, x2.0 layout)

## Energy

| consumer | power | share |
|---|---|---|
| cryostat (installed) | 232 kW | 72.7 % |
| QPU apparatus (lasers, optics, traps, sources) | 58 kW | 18.1 % |
| support apparatus (vacuum, chillers, racks) | 23.5 kW | 7.3 % |
| room-temperature control electronics | 4.4 kW | 1.4 % |
| classical host / optimiser | 1.45 kW | 0.5 % |
| cold electronics supply (cryo-CMOS, amplifiers, cold decoders) | 700 mW | 0.0 % |
| **total, complete computer (system boundary)** | **320 kW** |  |

Power at the three measurement boundaries (they are different quantities; never compare numbers across them):

| boundary | power | what it contains |
|---|---|---|
| 1. QPU module (electrical) | 58 kW | module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat |
|    cold-stage heat load (thermal, not wall power) | 19.8 W | heat lifted by the cryostat stages: cable conduction, attenuators, cold electronics |
| 2. Complete computer (system) | 320 kW | everything above incl. cryostat compressors, room-temperature control, decoders, host; no facility cooling |
| 3. Facility (PUE 1.2) | 384 kW | (system + network/support) x PUE; includes heat rejection and chilled water |

Energy per physical 2-qubit gate (all qubits busy, system boundary): 0.016 J.  Thermodynamic (Carnot) floor for the cryostat heat loads: 187 W, against 232 kW installed.

## Heat scheme

Two-stage pulse-tube cryocooler (4 K class): 31 unit(s) needed (1 for heat, 31 for 12,040 lines).

| stage | target | settles at | load | capacity | utilisation | largest sources |
|---|---|---|---|---|---|---|
| 50K | 45 K | 45 K | 18.7 W | 30 W | 62% | dc_electrodes 17.6 W, rf_trap 1.05 W |
| 4K | 4.2 K | 4.2 K | 1.15 W | 1.5 W | 76% | trap RF losses + laser light absorbed on chip 700 mW, dc_electrodes 419 mW, rf_trap 26.4 mW |

## Workloads (energy at the system boundary; classical alternative at the same boundary)

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Shor, RSA-2048 | ✗ 2,000 qubits hold only 0 tiles at d=101; the algorithm needs 2,800 plus a 15-tile factory; a reference design (10 factories) needs about 2,598,950 physical qubits | — | — | 1.49e+13 GWh |
| FeMoco ground-state energy (THC qubitization) | ✗ 2,000 qubits hold only 0 tiles at d=101; the algorithm needs 4,392 plus a 15-tile factory; a reference design (10 factories) needs about 4,001,502 physical qubits | — | — | none feasible |
| Small active-space chemistry (100 logical qubits) | ✗ 2,000 qubits hold only 0 tiles at d=101; the algorithm needs 200 plus a 15-tile factory; a reference design (10 factories) needs about 201,950 physical qubits | — | — | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.87 | 8.06 h | 2.57 MWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Variational solver, 20 qubits, GPU optimiser | fidelity 0.97 | 2.15 h | 687 kWh | 122 J (this job: quantum 2e+07× more energy) |
| Quantum linear solve, N = 2^20, full solution vector read out | ✗ 2,000 qubits hold only 0 tiles at d=101; the algorithm needs 160 plus a 15-tile factory | — | — | 0.0994 J |
| Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | ✗ 2,000 qubits hold only 0 tiles at d=101; the algorithm needs 160 plus a 15-tile factory | — | — | 0.0994 J |
| Quantum linear solve, N = 2^40, scalar observable, input given by an efficient oracle (no explicit loading) | ✗ 2,000 qubits hold only 0 tiles at d=101; the algorithm needs 280 plus a 15-tile factory | — | — | explicit vectors need more than one reference node; the comparison depends on structure (tensor-network or matrix-free methods) that is not assessed here |

## Warnings

- 12,040 lines exceed the 400 a single fridge carries (31 units); superconducting qubits cannot be split across fridges without a cryogenic interconnect
- no error-corrected computing: 2,000 physical qubits are fewer than one logical qubit at d=19 (721 each, x2.0 layout)
