"""Stub package evaluators for tests and for machines without the hill directory.

Everything here is labelled ``source = "stub"``: the temperatures are a made-up monotone function of the design's
power-related genes and carry NO physical meaning. Use only to exercise the loop machinery.
"""

from __future__ import annotations

from ..genes import Design
from .. import integration as I
from .base import OK, STUB, EvalResult

WORKLOADS = ("tensor_training", "skewed_compute", "attention_decode", "memory_stream", "mixed_serving")


class StubLegalityEvaluator:
    name = "package_legality"

    def available(self):
        return True, "STUB legality (always legal)"

    def cache_key(self, design: Design, context=None):
        return "stub-legal"

    def evaluate(self, design: Design, context=None) -> EvalResult:
        return EvalResult(self.name, OK, STUB, metrics={"legal": True}, key="stub-legal", notes=["STUB: no layout check"])


class StubThermalEvaluator:
    """``worst_gpu_c`` falls with the offload fraction and rises with hosted support dies; no physics."""

    name = "package_surrogate"

    def __init__(self, name: str = "package_surrogate"):
        self.name = name

    def available(self):
        return True, "STUB thermal"

    def cache_key(self, design: Design, context=None):
        g = design.genes
        return f"stub|{g['offload_fraction']}|{len(I.support_dies(g))}|{g['decoder_location']}|{g['mode']}"

    def evaluate(self, design: Design, context=None) -> EvalResult:
        g = design.genes
        k = len(I.support_dies(g))
        gpu = 104.6 - 12.0 * float(g["offload_fraction"]) + 4.0 * k + (3.0 if g["decoder_location"] == "package" else 0.0)
        hbm = 97.7 - 3.0 * float(g["offload_fraction"]) + 1.0 * k
        per = {w: {"gpu_peak_c": gpu - i, "hbm_peak_c": hbm - i, "support_peak_c": (80.0 + 5 * k) if k else None,
                   "package_w": 350.0, "per_die_peak_c": {}, "source": "stub"} for i, w in enumerate(WORKLOADS)}
        m = {"worst_gpu_c": gpu, "worst_hbm_c": hbm, "support_peak_c": (80.0 + 5 * k) if k else None,
             "score_informational": max((gpu - 25) / 79.59, (hbm - 25) / 72.68), "package_w_mean": 350.0,
             "package_w_max": 350.0, "thermal_source": "stub"}
        return EvalResult(self.name, OK, STUB, metrics=m, per_workload=per, key=self.cache_key(design),
                          notes=["STUB temperatures, no physical meaning"], cost={"seconds": 0.0})
