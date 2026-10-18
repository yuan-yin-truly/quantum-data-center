# Architecture v2: pooled GPU nodes, CPU sandbox pool, parking memory, shared QPU service (agents park while a QPU sub-task runs)

Pod of 1,000,000 users, mixed classes, 50 MW facility cap. GPU-only reference = same task load, calls run classically on GPUs; calls that would cost more than 200 module-hours classically are **not served** there. One module-hour costs about $5.4 (amortised capex incl. facility + energy). **Class mix, call densities, classical costs and induced demand are assumptions.**

| class | users | bg tasks/day | calls per bg task | kernel | classical cost per call (module-h) |
|---|---:|---:|---:|---|---:|
| coding_agents | 550,000 | 16,500,000 | 0.0002 | vqe_20q | 0.4 |
| materials | 100,000 | 1,200,000 | 0.01 | vqe_50q | 160 |
| chemistry | 100,000 | 1,200,000 | 0.01 | chemistry_small | 768 |
| biology | 70,000 | 840,000 | 0.005 | vqe_50q | 160 |
| mechanical | 100,000 | 1,000,000 | 0.02 | vqe_20q | 0.4 |
| finance | 80,000 | 800,000 | 0.02 | qla_scalar_explicit_1m | 0.05 |

## Induced-demand factor x1

| design | QPUs | GPU modules (racks) | CPU sockets | parking-memory TB | mean MW | peak MW | kJ/task | k$/day | calls on QPU / classical / unserved | QPU util | wait p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| GPU-only reference | 0 | 124,359 (1,944) | 0 | 0.0 | 903.9 | 903.9 | 2503 | 15,446 | 0 / 55,500 / 12,000 | 0% | 0 s |
| Parked sessions + QPU service | 43 | 4,360 (69) | 2,779 | 2.2 | 48.4 | 48.5 | 134 | 3,545 | 28,197 / 39,300 / 3 | 94% | 224 s |
| Hold GPU during QPU wait + QPU service | 43 | 4,360 (69) | 2,779 | 0.0 | 48.5 | 48.5 | 134 | 3,545 | 28,197 / 39,300 / 3 | 94% | 224 s |

Cheapest by sizing objective (cost + unserved calls valued at the classical cap): **park and hold tie (within 0.5 %)**. Parked design vs reference: cost 0.23x, mean power 0.05x, unserved calls 12,000 -> 3. Classes sent to the QPU service: materials, chemistry, biology.

| class | calls/day | on QPU | classical | unserved | reference: classical | reference: unserved |
|---|---:|---:|---:|---:|---:|---:|
| coding_agents | 3,300 | 0 | 3,300 | 0 | 3,300 | 0 |
| materials | 12,000 | 12,000 | 0 | 0 | 12,000 | 0 |
| chemistry | 12,000 | 11,997 | 0 | 3 | 0 | 12,000 |
| biology | 4,200 | 4,200 | 0 | 0 | 4,200 | 0 |
| mechanical | 20,000 | 0 | 20,000 | 0 | 20,000 | 0 |
| finance | 16,000 | 0 | 16,000 | 0 | 16,000 | 0 |

## Induced-demand factor x3

| design | QPUs | GPU modules (racks) | CPU sockets | parking-memory TB | mean MW | peak MW | kJ/task | k$/day | calls on QPU / classical / unserved | QPU util | wait p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| GPU-only reference | 0 | 365,296 (5,708) | 0 | 0.0 | 2652.0 | 2652.0 | 7344 | 45,345 | 0 / 166,500 / 36,000 | 0% | 0 s |
| Parked sessions + QPU service | 128 | 5,298 (83) | 2,779 | 10.1 | 82.2 | 82.3 | 228 | 9,483 | 84,569 / 117,900 / 31 | 95% | 405 s |
| Hold GPU during QPU wait + QPU service | 128 | 5,300 (83) | 2,779 | 0.0 | 82.2 | 82.3 | 228 | 9,483 | 84,569 / 117,900 / 31 | 95% | 405 s |

Cheapest by sizing objective (cost + unserved calls valued at the classical cap): **park and hold tie (within 0.5 %)**. Parked design vs reference: cost 0.21x, mean power 0.03x, unserved calls 36,000 -> 31. Classes sent to the QPU service: materials, chemistry, biology.

| class | calls/day | on QPU | classical | unserved | reference: classical | reference: unserved |
|---|---:|---:|---:|---:|---:|---:|
| coding_agents | 9,900 | 0 | 9,900 | 0 | 9,900 | 0 |
| materials | 36,000 | 36,000 | 0 | 0 | 36,000 | 0 |
| chemistry | 36,000 | 35,969 | 0 | 31 | 0 | 36,000 |
| biology | 12,600 | 12,600 | 0 | 0 | 12,600 | 0 |
| mechanical | 60,000 | 0 | 60,000 | 0 | 60,000 | 0 |
| finance | 48,000 | 0 | 48,000 | 0 | 48,000 | 0 |

## Induced-demand factor x10

| design | QPUs | GPU modules (racks) | CPU sockets | parking-memory TB | mean MW | peak MW | kJ/task | k$/day | calls on QPU / classical / unserved | QPU util | wait p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| GPU-only reference | 0 | 1,208,576 (18,884) | 0 | 0.0 | 8770.3 | 8770.3 | 24287 | 149,991 | 0 / 555,000 / 120,000 | 0% | 0 s |
| Parked sessions + QPU service | 422 | 8,588 (135) | 2,781 | 33.1 | 199.2 | 199.4 | 552 | 30,029 | 281,820 / 393,001 / 179 | 96% | 503 s |
| Hold GPU during QPU wait + QPU service | 422 | 8,595 (135) | 2,781 | 0.0 | 199.2 | 199.5 | 552 | 30,030 | 281,820 / 393,001 / 179 | 96% | 503 s |

Cheapest by sizing objective (cost + unserved calls valued at the classical cap): **park and hold tie (within 0.5 %)**. Parked design vs reference: cost 0.20x, mean power 0.02x, unserved calls 120,000 -> 179. Classes sent to the QPU service: materials, chemistry, biology.

| class | calls/day | on QPU | classical | unserved | reference: classical | reference: unserved |
|---|---:|---:|---:|---:|---:|---:|
| coding_agents | 33,000 | 0 | 33,000 | 0 | 33,000 | 0 |
| materials | 120,000 | 119,999 | 1 | 0 | 120,000 | 0 |
| chemistry | 120,000 | 119,821 | 0 | 179 | 0 | 120,000 |
| biology | 42,000 | 42,000 | 0 | 0 | 42,000 | 0 |
| mechanical | 200,000 | 0 | 200,000 | 0 | 200,000 | 0 |
| finance | 160,000 | 0 | 160,000 | 0 | 160,000 | 0 |

## Sensitivity (induced factor 1)

`GPU-only k$/day` leaves out the calls the reference cannot serve; the `cheapest` column counts them at the classical cap. Park and hold differ by under 0.5 % in every row, i.e. they tie.

| changed input | value | cheapest | park k$/day | hold k$/day | GPU-only k$/day | park QPUs |
|---|---|---|---:|---:|---:|---:|
| quantum.capex_scale | 0.5 | hold | 2,131 | 2,131 | 15,446 | 43 |
| quantum.capex_scale | 2.0 | park | 6,263 | 6,264 | 15,446 | 42 |
| design.classical_max_module_hours | 50 | park | 3,476 | 3,476 | 595 | 42 |
| design.classical_max_module_hours | 1000 | park | 3,558 | 3,558 | 68,393 | 43 |
| design.classical_cost_scale | 0.1 | park | 3,470 | 3,471 | 7,287 | 42 |
| design.classical_cost_scale | 0.02 | gpu_only | 1,884 | 1,884 | 1,884 | 0 |
| quantum.max_wait_s | 300 | hold | 11,272 | 11,272 | 15,446 | 100 |
| quantum.iterations_per_call | 1000000 | hold | 3,545 | 3,545 | 15,446 | 43 |
| parking.recompute_share | 1.0 | hold | 3,545 | 3,545 | 15,446 | 43 |
| parking.hbm_gb_per_module | 256 | park | 3,545 | 3,545 | 15,446 | 43 |

## Users served within the pod's 50 MW peak facility cap

| induced factor | GPU-only | parked design |
|---|---:|---:|
| x1 | < 200,000 (below the search range) | 1,031,250 |
| x3 | < 200,000 (below the search range) | 604,688 |

Users are scaled with the class mix fixed; the reference does not serve the calls above the classical cap in either case.
