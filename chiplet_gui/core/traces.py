"""Import and export power traces on their own, separately from a layout.

A project file already carries its traces, but traces also travel by
themselves: ``workloads.json`` and ``agent_workloads.json`` from the challenge,
and the parametric ``workloads`` block of a ``challenge_spec.json``. All of
those are read here, and what the GUI writes is ``workloads.json``-compatible
so the challenge's own tooling can consume it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from .analysis import base_power_maps
from .project import HOTSPOT_WEIGHT_KEYS, Project, Workload


def export_traces(project: Project, workloads: Sequence[str] | None = None) -> dict:
    """Resolved power traces in the challenge's ``workloads.json`` shape.

    Each map is the 16x16 base W/cell grid actually used, whether it came from
    the parametric model or from custom maps, so the file is self-contained.
    The parametric fields ride along under ``gui_parametric`` so a round trip
    through this format keeps the editor's sliders meaningful.
    """

    names = list(workloads or project.workloads)
    payload: dict = {
        "format_version": 3,
        "description": (
            "Power traces exported from the chiplet thermal GUI. Die maps are base power; "
            "port and route heat are added at evaluation from the placement."
        ),
        "coordinate_convention": (
            "x right, y up, origin at lower-left interposer corner; "
            "map row 0 is the bottom edge of its die"
        ),
        "power_unit": (
            "Base W per cell, not W/mm^2; each 16x16 map sums to base die watts "
            "before interconnect power"
        ),
        "interposer_mm": list(project.interposer_mm),
        "edge_clearance_mm": project.edge_clearance_mm,
        "minimum_die_gap_mm": project.minimum_die_gap_mm,
        "port_rule": project.port_rule,
        "thermal_model": project.thermal_model,
        "interconnect_model": project.interconnect_model,
        "reference_objectives_c": project.reference_objectives_c,
        "dies": {
            name: {"kind": die.kind, "size_mm": list(die.size_mm)}
            for name, die in project.dies.items()
        },
        "links": project.links,
        "example_layouts_mm": {
            project.run.layout_name: {k: list(v) for k, v in project.placements_mm.items()}
        },
        "workloads": {},
    }

    for name in names:
        workload = project.workloads[name]
        maps = {die: array.tolist() for die, array in base_power_maps(project, name).items()}
        per_die = {die: round(sum(sum(row) for row in rows), 6) for die, rows in maps.items()}
        payload["workloads"][name] = {
            "profile": workload.profile,
            "link_utilization": dict(workload.link_utilization),
            "total_w": round(sum(per_die.values()), 6),
            "per_die_total_w": per_die,
            "power_maps_w": maps,
            "gui_parametric": {
                "gpu_w": list(workload.gpu_w),
                "hbm_w": list(workload.hbm_w),
                "weights": dict(workload.weights),
                "enabled": workload.enabled,
                "use_custom_maps": workload.use_custom_maps,
            },
        }
    return payload


def _workload_block(data: dict) -> dict:
    """Find the workload dictionary inside any of the accepted file shapes."""

    if "workloads" in data and isinstance(data["workloads"], dict):
        return data["workloads"]
    # agent_workloads.json nests the payload one level down.
    nested = data.get("workload_data")
    if isinstance(nested, dict) and isinstance(nested.get("workloads"), dict):
        return nested["workloads"]
    raise ValueError(
        "No workloads found. Expected a GUI project, workloads.json, "
        "agent_workloads.json or a challenge_spec.json."
    )


def import_traces(
    project: Project, data: dict, replace: bool = True, die_names: Sequence[str] | None = None
) -> list[str]:
    """Load power traces into *project* and return the names that were read.

    With *replace* the project's workloads are swapped for the imported set;
    otherwise the imported ones are merged over the existing ones. A workload
    that carries explicit 16x16 maps keeps them, so a trace measured elsewhere
    survives the round trip untouched.
    """

    block = _workload_block(data)
    dies = list(die_names or project.dies)
    imported: dict[str, Workload] = {}

    for name, entry in block.items():
        if not isinstance(entry, dict):
            continue
        parametric = entry.get("gui_parametric", {})
        maps = entry.get("power_maps_w") or {}
        missing = [die for die in dies if die not in maps]
        if maps and missing:
            raise ValueError(
                f"Workload '{name}' has maps for {sorted(maps)} but this design needs {dies}."
            )

        # A file of explicit maps (workloads.json) carries no hotspot weights.
        # Keeping the ones already in the project means importing it does not
        # silently rewrite the parametric model behind the pinned maps.
        previous = project.workloads.get(name)
        weights = parametric.get("weights") or {}
        workload = Workload(
            name=name,
            profile=str(entry.get("profile", "") or (previous.profile if previous else "")),
            gpu_w=[float(v) for v in (parametric.get("gpu_w") or entry.get("gpu_w") or (previous.gpu_w if previous else [0.0] * 4))],
            hbm_w=[float(v) for v in (parametric.get("hbm_w") or entry.get("hbm_w") or (previous.hbm_w if previous else [0.0] * 4))],
            weights={
                key: float(
                    weights.get(
                        key,
                        entry.get(
                            key,
                            previous.weights.get(key, 1.0) if previous else 1.0,
                        ),
                    )
                )
                for key in HOTSPOT_WEIGHT_KEYS
            },
            link_utilization={
                str(k): float(v) for k, v in (entry.get("link_utilization") or {}).items()
            },
            enabled=bool(parametric.get("enabled", True)),
        )
        if maps:
            workload.custom_maps_w = {
                die: [[float(v) for v in row] for row in rows] for die, rows in maps.items()
            }
            # Explicit maps win unless the exporter said they were parametric.
            workload.use_custom_maps = bool(parametric.get("use_custom_maps", True))
            if not workload.use_custom_maps:
                workload.custom_maps_w = {}
            elif not any(workload.gpu_w) and not any(workload.hbm_w):
                # Keep the sliders showing the right watts for an external trace.
                for die_name in dies:
                    die = project.dies[die_name]
                    total = sum(sum(row) for row in workload.custom_maps_w[die_name])
                    workload.set_base_watts(die, round(float(total), 6))
        imported[name] = workload

    if not imported:
        raise ValueError("The file contained no readable workloads.")

    if replace:
        project.workloads = imported
    else:
        project.workloads.update(imported)
    return list(imported)


def write_traces(
    project: Project, path: str | Path, workloads: Sequence[str] | None = None
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(export_traces(project, workloads), indent=2) + "\n")
    return target


def read_traces(project: Project, path: str | Path, replace: bool = True) -> list[str]:
    return import_traces(project, json.loads(Path(path).read_text()), replace=replace)


__all__ = ["export_traces", "import_traces", "read_traces", "write_traces"]
