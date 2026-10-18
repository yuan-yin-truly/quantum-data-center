"""Where things live: repository root, hill directories, shared data."""

from __future__ import annotations

import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent                       # chiplet-thermal-gui/
WORKSPACE = REPO_ROOT.parent                     # SundAI_145/
DATA_DIR = PKG_DIR / "data"


def hill_candidates() -> list[Path]:
    """Hill directories in order of preference (the LOCAL quantum variant first)."""
    out = []
    env = os.environ.get("DESIGN_LOOP_HILL_DIR")
    if env:
        out.append(Path(env))
    hills = WORKSPACE / ".autolab" / "hills"
    # A copy under .autolab/ carries vendor/HotSpot, so it wins when present; the copy tracked in this
    # repository (hill_variant/, without vendor/) lets a fresh clone run everything except real HotSpot.
    out += [hills / "beat-the-hotspot-quantum", REPO_ROOT / "hill_variant" / "beat-the-hotspot-quantum",
            hills / "beat-the-hotspot"]
    return out


def find_hill() -> Path | None:
    for c in hill_candidates():
        if (c / "challenge_spec.json").is_file() and (c / "geometry.py").is_file():
            return c
    return None
