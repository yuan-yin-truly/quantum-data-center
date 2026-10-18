"""Quantum-classical hardware architecture simulator: compute power, energy and heat.

Submodules for the data-centre-of-2035 work: ``datacenter`` (hybrid CPU+GPU+QPU scheduler model),
``baselines`` (GPU matched-quality baselines), ``annealer`` (annealers as a separate class) and
``calibration`` (model against published power figures).
"""

from .architecture import DEFAULTS, PROFILES, Architecture, Result, evaluate

__all__ = ["Architecture", "Result", "evaluate", "DEFAULTS", "PROFILES"]
