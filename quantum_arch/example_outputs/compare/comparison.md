# Architecture comparison

| architecture | qubits | Λ | logical qubits | d | rQOPS | power | J / logical op | fridges | worst stage util. |
|---|---|---|---|---|---|---|---|---|---|
| atoms_qldpc_10k | 10,000 | 2.99 | 0 | — | — | 21.4 kW | — | none | — |
| atoms_surface_10k | 10,000 | 3.74 | 0 | 45 | — | 21.4 kW | — | none | — |
| ion_cryo4k_2k | 2,000 | 21.16 | 0 | 19 | — | 321 kW | — | 31 | 76% |
| ion_qccd_100q | 100 | 4.63 | 0 | 37 | — | 8.45 kW | — | none | — |
| sc_cryo_cmos_100k | 100,000 | 6.56 | 18 | 31 | 7.54e+05 | 2.74 MW | 3.63 | 27 | 2667% |
| sc_rt_direct_100q | 100 | 1.94 | 0 | 89 | — | 23.9 kW | — | 2 | 157% |
| spin_cmos_10k | 10,000 | 2.99 | 0 | 53 | — | 705 kW | — | 7 | 600% |

## Workloads (time, energy)

| architecture | Shor, RSA-2048 | FeMoco ground-state energy (THC qubitization) | Small active-space chemistry (100 logical qubits) | Variational solver, 50 qubits, GPU optimiser | Variational solver, 20 qubits, GPU optimiser |
|---|---|---|---|---|---|
| atoms_qldpc_10k | ✗ | ✗ | ✗ | 7.3 h, 151 kWh | 2.59 h, 53.7 kWh |
| atoms_surface_10k | ✗ | ✗ | ✗ | 7.3 h, 151 kWh | 2.59 h, 53.7 kWh |
| ion_cryo4k_2k | ✗ | ✗ | ✗ | 8.06 h, 2.58 MWh | 2.15 h, 691 kWh |
| ion_qccd_100q | ✗ | ✗ | ✗ | 23.3 h, 180 kWh | 5.97 h, 46.1 kWh |
| sc_cryo_cmos_100k | ✗ | ✗ | ✗ | 32.2 s, 24.5 kWh | 9.93 s, 7.55 kWh |
| sc_rt_direct_100q | ✗ | ✗ | ✗ | 34.2 s, 0.23 kWh | 10.4 s, 2.5e+05 J |
| spin_cmos_10k | ✗ | ✗ | ✗ | 75.2 s, 14.7 kWh | 24.2 s, 4.73 kWh |
