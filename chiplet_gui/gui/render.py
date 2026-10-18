"""Turn numerical fields into images and colour bars for the canvas.

Two kinds of field are shown over the interposer: power density in W/mm2
(which the GUI can compute instantly) and HotSpot's die-plane temperature in
Celsius (which needs a run). Both end up as a QImage covering the interposer
footprint, so the canvas paints them the same way.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from matplotlib import colormaps
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

#: Pixels per millimetre used when compositing a power field.
POWER_RESOLUTION = 8


@dataclass
class Field:
    """A scalar field over the interposer, ready to draw.

    ``image`` already covers the whole interposer footprint, so the canvas only
    has to stretch it over the package rectangle.
    """

    image: QImage
    low: float
    high: float
    label: str
    colormap: str
    #: Interpolate when stretching. Off for power, whose tile structure is real.
    smooth: bool = True

    @property
    def span(self) -> tuple[float, float]:
        return self.low, self.high


def _to_image(values: np.ndarray, low: float, high: float, colormap: str) -> QImage:
    """Map a 2-D array to an RGB QImage, row 0 at the top."""

    span = high - low
    normalised = np.zeros_like(values, dtype=float) if span <= 0 else (values - low) / span
    rgba = colormaps[colormap](np.clip(normalised, 0.0, 1.0), bytes=True)
    rgb = np.ascontiguousarray(rgba[:, :, :3])
    height, width, _ = rgb.shape
    # QImage does not own the buffer, so hand back a detached copy.
    return QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


def temperature_image(
    temperatures: np.ndarray,
    low: float | None = None,
    high: float | None = None,
    colormap: str = "inferno",
) -> Field:
    """HotSpot's die-plane temperature grid in Celsius, as a drawable field.

    ``run_simulations.parse_grid`` returns the grid with row 0 along the top
    edge of the package, which is the orientation a QImage wants, so no flip.
    Passing *low* and *high* pins the scale, which is what lets several
    workloads be compared on one colour bar.
    """

    values = np.asarray(temperatures, dtype=float)
    lo = float(values.min()) if low is None else float(low)
    hi = float(values.max()) if high is None else float(high)
    if hi - lo < 1e-9:
        hi = lo + 1e-9
    return Field(
        image=_to_image(values, lo, hi, colormap),
        low=lo,
        high=hi,
        label="Die-plane temperature (C)",
        colormap=colormap,
    )


def power_density_image(
    preview,
    project,
    mode: str = "combined",
    colormap: str = "magma",
    resolution: int = POWER_RESOLUTION,
) -> Field:
    """Composite a power-density field in W/mm2 from one :class:`PowerPreview`.

    The die maps and the interposer tiles are watts per cell of different
    sizes, so both are converted to density before they are combined. That
    makes the three modes directly comparable:

    * ``die`` -- base power plus the inside half of each PHY rectangle;
    * ``interposer`` -- routed-wire heat plus the outside half of each PHY;
    * ``combined`` -- their sum, i.e. all heat injected under that square mm.
    """

    width_mm, height_mm = project.interposer_mm
    columns = max(1, int(round(width_mm * resolution)))
    rows = max(1, int(round(height_mm * resolution)))

    # Pixel centres in mm, y measured up from the lower-left corner.
    xs = (np.arange(columns) + 0.5) * width_mm / columns
    ys = (np.arange(rows) + 0.5) * height_mm / rows
    grid_x, grid_y = np.meshgrid(xs, ys)

    field = np.zeros((rows, columns), dtype=float)

    if mode in ("interposer", "combined"):
        tiles = np.asarray(preview.interposer_tiles_w, dtype=float)
        tile_rows, tile_columns = tiles.shape
        tile_area = (width_mm / tile_columns) * (height_mm / tile_rows)
        i = np.clip((grid_x * tile_columns / width_mm).astype(int), 0, tile_columns - 1)
        j = np.clip((grid_y * tile_rows / height_mm).astype(int), 0, tile_rows - 1)
        field += tiles[j, i] / tile_area

    if mode in ("die", "combined"):
        for name, die_map in preview.die_maps_w.items():
            if name not in project.placements_mm:
                continue
            x0, y0, x1, y1 = project.die_box(name)
            values = np.asarray(die_map, dtype=float)
            pixel_rows, pixel_columns = values.shape
            pixel_area = ((x1 - x0) / pixel_columns) * ((y1 - y0) / pixel_rows)
            inside = (grid_x >= x0) & (grid_x < x1) & (grid_y >= y0) & (grid_y < y1)
            if not inside.any():
                continue
            # Map row 0 of a die map to the bottom edge of that die.
            col = np.clip(((grid_x - x0) / (x1 - x0) * pixel_columns).astype(int), 0, pixel_columns - 1)
            row = np.clip(((grid_y - y0) / (y1 - y0) * pixel_rows).astype(int), 0, pixel_rows - 1)
            field = np.where(inside, field + values[row, col] / pixel_area, field)

    # Flip to image order: row 0 of a QImage is the top of the package.
    picture = np.flipud(field)
    high = float(picture.max())
    return Field(
        image=_to_image(picture, 0.0, high if high > 0 else 1e-9, colormap),
        low=0.0,
        high=high,
        label="Power density (W/mm2)",
        colormap=colormap,
        smooth=False,
    )


class ColorBar(QWidget):
    """A compact horizontal colour bar with numeric end labels."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._field: Field | None = None
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_field(self, field: Field | None) -> None:
        self._field = field
        self.setVisible(field is not None)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._field is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        bar = QRectF(4, 4, max(1.0, self.width() - 8), 12.0)
        gradient = QLinearGradient(bar.topLeft(), bar.topRight())
        colormap = colormaps[self._field.colormap]
        for stop in range(11):
            red, green, blue, _ = colormap(stop / 10.0, bytes=True)
            gradient.setColorAt(stop / 10.0, QColor(int(red), int(green), int(blue)))
        painter.fillRect(bar, gradient)
        painter.setPen(QPen(QColor(110, 110, 115)))
        painter.drawRect(bar)

        painter.setPen(QPen(QColor(200, 200, 205)))
        text = QRectF(4, bar.bottom() + 1, bar.width(), 16)
        painter.drawText(text, Qt.AlignmentFlag.AlignLeft, f"{self._field.low:.4g}")
        painter.drawText(text, Qt.AlignmentFlag.AlignHCenter, self._field.label)
        painter.drawText(text, Qt.AlignmentFlag.AlignRight, f"{self._field.high:.4g}")
        painter.end()


__all__ = [
    "POWER_RESOLUTION",
    "ColorBar",
    "Field",
    "power_density_image",
    "temperature_image",
]
