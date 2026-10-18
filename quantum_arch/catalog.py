"""JSON catalogs shipped in ``quantum_arch/data`` and a small deep-merge helper."""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=None)
def _load(name: str) -> dict[str, Any]:
    path = DATA_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load(name: str) -> dict[str, Any]:
    """A private copy of the catalog ``name`` (safe to mutate)."""
    return copy.deepcopy(_load(name))


def entry(catalog: str, key: str) -> dict[str, Any]:
    data = load(catalog)
    if key not in data:
        known = ", ".join(k for k in data if not k.startswith("_"))
        raise KeyError(f"{key!r} is not in the {catalog} catalog; known: {known}")
    return data[key]


def keys(catalog: str) -> list[str]:
    return [k for k in _load(catalog) if not k.startswith("_")]


def deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively overlay ``override`` onto a copy of ``base``."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out
