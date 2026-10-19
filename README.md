# quantum-data-center

![A 2035 data center: GPU racks beside a quantum computer cryostat](web/public/images/hero.webp)

Our entry for SUNDAI @ MIT Track 1, "Build the AI data center of 2035": serve 100% of one user case on Earth, inside 500 MW and $30B, then make it cheap.

**The problem we take on.** In 2035, 50M agent developers launch 1.5B background agent tasks a day. If just one in a million calls a high-accuracy chemistry tool, a GPU sandbox needs about 48k more GPUs (282 MW, $7.9B), which pushes the fleet over the 500 MW cap. Six QPUs do the same calls in 1.7 MW. We design the GPU + QPU data center and the router that sends each task to the right machine, to cut energy and cost per task. A QPU only pays off when the classical method is expensive: above about 55 GPU-hours per call on cost (about 4 on energy). We assume 768, and the page shows that break-even.

![Architecture: a scheduler node sends LLM steps to a pool of GPU nodes and quantum-eligible calls to a shared QPU service, while agents park their sessions in a parking memory during the QPU job](web/public/images/architecture.svg?v=3)

The team page lives in `web/`. It opens with the problem statement and a GPU-only vs GPU + QPU comparison for the three cases, followed by a section per workstream.

## Run the page

```bash
cd web
npm install
npm run dev      # http://localhost:5173
npm run build    # typecheck + static build into web/dist
```

Pushing to `main` deploys to GitHub Pages through `.github/workflows/pages.yml`. Turn it on once under Settings → Pages → Source: GitHub Actions.

## Add your work

- **Research notes:** `docs/research-notes.md`.
- **Fleet model numbers:** `web/src/model/brief.ts` holds every number from the brief, each tagged with its page. `web/src/model/fleet.ts` is the fleet model. Both are plain TypeScript that Node 24 runs directly, so a quick script can import `computeFleet` to try numbers.
- **Simulation output for the web** (thermal runs, sweeps): put JSON under `web/public/data/<workstream>/`.

The brief and deck live in `data/`, which isn't committed. Ask a teammate for the files.

## What's in the repo

```
web/                  the team page (problem statement, comparison, task flow, research notes)
thermal_lab/          QC Hybrid Simulator: annual GPU + QPU rollout, router comparison and playback
dc_sim/               discrete-event simulator of a mixed GPU/QPU data centre with one scheduling node (README_DC_SIM.md)
quantum_arch/         quantum processors with their classical hardware: logical qubits, power, cryostat heat (README_QUANTUM.md)
design_loop/          automated design-space search for a hybrid package, local only (README_DESIGN_LOOP.md)
hill_variant/         local quantum variant of the Beat the Hotspot hill, used by design_loop
docs/                 research notes and workstream notes
tests/                Python tests for quantum_arch, dc_sim and design_loop
```

Python tools need numpy, scipy and matplotlib (`uv sync`, or `pip install -r requirements.txt`); run the tests with `python -m pytest tests`.
