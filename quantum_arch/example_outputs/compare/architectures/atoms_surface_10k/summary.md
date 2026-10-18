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
| lasers, vacuum, apparatus | 20 kW | 93.2 % |
| classical host / optimiser | 1.45 kW | 6.8 % |
| **total (system)** | **21.4 kW** |  |
| with facility overhead (PUE 1.2) | 25.7 kW |  |

Energy per physical 2-qubit gate (all qubits busy): 1.72e-06 J. 

## Workloads

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Shor, RSA-2048 | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 2,800 plus a 15-tile factory; a reference design (10 factories) needs about 15,342,950 physical qubits | — | — | 8.33e+12 GWh |
| FeMoco ground-state energy (THC qubitization) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 4,392 plus a 15-tile factory; a reference design (10 factories) needs about 25,512,414 physical qubits | — | — | none feasible |
| Small active-space chemistry (100 logical qubits) | ✗ 10,000 qubits hold only 0 tiles at d=101; the algorithm needs 200 plus a 15-tile factory; a reference design (10 factories) needs about 1,176,350 physical qubits | — | — | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.2 | 7.3 h | 151 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Variational solver, 20 qubits, GPU optimiser | fidelity 0.71 | 2.59 h | 53.7 kWh | 68.2 J (quantum uses 2.8e+06× more) |

## Warnings

- no error-corrected computing: 10,000 physical qubits are fewer than one logical qubit at d=45 (4049 each, x2.0 layout)
