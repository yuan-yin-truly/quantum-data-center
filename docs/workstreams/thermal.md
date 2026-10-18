## Thermal & cooling

**Owner:** _add your name_ · **Status:** placeholder

**Question:** Can a 2035 GPU (~5.5 kW per chip, 792 kW per rack) run on direct liquid or immersion, and how warm can the coolant be? The answer decides which Earth sites work without chillers, and so the PUE on the fleet card.

**Gap it bridges:** the "Cooling and site climate" row of the fleet card. PUE runs from 1.06 to 1.14 for liquid cooling (Deck s.15), which moves facility power by up to ~7%.

**Plan**

- Tool: the organizer's thermal studio, now in this repo. Run the GUI with `python -m chiplet_gui`, or headless with `chiplet_thermal_continuous/run_simulations.py` (needs a HotSpot build; see `README_GUI.md`)
- `quantum_arch/thermal2d.py` has a cryogenic-temperature solver; the room-temperature chips stay with HotSpot
- Scale the Track 2 power maps (~400 W package) toward 2035 chip power
- Sweep cooler resistance and coolant temperature, and find the highest coolant temperature that keeps chips in spec
- Export results for the web: per-die peaks and the 64×64 `.grid` maps

**Results**

_Put numbers, plots or JSON under `web/public/data/thermal/` and describe them here._

**Open questions**

- _What chip temperature limit do we use?_
