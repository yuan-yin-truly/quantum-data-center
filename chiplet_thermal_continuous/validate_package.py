#!/usr/bin/env python3
"""Check the reference example's legality and power-conserving source placement."""

import json
from pathlib import Path

import numpy as np

from generate_agent_workloads import agent_format
from generate_workloads import generate
from geometry import validate_layout
from interconnect import combined_heat, overlap

HERE = Path(__file__).resolve().parent


def main():
    spec = json.loads((HERE / "challenge_spec.json").read_text())
    portable = generate(spec)
    layout = json.loads((HERE / "random_layout.json").read_text())["random_layout"]["placements_mm"]
    routing = validate_layout(spec, layout)
    assert routing["weighted_route_gb_s_mm"] <= routing["route_limit_gb_s_mm"]
    assert json.loads((HERE / "workloads.json").read_text()) == portable
    assert json.loads((HERE / "agent_workloads.json").read_text()) == agent_format(spec)
    out = HERE / "random_example" / "hotspot_inputs" / "random_layout"
    for name, workload in portable["workloads"].items():
        heat = combined_heat(spec, name, workload["power_maps_w"], layout, routing)
        assert np.isclose(heat["phy_inside_die_w"], heat["phy_w"] / 2, atol=1e-7)
        assert np.isclose(heat["phy_outside_die_w"], heat["phy_w"] / 2, atol=1e-7)
        assert np.isclose(heat["total_w"], heat["base_w"]+heat["phy_w"]+heat["wire_w"], atol=1e-7)
        source_w = np.array([float(s) for s in (out / f"{name}.ptrace").read_text().splitlines()[1].split()])
        assert np.isclose(source_w.sum(), heat["total_w"], atol=1e-5)
        for link_id, link in heat["link_breakdown"].items():
            provisioned = next(item["gb_s"] for item in spec["links"] if item["id"] == link_id)
            for key in ("from_port_rectangle_mm", "to_port_rectangle_mm"):
                x0, y0, x1, y1 = link[key]
                assert np.isclose((x1-x0)*(y1-y0), 2 * spec["interconnect_model"]["port_heat_depth_each_side_mm"] *
                                  provisioned/spec["port_rule"]["density_gb_s_per_mm"], atol=1e-6)
    assert overlap((0,0,1,1), (1,0,2,1)) == 0
    print("PASS: seeded layout legal; both self-contained workload formats agree; 5 trace budgets and port splits conserve power")


if __name__ == "__main__":
    main()
