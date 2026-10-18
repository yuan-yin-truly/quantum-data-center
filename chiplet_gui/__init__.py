"""Interactive GUI for the SUNDAI continuous chiplet-placement thermal challenge.

Four GPU and four HBM chiplets are placed on a 52 x 42 mm silicon interposer.
The package wraps the challenge's own judge modules (``geometry``,
``interconnect``, ``generate_workloads``, ``run_simulations``) so that every
number the GUI shows comes from the same code the judge runs.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
