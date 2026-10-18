# sc_rt_direct_100q

Superconducting transmons, 100 physical qubits, `today` hardware profile. Control scheme: Room-temperature electronics, one coax per control line (Krinner-style).

## Computing power

| quantity | value |
|---|---|
| syndrome cycle | 0.81 µs |
| effective physical error p | 5.15e-03 |
| error suppression Λ = p_th/p (Rotated surface code) | 1.94 |
| code distance for target | 89 |
| logical qubits | 0 |
| logical clock | 0 Hz |
| rQOPS | 0 |
| logical error per op | n/a |
| peak physical 2-qubit gate rate | 1.25e+09 /s |

> No error-corrected computing: 100 physical qubits are fewer than one logical qubit at d=89 (15841 each, x2.0 layout)

## Energy

| consumer | power | share |
|---|---|---|
| cryostat (installed) | 20 kW | 83.7 % |
| room-temperature control electronics | 2.44 kW | 10.2 % |
| classical host / optimiser | 1.45 kW | 6.1 % |
| **total (system)** | **23.9 kW** |  |
| with facility overhead (PUE 1.2) | 28.7 kW |  |

Energy per physical 2-qubit gate (all qubits busy): 1.91e-05 J.  Thermodynamic (Carnot) floor for the cryostat heat loads: 89.4 W, against 20 kW installed.

## Heat scheme

Dry dilution refrigerator (XLD400-class): 2 unit(s) needed (2 for heat, 1 for 414 lines).

| stage | target | settles at | load | capacity | utilisation | largest sources |
|---|---|---|---|---|---|---|
| 50K | 45 K | 45 K | 10.8 W | 30 W | 36% | coupler 4.57 W, drive 2.61 W, flux 2.61 W |
| 4K | 4.2 K | 4.2 K | 380 mW | 1.5 W | 25% | coupler 116 mW, HEMT amplifiers (1 per feedline) 100 mW, drive 66 mW |
| Still | 1.2 K | 1.2 K | 1.88 mW | 40 mW | 5% | coupler 800 µW, drive 457 µW, flux 457 µW |
| CP | 0.14 K | 0.164 K | 313 µW | 200 µW | 157% ⚠ | coupler 103 µW, drive 58.9 µW, flux 58.9 µW |
| MXC | 0.02 K | 0.02 K | 17.9 µW | 19 µW | 94% | coupler 8.75 µW, flux 5 µW, coupler 1.69 µW |

## Spatial thermal maps

| plate | stage T | peak T | max rise | mean rise | peak power density | heat conserved |
|---|---|---|---|---|---|---|
| qubit chip @ MXC | 0.02 K | 0.02031 K | 0.312 mK | 0.115 mK | 7.97e-09 W/cm² | 1.6e-08 rel. err. |

## Workloads

| workload | result | time | energy | classical alternative |
|---|---|---|---|---|
| Shor, RSA-2048 | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 2,800 plus a 15-tile factory | — | — | 8.33e+12 GWh |
| FeMoco ground-state energy (THC qubitization) | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 4,392 plus a 15-tile factory | — | — | none feasible |
| Small active-space chemistry (100 logical qubits) | ✗ 100 qubits hold only 0 tiles at d=101; the algorithm needs 200 plus a 15-tile factory; a reference design (10 factories) needs about 5,057,150 physical qubits | — | — | none feasible |
| Variational solver, 50 qubits, GPU optimiser | fidelity 0.16 | 34.2 s | 0.23 kWh | state-vector simulation needs 1.8e+04 TB, more than the 1.5 TB reference node |
| Variational solver, 20 qubits, GPU optimiser | fidelity 0.66 | 10.4 s | 2.5e+05 J | 68.2 J (quantum uses 3.7e+03× more) |

## Warnings

- CP stage overloaded: 313 µW against 200 µW at 0.14 K (would settle at 0.164 K); needs 2 fridge units
- heat load needs 2 fridge units for one processor
- no error-corrected computing: 100 physical qubits are fewer than one logical qubit at d=89 (15841 each, x2.0 layout)
