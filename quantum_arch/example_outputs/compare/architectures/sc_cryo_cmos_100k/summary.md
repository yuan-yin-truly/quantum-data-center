# sc_cryo_cmos_100k

Superconducting transmons, 100,000 physical qubits, `projected` hardware profile. Control scheme: Cryo-CMOS controller at 4 K, flex cabling to the mixing chamber.

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 0.77 µs |
| effective physical error p | 1.52e-03 |
| error suppression Λ = p_th/p (Rotated surface code) | 6.56 |
| code distance for target | 31 |
| logical qubits | 18 |
| logical clock | 4.19e+04 Hz |
| rQOPS | 7.54e+05 |
| logical error per op | 2.7e-13 (target 1e-12) |
| peak physical 2-qubit gate rate | 1.67e+12 /s |

Decoder `union_find`: 6.49e+10 syndrome bits/s, 1.95e+13 op/s, decode latency 6.2 µs, control reaction time 6.9 µs.

## Energy

| consumer | power | share |
|---|---|---|
| cryostat (installed) | 2.7 MW | 98.6 % |
| room-temperature control electronics | 37.5 kW | 1.4 % |
| classical host / optimiser | 1.45 kW | 0.1 % |
| decoders | 412 W | 0.0 % |
| data links | 649 mW | 0.0 % |
| **total (system)** | **2.74 MW** |  |
| with facility overhead (PUE 1.2) | 3.29 MW |  |

Energy per physical 2-qubit gate (all qubits busy): 1.64e-06 J. Energy per logical operation: 3.63 J. Thermodynamic (Carnot) floor for the cryostat heat loads: 2.72 kW, against 2.7 MW installed.

## Heat scheme

Dry dilution refrigerator (XLD400-class): 27 unit(s) needed (27 for heat, 1 for 3,125 lines).

| stage | target | settles at | load | capacity | utilisation | largest sources |
|---|---|---|---|---|---|---|
| 50K | 45 K | 45 K | 160 mW | 300 W | 0% | digital_link 160 mW |
| 4K | 4.2 K | 38.9 K | 400 W | 15 W | 2667% ⚠ | cryo-CMOS controller (drive + flux DACs + readout) 300 W, HEMT amplifiers (1 per feedline) 100 W, digital_link 5.7 mW |
| Still | 1.2 K | 1.2 K | 40.8 mW | 400 mW | 10% | readout_out 35.8 mW, coupler 2.12 mW, drive 1.21 mW |
| CP | 0.14 K | 0.266 K | 9.92 mW | 2 mW | 496% ⚠ | readout_out 4.62 mW, coupler 2.92 mW, flux 1.67 mW |
| MXC | 0.02 K | 0.0645 K | 2.15 mW | 190 µW | 1133% ⚠ | coupler 1.17 mW, flux 667 µW, drive 190 µW |

## Spatial thermal maps

| plate | stage T | peak T | max rise | mean rise | peak power density | heat conserved |
|---|---|---|---|---|---|---|
| qubit chip @ MXC | 0.0645 K | 0.0648 K | 0.297 mK | 0.196 mK | 7.75e-08 W/cm² | 2.7e-08 rel. err. |
- 4K: cold electronics (300 W) exceed 10x the stage capacity; spatial map skipped

## Workloads

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Shor, RSA-2048 | ✗ 100,000 qubits hold only 4 tiles at d=101; the algorithm needs 2,800 plus a 15-tile factory; a reference design (10 factories) needs about 7,224,550 physical qubits | — | — | 8.33e+12 GWh |
| FeMoco ground-state energy (THC qubitization) | ✗ 100,000 qubits hold only 4 tiles at d=101; the algorithm needs 4,392 plus a 15-tile factory; a reference design (10 factories) needs about 12,431,454 physical qubits | — | — | none feasible |
| Small active-space chemistry (100 logical qubits) | ✗ 100,000 qubits hold only 4 tiles at d=101; the algorithm needs 200 plus a 15-tile factory; a reference design (10 factories) needs about 588,350 physical qubits | — | — | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.67 | 32.2 s | 24.5 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Variational solver, 20 qubits, GPU optimiser | fidelity 0.9 | 9.93 s | 7.55 kWh | 68.2 J (quantum uses 4e+05× more) |

## Warnings

- 4K stage overloaded: 400 W against 15 W at 4.2 K (would settle at 38.9 K); needs 27 fridge units
- CP stage overloaded: 9.92 mW against 2 mW at 0.14 K (would settle at 0.266 K); needs 5 fridge units
- MXC stage overloaded: 2.15 mW against 190 µW at 0.02 K (would settle at 0.0645 K); needs 12 fridge units
- heat load needs 27 fridge units for one processor
