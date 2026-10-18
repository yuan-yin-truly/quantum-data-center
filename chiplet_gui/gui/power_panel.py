"""The power-trace editor: per-die watts, hotspot shape and link traffic.

Each workload is a 16x16 W/cell map per die plus eight link utilisations. The
maps are normally generated from a handful of parameters, which is what makes
them editable here; a workload can also pin explicit maps, which is how an
externally measured trace keeps its exact numbers.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.analysis import PowerPreview, base_power_maps
from ..core.project import HOTSPOT_WEIGHT_KEYS, Project
from . import style
from .widgets import compact_table, heading, muted, read_only_item, spin

#: Readable captions for the four hotspot weights.
WEIGHT_LABELS = {
    "compute_hotspot_weight": "GPU compute hotspot",
    "interface_hotspot_weight": "GPU interface hotspot",
    "bank_hotspot_weight": "HBM bank hotspot",
    "io_hotspot_weight": "HBM I/O hotspot",
}


class MapThumbnails(QWidget):
    """The eight 16x16 power maps, drawn small and side by side.

    Showing all of them at once is the point: the hotspot weights move several
    dies at a time, and a single-die view hides that.
    """

    dieClicked = Signal(str)

    #: Smallest thumbnail worth drawing, in device pixels.
    MIN_SIDE = 86.0
    MARGIN = 6.0
    CAPTION = 15.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._images: list[tuple[str, QImage, float, float]] = []
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def _metrics(self) -> tuple[int, int, float, float, float]:
        """Choose a column count that fits the width, then size the cells.

        A wide panel shows all eight dies in one row, which keeps the second
        row from falling below the fold on a laptop screen; a narrow one falls
        back to two rows.
        """

        count = len(self._images) or 1
        margin, caption = self.MARGIN, self.CAPTION
        for columns in (count, 4, 2, 1):
            if columns > count:
                continue
            cell_width = (self.width() - margin * (columns + 1)) / columns
            if cell_width >= self.MIN_SIDE or columns == 1:
                rows = (count + columns - 1) // columns
                cell_height = (self.height() - margin * (rows + 1)) / rows - caption
                side = max(16.0, min(cell_width, cell_height))
                return columns, rows, cell_width, cell_height, side
        return 1, count, float(self.width()), float(self.height()), 16.0

    def set_maps(
        self,
        maps: dict[str, np.ndarray],
        order: list[str],
        shared_scale: bool = True,
        colormap: str = "magma",
    ) -> None:
        from matplotlib import colormaps

        self._images = []
        if not maps:
            self.update()
            return
        high = max(float(np.asarray(m).max()) for m in maps.values()) if shared_scale else 0.0
        for name in order:
            values = np.asarray(maps.get(name), dtype=float)
            if values.ndim != 2:
                continue
            top = high if shared_scale else float(values.max())
            top = top if top > 0 else 1e-9
            # Row 0 is the bottom of the die, so flip into image order.
            rgba = colormaps[colormap](np.clip(np.flipud(values) / top, 0, 1), bytes=True)
            rgb = np.ascontiguousarray(rgba[:, :, :3])
            image = QImage(
                rgb.data, rgb.shape[1], rgb.shape[0], 3 * rgb.shape[1], QImage.Format.Format_RGB888
            ).copy()
            self._images.append((name, image, float(values.sum()), float(values.max())))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(27, 27, 29))
        if not self._images:
            painter.setPen(QPen(style.MUTED_TEXT))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Select a workload to see its maps"
            )
            painter.end()
            return

        columns, _, cell_width, cell_height, side = self._metrics()
        margin, caption = self.MARGIN, self.CAPTION

        font = QFont(painter.font())
        font.setPointSizeF(8.0)
        painter.setFont(font)

        for index, (name, image, total, _peak) in enumerate(self._images):
            row, column = divmod(index, columns)
            left = margin + column * (cell_width + margin) + max(0.0, (cell_width - side) / 2)
            top = margin + row * (cell_height + caption + margin)
            target = QRectF(left, top, side, side)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            painter.drawImage(target, image)
            painter.setPen(QPen(QColor(90, 90, 96)))
            painter.drawRect(target)
            painter.setPen(QPen(QColor(220, 220, 225)))
            painter.drawText(
                QRectF(left, target.bottom() + 1, side, caption),
                Qt.AlignmentFlag.AlignHCenter,
                f"{name}  {total:.1f} W",
            )
        painter.end()

    def _index_at(self, position) -> int:
        columns, _, cell_width, cell_height, _ = self._metrics()
        margin, caption = self.MARGIN, self.CAPTION
        column = int((position.x() - margin) // max(1.0, cell_width + margin))
        row = int((position.y() - margin) // max(1.0, cell_height + caption + margin))
        if column < 0 or column >= columns:
            return -1
        index = row * columns + column
        return index if 0 <= index < len(self._images) else -1

    def mousePressEvent(self, event) -> None:  # noqa: N802
        index = self._index_at(event.position())
        if index >= 0:
            self.dieClicked.emit(self._images[index][0])

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self._index_at(event.position())
        if index < 0:
            self.setToolTip("")
            return
        name, _, total, peak = self._images[index]
        self.setToolTip(
            f"{name}: {total:.2f} W base power, hottest cell {peak:.3f} W\n"
            "Click to select this chiplet on the layout canvas."
        )


class PowerPanel(QWidget):
    """Edit the workloads and watch the resolved power respond."""

    workloadEdited = Signal()
    selectionChanged = Signal(str)
    structureChanged = Signal()
    #: A workload was ticked or unticked. Kept apart from structureChanged so
    #: toggling one does not rebuild the table the user is clicking in.
    enabledChanged = Signal()
    importRequested = Signal()
    exportRequested = Signal()
    #: A die thumbnail was clicked; the canvas selects that chiplet.
    dieHighlighted = Signal(str)

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._loading = False
        self._current: str | None = None
        self._die_spins: dict[str, object] = {}
        self._weight_spins: dict[str, object] = {}
        self._link_spins: dict[str, object] = {}

        self.workload_table = compact_table(("Run", "Workload", "Base W"))
        self.workload_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.workload_table.itemSelectionChanged.connect(self._on_selection)
        self.workload_table.itemChanged.connect(self._on_check)
        header = self.workload_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)

        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_workload)
        duplicate_button = QPushButton("Duplicate")
        duplicate_button.clicked.connect(self._duplicate_workload)
        rename_button = QPushButton("Rename")
        rename_button.clicked.connect(self._rename_workload)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._delete_workload)
        reset_button = QPushButton("Reset to challenge traces")
        reset_button.setToolTip("Restore the five workloads exactly as challenge_spec.json defines them")
        reset_button.clicked.connect(self._reset_workloads)
        import_button = QPushButton("Import traces...")
        import_button.clicked.connect(self.importRequested.emit)
        export_button = QPushButton("Export traces...")
        export_button.clicked.connect(self.exportRequested.emit)

        buttons = QGridLayout()
        for index, button in enumerate(
            (add_button, duplicate_button, rename_button, delete_button)
        ):
            buttons.addWidget(button, index // 2, index % 2)
        buttons.addWidget(import_button, 2, 0)
        buttons.addWidget(export_button, 2, 1)
        buttons.addWidget(reset_button, 3, 0, 1, 2)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 3, 6)
        left_layout.addWidget(heading("Workloads"))
        left_layout.addWidget(
            muted("Only the ticked workloads are simulated.", wrap=True)
        )
        left_layout.addWidget(self.workload_table, 1)
        left_layout.addLayout(buttons)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._build_editor())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 620])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.set_project(project)

    # ----------------------------------------------------------------- layout
    def _build_editor(self) -> QWidget:
        self.profile_edit = QLineEdit()
        self.profile_edit.setPlaceholderText("What this workload represents")
        self.profile_edit.editingFinished.connect(self._profile_changed)

        self.die_group = QGroupBox("Base die power (W, before link heat)")
        self.die_layout = QGridLayout(self.die_group)
        self.die_layout.setHorizontalSpacing(10)
        self.die_layout.setVerticalSpacing(4)

        self.weight_group = QGroupBox("Hotspot shape")
        weight_layout = QGridLayout(self.weight_group)
        for row, key in enumerate(HOTSPOT_WEIGHT_KEYS):
            box = spin(0.0, 20.0, 1.0, step=0.1, decimals=2, width=84)
            box.valueChanged.connect(lambda _, k=key: self._weight_changed(k))
            self._weight_spins[key] = box
            weight_layout.addWidget(QLabel(WEIGHT_LABELS[key]), row // 2, (row % 2) * 2)
            weight_layout.addWidget(box, row // 2, (row % 2) * 2 + 1)
        weight_layout.setColumnStretch(4, 1)

        self.link_group = QGroupBox("Link utilisation (fraction of peak bandwidth)")
        self.link_layout = QGridLayout(self.link_group)
        self.link_layout.setHorizontalSpacing(10)
        self.link_layout.setVerticalSpacing(4)

        self.custom_check = QCheckBox("Pin explicit 16x16 maps instead of the parametric model")
        self.custom_check.setToolTip(
            "Freezes the maps as they are now. Use it to hold an imported or\n"
            "hand-edited trace; the watt and shape fields then only describe the baseline."
        )
        self.custom_check.toggled.connect(self._custom_toggled)
        self.shared_scale_check = QCheckBox("Common colour scale across dies")
        self.shared_scale_check.setToolTip(
            "Off, each map uses its own scale so every die's shape is visible.\n"
            "On, all eight share one scale, which compares magnitudes but leaves\n"
            "the HBMs nearly black next to the far hotter GPUs."
        )
        self.shared_scale_check.setChecked(False)
        self.shared_scale_check.toggled.connect(lambda _: self.refresh_maps())

        self.maps = MapThumbnails()
        self.maps.dieClicked.connect(self.dieHighlighted.emit)
        maps_group = QGroupBox("Base power maps (W per cell)")
        maps_layout = QVBoxLayout(maps_group)
        maps_row = QHBoxLayout()
        maps_row.addWidget(self.shared_scale_check)
        maps_row.addStretch(1)
        maps_layout.addLayout(maps_row)
        maps_layout.addWidget(self.maps, 1)

        self.resolved_table = compact_table(
            ("Link", "Utilisation", "Active GB/s", "Route mm", "PHY W", "Wire W")
        )
        self.resolved_table.setMaximumHeight(210)
        self.resolved_summary = muted("")
        self.resolved_summary.setWordWrap(True)
        resolved_group = QGroupBox("Resolved power at the current placement")
        resolved_layout = QVBoxLayout(resolved_group)
        resolved_layout.addWidget(self.resolved_summary)
        resolved_layout.addWidget(self.resolved_table, 1)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(6, 6, 6, 6)
        inner_layout.setSpacing(6)
        self.title_label = heading("")
        inner_layout.addWidget(self.title_label)
        inner_layout.addWidget(self.profile_edit)
        inner_layout.addWidget(self.die_group)
        inner_layout.addWidget(self.weight_group)
        inner_layout.addWidget(self.link_group)
        inner_layout.addWidget(self.custom_check)
        inner_layout.addWidget(maps_group, 1)
        inner_layout.addWidget(resolved_group)

        area = QScrollArea()
        area.setWidget(inner)
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        return area

    # ---------------------------------------------------------------- project
    def set_project(self, project: Project) -> None:
        self._project = project
        self._build_die_fields()
        self._build_link_fields()
        self.refresh_list()
        names = list(project.workloads)
        self.select_workload(names[0] if names else None)

    def _build_die_fields(self) -> None:
        while self.die_layout.count():
            item = self.die_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._die_spins.clear()
        order = self._project.gpu_names() + self._project.hbm_names()
        for index, name in enumerate(order):
            box = spin(0.0, 1000.0, 0.0, step=1.0, decimals=2, suffix=" W", width=96)
            box.valueChanged.connect(lambda _, n=name: self._die_changed(n))
            self._die_spins[name] = box
            label = QLabel(name)
            colour = style.GPU_EDGE if self._project.dies[name].is_gpu else style.HBM_EDGE
            label.setStyleSheet(f"color: {colour.name()};")
            column = index % 4
            row = index // 4
            self.die_layout.addWidget(label, row, column * 2)
            self.die_layout.addWidget(box, row, column * 2 + 1)
        self.die_total_label = muted("")
        self.die_layout.addWidget(self.die_total_label, 2, 0, 1, 8)
        self.die_layout.setColumnStretch(8, 1)

    def _build_link_fields(self) -> None:
        while self.link_layout.count():
            item = self.link_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._link_spins.clear()
        for index, link in enumerate(self._project.links):
            link_id = link["id"]
            box = spin(0.0, 1.0, 0.0, step=0.05, decimals=3, width=84)
            box.valueChanged.connect(lambda _, k=link_id: self._link_changed(k))
            self._link_spins[link_id] = box
            label = QLabel(f"{link_id} ({link['from']}-{link['to']}, {link['gb_s']:g} GB/s)")
            label.setStyleSheet(f"color: {style.link_color(link_id).name()};")
            row, column = divmod(index, 2)
            self.link_layout.addWidget(label, row, column * 2)
            self.link_layout.addWidget(box, row, column * 2 + 1)
        self.link_layout.setColumnStretch(4, 1)

    # ------------------------------------------------------------------- list
    def refresh_list(self) -> None:
        self._loading = True
        try:
            names = list(self._project.workloads)
            self.workload_table.setRowCount(len(names))
            for row, name in enumerate(names):
                workload = self._project.workloads[name]
                check = QTableWidgetItem()
                check.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                check.setCheckState(
                    Qt.CheckState.Checked if workload.enabled else Qt.CheckState.Unchecked
                )
                self.workload_table.setItem(row, 0, check)
                label = read_only_item(name)
                if workload.use_custom_maps:
                    label.setText(f"{name}  (pinned maps)")
                self.workload_table.setItem(row, 1, label)
                total = sum(
                    workload.base_watts(die) for die in self._project.dies.values()
                )
                self.workload_table.setItem(row, 2, read_only_item(f"{total:.0f}", True))
            self.workload_table.resizeColumnsToContents()
        finally:
            self._loading = False

    def select_workload(self, name: str | None) -> None:
        self._current = name
        if name is None:
            self.title_label.setText("No workload")
            return
        for row in range(self.workload_table.rowCount()):
            item = self.workload_table.item(row, 1)
            if item is not None and item.text().split("  ")[0] == name:
                self._loading = True
                self.workload_table.selectRow(row)
                self._loading = False
                break
        self.refresh_editor()
        self.selectionChanged.emit(name)

    @property
    def current(self) -> str | None:
        return self._current

    def _on_selection(self) -> None:
        if self._loading:
            return
        rows = {index.row() for index in self.workload_table.selectedIndexes()}
        if not rows:
            return
        item = self.workload_table.item(min(rows), 1)
        if item is None:
            return
        name = item.text().split("  ")[0]
        if name != self._current:
            self._current = name
            self.refresh_editor()
            self.selectionChanged.emit(name)

    def _on_check(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0:
            return
        label = self.workload_table.item(item.row(), 1)
        if label is None:
            return
        name = label.text().split("  ")[0]
        workload = self._project.workloads.get(name)
        if workload is None:
            return
        wanted = item.checkState() == Qt.CheckState.Checked
        if wanted != workload.enabled:
            workload.enabled = wanted
            self.enabledChanged.emit()

    # ----------------------------------------------------------------- editor
    def refresh_editor(self) -> None:
        name = self._current
        if name is None or name not in self._project.workloads:
            return
        workload = self._project.workloads[name]
        self._loading = True
        try:
            self.title_label.setText(name)
            self.profile_edit.setText(workload.profile)
            for die_name, box in self._die_spins.items():
                box.setValue(workload.base_watts(self._project.dies[die_name]))
            for key, box in self._weight_spins.items():
                box.setValue(float(workload.weights.get(key, 1.0)))
            for link_id, box in self._link_spins.items():
                box.setValue(float(workload.link_utilization.get(link_id, 0.0)))
            self.custom_check.setChecked(workload.use_custom_maps)
            pinned = workload.use_custom_maps
            self.die_group.setEnabled(not pinned)
            self.weight_group.setEnabled(not pinned)
            self.die_group.setTitle(
                "Base die power (W) -- read-only while maps are pinned"
                if pinned
                else "Base die power (W, before link heat)"
            )
        finally:
            self._loading = False
        self.refresh_maps()

    def refresh_maps(self) -> None:
        name = self._current
        if name is None or name not in self._project.workloads:
            self.maps.set_maps({}, [])
            return
        try:
            maps = base_power_maps(self._project, name)
        except Exception:
            self.maps.set_maps({}, [])
            return
        order = self._project.gpu_names() + self._project.hbm_names()
        self.maps.set_maps(maps, order, shared_scale=self.shared_scale_check.isChecked())
        total = sum(float(m.sum()) for m in maps.values())
        peak = max((float(m.max()) for m in maps.values()), default=0.0)
        self.die_total_label.setText(
            f"Total base power {total:.1f} W, peak cell {peak:.3f} W"
        )

    def set_preview(self, preview: PowerPreview | None, message: str = "") -> None:
        """Show the resolved per-link PHY and wire watts for the live placement."""

        if preview is None:
            self.resolved_table.setRowCount(0)
            self.resolved_summary.setText(
                message or "Resolved link heat needs a legal layout."
            )
            return
        self.resolved_summary.setText(
            f"Base {preview.base_w:.2f} W + PHY {preview.phy_w:.3f} W "
            f"(inside die {preview.phy_inside_die_w:.3f} W, interposer {preview.phy_outside_die_w:.3f} W) "
            f"+ routed wire {preview.wire_w:.3f} W = {preview.total_w:.2f} W total."
        )
        breakdown = preview.link_breakdown
        self.resolved_table.setRowCount(len(breakdown))
        for row, (link_id, entry) in enumerate(breakdown.items()):
            name_item = read_only_item(link_id)
            name_item.setForeground(style.link_color(link_id))
            self.resolved_table.setItem(row, 0, name_item)
            self.resolved_table.setItem(
                row, 1, read_only_item(f"{entry['utilization']:.3f}", True)
            )
            self.resolved_table.setItem(
                row, 2, read_only_item(f"{entry['active_gb_s']:.1f}", True)
            )
            self.resolved_table.setItem(row, 3, read_only_item(f"{entry['route_mm']:.2f}", True))
            self.resolved_table.setItem(row, 4, read_only_item(f"{entry['phy_w']:.3f}", True))
            self.resolved_table.setItem(row, 5, read_only_item(f"{entry['wire_w']:.3f}", True))
        self.resolved_table.resizeColumnsToContents()

    # ------------------------------------------------------------------ edits
    def _workload(self):
        if self._current is None:
            return None
        return self._project.workloads.get(self._current)

    def _profile_changed(self) -> None:
        workload = self._workload()
        if workload is None or self._loading:
            return
        text = self.profile_edit.text()
        if text != workload.profile:
            workload.profile = text
            self.workloadEdited.emit()

    def _die_changed(self, die_name: str) -> None:
        workload = self._workload()
        if workload is None or self._loading:
            return
        workload.set_base_watts(self._project.dies[die_name], float(self._die_spins[die_name].value()))
        self.refresh_maps()
        self.refresh_list()
        self.workloadEdited.emit()

    def _weight_changed(self, key: str) -> None:
        workload = self._workload()
        if workload is None or self._loading:
            return
        workload.weights[key] = float(self._weight_spins[key].value())
        self.refresh_maps()
        self.workloadEdited.emit()

    def _link_changed(self, link_id: str) -> None:
        workload = self._workload()
        if workload is None or self._loading:
            return
        workload.link_utilization[link_id] = float(self._link_spins[link_id].value())
        self.workloadEdited.emit()

    def _custom_toggled(self, pinned: bool) -> None:
        workload = self._workload()
        if workload is None or self._loading:
            return
        if pinned:
            workload.custom_maps_w = {
                die: array.tolist()
                for die, array in base_power_maps(self._project, workload.name).items()
            }
            workload.use_custom_maps = True
        else:
            workload.use_custom_maps = False
            workload.custom_maps_w = {}
        self.refresh_editor()
        self.refresh_list()
        self.workloadEdited.emit()

    # -------------------------------------------------------------- structure
    def _add_workload(self) -> None:
        name, accepted = QInputDialog.getText(self, "Add workload", "Name:")
        name = name.strip()
        if not accepted or not name:
            return
        if name in self._project.workloads:
            QMessageBox.warning(self, "Add workload", f"'{name}' already exists.")
            return
        from ..core.project import Workload

        self._project.workloads[name] = Workload(
            name=name,
            profile="new workload",
            gpu_w=[50.0] * 4,
            hbm_w=[20.0] * 4,
            weights={key: 1.0 for key in HOTSPOT_WEIGHT_KEYS},
            link_utilization={link_id: 0.5 for link_id in self._project.link_ids},
        )
        self.refresh_list()
        self.select_workload(name)
        self.structureChanged.emit()

    def _duplicate_workload(self) -> None:
        source = self._workload()
        if source is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Duplicate workload", "New name:", text=f"{source.name}_copy"
        )
        name = name.strip()
        if not accepted or not name or name in self._project.workloads:
            return
        self._project.workloads[name] = source.copy_as(name)
        self.refresh_list()
        self.select_workload(name)
        self.structureChanged.emit()

    def _rename_workload(self) -> None:
        workload = self._workload()
        if workload is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Rename workload", "New name:", text=workload.name
        )
        name = name.strip()
        if not accepted or not name or name == workload.name:
            return
        if name in self._project.workloads:
            QMessageBox.warning(self, "Rename workload", f"'{name}' already exists.")
            return
        # Rebuild in place so the run order the user sees is preserved.
        renamed = {}
        for key, value in self._project.workloads.items():
            if key == workload.name:
                value.name = name
                renamed[name] = value
            else:
                renamed[key] = value
        self._project.workloads = renamed
        self.refresh_list()
        self.select_workload(name)
        self.structureChanged.emit()

    def _delete_workload(self) -> None:
        workload = self._workload()
        if workload is None:
            return
        if len(self._project.workloads) <= 1:
            QMessageBox.warning(self, "Delete workload", "Keep at least one workload.")
            return
        confirm = QMessageBox.question(
            self,
            "Delete workload",
            f"Delete '{workload.name}' and its power trace?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        del self._project.workloads[workload.name]
        self.refresh_list()
        names = list(self._project.workloads)
        self.select_workload(names[0] if names else None)
        self.structureChanged.emit()

    def _reset_workloads(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Reset traces",
            "Replace every workload with the five from challenge_spec.json?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        from ..core.project import Workload
        from ..core.simcore import default_spec

        spec = default_spec()
        self._project.workloads = {
            name: Workload.from_spec(name, entry) for name, entry in spec["workloads"].items()
        }
        self.refresh_list()
        names = list(self._project.workloads)
        self.select_workload(names[0] if names else None)
        self.structureChanged.emit()


__all__ = ["WEIGHT_LABELS", "MapThumbnails", "PowerPanel"]
