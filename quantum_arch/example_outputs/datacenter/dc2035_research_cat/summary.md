# dc2035_research_cat: hybrid CPU + GPU + QPU data centre

Hardware profile `mid2030s` (a SCENARIO, not a forecast). GPUs: Accelerator module (base) (5 kW per module, server overhead x1.35); PUE 1.15, network overhead 8%. Routing policy: `time_and_energy`.

There is no GPU-per-QPU conversion in this model. Quantum systems only take jobs that have a validated quantum implementation, at their own runtime, energy and acceptance probability. Power boundaries: module = accelerator modules / QPU module; system = complete servers and quantum computers; facility = system x network x PUE.

## Quantum system types

| pool | kind | system | busy power (system) | standby | busy power (facility) |
|---|---|---|---|---|---|
| cat_repetition | gate | dc2035_cat_40k | 270 kW | 258 kW | 335 kW |
| annealer | annealer | annealer | 14 kW | 10.6 kW | 17.4 kW |

## Scenarios on the same workload mix

| quantity | gpu_only | augment | replace |
|---|---|---|---|
| GPU modules | 1600 | 1600 | 800 |
| quantum systems | none | cat_repetition: 2, annealer: 1 | cat_repetition: 2, annealer: 1 |
| GPU utilisation (at the served demand) | 70% | 56% | 85% |
| power, module boundary | 6.13 MW | 5.15 MW | 3.67 MW |
| power, system boundary (IT) | 8.3 MW | 7.5 MW | 5.52 MW |
| power, facility boundary | 10.3 MW | 9.32 MW | 6.85 MW |
| share of GPU demand moved to quantum | 0.0% | 23.0% | 23.0% |
| capacity: max sustainable demand vs GPU-only (same mix, scaled) | 1.00x | 1.26x | 0.63x |
| ordinary-AI headroom if other classes keep their demand (GPU modules) | 688 | 916 | 236 |
| ... as a ratio to GPU-only | 1.00x | 1.33x | 0.34x |
| share of the baseline demand actually served | 100% | 100% | 76% |
| facility J per baseline GPU-second of accepted work | 9203 | 8320 | 8024 |
| ... relative to GPU-only | 1.000 | 0.904 | 0.872 |

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
| llm_serving | 15% | — | 3.99 ms | — | 3.99 ms | 37.2 J | — |  |
| llm_training | 25% | — | 4.28 d | — | 4.28 d | 172 MWh | — |  |
| engineering_simulation | 20% | — | 8 h | — | 8 h | 1.19 MWh | — |  |
| materials_chemistry | 30% | 60.0% | 12 h | 100 min | 5.8 h | 4.76 MWh | 768 / 4.27 |  |
| scheduling_optimisation | 10% | 50.0% | 10 s | 4.39 s | 7.19 s | 0.123 kWh | 0.0222 / 0.000305 |  |

| quantum pool | systems | utilisation | queue wait | system power | facility power |
|---|---|---|---|---|---|
| cat_repetition | 2 | 1% | 36.1 ms | 516 kW | 641 kW |
| annealer | 1 | 29% | 82.2 ms | 11.6 kW | 14.4 kW |

### replace: job classes

| class | demand share | moved to quantum | GPU turnaround | quantum turnaround | mean turnaround | facility energy per accepted answer | classical cost / break-even (GPU-module h per job) | note |
|---|---|---|---|---|---|---|---|---|
| llm_serving | 15% | — | 3.99 ms | — | 3.99 ms | 34.3 J | — |  |
| llm_training | 25% | — | 18.1 d | — | 18.1 d | 158 MWh | — |  |
| engineering_simulation | 20% | — | 9.38 h | — | 9.38 h | 1.1 MWh | — |  |
| materials_chemistry | 30% | 60.0% | 12.2 h | 101 min | 5.88 h | 4.96 MWh | 768 / 4.27 |  |
| scheduling_optimisation | 10% | 50.0% | 10 s | 4.37 s | 7.19 s | 0.115 kWh | 0.0222 / 0.000305 |  |

> cannot carry the baseline demand at the 85% utilisation cap; figures below are for the 76% of the demand it can serve


| quantum pool | systems | utilisation | queue wait | system power | facility power |
|---|---|---|---|---|---|
| cat_repetition | 2 | 1% | 21 ms | 516 kW | 641 kW |
| annealer | 1 | 22% | 57.2 ms | 11.4 kW | 14.1 kW |

## Break-even movable-work fraction

Smallest share of the GPU demand that must be movable (eligible AND mapped) for a scenario to match the GPU-only facility. The closed-form limit for REPLACE is: break-even = fraction of GPUs removed, when quantum capacity suffices.

| scenario | movable share for capacity parity | movable share for energy parity |
|---|---|---|
| augment | 0.0% | 9.2% |
| replace | 56.9% | 9.8% |

| movable share | augment: capacity / energy (vs GPU-only) | replace: capacity / energy (vs GPU-only) |
|---|---|---|
| 0% | 1.00x / 1.063 | 0.50x / 1.095 |
| 10% | 1.10x / 0.994 | 0.55x / 0.998 |
| 20% | 1.22x / 0.925 | 0.61x / 0.901 |
| 30% | 1.36x / 0.856 | 0.68x / 0.804 |
| 40% | 1.53x / 0.786 | 0.77x / 0.707 |
| 50% | 1.70x / 0.717 | 0.90x / 0.626 |
| 60% | 1.91x / 0.648 | 1.04x / 0.557 |
| 70% | 2.17x / 0.581 | 1.19x / 0.490 |
| 80% | 2.52x / 0.526 | 1.38x / 0.435 |
| 90% | 3.01x / 0.471 | 1.64x / 0.380 |
| 100% | 3.72x / 0.416 | 2.03x / 0.325 |

Capacity = largest demand (same mix, scaled) the facility sustains at the utilisation cap, relative to GPU-only. Energy = facility joules per baseline GPU-second of accepted work, relative to GPU-only (below 1 is better).

> Scenario analysis, not a forecast: job classes, classical costs, mapping quality and hardware profile are inputs. No GPU-per-QPU conversion exists in this model.
