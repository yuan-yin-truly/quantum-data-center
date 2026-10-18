#!/usr/bin/env python3
"""Expand the compact challenge specification into portable 16x16 watt maps."""

import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent


def map_for(spec, workload_name, die_name):
    n = spec["power_pixels_per_die_side"]
    die = spec["dies"][die_name]
    workload = spec["workloads"][workload_name]
    yy, xx = np.mgrid[0:n, 0:n]
    xx, yy = (xx + 0.5) / n, (yy + 0.5) / n

    def gaussian(center, sigma):
        return np.exp(-((xx - center[0]) ** 2 + (yy - center[1]) ** 2) / (2 * sigma**2))

    if die["kind"] == "GPU":
        weights = (np.ones((n, n))
                   + workload["compute_hotspot_weight"] * gaussian(die["compute_hotspot_xy"], .13)
                   + workload["interface_hotspot_weight"] * gaussian(die["interface_hotspot_xy"], .16))
    else:
        weights = (np.ones((n, n))
                   + workload["bank_hotspot_weight"] * gaussian(die["bank_hotspot_xy"], .20)
                   + workload["io_hotspot_weight"] * gaussian(die["io_hotspot_xy"], .13))
    idx = int(die_name[1:])
    total = workload["gpu_w" if die["kind"] == "GPU" else "hbm_w"][idx]
    return weights / weights.sum() * total


def generate(spec):
    result = {
        "format_version": 3,
        "description": "Portable synthetic benchmark. Die maps are base power; workload traffic and placement-dependent rectangular port and route heat are added at evaluation.",
        "coordinate_convention": "x right, y up, origin at lower-left interposer corner; map row 0 is the bottom edge of its die",
        "power_unit": "Base W per cell, not W/mm^2; each 16x16 map sums to base die watts before interconnect power",
        "interposer_mm": spec["interposer_mm"],
        "edge_clearance_mm": spec["edge_clearance_mm"],
        "minimum_die_gap_mm": spec["minimum_die_gap_mm"],
        "port_rule": spec["port_rule"],
        "thermal_model": spec["thermal_model"],
        "interconnect_model": spec["interconnect_model"],
        "reference_objectives_c": spec.get("reference_objectives_c"),
        "dies": {name: {"kind": die["kind"], "size_mm": die["size_mm"]}
                 for name, die in spec["dies"].items()},
        "links": spec["links"],
        "example_layouts_mm": spec["example_layouts_mm"],
        "workloads": {}
    }
    for name, workload in spec["workloads"].items():
        maps = {die: np.round(map_for(spec, name, die), 9).tolist() for die in spec["dies"]}
        result["workloads"][name] = {
            "profile": workload["profile"],
            "link_utilization": workload["link_utilization"],
            "total_w": round(sum(sum(row) for power in maps.values() for row in power), 6),
            "per_die_total_w": {die: round(sum(sum(row) for row in power), 6) for die, power in maps.items()},
            "power_maps_w": maps
        }
    return result


if __name__ == "__main__":
    spec = json.loads((HERE / "challenge_spec.json").read_text())
    output = HERE / "workloads.json"
    output.write_text(json.dumps(generate(spec), indent=2) + "\n")
    print(f"Wrote {output}: {len(spec['workloads'])} workloads × {len(spec['dies'])} distinct die maps")
