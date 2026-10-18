# dc2035_ai_serving: hybrid CPU + GPU + QPU data centre

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
| GPU utilisation (at the served demand) | 70% | 69% | 85% |
| power, module boundary | 6.13 MW | 6.05 MW | 3.67 MW |
| power, system boundary (IT) | 8.3 MW | 11.1 MW | 7.87 MW |
| power, facility boundary | 10.3 MW | 13.7 MW | 9.77 MW |
| share of GPU demand moved to quantum | 0.0% | 1.9% | 1.9% |
| capacity: max sustainable demand vs GPU-only (same mix, scaled) | 1.00x | 1.02x | 0.51x |
| ordinary-AI headroom if other classes keep their demand (GPU modules) | 1192 | 1210 | 530 |
| ... as a ratio to GPU-only | 1.00x | 1.02x | 0.44x |
| share of the baseline demand actually served | 100% | 100% | 62% |
| facility J per baseline GPU-second of accepted work | 9203 | 1.228e+04 | 1.413e+04 |
| ... relative to GPU-only | 1.000 | 1.334 | 1.536 |

### gpu_only: job classes

| class | demand share | moved to quantum | GPU turnaround | quantum turnaround | mean turnaround | facility energy per accepted answer | classical cost / break-even (GPU-module h per job) | note |
|---|---|---|---|---|---|---|---|---|
| llm_serving | 50% | — | 3.99 ms | — | 3.99 ms | 35.4 J | — |  |
| llm_training | 35% | — | 7.25 d | — | 7.25 d | 164 MWh | — |  |
| engineering_simulation | 10% | — | 8.59 h | — | 8.59 h | 1.14 MWh | — |  |
| materials_chemistry | 3% | 0.0% | 25.3 h | — | 25.3 h | 6.82 MWh | — | no quantum system of this kind in the scenario |
| scheduling_optimisation | 2% | 0.0% | 13.6 s | — | 13.6 s | 0.197 kWh | — | no quantum system of this kind in the scenario |

### augment: job classes

| class | demand share | moved to quantum | GPU turnaround | quantum turnaround | mean turnaround | facility energy per accepted answer | classical cost / break-even (GPU-module h per job) | note |
|---|---|---|---|---|---|---|---|---|
| llm_serving | 50% | — | 3.99 ms | — | 3.99 ms | 35.6 J | — |  |
| llm_training | 35% | — | 7.25 d | — | 7.25 d | 164 MWh | — |  |
| engineering_simulation | 10% | — | 8.59 h | — | 8.59 h | 1.14 MWh | — |  |
| materials_chemistry | 3% | 30.0% | 19.5 h | 2.64 h | 14.4 h | 86.4 MWh | 768 / 121 |  |
| scheduling_optimisation | 2% | 50.0% | 10.4 s | 4.39 s | 7.4 s | 0.129 kWh | 0.0222 / 0.000305 |  |

| quantum pool | systems | utilisation | queue wait | system power | facility power |
|---|---|---|---|---|---|
| sc_surface | 1 | 0% | 1.87 s | 2.87 MW | 3.56 MW |
| annealer | 1 | 6% | 12.4 ms | 10.8 kW | 13.5 kW |

### replace: job classes

| class | demand share | moved to quantum | GPU turnaround | quantum turnaround | mean turnaround | facility energy per accepted answer | classical cost / break-even (GPU-module h per job) | note |
|---|---|---|---|---|---|---|---|---|
| llm_serving | 50% | — | 3.99 ms | — | 3.99 ms | 34.3 J | — |  |
| llm_training | 35% | — | 54.8 d | — | 54.8 d | 158 MWh | — |  |
| engineering_simulation | 10% | — | 16.1 h | — | 16.1 h | 1.1 MWh | — |  |
| materials_chemistry | 3% | 30.0% | 15.7 h | 2.25 h | 11.7 h | 137 MWh | 768 / 121 |  |
| scheduling_optimisation | 2% | 50.0% | 13.4 s | 4.87 s | 9.13 s | 0.133 kWh | 0.0222 / 0.000305 |  |

> cannot carry the baseline demand at the 85% utilisation cap; figures below are for the 62% of the demand it can serve


| quantum pool | systems | utilisation | queue wait | system power | facility power |
|---|---|---|---|---|---|
| sc_surface | 1 | 0% | 1.15 s | 2.87 MW | 3.56 MW |
| annealer | 1 | 4% | 7.5 ms | 10.8 kW | 13.4 kW |

## Break-even movable-work fraction

Smallest share of the GPU demand that must be movable (eligible AND mapped) for a scenario to match the GPU-only facility. The closed-form limit for REPLACE is: break-even = fraction of GPUs removed, when quantum capacity suffices.

| scenario | movable share for capacity parity | movable share for energy parity |
|---|---|---|
| augment | 0.0% | 75.4% |
| replace | 93.6% | 54.0% |

| movable share | augment: capacity / energy (vs GPU-only) | replace: capacity / energy (vs GPU-only) |
|---|---|---|
| 0% | 1.00x / 1.347 | 0.50x / 1.561 |
| 10% | 1.09x / 1.279 | 0.55x / 1.426 |
| 20% | 1.20x / 1.212 | 0.60x / 1.292 |
| 30% | 1.26x / 1.151 | 0.68x / 1.157 |
| 40% | 1.33x / 1.117 | 0.73x / 1.077 |
| 50% | 1.40x / 1.084 | 0.76x / 1.022 |
| 60% | 1.48x / 1.051 | 0.81x / 0.967 |
| 70% | 1.57x / 1.018 | 0.86x / 0.927 |
| 80% | 1.67x / 0.985 | 0.91x / 0.893 |
| 90% | 1.78x / 0.951 | 0.97x / 0.860 |
| 100% | 1.92x / 0.918 | 1.05x / 0.827 |

Capacity = largest demand (same mix, scaled) the facility sustains at the utilisation cap, relative to GPU-only. Energy = facility joules per baseline GPU-second of accepted work, relative to GPU-only (below 1 is better).

> Scenario analysis, not a forecast: job classes, classical costs, mapping quality and hardware profile are inputs. No GPU-per-QPU conversion exists in this model.
