"""Fluid (aggregate) demand of the mass LLM traffic: the first level of the TWO-LEVEL demand model.

Scale decision: 4 billion + 400 million + 50 million users cannot be simulated one by one. The mass traffic of cases A
(prompters), B (agent developers) and C (knowledge workers) is therefore a set of AGGREGATE token-rate classes per user
region (rates per second, diurnal and time-zone shaped), which consume prefill/decode capacity and context memory of the sites.
Everything a user injects, and every "interesting" job (agent job batches, research jobs, quantum-eligible jobs, hybrid
pipelines), is a DISCRETE task (``tasks.py``) that competes with the fluid traffic for the same racks, power and memory.
All parameters are ASSUMPTIONS in ``data/assumptions.json``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from . import qfeas
from .config import assumptions

CASES = {"A": ("A",), "B": ("B",), "C": ("C",), "AB": ("A", "B"), "AC": ("A", "C"), "BC": ("B", "C"), "mix": ("A", "B", "C"), "ABC": ("A", "B", "C")}


def diurnal_factor(shape: dict, local_hour: float) -> float:
    """Diurnal multiplier with 24 h mean 1 (``cosine`` or ``bell`` + floor)."""
    if shape["type"] == "cosine":
        return 1.0 + shape["amplitude"] * math.cos(2 * math.pi * (local_hour - shape["peak_hour"]) / 24.0)
    # bell: floor + (1 - floor') gaussian bump, normalised numerically to mean 1
    c, sd, fl = shape["centre_hour"], shape["sd_hours"], shape["floor"]

    def raw(h: float) -> float:
        d = min(abs(h - c), 24 - abs(h - c))
        return fl + (1 - fl) * math.exp(-0.5 * (d / sd) ** 2)
    norm = sum(raw(i + 0.5) for i in range(24)) / 24.0
    return raw(local_hour) / norm


@dataclass
class Chunk:
    cls: str
    region: str
    req_rate: float          # requests (steps) per second
    prefill_new_tok_s: float
    cached_tok_s: float      # tokens/s of cached context (recomputed on a cache miss)
    decode_tok_s: float
    ctx_need_tb: float       # context memory needed for the live sessions
    allowed_rtt_s: float
    weight: float
    users_active_share: float = 0.0

    def prefill_tok_s(self, hit: float) -> float:
        return self.prefill_new_tok_s + (1.0 - hit) * self.cached_tok_s


class FluidDemand:
    def __init__(self, case: str = "mix", scale: float = 1.0, engine_cfg: dict | None = None, start_utc_hour: float = 0.0,
                 regions: dict | None = None, overrides: dict | None = None):
        a = assumptions()
        self.cfg = a["demand"]
        if overrides:
            for k, v in overrides.items():
                if k in self.cfg and isinstance(v, dict):
                    self.cfg[k].update(v)
        eng = engine_cfg or a["engine"]
        self.case = case
        self.classes = CASES.get(case) or tuple(case)
        self.scale = float(scale)
        self.start_utc_hour = float(start_utc_hour)
        self.regions = regions or {k: v for k, v in a["regions"].items() if not k.startswith("_")}
        g = qfeas.gpu_module()
        mc = float(eng["model_cost_x"])
        self.P = g["prefill_tok_s_70b"] / mc          # prefill tokens/s of one GPU module for the served model
        self.D = g["decode_tok_s_70b"] / mc
        self.replica = int(self.cfg.get("replica_modules", 8))
        self.surge = 1.0
        self.surge_by_class: dict[str, float] = {}

    def allowed_rtt(self, cls: str) -> float:
        c = self.cfg[cls]
        # time to first token = RTT + prefill compute of one request on a replica + queueing margin
        pf = c["prefill_new_tokens"] / (self.P * self.replica)
        return max(0.0, c["ttft_slo_s"] - pf - self.cfg["queue_margin_s"])

    def local_hour(self, t_s: float, region: str) -> float:
        return (self.start_utc_hour + t_s / 3600.0 + self.regions[region]["utc_offset"]) % 24.0

    def chunks(self, t_s: float) -> list[Chunk]:
        out = []
        for cn in self.classes:
            c = self.cfg[cn]
            shape = self.cfg["diurnal"][c["diurnal"]]
            mult = self.scale * self.surge * self.surge_by_class.get(cn, 1.0)
            for r, share in c["region_share"].items():
                if share <= 0:
                    continue
                dfac = diurnal_factor(shape, self.local_hour(t_s, r))
                req = c["users"] * share * c["req_per_user_day"] / 86400.0 * dfac * mult
                out.append(Chunk(cls=cn, region=r, req_rate=req, prefill_new_tok_s=req * c["prefill_new_tokens"],
                                 cached_tok_s=req * c["cached_ctx_tokens"], decode_tok_s=req * c["decode_tokens"],
                                 ctx_need_tb=c["users"] * share * c["active_frac"] * dfac * mult * c["ctx_gb"] / 1000.0,
                                 allowed_rtt_s=self.allowed_rtt(cn), weight=float(c.get("weight", 1.0))))
        return out

    def module_equivalents(self, t_s: float, hit: float = 1.0) -> dict[str, float]:
        """GPU-module-equivalents (at 100 % utilisation) needed per class at time t, for calibration and documentation."""
        out: dict[str, float] = {}
        for ch in self.chunks(t_s):
            out[ch.cls] = out.get(ch.cls, 0.0) + ch.prefill_tok_s(hit) / self.P + ch.decode_tok_s / self.D
        return out

    def users(self) -> dict[str, float]:
        return {cn: float(self.cfg[cn]["users"]) for cn in self.classes}

    def describe(self) -> dict[str, Any]:
        return {"case": self.case, "classes": list(self.classes), "prefill_tok_s_per_module": self.P, "decode_tok_s_per_module": self.D,
                "allowed_rtt_ms": {c: self.allowed_rtt(c) * 1000 for c in self.classes}}
