"""The editable design: placements, routed wires, power traces and setup.

A :class:`Project` is everything the GUI lets you change. It saves to one JSON
file so a layout and the power traces that go with it travel together, and it
can rebuild a ``challenge_spec``-shaped dictionary (:meth:`Project.to_spec`)
that the judge modules consume unchanged.
"""

from __future__ import annotations

import copy
import json
import math
import os
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .simcore import default_spec

#: Marker written into saved files so imports can be recognised.
FORMAT = "chiplet-thermal-gui-project"
FORMAT_VERSION = 2

GRID_CHOICES = (64, 128, 256)

#: Parametric fields of a workload, in the order the editor shows them.
HOTSPOT_WEIGHT_KEYS = (
    "compute_hotspot_weight",
    "interface_hotspot_weight",
    "bank_hotspot_weight",
    "io_hotspot_weight",
)


def _round_pair(values: Iterable[float], digits: int = 3) -> list[float]:
    return [round(float(v), digits) for v in values]


@dataclass
class DieDef:
    """One chiplet: its kind, footprint and base-power hotspot centres.

    ``hotspots`` holds the two normalised (0..1) hotspot centres under the role
    names the challenge uses for this kind of die: compute/interface for a GPU,
    bank/io for an HBM.
    """

    name: str
    kind: str
    size_mm: list[float]
    hotspots: dict[str, list[float]] = field(default_factory=dict)

    @property
    def index(self) -> int:
        """The trailing digit of the die name, e.g. 2 for G2."""

        return int(self.name[1:])

    @property
    def is_gpu(self) -> bool:
        return self.kind == "GPU"

    @property
    def hotspot_roles(self) -> tuple[str, str]:
        return ("compute", "interface") if self.is_gpu else ("bank", "io")

    def spec_entry(self) -> dict:
        """The die as challenge_spec.json writes it."""

        entry: dict[str, Any] = {"kind": self.kind, "size_mm": list(self.size_mm)}
        for role in self.hotspot_roles:
            entry[f"{role}_hotspot_xy"] = list(self.hotspots[role])
        return entry

    @classmethod
    def from_spec(cls, name: str, entry: dict) -> DieDef:
        kind = entry["kind"]
        roles = ("compute", "interface") if kind == "GPU" else ("bank", "io")
        return cls(
            name=name,
            kind=kind,
            size_mm=[float(v) for v in entry["size_mm"]],
            hotspots={role: [float(v) for v in entry[f"{role}_hotspot_xy"]] for role in roles},
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "size_mm": list(self.size_mm),
            "hotspots": copy.deepcopy(self.hotspots),
        }

    @classmethod
    def from_dict(cls, name: str, data: dict) -> DieDef:
        return cls(
            name=name,
            kind=data["kind"],
            size_mm=[float(v) for v in data["size_mm"]],
            hotspots={k: [float(v) for v in xy] for k, xy in data.get("hotspots", {}).items()},
        )


@dataclass
class Workload:
    """One power-trace pattern.

    Normally parametric: per-die base watts, four hotspot weights and the eight
    link utilisations generate the 16x16 W/cell maps exactly as
    ``generate_workloads.map_for`` does. Set :attr:`use_custom_maps` to pin
    explicit maps instead, which is what importing measured or hand-edited
    traces does; the parametric watts then only describe the baseline.
    """

    name: str
    profile: str = ""
    gpu_w: list[float] = field(default_factory=lambda: [0.0] * 4)
    hbm_w: list[float] = field(default_factory=lambda: [0.0] * 4)
    weights: dict[str, float] = field(default_factory=dict)
    link_utilization: dict[str, float] = field(default_factory=dict)
    enabled: bool = True
    use_custom_maps: bool = False
    custom_maps_w: dict[str, list[list[float]]] = field(default_factory=dict)

    def base_watts(self, die: DieDef) -> float:
        """Base watts this workload assigns to *die*, before link heat."""

        if self.use_custom_maps and die.name in self.custom_maps_w:
            return float(sum(sum(row) for row in self.custom_maps_w[die.name]))
        source = self.gpu_w if die.is_gpu else self.hbm_w
        return float(source[die.index])

    def set_base_watts(self, die: DieDef, watts: float) -> None:
        source = self.gpu_w if die.is_gpu else self.hbm_w
        source[die.index] = float(watts)

    def spec_entry(self) -> dict:
        """The workload as challenge_spec.json writes it."""

        entry: dict[str, Any] = {
            "profile": self.profile,
            "gpu_w": [float(v) for v in self.gpu_w],
            "hbm_w": [float(v) for v in self.hbm_w],
        }
        for key in HOTSPOT_WEIGHT_KEYS:
            entry[key] = float(self.weights.get(key, 1.0))
        entry["link_utilization"] = {k: float(v) for k, v in self.link_utilization.items()}
        return entry

    @classmethod
    def from_spec(cls, name: str, entry: dict) -> Workload:
        return cls(
            name=name,
            profile=entry.get("profile", ""),
            gpu_w=[float(v) for v in entry["gpu_w"]],
            hbm_w=[float(v) for v in entry["hbm_w"]],
            weights={key: float(entry.get(key, 1.0)) for key in HOTSPOT_WEIGHT_KEYS},
            link_utilization={k: float(v) for k, v in entry["link_utilization"].items()},
        )

    def to_dict(self) -> dict:
        data = {
            "profile": self.profile,
            "gpu_w": [float(v) for v in self.gpu_w],
            "hbm_w": [float(v) for v in self.hbm_w],
            "weights": {k: float(v) for k, v in self.weights.items()},
            "link_utilization": {k: float(v) for k, v in self.link_utilization.items()},
            "enabled": bool(self.enabled),
        }
        if self.use_custom_maps:
            data["use_custom_maps"] = True
            data["power_maps_w"] = copy.deepcopy(self.custom_maps_w)
        return data

    @classmethod
    def from_dict(cls, name: str, data: dict) -> Workload:
        maps = data.get("power_maps_w") or {}
        weights = data.get("weights", {})
        return cls(
            name=name,
            profile=data.get("profile", ""),
            gpu_w=[float(v) for v in data.get("gpu_w", [0.0] * 4)],
            hbm_w=[float(v) for v in data.get("hbm_w", [0.0] * 4)],
            weights={key: float(weights.get(key, 1.0)) for key in HOTSPOT_WEIGHT_KEYS},
            link_utilization={k: float(v) for k, v in data.get("link_utilization", {}).items()},
            enabled=bool(data.get("enabled", True)),
            use_custom_maps=bool(data.get("use_custom_maps", bool(maps))),
            custom_maps_w={
                die: [[float(v) for v in row] for row in rows] for die, rows in maps.items()
            },
        )

    def copy_as(self, name: str) -> Workload:
        return replace(
            self,
            name=name,
            gpu_w=list(self.gpu_w),
            hbm_w=list(self.hbm_w),
            weights=dict(self.weights),
            link_utilization=dict(self.link_utilization),
            custom_maps_w=copy.deepcopy(self.custom_maps_w),
        )


@dataclass
class RunSettings:
    """How a simulation is executed, as opposed to what is simulated."""

    hotspot_path: str = ""
    grid: int = 64
    interconnect_enabled: bool = True
    parallel_jobs: int = 0  # 0 selects a sensible default from the CPU count
    reuse_existing: bool = True
    output_dir: str = ""
    layout_name: str = "gui_layout"

    def effective_jobs(self, workload_count: int) -> int:
        """Worker count for one run, never more than there is work for."""

        if self.parallel_jobs > 0:
            requested = self.parallel_jobs
        else:
            # HotSpot is single-threaded per trace; leave a core for the GUI.
            requested = max(1, min(8, (os.cpu_count() or 2) - 1))
        return max(1, min(requested, max(1, workload_count)))

    def to_dict(self) -> dict:
        return {
            "hotspot_path": self.hotspot_path,
            "grid": int(self.grid),
            "interconnect_enabled": bool(self.interconnect_enabled),
            "parallel_jobs": int(self.parallel_jobs),
            "reuse_existing": bool(self.reuse_existing),
            "output_dir": self.output_dir,
            "layout_name": self.layout_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RunSettings:
        grid = int(data.get("grid", 64))
        return cls(
            hotspot_path=data.get("hotspot_path", ""),
            grid=grid if grid in GRID_CHOICES else 64,
            interconnect_enabled=bool(data.get("interconnect_enabled", True)),
            parallel_jobs=int(data.get("parallel_jobs", 0)),
            reuse_existing=bool(data.get("reuse_existing", True)),
            output_dir=data.get("output_dir", ""),
            layout_name=data.get("layout_name", "gui_layout") or "gui_layout",
        )


@dataclass
class Project:
    """A complete, editable chiplet design.

    Holds the placements, any explicitly routed wires, the die definitions, the
    power-trace workloads and every numerical setup block the judge reads.
    :meth:`to_spec` reassembles those blocks into the shape the judge modules
    expect, so edits here flow straight into validation and into HotSpot.
    """

    name: str = "untitled"
    placements_mm: dict[str, list[float]] = field(default_factory=dict)
    wire_routes_grid: dict[str, list[list[int]]] = field(default_factory=dict)
    dies: dict[str, DieDef] = field(default_factory=dict)
    workloads: dict[str, Workload] = field(default_factory=dict)
    links: list[dict] = field(default_factory=list)
    interposer_mm: list[float] = field(default_factory=lambda: [52.0, 42.0])
    edge_clearance_mm: float = 1.0
    minimum_die_gap_mm: float = 1.0
    power_pixels_per_die_side: int = 16
    port_rule: dict = field(default_factory=dict)
    thermal_model: dict = field(default_factory=dict)
    interconnect_model: dict = field(default_factory=dict)
    reference_objectives_c: dict | None = None
    run: RunSettings = field(default_factory=RunSettings)
    notes: str = ""
    path: Path | None = None

    # ------------------------------------------------------------ construction
    @classmethod
    def from_spec(cls, spec: dict, layout: str | None = None) -> Project:
        """Build a project from a challenge spec and one of its example layouts."""

        dies = {name: DieDef.from_spec(name, entry) for name, entry in spec["dies"].items()}
        workloads = {
            name: Workload.from_spec(name, entry) for name, entry in spec["workloads"].items()
        }
        examples = spec.get("example_layouts_mm", {})
        chosen = layout if layout in examples else next(iter(examples), None)
        placements: dict[str, list[float]] = {}
        if chosen:
            placements = {die: _round_pair(xy) for die, xy in examples[chosen].items()}
        if not placements:
            placements = {name: [1.0, 1.0] for name in dies}
        return cls(
            name=chosen or "untitled",
            placements_mm=placements,
            dies=dies,
            workloads=workloads,
            links=copy.deepcopy(spec["links"]),
            interposer_mm=[float(v) for v in spec["interposer_mm"]],
            edge_clearance_mm=float(spec["edge_clearance_mm"]),
            minimum_die_gap_mm=float(spec["minimum_die_gap_mm"]),
            power_pixels_per_die_side=int(spec["power_pixels_per_die_side"]),
            port_rule=copy.deepcopy(spec["port_rule"]),
            thermal_model=copy.deepcopy(spec["thermal_model"]),
            interconnect_model=copy.deepcopy(spec["interconnect_model"]),
            reference_objectives_c=copy.deepcopy(spec.get("reference_objectives_c")),
            run=RunSettings(layout_name=chosen or "gui_layout"),
        )

    @classmethod
    def default(cls, challenge_dir: str | None = None, layout: str = "ring_center") -> Project:
        return cls.from_spec(default_spec(challenge_dir), layout)

    def copy(self) -> Project:
        """A deep copy, safe to hand to a worker thread."""

        path = self.path
        self.path = None
        try:
            clone = copy.deepcopy(self)
        finally:
            self.path = path
        clone.path = path
        return clone

    # -------------------------------------------------------------- spec shape
    def to_spec(self) -> dict:
        """Rebuild a challenge_spec.json-shaped dictionary from this project."""

        return {
            "version": "gui-edited",
            "description": f"Edited in the chiplet thermal GUI: {self.name}",
            "interposer_mm": [float(v) for v in self.interposer_mm],
            "edge_clearance_mm": float(self.edge_clearance_mm),
            "minimum_die_gap_mm": float(self.minimum_die_gap_mm),
            "port_rule": copy.deepcopy(self.port_rule),
            "thermal_model": copy.deepcopy(self.thermal_model),
            "power_pixels_per_die_side": int(self.power_pixels_per_die_side),
            "reference_objectives_c": copy.deepcopy(self.reference_objectives_c),
            "dies": {name: die.spec_entry() for name, die in self.dies.items()},
            "links": copy.deepcopy(self.links),
            "workloads": {name: wl.spec_entry() for name, wl in self.workloads.items()},
            "example_layouts_mm": {
                self.run.layout_name: {k: list(v) for k, v in self.placements_mm.items()}
            },
            "interconnect_model": copy.deepcopy(self.interconnect_model),
        }

    def enabled_workloads(self) -> list[str]:
        """Names of the workloads a run would simulate, in project order."""

        return [name for name, wl in self.workloads.items() if wl.enabled]

    @property
    def link_ids(self) -> list[str]:
        return [link["id"] for link in self.links]

    def link(self, link_id: str) -> dict:
        for item in self.links:
            if item["id"] == link_id:
                return item
        raise KeyError(link_id)

    def die_box(self, name: str) -> tuple[float, float, float, float]:
        """(x0, y0, x1, y1) in mm for one placed die."""

        x, y = self.placements_mm[name]
        w, h = self.dies[name].size_mm
        return float(x), float(y), float(x) + float(w), float(y) + float(h)

    def gpu_names(self) -> list[str]:
        return sorted(name for name, die in self.dies.items() if die.is_gpu)

    def hbm_names(self) -> list[str]:
        return sorted(name for name, die in self.dies.items() if not die.is_gpu)

    # ------------------------------------------------------- spec deviations
    def deviations(self, reference: dict | None = None) -> list[str]:
        """Setup values that differ from the challenge spec, in readable form.

        A deviation is legitimate for exploration but means the result is no
        longer comparable with the leaderboard, so the GUI says so plainly.
        """

        spec = reference or default_spec()
        found: list[str] = []

        def compare(label: str, mine: Any, theirs: Any) -> None:
            if isinstance(mine, bool) or isinstance(theirs, bool):
                if mine != theirs:
                    found.append(f"{label}: {mine} (spec {theirs})")
            elif isinstance(mine, (int, float)) and isinstance(theirs, (int, float)):
                if not math.isclose(float(mine), float(theirs), rel_tol=1e-9, abs_tol=1e-12):
                    found.append(f"{label}: {mine:g} (spec {theirs:g})")
            elif mine != theirs:
                found.append(f"{label}: {mine} (spec {theirs})")

        for block in ("thermal_model", "port_rule", "interconnect_model"):
            mine_block, spec_block = getattr(self, block), spec[block]
            for key in sorted(set(mine_block) | set(spec_block)):
                if key.endswith(("note", "assumption")):
                    continue
                compare(f"{block}.{key}", mine_block.get(key), spec_block.get(key))

        compare("interposer_mm", list(self.interposer_mm), list(spec["interposer_mm"]))
        compare("edge_clearance_mm", self.edge_clearance_mm, spec["edge_clearance_mm"])
        compare("minimum_die_gap_mm", self.minimum_die_gap_mm, spec["minimum_die_gap_mm"])
        compare(
            "power_pixels_per_die_side",
            self.power_pixels_per_die_side,
            spec["power_pixels_per_die_side"],
        )

        for name in sorted(set(self.dies) | set(spec["dies"])):
            if name not in self.dies or name not in spec["dies"]:
                found.append(f"dies.{name}: " + ("added" if name in self.dies else "removed"))
                continue
            compare(
                f"dies.{name}.size_mm",
                list(self.dies[name].size_mm),
                list(spec["dies"][name]["size_mm"]),
            )
            for role, xy in self.dies[name].hotspots.items():
                compare(
                    f"dies.{name}.{role}_hotspot_xy",
                    list(xy),
                    list(spec["dies"][name][f"{role}_hotspot_xy"]),
                )

        spec_links = {item["id"]: item for item in spec["links"]}
        for link_id in sorted(set(self.link_ids) | set(spec_links)):
            if link_id not in spec_links or link_id not in self.link_ids:
                found.append(
                    f"links.{link_id}: " + ("added" if link_id in self.link_ids else "removed")
                )
                continue
            mine = self.link(link_id)
            for key in ("from", "to", "gb_s", "max_route_mm"):
                compare(f"links.{link_id}.{key}", mine.get(key), spec_links[link_id].get(key))

        for name in sorted(set(self.workloads) | set(spec["workloads"])):
            if name not in spec["workloads"]:
                found.append(f"workloads.{name}: added")
                continue
            if name not in self.workloads:
                found.append(f"workloads.{name}: removed")
                continue
            mine_wl, theirs_wl = self.workloads[name], spec["workloads"][name]
            if mine_wl.use_custom_maps and self._custom_maps_differ(spec, name):
                found.append(f"workloads.{name}: custom 16x16 power maps")
            compare(f"workloads.{name}.gpu_w", list(mine_wl.gpu_w), list(theirs_wl["gpu_w"]))
            compare(f"workloads.{name}.hbm_w", list(mine_wl.hbm_w), list(theirs_wl["hbm_w"]))
            for key in HOTSPOT_WEIGHT_KEYS:
                compare(f"workloads.{name}.{key}", mine_wl.weights.get(key), theirs_wl.get(key))
            utilisation = theirs_wl["link_utilization"]
            for link_id in sorted(set(mine_wl.link_utilization) | set(utilisation)):
                compare(
                    f"workloads.{name}.utilization.{link_id}",
                    mine_wl.link_utilization.get(link_id),
                    utilisation.get(link_id),
                )
        return found

    def _custom_maps_differ(self, spec: dict, workload: str) -> bool:
        """Whether pinned maps actually differ from what the spec would generate.

        Importing the challenge's own ``workloads.json`` pins maps that are
        numerically identical to the parametric ones, and that must not be
        reported as a change: it would wrongly mark a valid score as
        incomparable.
        """

        from .simcore import load_modules

        maps = self.workloads[workload].custom_maps_w
        if not maps:
            return False
        try:
            generate = load_modules().generate_workloads.map_for
        except Exception:
            return True
        for die, rows in maps.items():
            if die not in spec["dies"]:
                return True
            expected = generate(spec, workload, die)
            mine = [[float(v) for v in row] for row in rows]
            if len(mine) != len(expected) or any(
                len(a) != len(b) for a, b in zip(mine, expected)
            ):
                return True
            for a_row, b_row in zip(mine, expected):
                for a, b in zip(a_row, b_row):
                    if not math.isclose(a, float(b), rel_tol=1e-7, abs_tol=1e-9):
                        return True
        return False

    # ------------------------------------------------------------------- JSON
    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "name": self.name,
            "notes": self.notes,
            "placements_mm": {k: _round_pair(v) for k, v in self.placements_mm.items()},
            "wire_routes_grid": {
                k: [[int(i), int(j)] for i, j in v] for k, v in self.wire_routes_grid.items()
            },
            "dies": {name: die.to_dict() for name, die in self.dies.items()},
            "links": copy.deepcopy(self.links),
            "workloads": {name: wl.to_dict() for name, wl in self.workloads.items()},
            "interposer_mm": [float(v) for v in self.interposer_mm],
            "edge_clearance_mm": float(self.edge_clearance_mm),
            "minimum_die_gap_mm": float(self.minimum_die_gap_mm),
            "power_pixels_per_die_side": int(self.power_pixels_per_die_side),
            "port_rule": copy.deepcopy(self.port_rule),
            "thermal_model": copy.deepcopy(self.thermal_model),
            "interconnect_model": copy.deepcopy(self.interconnect_model),
            "reference_objectives_c": copy.deepcopy(self.reference_objectives_c),
            "run_settings": self.run.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict, fallback_spec: dict | None = None) -> Project:
        """Load a project, filling anything absent from the challenge spec."""

        spec = fallback_spec or default_spec()
        base = cls.from_spec(spec)
        dies = {n: DieDef.from_dict(n, d) for n, d in data.get("dies", {}).items()} or base.dies
        workloads = {
            n: Workload.from_dict(n, d) for n, d in data.get("workloads", {}).items()
        } or base.workloads
        placements = {
            k: _round_pair(v) for k, v in data.get("placements_mm", {}).items()
        } or base.placements_mm
        routes = data.get("wire_routes_grid") or {}
        return cls(
            name=data.get("name") or base.name,
            notes=data.get("notes", ""),
            placements_mm=placements,
            wire_routes_grid={k: [[int(i), int(j)] for i, j in v] for k, v in routes.items()},
            dies=dies,
            workloads=workloads,
            links=copy.deepcopy(data.get("links") or base.links),
            interposer_mm=[float(v) for v in data.get("interposer_mm", base.interposer_mm)],
            edge_clearance_mm=float(data.get("edge_clearance_mm", base.edge_clearance_mm)),
            minimum_die_gap_mm=float(data.get("minimum_die_gap_mm", base.minimum_die_gap_mm)),
            power_pixels_per_die_side=int(
                data.get("power_pixels_per_die_side", base.power_pixels_per_die_side)
            ),
            port_rule={**base.port_rule, **(data.get("port_rule") or {})},
            thermal_model={**base.thermal_model, **(data.get("thermal_model") or {})},
            interconnect_model={**base.interconnect_model, **(data.get("interconnect_model") or {})},
            reference_objectives_c=data.get("reference_objectives_c", base.reference_objectives_c),
            run=RunSettings.from_dict(data.get("run_settings") or {}),
        )

    def save(self, path: str | os.PathLike[str]) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        self.path = target
        return target

    @classmethod
    def load(cls, path: str | os.PathLike[str], fallback_spec: dict | None = None) -> Project:
        source = Path(path)
        project = load_any(json.loads(source.read_text()), fallback_spec)
        project.path = source
        if project.name in ("untitled", "") and source.stem:
            project.name = source.stem
        return project

    # ------------------------------------------------------- judge-side export
    def to_judge_layouts(self, include_routes: bool = True) -> dict:
        """A --layouts file for run_simulations.py.

        The result is exactly what the judge accepts: placements plus, when
        wires were drawn by hand, the explicit wire_routes_grid paths.
        """

        entry: dict[str, Any] = {
            "placements_mm": {k: _round_pair(v) for k, v in self.placements_mm.items()}
        }
        if include_routes and self.wire_routes_grid:
            entry["wire_routes_grid"] = {
                k: [[int(i), int(j)] for i, j in v] for k, v in self.wire_routes_grid.items()
            }
        return {self.run.layout_name: entry}


def load_any(data: dict, fallback_spec: dict | None = None) -> Project:
    """Load a GUI project, a challenge --layouts file or a bare placement map.

    Importing somebody else's layout should just work, so all three shapes the
    challenge uses in practice are accepted:

    * this GUI's own project file (``format`` marker present);
    * a --layouts mapping of names to ``placements_mm`` plus optional
      ``wire_routes_grid`` (the first usable entry is taken);
    * a bare mapping of die names to [x, y] origins.
    """

    if data.get("format") == FORMAT:
        return Project.from_dict(data, fallback_spec)

    spec = fallback_spec or default_spec()
    die_names = set(spec["dies"])

    if die_names <= set(data):
        project = Project.from_spec(spec)
        project.placements_mm = {name: _round_pair(data[name]) for name in die_names}
        project.name = "imported_layout"
        project.run.layout_name = "imported_layout"
        return project

    for layout_name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        placements = entry.get("placements_mm", entry)
        if not isinstance(placements, dict) or not die_names <= set(placements):
            continue
        project = Project.from_spec(spec)
        project.placements_mm = {name: _round_pair(placements[name]) for name in die_names}
        routes = entry.get("wire_routes_grid") or {}
        project.wire_routes_grid = {
            k: [[int(i), int(j)] for i, j in v] for k, v in routes.items()
        }
        project.name = str(layout_name)
        project.run.layout_name = str(layout_name)
        return project

    raise ValueError(
        "Unrecognised file. Expected a GUI project, a challenge --layouts file, "
        "or a mapping of die names to [x, y] origins in mm."
    )


__all__ = [
    "FORMAT",
    "FORMAT_VERSION",
    "GRID_CHOICES",
    "HOTSPOT_WEIGHT_KEYS",
    "DieDef",
    "Project",
    "RunSettings",
    "Workload",
    "load_any",
]
