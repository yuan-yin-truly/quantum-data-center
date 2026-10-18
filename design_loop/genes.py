"""Design space: typed, bounded genes; canonical, hashable designs.

A :class:`Space` is declarative (JSON; YAML too if PyYAML is installed). A :class:`Design` is the genes after
canonicalisation (clamped, rounded, repaired for incompatible combinations) plus a package layout, so two
descriptions of the same design always have the same ``id`` and are evaluated once.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

DIES = ("G0", "G1", "G2", "G3", "H0", "H1", "H2", "H3")


class SpaceError(ValueError):
    pass


def _sig(x: float, digits: int = 2) -> float:
    """Round to ``digits`` significant digits (keeps log-scaled genes on a coarse, cache-friendly lattice)."""
    if x == 0 or not math.isfinite(x):
        return x
    return float(f"{x:.{digits - 1}e}")


@dataclass
class Gene:
    name: str
    type: str                       # cat | int | float | logint | logfloat | bool
    default: Any
    choices: list | None = None
    lo: float | None = None
    hi: float | None = None
    step: float | None = None       # float grid / int stride
    group: str = "misc"             # quantum | integration | classical | facility
    doc: str = ""

    def __post_init__(self):
        if self.type not in ("cat", "int", "float", "logint", "logfloat", "bool"):
            raise SpaceError(f"gene {self.name}: unknown type {self.type!r}")
        if self.type == "cat" and not self.choices:
            raise SpaceError(f"gene {self.name}: categorical gene needs choices")
        if self.type in ("int", "float", "logint", "logfloat"):
            if self.lo is None or self.hi is None or self.lo > self.hi:
                raise SpaceError(f"gene {self.name}: needs lo <= hi")
            if self.type in ("logint", "logfloat") and self.lo <= 0:
                raise SpaceError(f"gene {self.name}: log genes need lo > 0")
        if self.type == "bool":
            self.choices = [False, True]
        self.default = self.clamp(self.default)

    # ---- canonical form -----------------------------------------------------------------------------
    def clamp(self, v: Any) -> Any:
        t = self.type
        if t == "cat":
            if v not in self.choices:
                raise SpaceError(f"gene {self.name}: {v!r} not in {self.choices}")
            return v
        if t == "bool":
            return bool(v)
        v = float(v)
        v = min(max(v, self.lo), self.hi)
        if t == "int":
            return int(round(v))
        if t == "logint":
            return int(min(max(_sig(round(v)), self.lo), self.hi))
        if t == "logfloat":
            return min(max(_sig(v), self.lo), self.hi)
        if self.step:
            v = round(round(v / self.step) * self.step, 10)
        return min(max(v, self.lo), self.hi)

    # ---- sampling / moves ---------------------------------------------------------------------------
    def sample(self, rng: random.Random) -> Any:
        t = self.type
        if t in ("cat", "bool"):
            return rng.choice(self.choices)
        if t in ("logint", "logfloat"):
            return self.clamp(math.exp(rng.uniform(math.log(self.lo), math.log(self.hi))))
        return self.clamp(rng.uniform(self.lo, self.hi))

    def neighbours(self, v: Any) -> list:
        """Adjacent values: other categories, or one step up/down."""
        t = self.type
        if t in ("cat", "bool"):
            return [c for c in self.choices if c != v]
        out = []
        if t == "int":
            stride = int(self.step or 1)
            cands = [v - stride, v + stride]
        elif t in ("logint", "logfloat"):
            cands = [v / 1.5, v * 1.5, v / 2.5, v * 2.5]
        else:
            step = self.step or (self.hi - self.lo) / 10.0
            cands = [v - step, v + step]
        for c in cands:
            c = self.clamp(c)
            if c != v and c not in out:
                out.append(c)
        return out

    def mutate(self, v: Any, rng: random.Random) -> Any:
        t = self.type
        if t in ("cat", "bool"):
            others = [c for c in self.choices if c != v]
            return rng.choice(others) if others else v
        if t in ("logint", "logfloat"):
            return self.clamp(v * math.exp(rng.gauss(0.0, 0.7)))
        span = self.hi - self.lo
        w = self.clamp(v + rng.gauss(0.0, 0.2 * span if span else 1.0))
        if w == v:
            ns = self.neighbours(v)
            return rng.choice(ns) if ns else v
        return w

    def to_dict(self) -> dict:
        d = {"type": self.type, "default": self.default, "group": self.group}
        for k in ("choices", "lo", "hi", "step", "doc"):
            val = getattr(self, k)
            if val not in (None, "") and not (k == "choices" and self.type == "bool"):
                d[k] = val
        return d


def _canon_layout(layout: dict | None, grid: float) -> dict[str, list[float]]:
    if not layout:
        return {}
    out = {}
    for d in DIES:
        x, y = layout[d]
        out[d] = [round(round(float(x) / grid) * grid, 6), round(round(float(y) / grid) * grid, 6)]
    return out


class Design:
    """An immutable canonical design. Equality and hashing use :attr:`id`."""

    __slots__ = ("genes", "layout", "_id")

    def __init__(self, genes: dict[str, Any], layout: dict[str, list[float]] | None):
        object.__setattr__(self, "genes", dict(sorted(genes.items())))
        object.__setattr__(self, "layout", {d: list(layout[d]) for d in DIES} if layout else {})
        object.__setattr__(self, "_id", None)

    def __setattr__(self, k, v):                                   # pragma: no cover
        raise AttributeError("Design is immutable")

    def canonical(self) -> dict:
        return {"genes": self.genes, "layout": self.layout}

    @property
    def id(self) -> str:
        if self._id is None:
            blob = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"), default=str)
            object.__setattr__(self, "_id", hashlib.sha1(blob.encode()).hexdigest()[:12])
        return self._id

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, Design) and other.id == self.id

    def __getitem__(self, k):
        return self.genes[k]

    def get(self, k, default=None):
        return self.genes.get(k, default)

    def to_dict(self) -> dict:
        return {"id": self.id, **self.canonical()}

    @classmethod
    def from_dict(cls, d: dict) -> "Design":
        return cls(d["genes"], d.get("layout") or None)

    def replace(self, **genes) -> "Design":
        g = dict(self.genes)
        g.update(genes)
        return Design(g, self.layout)

    def with_layout(self, layout: dict) -> "Design":
        return Design(self.genes, layout)

    def diff(self, other: "Design") -> list[str]:
        """Names of genes (and ``layout``) that differ."""
        out = [k for k in self.genes if self.genes[k] != other.genes.get(k)]
        if self.layout != other.layout:
            out.append("layout")
        return out

    def __repr__(self):
        return f"Design({self.id} mode={self.genes.get('mode')} mod={self.genes.get('modality')})"


@dataclass
class Space:
    name: str
    genes: dict[str, Gene]
    fixed: dict[str, Any] = field(default_factory=dict)
    layout_cfg: dict[str, Any] = field(default_factory=lambda: {"enabled": True, "grid_mm": 0.05, "step_mm": 1.5})
    description: str = ""
    #: hook(genes: dict) -> dict ; resolves incompatible combinations. Set by integration.make_space().
    repair: Callable[[dict], dict] | None = None

    # ---- construction -------------------------------------------------------------------------------
    @classmethod
    def from_dict(cls, raw: dict) -> "Space":
        genes = {}
        for name, g in raw.get("genes", {}).items():
            g = dict(g)
            genes[name] = Gene(name=name, type=g.pop("type"), default=g.pop("default"), **{
                k: g[k] for k in ("choices", "lo", "hi", "step", "group", "doc") if k in g})
        if not genes:
            raise SpaceError("a space needs at least one gene")
        fixed = dict(raw.get("fixed", {}))
        for k in fixed:
            if k not in genes:
                raise SpaceError(f"fixed gene {k!r} is not defined")
            fixed[k] = genes[k].clamp(fixed[k])
        layout_cfg = {"enabled": True, "grid_mm": 0.05, "step_mm": 1.5, **raw.get("layout", {})}
        return cls(raw.get("name", "space"), genes, fixed, layout_cfg, raw.get("description", ""))

    @classmethod
    def load(cls, path: str | Path) -> "Space":
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if p.suffix in (".yaml", ".yml"):
            try:
                import yaml                                          # type: ignore
            except ImportError as exc:
                raise SpaceError("YAML spaces need PyYAML (pip install pyyaml); JSON works without it") from exc
            raw = yaml.safe_load(text)
        else:
            raw = json.loads(text)
        return cls.from_dict(raw)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "genes": {k: g.to_dict() for k, g in self.genes.items()},
                "fixed": self.fixed, "layout": self.layout_cfg}

    # ---- canonicalisation ---------------------------------------------------------------------------
    @property
    def mutable(self) -> list[str]:
        return [k for k in self.genes if k not in self.fixed]

    def defaults(self) -> dict[str, Any]:
        d = {k: g.default for k, g in self.genes.items()}
        d.update(self.fixed)
        return d

    def canonicalize(self, raw_genes: dict[str, Any] | None, layout: dict | None = None) -> Design:
        """Clamp, round, apply fixed values and repair; unknown genes are an error, missing take defaults."""
        raw_genes = dict(raw_genes or {})
        for k in raw_genes:
            if k not in self.genes:
                raise SpaceError(f"unknown gene {k!r}")
        g = self.defaults()
        for k, v in raw_genes.items():
            if k in self.fixed:
                continue
            g[k] = self.genes[k].clamp(v)
        if self.repair:
            g = self.repair(dict(g))
            g = {k: (self.genes[k].clamp(v) if k in self.genes else v) for k, v in g.items()}
            g.update({k: v for k, v in self.fixed.items()})
        grid = float(self.layout_cfg.get("grid_mm", 0.05))
        return Design(g, _canon_layout(layout, grid) if self.layout_cfg.get("enabled", True) else None)

    def recanonicalize(self, d: Design) -> Design:
        return self.canonicalize(d.genes, d.layout or None)

    # ---- sampling and moves -------------------------------------------------------------------------
    def random_genes(self, rng: random.Random) -> dict[str, Any]:
        return {k: self.genes[k].sample(rng) for k in self.mutable}

    def mutate(self, d: Design, rng: random.Random, n_genes: int | None = None) -> tuple[Design, list[str]]:
        """Mutate ``n_genes`` (default 1-3) genes; returns the canonical child and the genes that really changed."""
        names = self.mutable
        n = n_genes or rng.choice([1, 1, 2, 3])
        for _ in range(8):
            pick = rng.sample(names, min(n, len(names)))
            g = dict(d.genes)
            for k in pick:
                g[k] = self.genes[k].mutate(g[k], rng)
            child = self.canonicalize(g, d.layout or None)
            changed = child.diff(d)
            if changed:
                return child, changed
        return d, []

    def crossover(self, a: Design, b: Design, rng: random.Random) -> tuple[Design, list[str]]:
        """Uniform crossover per gene group; layout is inherited whole from one parent."""
        by_group: dict[str, list[str]] = {}
        for k in self.mutable:
            by_group.setdefault(self.genes[k].group, []).append(k)
        g = dict(a.genes)
        taken = []
        for grp, names in sorted(by_group.items()):
            if rng.random() < 0.5:
                for k in names:
                    g[k] = b.genes[k]
                taken.append(grp)
        layout = b.layout if rng.random() < 0.5 else a.layout
        child = self.canonicalize(g, layout or None)
        return child, [f"from_b:{t}" for t in taken] + (["layout_from_b"] if layout is b.layout else [])

    def neighbours(self, d: Design, limit_per_gene: int = 6) -> list[tuple[Design, str]]:
        """Single-gene variants of ``d`` (ablations / neighbours), deterministic order."""
        out: list[tuple[Design, str]] = []
        seen = {d.id}
        for k in self.mutable:
            for v in self.genes[k].neighbours(d.genes[k])[:limit_per_gene]:
                g = dict(d.genes)
                g[k] = v
                c = self.canonicalize(g, d.layout or None)
                if c.id not in seen:
                    seen.add(c.id)
                    out.append((c, k))
        return out
