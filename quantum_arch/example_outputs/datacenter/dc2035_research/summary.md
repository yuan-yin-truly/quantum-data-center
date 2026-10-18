# dc2035_research: hybrid CPU + GPU + QPU data centre

Hardware profile `mid2030s` (a SCENARIO, not a forecast). GPUs: Accelerator module (base) (5 kW per module, server overhead x1.35); PUE 1.15, network overhead 8%. Routing policy: `time_and_energy`.

There is no GPU-per-QPU conversion in this model. Quantum systems only take jobs that have a validated quantum implementation, at their own runtime, energy and acceptance probability. Power boundaries: module = accelerator modules / QPU module; system = complete servers and quantum computers; facility = system x network x PUE.

## Quantum system types

| pool | kind | system | busy power (system) | standby | busy power (facility) |
|---|---|---|---|---|---|
| sc_surface | gate | dc2035_sc_surface_300k | 2.91 MW | 2.87 MW | 3.62 MW |
| annealer | annealer | annealer | 14 kW | 10.6 kW | 17.4 kW |

## Scenarios on the same workload mix

| quantity | gpu_only | augment | replace |
|---|---|---|---|
| GPU modules | 1600 | 1600 | 800 |
| quantum systems | none | sc_surface: 1, annealer: 1 | sc_surface: 1, annealer: 1 |
| GPU utilisation (at the served demand) | 70% | 56% | 85% |
| power, module boundary | 6.13 MW | 5.15 MW | 3.67 MW |
| power, system boundary (IT) | 8.3 MW | 9.86 MW | 7.87 MW |
| power, facility boundary | 10.3 MW | 12.2 MW | 9.77 MW |
| share of GPU demand moved to quantum | 0.0% | 23.0% | 23.0% |
| capacity: max sustainable demand vs GPU-only (same mix, scaled) | 1.00x | 1.26x | 0.63x |
| ordinary-AI headroom if other classes keep their demand (GPU modules) | 688 | 916 | 236 |
| ... as a ratio to GPU-only | 1.00x | 1.33x | 0.34x |
| share of the baseline demand actually served | 100% | 100% | 76% |
| facility J per baseline GPU-second of accepted work | 9203 | 1.093e+04 | 1.145e+04 |
| ... relative to GPU-only | 1.000 | 1.188 | 1.244 |

### gpu_only: job classes

| class | demand share | moved to quantum | GPU turnaround | quantum turnaround | mean turnaround | facility energy per accepted answer | classical cost / break-even (GPU-module h per job) | note |
|---|---|---|---|---|---|---|---|---|
| llm_serving | 15% | — | 3.99 ms | — | 3.99 ms | 35.4 J | — |  |
| llm_training | 25% | — | 4.28 d | — | 4.28 d | 164 MWh | — |  |
| engineering_simulation | 20% | — | 8.12 h | — | 8.12 h | 1.14 MWh | — |  |
| materials_chemistry | 30% | 0.0% | 12.9 h | — | 12.9 h | 6.82 MWh | — | no quantum system of this kind in the scenario |
| scheduling_optimisation | 10% | 0.0% | 10.2 s | — | 10.2 s | 0.197 kWh | — | no quantum system of this kind in the scenario |

### augment: job classes

| class | demand share | moved to quantum | GPU turnaround | quantum turnaround | mean turnaround | facility energy per accepted answer | classical cost / break-even (GPU-module h per job) | note |
|---|---|---|---|---|---|---|---|---|
| llm_serving | 15% | — | 3.99 ms | — | 3.99 ms | 37.1 J | — |  |
| llm_training | 25% | — | 4.28 d | — | 4.28 d | 172 MWh | — |  |
| engineering_simulation | 20% | — | 8 h | — | 8 h | 1.19 MWh | — |  |
| materials_chemistry | 30% | 60.0% | 12 h | 113 min | 5.93 h | 11.5 MWh | 768 / 121 |  |
| scheduling_optimisation | 10% | 50.0% | 10 s | 4.39 s | 7.19 s | 0.123 kWh | 0.0222 / 0.000305 |  |

| quantum pool | systems | utilisation | queue wait | system power | facility power |
|---|---|---|---|---|---|
| sc_surface | 1 | 7% | 40.3 s | 2.87 MW | 3.56 MW |
| annealer | 1 | 29% | 82.2 ms | 11.6 kW | 14.4 kW |

### replace: job classes

| class | demand share | moved to quantum | GPU turnaround | quantum turnaround | mean turnaround | facility energy per accepted answer | classical cost / break-even (GPU-module h per job) | note |
|---|---|---|---|---|---|---|---|---|
| llm_serving | 15% | — | 3.99 ms | — | 3.99 ms | 34.3 J | — |  |
| llm_training | 25% | — | 18 d | — | 18 d | 158 MWh | — |  |
| engineering_simulation | 20% | — | 9.37 h | — | 9.37 h | 1.1 MWh | — |  |
| materials_chemistry | 30% | 60.0% | 12.2 h | 114 min | 6.01 h | 13.7 MWh | 768 / 121 |  |
| scheduling_optimisation | 10% | 50.0% | 10 s | 4.37 s | 7.19 s | 0.115 kWh | 0.0222 / 0.000305 |  |

> cannot carry the baseline demand at the 85% utilisation cap; figures below are for the 76% of the demand it can serve


| quantum pool | systems | utilisation | queue wait | system power | facility power |
|---|---|---|---|---|---|
| sc_surface | 1 | 6% | 30.1 s | 2.87 MW | 3.56 MW |
| annealer | 1 | 22% | 57.2 ms | 11.4 kW | 14.1 kW |

## Break-even movable-work fraction

Smallest share of the GPU demand that must be movable (eligible AND mapped) for a scenario to match the GPU-only facility. The closed-form limit for REPLACE is: break-even = fraction of GPUs removed, when quantum capacity suffices.

| scenario | movable share for capacity parity | movable share for energy parity |
|---|---|---|
| augment | 0.0% | 50.3% |
| replace | 57.0% | 40.8% |

| movable share | augment: capacity / energy (vs GPU-only) | replace: capacity / energy (vs GPU-only) |
|---|---|---|
| 0% | 1.00x / 1.347 | 0.50x / 1.561 |
| 10% | 1.10x / 1.278 | 0.55x / 1.423 |
| 20% | 1.21x / 1.209 | 0.61x / 1.286 |
| 30% | 1.36x / 1.140 | 0.68x / 1.148 |
| 40% | 1.53x / 1.071 | 0.77x / 1.010 |
| 50% | 1.70x / 1.002 | 0.90x / 0.911 |
| 60% | 1.90x / 0.933 | 1.04x / 0.842 |
| 70% | 2.17x / 0.866 | 1.18x / 0.775 |
| 80% | 2.51x / 0.811 | 1.37x / 0.720 |
| 90% | 2.63x / 0.757 | 1.63x / 0.666 |
| 100% | 2.63x / 0.702 | 2.02x / 0.611 |

Capacity = largest demand (same mix, scaled) the facility sustains at the utilisation cap, relative to GPU-only. Energy = facility joules per baseline GPU-second of accepted work, relative to GPU-only (below 1 is better).

> Scenario analysis, not a forecast: job classes, classical costs, mapping quality and hardware profile are inputs. No GPU-per-QPU conversion exists in this model.
