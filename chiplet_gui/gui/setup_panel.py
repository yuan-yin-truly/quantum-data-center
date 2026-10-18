"""Simulation setup: the HotSpot run, the thermal stack and the link model.

Every number the judge reads is editable here, which is what makes the GUI
usable for exploring the model rather than only the placement. Changing one
makes the run no longer comparable with the leaderboard, so the panel keeps a
running list of what deviates from ``challenge_spec.json`` and offers to put
each block back.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.project import GRID_CHOICES, Project
from ..core.simcore import find_hotspot_binary, is_hotspot_binary
from .widgets import StatusLine, int_spin, muted, spin

#: ``(key, label, minimum, maximum, step, decimals, suffix)`` per editable field.
THERMAL_FIELDS = (
    ("ambient_c", "Ambient temperature", -50.0, 200.0, 1.0, 2, " C"),
    ("interposer_si_thickness_um", "Interposer silicon", 10.0, 2000.0, 10.0, 1, " um"),
    ("die_si_thickness_um", "Die silicon", 10.0, 2000.0, 10.0, 1, " um"),
    ("tim_thickness_um", "TIM", 1.0, 500.0, 1.0, 1, " um"),
    ("thermal_resistivity_si_mK_per_W", "Silicon resistivity", 1e-5, 1.0, 0.001, 7, " m*K/W"),
    ("thermal_resistivity_gap_mK_per_W", "Passive gap resistivity", 1e-4, 50.0, 0.1, 4, " m*K/W"),
    ("thermal_resistivity_tim_mK_per_W", "TIM resistivity (contact)", 1e-4, 50.0, 0.05, 4, " m*K/W"),
    ("outside_contact_resistivity_mK_per_W", "TIM resistivity (outside)", 1e-4, 50.0, 0.1, 4, " m*K/W"),
    ("spreader_side_mm", "Spreader side", 5.0, 500.0, 1.0, 2, " mm"),
    ("sink_side_mm", "Sink side", 5.0, 500.0, 1.0, 2, " mm"),
    ("cooling_resistance_K_per_W", "Convection resistance", 0.001, 10.0, 0.01, 4, " K/W"),
)

INTERCONNECT_FIELDS = (
    ("phy_energy_total_pj_per_bit", "PHY energy", 0.0, 10.0, 0.01, 4, " pJ/bit"),
    ("wire_energy_pj_per_bit_per_mm", "Wire energy", 0.0, 10.0, 0.01, 4, " pJ/bit/mm"),
    ("phy_split_gpu_fraction", "GPU share of PHY heat", 0.0, 1.0, 0.05, 3, ""),
    ("port_heat_depth_each_side_mm", "Port heat depth each side", 0.05, 10.0, 0.1, 3, " mm"),
)

PORT_FIELDS = (
    ("density_gb_s_per_mm", "Port density", 1.0, 2000.0, 10.0, 2, " GB/s/mm"),
    ("usable_center_fraction_of_each_die_side", "Usable side fraction", 0.05, 1.0, 0.05, 3, ""),
    ("minimum_gap_between_ports_mm", "Minimum port gap", 0.0, 5.0, 0.1, 3, " mm"),
    ("route_grid_pitch_mm", "Route track pitch", 0.05, 5.0, 0.05, 3, " mm"),
    ("route_clearance_mm", "Route clearance from dies", 0.0, 5.0, 0.05, 3, " mm"),
    (
        "total_bandwidth_weighted_route_limit_gb_s_mm",
        "Weighted route budget",
        100.0,
        1e6,
        500.0,
        1,
        " GB/s*mm",
    ),
)

GEOMETRY_FIELDS = (
    ("edge_clearance_mm", "Edge clearance", 0.0, 10.0, 0.1, 3, " mm"),
    ("minimum_die_gap_mm", "Minimum die gap", 0.0, 10.0, 0.1, 3, " mm"),
)


class SetupPanel(QWidget):
    """Editable run, thermal, interconnect and placement-rule settings."""

    settingsChanged = Signal()
    geometryChanged = Signal()
    hotspotPathChanged = Signal(str)

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._loading = False
        self._spins: dict[tuple[str, str], Any] = {}
        self._contact_spins: list[Any] = []

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._build_run_group())
        layout.addWidget(self._build_block_group("Thermal stack and cooling", "thermal_model", THERMAL_FIELDS))
        layout.addWidget(self._build_contact_group())
        layout.addWidget(
            self._build_block_group("Interconnect heat model", "interconnect_model", INTERCONNECT_FIELDS)
        )
        layout.addWidget(self._build_block_group("Port and routing rules", "port_rule", PORT_FIELDS))
        layout.addWidget(self._build_block_group("Placement rules", "geometry", GEOMETRY_FIELDS))
        layout.addWidget(self._build_deviation_group())
        layout.addStretch(1)

        area = QScrollArea()
        area.setWidget(inner)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(area)

        self.set_project(project)

    # ------------------------------------------------------------------ build
    def _build_run_group(self) -> QGroupBox:
        group = QGroupBox("HotSpot run")
        grid = QGridLayout(group)

        self.binary_edit = QLineEdit()
        self.binary_edit.setPlaceholderText("Path to the compiled hotspot executable")
        self.binary_edit.editingFinished.connect(self._binary_edited)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_binary)
        detect = QPushButton("Auto-detect")
        detect.clicked.connect(self._detect_binary)

        self.binary_status = StatusLine()

        self.grid_box = QComboBox()
        for choice in GRID_CHOICES:
            self.grid_box.addItem(f"{choice} x {choice}", choice)
        self.grid_box.currentIndexChanged.connect(self._grid_changed)

        self.jobs_spin = int_spin(0, 64, 0, width=84)
        self.jobs_spin.setToolTip(
            "Workloads solved at the same time. 0 picks a default from the CPU count.\n"
            "The workloads are independent, so this is close to a linear speed-up."
        )
        self.jobs_spin.valueChanged.connect(self._jobs_changed)
        self.jobs_hint = muted("")

        self.interconnect_check = QCheckBox("Include PHY and routed-wire heat")
        self.interconnect_check.setToolTip(
            "Unticking it is the challenge's zero-link-heat A/B control, equivalent to\n"
            "run_simulations.py --disable-interconnect."
        )
        self.interconnect_check.toggled.connect(self._interconnect_toggled)

        self.reuse_check = QCheckBox("Reuse an identical previous solve")
        self.reuse_check.setToolTip(
            "Skips HotSpot when every input file and the binary hash match the last run."
        )
        self.reuse_check.toggled.connect(self._reuse_toggled)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("gui_runs next to the project (default)")
        self.output_edit.editingFinished.connect(self._output_edited)
        output_browse = QPushButton("Browse...")
        output_browse.clicked.connect(self._browse_output)

        self.label_edit = QLineEdit()
        self.label_edit.setToolTip("Name used for this layout in results.json and the run folder")
        self.label_edit.editingFinished.connect(self._label_edited)

        row = 0
        grid.addWidget(QLabel("HotSpot binary"), row, 0)
        grid.addWidget(self.binary_edit, row, 1)
        binary_buttons = QHBoxLayout()
        binary_buttons.addWidget(browse)
        binary_buttons.addWidget(detect)
        holder = QWidget()
        holder.setLayout(binary_buttons)
        grid.addWidget(holder, row, 2)
        row += 1
        grid.addWidget(self.binary_status, row, 1, 1, 2)
        row += 1
        grid.addWidget(QLabel("Thermal grid"), row, 0)
        grid.addWidget(self.grid_box, row, 1)
        row += 1
        grid.addWidget(QLabel("Parallel workloads"), row, 0)
        jobs_row = QHBoxLayout()
        jobs_row.addWidget(self.jobs_spin)
        jobs_row.addWidget(self.jobs_hint, 1)
        holder = QWidget()
        holder.setLayout(jobs_row)
        grid.addWidget(holder, row, 1, 1, 2)
        row += 1
        grid.addWidget(self.interconnect_check, row, 1, 1, 2)
        row += 1
        grid.addWidget(self.reuse_check, row, 1, 1, 2)
        row += 1
        grid.addWidget(QLabel("Run output folder"), row, 0)
        grid.addWidget(self.output_edit, row, 1)
        grid.addWidget(output_browse, row, 2)
        row += 1
        grid.addWidget(QLabel("Layout label"), row, 0)
        grid.addWidget(self.label_edit, row, 1)
        grid.setColumnStretch(1, 1)
        return group

    def _build_block_group(self, title: str, block: str, fields: tuple) -> QGroupBox:
        group = QGroupBox(title)
        grid = QGridLayout(group)
        for index, (key, label, low, high, step, decimals, suffix) in enumerate(fields):
            box = spin(low, high, 0.0, step=step, decimals=decimals, suffix=suffix, width=132)
            box.valueChanged.connect(lambda _, b=block, k=key: self._field_changed(b, k))
            self._spins[(block, key)] = box
            row, column = divmod(index, 2)
            grid.addWidget(QLabel(label), row, column * 2)
            grid.addWidget(box, row, column * 2 + 1)
        grid.setColumnStretch(4, 1)
        reset = QPushButton("Reset this block to the spec")
        reset.clicked.connect(lambda: self._reset_block(block))
        grid.addWidget(reset, (len(fields) + 1) // 2, 0, 1, 4)
        return group

    def _build_contact_group(self) -> QGroupBox:
        group = QGroupBox("Good-contact cooling window")
        grid = QGridLayout(group)
        captions = ("x origin", "y origin", "width", "height")
        for index, caption in enumerate(captions):
            box = spin(0.0, 500.0, 0.0, step=1.0, decimals=2, suffix=" mm", width=110)
            box.valueChanged.connect(lambda _: self._contact_changed())
            self._contact_spins.append(box)
            grid.addWidget(QLabel(caption), 0, index * 2)
            grid.addWidget(box, 0, index * 2 + 1)
        grid.addWidget(
            muted(
                "Inside this rectangle the TIM uses the contact resistivity; outside it uses the "
                "higher one. The cooler stays fixed while the dies move.",
                wrap=True,
            ),
            1,
            0,
            1,
            8,
        )
        grid.setColumnStretch(8, 1)
        return group

    def _build_deviation_group(self) -> QGroupBox:
        group = QGroupBox("Comparability with the challenge spec")
        layout = QVBoxLayout(group)
        self.deviation_status = StatusLine()
        self.deviation_list = QLabel("")
        self.deviation_list.setWordWrap(True)
        self.deviation_list.setProperty("role", "warn")
        reset_all = QPushButton("Reset the whole setup to challenge_spec.json")
        reset_all.clicked.connect(self._reset_all)
        layout.addWidget(self.deviation_status)
        layout.addWidget(self.deviation_list)
        layout.addWidget(reset_all)
        return group

    # ---------------------------------------------------------------- project
    def set_project(self, project: Project) -> None:
        self._project = project
        self.refresh()

    def refresh(self) -> None:
        """Pull every widget value from the project and restate comparability."""

        project = self._project
        self._loading = True
        try:
            self.binary_edit.setText(project.run.hotspot_path)
            index = self.grid_box.findData(project.run.grid)
            self.grid_box.setCurrentIndex(max(0, index))
            self.jobs_spin.setValue(project.run.parallel_jobs)
            self.interconnect_check.setChecked(project.run.interconnect_enabled)
            self.reuse_check.setChecked(project.run.reuse_existing)
            self.output_edit.setText(project.run.output_dir)
            self.label_edit.setText(project.run.layout_name)

            for (block, key), box in self._spins.items():
                value = self._block_value(block, key)
                if value is not None:
                    box.setValue(float(value))
            contact = project.thermal_model.get("cooling_contact_rect_mm") or [0, 0, 0, 0]
            for box, value in zip(self._contact_spins, contact):
                box.setValue(float(value))
        finally:
            self._loading = False

        self._update_binary_status()
        self._update_jobs_hint()
        self.refresh_deviations()

    def refresh_run_summary(self) -> None:
        """Restate the parallelism hint and comparability after an outside edit."""

        self._update_jobs_hint()
        self.refresh_deviations()

    def _block_value(self, block: str, key: str):
        if block == "geometry":
            return getattr(self._project, key, None)
        return getattr(self._project, block, {}).get(key)

    def _set_block_value(self, block: str, key: str, value: float) -> None:
        if block == "geometry":
            setattr(self._project, key, value)
        else:
            getattr(self._project, block)[key] = value

    def refresh_deviations(self) -> None:
        deviations = self._project.deviations()
        if not deviations:
            self.deviation_status.set_message(
                "Setup matches the challenge spec, so the score is comparable.", "ok"
            )
            self.deviation_list.setText("")
            return
        self.deviation_status.set_message(
            f"{len(deviations)} value(s) differ from the spec. Results stay valid for "
            "exploration but the leaderboard score is no longer comparable.",
            "warn",
        )
        shown = deviations[:14]
        text = "\n".join(f"- {item}" for item in shown)
        if len(deviations) > len(shown):
            text += f"\n- ... and {len(deviations) - len(shown)} more"
        self.deviation_list.setText(text)

    # ------------------------------------------------------------------ edits
    def _field_changed(self, block: str, key: str) -> None:
        if self._loading:
            return
        box = self._spins[(block, key)]
        self._set_block_value(block, key, float(box.value()))
        self.refresh_deviations()
        # Pitch, clearance and the placement rules change the route lattice.
        if block in ("port_rule", "geometry"):
            self.geometryChanged.emit()
        else:
            self.settingsChanged.emit()

    def _contact_changed(self) -> None:
        if self._loading:
            return
        self._project.thermal_model["cooling_contact_rect_mm"] = [
            round(float(box.value()), 4) for box in self._contact_spins
        ]
        self.refresh_deviations()
        self.settingsChanged.emit()

    def _grid_changed(self) -> None:
        if self._loading:
            return
        self._project.run.grid = int(self.grid_box.currentData())
        self.settingsChanged.emit()

    def _jobs_changed(self) -> None:
        if self._loading:
            return
        self._project.run.parallel_jobs = int(self.jobs_spin.value())
        self._update_jobs_hint()
        self.settingsChanged.emit()

    def _update_jobs_hint(self) -> None:
        count = max(1, len(self._project.enabled_workloads()))
        jobs = self._project.run.effective_jobs(count)
        cpus = os.cpu_count() or 1
        self.jobs_hint.setText(
            f"{jobs} process(es) for {count} workload(s); this machine reports {cpus} CPUs."
        )

    def _interconnect_toggled(self, enabled: bool) -> None:
        if self._loading:
            return
        self._project.run.interconnect_enabled = enabled
        self.settingsChanged.emit()

    def _reuse_toggled(self, enabled: bool) -> None:
        if self._loading:
            return
        self._project.run.reuse_existing = enabled

    def _output_edited(self) -> None:
        if self._loading:
            return
        self._project.run.output_dir = self.output_edit.text().strip()

    def _browse_output(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Folder to write run results into", self._project.run.output_dir or ""
        )
        if directory:
            self.output_edit.setText(directory)
            self._output_edited()

    def _label_edited(self) -> None:
        if self._loading:
            return
        text = self.label_edit.text().strip() or "gui_layout"
        self._project.run.layout_name = text
        self.label_edit.setText(text)

    # ----------------------------------------------------------------- binary
    def _binary_edited(self) -> None:
        if self._loading:
            return
        self._project.run.hotspot_path = self.binary_edit.text().strip()
        self._update_binary_status()
        self.hotspotPathChanged.emit(self._project.run.hotspot_path)

    def _browse_binary(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select the compiled HotSpot executable",
            self._project.run.hotspot_path or "",
            "Executable (*.exe);;All files (*)",
        )
        if path:
            self.binary_edit.setText(path)
            self._binary_edited()

    def _detect_binary(self) -> None:
        found = find_hotspot_binary()
        if found:
            self.binary_edit.setText(str(found))
            self._binary_edited()
        else:
            self.binary_status.set_message(
                "No HotSpot build found nearby. Point to the executable inside its own "
                "repository checkout.",
                "error",
            )

    def _update_binary_status(self) -> None:
        path = self._project.run.hotspot_path
        if not path:
            self.binary_status.set_message(
                "No HotSpot binary set, so simulations cannot run yet.", "warn"
            )
        elif is_hotspot_binary(path):
            self.binary_status.set_message("HotSpot binary looks usable.", "ok")
        else:
            self.binary_status.set_message(
                "Not usable: the file must exist and sit inside its HotSpot repository, "
                "because examples/example3/example.config is read from beside it.",
                "error",
            )

    # ----------------------------------------------------------------- resets
    def _reset_block(self, block: str) -> None:
        from ..core.simcore import default_spec

        spec = default_spec()
        if block == "geometry":
            self._project.edge_clearance_mm = float(spec["edge_clearance_mm"])
            self._project.minimum_die_gap_mm = float(spec["minimum_die_gap_mm"])
        else:
            setattr(self._project, block, dict(spec[block]))
        self.refresh()
        self.geometryChanged.emit()

    def _reset_all(self) -> None:
        from ..core.simcore import default_spec

        spec = default_spec()
        self._project.thermal_model = dict(spec["thermal_model"])
        self._project.interconnect_model = dict(spec["interconnect_model"])
        self._project.port_rule = dict(spec["port_rule"])
        self._project.edge_clearance_mm = float(spec["edge_clearance_mm"])
        self._project.minimum_die_gap_mm = float(spec["minimum_die_gap_mm"])
        self._project.interposer_mm = [float(v) for v in spec["interposer_mm"]]
        self._project.power_pixels_per_die_side = int(spec["power_pixels_per_die_side"])
        self.refresh()
        self.geometryChanged.emit()


__all__ = [
    "GEOMETRY_FIELDS",
    "INTERCONNECT_FIELDS",
    "PORT_FIELDS",
    "THERMAL_FIELDS",
    "SetupPanel",
]
