# Architecture comparison

Power is quoted at the boundary named in each column header (system = complete quantum computer; facility = incl. PUE and network). rQOPS compares gate-based machines only; annealers and photonic networks use their own metrics or coarse models (see README_QUANTUM.md).

| architecture | qubits | Λ | logical qubits | d | rQOPS | system power | facility power | J / logical op (system) | fridges | worst stage util. |
|---|---|---|---|---|---|---|---|---|---|---|
| dc2035_sc_surface_300k | 300,000 | 12.74 | 99 | 23 | 7.83e+06 | 2.91 MW | 3.35 MW | 0.372 | 1 | 98% |
| dc2035_cat_40k | 40,000 | 8.11 | 263 | 27 | 8.4e+06 | 270 kW | 310 kW | 0.0321 | 1 | 99% |
| dc2035_ions_40k | 40,000 | 34.78 | 777 | 12 | 1.9e+05 | 352 kW | 404 kW | 1.85 | none | — |
| dc2035_atoms_surface_1m | 1,000,000 | 8.00 | 240 | 27 | 1.11e+04 | 517 kW | 594 kW | 46.7 | none | — |
| dc2035_photonic_6m | 6,000,000 | 3.08 | 124 | 53 | 2.34e+06 | 6.01 MW | 6.92 MW | 2.57 | 1 | 80% |

## Workloads (time, system-boundary energy)

| architecture | Small active-space chemistry (100 logical qubits) | Variational solver, 50 qubits, GPU optimiser | Quantum linear solve, N = 2^20, one scalar observable of the solution (explicit data loading) |
|---|---|---|---|
| dc2035_sc_surface_300k | 11.8 min, 571 kWh | 21.6 s, 17.4 kWh | 4.26 h, 12.4 MWh |
| dc2035_cat_40k | 3.79 min, 17 kWh | 43.8 s, 3.25 kWh | 75.1 min, 338 kWh |
| dc2035_ions_40k | 2.84 days, 23.9 MWh | 3.89 h, 1.35 MWh | 50 days, 422 MWh |
| dc2035_atoms_surface_1m | 3.2 days, 39.6 MWh | 4.52 h, 2.31 MWh | 93.4 days, 1.16 GWh |
| dc2035_photonic_6m | 2.95 h, 17.8 MWh | 53.3 s, 88.9 kWh | 2.17 days, 313 MWh |
