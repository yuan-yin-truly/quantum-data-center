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
| lasers, vacuum, apparatus | 7 kW | 82.9 % |
| classical host / optimiser | 1.45 kW | 17.1 % |
| **total (system)** | **8.45 kW** |  |
| with facility overhead (PUE 1.2) | 10.1 kW |  |

Energy per physical 2-qubit gate (all qubits busy): 0.0253 J. 

## Workloads

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Shor, RSA-2048 | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 2,800 plus a 15-tile factory; a reference design (10 factories) needs about 11,944,550 physical qubits | — | — | 8.33e+12 GWh |
| FeMoco ground-state energy (THC qubitization) | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 4,392 plus a 15-tile factory; a reference design (10 factories) needs about 18,390,558 physical qubits | — | — | none feasible |
| Small active-space chemistry (100 logical qubits) | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 200 plus a 15-tile factory; a reference design (10 factories) needs about 857,150 physical qubits | — | — | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.51 | 23.3 h | 180 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Variational solver, 20 qubits, GPU optimiser | fidelity 0.85 | 5.97 h | 46.1 kWh | 68.2 J (quantum uses 2.4e+06× more) |

## Warnings

- no error-corrected computing: 100 physical qubits are fewer than one logical qubit at d=37 (2737 each, x2.0 layout)
