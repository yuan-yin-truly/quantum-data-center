# Use case B: specialised vs integrated vs mixed nodes (GPU-only reference always shown)

Pod of 1,000,000 agent developers (12 interactive + 30 background tasks of 80 steps per user and day), cap 50 MW facility. QPU = dc2035_cat_40k (270 kW busy, 258 kW standby, $120M assumed), kernel vqe_50q (43.8 s per call, 11.7 MJ). **All unit costs, call densities and classical costs are assumptions; the quantum side is read from quantum_arch.**

`calls/task` = quantum-eligible tool calls per background task; `X` = cost of the best classical method for such a call at equal accuracy, GPU module-hours.


## Base comparison: 0.001 calls per background task, X = 1 module-hours

| design | QPUs (node + hall) | GPU modules | mean MW (GPU / CPU / QPU, IT) | peak MW | kJ/task | k$/day | $/day vs GPU-only | calls on QPU | QPU util | wait p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPU-only reference | 0 | 7,363 | 54.6 (45.4 / 1.0 / 0.0) | 54.6 | 112 | 932 | 1.00 | 0/30,000 | 0% | 0 s |
| Specialised pools (shared QPU hall) | 1 (0+1) | 7,279 | 54.6 (44.9 / 1.2 / 0.3) | 54.6 | 112 | 998 | 1.07 | 1,807/30,000 | 97% | 1800 s |
| Integrated nodes (one QPU per node) | 1 (1+0) | 7,275 | 54.3 (44.9 / 1.0 / 0.3) | 54.3 | 112 | 990 | 1.06 | 1,893/30,000 | 97% | 1800 s |
| Mix (node QPUs + shared hall) | 2 (1+1) | 7,188 | 54.0 (44.3 / 1.0 / 0.5) | 54.0 | 111 | 1,048 | 1.12 | 3,781/30,000 | 97% | 1800 s |
| Integrated at 16 GPU modules per QPU (server scale) | 374 (374+0) | 5,974 | 158.2 (36.9 / 1.0 / 96.7) | 163.2 | 325 | 26,373 | 28.28 | 30,000/30,000 | 4% | 50 s |
| Integrated at 64 GPU modules per QPU (server scale) | 94 (94+0) | 5,974 | 73.3 (36.9 / 1.0 / 24.4) | 74.4 | 151 | 7,199 | 7.72 | 30,000/30,000 | 16% | 124 s |

Cheapest: **GPU-only reference**.

## Base comparison: 0.001 calls per background task, X = 10 module-hours

| design | QPUs (node + hall) | GPU modules | mean MW (GPU / CPU / QPU, IT) | peak MW | kJ/task | k$/day | $/day vs GPU-only | calls on QPU | QPU util | wait p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPU-only reference | 0 | 19,863 | 144.8 (122.5 / 0.6 / 0.0) | 144.8 | 298 | 2,471 | 1.00 | 0/30,000 | 0% | 0 s |
| Specialised pools (shared QPU hall) | 16 (0+16) | 6,369 | 52.7 (39.3 / 1.2 / 4.3) | 52.7 | 108 | 1,912 | 0.77 | 29,147/30,000 | 96% | 727 s |
| Integrated nodes (one QPU per node) | 15 (15+0) | 6,684 | 54.4 (41.2 / 1.0 / 4.0) | 54.5 | 112 | 1,876 | 0.76 | 28,465/30,000 | 96% | 1763 s |
| Mix (node QPUs + shared hall) | 16 (4+12) | 6,268 | 51.8 (38.7 / 1.0 / 4.3) | 51.8 | 106 | 1,894 | 0.77 | 29,364/30,000 | 96% | 857 s |
| Integrated at 16 GPU modules per QPU (server scale) | 374 (374+0) | 5,974 | 158.2 (36.9 / 1.0 / 96.7) | 163.2 | 325 | 26,373 | 10.67 | 30,000/30,000 | 4% | 50 s |
| Integrated at 64 GPU modules per QPU (server scale) | 94 (94+0) | 5,974 | 73.3 (36.9 / 1.0 / 24.4) | 74.4 | 151 | 7,199 | 2.91 | 30,000/30,000 | 16% | 124 s |

Cheapest: **Integrated nodes (one QPU per node)**.

## Base comparison: 0.001 calls per background task, X = 100 module-hours

| design | QPUs (node + hall) | GPU modules | mean MW (GPU / CPU / QPU, IT) | peak MW | kJ/task | k$/day | $/day vs GPU-only | calls on QPU | QPU util | wait p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| GPU-only reference | 0 | 144,863 | 1051.8 (893.7 / 0.6 / 0.0) | 1051.8 | 2164 | 17,983 | 1.00 | 0/30,000 | 0% | 0 s |
| Specialised pools (shared QPU hall) | 17 (0+17) | 5,974 | 50.2 (36.9 / 1.2 / 4.6) | 50.2 | 103 | 1,932 | 0.11 | 30,000/30,000 | 94% | 190 s |
| Integrated nodes (one QPU per node) | 17 (17+0) | 6,446 | 53.3 (39.8 / 1.0 / 4.6) | 53.4 | 110 | 1,984 | 0.11 | 29,898/30,000 | 89% | 1484 s |
| Mix (node QPUs + shared hall) | 17 (8+9) | 5,974 | 49.9 (36.9 / 1.0 / 4.6) | 50.0 | 103 | 1,926 | 0.11 | 30,000/30,000 | 92% | 315 s |
| Integrated at 16 GPU modules per QPU (server scale) | 374 (374+0) | 5,974 | 158.2 (36.9 / 1.0 / 96.7) | 163.2 | 325 | 26,373 | 1.47 | 30,000/30,000 | 4% | 50 s |
| Integrated at 64 GPU modules per QPU (server scale) | 94 (94+0) | 5,974 | 73.3 (36.9 / 1.0 / 24.4) | 74.4 | 151 | 7,199 | 0.40 | 30,000/30,000 | 16% | 124 s |

Cheapest: **Mix (node QPUs + shared hall)**.

## Which design wins, over the unknowns (cheapest total cost per day)

| calls/task \ X (module-h) | 0.03 | 0.1 | 0.3 | 1 | 3 | 10 | 30 | 100 |
|---|---|---|---|---|---|---|---|---|
| 0 | GPU | GPU | GPU | GPU | GPU | GPU | GPU | GPU |
| 0.0001 | GPU | GPU | GPU | GPU | GPU | node (0.96) | node (0.71) | node (0.36) |
| 0.0003 | GPU | GPU | GPU | GPU | GPU | mix (0.87) | mix (0.48) | mix (0.19) |
| 0.001 | GPU | GPU | GPU | GPU | GPU | node (0.76) | mix (0.33) | mix (0.11) |
| 0.003 | GPU | GPU | GPU | GPU | GPU | node (0.69) | mix (0.25) | mix (0.08) |
| 0.01 | GPU | GPU | GPU | GPU | GPU | node (0.66) | mix (0.23) | mix (0.07) |

Cell = cheapest design (ratio of its cost to the GPU-only reference in brackets). `GPU` = no QPU pays off; `pool` = shared QPU hall; `node` = one QPU per node; `mix` = both.


## Sensitivity at the base cell (1e-3 calls per task, X = 10)

| changed input | value | cheapest | pool k$/day | node k$/day | mix k$/day | GPU-only k$/day |
|---|---|---|---:|---:|---:|---:|
| quantum.iterations_per_call | 1000.0 | mix | 1,863 | 1,876 | 1,857 | 2,471 |
| quantum.iterations_per_call | 100000.0 | node | 2,324 | 1,876 | 2,125 | 2,471 |
| quantum.iterations_per_call | 1000000.0 | node | 2,539 | 1,876 | 2,439 | 2,471 |
| quantum.capex_scale | 0.25 | mix | 1,093 | 1,093 | 1,087 | 2,471 |
| quantum.capex_scale | 0.5 | node | 1,373 | 1,357 | 1,367 | 2,471 |
| quantum.capex_scale | 2.0 | GPU | 2,521 | 2,498 | 2,524 | 2,471 |
| quantum.max_wait_s | 300 | node | 2,296 | 1,986 | 2,047 | 2,471 |
| quantum.max_wait_s | 7200 | node | 1,853 | 1,799 | 1,842 | 2,471 |
| quantum.workload | vqe_20q | node | 1,178 | 1,104 | 1,104 | 2,471 |
| quantum.workload | chemistry_small | GPU | 2,539 | 2,519 | 2,568 | 2,471 |
| cpu.host_cpu_spare_fraction | 0.0 | node | 1,912 | 1,883 | 1,900 | 2,491 |
| cpu.host_cpu_spare_fraction | 0.9 | node | 1,912 | 1,871 | 1,889 | 2,471 |
| quantum.duration_cv | 0.0 | node | 1,911 | 1,872 | 1,890 | 2,471 |
| quantum.duration_cv | 1.0 | node | 1,911 | 1,885 | 1,891 | 2,471 |

## Robustness to the random call stream (base cell, 5 seeds)

| seed | cheapest | pool | node | mix | GPU-only (k$/day) |
|---|---|---:|---:|---:|---:|
| 1 | node | 1,911 | 1,874 | 1,891 | 2,471 |
| 2 | node | 1,910 | 1,869 | 1,891 | 2,471 |
| 3 | node | 1,909 | 1,870 | 1,890 | 2,471 |
| 4 | node | 1,907 | 1,868 | 1,886 | 2,471 |
| 5 | node | 1,911 | 1,878 | 1,894 | 2,471 |

## Users served within the pod's 50 MW peak facility cap

| calls/task | X | GPU-only | cheapest hybrid |
|---|---|---:|---:|
| 0.001 | 3 | 664,844 | 664,844 |
| 0.001 | 10 | 342,188 | 921,875 |
| 0.0003 | 30 | 369,531 | 1,047,656 |

Bisection on the user count, each point re-sized; the answer is the largest tested user count under the cap.
