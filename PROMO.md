# Quantum Data Center 2035

![A 2035 data-centre room: GPU racks beside a quantum cryostat](https://raw.githubusercontent.com/yuan-yin-truly/quantum-data-center/main/web/public/images/hero.webp)

**Should a 2035 AI data centre have quantum computers in it, and if so, how should it be built?**

We answer with simulation, always against a GPU-only data centre as the reference, for a world of AI agents used by developers, chemists, materials scientists, biologists, engineers and financial analysts.

## What we built

1. **The chip:** cryogenic heat budgets and thermal layouts for quantum and classical hardware.
2. **The data centre:** power, cooling and cost across six Earth sites within 500 MW.
3. **The numbers:** energy, cost and users served, side by side with a GPU-only design.
4. **The scheduler:** which task goes to a GPU, a CPU sandbox or a QPU, and what happens while an agent waits (it parks its session and frees the GPU).

## What we learned

- Quantum hardware pays off only above a break-even that depends on two things nobody has measured yet: how often agent work contains a quantum-friendly step, and what the best classical method costs for it. We map that break-even instead of guessing.
- Where the QPUs sit matters less than expected. Shared QPU halls, per-node QPUs and mixtures come out within a few percent, while a QPU next to every server is far more expensive.
- Every number comes with its assumptions, and every study can be rerun.

## Explore

- Website: https://yuan-yin-truly.github.io/quantum-data-center/
- Code: https://github.com/yuan-yin-truly/quantum-data-center
