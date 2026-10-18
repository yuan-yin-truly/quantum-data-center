## Thermal & cooling

**Owner:** _add your name_ · **Status:** placeholder

**Question:** Can a 2035 GPU (~5.5 kW per chip, 792 kW per rack) run on direct liquid or immersion, and how warm can the coolant be? The answer decides which Earth sites work without chillers, and so the PUE on the fleet card.

**Gap it bridges:** the "Cooling and site climate" row of the fleet card. PUE runs from 1.06 to 1.14 for liquid cooling (Deck s.15), which moves facility power by up to ~7%.

**Plan**

- Tool: [chiplet-thermal-gui](https://github.com/Czaja107/chiplet-thermal-gui), run headless with `run_simulations.py`
- Scale the Track 2 power maps (~400 W package) toward 2035 chip power
- Sweep cooler resistance and coolant temperature, and find the highest coolant temperature that keeps chips in spec
- Export results for the web: per-die peaks and the 64×64 `.grid` maps

**Results**

_Put numbers, plots or JSON under `web/public/data/thermal/` and describe them here._

**Open questions**

- _What chip temperature limit do we use?_
