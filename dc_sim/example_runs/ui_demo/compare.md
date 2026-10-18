# dc_sim compare: ui_demo

*Illustrative model. Score structure of the challenge: users served within SLO at the constraints (500 MW grid, 30 B USD), then dollars saved against the GPU-only reference (same site power caps, QPU power replaced by GPU racks, policy `gpu_only`).*

Power boundary of all energy figures: facility (system x (1 + network) x PUE). Dollars: capex amortised over 5 years + energy actually used, per simulated-day equivalent.

| rank | policy | served % (worst of A/B/C/tasks) | A % | B % | C % | tasks % | facility MWh | energy USD/day | total USD/day | saved vs GPU-only ref, USD/day (total / energy only) | on QPU / classical / rejected | cap held |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Greedy cost/time-aware | 92.86 | - | - | 100.0 | 95.0 | 325 | 156k | 9,727k | -1,717k / +2.2k | 6 / 4 / 1 | True |
| 2 | Batch optimiser (MILP + LP) | 92.86 | - | - | 100.0 | 95.0 | 317 | 171k | 9,742k | -1,732k / -12.8k | 6 / 4 / 1 | True |
| 3 | FIFO / first-fit | 57.14 | - | - | 100.0 | 70.0 | 322 | 190k | 9,761k | -1,750k / -31.2k | 10 / 0 / 1 | True |
| 4 | GPU-only reference fleet + policy | 50.00 | - | - | 100.0 | 65.0 | 291 | 159k | 8,010k | +0k / +0.0k | 0 / 4 / 7 | True |
| 5 | GPU-only reference (batch, no QPU) | 50.00 | - | - | 100.0 | 65.0 | 316 | 171k | 9,742k | -1,732k / -12.8k | 0 / 4 / 7 | True |

## QPU break-even (what has to be true for a QPU node to pay for itself)

Per QPU node: fixed cost per day = amortised capex + standby energy; saving per job = assumed classical cost minus the QPU's marginal energy cost. The classical costs are ASSUMPTIONS (largest uncertainty).

| QPU node | workload | job occupancy | max jobs/day | classical USD/job | QPU marginal USD/job | fixed USD/day | break-even jobs/day | pays off at capacity |
|---|---|---|---|---|---|---|---|---|
| QPU, 40k cat qubits (repetition code) | chemistry_small | 4.8 min | 301 | 2171.55 | 0.087 | 66,321 | 30.5 | True |
| QPU, 40k cat qubits (repetition code) | vqe_50q | 104 s | 833 | 452.41 | 0.031 | 66,321 | 146.6 | True |
| QPU, 40k cat qubits (repetition code) | vqe_20q | 73 s | 1187 | 1.13 | 0.022 | 66,321 | 59797.3 | False |
| QPU, 40k cat qubits (repetition code) | qla_scalar_explicit_1m | 76.1 min | 19 | 0.14 | 1.374 | 66,321 | never | False |
| Mixed node: 16 GPU modules + 40k cat-qubit QPU on a low-latency link | chemistry_small | 4.8 min | 301 | 2171.55 | 0.087 | 71,801 | 33.1 | True |
| Mixed node: 16 GPU modules + 40k cat-qubit QPU on a low-latency link | vqe_50q | 104 s | 833 | 452.41 | 0.031 | 71,801 | 158.7 | True |
| Mixed node: 16 GPU modules + 40k cat-qubit QPU on a low-latency link | vqe_20q | 73 s | 1187 | 1.13 | 0.022 | 71,801 | 64737.7 | False |
| Mixed node: 16 GPU modules + 40k cat-qubit QPU on a low-latency link | qla_scalar_explicit_1m | 76.1 min | 19 | 0.14 | 1.374 | 71,801 | never | False |
| QPU, 300k transmons (surface code, MW-scale cryo) | chemistry_small | 12.8 min | 113 | 2171.55 | 0.572 | 250,783 | 115.5 | False |
| QPU, 300k transmons (surface code, MW-scale cryo) | vqe_50q | 82 s | 1059 | 452.41 | 0.061 | 250,783 | 554.4 | True |
| QPU, 300k transmons (surface code, MW-scale cryo) | vqe_20q | 67 s | 1295 | 1.13 | 0.050 | 250,783 | 231949.7 | False |
| QPU, 300k transmons (surface code, MW-scale cryo) | qla_scalar_explicit_1m | 4.3 h | 6 | 0.14 | 11.491 | 250,783 | never | False |
| QPU, 40k trapped ions (qLDPC) | chemistry_small | 2.8 d | 0 | 2171.55 | 20.817 | 109,920 | 51.1 | False |
| QPU, 40k trapped ions (qLDPC) | vqe_50q | 3.9 h | 6 | 452.41 | 1.195 | 109,920 | 243.6 | False |
| QPU, 40k trapped ions (qLDPC) | vqe_20q | 63.5 min | 23 | 1.13 | 0.324 | 109,920 | 136171.6 | False |
| QPU, 40k trapped ions (qLDPC) | qla_scalar_explicit_1m | 50.0 d | 0 | 0.14 | 366.819 | 109,920 | never | False |
