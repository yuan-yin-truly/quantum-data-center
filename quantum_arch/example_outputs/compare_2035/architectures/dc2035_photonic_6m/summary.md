# dc2035_photonic_6m

Photonic, fusion-based (room-temperature optics, cryogenic detectors), 6,000,000 physical qubits, `mid2030s` hardware profile. Control scheme: Optical network at room temperature; superconducting nanowire detectors in cryo cabinets (~4 K).

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 1 µs |
| effective physical error p | 3.25e-03 |
| error suppression Λ = p_th/p (Fusion-based photonic network (surface-like fusion lattice)) | 3.08 |
| code distance for target | 53 |
| logical qubits | 124 |
| logical clock | 1.89e+04 Hz |
| rQOPS | 2.34e+06 |
| logical error per op | 3.5e-13 (target 1e-12) |
| peak physical 2-qubit gate rate | 3e+13 /s |

Decoder `fusion_matching`: 2.99e+12 syndrome bits/s, 8.97e+15 op/s, decode latency 106 µs, control reaction time 106 µs.

## Energy

| consumer | power | share |
|---|---|---|
| QPU apparatus (lasers, optics, traps, sources) | 3.62 MW | 60.2 % |
| cryostat (installed) | 2.29 MW | 38.2 % |
| decoders | 89.8 kW | 1.5 % |
| classical host / optimiser | 8.65 kW | 0.1 % |
| cold electronics supply (cryo-CMOS, amplifiers, cold decoders) | 600 W | 0.0 % |
| data links | 29.9 W | 0.0 % |
| **total, complete computer (system boundary)** | **6.01 MW** |  |

Power at the three measurement boundaries (they are different quantities; never compare numbers across them):

| boundary | power | what it contains |
|---|---|---|
| 1. QPU module (electrical) | 3.62 MW | module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat |
|    cold-stage heat load (thermal, not wall power) | 707 W | heat lifted by the cryostat stages: cable conduction, attenuators, cold electronics |
| 2. Complete computer (system) | 6.01 MW | everything above incl. cryostat compressors, room-temperature control, decoders, host; no facility cooling |
| 3. Facility (PUE 1.15) | 6.92 MW | (system + network/support) x PUE; includes heat rejection and chilled water |

Energy per physical 2-qubit gate (all qubits busy, system boundary): 2e-07 J. Energy per logical operation (system boundary): 2.57 J. Thermodynamic (Carnot) floor for the cryostat heat loads: 43 kW, against 2.29 MW installed.

## Heat scheme

Cryo cabinet for superconducting nanowire detectors (about 4 K), rack-style: 1 unit(s) needed (1 for heat, 1 for 612,000 lines).

| stage | target | settles at | load | capacity | utilisation | largest sources |
|---|---|---|---|---|---|---|
| 50K | 45 K | 45 K | 105 W | 15 kW | 1% | detector_bias_readout 95.9 W, fiber_out 8.72 W |
| 4K | 4.2 K | 4.2 K | 603 W | 750 W | 80% | SNSPD bias and cryogenic readout 600 W, detector_bias_readout 2.42 W, fiber_out 231 mW |

## Spatial thermal maps

| plate | stage T | peak T | max rise | mean rise | peak power density | heat conserved |
|---|---|---|---|---|---|---|
| cold electronics @ 4K | 4.2 K | 13.24 K | 9.04e+03 mK | 4.64e+03 mK | 87.4 W/cm² | 1.4e-10 rel. err. |

## Workloads (energy at the system boundary; classical alternative at the same boundary)

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Small active-space chemistry (100 logical qubits) | d=51, 5,930,280 qubits (reaction time) | 2.95 h | 17.8 MWh | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.16 | 53.3 s | 88.9 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | d=57, 5,750,730 qubits, 100% of gates beyond one inversion (loading, read-out repeats); no advantage claimed | 2.17 days | 313 MWh | 0.188 J |
