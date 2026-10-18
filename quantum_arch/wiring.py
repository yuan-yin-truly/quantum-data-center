"""Heat flowing down the signal lines of a cryostat.

Two contributions, following Krinner et al. (EPJ Quantum Technol. 6, 2, 2019):

*Passive* conduction. A line thermalised at every stage delivers to stage i

    Q_i = sum_conductors  A_c / L_i * integral_{T_i}^{T_{i-1}} k_c(T) dT

where L_i is the cable run between stage i-1 and i.

*Active* dissipation. A signal of average power ``P_chip`` at the qubit chip is
launched from room temperature at ``P_chip * 10^(total_attenuation/10)``. Each
attenuator turns the fraction ``1 - 10^(-A/10)`` of the power reaching it into
heat at its stage; cable loss is split evenly between the stages at the two
ends of a segment. DC bias lines dissipate ``I^2 R_eff`` times their duty cycle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from . import materials
from .cryo import T_ROOM, Fridge

#: Segments whose cold end is at or above this temperature use the "warm" conductors.
ZONE_SPLIT_K = 3.0


@dataclass(frozen=True)
class CableType:
    name: str
    #: (material, cross-section in mm^2, zone) with zone in {"all", "warm", "cold"}.
    conductors: tuple[tuple[str, float, str], ...]
    note: str = ""


def _coax(name, outer, centre, scale=1.0, note=""):
    # UT-085: centre Ø0.51 mm, PTFE Ø1.68 mm, outer conductor Ø1.68..2.19 mm.
    return CableType(name, (
        (outer, 1.55 * scale, "all"), (centre, 0.204 * scale, "all"),
        ("ptfe", 2.01 * scale, "all")), note)


CABLES: dict[str, CableType] = {c.name: c for c in [
    _coax("coax_ut085_ss", "ss304", "ss304", note="0.085\" stainless/stainless semi-rigid"),
    _coax("coax_ut085_cuni", "cuni", "cuni", note="0.085\" CuNi/CuNi semi-rigid"),
    _coax("coax_ut085_nbti", "nbti", "nbti", note="0.085\" NbTi/NbTi semi-rigid (superconducting)"),
    _coax("coax_ut047_ss", "ss304", "ss304", scale=(0.047 / 0.085) ** 2,
          note="0.047\" stainless semi-rigid, area scaled with diameter squared"),
    CableType("twisted_pair_dc", (("phosphor_bronze", 0.032, "warm"), ("nbti", 0.032, "cold")),
              "DC loom: phosphor-bronze pair to 4 K, NbTi pair below"),
    CableType("flex_nbti", (("nbti", 0.002, "all"), ("polyimide", 0.03, "all")),
              "Polyimide flex with NbTi trace, per line"),
    CableType("flex_cuni_digital", (("cuni", 0.0015, "all"), ("polyimide", 0.05, "all")),
              "Polyimide flex with CuNi trace for digital links, per line"),
    CableType("fiber_silica", (("silica", 0.0123, "all"),), "125 um silica fibre"),
]}


@dataclass
class LineType:
    """A family of identical lines running from room temperature down to ``reach``."""
    kind: str
    per_qubit: float
    cable: dict[str, str]
    reach: str
    attenuation_db: dict[str, float] = field(default_factory=dict)
    #: Average signal power delivered at the chip; ``None`` for output / passive lines.
    chip_power_dbm: float | None = None
    cable_loss_db_per_segment: float = 1.5
    dc_current_ma: float = 0.0
    dc_duty: float = 1.0 / 3.0
    r_eff_ohm: dict[str, float] = field(default_factory=dict)
    #: Room-temperature electronics channels consumed per line (0 if driven from the cold).
    rt_channels: float = 0.0
    #: Electrical power of one such channel (W). DAC/DC channels are far cheaper than RF ones.
    rt_w_per_channel: float = 8.0
    #: Stage the line starts at; ``None`` means room temperature.
    start: str | None = None
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "LineType":
        d = dict(d)
        if isinstance(d.get("cable"), str):
            d["cable"] = {"all": d["cable"]}
        return cls(**d)

    def count(self, n_qubits: int) -> int:
        return math.ceil(self.per_qubit * n_qubits - 1e-9) if self.per_qubit > 0 else 0


def with_reach(line: LineType, qpu_stage: str) -> LineType:
    """Resolve the symbolic reach ``"qpu"`` to the stage holding the qubits."""
    if line.reach == "qpu":
        return replace(line, reach=qpu_stage)
    return line


def _segments(line: LineType, fridge: Fridge) -> range:
    first = 0 if line.start is None else fridge.index(line.start) + 1
    return range(first, fridge.index(line.reach) + 1)


def _cable_for_zone(line: LineType, zone: str) -> CableType:
    key = line.cable.get(zone) or line.cable.get("all")
    if key is None:
        raise KeyError(f"line {line.kind!r} has no cable for zone {zone!r}")
    return CABLES[key]


def passive_per_line(line: LineType, fridge: Fridge, temps_k: dict[str, float]) -> dict[str, float]:
    """Conducted heat (W) delivered to each stage by ONE line of this type."""
    out: dict[str, float] = {}
    for i in _segments(line, fridge):
        stage = fridge.stages[i]
        t_hot = T_ROOM if i == 0 else temps_k[fridge.stages[i - 1].name]
        t_cold = temps_k[stage.name]
        zone = "warm" if t_cold >= ZONE_SPLIT_K else "cold"
        cable = _cable_for_zone(line, zone)
        length = stage.cable_len_mm * 1e-3
        q = 0.0
        for mat, area_mm2, z in cable.conductors:
            if z not in ("all", zone):
                continue
            q += (area_mm2 * 1e-6 / length) * materials.conductivity_integral(
                materials.get(mat), t_cold, t_hot)
        out[stage.name] = q
    return out


def _db_to_lin(db: float) -> float:
    return 10.0 ** (db / 10.0)


def active_per_line(line: LineType, fridge: Fridge) -> dict[str, float]:
    """Dissipated signal / bias power (W) at each stage for ONE line."""
    out = {s.name: 0.0 for s in fridge.stages}
    names = [fridge.stages[i].name for i in _segments(line, fridge)]
    above_first = line.start  # stage warmer than the first segment (None = room temperature)

    if line.chip_power_dbm is not None:
        p_chip = 1e-3 * _db_to_lin(line.chip_power_dbm)
        seg_loss = line.cable_loss_db_per_segment
        total_att = sum(line.attenuation_db.get(n, 0.0) for n in names) + seg_loss * len(names)
        power = p_chip * _db_to_lin(total_att)  # launched at room temperature
        for i, name in enumerate(names):
            # Cable segment arriving at this stage: half its loss heats the stage above, half this one.
            seg = power * (1 - _db_to_lin(-seg_loss))
            power -= seg
            out[name] += 0.5 * seg
            if i > 0:
                out[names[i - 1]] += 0.5 * seg
            elif above_first is not None:
                out[above_first] += 0.5 * seg
            att = line.attenuation_db.get(name, 0.0)
            absorbed = power * (1 - _db_to_lin(-att))
            out[name] += absorbed
            power -= absorbed
    if line.dc_current_ma:
        i_a = line.dc_current_ma * 1e-3
        for name, r in line.r_eff_ohm.items():
            if name in out:
                out[name] += i_a ** 2 * r * line.dc_duty
    return out
