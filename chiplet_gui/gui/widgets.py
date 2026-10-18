"""Small shared widgets: labelled spin boxes, headings and a status line."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "heading")
    return label


def muted(text: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "muted")
    label.setWordWrap(wrap)
    return label


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


def spin(
    minimum: float,
    maximum: float,
    value: float,
    step: float = 0.1,
    decimals: int = 3,
    suffix: str = "",
    width: int = 92,
) -> QDoubleSpinBox:
    """A float editor with sane keyboard behaviour for engineering values."""

    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setKeyboardTracking(False)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    if suffix:
        box.setSuffix(suffix)
    box.setFixedWidth(width)
    return box


def int_spin(
    minimum: int, maximum: int, value: int, suffix: str = "", width: int = 92
) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setValue(value)
    box.setKeyboardTracking(False)
    box.setAlignment(Qt.AlignmentFlag.AlignRight)
    if suffix:
        box.setSuffix(suffix)
    box.setFixedWidth(width)
    return box


def read_only_item(text: str, align_right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if align_right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def stretch_column(table: QTableWidget, index: int = 0) -> None:
    """Let one column absorb the spare width and size the rest to their content.

    Numeric tables otherwise end with one column stretched across half the
    panel, which reads as a layout mistake.
    """

    from PySide6.QtWidgets import QHeaderView

    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    for column in range(table.columnCount()):
        header.setSectionResizeMode(
            column,
            QHeaderView.ResizeMode.Stretch if column == index else QHeaderView.ResizeMode.ResizeToContents,
        )


def compact_table(headers: Iterable[str], rows: int = 0) -> QTableWidget:
    """A table sized for dense numeric display inside a dock."""

    columns = list(headers)
    table = QTableWidget(rows, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
    table.horizontalHeader().setStretchLastSection(True)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return table


class StatusLine(QWidget):
    """A one-line verdict with a coloured role, used for legality and runs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)

    def set_message(self, text: str, role: str = "muted") -> None:
        self._label.setText(text)
        self._label.setProperty("role", role)
        # A property change needs an explicit restyle to take effect.
        self._label.style().unpolish(self._label)
        self._label.style().polish(self._label)


class LabelledRow(QWidget):
    """A caption followed by one or more widgets on a single row."""

    def __init__(self, caption: str, *widgets: QWidget, stretch: bool = True) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(caption)
        label.setMinimumWidth(150)
        layout.addWidget(label)
        for widget in widgets:
            layout.addWidget(widget)
        if stretch:
            layout.addStretch(1)


class CheckRow(QCheckBox):
    """A checkbox that reports its new state through one callback."""

    def __init__(self, caption: str, checked: bool, on_change: Callable[[bool], None]) -> None:
        super().__init__(caption)
        self.setChecked(checked)
        self.toggled.connect(on_change)


class FormBlock(QWidget):
    """A vertical stack of rows with a small, consistent gutter."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 2)
        self._layout.setSpacing(4)

    def add(self, widget: QWidget) -> QWidget:
        self._layout.addWidget(widget)
        return widget

    def add_row(self, caption: str, *widgets: QWidget) -> LabelledRow:
        row = LabelledRow(caption, *widgets)
        self._layout.addWidget(row)
        return row

    def add_stretch(self) -> None:
        self._layout.addStretch(1)


__all__ = [
    "CheckRow",
    "FormBlock",
    "LabelledRow",
    "StatusLine",
    "compact_table",
    "heading",
    "int_spin",
    "muted",
    "read_only_item",
    "separator",
    "spin",
    "stretch_column",
]
