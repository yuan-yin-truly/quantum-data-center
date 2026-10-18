"""The evaluator protocol and its result record."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..genes import Design

#: statuses an evaluator can report
OK, UNAVAILABLE, ERROR, SKIPPED = "ok", "unavailable", "error", "skipped"
#: where the numbers come from (stated next to every reported number)
REAL, SURROGATE, STUB, MODEL = "real", "surrogate", "stub", "model"


@dataclass
class EvalResult:
    """What every evaluator returns: metrics, per-workload breakdown, and a cost/time record."""

    evaluator: str
    status: str = OK
    source: str = MODEL                 # real | surrogate | stub | model
    metrics: dict[str, Any] = field(default_factory=dict)
    per_workload: dict[str, dict[str, Any]] = field(default_factory=dict)   # {group: {workload: {...}}} or {workload: {...}}
    violations: list[str] = field(default_factory=list)                     # hard-constraint violations found here
    notes: list[str] = field(default_factory=list)
    cost: dict[str, Any] = field(default_factory=dict)                      # seconds, hotspot_runs, cache_hit
    key: str = ""                       # cache key of the sub-problem this result answers
    boundary: str = ""                  # power boundary the energy/power numbers use

    @property
    def ok(self) -> bool:
        return self.status == OK

    def to_dict(self) -> dict:
        return {"evaluator": self.evaluator, "status": self.status, "source": self.source, "metrics": self.metrics,
                "per_workload": self.per_workload, "violations": self.violations, "notes": self.notes,
                "cost": self.cost, "key": self.key, "boundary": self.boundary}

    @classmethod
    def from_dict(cls, d: dict) -> "EvalResult":
        return cls(**{k: d.get(k, v) for k, v in
                      (("evaluator", ""), ("status", OK), ("source", MODEL), ("metrics", {}), ("per_workload", {}),
                       ("violations", []), ("notes", []), ("cost", {}), ("key", ""), ("boundary", ""))})


@runtime_checkable
class Evaluator(Protocol):
    """One evaluator = one view of a design. ``context`` carries earlier results by evaluator name."""

    name: str

    def available(self) -> tuple[bool, str]: ...

    def cache_key(self, design: Design, context: dict[str, EvalResult]) -> str: ...

    def evaluate(self, design: Design, context: dict[str, EvalResult]) -> EvalResult: ...


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.seconds = time.perf_counter() - self.t0


def unavailable(name: str, reason: str, source: str = MODEL) -> EvalResult:
    return EvalResult(evaluator=name, status=UNAVAILABLE, source=source, notes=[reason])


def errored(name: str, exc: BaseException, source: str = MODEL) -> EvalResult:
    return EvalResult(evaluator=name, status=ERROR, source=source, notes=[f"{type(exc).__name__}: {exc}"])
