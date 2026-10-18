# ion_qccd_100q

Trapped ions (QCCD, shuttling), 100 physical qubits, `today` hardware profile. Control scheme: Room-temperature UHV trap, laser control.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 1.82 ms |
| effective physical error p | 2.16e-03 |
| error suppression Λ = p_th/p (Rotated surface code) | 4.63 |
| code distance for target | 37 |
| logical qubits | 0 |
| logical clock | 0 Hz |
| rQOPS | 0 |
| logical error per op | n/a |
| peak physical 2-qubit gate rate | 3.33e+05 /s |

> No error-corrected computing: 100 physical qubits are fewer than one logical qubit at d=37 (2737 each, x2.0 layout)

## Energy

| consumer | power | share |
|---|---|---|
| QPU apparatus (lasers, optics, traps, sources) | 20 kW | 56.4 % |
| support apparatus (vacuum, chillers, racks) | 14 kW | 39.5 % |
| classical host / optimiser | 1.45 kW | 4.1 % |
| **total, complete computer (system boundary)** | **35.4 kW** |  |

Power at the three measurement boundaries (they are different quantities; never compare numbers across them):

| boundary | power | what it contains |
|---|---|---|
| 1. QPU module (electrical) | 20 kW | module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat |
| 2. Complete computer (system) | 35.4 kW | everything above incl. cryostat compressors, room-temperature control, decoders, host; no facility cooling |
| 3. Facility (PUE 1.2) | 42.5 kW | (system + network/support) x PUE; includes heat rejection and chilled water |

Energy per physical 2-qubit gate (all qubits busy, system boundary): 0.106 J. 

## Workloads (energy at the system boundary; classical alternative at the same boundary)

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Shor, RSA-2048 | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 2,800 plus a 15-tile factory; a reference design (10 factories) needs about 11,944,550 physical qubits | — | — | 1.49e+13 GWh |
| FeMoco ground-state energy (THC qubitization) | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 4,392 plus a 15-tile factory; a reference design (10 factories) needs about 18,390,558 physical qubits | — | — | none feasible |
| Small active-space chemistry (100 logical qubits) | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 200 plus a 15-tile factory; a reference design (10 factories) needs about 857,150 physical qubits | — | — | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.51 | 23.3 h | 810 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Variational solver, 20 qubits, GPU optimiser | fidelity 0.85 | 5.97 h | 207 kWh | 122 J (this job: quantum 6.1e+06× more energy) |
| Quantum linear solve, N = 2^20, full solution vector read out | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 160 plus a 15-tile factory | — | — | 0.0994 J |
| Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 160 plus a 15-tile factory | — | — | 0.0994 J |
| Quantum linear solve, N = 2^40, scalar observable, input given by an efficient oracle (no explicit loading) | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 280 plus a 15-tile factory | — | — | explicit vectors need more than one reference node; the comparison depends on structure (tensor-network or matrix-free methods) that is not assessed here |

## Warnings

- no error-corrected computing: 100 physical qubits are fewer than one logical qubit at d=37 (2737 each, x2.0 layout)
