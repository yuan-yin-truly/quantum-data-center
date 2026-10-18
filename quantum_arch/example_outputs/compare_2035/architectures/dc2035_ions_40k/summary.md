# dc2035_ions_40k

Trapped ions (QCCD, shuttling), 40,000 physical qubits, `mid2030s` hardware profile. Control scheme: Room-temperature UHV trap, laser control.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 340 µs |
| effective physical error p | 2.30e-04 |
| error suppression Λ = p_th/p (Bivariate-bicycle qLDPC ('gross' family)) | 34.78 |
| code distance for target | 12 |
| logical qubits | 777 |
| logical clock | 245 Hz |
| rQOPS | 1.9e+05 |
| logical error per op | 6.8e-10 (target 1e-09) |
| peak physical 2-qubit gate rate | 6.67e+08 /s |

Decoder `bp_osd`: 5.88e+07 syndrome bits/s, 1.76e+12 op/s, decode latency 2.4 ms, control reaction time 2.45 ms.

## Energy

| consumer | power | share |
|---|---|---|
| QPU apparatus (lasers, optics, traps, sources) | 212 kW | 60.3 % |
| support apparatus (vacuum, chillers, racks) | 130 kW | 37.0 % |
| classical host / optimiser | 8.65 kW | 2.5 % |
| decoders | 890 W | 0.3 % |
| data links | 588 µW | 0.0 % |
| **total, complete computer (system boundary)** | **352 kW** |  |

Power at the three measurement boundaries (they are different quantities; never compare numbers across them):

| boundary | power | what it contains |
|---|---|---|
| 1. QPU module (electrical) | 212 kW | module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat |
| 2. Complete computer (system) | 352 kW | everything above incl. cryostat compressors, room-temperature control, decoders, host; no facility cooling |
| 3. Facility (PUE 1.15) | 404 kW | (system + network/support) x PUE; includes heat rejection and chilled water |

Energy per physical 2-qubit gate (all qubits busy, system boundary): 0.000527 J. Energy per logical operation (system boundary): 1.85 J.

## Workloads (energy at the system boundary; classical alternative at the same boundary)

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Small active-space chemistry (100 logical qubits) | d=18, 39,600 qubits (reaction time) | 2.84 days | 23.9 MWh | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.93 | 3.89 h | 1.35 MWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | d=18, 39,600 qubits, 100% of gates beyond one inversion (loading, read-out repeats); no advantage claimed | 50 days | 422 MWh | 0.188 J |
