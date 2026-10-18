# atoms_qldpc_10k

Neutral atoms in optical tweezers (Rydberg gates), 10,000 physical qubits, `projected` hardware profile. Control scheme: Room-temperature UHV cell, laser/AOD control.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 1.4 ms |
| effective physical error p | 2.67e-03 |
| error suppression Λ = p_th/p (Bivariate-bicycle qLDPC ('gross' family)) | 2.99 |
| code distance for target | n/a |
| logical qubits | 0 |
| logical clock | 0 Hz |
| rQOPS | 0 |
| logical error per op | n/a |
| peak physical 2-qubit gate rate | 1.25e+10 /s |

> No error-corrected computing: target 1e-09 needs a distance above 101

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
| Shor, RSA-2048 | ✗ 10,000 qubits hold only 208 tiles at d=18; the algorithm needs 2,100 plus a 15-tile factory | — | — | 8.33e+12 GWh |
| FeMoco ground-state energy (THC qubitization) | ✗ 10,000 qubits hold only 208 tiles at d=18; the algorithm needs 3,294 plus a 15-tile factory | — | — | none feasible |
| Small active-space chemistry (100 logical qubits) | ✗ d=18: total logical error 3.36e+06 exceeds the budget 1e-01 | — | — | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.2 | 7.3 h | 151 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Variational solver, 20 qubits, GPU optimiser | fidelity 0.71 | 2.59 h | 53.7 kWh | 68.2 J (quantum uses 2.8e+06× more) |

## Warnings

- no error-corrected computing: target 1e-09 needs a distance above 101
