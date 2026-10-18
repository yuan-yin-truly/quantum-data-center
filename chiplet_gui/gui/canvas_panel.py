"""The centre of the window: the canvas plus its overlay and mode controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.project import Project
from .canvas import MODE_ROUTE, LayoutCanvas
from .render import ColorBar, Field
from .widgets import muted

#: Overlay choices, as ``(label, key)``. ``temperature`` needs a finished run.
OVERLAYS = (
    ("No overlay", "none"),
    ("Die-plane power", "die"),
    ("Interposer power (wire + outside PHY)", "interposer"),
    ("Combined power density", "combined"),
    ("Temperature (last run)", "temperature"),
)

SNAP_STEPS = (
    ("Free", 0.0),
    ("0.05 mm", 0.05),
    ("0.1 mm", 0.1),
    ("0.25 mm", 0.25),
    ("0.5 mm (track pitch)", 0.5),
)


class CanvasPanel(QWidget):
    """Wraps :class:`LayoutCanvas` with the controls that change what it shows."""

    overlayChanged = Signal()
    requestRouteExit = Signal()

    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas = LayoutCanvas(project, self)

        self.overlay_box = QComboBox()
        for label, key in OVERLAYS:
            self.overlay_box.addItem(label, key)
        self.overlay_box.setCurrentIndex(3)
        self.overlay_box.currentIndexChanged.connect(lambda _: self.overlayChanged.emit())

        self.workload_box = QComboBox()
        self.workload_box.setMinimumWidth(150)
        self.workload_box.currentIndexChanged.connect(lambda _: self.overlayChanged.emit())

        self.snap_box = QComboBox()
        for label, step in SNAP_STEPS:
            self.snap_box.addItem(label, step)
        self.snap_box.setCurrentIndex(2)
        self.snap_box.currentIndexChanged.connect(self._apply_snap)

        self.ports_check = self._toggle("Ports", True, "show_ports")
        self.routes_check = self._toggle("Wires", True, "show_routes")
        self.grid_check = self._toggle("Track grid", False, "show_track_grid")
        self.labels_check = QCheckBox("Die readouts")
        self.labels_check.setChecked(True)
        self.labels_check.toggled.connect(self._apply_annotations)

        fit_button = QToolButton()
        fit_button.setText("Fit")
        fit_button.setToolTip("Fit the whole package in the view")
        fit_button.clicked.connect(self.canvas.fit)

        zoom_in = QToolButton()
        zoom_in.setText("+")
        zoom_in.clicked.connect(lambda: self.canvas.zoom(1.25))
        zoom_out = QToolButton()
        zoom_out.setText("-")
        zoom_out.clicked.connect(lambda: self.canvas.zoom(0.8))

        controls = QHBoxLayout()
        controls.setContentsMargins(6, 4, 6, 2)
        controls.setSpacing(8)
        controls.addWidget(QLabel("Overlay"))
        controls.addWidget(self.overlay_box)
        controls.addWidget(QLabel("Workload"))
        controls.addWidget(self.workload_box)
        controls.addSpacing(10)
        controls.addWidget(QLabel("Snap"))
        controls.addWidget(self.snap_box)
        controls.addSpacing(10)
        controls.addWidget(self.ports_check)
        controls.addWidget(self.routes_check)
        controls.addWidget(self.grid_check)
        controls.addWidget(self.labels_check)
        controls.addStretch(1)
        controls.addWidget(fit_button)
        controls.addWidget(zoom_out)
        controls.addWidget(zoom_in)

        self.mode_banner = QLabel("")
        self.mode_banner.setVisible(False)
        self.mode_banner.setWordWrap(True)
        self.mode_banner.setStyleSheet(
            "background: #27343f; color: #cfe6ff; border: 1px solid #3f5a70;"
            "border-radius: 3px; padding: 5px 8px;"
        )

        self.colorbar = ColorBar()
        self.colorbar.setVisible(False)

        self.hover_label = muted("")
        self.hover_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.hint_label = muted(
            "Drag a chiplet to move it. Arrow keys nudge by the snap step, shift for ten."
        )
        footer = QHBoxLayout()
        footer.setContentsMargins(6, 0, 6, 4)
        footer.addWidget(self.hint_label, 1)
        footer.addWidget(self.hover_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(controls)
        layout.addWidget(self.mode_banner)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.colorbar)
        layout.addLayout(footer)

        self.canvas.hovered.connect(self.hover_label.setText)
        self.canvas.draftChanged.connect(self._show_draft_message)
        self.canvas.routeCancelled.connect(self._on_route_cancelled)
        self._apply_snap()

    # ---------------------------------------------------------------- helpers
    def _toggle(self, caption: str, checked: bool, attribute: str) -> QCheckBox:
        box = QCheckBox(caption)
        box.setChecked(checked)

        def apply(state: bool) -> None:
            setattr(self.canvas, attribute, state)
            self.overlayChanged.emit()

        box.toggled.connect(apply)
        return box

    def _apply_snap(self) -> None:
        self.canvas.snap_mm = float(self.snap_box.currentData())

    def _apply_annotations(self, enabled: bool) -> None:
        self.canvas.show_annotations = enabled
        self.overlayChanged.emit()

    # ---------------------------------------------------------------- display
    @property
    def overlay_key(self) -> str:
        return str(self.overlay_box.currentData())

    @property
    def workload(self) -> str | None:
        return self.workload_box.currentData()

    def set_workloads(self, names: list[str], keep: str | None = None) -> None:
        """Refresh the workload selector, preserving the choice where possible."""

        wanted = keep or self.workload
        self.workload_box.blockSignals(True)
        self.workload_box.clear()
        for name in names:
            self.workload_box.addItem(name, name)
        if wanted in names:
            self.workload_box.setCurrentIndex(names.index(wanted))
        self.workload_box.blockSignals(False)

    def set_field(self, field: Field | None) -> None:
        self.canvas.set_field(field)
        self.colorbar.set_field(field)
        self.colorbar.setVisible(field is not None)

    def set_temperature_available(self, available: bool) -> None:
        """Grey out the temperature overlay until a run has produced one."""

        index = self.overlay_box.findData("temperature")
        if index < 0:
            return
        model = self.overlay_box.model()
        model.item(index).setEnabled(available)
        if not available and self.overlay_key == "temperature":
            self.overlay_box.setCurrentIndex(self.overlay_box.findData("combined"))

    # ------------------------------------------------------------------ modes
    def show_route_banner(self, link_id: str, detail: str = "") -> None:
        self.mode_banner.setText(
            f"<b>Drawing wire {link_id}.</b> Click track cells to add waypoints, right-click or "
            "backspace to step back, double-click or Enter to finish at the far port, Escape to "
            f"cancel. {detail}"
        )
        self.mode_banner.setVisible(True)

    def _show_draft_message(self, message: str) -> None:
        if self.canvas.mode == MODE_ROUTE and self.canvas.route_link:
            self.show_route_banner(self.canvas.route_link, message)

    def _on_route_cancelled(self) -> None:
        self.mode_banner.setVisible(False)
        self.requestRouteExit.emit()


__all__ = ["OVERLAYS", "SNAP_STEPS", "CanvasPanel"]
