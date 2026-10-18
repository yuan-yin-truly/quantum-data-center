#!/usr/bin/env python3
"""Validate continuous layouts, export HotSpot inputs and simulate five workloads."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

from generate_workloads import HERE, generate
from geometry import die_box, validate_layout
from interconnect import combined_heat, interposer_tiles


def _floorplan_line(name, x, y, width, height, cp=None, resist=None):
    values = [name, width / 1000, height / 1000, x / 1000, y / 1000]
    if cp is not None:
        values.extend([cp, resist])
    return "\t".join(str(v) for v in values) + "\n"


def create_hotspot_files(spec, portable, layout, routing, run_dir, grid, vendor, include_interconnect=True):
    run_dir.mkdir(parents=True, exist_ok=True)
    W, H = spec["interposer_mm"]
    r = spec["thermal_model"]
    tiles = interposer_tiles(spec)
    (run_dir / "interposer.flp").write_text("".join(_floorplan_line(*tile) for tile in tiles))
    cx, cy, cw, ch = r["cooling_contact_rect_mm"]
    edge_tim = r["outside_contact_resistivity_mK_per_W"]
    center_tim = r["thermal_resistivity_tim_mK_per_W"]
    if not (0 < cx < cx + cw < W and 0 < cy < cy + ch < H):
        raise ValueError("cooling contact must be inside the interposer footprint")
    tim_regions = (("cooling_contact", cx, cy, cw, ch, center_tim),
                   ("perimeter_bottom", 0, 0, W, cy, edge_tim),
                   ("perimeter_top", 0, cy + ch, W, H - cy - ch, edge_tim),
                   ("perimeter_left", 0, cy, cx, ch, edge_tim),
                   ("perimeter_right", cx + cw, cy, W - cx - cw, ch, edge_tim))
    (run_dir / "tim.flp").write_text("".join(_floorplan_line(name, x, y, w, h, 4.0e6, resist)
                                           for name, x, y, w, h, resist in tim_regions))

    die_boxes = {name: die_box(spec, layout, name) for name in layout}
    die_lines = []
    passive_names = []
    # No sources in the passive gaps, but the gaps have a different k from Si.
    xs = sorted({0.0, W, *(q for x0, _, x1, _ in die_boxes.values() for q in (x0, x1))})
    ys = sorted({0.0, H, *(q for _, y0, _, y1 in die_boxes.values() for q in (y0, y1))})
    for j, (y0, y1) in enumerate(zip(ys, ys[1:])):
        for i, (x0, x1) in enumerate(zip(xs, xs[1:])):
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            if any(a < mx < c and b < my < d for a, b, c, d in die_boxes.values()):
                continue
            gap_name = f"gap_{j}_{i}"
            passive_names.append(gap_name)
            die_lines.append(_floorplan_line(gap_name, x0, y0, x1-x0, y1-y0,
                                              1.0e6, r["thermal_resistivity_gap_mK_per_W"]))

    die_pixels = []
    n = spec["power_pixels_per_die_side"]
    for name, (x0, y0, x1, y1) in die_boxes.items():
        dx, dy = (x1-x0)/n, (y1-y0)/n
        for row in range(n):
            for col in range(n):
                unit = f"{name}_y{row:02d}_x{col:02d}"
                die_pixels.append((unit, name, row, col))
                die_lines.append(_floorplan_line(unit, x0+col*dx, y0+row*dy, dx, dy,
                                                  1.75e6, r["thermal_resistivity_si_mK_per_W"]))
    (run_dir / "chiplets.flp").write_text("# die material followed by passive gap material\n" + "".join(die_lines))

    (run_dir / "stack.lcf").write_text(
        "# LCF order: Si interposer, heterogeneous active die plane, TIM to top heat sink\n"
        f"0\nY\nY\n1.75e6\n{r['thermal_resistivity_si_mK_per_W']}\n{r['interposer_si_thickness_um'] * 1e-6:.9g}\ninterposer.flp\n"
        f"1\nY\nY\n1.75e6\n{r['thermal_resistivity_si_mK_per_W']}\n{r['die_si_thickness_um'] * 1e-6:.9g}\nchiplets.flp\n"
        f"2\nY\nN\n4.0e6\n{r['thermal_resistivity_tim_mK_per_W']}\n{r['tim_thickness_um'] * 1e-6:.9g}\ntim.flp\n"
    )
    config = (vendor / "examples/example3/example.config").read_text()
    changes = {"ambient": 273.15 + r["ambient_c"], "init_temp": 273.15 + r["ambient_c"],
               "grid_rows": grid, "grid_cols": grid,
               "s_spreader": r["spreader_side_mm"] / 1000,
               "s_sink": r["sink_side_mm"] / 1000,
               "r_convec": r["cooling_resistance_K_per_W"]}
    for key, value in changes.items():
        config, count = re.subn(rf"(?m)^(\s*-{key}\s+)\S+", lambda match: match.group(1) + str(value), config)
        if count != 1:
            raise ValueError(f"expected exactly one -{key} configuration parameter")
    (run_dir / "benchmark.config").write_text(config)

    heat_reports = {}
    for workload, data in portable["workloads"].items():
        if include_interconnect:
            heat = combined_heat(spec, workload, data["power_maps_w"], layout, routing)
        else:
            nx, ny = spec["interconnect_model"]["interposer_heat_tiles"]
            heat = {"die_maps_w": data["power_maps_w"],
                    "interposer_tiles_w": np.zeros((ny, nx)),
                    "link_breakdown": {}, "base_w": data["total_w"], "phy_w": 0.0,
                    "phy_inside_die_w": 0.0, "phy_outside_die_w": 0.0,
                    "wire_w": 0.0, "total_w": data["total_w"]}
        heat_reports[workload] = {key: value for key, value in heat.items()
                                  if key not in ("die_maps_w", "interposer_tiles_w")}
        source_names = [tile[0] for tile in tiles] + passive_names + [b[0] for b in die_pixels]
        source_w = heat["interposer_tiles_w"].flatten().tolist() + [0.0] * len(passive_names)
        source_w += [heat["die_maps_w"][die][row][col] for _, die, row, col in die_pixels]
        # Both interposer tiles and the active die plane have power entries.
        (run_dir / f"{workload}.ptrace").write_text("\t".join(source_names) + "\n"
                                                      + "\t".join(f"{x:.9g}" for x in source_w) + "\n")
    (run_dir / "power_budget.json").write_text(json.dumps(heat_reports, indent=2) + "\n")
    return heat_reports


def parse_grid(filename, grid):
    layers = []
    current = []
    for line in filename.read_text().splitlines():
        if line.startswith("Layer "):
            if current:
                layers.append(np.array(current).reshape(grid, grid))
                current = []
        elif line.strip():
            index, value = line.split()
            if int(index) != len(current):
                raise ValueError("grid indices are not contiguous")
            current.append(float(value))
    if current:
        layers.append(np.array(current).reshape(grid, grid))
    if len(layers) < 3:
        raise ValueError("expected interposer, die and TIM layers")
    return layers[1] - 273.15


def input_fingerprint(run_dir, workload, hotspot, vendor):
    digest = hashlib.sha256()
    for filename in (hotspot, vendor / "examples/example3/example.materials",
                     *(run_dir / item for item in ("chiplets.flp", "interposer.flp", "tim.flp",
                                                   "stack.lcf", "benchmark.config", f"{workload}.ptrace"))):
        digest.update(filename.read_bytes())
    return digest.hexdigest()


def die_peaks(spec, layout, map_c):
    rows, cols = map_c.shape
    W, H = spec["interposer_mm"]
    xx = (np.arange(cols) + 0.5) / cols * W
    yy = H - (np.arange(rows) + 0.5) / rows * H
    peaks = {}
    for name in layout:
        x0, y0, x1, y1 = die_box(spec, layout, name)
        mask = (xx >= x0) & (xx < x1)
        rowmask = (yy >= y0) & (yy < y1)
        if not mask.any() or not rowmask.any():
            raise ValueError(f"thermal grid misses die {name}")
        peaks[name] = round(float(map_c[np.ix_(rowmask, mask)].max()), 2)
    return peaks


def make_figure(spec, layouts, results, maps, path):
    names = list(layouts)
    workloads = list(spec["workloads"])
    fig, axes = plt.subplots(len(names), len(workloads), figsize=(18, 3.0 * len(names)),
                             constrained_layout=True, squeeze=False)
    temps = [m for m in maps.values()]
    lo = min(float(m.min()) for m in temps)
    hi = max(float(m.max()) for m in temps)
    for row, name in enumerate(names):
        for col, workload in enumerate(workloads):
            ax = axes[row, col]
            m = maps[(name, workload)]
            im = ax.imshow(m, origin="upper", extent=(0, spec["interposer_mm"][0], 0, spec["interposer_mm"][1]),
                           cmap="inferno", vmin=lo, vmax=hi)
            for die in layouts[name]:
                x0, y0, x1, y1 = die_box(spec, layouts[name], die)
                ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, edgecolor="cyan", fill=False, lw=.7))
                ax.text((x0+x1)/2, (y0+y1)/2, die, color="white", ha="center", va="center", fontsize=6,
                        bbox={"facecolor": "black", "alpha": .45, "pad": .5})
            ax.set(xlim=(0, spec["interposer_mm"][0]), ylim=(0, spec["interposer_mm"][1]),
                   title=f"{name} | {workload}\nGPU {results[name][workload]['gpu_peak_c']:.1f} / HBM {results[name][workload]['hbm_peak_c']:.1f} °C")
            if row == len(names)-1:
                ax.set_xlabel("x (mm)")
            if col == 0:
                ax.set_ylabel("y (mm)")
    fig.colorbar(im, ax=axes, label="Active-layer temperature (°C)", shrink=.72)
    fig.savefig(path, dpi=95)
    plt.close(fig)


def make_wire_figure(spec, layouts, results, out):
    workload = "memory_stream"
    nx, ny = spec["interconnect_model"]["interposer_heat_tiles"]
    fig, axes = plt.subplots(1, len(layouts), figsize=(5 * len(layouts), 4),
                             constrained_layout=True, squeeze=False)
    images = []
    for ax, (name, layout) in zip(axes[0], layouts.items()):
        trace = (out / "hotspot_inputs" / name / f"{workload}.ptrace").read_text().splitlines()
        power = np.array([float(v) for v in trace[1].split()[:nx * ny]]).reshape(ny, nx)
        im = ax.imshow(power, origin="lower", extent=(0, spec["interposer_mm"][0], 0, spec["interposer_mm"][1]), cmap="magma",
                       vmin=0, vmax=None, interpolation="nearest")
        images.append(im)
        for die in layout:
            x0, y0, x1, y1 = die_box(spec, layout, die)
            ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, fill=False, edgecolor="cyan", lw=.8))
            ax.text((x0+x1)/2, (y0+y1)/2, die, color="white", fontsize=7, ha="center", va="center",
                    bbox={"facecolor": "black", "alpha": .5, "pad": .5})
        ax.set(title=f"{name}\nwire {results[name][workload]['interconnect_wire_w']:.2f} W, PHY {results[name][workload]['interconnect_phy_w']:.2f} W",
               xlabel="x (mm)", ylabel="y (mm)")
    for im in images:
        im.set_clim(0, max(float(item.get_array().max()) for item in images))
    fig.colorbar(images[-1], ax=axes, label="Wire + outside-port heat in interposer tile (W)", shrink=.72)
    fig.savefig(out / "wire_heat_memory_stream.png", dpi=120)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hotspot", type=Path, required=True, help="compiled HotSpot binary")
    parser.add_argument("--grid", type=int, choices=(64, 128, 256), default=64)
    parser.add_argument("--layouts", type=Path, help="optional JSON object mapping names to die-origin coordinates in mm")
    parser.add_argument("--output", type=Path, default=HERE / "example_outputs")
    parser.add_argument("--inputs-only", action="store_true", help="export all HotSpot inputs without running it")
    parser.add_argument("--reuse-existing", action="store_true", help="reuse grid files only when all simulator inputs match")
    parser.add_argument("--disable-interconnect", action="store_true", help="run an A/B baseline with zero link heat")
    args = parser.parse_args()
    hotspot = args.hotspot.resolve()
    vendor = hotspot.parent
    if not (vendor / "examples/example3/example.config").exists():
        parser.error("--hotspot must refer to a built HotSpot in its upstream repository")
    spec = json.loads((HERE / "challenge_spec.json").read_text())
    portable = generate(spec)
    (HERE / "workloads.json").write_text(json.dumps(portable, indent=2) + "\n")
    raw_layouts = json.loads(args.layouts.read_text()) if args.layouts else spec["example_layouts_mm"]
    layouts = {name: value.get("placements_mm", value) for name, value in raw_layouts.items()}
    wire_paths = {name: value.get("wire_routes_grid", {}) for name, value in raw_layouts.items()}
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    results, maps = {}, {}
    for name, layout in layouts.items():
        routing = validate_layout(spec, layout, wire_routes_grid=wire_paths[name])
        run_dir = out / "hotspot_inputs" / name
        heat_reports = create_hotspot_files(spec, portable, layout, routing, run_dir, args.grid, vendor,
                                            include_interconnect=not args.disable_interconnect)
        results[name] = {}
        for workload, data in portable["workloads"].items():
            if args.inputs_only:
                continue
            cmd = [str(hotspot), "-c", "benchmark.config", "-f", "chiplets.flp", "-p", f"{workload}.ptrace",
                   "-materials_file", str(vendor / "examples/example3/example.materials"),
                   "-model_type", "grid", "-detailed_3D", "on", "-grid_layer_file", "stack.lcf",
                   "-grid_steady_file", f"{workload}.grid", "-steady_file", f"{workload}.steady"]
            fingerprint = input_fingerprint(run_dir, workload, hotspot, vendor)
            digest_path = run_dir / f"{workload}.sha256"
            if not (args.reuse_existing and (run_dir / f"{workload}.grid").is_file()
                    and digest_path.is_file() and digest_path.read_text().strip() == fingerprint):
                proc = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True)
                if proc.returncode:
                    raise RuntimeError(f"HotSpot failed for {name}/{workload}:\n{proc.stdout}\n{proc.stderr}")
                digest_path.write_text(fingerprint + "\n")
            m = parse_grid(run_dir / f"{workload}.grid", args.grid)
            maps[(name, workload)] = m
            peaks = die_peaks(spec, layout, m)
            gpu_peak = max(peaks[d] for d in peaks if d.startswith("G"))
            hbm_peak = max(peaks[d] for d in peaks if d.startswith("H"))
            results[name][workload] = {"gpu_peak_c": gpu_peak, "hbm_peak_c": hbm_peak,
                                       "die_peak_c": peaks, "base_power_w": data["total_w"],
                                       "total_power_w": heat_reports[workload]["total_w"],
                                       "interconnect_phy_w": heat_reports[workload]["phy_w"],
                                       "phy_inside_die_w": heat_reports[workload]["phy_inside_die_w"],
                                       "phy_outside_die_w": heat_reports[workload]["phy_outside_die_w"],
                                       "interconnect_wire_w": heat_reports[workload]["wire_w"]}
            print(f"{name:14s} {workload:17s} GPU {gpu_peak:.2f} °C  HBM {hbm_peak:.2f} °C", flush=True)
        results[name]["routing"] = routing
    if args.inputs_only:
        print(f"Exported portable maps and HotSpot files to {out}")
        return
    objective = {name: {"worst_gpu_c": max(results[name][w]["gpu_peak_c"] for w in spec["workloads"]),
                        "worst_hbm_c": max(results[name][w]["hbm_peak_c"] for w in spec["workloads"]),
                        "weighted_route_gb_s_mm": results[name]["routing"]["weighted_route_gb_s_mm"]}
                 for name in layouts}
    reference = spec.get("reference_objectives_c")
    if reference:
        ambient = spec["thermal_model"]["ambient_c"]
        for name, metrics in objective.items():
            metrics["leaderboard_score"] = round(max(
                (metrics["worst_gpu_c"] - ambient) / (reference["worst_gpu_c"] - ambient),
                (metrics["worst_hbm_c"] - ambient) / (reference["worst_hbm_c"] - ambient)), 6)
    report = {"thermal_grid": args.grid, "units": "temperatures are Celsius; routes are GB/s·mm",
              "interconnect_enabled": not args.disable_interconnect,
              "interconnect_model": spec["interconnect_model"],
              "reference_objectives_c": reference,
              "note": "Base powers, link traffic, electrical coefficients and cooling parameters are synthetic challenge assumptions.",
              "objectives": objective, "per_layout_workload": results}
    (out / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    make_figure(spec, layouts, results, maps, out / "temperature_maps.png")
    if not args.disable_interconnect:
        make_wire_figure(spec, layouts, results, out)
    print(json.dumps(objective, indent=2))


if __name__ == "__main__":
    main()
