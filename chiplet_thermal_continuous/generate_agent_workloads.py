#!/usr/bin/env python3
"""Build a self-describing, simulator-independent workload and geometry file."""

import json

from generate_workloads import HERE, generate


def agent_format(spec):
    payload = generate(spec)
    fields = {
        "format_version": "Integer schema version of workload_data.",
        "coordinate_convention": "All coordinates are in mm, origin at lower-left, x right and y up. Die maps use bottom-first rows.",
        "power_unit": "Each power_maps_w entry is watts IN that pixel, not W/mm²; divide by pixel physical area for flux.",
        "interposer_mm": "[width,height] in mm of the rectangular interposer.",
        "edge_clearance_mm": "Minimum die-to-interposer-edge separation in mm.",
        "minimum_die_gap_mm": "Minimum spacing between each pair of die rectangles in mm, including diagonals when both projections overlap.",
        "port_rule": {
            "density_gb_s_per_mm": "Peak provisioned bidirectional-equivalent GB/s per mm of allocated chiplet side; same length reserved at both endpoints.",
            "usable_center_fraction_of_each_die_side": "Fraction of each side usable for port segments; centered; all assigned port segments must fit.",
            "minimum_gap_between_ports_mm": "Gap in mm between port segments assigned to the same die side.",
            "route_grid_pitch_mm": "Center-to-center grid spacing in mm for obstacle-aware Manhattan wiring.",
            "route_clearance_mm": "Routing cell center exclusion margin from every die in mm.",
            "total_bandwidth_weighted_route_limit_gb_s_mm": "Maximum sum over links of link.gb_s * routed length in mm."
        },
        "thermal_model": {
            "ambient_c": "Ambient degrees Celsius.",
            "interposer_si_thickness_um": "Silicon interposer layer thickness in micrometers; wire and outside-port watts enter this layer.",
            "die_si_thickness_um": "Chiplet and gap model layer thickness in micrometers; die watts and inside-port watts enter this layer.",
            "tim_thickness_um": "Top TIM layer thickness in micrometers.",
            "thermal_resistivity_si_mK_per_W": "Silicon material resistivity in metre-kelvin per watt (m·K/W, NOT milli-kelvin).",
            "thermal_resistivity_gap_mK_per_W": "Gap-layer material thermal resistivity in m·K/W.",
            "thermal_resistivity_tim_mK_per_W": "Good central-contact TIM resistivity in m·K/W.",
            "cooling_contact_rect_mm": "[x0,y0,width,height] central good-cooling footprint in mm.",
            "outside_contact_resistivity_mK_per_W": "Peripheral TIM material resistivity in m·K/W.",
            "spreader_side_mm": "Square spreader side length in mm.",
            "sink_side_mm": "Square heat sink side length in mm.",
            "cooling_resistance_K_per_W": "Fixed sink-to-ambient resistance K/W.",
            "boundary_note": "Narrative of fixed top contact; other surfaces have no separate convection."
        },
        "interconnect_model": {
            "phy_energy_total_pj_per_bit": "Energy per active bit for the two chiplet endpoint PHYs combined, pJ/bit.",
            "phy_split_gpu_fraction": "Fraction of combined PHY power assigned to the GPU endpoint; remainder to HBM.",
            "port_heat_depth_each_side_mm": "Each endpoint's power rectangle extends this far into and out of the die edge in mm.",
            "wire_energy_pj_per_bit_per_mm": "Routed wire energy per active bit per mm, pJ/(bit·mm).",
            "interposer_heat_tiles": "[columns,rows] of interposer output power tiles, bottom-first, for the reference HotSpot discretization.",
            "assumption": "Narrative of synthetic source placement and vertical layers."
        },
        "reference_objectives_c": "Fixed reference worst GPU and HBM temperatures as a keyed object in °C, for score; may be null before calibration.",
        "dies": "Mapping G0-G3 and H0-H3 to kind (GPU/HBM) and size_mm [width,height]. Lower-left placement position supplied separately.",
        "links": "Eight REQUIRED connection objects: id, from GPU, to HBM, gb_s provisioned peak bandwidth, max_route_mm reach including access segments.",
        "example_layouts_mm": "Mapping example layout names to all eight [x0,y0] die origins in mm; submit custom placements instead.",
        "workloads": {
            "profile": "Human-readable qualitative workload description.",
            "link_utilization": "Map link ID to activity fraction u in [0,1]; instantaneous steady-state delivered GB/s = link.gb_s * u; varies by workload.",
            "total_w": "Sum of base power_maps_w over all dies in W; excludes added PHY and wire heat.",
            "per_die_total_w": "Base watts by die, excluding PHY and wire heat.",
            "power_maps_w": "Map die ID to 16x16 array [row_y][column_x] of BASE watts per cell; row 0 is bottom. Each map covers the die rectangle exactly."
        }
    }
    return {
        "document_version": 1,
        "purpose": "Self-contained input and implementation contract for an AI agent or a different thermal solver.",
        "field_descriptions": fields,
        "solver_contract": [
            "Read workload_data and choose one workload and a legal placement; never treat the base maps as total link-inclusive power.",
            "Determine one nonoverlapping port segment per link at BOTH endpoints; its length is link.gb_s / port_rule.density_gb_s_per_mm. The reference allocator deterministically sorts link IDs on each facing side within its centered usable fraction.",
            "Choose an obstacle-free rectilinear path from each assigned edge port to its matching port. Include both port-to-track accesses in length L in mm; enforce per-link reach and sum(gb_s * L) budget.",
            "active_bits_per_s = 8e9 * link.gb_s * workload.link_utilization[link.id].",
            "phy_total_W = active_bits_per_s * interconnect_model.phy_energy_total_pj_per_bit * 1e-12; assign GPU fraction to GPU and remainder to HBM.",
            "At EACH endpoint form axis-aligned rectangle of tangential length link.gb_s / port density centered on the port, and normal depth d into die plus d outward. Distribute that endpoint's PHY W uniformly over full area 2*d*length; inside half enters chiplet/die layer, outside half enters interposer layer. Use exact area overlap to rasterize; power at zero-area edge itself is zero.",
            "wire_W = active_bits_per_s * L * interconnect_model.wire_energy_pj_per_bit_per_mm * 1e-12. Distribute uniformly per mm along each Manhattan segment including end access; inject this into interposer layer. No extra PHY power is added at the edge point.",
            "Base die maps, interior PHY, exterior PHY and wire heat must sum to base total plus all link PHY and wire W. Compute maximum temperature separately over all GPU and HBM cells and all five workloads.",
            "The included thermal_model gives benchmark boundary assumptions, but absolute predictions from an alternative solver are not guaranteed to match reference HotSpot. For competition use the common judge."
        ],
        "workload_data": payload
    }


if __name__ == "__main__":
    spec = json.loads((HERE / "challenge_spec.json").read_text())
    output = HERE / "agent_workloads.json"
    output.write_text(json.dumps(agent_format(spec), indent=2) + "\n")
    print(f"Wrote {output}")
