# dc2035_cat_40k

Superconducting cat qubits (bosonic, bias-preserving repetition code), 40,000 physical qubits, `mid2030s` hardware profile. Control scheme: Cryo-CMOS controller at 4 K, flex cabling to the mixing chamber.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 1.16 µs |
| effective physical error p | 2.47e-03 |
| error suppression Λ = p_th/p (Cat-qubit repetition code (phase-flip, bias-preserving CX)) | 8.11 |
| code distance for target | 27 |
| logical qubits | 263 |
| logical clock | 3.19e+04 Hz |
| rQOPS | 8.4e+06 |
| logical error per op | 6.5e-13 (target 1e-12) |
| peak physical 2-qubit gate rate | 2e+11 /s |

Decoder `repetition_matching`: 1.72e+10 syndrome bits/s, 1.72e+12 op/s, decode latency 1.35 µs, control reaction time 2.05 µs.

## Energy

| consumer | power | share |
|---|---|---|
| cryostat (installed) | 255 kW | 94.5 % |
| classical host / optimiser | 8.65 kW | 3.2 % |
| room-temperature control electronics | 6 kW | 2.2 % |
| cold electronics supply (cryo-CMOS, amplifiers, cold decoders) | 59.6 W | 0.0 % |
| decoders | 53.8 W | 0.0 % |
| data links | 172 mW | 0.0 % |
| **total, complete computer (system boundary)** | **270 kW** |  |

Power at the three measurement boundaries (they are different quantities; never compare numbers across them):

| boundary | power | what it contains |
|---|---|---|
| 1. QPU module (electrical) | 59.6 W | module apparatus (lasers, optics, traps, sources) + supply of electronics inside the cryostat |
|    cold-stage heat load (thermal, not wall power) | 59.7 W | heat lifted by the cryostat stages: cable conduction, attenuators, cold electronics |
| 2. Complete computer (system) | 270 kW | everything above incl. cryostat compressors, room-temperature control, decoders, host; no facility cooling |
| 3. Facility (PUE 1.15) | 310 kW | (system + network/support) x PUE; includes heat rejection and chilled water |

Energy per physical 2-qubit gate (all qubits busy, system boundary): 1.35e-06 J. Energy per logical operation (system boundary): 0.0321 J. Thermodynamic (Carnot) floor for the cryostat heat loads: 4.21 kW, against 255 kW installed.

## Heat scheme

Large-format multi-unit dilution platform (Bluefors KIDE class), 2035 scenario: 1 unit(s) needed (1 for heat, 1 for 1,250 lines).

| stage | target | settles at | load | capacity | utilisation | largest sources |
|---|---|---|---|---|---|---|
| 50K | 45 K | 45 K | 64 mW | 1.2 kW | 0% | digital_link 64 mW |
| 4K | 4.2 K | 4.2 K | 59.6 W | 60 W | 99% | cryo-CMOS controller (drive + pump + readout) 39.6 W, HEMT amplifiers (1 per feedline) 20 W, digital_link 2.28 mW |
| Still | 1.2 K | 1.2 K | 8.3 mW | 1.2 W | 1% | readout_out 7.16 mW, drive 486 µW, buffer_pump 486 µW |
| CP | 0.14 K | 0.14 K | 1.15 mW | 14 mW | 8% | readout_out 923 µW, buffer_pump 62.9 µW, drive 62.7 µW |
| MXC | 0.02 K | 0.02 K | 233 µW | 570 µW | 41% | buffer_pump 140 µW, drive 75.8 µW, readout_out 15.2 µW |

## Spatial thermal maps

| plate | stage T | peak T | max rise | mean rise | peak power density | heat conserved |
|---|---|---|---|---|---|---|
| cold electronics @ 4K | 4.2 K | 6.192 K | 1.99e+03 mK | 723 mK | 5.77 W/cm² | 3.3e-08 rel. err. |
| qubit chip @ MXC | 0.02 K | 0.02567 K | 5.67 mK | 3.99 mK | 1.86e-07 W/cm² | 3.5e-08 rel. err. |

## Workloads (energy at the system boundary; classical alternative at the same boundary)

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Small active-space chemistry (100 logical qubits) | d=25, 39,788 qubits (factory throughput) | 3.79 min | 17 kWh | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.39 | 43.8 s | 3.25 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | d=27, 39,644 qubits, 100% of gates beyond one inversion (loading, read-out repeats); no advantage claimed | 75.1 min | 338 kWh | 0.188 J |
