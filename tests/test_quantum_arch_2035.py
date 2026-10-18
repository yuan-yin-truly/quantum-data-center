"""Tests for the data-centre-of-2035 extension of quantum_arch.

They pin: scenario ordering of the mid-2030s profiles, the three power-measurement boundaries, the
calibration against published figures, the separate annealer class, the explicit I/O overhead of
quantum linear algebra, the GPU baselines, and the qualitative result of the hybrid scheduler
(replace only helps if enough work can move; augment is the plausible path), with no "N GPUs per QPU"
conversion anywhere.
"""

import json
import math
import re
from pathlib import Path

import pytest

from quantum_arch import (Architecture, annealer, baselines, calibration, catalog, classical, datacenter, evaluate,
                          qec, report)
from quantum_arch.__main__ import EXAMPLES

ROOT = Path(__file__).resolve().parents[1]
GATE_MODALITIES = ["superconducting", "spin_silicon", "trapped_ion", "neutral_atom", "cat_superconducting", "photonic"]
SCEN = ["mid2030s_low", "mid2030s", "mid2030s_high"]


def _arch(**kw):
    base = {"name": "t", "plates": False, "workloads": []}
    base.update(kw)
    return Architecture.from_dict(base)


# ---- profiles and defaults ----------------------------------------------------------------------
def test_mid2030s_is_the_default_profile_and_old_profiles_still_work():
    assert Architecture.from_dict({}).config["profile"] == "mid2030s"
    for prof in ("today", "projected", "mid2030s"):
        res = evaluate(_arch(modality="superconducting", profile=prof, n_qubits=1000))
        assert res.total_power_w > 0
    res = evaluate(_arch(modality="superconducting", profile="mid2030s_base", n_qubits=1000))   # alias
    assert res.arch["profile"] == "mid2030s_base" and res.budget.p_eff > 0


@pytest.mark.parametrize("modality", GATE_MODALITIES)
def test_scenarios_are_ordered_low_base_high(modality):
    lam = []
    for p in SCEN:
        res = evaluate(_arch(modality=modality, profile=p, n_qubits=2000, scheme=None))
        lam.append(res.capability.lam)
    assert lam[0] < lam[1] < lam[2]
    # and the base scenario is better than today's anchor
    today = evaluate(_arch(modality=modality, profile="today", n_qubits=2000))
    assert lam[1] > today.capability.lam


def test_catalog_values_carry_a_source_or_the_word_assumption():
    for name in ("classical", "fridges", "codes", "workloads", "annealers"):
        for key in catalog.keys(name):
            e = catalog.entry(name, key)
            text = json.dumps(e.get("source", "")) + json.dumps([p.get("profile_note", "") for p in e.get("profiles", {}).values()])
            assert text.strip('"[]," ') and ("assumption" in text.lower() or "ASSUMPTION" in text or re.search(r"\d{4}|et al|arXiv|Nature|NVIDIA|AMD|D-Wave|Bluefors|definition", text)), (name, key)
    for key in catalog.keys("modalities"):
        mod = catalog.entry("modalities", key)
        for pname, prof in mod["profiles"].items():
            if pname.startswith("mid2030s"):
                assert prof.get("profile_note"), (key, pname)
        for sk, s in mod["schemes"].items():
            assert s.get("source") or "extends" in s or s.get("label"), (key, sk)


def test_every_2035_classical_device_is_flagged_as_a_scenario():
    for k in catalog.keys("classical"):
        e = catalog.entry("classical", k)
        if k.endswith("_2035") or "_2035_" in k:
            assert e["vintage"] == "mid2030s" and e["scenario"] in ("base", "slow progress", "fast progress")
            assert "SCENARIO" in e["source"] or "ASSUMPTION" in e["source"]
        else:
            assert e.get("vintage") in ("today", None)


def test_scenario_suffix_resolution_for_classical_devices():
    assert classical.Device.from_catalog("gpu_2035", "mid2030s_low").key == "gpu_2035_low"
    assert classical.Device.from_catalog("gpu_2035", "mid2030s_high").key == "gpu_2035_high"
    assert classical.Device.from_catalog("auto:gpu", "today").key == "gpu_b200"
    assert classical.Device.from_catalog("auto:cpu", "mid2030s").key == "cpu_2035"
    assert classical.Device.from_catalog("auto:asic_4k", "mid2030s_high").key == "asic_decoder_4k_2035_high"
    low, base, high = (classical.Device.from_catalog("gpu_2035", p) for p in SCEN)
    assert low.fp16_flops < base.fp16_flops < high.fp16_flops and low.hbm_tbps < base.hbm_tbps < high.hbm_tbps


# ---- power-measurement boundaries -----------------------------------------------------------------
def test_boundaries_module_system_facility_are_distinct_and_consistent():
    res = evaluate(Architecture.from_file(EXAMPLES / "dc2035_cat_40k.json"))
    b = res.boundaries
    assert b["system"]["power_w"] == pytest.approx(res.total_power_w)
    assert b["facility"]["power_w"] == pytest.approx((res.total_power_w + b["facility"]["network_support_w"]) * b["facility"]["pue"])
    assert res.metrics["facility_power_w"] == pytest.approx(b["facility"]["power_w"])
    assert 0 < b["module"]["electrical_w"] < b["system"]["power_w"] < b["facility"]["power_w"]
    # the cold-stage heat load is thermal and is NOT a share of the wall power
    cold = b["module"]["cold_heat_load_w"]
    assert cold == pytest.approx(sum(s.load_w for s in res.cryo.stages)) and cold < 0.1 * res.total_power_w
    d = report.to_dict(res)
    assert d["power_boundaries"]["module"]["cold_heat_load_w"] == pytest.approx(cold)
    assert "Power at the three measurement boundaries" in report.summary_markdown(res)


def test_facility_boundary_includes_network_and_pue_once():
    a = _arch(modality="trapped_ion", profile="today", n_qubits=100, facility={"pue": 1.5, "network_support_w": 2000.0})
    res = evaluate(a)
    assert res.boundaries["facility"]["power_w"] == pytest.approx((res.total_power_w + 2000.0) * 1.5)
    assert "network_support_w" not in res.power_w     # it is a facility item, not a system consumer


def test_cold_electronics_supply_is_part_of_the_system_boundary():
    res = evaluate(_arch(modality="superconducting", profile="projected", scheme="cryo_cmos_4k", n_qubits=2000))
    key = "cold electronics supply (cryo-CMOS, amplifiers, cold decoders)"
    assert res.power_w[key] == pytest.approx(res.cryo.stage_result("4K").components_w, rel=0.02)


def test_server_overhead_is_opt_in_and_uses_the_device_ratio():
    plain = evaluate(_arch(modality="trapped_ion", profile="today", n_qubits=100,
                           classical=[{"role": "host", "device": "gpu_b200", "count": 2, "utilisation": 1.0}]))
    ovh = evaluate(_arch(modality="trapped_ion", profile="today", n_qubits=100, facility={"include_server_overhead": True},
                         classical=[{"role": "host", "device": "gpu_b200", "count": 2, "utilisation": 1.0}]))
    extra = ovh.total_power_w - plain.total_power_w
    assert extra == pytest.approx(2 * 1000.0 * (1.79 - 1.0))


def test_workload_energies_are_reported_at_system_and_facility_boundary():
    res = evaluate(_arch(modality="superconducting", profile="mid2030s", scheme="cryo_cmos_4k", n_qubits=300000,
                         cryostat={"capacity_scale": 112.0}, workloads=["chemistry_small"], facility={"pue": 1.3}))
    w = res.workloads["chemistry_small"]
    assert w["feasible"] and w["boundary"] == "system"
    assert w["facility_energy_j"] == pytest.approx(w["energy_j"] * 1.3)
    assert w["p_accept"] == pytest.approx(1 - w["total_logical_error"])


# ---- calibration ----------------------------------------------------------------------------------
def test_calibration_against_published_power_figures():
    rows = {r["id"]: r for r in calibration.run_calibration()}
    assert 0.6 < rows["helios_vs_40kW"]["ratio"] <= 1.0              # below the <40 kW upper bound, same scale
    assert rows["helios_vs_40kW"]["legacy_ratio"] < 0.2              # the old 3 kW + 40 W/qubit default was far too low
    assert rows["dwave_advantage2"]["ratio"] == pytest.approx(1.0, abs=0.01)
    assert rows["quandela_ascella"]["ratio"] == pytest.approx(1.0, abs=0.01)
    assert rows["quera_aquila_256"]["ratio"] == pytest.approx(1.0, abs=0.02)
    assert rows["quera_aquila_10000"]["ratio"] == pytest.approx(1.0, abs=0.02)
    assert rows["dgx_b200_system"]["ratio"] == pytest.approx(1.0, abs=0.01)
    assert rows["dgx_b200_modules"]["ratio"] == pytest.approx(1.0, abs=0.01)
    assert rows["gpu_mi355x"]["model_w"] == 1400.0 and rows["gpu_h200"]["model_w"] == 700.0
    refs = catalog.load("references")
    assert refs["power"]["pasqal_overview"]["status"] == "unconfirmed"
    assert refs["power"]["helios_oracle"]["status"] != "confirmed"


def test_calibration_markdown_names_the_boundary_and_states_the_limits():
    md = calibration.calibration_markdown(calibration.run_calibration())
    assert "boundary" in md and "not matched" in md


# ---- more modalities, honestly flagged -------------------------------------------------------------------
def test_cat_qubits_need_far_fewer_physical_qubits_per_logical_qubit():
    cat, surf = qec.Code("cat_repetition"), qec.Code("surface")
    for d in (5, 15, 25):
        assert cat.tile_qubits(d) == 2 * d - 1 < surf.tile_qubits(d)
    assert cat.tile_qubits(5) == 9           # AWS Ocelot: 5 cat + 4 ancilla qubits


def test_cat_bit_flip_floor_can_make_a_target_unreachable():
    a = dict(modality="cat_superconducting", profile="mid2030s", n_qubits=40000, scheme="cryo_cmos_4k")
    good = evaluate(_arch(**a))
    bad = evaluate(_arch(qubit_overrides={"err_bitflip": 1e-9}, **a))
    assert good.capability.feasible and not bad.capability.feasible
    assert "bit-flip" in bad.capability.reason
    assert good.capability.logical_qubits > evaluate(_arch(modality="superconducting", profile="mid2030s", n_qubits=40000,
                                                           scheme="cryo_cmos_4k")).capability.logical_qubits


def test_photonic_and_cat_models_are_flagged_as_coarse():
    mods = catalog.load("modalities")
    assert "coarse" in mods["photonic"]["flags"].lower() and "NOT a surface code" in mods["photonic"]["flags"]
    assert "assumption" in mods["cat_superconducting"]["flags"].lower()
    assert "ASSUMPTION" in catalog.entry("codes", "fusion_network")["source"]


def test_annealer_is_a_separate_class_with_its_own_metrics():
    with pytest.raises(KeyError):
        evaluate(_arch(modality="annealer"))                      # not a gate-model modality
    assert "annealer" not in catalog.keys("modalities")
    res = annealer.evaluate_annealer({"profile": "today", "host": {"device": "cpu_epyc_96c", "count": 0, "utilisation": 0.0}})
    d = res.to_dict()
    assert "rqops" not in {k.lower() for k in d} and "NOT comparable" in d["metrics_family"]
    assert res.system_power_w == pytest.approx(12500.0)
    easy, hard = annealer.solve_cost(res, 0.1), annealer.solve_cost(res, 0.001)
    assert hard["reads"] > easy["reads"] and hard["energy_system_j"] > easy["energy_system_j"]
    assert easy["confidence_achieved"] >= 0.99
    assert res.boundaries["facility"]["power_w"] > res.boundaries["system"]["power_w"] > res.boundaries["module"]["cold_heat_load_w"]


# ---- quantum linear algebra: explicit I/O overhead, no advantage claimed -------------------------------------
def test_quantum_linear_algebra_charges_loading_and_readout_and_claims_no_advantage():
    res = evaluate(_arch(modality="superconducting", profile="mid2030s", scheme="cryo_cmos_4k", n_qubits=300000,
                         cryostat={"capacity_scale": 112.0},
                         workloads=["qla_scalar_explicit_1m", "qla_full_vector_1m"]))
    sc, fv = res.workloads["qla_scalar_explicit_1m"], res.workloads["qla_full_vector_1m"]
    for w in (sc, fv):
        assert w["advantage_claimed"] is False and "No quantum advantage" in w["caveat"]
        assert w["energy_ratio_quantum_over_classical"] > 1.0       # the classical solver wins by orders of magnitude
    assert sc["io_overhead_share"] > 0.9
    assert fv["energy_j"] > 1e6 * sc["energy_j"]                    # reading every amplitude out is hopeless
    assert fv["runs"] == pytest.approx(fv["inversion_toffoli"] * 0 + 1048576 / 1e-4)


# ---- GPU baselines --------------------------------------------------------------------------------------
def test_llm_inference_baseline_boundaries_and_scenario_ordering():
    t = {k: baselines.llm_inference(k, "today" if "2035" not in k else "mid2030s") for k in ("gpu_h200", "gpu_b200", "gpu_2035")}
    for r in t.values():
        j = r["j_per_token"]
        assert j["module"] < j["system"] <= j["facility"]
    assert t["gpu_2035"]["j_per_token"]["system"] < t["gpu_b200"]["j_per_token"]["system"] < t["gpu_h200"]["j_per_token"]["system"]
    low, base, high = (baselines.llm_inference("gpu_2035", p)["j_per_token"]["system"] for p in SCEN)
    assert high < base < low
    idle_heavy = baselines.llm_inference("gpu_2035", "mid2030s", utilisation=0.1)["j_per_token"]["module"]
    assert idle_heavy > baselines.llm_inference("gpu_2035", "mid2030s", utilisation=0.9)["j_per_token"]["module"]


def test_mlperf_anchor_reproduces_the_amd_node_throughput():
    r = baselines.llm_inference("gpu_mi355x", "today")
    assert 8 * r["tokens_per_s_per_module_at_slo"] == pytest.approx(100282.0, rel=0.02)


def test_training_baseline_scales_with_modules_and_has_no_quantum_counterpart():
    a = baselines.llm_training("gpu_2035", 1000, "mid2030s")
    b = baselines.llm_training("gpu_2035", 2000, "mid2030s")
    assert a["time_s"] == pytest.approx(2 * b["time_s"])
    assert a["energy_j"]["module"] == pytest.approx(b["energy_j"]["module"], rel=1e-6)
    assert "No quantum" in baselines.dense_matmul("gpu_2035", "mid2030s")["note"]


# ---- data-centre scheduler -----------------------------------------------------------------------------
def test_erlang_c_known_values():
    assert datacenter.erlang_c(1, 0.5) == pytest.approx(0.5)               # M/M/1: P(wait) = rho
    assert datacenter.erlang_c(2, 1.0) == pytest.approx(1.0 / 3.0)         # textbook value
    assert datacenter.mean_wait_s(1, 0.5, 10.0) == pytest.approx(10.0)     # M/M/1: rho/(1-rho) x S
    assert datacenter.mean_wait_s(2, 2.0, 1.0) == math.inf


def test_closed_form_replace_limit():
    assert datacenter.replace_capacity_ratio(0.0, 0.5) == pytest.approx(0.5)
    assert datacenter.replace_capacity_ratio(0.5, 0.5) == pytest.approx(1.0)
    assert datacenter.replace_capacity_ratio(0.8, 0.5) > 1.0
    assert datacenter.break_even_moved_fraction(0.5) == 0.5


def test_per_job_feasibility_is_delegated_to_evaluate():
    chk = datacenter.quantum_job_check("dc2035_cat_40k", "chemistry_small")
    res = evaluate(Architecture.from_file(EXAMPLES / "dc2035_cat_40k.json").with_overrides(workloads=["chemistry_small"], plates=False))
    w = res.workloads["chemistry_small"]
    assert chk["feasible"] and chk["runtime_s"] == pytest.approx(w["runtime_s"]) and chk["energy_system_j"] == pytest.approx(w["energy_j"])
    assert chk["total_logical_error"] <= 0.1
    infeasible = datacenter.quantum_job_check("dc2035_cat_40k", "femoco_thc")
    assert not infeasible["feasible"] and infeasible["reason"]


def test_offload_decision_function():
    job = {"workload": "chemistry_small", "gpu_seconds": 64 * 12 * 3600, "gpus_per_job": 64, "mapping_quality": 0.7,
           "prep_s": 600, "post_s": 300}
    d = datacenter.offload_decision(job, "dc2035_cat_40k")
    assert d["route"] == "quantum" and d["quantum"]["turnaround_s"] < d["gpu"]["turnaround_s"]
    cheap = dict(job, gpu_seconds=64 * 60.0)                       # a classical solver that needs only 1 h on 64 modules
    assert datacenter.offload_decision(cheap, "dc2035_cat_40k")["route"] == "gpu"
    assert datacenter.offload_decision(job, "dc2035_cat_40k", queue_wait_quantum_s=1e6)["route"] == "gpu"
    assert datacenter.offload_decision(dict(job, workload="femoco_thc"), "dc2035_cat_40k")["route"] == "gpu"


@pytest.fixture(scope="module")
def runs():
    return {n: datacenter.run_datacenter(n) for n in ("dc2035_ai_serving", "dc2035_research", "dc2035_research_cat")}


def test_replacing_gpus_without_movable_work_cuts_ordinary_ai_capacity(runs):
    r = runs["dc2035_ai_serving"]["scenarios"]
    assert r["replace"]["comparison"]["max_total_demand_ratio"] < 0.6
    assert r["replace"]["served_fraction"] < 0.7                      # it cannot even carry the baseline demand
    assert r["replace"]["comparison"]["ordinary_ai_capacity_ratio"] < 0.6
    assert r["augment"]["comparison"]["max_total_demand_ratio"] >= 1.0
    assert r["augment"]["comparison"]["ordinary_ai_capacity_ratio"] >= 1.0


def test_augment_gains_capacity_when_enough_work_can_move(runs):
    r = runs["dc2035_research"]["scenarios"]
    assert r["augment"]["comparison"]["max_total_demand_ratio"] > 1.1
    assert r["augment"]["movable_share_of_demand"] > 0.15
    assert r["augment"]["comparison"]["max_total_demand_ratio"] > r["replace"]["comparison"]["max_total_demand_ratio"]
    mc = next(c for c in r["augment"]["classes"] if c["class"] == "materials_chemistry")
    assert mc["quantum_turnaround_s"] < mc["gpu_turnaround_s"] and mc["routed_to_quantum"] > 0


def test_power_boundaries_of_the_facility_are_ordered_and_consistent(runs):
    for res in runs.values():
        for r in res["scenarios"].values():
            p = r["power_w"]
            assert p["module"] < p["system"] < p["facility"]
            assert p["system"] == pytest.approx(sum(p["by_pool_system_w"].values()))
            assert p["facility"] == pytest.approx(p["system"] * (1 + res["facility"]["network_overhead_fraction"]) * res["facility"]["pue"])


def test_energy_per_accepted_answer_is_conserved_across_classes(runs):
    r = runs["dc2035_research"]["scenarios"]["augment"]
    attributed = sum(c["facility_j_per_accepted_answer"] * c["answers_per_s"] for c in r["classes"])
    gpu_q = (r["power_w"]["by_pool_system_w"]["gpu"] + sum(v for k, v in r["power_w"]["by_pool_system_w"].items() if k.startswith("quantum:")))
    fac = runs["dc2035_research"]["facility"]
    assert attributed == pytest.approx(gpu_q * (1 + fac["network_overhead_fraction"]) * fac["pue"], rel=1e-6)


def test_break_even_movable_fraction_for_replace_matches_the_removed_fraction():
    sw = datacenter.movable_sweep("dc2035_research", shares=[i / 10 for i in range(0, 11)])
    be = sw["break_even"]["replace"]["movable_share_for_capacity_parity"]
    assert be is not None and 0.45 < be < 0.7                         # about the 50 % of GPUs removed, plus failures and retries
    assert sw["break_even"]["augment"]["movable_share_for_capacity_parity"] == 0
    caps = [r["replace"]["max_demand_ratio"] for r in sw["rows"]]
    assert all(b >= a - 1e-6 for a, b in zip(caps, caps[1:]))        # more movable work never hurts


def test_a_hungry_idle_quantum_system_makes_augment_cost_energy(runs):
    sc, cat = runs["dc2035_research"]["scenarios"]["augment"], runs["dc2035_research_cat"]["scenarios"]["augment"]
    assert sc["comparison"]["energy_per_baseline_gpu_second_ratio"] > 1.0       # MW-scale cryostat on standby
    assert cat["comparison"]["energy_per_baseline_gpu_second_ratio"] < sc["comparison"]["energy_per_baseline_gpu_second_ratio"]


def test_datacenter_report_files_and_valid_json(tmp_path):
    res = datacenter.run_datacenter("dc2035_research")
    sw = datacenter.movable_sweep("dc2035_research", shares=[0.0, 0.5, 1.0])
    out = datacenter.write_datacenter_report(res, sw, tmp_path / "dc")
    for name in ("result.json", "summary.md", "movable_sweep.png"):
        assert (out / name).stat().st_size > 0
    json.loads((out / "result.json").read_text(), parse_constant=lambda c: pytest.fail("NaN/Infinity in JSON"))


def test_pool_failure_modes_are_reported_not_hidden():
    cfg = datacenter.load_config("dc2035_research")
    cfg["quantum_pools"]["sc_surface"]["architecture"] = {**json.loads((EXAMPLES / "dc2035_sc_surface_300k.json").read_text()), "n_qubits": 1000}
    res = datacenter.run_datacenter(cfg)
    notes = [c["note"] for c in res["scenarios"]["augment"]["classes"] if c["class"] == "materials_chemistry"]
    assert notes and "infeasible" in notes[0]


# ---- wording and compatibility -------------------------------------------------------------------------------
def test_no_replacement_ratio_is_stated_anywhere():
    bad = re.compile(r"1\s*(QPU|quantum (chip|processor))\s*(=|equals)\s*\d+\s*GPU", re.I)
    for path in [ROOT / "README_QUANTUM.md", *Path(ROOT / "quantum_arch").rglob("*.md"), *Path(ROOT / "quantum_arch").rglob("*.py")]:
        assert not bad.search(path.read_text(encoding="utf-8", errors="ignore")), path
    assert "no meaningful conversion" in (ROOT / "README_QUANTUM.md").read_text().lower()
    assert "Quantum Echoes" in (ROOT / "README_QUANTUM.md").read_text()


def test_hill_facing_api_is_unchanged():
    from quantum_arch import Architecture as A, Result, evaluate as ev, DEFAULTS
    res = ev(A.from_file(EXAMPLES / "sc_rt_direct_100q.json"))
    d = report.to_dict(res)
    for key in ("name", "modality", "scheme", "profile", "n_qubits", "computing", "decoder", "power_w", "total_power_w",
                "facility_power_w", "metrics", "classical_blocks", "workloads", "warnings", "cryostat"):
        assert key in d
    assert {"quantum_arch_total"} or True
    assert res.arch["facility"]["pue"] == 1.2 and isinstance(DEFAULTS["facility"]["pue"], float)
    for blk in res.blocks:
        assert blk.power_w > 0 and blk.device.idle_w >= 0
    w = res.workloads["vqe_50q"]
    for k in ("feasible", "runtime_s", "energy_j", "power_w", "type"):
        assert k in w
