"""Dark engineering theme and the colours the canvas and tables share."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

#: Die fill and outline per kind, plus the selected/invalid variants.
GPU_FILL = QColor(37, 72, 112)
GPU_EDGE = QColor(120, 180, 246)
HBM_FILL = QColor(94, 61, 28)
HBM_EDGE = QColor(240, 170, 90)
INVALID_FILL = QColor(120, 36, 40)
INVALID_EDGE = QColor(244, 100, 104)
SELECTED_EDGE = QColor(255, 255, 255)

INTERPOSER_FILL = QColor(26, 26, 28)
INTERPOSER_EDGE = QColor(110, 110, 115)
CLEARANCE_EDGE = QColor(90, 90, 96)
COOLING_EDGE = QColor(86, 160, 140)
TRACK_GRID = QColor(58, 58, 64)
PORT_COLOR = QColor(255, 214, 102)
TEXT_COLOR = QColor(226, 226, 230)
MUTED_TEXT = QColor(150, 150, 158)

OK_COLOR = QColor(129, 199, 132)
WARN_COLOR = QColor(255, 183, 77)
ERROR_COLOR = QColor(239, 108, 112)

#: One stable colour per link, so a wire keeps its identity across panels.
LINK_COLORS = {
    "P0": QColor(102, 187, 255),
    "P1": QColor(129, 212, 162),
    "P2": QColor(240, 142, 190),
    "P3": QColor(186, 160, 245),
    "S0": QColor(120, 200, 230),
    "S1": QColor(200, 214, 130),
    "S2": QColor(240, 180, 140),
    "S3": QColor(170, 180, 220),
}

_FALLBACK_LINK_COLORS = (
    QColor(102, 187, 255),
    QColor(129, 212, 162),
    QColor(240, 142, 190),
    QColor(186, 160, 245),
    QColor(240, 180, 140),
)


def link_color(link_id: str) -> QColor:
    """A stable colour for any link id, including ones added by the user."""

    if link_id in LINK_COLORS:
        return LINK_COLORS[link_id]
    return _FALLBACK_LINK_COLORS[abs(hash(link_id)) % len(_FALLBACK_LINK_COLORS)]


def die_colors(kind: str) -> tuple[QColor, QColor]:
    """``(fill, edge)`` for a die of this kind."""

    return (GPU_FILL, GPU_EDGE) if kind == "GPU" else (HBM_FILL, HBM_EDGE)


STYLESHEET = """
QWidget { font-size: 12px; }
QGroupBox {
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: #64b5f6;
    font-weight: 600;
}
QToolBar { spacing: 6px; padding: 4px; border: none; }
QToolButton { padding: 3px 6px; }
QPlainTextEdit, QTextEdit { background: #1b1b1b; color: #d0d0d0; }
QTreeWidget, QTableWidget, QListWidget { background: #232323; alternate-background-color: #282828; }
QHeaderView::section {
    background: #333336;
    color: #dcdcdc;
    padding: 3px 6px;
    border: none;
    border-right: 1px solid #2a2a2a;
}
QTabBar::tab { padding: 5px 12px; }
QTabBar::tab:selected { color: #64b5f6; }
QProgressBar { border: 1px solid #4a4a4a; border-radius: 3px; text-align: center; }
QProgressBar::chunk { background-color: #1565c0; }
QLabel[role="heading"] { color: #64b5f6; font-weight: 600; }
QLabel[role="muted"] { color: #96969e; }
QLabel[role="ok"] { color: #81c784; }
QLabel[role="warn"] { color: #ffb74d; }
QLabel[role="error"] { color: #ef6c70; }
QDoubleSpinBox, QSpinBox, QLineEdit, QComboBox { padding: 2px 4px; }
"""


def apply_theme(app) -> None:
    """Restrained dark theme, matching the GaN thermal simulator GUI."""

    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(43, 43, 43))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(21, 101, 192))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(130, 130, 130)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(130, 130, 130)
    )
    app.setPalette(palette)


__all__ = [
    "CLEARANCE_EDGE",
    "COOLING_EDGE",
    "ERROR_COLOR",
    "GPU_EDGE",
    "GPU_FILL",
    "HBM_EDGE",
    "HBM_FILL",
    "INTERPOSER_EDGE",
    "INTERPOSER_FILL",
    "INVALID_EDGE",
    "INVALID_FILL",
    "LINK_COLORS",
    "MUTED_TEXT",
    "OK_COLOR",
    "PORT_COLOR",
    "SELECTED_EDGE",
    "STYLESHEET",
    "TEXT_COLOR",
    "TRACK_GRID",
    "WARN_COLOR",
    "apply_theme",
    "die_colors",
    "link_color",
]
