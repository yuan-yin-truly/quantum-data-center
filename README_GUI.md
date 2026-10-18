# Chiplet Thermal Studio

A desktop workbench for the SUNDAI *Beat the Hotspot* challenge: place four GPU
and four HBM chiplets on the 52 × 42 mm silicon interposer, route the eight
compulsory links, edit the power traces, and run HotSpot over the result.

Every number comes from the challenge's own judge modules. The GUI imports
`geometry.py`, `interconnect.py`, `generate_workloads.py` and
`run_simulations.py` from `chiplet_thermal_continuous/` rather than
reimplementing them, so legality, port assignment, link heat, the HotSpot input
files and the peak-temperature extraction are identical to what the judge
computes. A run of the bundled `random_layout.json` reproduces the reference
objectives exactly: worst GPU 104.59 °C, worst HBM 97.68 °C, score 1.0.

## Starting it

```
python -m pip install -r requirements.txt
python -m chiplet_gui
```

or double-click `run_gui.bat` on Windows. An optional design file can be passed
in: `run_gui.bat my_design.json`.

The GUI finds the challenge package and a compiled HotSpot automatically. It
looks for `hotspot.exe` / `hotspot` in this folder, its parent, and the usual
`HotSpot-master/`, `HotSpot/` and `vendor/HotSpot/` subdirectories, and honours
the `HOTSPOT_BINARY` and `CHIPLET_CHALLENGE_DIR` environment variables. The
binary must still sit inside its own repository checkout, because
`examples/example3/example.config` is read from next to it.

Without HotSpot the GUI still runs: placement, routing, validation, power
editing and every preview work, and **Export HotSpot inputs** writes a complete
input set to simulate elsewhere.

## The four tabs

### Layout

The floorplan. Drag a chiplet to move it; arrow keys nudge by the snap step and
shift multiplies that by ten. The wheel zooms, the middle button pans. Typing
exact coordinates in the **Placement** table on the left does the same thing,
and the two stay in step.

The layout is re-validated on every move, which takes about two milliseconds,
so the verdict in the status bar is always current. A die that breaks a rule
turns red and the panel names every violation at once, not just the first.
Dies are clamped so they can never leave the legal edge-clearance window.

The **Overlay** selector draws a field over the package:

| Overlay | What it shows |
| --- | --- |
| Die-plane power | Base die power plus the inside half of each PHY rectangle |
| Interposer power | Routed-wire heat plus the outside half of each PHY |
| Combined power density | Their sum, in W/mm², i.e. all heat injected under that square millimetre |
| Temperature | HotSpot's die-plane result from the selected run |

Power overlays recompute in about seven milliseconds, so link heat visibly
moves as a die is dragged. The dashed rectangle is the fixed 44 × 34 mm
good-contact cooling window, which does **not** move with the dies.

### Wires

All eight links, their routed length against their reach, and whether each is
routed automatically or by hand.

- Dashed wires are the judge's own deterministic shortest routes.
- Solid wires are yours, and are exported as `wire_routes_grid`.

**Draw wire…** enters routing mode on the canvas. The 0.5 mm track grid appears,
cells under a die or inside its clearance are washed red, and the two cells the
wire must connect are outlined in green and amber. Click track cells to add
waypoints — a distant click fills in the Manhattan path to it, and clicking a
cell already on the path trims back to it. Right-click or backspace steps back,
double-click or Enter finishes at the far port, Escape cancels.

The draft is checked as you draw. The banner reports the routed length against
that link's reach *and* the projected weighted-route total against the
13,500 GB/s·mm budget shared by all eight links, because a detour that fits its
own reach can still break the shared budget. A route that would fail is refused
before it is committed, and anything that somehow slips through is re-checked by
the judge's validator on commit and rolled back if rejected.

**Copy all auto routes to editable wires** turns the judge's routing into a
starting point you can then adjust.

### Power traces

Each workload is a 16 × 16 W/cell map per die plus eight link utilisations.
They are normally parametric — per-die base watts and four hotspot weights
generate the maps exactly as `generate_workloads.map_for` does — so editing a
watt or a weight redraws all eight maps immediately.

Tick a workload to include it in a run. Workloads can be added, duplicated,
renamed and deleted, and the five challenge traces can be restored at any time.

**Pin explicit 16 × 16 maps** freezes the maps as they are, which is how an
imported or hand-edited trace keeps its exact numbers; the watt and shape fields
then only describe the baseline.

**Import traces** reads any of the four shapes the challenge uses:
this GUI's own export, `workloads.json`, `agent_workloads.json`, and the
parametric `workloads` block of a `challenge_spec.json`. **Export traces**
writes a `workloads.json`-compatible file with the resolved maps, so it is
self-contained, plus the parametric fields so a round trip keeps the editor
meaningful.

The lower table resolves the current placement into per-link PHY and wire watts,
so you can see what a layout change costs before running anything.

### Simulation setup

Every number the judge reads, editable: the thermal stack and cooling, the
interconnect energy coefficients, the port and routing rules, and the placement
rules. Also the run itself — HotSpot binary, 64/128/256 grid, how many workloads
to solve in parallel, and whether to reuse an identical previous solve.

Changing any of these is legitimate for exploration but makes the score
incomparable with the leaderboard, so the panel keeps a live list of what
differs from `challenge_spec.json` and offers to reset each block. Runs carry
that list into their `results.json`, and the Results tab says plainly whether a
score is comparable. Importing the challenge's own `workloads.json` is **not**
flagged: the pinned maps are compared numerically against what the spec
generates, so identical maps count as unchanged.

Unticking **Include PHY and routed-wire heat** is the challenge's zero-link-heat
A/B control, equivalent to `run_simulations.py --disable-interconnect`.

### Results

Worst GPU and worst HBM temperature, the leaderboard score, per-workload peaks
with their power budget, and per-die peaks. The challenge asks for both
objectives to be kept rather than collapsed into one number, so every run of the
session is also plotted as a point on a worst-GPU / worst-HBM scatter, with the
reference layout drawn as crosshairs: anything below and to the left of both
lines improves both objectives at once. Click a point to bring that run back.

## Runs

The five workloads are independent steady-state solves, so they run in parallel.
On a 32-core machine the full set takes about **85 seconds instead of about
7 minutes** serially, with identical results. The run happens on a worker
thread, so the window stays usable — you can keep dragging chiplets while
HotSpot solves — and **Stop** kills the HotSpot processes rather than waiting
for them.

Each run snapshots the design, so its results always describe the layout that
was actually simulated, not whatever you edited afterwards.

A run folder holds the HotSpot inputs, the raw `.grid` and `.steady` outputs, a
`results.json` in the judge's own shape, `layout.json` (a ready `--layouts`
file), `gui_project.json` and the temperature maps. It is self-describing:
**Load a previous run…** reopens one, maps included. With **Reuse an identical
previous solve** on, re-running an unchanged design finishes in a fraction of a
second instead of re-solving.

## Files the GUI reads and writes

| Action | Format |
| --- | --- |
| Save / Open | A GUI project: placement, wires, dies, traces, every setup block and the run settings, in one JSON file |
| Import layout | A GUI project, a challenge `--layouts` file, or a bare `{"G0": [x, y], ...}` map. You are asked whether to take the whole design or only the placement and wires |
| Export for judge | A `--layouts` file with `placements_mm` and, when you drew any, `wire_routes_grid` |
| Import / export traces | `workloads.json`, `agent_workloads.json`, `challenge_spec.json` or this GUI's export |
| Export HotSpot inputs | Floorplans, layer stack, config and power traces, without running HotSpot |

To hand a design to the judge:

```
python run_simulations.py --hotspot <hotspot> --layouts my_layout.json --grid 64 --output my_run
```

## Layout of the code

```
chiplet_gui/
  core/
    simcore.py    locates the challenge package and HotSpot, imports the judge modules
    project.py    the editable design; JSON I/O; rebuilds a challenge_spec-shaped dict
    analysis.py   validation, the route lattice, and the instant power preview
    traces.py     power-trace import and export on their own
    runner.py     HotSpot input generation, parallel solving, cancellation, results
  gui/
    canvas.py       the draggable floorplan and the interactive wire router
    canvas_panel.py the canvas with its overlay and mode controls
    panels.py       placement numbers, legality, and the wire list
    power_panel.py  the workload editor and the 16x16 map thumbnails
    setup_panel.py  thermal, interconnect, port and run settings
    results_panel.py objectives, per-workload peaks and the Pareto view
    controller.py   the worker thread
    main_window.py  the window, actions and all the wiring
    render.py       fields to images, and the colour bar
    style.py        the dark theme and shared colours
```

## Caveats

These come from the challenge itself, not from the GUI. The thermal model is a
deliberately simplified three-layer stack with a fixed cooler; the base powers,
link traffic and the PHY/wire energy coefficients are synthetic benchmark
assumptions, not measured GPU or HBM data; and the router models no wire width,
congestion, IR drop, latency or vias. Outputs are relative benchmark values, not
calibrated junction predictions. The judge's example uses a 64 × 64 grid; 128
and 256 are available here and are worth checking before trusting a small
margin.
