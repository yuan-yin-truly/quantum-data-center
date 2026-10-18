# dc2035_atoms_surface_1m

Neutral atoms in optical tweezers (Rydberg gates), 1,000,000 physical qubits, `mid2030s` hardware profile. Control scheme: Room-temperature UHV cell, laser/AOD control.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 804 µs |
| effective physical error p | 1.25e-03 |
| error suppression Λ = p_th/p (Rotated surface code) | 8.00 |
| code distance for target | 27 |
| logical qubits | 240 |
| logical clock | 46.1 Hz |
| rQOPS | 1.11e+04 |
| logical error per op | 6.1e-13 (target 1e-12) |
| peak physical 2-qubit gate rate | 1.25e+12 /s |

Decoder `union_find`: 6.22e+08 syndrome bits/s, 1.87e+11 op/s, decode latency 5.4 µs, control reaction time 506 µs.

## Energy

| consumer | power | share |
|---|---|---|
| QPU apparatus (lasers, optics, traps, sources) | 304 kW | 58.8 % |
| support apparatus (vacuum, chillers, racks) | 204 kW | 39.5 % |
| classical host / optimiser | 8.65 kW | 1.7 % |
| decoders | 41.5 W | 0.0 % |
| data links | 6.22 mW | 0.0 % |
| **total, complete computer (system boundary)** | **517 kW** |  |

Power at the three measurement boundaries (they are different quantities; never compare numbers across them):

| boundary | power | what it contains |
|---|---|---|
| 1. QPU module (electrical) | 304 kW | module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat |
| 2. Complete computer (system) | 517 kW | everything above incl. cryostat compressors, room-temperature control, decoders, host; no facility cooling |
| 3. Facility (PUE 1.15) | 594 kW | (system + network/support) x PUE; includes heat rejection and chilled water |

Energy per physical 2-qubit gate (all qubits busy, system boundary): 4.13e-07 J. Energy per logical operation (system boundary): 46.7 J.

## Workloads (energy at the system boundary; classical alternative at the same boundary)

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Small active-space chemistry (100 logical qubits) | d=25, 999,200 qubits (factory throughput) | 3.2 days | 39.6 MWh | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.55 | 4.52 h | 2.31 MWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | d=29, 974,980 qubits, 100% of gates beyond one inversion (loading, read-out repeats); no advantage claimed | 93.4 days | 1.16 GWh | 0.188 J |
