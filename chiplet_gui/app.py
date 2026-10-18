"""Application entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chiplet_gui",
        description=(
            "Placement, routing and thermal workbench for the SUNDAI continuous "
            "chiplet-placement challenge."
        ),
    )
    parser.add_argument("project", nargs="?", help="design or layout JSON to open at start")
    parser.add_argument(
        "--challenge-dir",
        help="directory holding challenge_spec.json and the judge modules (auto-detected)",
    )
    parser.add_argument("--hotspot", help="path to the compiled HotSpot executable")
    arguments = parser.parse_args(argv)

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        print(
            "PySide6 is not installed, so the GUI cannot start.\n"
            "Install it with:  python -m pip install PySide6",
            file=sys.stderr,
        )
        return 2

    from .core.simcore import SimulatorNotFound, load_modules
    from .gui.style import apply_theme

    application = QApplication.instance() or QApplication(sys.argv[:1])
    application.setApplicationName("Chiplet Thermal Studio")
    application.setOrganizationName("chiplet_gui")
    apply_theme(application)

    try:
        load_modules(arguments.challenge_dir)
    except SimulatorNotFound as exc:
        QMessageBox.critical(None, "Challenge package not found", str(exc))
        print(exc, file=sys.stderr)
        return 2

    from .core.project import Project
    from .gui.main_window import MainWindow

    project: Project | None = None
    failure = ""
    if arguments.project:
        try:
            project = Project.load(arguments.project)
        except Exception as exc:
            failure = f"Could not open {arguments.project}: {exc}"

    if project is None:
        project = Project.default(arguments.challenge_dir)
    if arguments.hotspot:
        project.run.hotspot_path = str(Path(arguments.hotspot))

    window = MainWindow(project)
    window.show()
    if failure:
        window.log.log(failure)
    return application.exec()


__all__ = ["main"]
