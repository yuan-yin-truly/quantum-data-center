# dc2035_sc_surface_300k

Superconducting transmons, 300,000 physical qubits, `mid2030s` hardware profile. Control scheme: Cryo-CMOS controller at 4 K, flex cabling to the mixing chamber.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 0.55 µs |
| effective physical error p | 7.85e-04 |
| error suppression Λ = p_th/p (Rotated surface code) | 12.74 |
| code distance for target | 23 |
| logical qubits | 99 |
| logical clock | 7.91e+04 Hz |
| rQOPS | 7.83e+06 |
| logical error per op | 1.3e-13 (target 1e-12) |
| peak physical 2-qubit gate rate | 5e+12 /s |

Decoder `union_find`: 2.72e+11 syndrome bits/s, 8.16e+13 op/s, decode latency 4.6 µs, control reaction time 5.1 µs.

## Energy

| consumer | power | share |
|---|---|---|
| cryostat (installed) | 2.86 MW | 98.1 % |
| room-temperature control electronics | 45 kW | 1.5 % |
| classical host / optimiser | 8.65 kW | 0.3 % |
| decoders | 853 W | 0.0 % |
| cold electronics supply (cryo-CMOS, amplifiers, cold decoders) | 447 W | 0.0 % |
| data links | 2.72 W | 0.0 % |
| **total, complete computer (system boundary)** | **2.91 MW** |  |

Power at the three measurement boundaries (they are different quantities; never compare numbers across them):

| boundary | power | what it contains |
|---|---|---|
| 1. QPU module (electrical) | 447 W | module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat |
|    cold-stage heat load (thermal, not wall power) | 448 W | heat lifted by the cryostat stages: cable conduction, attenuators, cold electronics |
| 2. Complete computer (system) | 2.91 MW | everything above incl. cryostat compressors, room-temperature control, decoders, host; no facility cooling |
| 3. Facility (PUE 1.15) | 3.35 MW | (system + network/support) x PUE; includes heat rejection and chilled water |

Energy per physical 2-qubit gate (all qubits busy, system boundary): 5.82e-07 J. Energy per logical operation (system boundary): 0.372 J. Thermodynamic (Carnot) floor for the cryostat heat loads: 31.6 kW, against 2.86 MW installed.

## Heat scheme

Large-format multi-unit dilution platform (Bluefors KIDE class), 2035 scenario: 1 unit(s) needed (1 for heat, 1 for 9,375 lines).

| stage | target | settles at | load | capacity | utilisation | largest sources |
|---|---|---|---|---|---|---|
| 50K | 45 K | 45 K | 480 mW | 13.4 kW | 0% | digital_link 480 mW |
| 4K | 4.2 K | 4.2 K | 447 W | 672 W | 67% | cryo-CMOS controller (drive + flux DACs + readout) 297 W, HEMT amplifiers (1 per feedline) 150 W, digital_link 17.1 mW |
| Still | 1.2 K | 1.2 K | 68.2 mW | 13.4 W | 1% | readout_out 53.7 mW, coupler 6.37 mW, drive 3.64 mW |
| CP | 0.14 K | 0.14 K | 22.8 mW | 157 mW | 15% | coupler 8.75 mW, readout_out 6.92 mW, flux 5 mW |
| MXC | 0.02 K | 0.02 K | 6.28 mW | 6.38 mW | 98% | coupler 3.5 mW, flux 2 mW, drive 569 µW |

## Spatial thermal maps

| plate | stage T | peak T | max rise | mean rise | peak power density | heat conserved |
|---|---|---|---|---|---|---|
| cold electronics @ 4K | 4.2 K | 10.54 K | 6.34e+03 mK | 3.07e+03 mK | 43.3 W/cm² | 7.0e-10 rel. err. |
| qubit chip @ MXC | 0.02 K | 0.02476 K | 4.76 mK | 3.32 mK | 1.5e-07 W/cm² | 2.7e-08 rel. err. |

## Workloads (energy at the system boundary; classical alternative at the same boundary)

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Small active-space chemistry (100 logical qubits) | d=21, 295,135 qubits (factory throughput) | 11.8 min | 571 kWh | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.79 | 21.6 s | 17.4 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | d=23, 295,960 qubits, 100% of gates beyond one inversion (loading, read-out repeats); no advantage claimed | 4.26 h | 12.4 MWh | 0.188 J |
