# dc_sim run: ui_demo / policy batch

*Results of an illustrative model; every demand, cost and node-count number not taken from `quantum_arch` is an ASSUMPTION (see `dc_sim/data/assumptions.json`).*

- fleet `default_6site`, seed 1, simulated 3.0 h in ticks of 60 s, case `C`
- power boundary of all energy numbers: **facility = system x (1 + network overhead) x PUE(site, ambient)**

## Users served within SLO

| case | users | requests served within SLO | worst tick | mean RTT |
|---|---|---|---|---|
| C | 400 M | 100.00 % | 100.0 % | 84 ms |

Discrete tasks: 19/20 within SLO (95.0 %), late 0, rejected 1, failed 0, open at horizon 0.
Headline `served` = worst of (A, B, C users within SLO, tasks within SLO) = **92.86 %**.

## Energy, power, dollars

- facility energy 316.5 MWh (system 266.2, module 176.2); mean 105.5 MW, peak 106.4 MW of 500 MW
- site power cap never exceeded: **True** (max site ratio 0.289)
- energy $171k/day + capex amortised $9.57M/day = **$9.74M/day** (5-year $17.8B)

## Quantum offload

- 11 quantum-eligible units: 6 ran on a QPU, 4 classical, 1 rejected; QPU utilisation 0.8 % over 25 QPU nodes; fallbacks after failed attempts 0

| time | task | action | where | reason |
|---|---|---|---|---|
| 3.0 min | q000 (quantum_fault_tolerant) | assign | eu_north/mixed_cat/002 | Batch MILP: min cost subject to SLO, capacity, power, queue-time / quantum on eu_north/mixed_cat/002 (dc2035_cat_40k), queue wait 0 s, run 17.2 min, 1.12 expected attempts (p=0.877), ends t+21.2 min (SLO in 2.5 h) / cost $511, energy 135 kWh (facility) / no classical alternative at this accuracy |
| 9.0 min | qo000 (quantum_optimisation) | assign | eu_north/gpu_rack/002 | Batch MILP: min cost subject to SLO, capacity, power, queue-time / classical fallback of a quantum job on eu_north/gpu_rack/002: 8 modules x 90 s, ends t+91 s (SLO in 29.3 min) / cost $0.606, energy 1.5 kWh (facility) / best quantum alternative: $2.23, 67.5 Wh, ends t+15 s |
| 12.0 min | q002 (quantum_variational) | assign | eu_north/mixed_cat/001 | Batch MILP: min cost subject to SLO, capacity, power, queue-time / quantum on eu_north/mixed_cat/001 (dc2035_cat_40k), queue wait 0 s, run 3.5 min, 1.10 expected attempts (p=0.900), ends t+7.5 min (SLO in 2.5 h) / cost $99.3, energy 21.5 kWh (facility) / no classical alternative at this accuracy |
| 12.0 min | hyb000#1 (hybrid_pipeline) | assign | eu_north/gpu_rack/001 | Batch MILP: min cost subject to SLO, capacity, power, queue-time / GPU job on eu_north/gpu_rack/001: 32 modules x 11.2 min, transfer 11 s, ends t+11.4 min (SLO in 2.6 h) / cost $19.7, energy 45.1 kWh (facility) |
| 16.0 min | q003 (quantum_variational) | assign | eu_north/gpu_rack/002 | Batch MILP: min cost subject to SLO, capacity, power, queue-time / classical fallback of a quantum job on eu_north/gpu_rack/002: 4 modules x 6.0 min, ends t+6.0 min (SLO in 2.5 h) / cost $1.25, energy 3.01 kWh (facility) / best quantum alternative: $66.4, 6.7 kWh, ends t+6.4 min |
| 20.0 min | q004 (quantum_linear_algebra) | assign | eu_north/gpu_rack/001 | Batch MILP: min cost subject to SLO, capacity, power, queue-time / classical fallback of a quantum job on eu_north/gpu_rack/001: 8 modules x 22 s, ends t+24 s (SLO in 2.5 h) / cost $0.361, energy 376 Wh (facility) / no feasible quantum option: quantum: Quantum annealer (D-Wave Advantage2 class): ann |
| 24.0 min | hyb000#2 (hybrid_pipeline) | assign | eu_north/mixed_cat/002 | Batch MILP: min cost subject to SLO, capacity, power, queue-time / quantum on eu_north/mixed_cat/002 (dc2035_cat_40k), queue wait 0 s, run 9.6 min, 1.12 expected attempts (p=0.877), ends t+11.6 min (SLO in 2.4 h) / cost $300, energy 114 kWh (facility) / no classical alternative at this accuracy |
| 25.0 min | q005 (quantum_fault_tolerant) | reject | - | no feasible route: classical fallback cannot reach the required accuracy; quantum: QPU, 40k cat qubits (repetition code): 40,000 qubits hold only 199 tiles at d=101; the algorithm needs 4,392 plus a 12-tile factory; Mixed node: 16 GPU modules + 40k cat-qubit QPU on a low-latency link: 40,000 qubits  |
