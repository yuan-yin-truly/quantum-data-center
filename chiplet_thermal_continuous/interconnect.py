"""Workload-dependent PHY and routed-wire heat for the synthetic benchmark."""

import numpy as np

from geometry import die_box


def overlap(a, b):
    """Intersection area of two axis-aligned (x0,y0,x1,y1) rectangles."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def port_rectangle(center, normal, length, depth):
    """Full uniformly heated port rectangle, depth on each side of the edge."""
    x, y = center
    if normal[0]:
        return (x - depth, y - length / 2, x + depth, y + length / 2)
    return (x - length / 2, y - depth, x + length / 2, y + depth)


def route_segments(route, pitch):
    """Continuous Manhattan segments; access goes outward before tangential travel."""
    path = route["path_grid"]
    tracks = [((i + .5) * pitch, (j + .5) * pitch) for i, j in path]
    result = []
    for port, track, normal in ((route["from_port"], tracks[0], route["from_normal"]),
                                (route["to_port"], tracks[-1], route["to_normal"])):
        # From edge outward along its normal, then turn towards the track.
        corner = (track[0], port[1]) if normal[0] else (port[0], track[1])
        result.extend(((port, corner), (corner, track)))
    result.extend(zip(tracks, tracks[1:]))
    return [(a, b) for a, b in result if abs(a[0]-b[0]) + abs(a[1]-b[1]) > 1e-10]


def segment_tile_lengths(a, b, nx, ny, width, height):
    """Yield exact lengths in each tile of one axis-aligned segment."""
    length = abs(a[0]-b[0]) + abs(a[1]-b[1])
    cuts = [0., 1.]
    axis = 0 if abs(a[0]-b[0]) > 1e-10 else 1
    spacing = (width / nx, height / ny)[axis]
    count = (nx, ny)[axis]
    for k in range(1, count):
        t = (k * spacing - a[axis]) / (b[axis] - a[axis])
        if 0 < t < 1:
            cuts.append(t)
    cuts.sort()
    for t0, t1 in zip(cuts, cuts[1:]):
        tm = (t0+t1)/2
        x, y = (a[0] + tm*(b[0]-a[0]), a[1] + tm*(b[1]-a[1]))
        i = min(nx-1, max(0, int(x * nx / width)))
        j = min(ny-1, max(0, int(y * ny / height)))
        yield j, i, (t1-t0)*length


def interposer_tiles(spec):
    nx, ny = spec["interconnect_model"]["interposer_heat_tiles"]
    width, height = spec["interposer_mm"]
    return [(f"ip_y{j:02d}_x{i:02d}", i * width / nx, j * height / ny,
             width / nx, height / ny) for j in range(ny) for i in range(nx)]


def combined_heat(spec, workload_name, base_maps, layout, routing):
    """Return die maps and interposer tiles in watts, conserving link power."""
    n = spec["power_pixels_per_die_side"]
    rule = spec["interconnect_model"]
    workload = spec["workloads"][workload_name]
    traffic = workload["link_utilization"]
    links = {link["id"]: link for link in spec["links"]}
    if set(traffic) != set(links) or any(not 0 <= value <= 1 for value in traffic.values()):
        raise ValueError(f"{workload_name}: link utilization must cover each link in [0,1]")
    die_maps = {die: np.array(power, dtype=float).copy() for die, power in base_maps.items()}
    nx, ny = rule["interposer_heat_tiles"]
    tile_heat = np.zeros((ny, nx))
    width, height = spec["interposer_mm"]
    pitch = spec["port_rule"]["route_grid_pitch_mm"]
    breakdown = {}

    port_depth = rule["port_heat_depth_each_side_mm"]

    def add_port_heat(die, port, normal, length, watts):
        x0, y0, x1, y1 = die_box(spec, layout, die)
        rect = port_rectangle(port, normal, length, port_depth)
        # Both halves have equal area. Uniform power density is W / (2*d*L).
        density = watts / (2 * port_depth * length)
        dx, dy = (x1-x0)/n, (y1-y0)/n
        for row in range(n):
            for col in range(n):
                pixel = (x0+col*dx, y0+row*dy, x0+(col+1)*dx, y0+(row+1)*dy)
                die_maps[die][row, col] += density * overlap(rect, pixel)
        if normal[0] > 0:
            outside = (port[0], rect[1], rect[2], rect[3])
        elif normal[0] < 0:
            outside = (rect[0], rect[1], port[0], rect[3])
        elif normal[1] > 0:
            outside = (rect[0], port[1], rect[2], rect[3])
        else:
            outside = (rect[0], rect[1], rect[2], port[1])
        tw, th = width/nx, height/ny
        i0, i1 = max(0, int(outside[0]/tw)), min(nx, int(np.ceil(outside[2]/tw)))
        j0, j1 = max(0, int(outside[1]/th)), min(ny, int(np.ceil(outside[3]/th)))
        for j in range(j0, j1):
            for i in range(i0, i1):
                tile = (i*tw, j*th, (i+1)*tw, (j+1)*th)
                tile_heat[j, i] += density * overlap(outside, tile)
        return rect

    for link_id, link in links.items():
        route = routing["routes"][link_id]
        rate_bits_s = link["gb_s"] * traffic[link_id] * 8e9
        phy_w = rate_bits_s * rule["phy_energy_total_pj_per_bit"] * 1e-12
        wire_w = (rate_bits_s * rule["wire_energy_pj_per_bit_per_mm"] * 1e-12
                  * route["route_length_mm"])
        gpu_w = phy_w * rule["phy_split_gpu_fraction"]
        hbm_w = phy_w - gpu_w
        from_rect = add_port_heat(link["from"], route["from_port"], route["from_normal"], route["required_port_mm"], gpu_w)
        to_rect = add_port_heat(link["to"], route["to_port"], route["to_normal"], route["required_port_mm"], hbm_w)
        segments = route_segments(route, pitch)
        distance = sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a, b in segments)
        if distance <= 0 or abs(distance-route["route_length_mm"]) > .00101:
            raise ValueError("wire route has zero length")
        for a, b in segments:
            for j, i, segment_length in segment_tile_lengths(a, b, nx, ny, width, height):
                tile_heat[j, i] += wire_w * segment_length / distance
        breakdown[link_id] = {"utilization": traffic[link_id], "active_gb_s": round(link["gb_s"]*traffic[link_id], 3),
                              "route_mm": route["route_length_mm"], "phy_w": round(phy_w, 6),
                              "phy_inside_die_w": round(phy_w/2, 6), "phy_outside_die_w": round(phy_w/2, 6),
                              "from_port_rectangle_mm": list(from_rect), "to_port_rectangle_mm": list(to_rect),
                              "wire_w": round(wire_w, 6), "total_w": round(phy_w+wire_w, 6)}

    total_base = sum(float(np.asarray(m).sum()) for m in base_maps.values())
    total_die = sum(float(m.sum()) for m in die_maps.values())
    total_interposer = float(tile_heat.sum())
    expected_phy = sum(item["phy_w"] for item in breakdown.values())
    expected_wire = sum(item["wire_w"] for item in breakdown.values())
    expected = total_base + sum(item["total_w"] for item in breakdown.values())
    if (abs(total_die + total_interposer - expected) > 1e-4
            or abs(total_die-total_base-expected_phy/2) > 1e-4
            or abs(total_interposer-expected_wire-expected_phy/2) > 1e-4):
        raise ValueError("interconnect power was not conserved")
    return {"die_maps_w": die_maps, "interposer_tiles_w": tile_heat,
            "link_breakdown": breakdown, "base_w": total_base,
            "phy_w": expected_phy, "phy_inside_die_w": total_die-total_base,
            "phy_outside_die_w": total_interposer-expected_wire,
            "wire_w": expected_wire, "total_w": total_die+total_interposer}
