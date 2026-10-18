# atoms_surface_10k

Neutral atoms in optical tweezers (Rydberg gates), 10,000 physical qubits, `projected` hardware profile. Control scheme: Room-temperature UHV cell, laser/AOD control.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 1.4 ms |
| effective physical error p | 2.67e-03 |
| error suppression Λ = p_th/p (Rotated surface code) | 3.74 |
| code distance for target | 45 |
| logical qubits | 0 |
| logical clock | 0 Hz |
| rQOPS | 0 |
| logical error per op | n/a |
| peak physical 2-qubit gate rate | 1.25e+10 /s |

> No error-corrected computing: 10,000 physical qubits are fewer than one logical qubit at d=45 (4049 each, x2.0 layout)

## Energy

| consumer | power | share |
|---|---|---|
| QPU apparatus (lasers, optics, traps, sources) | 5 kW | 43.7 % |
| support apparatus (vacuum, chillers, racks) | 5 kW | 43.7 % |
| classical host / optimiser | 1.45 kW | 12.6 % |
| **total, complete computer (system boundary)** | **11.4 kW** |  |

Power at the three measurement boundaries (they are different quantities; never compare numbers across them):

| boundary | power | what it contains |
|---|---|---|
| 1. QPU module (electrical) | 5 kW | module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat |
| 2. Complete computer (system) | 11.4 kW | everything above incl. cryostat compressors, room-temperature control, decoders, host; no facility cooling |
| 3. Facility (PUE 1.2) | 13.7 kW | (system + network/support) x PUE; includes heat rejection and chilled water |

Energy per physical 2-qubit gate (all qubits busy, system boundary): 9.16e-07 J. 

## Workloads (energy at the system boundary; classical alternative at the same boundary)

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Shor, RSA-2048 | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 2,800 plus a 15-tile factory; a reference design (10 factories) needs about 15,342,950 physical qubits | — | — | 1.49e+13 GWh |
| FeMoco ground-state energy (THC qubitization) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 4,392 plus a 15-tile factory; a reference design (10 factories) needs about 25,512,414 physical qubits | — | — | none feasible |
| Small active-space chemistry (100 logical qubits) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 200 plus a 15-tile factory; a reference design (10 factories) needs about 1,176,350 physical qubits | — | — | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.2 | 7.3 h | 78.3 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Variational solver, 20 qubits, GPU optimiser | fidelity 0.71 | 2.59 h | 27.8 kWh | 122 J (this job: quantum 8.2e+05× more energy) |
| Quantum linear solve, N = 2^20, full solution vector read out | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 160 plus a 15-tile factory | — | — | 0.0994 J |
| Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 160 plus a 15-tile factory | — | — | 0.0994 J |
| Quantum linear solve, N = 2^40, scalar observable, input given by an efficient oracle (no explicit loading) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 280 plus a 15-tile factory | — | — | explicit vectors need more than one reference node; the comparison depends on structure (tensor-network or matrix-free methods) that is not assessed here |

## Warnings

- no error-corrected computing: 10,000 physical qubits are fewer than one logical qubit at d=45 (4049 each, x2.0 layout)
