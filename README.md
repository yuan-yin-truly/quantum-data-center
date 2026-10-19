# Quantum Data Center

**▶ Live site: [yuan-yin-truly.github.io/quantum-data-center/](https://yuan-yin-truly.github.io/quantum-data-center/)**.

[![A 2035 data center: GPU racks beside a quantum computer cryostat](web/public/images/hero.webp)](https://yuan-yin-truly.github.io/quantum-data-center/)

**Should a 2035 AI data center have quantum computers in it, and if so, how should it be built?**

We answer with simulation, always against a GPU-only data center as the reference, for a world of AI agents used by developers, chemists, materials scientists, biologists, engineers and financial analysts.

**The problem we take on.** In 2035, 50M agent developers launch 1.5B background agent tasks a day. If just one in a million calls a high-accuracy chemistry tool, a GPU sandbox needs about 48k more GPUs (282 MW, $7.9B), which pushes the fleet over the 500 MW cap. Six QPUs do the same calls in 1.7 MW.

## What we built

1. **The chip:** cryogenic heat budgets and thermal layouts for quantum and classical hardware.
2. **The data center:** power, cooling and cost across six sites within 500 MW.
3. **The numbers:** energy, cost and users served, side by side with a GPU-only design.
4. **The scheduler:** which task goes to a GPU, a CPU sandbox or a QPU, and what happens while an agent waits (it parks its session and frees the GPU).

![Architecture: a scheduler node sends LLM steps to a pool of GPU nodes and quantum-eligible calls to a shared QPU service, while agents park their sessions in a parking memory during the QPU job](web/public/images/architecture.svg?v=3)

## What we learned

- Quantum hardware pays off only above a break-even that depends on two things nobody has measured yet: how often agent work contains a quantum-friendly step, and what the best classical method costs for it. We map that break-even instead of guessing. With our cost assumptions, a QPU wins on cost once the classical method needs more than about 55 GPU-hours per call (about 4 on energy).
- Where the QPUs sit matters less than expected. Shared QPU halls, per-node QPUs and mixtures come out within a few percent of each other (about one QPU, not a significant difference), while a QPU next to every server is far more expensive.
- Every number comes with its assumptions, and every study can be rerun.

The [team page](https://yuan-yin-truly.github.io/quantum-data-center/) is built from `web/`. It opens with the problem statement and a GPU-only vs GPU + QPU comparison for the three cases, then the architecture, the task-flow and parking-memory simulations, and the research notes. The QC Hybrid Simulator (`thermal_lab/`) has its own page, linked from the top bar.

## Run the page locally

```bash
cd web
npm install
npm run dev      # http://localhost:5173
npm run build    # typecheck + static build into web/dist
```

Pushing to `main` deploys to GitHub Pages through `.github/workflows/pages.yml`. Turn it on once under Settings → Pages → Source: GitHub Actions.

## What's in the repo

```
web/                  the team page (problem statement, comparison, task flow, research notes)
thermal_lab/          QC Hybrid Simulator: annual GPU + QPU rollout, router comparison and playback
dc_sim/               discrete-event simulator of a mixed GPU/QPU data center with one scheduling node (README_DC_SIM.md)
quantum_arch/         quantum processors with their classical hardware: logical qubits, power, cryostat heat (README_QUANTUM.md)
design_loop/          automated design-space search for a hybrid package, local only (README_DESIGN_LOOP.md)
hill_variant/         local quantum variant of the Beat the Hotspot hill, used by design_loop
docs/                 research notes and workstream notes
tests/                Python tests for quantum_arch, dc_sim and design_loop
```

Python tools need numpy, scipy and matplotlib (`uv sync`, or `pip install -r requirements.txt`); run the tests with `python -m pytest tests`.
