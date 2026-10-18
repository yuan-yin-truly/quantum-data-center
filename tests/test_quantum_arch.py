"""Physics and plumbing checks for quantum_arch.

The cable and attenuator tests pin the model to Krinner et al., EPJ Quantum
Technology 6, 2 (2019): per-line heat loads of a 0.085" stainless coax in a
Bluefors XLD400, and the 10 dBm attenuator experiment.
"""

import json
import math

import numpy as np
import pytest

from quantum_arch import Architecture, evaluate, materials, qec, report, sweep, thermal2d, wiring
from quantum_arch.cryo import Fridge, carnot_floor_w
from quantum_arch.__main__ import EXAMPLES

KRINNER_TEMPS = {"50K": 35.0, "4K": 2.85, "Still": 0.882, "CP": 0.082, "MXC": 0.006}


# ---- materials ----------------------------------------------------------------------------
def test_integral_of_linear_conductivity_is_exact():
    m = materials.Material("lin", ((1.0, 1.0), (300.0, 300.0)))
    assert materials.conductivity_integral(m, 0.0, 10.0) == pytest.approx(50.0, rel=2e-3)
    assert materials.conductivity_integral(m, 5.0, 50.0) == pytest.approx((50**2 - 5**2) / 2, rel=2e-3)


def test_stainless_integral_matches_handbook():
    # Handbook value of the 4-300 K integral for 304 stainless: about 3000 W/m.
    val = materials.conductivity_integral(materials.get("ss304"), 4.0, 300.0)
    assert 2700 < val < 3300


# ---- wiring -------------------------------------------------------------------------------
def _drive_line():
    return wiring.LineType.from_dict(dict(
        kind="drive", per_qubit=1, cable="coax_ut085_ss", reach="MXC",
        attenuation_db={"4K": 20, "CP": 20, "MXC": 20}, chip_power_dbm=-78))


def test_passive_load_matches_krinner_prediction():
    p = wiring.passive_per_line(_drive_line(), Fridge.from_catalog("dilution_xld"), KRINNER_TEMPS)
    # Paper: 24-27 mW, 0.4-1.7 mW, 1.9-2.1 uW, 0.33-0.43 uW, 0.004 uW.
    assert 0.85 * 24e-3 < p["50K"] < 1.15 * 27e-3
    assert 0.8 * 0.4e-3 < p["4K"] < 1.7e-3
    assert 0.75 * 1.9e-6 < p["Still"] < 1.25 * 2.1e-6
    assert 0.7 * 0.33e-6 < p["CP"] < 1.3 * 0.43e-6
    assert 0.5 * 4e-9 < p["MXC"] < 2 * 4e-9


def test_nbti_output_line_is_within_a_small_factor_of_krinner_at_the_cold_plate():
    line = wiring.LineType.from_dict(dict(
        kind="out", per_qubit=1, cable={"warm": "coax_ut085_ss", "cold": "coax_ut085_nbti"}, reach="MXC"))
    p = wiring.passive_per_line(line, Fridge.from_catalog("dilution_xld"), KRINNER_TEMPS)
    # Paper: 0.29-0.39 uW. The model assumes full thermalisation and underestimates by ~2x.
    assert 0.29e-6 / 3 < p["CP"] < 0.39e-6 * 1.2


def test_attenuator_dissipation_matches_krinner_experiment():
    line = wiring.LineType.from_dict(dict(
        kind="t", per_qubit=1, cable="coax_ut085_ss", reach="MXC",
        attenuation_db={"4K": 20, "CP": 20, "MXC": 20}, chip_power_dbm=10 - 60, cable_loss_db_per_segment=0))
    a = wiring.active_per_line(line, Fridge.from_catalog("dilution_xld"))
    assert a["4K"] == pytest.approx(9.9e-3, rel=0.01)
    assert a["CP"] == pytest.approx(99e-6, rel=0.01)
    assert a["MXC"] == pytest.approx(0.99e-6, rel=0.01)


def test_active_power_is_conserved():
    # Launched power ends up as heat in the cryostat, at the chip, or (for half the first
    # cable segment) on the room-temperature side.
    line = _drive_line()
    f = Fridge.from_catalog("dilution_xld")
    launched = 1e-3 * 10 ** ((-78 + 60 + 1.5 * 5) / 10)
    first_half = 0.5 * launched * (1 - 10 ** (-0.15))
    delivered = 1e-3 * 10 ** (-78 / 10)
    dissipated = sum(wiring.active_per_line(line, f).values())
    assert dissipated == pytest.approx(launched - delivered - first_half, rel=1e-9)


def test_cold_start_line_heats_its_own_launch_stage():
    line = wiring.LineType.from_dict(dict(
        kind="x", per_qubit=1, cable="flex_nbti", start="4K", reach="MXC",
        attenuation_db={"MXC": 20}, chip_power_dbm=-78))
    a = wiring.active_per_line(line, Fridge.from_catalog("dilution_xld"))
    assert a["4K"] > 0 and a["50K"] == 0  # cable loss in the first cold segment warms the launch stage


def test_cold_start_line_ignores_warm_stages():
    line = wiring.LineType.from_dict(dict(kind="x", per_qubit=1, cable="flex_nbti", start="4K", reach="MXC"))
    f = Fridge.from_catalog("dilution_xld")
    p = wiring.passive_per_line(line, f, KRINNER_TEMPS)
    assert "50K" not in p and "4K" not in p and set(p) == {"Still", "CP", "MXC"}


# ---- cryostat -----------------------------------------------------------------------------
def test_cooling_curve_round_trip_and_anchor():
    f = Fridge.from_catalog("dilution_xld")
    for st in f.stages:
        assert st.capacity(st.t_ref_k) == pytest.approx(st.cap_ref_w)
        assert st.capacity(st.temperature(0.5 * st.cap_ref_w)) == pytest.approx(0.5 * st.cap_ref_w)
        assert st.temperature(0.0) == pytest.approx(st.t_base_k)


def test_carnot_floor():
    assert carnot_floor_w({"4K": 1.0}, {"4K": 4.0}) == pytest.approx(300 / 4 - 1)


# ---- spatial thermal solver -----------------------------------------------------------------
def test_uniform_power_gives_uniform_temperature_matching_contact_law():
    contact = thermal2d.Contact(1.0, 4.0, 2.0)
    plate = thermal2d.Plate("u", "4K", 4.2, (10, 10), 0.3, "silicon", contact,
                            [thermal2d.Source("all", 0, 0, 10, 10, 0.1)])
    res = thermal2d.solve_plate(plate)
    area = 1e-4
    assert np.ptp(res.temperature_k) < 1e-6
    assert contact.flux(res.temperature_k.mean(), 4.2) * area == pytest.approx(0.1, rel=1e-5)


@pytest.mark.parametrize("stage_t,power", [(4.2, 0.5), (0.02, 2e-6)])
def test_heat_is_conserved_with_hotspots(stage_t, power):
    plate = thermal2d.Plate("c", "s", stage_t, (20, 20), 0.3, "silicon", thermal2d.Contact(),
                            [thermal2d.Source("a", 4, 4, 6, 6, power, hotspot=3.0),
                             thermal2d.Source("b", 12, 10, 5, 5, power / 2)])
    res = thermal2d.solve_plate(plate)
    assert res.removed_w == pytest.approx(res.injected_w, rel=1e-5)
    assert res.injected_w == pytest.approx(1.5 * power, rel=1e-9)
    assert res.rise_max_k > 0
    # The hot spot lies inside source "a".
    iy, ix = np.unravel_index(res.temperature_k.argmax(), res.temperature_k.shape)
    assert 4 <= (ix + 0.5) * res.ds_mm <= 10 and 4 <= (iy + 0.5) * res.ds_mm <= 10


def test_better_conductor_spreads_heat_and_lowers_peak():
    def peak(material):
        plate = thermal2d.Plate("m", "4K", 4.2, (30, 30), 1.0, material, thermal2d.Contact(),
                                [thermal2d.Source("a", 12, 12, 6, 6, 1.0)])
        return thermal2d.solve_plate(plate).rise_max_k

    assert peak("cu_rrr100") < peak("silicon") < peak("ptfe")


# ---- error correction ---------------------------------------------------------------------
def test_surface_code_patch_size_and_scaling():
    code = qec.Code("surface")
    assert code.tile_qubits(5) == 49
    p = 1e-3
    assert code.logical_error_per_round(p, 7) / code.logical_error_per_round(p, 5) == pytest.approx(p / code.threshold)


def test_capability_grows_with_qubits_and_fails_above_threshold():
    from quantum_arch.architecture import resolve_modality
    m = resolve_modality("superconducting", "projected", {})
    budget = qec.error_budget(m)
    code = qec.Code("surface")
    small = qec.capability(code, budget, 100_000)
    big = qec.capability(code, budget, 1_000_000)
    assert big.logical_qubits > small.logical_qubits > 0
    assert big.rqops > small.rqops
    bad = qec.capability(code, qec.ErrorBudget(1e-6, 0.02, 0, {}), 1_000_000)
    assert not bad.feasible


def test_workload_plan_respects_error_budget_and_runtime_bounds():
    from quantum_arch.architecture import resolve_modality
    budget = qec.error_budget(resolve_modality("superconducting", "projected", {}))
    code = qec.Code("surface")
    plan = qec.plan_workload(code, budget, 2_000_000, 100, 1e8, 1e8, 0.1, reaction_time_s=1e-5)
    assert plan.feasible and plan.total_logical_error <= 0.1
    assert plan.runtime_s >= 1e8 * 1e-5  # cannot beat the reaction time
    starved = qec.plan_workload(code, budget, 10_000, 100, 1e8, 1e8, 0.1, reaction_time_s=1e-5)
    assert not starved.feasible and starved.reference_qubits > 10_000


# ---- end to end ---------------------------------------------------------------------------
EXAMPLE_FILES = sorted(EXAMPLES.glob("*.json"))


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.stem)
def test_every_example_evaluates_and_serialises(path):
    res = evaluate(Architecture.from_file(path))
    assert res.total_power_w == pytest.approx(sum(res.power_w.values()))
    json.dumps(report.to_dict(res), default=float)
    assert "##" in report.summary_markdown(res)
    for plate in res.plates:
        assert plate.removed_w == pytest.approx(plate.injected_w, rel=1e-4)


def test_ambient_systems_have_no_cryostat_and_cryo_systems_do():
    ion = evaluate(Architecture.from_file(EXAMPLES / "ion_qccd_100q.json"))
    sc = evaluate(Architecture.from_file(EXAMPLES / "sc_rt_direct_100q.json"))
    assert ion.cryo is None and "cryostat (installed)" not in ion.power_w
    assert sc.cryo is not None and sc.power_w["cryostat (installed)"] == sc.cryo.wall_power_w


def test_direct_wiring_hits_the_cold_plate_wall_before_cryo_cmos_does():
    base = Architecture.from_file(EXAMPLES / "sc_rt_direct_100q.json")
    direct = sweep.max_qubits_single_fridge(base)
    thin = sweep.max_qubits_single_fridge(base.with_overrides(scheme="rt_ut047"))
    cmos = sweep.max_qubits_single_fridge(base.with_overrides(scheme="cryo_cmos_4k"))
    assert direct["max_qubits"] < thin["max_qubits"] < cmos["max_qubits"]
    assert direct["limit"] in ("CP", "MXC")
    assert cmos["limit"] == "4K"
    # 4 K electronics at 4 mW/qubit against 1.5 W of cooling power.
    assert cmos["max_qubits"] == pytest.approx(1.5 / 4e-3, rel=0.08)


def test_overloaded_stage_is_reported_and_adds_fridges():
    res = evaluate(Architecture.from_file(EXAMPLES / "sc_rt_direct_100q.json"))
    cp = res.cryo.stage_result("CP")
    assert cp.overloaded and cp.temperature_k > cp.target_k
    assert res.cryo.units_needed >= math.ceil(cp.load_w / cp.capacity_w)
    assert any("CP stage overloaded" in w for w in res.warnings)


def test_qldpc_requires_nonlocal_connectivity():
    arch = Architecture.from_file(EXAMPLES / "sc_rt_direct_100q.json").with_overrides(
        qec={"code": "bivariate_bicycle", "decoder": "bp_osd"})
    res = evaluate(arch)
    assert not res.capability.feasible and "long-range" in res.capability.reason


def test_report_writes_files(tmp_path):
    res = evaluate(Architecture.from_file(EXAMPLES / "sc_cryo_cmos_100k.json"))
    out = report.write_report(res, tmp_path / "r")
    for name in ("result.json", "summary.md", "heat_budget.png", "power.png"):
        assert (out / name).stat().st_size > 0
    data = json.loads((out / "result.json").read_text())
    assert data["cryostat"]["stages"][1]["name"] == "4K"
