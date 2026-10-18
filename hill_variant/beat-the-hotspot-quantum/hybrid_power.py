"""Power-map and link-traffic modifiers for the hybrid (quantum-integrated) package.

LOCAL-ONLY VARIANT. Results built on this module must never be compared with, or
submitted to, the official beat-the-hotspot leaderboard.

This module is pure data manipulation (numpy only, no quantum_arch import) so it
runs both on the host and inside the pinned evaluation container. It never
re-implements physics: the original ``generate_workloads.generate`` produces the
frozen power maps, the original ``geometry``/``interconnect`` modules produce the
routes and interface/wire heat. All this module does is

* turn a declared ``quantum`` block into a small JSON ``modifiers`` document
  (``build_modifiers``), and
* apply that document to a copy of the original spec and power maps
  (``apply_modifiers``).

Modifier document (all keys optional)::

    {"die_power_scale":        {workload: {die: factor}},
     "die_power_override_w":   {workload: {die: watts}},     # uniform map
     "link_utilization_scale": {workload: {link: factor}},
     "replaced_dies":          [die, ...]}

The offload fraction is always an INPUT. Nothing here derives it from a claim of
quantum speedup.
"""

from __future__ import annotations

import copy
import math

import numpy as np

SUPPORTED_REPLACED_MODES = ("redistributed", "dropped")


class ModifierError(ValueError):
    """Raised for an inconsistent modifier request (caller maps it to a clear error)."""


# ---------------------------------------------------------------------------------------------
# applying modifiers to the original data
# ---------------------------------------------------------------------------------------------
def is_identity(modifiers: dict | None) -> bool:
    """True when the modifiers leave every power map and link utilisation untouched."""
    if not modifiers:
        return True
    if modifiers.get("replaced_dies"):
        return False
    if any(per_workload for per_workload in (modifiers.get("die_power_override_w") or {}).values()):
        return False
    for table in ("die_power_scale", "link_utilization_scale"):
        for per_workload in (modifiers.get(table) or {}).values():
            if any(value != 1.0 for value in per_workload.values()):
                return False
    return True


def apply_modifiers(spec: dict, portable: dict, modifiers: dict | None) -> tuple[dict, dict]:
    """Return modified deep copies ``(spec, portable)``; the inputs are not changed."""
    spec2, portable2 = copy.deepcopy(spec), copy.deepcopy(portable)
    if is_identity(modifiers):
        return spec2, portable2
    n = spec["power_pixels_per_die_side"]
    scales = modifiers.get("die_power_scale") or {}
    overrides = modifiers.get("die_power_override_w") or {}
    link_scales = modifiers.get("link_utilization_scale") or {}
    for workload in portable2["workloads"]:
        data = portable2["workloads"][workload]
        for die, factor in (scales.get(workload) or {}).items():
            _check_factor(factor, f"die_power_scale[{workload}][{die}]")
            if die not in data["power_maps_w"]:
                raise ModifierError(f"unknown die {die!r} in die_power_scale")
            if factor != 1.0:
                data["power_maps_w"][die] = np.round(
                    np.asarray(data["power_maps_w"][die], dtype=float) * factor, 9).tolist()
        for die, watts in (overrides.get(workload) or {}).items():
            _check_factor(watts, f"die_power_override_w[{workload}][{die}]")
            if die not in data["power_maps_w"]:
                raise ModifierError(f"unknown die {die!r} in die_power_override_w")
            data["power_maps_w"][die] = np.full((n, n), watts / (n * n)).round(9).tolist()
        data["per_die_total_w"] = {die: round(sum(sum(row) for row in power), 6)
                                   for die, power in data["power_maps_w"].items()}
        data["total_w"] = round(sum(data["per_die_total_w"].values()), 6)
        known_links = {link["id"] for link in spec["links"]}
        for link, factor in (link_scales.get(workload) or {}).items():
            _check_factor(factor, f"link_utilization_scale[{workload}][{link}]")
            if link not in known_links:
                raise ModifierError(f"unknown link {link!r} in link_utilization_scale")
            current = spec2["workloads"][workload]["link_utilization"][link]
            spec2["workloads"][workload]["link_utilization"][link] = min(1.0, current * factor)
    return spec2, portable2


def _check_factor(value, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ModifierError(f"{label} must be a finite number >= 0")


# ---------------------------------------------------------------------------------------------
# building modifiers from a declared quantum block
# ---------------------------------------------------------------------------------------------
def build_modifiers(spec: dict, portable: dict, *, fractions: dict, dynamic_power_fraction: float,
                    traffic_coupling: float, replaced_mode: str, hosts: dict) -> dict:
    """Translate declared assumptions into a modifier document.

    ``fractions``: ``{workload: {gpu_die: offload_fraction}}`` (complete; 0 where unset).
    ``hosts``: ``{die: {"power_w": {workload: watts}, "traffic_scale": float}}`` for dies that are
    re-declared as quantum-support chiplets. Their power maps become uniform.

    Per-workload, per-GPU-die power factor for a remaining GPU ``i``::

        scale_i = 1 - dynamic_power_fraction * f_i  (+ R / sum_j P_j   if replaced_mode == "redistributed")

    where ``R`` is the original base power of all replaced dies in that workload and ``P_j`` the
    original base power of the remaining GPUs. Link utilisation of a link whose GPU end ``i``
    remains is scaled by ``(1 - traffic_coupling * f_i)`` times the same redistribution factor
    (clipped to utilisation <= 1 on application).
    """
    if replaced_mode not in SUPPORTED_REPLACED_MODES:
        raise ModifierError(f"replaced_die_work must be one of {SUPPORTED_REPLACED_MODES}")
    gpu_dies = [d for d, v in spec["dies"].items() if v["kind"] == "GPU"]
    replaced = sorted(hosts)
    remaining = [d for d in gpu_dies if d not in hosts]
    if not remaining:
        raise ModifierError("at least one GPU die must remain a GPU")
    modifiers: dict = {"die_power_scale": {}, "die_power_override_w": {},
                       "link_utilization_scale": {}, "replaced_dies": replaced}
    for workload, data in portable["workloads"].items():
        totals = data["per_die_total_w"]
        moved = sum(totals[d] for d in replaced)
        remaining_w = sum(totals[d] for d in remaining)
        extra = moved / remaining_w if (replaced_mode == "redistributed" and remaining_w > 0) else 0.0
        scale, link_scale, override = {}, {}, {}
        f_w = fractions.get(workload, {})
        for die in remaining:
            f = float(f_w.get(die, 0.0))
            scale[die] = round(1.0 - dynamic_power_fraction * f + extra, 12)
        for link in spec["links"]:
            gpu = link["from"]
            if gpu in hosts:
                link_scale[link["id"]] = float(hosts[gpu].get("traffic_scale", 0.0))
            else:
                f = float(f_w.get(gpu, 0.0))
                link_scale[link["id"]] = round((1.0 - traffic_coupling * f) * (1.0 + extra), 12)
        for die, host in hosts.items():
            override[die] = float(host["power_w"][workload])
        modifiers["die_power_scale"][workload] = scale
        modifiers["link_utilization_scale"][workload] = link_scale
        modifiers["die_power_override_w"][workload] = override
    return modifiers


# ---------------------------------------------------------------------------------------------
# cheap power accounting (no HotSpot): original combined_heat on the (modified) inputs
# ---------------------------------------------------------------------------------------------
def power_budgets(spec: dict, portable: dict, layout: dict, routing: dict) -> dict:
    """Package power per workload using the unmodified ``interconnect.combined_heat``."""
    from interconnect import combined_heat

    out = {}
    for workload, data in portable["workloads"].items():
        heat = combined_heat(spec, workload, data["power_maps_w"], layout, routing)
        out[workload] = {
            "total_w": round(heat["total_w"], 6),
            "base_w": round(heat["base_w"], 6),
            "phy_w": round(heat["phy_w"], 6),
            "wire_w": round(heat["wire_w"], 6),
            "per_die_w": {die: round(float(np.asarray(m).sum()), 6) for die, m in heat["die_maps_w"].items()},
            "link_utilization": dict(spec["workloads"][workload]["link_utilization"]),
        }
    return out
