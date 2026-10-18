"""Background execution, so the window stays responsive during a solve.

A full five-workload run is minutes of HotSpot time. It happens on a worker
thread with progress and log lines streaming back, and ``cancel`` kills the
HotSpot processes rather than waiting for them.
"""

from __future__ import annotations

import traceback
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ..core.project import Project
from ..core.runner import RunCancelled, RunResult, SimulationRunner


class _Worker(QObject):
    """Runs one simulation on the worker thread."""

    progress = Signal(float, str)
    logged = Signal(str)
    finished = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()

    def __init__(
        self,
        project: Project,
        workloads: Sequence[str],
        run_dir: Path | None,
        label: str,
        inputs_only: bool,
    ) -> None:
        super().__init__()
        self._project = project
        self._workloads = list(workloads)
        self._run_dir = run_dir
        self._label = label
        self._inputs_only = inputs_only
        self.runner = SimulationRunner(
            progress=lambda fraction, message: self.progress.emit(fraction, message),
            log=lambda message: self.logged.emit(message),
        )

    def run(self) -> None:
        try:
            if self._inputs_only:
                directory, _, _ = self.runner.prepare(
                    self._project, self._workloads, self._run_dir
                )
                self.progress.emit(1.0, "HotSpot inputs exported")
                self.finished.emit(directory)
                return
            result = self.runner.run(
                self._project, self._workloads, self._run_dir, self._label
            )
            self.finished.emit(result)
        except RunCancelled:
            self.cancelled.emit()
        except Exception as exc:  # surfaced in the log panel and a dialog
            self.failed.emit(str(exc), traceback.format_exc())


class RunController(QObject):
    """Owns the worker thread and the one run that may be in flight."""

    progress = Signal(float, str)
    logged = Signal(str)
    runFinished = Signal(object)  # RunResult
    inputsExported = Signal(object)  # Path
    failed = Signal(str, str)
    cancelled = Signal()
    busyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._inputs_only = False

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(
        self,
        project: Project,
        workloads: Sequence[str],
        run_dir: Path | None = None,
        label: str | None = None,
        inputs_only: bool = False,
    ) -> None:
        """Begin a run on a private copy of the project.

        The copy matters: the user keeps dragging dies while HotSpot solves,
        and the result must describe the layout that was actually simulated.
        """

        if self.busy:
            raise RuntimeError("A simulation is already running.")
        snapshot = project.copy()
        self._inputs_only = inputs_only
        self._thread = QThread()
        self._worker = _Worker(
            snapshot,
            workloads,
            run_dir,
            label or snapshot.run.layout_name,
            inputs_only,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.logged.connect(self.logged)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._thread.start()
        self.busyChanged.emit(True)

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.runner.cancel()

    # ---------------------------------------------------------------- private
    def _cleanup(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None
        self.busyChanged.emit(False)

    def _on_finished(self, payload: object) -> None:
        inputs_only = self._inputs_only
        self._cleanup()
        if inputs_only:
            self.inputsExported.emit(payload)
        elif isinstance(payload, RunResult):
            self.runFinished.emit(payload)

    def _on_failed(self, message: str, trace: str) -> None:
        self._cleanup()
        self.failed.emit(message, trace)

    def _on_cancelled(self) -> None:
        self._cleanup()
        self.cancelled.emit()


__all__ = ["RunController"]
