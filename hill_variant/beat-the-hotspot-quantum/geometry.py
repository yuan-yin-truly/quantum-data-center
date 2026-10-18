"""Continuous die placement and deterministic, obstacle-aware bandwidth checks.

Coordinates are millimetres from the lower-left corner. Ports are short line
segments on the facing die sides; Manhattan routes use a 0.5 mm track grid.
This is a reproducible competition rule, not a routed electrical design.
"""

from collections import defaultdict
from heapq import heappop, heappush
import math


def die_box(spec, xy, name):
    x, y = xy[name]
    w, h = spec["dies"][name]["size_mm"]
    return x, y, x + w, y + h


def _side(box, other):
    x0, y0, x1, y1 = box
    ox0, oy0, ox1, oy1 = other
    dx = (ox0 + ox1 - x0 - x1) / 2
    dy = (oy0 + oy1 - y0 - y1) / 2
    if abs(dx) >= abs(dy):
        return "right" if dx > 0 else "left"
    return "top" if dy > 0 else "bottom"


def _side_port(spec, box, side, allocated):
    x0, y0, x1, y1 = box
    horizontal = side in ("top", "bottom")
    length = (x1 - x0) if horizontal else (y1 - y0)
    rule = spec["port_rule"]
    capacity = length * rule["usable_center_fraction_of_each_die_side"]
    gap = rule["minimum_gap_between_ports_mm"]
    allocated = sorted(allocated, key=lambda item: item[0])
    needed = sum(item[1] for item in allocated) + max(0, len(allocated) - 1) * gap
    if needed > capacity + 1e-8:
        raise ValueError(f"die-edge capacity: {side} requires {needed:.2f} mm, has {capacity:.2f} mm")
    axis_start = (x0 if horizontal else y0) + (length - needed) / 2
    ports = {}
    for link_id, required in allocated:
        middle = axis_start + required / 2
        if side == "left":
            position, normal = (x0, middle), (-1, 0)
        elif side == "right":
            position, normal = (x1, middle), (1, 0)
        elif side == "bottom":
            position, normal = (middle, y0), (0, -1)
        else:
            position, normal = (middle, y1), (0, 1)
        ports[link_id] = {"side": side, "center_mm": position,
                          "normal": normal, "reserved_length_mm": required}
        axis_start += required + gap
    return ports, needed, capacity


def _route_grid(spec, boxes, a, b, proposed_path=None):
    rule = spec["port_rule"]
    pitch = rule["route_grid_pitch_mm"]
    clearance = rule["route_clearance_mm"]
    width, height = spec["interposer_mm"]
    nx, ny = round(width / pitch), round(height / pitch)

    def pos(i, j):
        return ((i + 0.5) * pitch, (j + 0.5) * pitch)

    def blocked(i, j):
        x, y = pos(i, j)
        return any(x0 - clearance < x < x1 + clearance and y0 - clearance < y < y1 + clearance
                   for x0, y0, x1, y1 in boxes.values())

    def endpoint(port):
        x, y = port["center_mm"]
        dx, dy = port["normal"]
        px, py = x + dx * (clearance + pitch), y + dy * (clearance + pitch)
        cell = (math.floor(px / pitch), math.floor(py / pitch))
        if not (0 <= cell[0] < nx and 0 <= cell[1] < ny) or blocked(*cell):
            raise ValueError("port cannot access a free route track")
        access = abs(x - pos(*cell)[0]) + abs(y - pos(*cell)[1])
        return cell, access

    start, start_access = endpoint(a)
    goal, end_access = endpoint(b)
    if proposed_path is not None:
        path = [tuple(cell) for cell in proposed_path]
        if not path or path[0] != start or path[-1] != goal:
            raise ValueError(f"wire path must start at {start} and end at {goal}")
        for cell in path:
            if (len(cell) != 2 or not all(isinstance(v, int) for v in cell)
                    or not (0 <= cell[0] < nx and 0 <= cell[1] < ny) or blocked(*cell)):
                raise ValueError("wire path contains a blocked or invalid track cell")
        if any(abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1 for a, b in zip(path, path[1:])):
            raise ValueError("wire path must use adjacent Manhattan track cells")
        return round((len(path)-1) * pitch + start_access + end_access, 3), path
    heap = [(0, 0, start)]
    distance = {start: 0}
    parent = {}
    while heap:
        _, dist, cell = heappop(heap)
        if dist != distance[cell]:
            continue
        if cell == goal:
            path = [goal]
            while path[-1] != start:
                path.append(parent[path[-1]])
            path.reverse()
            return round((dist * pitch + start_access + end_access), 3), path
        for delta in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = cell[0] + delta[0], cell[1] + delta[1]
            if not (0 <= nxt[0] < nx and 0 <= nxt[1] < ny) or blocked(*nxt):
                continue
            nd = dist + 1
            if nd < distance.get(nxt, math.inf):
                distance[nxt] = nd
                parent[nxt] = cell
                h = abs(nxt[0] - goal[0]) + abs(nxt[1] - goal[1])
                heappush(heap, (nd + h, nd, nxt))
    raise ValueError("no obstacle-free rectilinear route")


def validate_layout(spec, xy, check_routes=True, wire_routes_grid=None):
    wire_routes_grid = wire_routes_grid or {}
    unknown = set(wire_routes_grid) - {link["id"] for link in spec["links"]}
    if unknown:
        raise ValueError(f"unknown wire links: {sorted(unknown)}")
    if set(xy) != set(spec["dies"]):
        raise ValueError("place every GPU and HBM exactly once")
    width, height = spec["interposer_mm"]
    edge = spec["edge_clearance_mm"]
    gap = spec["minimum_die_gap_mm"]
    boxes = {name: die_box(spec, xy, name) for name in xy}
    for name, (x0, y0, x1, y1) in boxes.items():
        if min(x0, y0) < edge - 1e-8 or x1 > width - edge + 1e-8 or y1 > height - edge + 1e-8:
            raise ValueError(f"{name} violates package edge clearance")
    for i, (name, a) in enumerate(boxes.items()):
        for other, b in list(boxes.items())[i + 1:]:
            gx = max(b[0] - a[2], a[0] - b[2], 0)
            gy = max(b[1] - a[3], a[1] - b[3], 0)
            if gx < gap - 1e-8 and gy < gap - 1e-8:
                raise ValueError(f"{name} and {other} violate {gap} mm clearance")

    assignments = defaultdict(list)
    by_id = {}
    density = spec["port_rule"]["density_gb_s_per_mm"]
    for link in spec["links"]:
        by_id[link["id"]] = link
        for die, neighbor in ((link["from"], link["to"]), (link["to"], link["from"])):
            side = _side(boxes[die], boxes[neighbor])
            assignments[(die, side)].append((link["id"], link["gb_s"] / density))

    ports = defaultdict(dict)
    capacity_usage = {}
    for (die, side), links in assignments.items():
        selected, used, available = _side_port(spec, boxes[die], side, links)
        ports[die].update(selected)
        capacity_usage[f"{die}.{side}"] = {"reserved_mm_including_gaps": round(used, 3),
                                          "available_mm": round(available, 3)}

    routes = {}
    weighted = 0.0
    for link in spec["links"]:
        a, b = ports[link["from"]][link["id"]], ports[link["to"]][link["id"]]
        lower_bound = sum(abs(u - v) for u, v in zip(a["center_mm"], b["center_mm"]))
        if lower_bound > link["max_route_mm"] + 1e-8:
            raise ValueError(f"{link['id']} port Manhattan lower bound {lower_bound:.2f} mm exceeds reach")
        if check_routes:
            length, path = _route_grid(spec, boxes, a, b, wire_routes_grid.get(link["id"]))
        else:
            if wire_routes_grid:
                raise ValueError("wire routes cannot be supplied when routing is disabled")
            length, path = lower_bound, []
        if length > link["max_route_mm"] + 1e-8:
            raise ValueError(f"{link['id']} route {length:.2f} mm exceeds {link['max_route_mm']:.2f} mm")
        routes[link["id"]] = {"from": link["from"], "to": link["to"],
                              "bandwidth_gb_s": link["gb_s"], "required_port_mm": link["gb_s"] / density,
                              "from_port": a["center_mm"], "to_port": b["center_mm"],
                              "from_normal": a["normal"], "to_normal": b["normal"],
                              "route_length_mm": length, "limit_mm": link["max_route_mm"],
                              "path_grid": [list(cell) for cell in path]}
        weighted += link["gb_s"] * length
    cap = spec["port_rule"]["total_bandwidth_weighted_route_limit_gb_s_mm"]
    if weighted > cap + 1e-8:
        raise ValueError(f"total bandwidth-weighted route {weighted:.1f} exceeds {cap:.1f} GB/s·mm")
    return {"routes": routes, "die_edge_capacity": capacity_usage,
            "weighted_route_gb_s_mm": round(weighted, 2), "route_limit_gb_s_mm": cap}
