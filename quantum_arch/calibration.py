"""Compare the ``today`` profile with published power figures.

The published numbers (``data/references.json``) are a MIX of ratings, maxima, averages and vendor
claims at different measurement boundaries, not matched benchmarks. A ratio near 1 means the model's
default sits on the same scale as the reference at the stated boundary; it is a sanity check, and for
the entries that were used to SET the defaults (marked ``anchored``) it holds by construction.

Run ``python -m quantum_arch calibrate`` or ``quantum_arch.calibration.run_calibration()``.
"""

from __future__ import annotations

from typing import Any

from . import annealer, catalog, classical
from .architecture import Architecture, evaluate

#: Defaults before the calibration (modalities.json at the start of the audit), for the "before" column.
LEGACY_DEFAULTS_W = {
    "trapped_ion": (3000.0, 40.0),
    "neutral_atom": (5000.0, 1.5),
}


def _quantum_system_w(modality: str, n: int, scheme: str | None = None, profile: str = "today") -> float:
    arch = Architecture.from_dict({"name": "calibration", "modality": modality, "profile": profile, "n_qubits": n,
                                   "scheme": scheme, "plates": False, "workloads": [],
                                   "classical": [{"role": "host", "device": "cpu_epyc_96c", "count": 1, "utilisation": 0.3}]})
    return evaluate(arch).total_power_w


def _row(rid: str, label: str, ref_w: float, model_w: float, boundary: str, anchored: bool, legacy_w: float | None = None,
         comment: str = "", ref_kind: str = "", status: str = "") -> dict[str, Any]:
    return {"id": rid, "label": label, "reference_w": ref_w, "model_w": model_w, "ratio": model_w / ref_w,
            "boundary": boundary, "anchored_by_construction": anchored, "legacy_default_w": legacy_w,
            "legacy_ratio": (legacy_w / ref_w) if legacy_w else None, "comment": comment, "reference_kind": ref_kind,
            "reference_status": status}


def run_calibration() -> list[dict[str, Any]]:
    refs = catalog.load("references")["power"]
    rows: list[dict[str, Any]] = []

    def ref(k):
        return refs[k]

    # --- Helios-class trapped-ion system (98 qubits): model = QPU apparatus + support + 1 host CPU --------------------------
    r = ref("helios_base_unit")
    lw = sum(LEGACY_DEFAULTS_W["trapped_ion"][0:1]) + LEGACY_DEFAULTS_W["trapped_ion"][1] * 98
    rows.append(_row("helios_vs_40kW", "Trapped-ion system, 98 qubits (Helios class), today profile", r["value_w"],
                     _quantum_system_w("trapped_ion", 98), "system (excl. facility); reference is an UPPER BOUND", False, lw,
                     "Reference is 'less than 40 kW'; the model sits below it by design. Old default (3 kW + 40 W/qubit) was 5.8x too low.",
                     r["kind"], r["status"]))
    r = ref("helios_oracle")
    rows.append(_row("helios_vs_60kW", "Same system against the Oracle announcement (about 60 kW without HVAC)", r["value_w"],
                     _quantum_system_w("trapped_ion", 98), "system; reference excludes HVAC", False, lw,
                     "Sources disagree (40 vs 60 kW); the model is calibrated to the vendor's own <40 kW upper bound, so it is expected "
                     "to lie below 60 kW.", r["kind"], r["status"]))
    # --- D-Wave annealer ------------------------------------------------------------------------------------------------------
    r = ref("dwave_advantage2")
    a = annealer.evaluate_annealer({"profile": "today", "host": {"device": "cpu_epyc_96c", "count": 0, "utilisation": 0.0}})
    rows.append(_row("dwave_advantage2", "Annealer, Advantage2 class (QPU system only, no user host)", r["value_w"], a.system_power_w,
                     "system", True, None, "Anchored: the catalog takes the vendor's 12.5 kW; 12.5 kW = 208 V x 60 A, so it may be a rating.",
                     r["kind"], r["status"]))
    # --- Quandela photonic ----------------------------------------------------------------------------------------------------
    r = ref("quandela_ascella")
    rows.append(_row("quandela_ascella", "Photonic, 6 qubits (Ascella class), cryostat inside the rack", r["value_w"],
                     _quantum_system_w("photonic", 6, "ambient") - classical.Device.from_catalog("cpu_epyc_96c").power_w(0.3),
                     "system (excluding the user's host CPU)", True, None,
                     "Anchored by construction. Not a statement about fault-tolerant photonic machines.", r["kind"], r["status"]))
    # --- neutral atoms --------------------------------------------------------------------------------------------------------
    r = ref("quera_aquila_paqit")
    host_w = classical.Device.from_catalog("cpu_epyc_96c").power_w(0.3)
    for n, ref_w in ((256, 6920.0 + 0.308 * 256), (10000, 6920.0 + 0.308 * 10000)):
        legacy = LEGACY_DEFAULTS_W["neutral_atom"][0] + LEGACY_DEFAULTS_W["neutral_atom"][1] * n
        rows.append(_row(f"quera_aquila_{n}", f"Neutral atoms, {n:,} qubits (QuEra Aquila fit)", ref_w,
                         _quantum_system_w("neutral_atom", n) - host_w, "system (excluding host CPU)", True, legacy,
                         "Reference is PaQit's fitted P0 + alpha N (6.92 kW + 0.308 W/qubit), itself fitted to QuEra data.",
                         r["kind"], r["status"]))
    p = ref("pasqal_overview")
    rows.append(_row("pasqal_2_6kw", "Neutral atoms, about 100 qubits against the unconfirmed 'Pasqal 2.6 kW'", p["value_w"],
                     _quantum_system_w("neutral_atom", 100) - host_w, "system", False,
                     LEGACY_DEFAULTS_W["neutral_atom"][0] + 150.0,
                     "Reference NOT confirmed from a primary source; Pasqal's own brochure lists 3.5 kW average laser power alone "
                     "(10 kW installed) and a 380 V 32 A supply, so a 7 kW system is not in conflict with Pasqal's documents.",
                     p["kind"], p["status"]))
    # --- GPU server and GPU modules --------------------------------------------------------------------------------------------
    r = ref("dgx_b200")
    b200 = classical.Device.from_catalog("gpu_b200")
    rows.append(_row("dgx_b200_system", "GPU server, 8 x B200-class: system boundary", r["value_w"], 8 * b200.tdp_w * b200.system_overhead_ratio,
                     "system (maximum)", True, 8 * b200.tdp_w,
                     "Anchored: the server overhead ratio 1.79 is derived from this very figure (max-to-max).", r["kind"], r["status"]))
    rows.append(_row("dgx_b200_modules", "GPU server, 8 x B200-class: module boundary (8 x 1 kW)", 8 * 1000.0, 8 * b200.tdp_w, "module (maximum)", True,
                     None, "NVIDIA guide: 1,000 W per GPU maximum with five PSUs.", r["kind"], r["status"]))
    for key, rid, label, n_gpu in (("h200_sxm", "gpu_h200", "H200-class module", 1), ("mi350x", "gpu_mi350x", "MI350X-class module", 1),
                                   ("mi355x", "gpu_mi355x", "MI355X-class module", 1)):
        rr = ref(key)
        dev = classical.Device.from_catalog(rid)
        rows.append(_row(rid, label, rr["value_w"], dev.tdp_w, "module (maximum)", True, None, "", rr["kind"], rr["status"]))
    rr = ref("mi355x")
    mi = classical.Device.from_catalog("gpu_mi355x")
    rows.append(_row("mi355x_x8", "Eight MI355X, GPUs only (11.2 kW in the overview)", 8 * rr["value_w"], 8 * mi.tdp_w, "module (maximum)", True, None,
                     "The server around them adds power (not stated by AMD); the model's ratio for this class is an assumption.",
                     rr["kind"], rr["status"]))
    return rows


def calibration_markdown(rows: list[dict[str, Any]]) -> str:
    from .report import _table
    from .architecture import _fmt_w
    L = ["# Calibration of the `today` profile against published figures", "",
         "Published figures are a mix of ratings, maxima, averages and vendor claims at different boundaries; they are not matched "
         "benchmarks. `anchored` rows hold by construction (the catalog was set from that figure). The first column of each row names "
         "the measurement boundary of BOTH numbers.", "",
         _table(["case", "reference", "kind / status", "model (today)", "model / ref.", "boundary", "anchored", "old default / ref."],
                [[r["label"], _fmt_w(r["reference_w"]), f"{r['reference_status']}", _fmt_w(r["model_w"]), f"{r['ratio']:.2f}", r["boundary"],
                  "yes" if r["anchored_by_construction"] else "no",
                  f"{r['legacy_ratio']:.2f}" if r["legacy_ratio"] else "—"] for r in rows]), ""]
    L += ["## Notes", ""] + [f"- **{r['label']}**: {r['comment']}" for r in rows if r["comment"]]
    return "\n".join(L) + "\n"
