"""The layout dock: exact placement numbers, legality and the wire list."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.analysis import LayoutReport
from ..core.project import Project
from . import style
from .widgets import StatusLine, compact_table, int_spin, muted, read_only_item, spin


class PlacementPanel(QWidget):
    """Numeric twin of the canvas: every die origin to three decimals.

    Dragging is for exploring and typing is for pinning a value down, so both
    edit the same project and each refreshes the other.
    """

    placementEdited = Signal(str, float, float)
    dieSelected = Signal(list)
    exampleRequested = Signal(str)
    randomiseRequested = Signal(int, float)
    snapAllRequested = Signal()

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._loading = False
        self._spins: dict[str, tuple] = {}

        self.table = compact_table(("Die", "Kind", "X (mm)", "Y (mm)", "Size (mm)"))
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._emit_selection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.example_box = QComboBox()
        load_example = QPushButton("Load")
        load_example.setToolTip("Replace the placement with this reference layout")
        load_example.clicked.connect(
            lambda: self.exampleRequested.emit(str(self.example_box.currentText()))
        )

        self.seed_spin = int_spin(0, 99999999, 20261017, width=104)
        self.jitter_spin = spin(0.05, 5.0, 0.65, step=0.05, decimals=2, suffix=" mm", width=84)
        randomise = QPushButton("Randomise")
        randomise.setToolTip(
            "Jitter the current placement and keep the first legal result, the same way\n"
            "the challenge's generate_random_layout.py does"
        )
        randomise.clicked.connect(
            lambda: self.randomiseRequested.emit(int(self.seed_spin.value()), float(self.jitter_spin.value()))
        )
        snap_all = QPushButton("Snap all to grid")
        snap_all.clicked.connect(self.snapAllRequested.emit)

        tools = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("Reference"))
        row.addWidget(self.example_box, 1)
        row.addWidget(load_example)
        tools.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Seed"))
        row.addWidget(self.seed_spin)
        row.addWidget(QLabel("Jitter"))
        row.addWidget(self.jitter_spin)
        row.addWidget(randomise)
        row.addStretch(1)
        tools.addLayout(row)
        tools.addWidget(snap_all)

        self.status = StatusLine()
        self.budget_bar = QProgressBar()
        self.budget_bar.setFormat("%v of %m GB/s*mm routed")
        self.budget_bar.setTextVisible(True)
        self.issues = QLabel("")
        self.issues.setWordWrap(True)
        self.issues.setProperty("role", "error")

        legality = QGroupBox("Legality")
        legality_layout = QVBoxLayout(legality)
        legality_layout.setSpacing(4)
        legality_layout.addWidget(self.status)
        legality_layout.addWidget(self.budget_bar)
        legality_layout.addWidget(self.issues)

        placement = QGroupBox("Placement")
        placement_layout = QVBoxLayout(placement)
        placement_layout.addWidget(self.table, 1)
        placement_layout.addLayout(tools)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(placement, 1)
        layout.addWidget(legality)

        self.set_project(project)

    # ---------------------------------------------------------------- project
    def set_project(self, project: Project) -> None:
        self._project = project
        self._rebuild_table()
        self.example_box.clear()
        self.example_box.addItems(["ring_center", "ring_compact", "ring_spread"])

    def _rebuild_table(self) -> None:
        self._loading = True
        try:
            names = sorted(self._project.placements_mm)
            self.table.setRowCount(len(names))
            self._spins.clear()
            width_mm, height_mm = self._project.interposer_mm
            for row, name in enumerate(names):
                die = self._project.dies[name]
                x_mm, y_mm = (float(v) for v in self._project.placements_mm[name])
                self.table.setItem(row, 0, read_only_item(name))
                self.table.setItem(row, 1, read_only_item(die.kind))
                x_spin = spin(0.0, float(width_mm), x_mm, step=0.1, decimals=3, width=84)
                y_spin = spin(0.0, float(height_mm), y_mm, step=0.1, decimals=3, width=84)
                x_spin.valueChanged.connect(lambda _, n=name: self._emit_edit(n))
                y_spin.valueChanged.connect(lambda _, n=name: self._emit_edit(n))
                self.table.setCellWidget(row, 2, x_spin)
                self.table.setCellWidget(row, 3, y_spin)
                self.table.setItem(
                    row, 4, read_only_item(f"{die.size_mm[0]:g} x {die.size_mm[1]:g}", True)
                )
                self._spins[name] = (x_spin, y_spin)
            self.table.resizeColumnsToContents()
        finally:
            self._loading = False

    def _emit_edit(self, name: str) -> None:
        if self._loading:
            return
        x_spin, y_spin = self._spins[name]
        self.placementEdited.emit(name, float(x_spin.value()), float(y_spin.value()))

    def _emit_selection(self) -> None:
        if self._loading:
            return
        rows = {index.row() for index in self.table.selectedIndexes()}
        names = []
        for row in sorted(rows):
            item = self.table.item(row, 0)
            if item:
                names.append(item.text())
        self.dieSelected.emit(names)

    # ----------------------------------------------------------------- update
    def refresh(self, report: LayoutReport | None) -> None:
        """Pull the numbers back from the project and show the verdict."""

        self._loading = True
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is None:
                    continue
                name = item.text()
                x_mm, y_mm = (float(v) for v in self._project.placements_mm[name])
                x_spin, y_spin = self._spins[name]
                if abs(x_spin.value() - x_mm) > 1e-9:
                    x_spin.setValue(x_mm)
                if abs(y_spin.value() - y_mm) > 1e-9:
                    y_spin.setValue(y_mm)
                faulty = bool(report and name in report.die_errors)
                for column in range(self.table.columnCount()):
                    cell = self.table.item(row, column)
                    if cell is not None:
                        cell.setForeground(
                            style.ERROR_COLOR if faulty else style.TEXT_COLOR
                        )
        finally:
            self._loading = False

        if report is None:
            self.status.set_message("Not validated yet.", "muted")
            self.issues.setText("")
            return

        if report.legal:
            self.status.set_message("Layout is legal.", "ok")
            self.issues.setText("")
        else:
            self.status.set_message(report.message, "error")
            self.issues.setText("\n".join(report.issues))

        limit = report.route_limit
        used = report.weighted_route
        if limit and used is not None:
            self.budget_bar.setMaximum(int(limit))
            self.budget_bar.setValue(int(used))
            self.budget_bar.setVisible(True)
        else:
            self.budget_bar.setVisible(False)

    def select_dies(self, names: list[str]) -> None:
        self._loading = True
        try:
            wanted = set(names)
            self.table.clearSelection()
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is not None and item.text() in wanted:
                    self.table.selectRow(row)
        finally:
            self._loading = False


class LinkPanel(QWidget):
    """The eight compulsory links, their routed length and how each was routed."""

    drawRequested = Signal(str)
    autoRequested = Signal(str)
    bakeAllRequested = Signal()
    clearRequested = Signal(str)
    clearAllRequested = Signal()

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project

        self.table = compact_table(
            ("Link", "Route", "GB/s", "Routed", "Reach", "Wire")
        )
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(lambda _: self._draw_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.draw_button = QPushButton("Draw wire...")
        self.draw_button.setToolTip("Draw this link's route on the canvas by clicking track cells")
        self.draw_button.clicked.connect(self._draw_selected)

        self.auto_button = QPushButton("Auto-route")
        self.auto_button.setToolTip("Drop the hand-drawn route and let the judge's router decide")
        self.auto_button.clicked.connect(
            lambda: self._with_selection(self.autoRequested.emit)
        )

        self.bake_button = QPushButton("Copy all auto routes to editable wires")
        self.bake_button.setToolTip(
            "Turn the judge's own routes into hand-drawn ones you can then adjust"
        )
        self.bake_button.clicked.connect(self.bakeAllRequested.emit)

        self.clear_all_button = QPushButton("Clear all hand-drawn wires")
        self.clear_all_button.clicked.connect(self.clearAllRequested.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.draw_button)
        buttons.addWidget(self.auto_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.bake_button)
        layout.addWidget(self.clear_all_button)
        layout.addWidget(
            muted(
                "Dashed wires are the judge's automatic shortest routes. Solid wires are yours "
                "and are exported as wire_routes_grid.",
                wrap=True,
            )
        )
        self.set_project(project)

    def set_project(self, project: Project) -> None:
        self._project = project
        self.refresh(None)

    def selected_link(self) -> str | None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            return None
        item = self.table.item(min(rows), 0)
        return item.text() if item else None

    def _draw_selected(self) -> None:
        self._with_selection(self.drawRequested.emit)

    def _with_selection(self, emit) -> None:
        link_id = self.selected_link()
        if link_id:
            emit(link_id)

    def _update_buttons(self) -> None:
        link_id = self.selected_link()
        self.draw_button.setEnabled(bool(link_id))
        manual = bool(link_id and link_id in self._project.wire_routes_grid)
        self.auto_button.setEnabled(manual)
        self.auto_button.setText("Drop hand-drawn route" if manual else "Auto-route")

    def refresh(self, report: LayoutReport | None) -> None:
        keep = self.selected_link()
        links = self._project.links
        self.table.setRowCount(len(links))
        for row, link in enumerate(links):
            link_id = link["id"]
            route = report.route(link_id) if report else None
            manual = link_id in self._project.wire_routes_grid
            colour = style.link_color(link_id)

            name_item = read_only_item(link_id)
            name_item.setForeground(colour)
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, read_only_item(f"{link['from']}-{link['to']}"))
            self.table.setItem(row, 2, read_only_item(f"{link['gb_s']:g}", True))

            if route:
                length = float(route["route_length_mm"])
                limit = float(route["limit_mm"])
                routed = read_only_item(f"{length:.2f}", True)
                routed.setForeground(
                    style.ERROR_COLOR
                    if length > limit + 1e-9
                    else (style.WARN_COLOR if length > 0.9 * limit else style.OK_COLOR)
                )
            else:
                routed = read_only_item("-", True)
            self.table.setItem(row, 3, routed)
            self.table.setItem(row, 4, read_only_item(f"{link['max_route_mm']:g}", True))
            self.table.setItem(row, 5, read_only_item("hand-drawn" if manual else "auto"))
        self.table.resizeColumnsToContents()

        if keep:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is not None and item.text() == keep:
                    self.table.selectRow(row)
                    break
        self.bake_button.setEnabled(bool(report and report.legal))
        self.clear_all_button.setEnabled(bool(self._project.wire_routes_grid))
        self._update_buttons()


__all__ = ["LinkPanel", "PlacementPanel"]
