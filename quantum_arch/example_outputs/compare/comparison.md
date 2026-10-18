# Architecture comparison

Power is quoted at the boundary named in each column header (system = complete quantum computer; facility = incl. PUE and network). rQOPS compares gate-based machines only; annealers and photonic networks use their own metrics or coarse models (see README_QUANTUM.md).

| architecture | qubits | Λ | logical qubits | d | rQOPS | system power | facility power | J / logical op (system) | fridges | worst stage util. |
|---|---|---|---|---|---|---|---|---|---|---|
| sc_rt_direct_100q | 100 | 1.94 | 0 | 89 | — | 23.9 kW | 28.7 kW | — | 2 | 157% |
| sc_cryo_cmos_100k | 100,000 | 6.56 | 18 | 31 | 7.54e+05 | 2.74 MW | 3.29 MW | 3.63 | 27 | 2667% |
| spin_cmos_10k | 10,000 | 2.99 | 0 | 53 | — | 705 kW | 846 kW | — | 7 | 600% |
| ion_qccd_100q | 100 | 4.63 | 0 | 37 | — | 35.4 kW | 42.5 kW | — | none | — |
| ion_cryo4k_2k | 2,000 | 21.16 | 0 | 19 | — | 320 kW | 384 kW | — | 31 | 76% |
| atoms_surface_10k | 10,000 | 3.74 | 0 | 45 | — | 11.4 kW | 13.7 kW | — | none | — |
| atoms_qldpc_10k | 10,000 | 2.99 | 0 | — | — | 11.4 kW | 13.7 kW | — | none | — |

## Workloads (time, system-boundary energy)

| architecture | Shor, RSA-2048 | FeMoco ground-state energy (THC qubitization) | Small active-space chemistry (100 logical qubits) | Variational solver, 50 qubits, GPU optimiser | Variational solver, 20 qubits, GPU optimiser | Quantum linear solve, N = 2^20, full solution vector read out | Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) | Quantum linear solve, N = 2^40, scalar observable, input given by an efficient oracle (no explicit loading) |
|---|---|---|---|---|---|---|---|---|
| sc_rt_direct_100q | ✗ | ✗ | ✗ | 34.2 s, 0.23 kWh | 10.4 s, 2.5e+05 J | ✗ | ✗ | ✗ |
| sc_cryo_cmos_100k | ✗ | ✗ | ✗ | 32.2 s, 24.5 kWh | 9.93 s, 7.55 kWh | ✗ | ✗ | ✗ |
| spin_cmos_10k | ✗ | ✗ | ✗ | 75.2 s, 14.7 kWh | 24.2 s, 4.73 kWh | ✗ | ✗ | ✗ |
| ion_qccd_100q | ✗ | ✗ | ✗ | 23.3 h, 810 kWh | 5.97 h, 207 kWh | ✗ | ✗ | ✗ |
| ion_cryo4k_2k | ✗ | ✗ | ✗ | 8.06 h, 2.57 MWh | 2.15 h, 687 kWh | ✗ | ✗ | ✗ |
| atoms_surface_10k | ✗ | ✗ | ✗ | 7.3 h, 78.3 kWh | 2.59 h, 27.8 kWh | ✗ | ✗ | ✗ |
| atoms_qldpc_10k | ✗ | ✗ | ✗ | 7.3 h, 78.3 kWh | 2.59 h, 27.8 kWh | ✗ | ✗ | ✗ |
