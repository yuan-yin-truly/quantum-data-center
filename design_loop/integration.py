"""From genes to physical descriptions: repair rules, ``quantum_arch`` architecture dicts, package roles.

Integration modes (an INPUT-driven definition, never a claim of quantum speedup):

``gpu_only``  baseline. All four GPU dies and four HBM stacks stay classical; no quantum subsystem.
``add``       keep every GPU/HBM. ``n_quantum_systems`` quantum computers are added to the facility and a
              share ``offload_fraction`` of each GPU's work is ASSUMED movable to them (an input).
``replace``   ``k >= 1`` of the four GPU dies are re-declared as quantum-support chiplets (hosts of the decoder
              bank and controller power on the interposer). Their work is redistributed to the remaining GPUs
              (the LOCAL hill variant's "redistributed" rule), minus the assumed offloaded share.

HBM stacks are never re-declared: each GPU has a mandatory primary link to its HBM stack, and the judge's link
topology is not changed (documented limitation).
"""

from __future__ import annotations

import copy
from typing import Any

from .genes import Space

SUPPORT_GENES = ("support_G0", "support_G1", "support_G2", "support_G3")
GPU_DIES = ("G0", "G1", "G2", "G3")
MODES = ("gpu_only", "add", "replace")

QUANTUM_GENES = ("modality", "scheme", "n_qubits", "cryostat_scale", "profile", "code", "decoder", "decoder_device",
                 "decoder_location", "task", "host_device", "host_count", "optimizer_device", "optimizer_count",
                 "optimizer_location", "n_quantum_systems")

try:                                                     # the catalogs are plain JSON shipped with quantum_arch
    from quantum_arch import catalog as _cat
except Exception:                                        # pragma: no cover
    _cat = None


def catalogs_available() -> bool:
    return _cat is not None


def _modalities() -> dict:
    return _cat.load("modalities") if _cat else {}


def _fridges() -> dict:
    return _cat.load("fridges") if _cat else {}


def _codes() -> dict:
    return _cat.load("codes") if _cat else {}


def _decoders() -> dict:
    return _cat.load("decoders") if _cat else {}


def support_dies(genes: dict) -> list[str]:
    return [d for d, k in zip(GPU_DIES, SUPPORT_GENES) if genes.get(k)]


def stage_names(modality: str, scheme: str, profile: str) -> list[str]:
    """Cryostat stage names that the scheme uses (empty for ambient systems)."""
    mods = _modalities()
    if modality not in mods:
        return []
    sch = mods[modality]["schemes"].get(scheme)
    if sch is None:
        return []
    base = sch
    if "extends" in sch:
        base = {**mods[modality]["schemes"][sch["extends"]], **{k: v for k, v in sch.items() if k != "extends"}}
    key = (base.get("profile_cryostat") or {}).get(profile) or base.get("cryostat")
    fr = _fridges().get(key, {})
    stages = fr.get("stages", [])
    return [s["name"] for s in stages] if isinstance(stages, list) else list(stages)


def allowed_codes(modality: str) -> list[str]:
    mods, codes = _modalities(), _codes()
    mod = mods[modality]
    default = mod.get("default_code", "surface")
    if default in ("cat_repetition", "fusion_network"):
        return [default]
    out = ["surface"]
    if mod.get("nonlocal_connectivity") and "bivariate_bicycle" in codes:
        out.append("bivariate_bicycle")
    return out


def default_decoder(code: str) -> str:
    dec = _decoders()
    try:
        from quantum_arch import qec
        d = qec.Code(code).default_decoder
        if d in dec:
            return d
    except Exception:                                    # pragma: no cover
        pass
    for k, v in dec.items():
        if not k.startswith("_") and code in v["codes"]:
            return k
    return "union_find"


def repair(g: dict[str, Any], defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve incompatible gene combinations so that equal designs share one canonical form.

    ``defaults`` are the space defaults: genes that have no effect in a mode are reset to them, so designs that
    differ only in irrelevant genes collapse onto one id (and are cached once).
    """
    g = dict(g)
    defaults = defaults or {}
    mode = g.get("mode", "gpu_only")
    if mode not in MODES:
        mode = g["mode"] = "gpu_only"
    if mode == "gpu_only":
        g["offload_fraction"] = 0.0
        for k in SUPPORT_GENES:
            g[k] = False
        for k in QUANTUM_GENES + ("devices_per_support_die", "support_extra_w"):
            if k in defaults:
                g[k] = defaults[k]
        return g
    if not _cat:                                         # pragma: no cover
        return g
    mods = _modalities()
    mod = mods[g["modality"]]
    # scheme
    if g.get("scheme") not in mod["schemes"]:
        g["scheme"] = mod["default_scheme"]
    profile = g.get("profile", "mid2030s")
    stages = stage_names(g["modality"], g["scheme"], profile)
    if g.get("scheme") in mod["schemes"] and not stages:
        g["cryostat_scale"] = 1.0
    # code and decoder
    ok = allowed_codes(g["modality"])
    if g.get("code") not in ok:
        g["code"] = mod.get("default_code", "surface")
    if g.get("decoder") not in _decoders() or g["code"] not in _decoders()[g["decoder"]]["codes"]:
        g["decoder"] = default_decoder(g["code"])
    # integration
    if mode == "add":
        for k in SUPPORT_GENES:
            g[k] = False
    else:
        n_sup = sum(bool(g.get(k)) for k in SUPPORT_GENES)
        if n_sup == 0:
            g["support_G3"] = True
        elif n_sup == 4:
            g["support_G0"] = False
    k_sup = sum(bool(g.get(k)) for k in SUPPORT_GENES)
    # decoder placement
    loc, dev = g.get("decoder_location", "RT"), g.get("decoder_device", "auto:fpga")
    if loc == "4K" and "4K" not in stages:
        loc = "RT"
    if loc == "package" and k_sup == 0:
        loc = "RT"
    if loc == "4K":
        dev = "auto:asic_4k"
    else:
        if dev == "auto:asic_4k":
            dev = "auto:asic_rt"
        if loc == "package" and dev not in ("auto:asic_rt", "auto:fpga"):
            dev = "auto:asic_rt"
    g["decoder_location"], g["decoder_device"] = loc, dev
    if loc != "package" and "devices_per_support_die" in defaults:
        g["devices_per_support_die"] = defaults["devices_per_support_die"]
    if k_sup == 0 and "support_extra_w" in defaults:
        g["support_extra_w"] = defaults["support_extra_w"]
    # optimiser at 4 K only as a cryo ASIC
    oloc, odev = g.get("optimizer_location", "RT"), g.get("optimizer_device", "auto:cpu")
    if oloc == "4K":
        if "4K" in stages:
            odev = "auto:asic_4k"
        else:
            oloc = "RT"
    elif odev == "auto:asic_4k":
        odev = "auto:asic_rt"
    g["optimizer_location"], g["optimizer_device"] = oloc, odev
    return g


# ------------------------------------------------------------------------------------------------------
# architecture
# ------------------------------------------------------------------------------------------------------
def architecture_dict(g: dict[str, Any], name: str = "design") -> dict[str, Any]:
    """The ``quantum_arch`` architecture for a quantum design. ``package`` decoders are costed as RT decoders
    (their power is moved onto the package by the package evaluator, not duplicated)."""
    loc = g["decoder_location"]
    return {
        "name": name,
        "modality": g["modality"],
        "profile": g["profile"],
        "scheme": g["scheme"],
        "n_qubits": int(g["n_qubits"]),
        "cryostat": {"capacity_scale": float(g["cryostat_scale"])},
        "qec": {"code": g["code"], "decoder": g["decoder"], "decoder_device": g["decoder_device"],
                "decoder_location": "RT" if loc == "package" else loc, "target_logical_error": 1e-12},
        "classical": [
            {"role": "host", "device": g["host_device"], "count": int(g["host_count"]), "utilisation": 0.3, "location": "RT"},
            {"role": "optimizer", "device": g["optimizer_device"], "count": int(g["optimizer_count"]),
             "utilisation": 0.3, "location": g["optimizer_location"]},
        ],
        "facility": {"pue": float(g["pue"]), "network_support_w": 0.0},
        "plates": False,
    }


def quantum_key(g: dict[str, Any]) -> str:
    """Genes that determine the quantum_arch evaluation (the cache key of the quantum evaluator)."""
    import json
    sub = {k: g[k] for k in ("modality", "scheme", "n_qubits", "cryostat_scale", "profile", "code", "decoder",
                              "decoder_device", "decoder_location", "host_device", "host_count", "optimizer_device",
                              "optimizer_count", "optimizer_location", "pue") if k in g}
    return json.dumps(sub, sort_keys=True)


# ------------------------------------------------------------------------------------------------------
# default space
# ------------------------------------------------------------------------------------------------------
def default_space_dict() -> dict[str, Any]:
    mods = [k for k in (_modalities() or {}) if not k.startswith("_")] or ["superconducting"]
    schemes: list[str] = []
    for m in mods:
        for s in (_modalities().get(m, {}).get("schemes", {}) if _cat else {}):
            if s not in schemes:
                schemes.append(s)
    tasks = [k for k in (_cat.load("workloads") if _cat else {}) if not k.startswith("_")] or ["vqe_50q"]
    decs = [k for k in (_decoders() or {}) if not k.startswith("_")] or ["union_find"]
    codes = [k for k in (_codes() or {}) if not k.startswith("_")] or ["surface"]
    G = lambda t, d, group, doc, **kw: {"type": t, "default": d, "group": group, "doc": doc, **kw}
    return {
        "name": "datacentre_2035_default",
        "description": "Quantum modality, QEC, decoders, cryostat, integration mode, support chiplets and layout "
                       "for the Beat-the-Hotspot package; hardware at the mid-2030s scenario profile.",
        "genes": {
            "mode": G("cat", "add", "integration", "gpu_only | add | replace", choices=list(MODES)),
            "offload_fraction": G("float", 0.1, "integration",
                                  "INPUT ASSUMPTION: share of each remaining GPU's work movable to the quantum side",
                                  lo=0.0, hi=0.6, step=0.05),
            "n_quantum_systems": G("logint", 2, "integration", "quantum computers in the facility", lo=1, hi=32),
            "support_G0": G("bool", False, "integration", "G0 re-declared as quantum-support chiplet (replace)"),
            "support_G1": G("bool", False, "integration", "G1 re-declared as quantum-support chiplet (replace)"),
            "support_G2": G("bool", False, "integration", "G2 re-declared as quantum-support chiplet (replace)"),
            "support_G3": G("bool", False, "integration", "G3 re-declared as quantum-support chiplet (replace)"),
            "devices_per_support_die": G("int", 4, "integration",
                                        "ASSUMPTION: decoder devices one support die can host", lo=1, hi=16),
            "support_extra_w": G("float", 3.0, "integration", "controller/IO overhead of a support die (W, assumption)",
                                 lo=0.0, hi=10.0, step=1.0),
            "modality": G("cat", "superconducting", "quantum", "qubit modality", choices=mods),
            "scheme": G("cat", "cryo_cmos_4k", "quantum", "control / wiring scheme (repaired to the modality)", choices=schemes),
            "n_qubits": G("logint", 100000, "quantum", "physical qubits", lo=1000, hi=2000000),
            "cryostat_scale": G("logfloat", 20.0, "quantum", "cryostat capacity scale (hypothetical large cryoplatforms)",
                                lo=1.0, hi=300.0),
            "profile": G("cat", "mid2030s", "quantum", "hardware profile / scenario",
                         choices=["mid2030s_low", "mid2030s", "mid2030s_high"]),
            "code": G("cat", "surface", "quantum", "QEC code (repaired to the modality)", choices=codes),
            "decoder": G("cat", "union_find", "quantum", "decoder algorithm (repaired to the code)", choices=decs),
            "decoder_device": G("cat", "auto:asic_rt", "classical", "decoder hardware",
                                choices=["auto:fpga", "auto:asic_rt", "auto:asic_4k", "auto:gpu"]),
            "decoder_location": G("cat", "RT", "classical", "RT = room temperature, 4K = cryo stage, "
                                  "package = on support chiplets of the interposer", choices=["RT", "4K", "package"]),
            "task": G("cat", "vqe_50q", "quantum", "quantum workload the offloaded work is mapped to", choices=tasks),
            "host_device": G("cat", "auto:cpu", "classical", "classical host device", choices=["auto:cpu", "auto:gpu"]),
            "host_count": G("int", 1, "classical", "host count", lo=1, hi=8),
            "optimizer_device": G("cat", "auto:gpu", "classical", "optimiser (variational loop) device",
                                  choices=["auto:cpu", "auto:gpu", "auto:fpga", "auto:asic_rt", "auto:asic_4k"]),
            "optimizer_count": G("int", 4, "classical", "optimiser count", lo=1, hi=16),
            "optimizer_location": G("cat", "RT", "classical", "RT or 4K (cryo ASIC)", choices=["RT", "4K"]),
            "pue": G("float", 1.15, "facility", "PUE for the facility boundary", lo=1.05, hi=1.5, step=0.05),
        },
        "fixed": {"pue": 1.15},
        "layout": {"enabled": True, "grid_mm": 0.05, "step_mm": 1.5, "seeds": ["baseline_example"]},
    }


def make_space(raw: dict | None = None) -> Space:
    """Build a Space (default if ``raw`` is None) with this module's repair rules attached."""
    sp = Space.from_dict(raw or default_space_dict())
    defaults = sp.defaults()
    sp.repair = lambda g: repair(g, defaults)
    return sp
