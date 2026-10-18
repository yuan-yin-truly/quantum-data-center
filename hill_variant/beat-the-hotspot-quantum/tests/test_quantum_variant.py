"""Tests for the LOCAL-ONLY quantum variant.

Fast tests need only numpy (they also run in the hill container). Tests that touch
quantum_arch skip unless scipy and the quantum_arch repo are importable (use the
chiplet-thermal-gui venv). The HotSpot equivalence test is opt-in:

    RUN_HOTSPOT=1 <venv python> -m pytest tests/test_quantum_variant.py -k hotspot

(it needs Docker on macOS or a Linux x86-64 host and takes a few minutes).
"""

import copy
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

HILL = Path(__file__).resolve().parents[1]
needs_vendor = pytest.mark.skipif(not (HILL / "vendor/HotSpot/hotspot").exists(),
                              reason="vendor/HotSpot is not in the repo; restore it from the original hill (see README_QUANTUM_VARIANT.md)")
sys.path.insert(0, str(HILL))

from generate_workloads import generate  # noqa: E402
from geometry import validate_layout  # noqa: E402
from hybrid_power import (ModifierError, apply_modifiers, build_modifiers, is_identity,  # noqa: E402
                          power_budgets)
from interconnect import combined_heat  # noqa: E402
from quantum_block import QuantumBlockError, validate_quantum_block  # noqa: E402

SPEC = json.loads((HILL / "challenge_spec.json").read_text())
PORTABLE = generate(SPEC)
BASE_LAYOUT = json.loads((HILL / "examples/baseline/submission.json").read_text())["placements_mm"]
ROUTING = validate_layout(SPEC, BASE_LAYOUT)
WORKLOADS = list(SPEC["workloads"])


def vq(raw, **kw):
    return validate_quantum_block(raw, spec=SPEC, **kw)


MIN = {"architecture_example": "sc_rt_direct_100q", "task": {"workload": "vqe_50q"}}


# ---------------------------------------------------------------------------------------------
# schema validation
# ---------------------------------------------------------------------------------------------
def test_minimal_block_gets_explicit_defaults():
    nb = vq(MIN)
    assert nb["task"]["package_workload"] == "mixed_serving"
    assert nb["offload"]["dynamic_power_fraction"] == 1.0
    assert nb["offload"]["replaced_die_work"] == "redistributed"
    assert not nb["offload"]["any_fraction"]
    assert all(f == 0.0 for per in nb["offload"]["fractions"].values() for f in per.values())


@pytest.mark.parametrize("mutation, phrase", [
    ({"surprise": 1}, "unknown key"),
    ({"architecture": {}}, "exactly one"),
    ({"architecture_example": None, "architecture_overrides": [1]}, "architecture_example"),
    ({"task": {}}, "task.workload"),
    ({"task": {"workload": "vqe_50q", "package_workload": "nope"}}, "package_workload"),
    ({"offload": {"fractions": {"*": 1.5}}}, "<= 1"),
    ({"offload": {"fractions": {"*": -0.1}}}, ">= 0"),
    ({"offload": {"fractions": {"*": True}}}, "finite number"),
    ({"offload": {"fractions": {"*": float("nan")}}}, "finite number"),
    ({"offload": {"fractions": {"no_such_workload": 0.1}}}, "unknown workload"),
    ({"offload": {"fractions": {"*": {"H0": 0.1}}}}, "not a GPU die"),
    ({"offload": {"replaced_die_work": "vanish"}}, "replaced_die_work"),
    ({"offload": {"dynamic_power_fraction": 2}}, "<= 1"),
    ({"offload": {"active_in": ["tensor_training"], "fractions": {"memory_stream": 0.1}}}, "active_in"),
    ({"package_hosts": {"dies": {"G3": {"max_devices": 4}}}}, "device"),
    ({"package_hosts": {"device": "asic_decoder_rt", "dies": {"H0": {"max_devices": 4}}}}, "GPU die"),
    ({"package_hosts": {"device": "asic_decoder_rt", "dies": {"G3": {}}}}, "max_devices"),
    ({"package_hosts": {"device": "asic_decoder_rt", "dies": {"G3": {"max_devices": 2.5}}}}, "integer"),
    ({"package_hosts": {"device": "asic_decoder_rt",
                        "dies": {d: {"max_devices": 1} for d in ("G0", "G1", "G2", "G3")}}}, "remain a GPU"),
    ({"package_hosts": {"device": "asic_decoder_rt", "dies": {"G3": {"max_devices": 4}}},
      "offload": {"fractions": {"tensor_training": {"G3": 0.2}}}}, "cannot offload"),
    ({"limits": {"max_fridge_units": -1}}, ">= 0"),
])
def test_malformed_blocks_are_rejected_with_a_clear_message(mutation, phrase):
    raw = copy.deepcopy(MIN)
    for key, value in mutation.items():
        if value is None:
            raw.pop(key, None)
        else:
            raw[key] = value
    with pytest.raises(QuantumBlockError) as info:
        vq(raw)
    assert phrase in str(info.value)


def test_quantum_block_must_be_an_object():
    for bad in (None, [], "x", 3):
        with pytest.raises(QuantumBlockError):
            vq(bad)


def test_fraction_resolution_specific_overrides_wildcard():
    nb = vq({**MIN, "offload": {"fractions": {"*": 0.1, "memory_stream": {"G0": 0.4, "*": 0.2},
                                              "mixed_serving": 0.3}}})
    f = nb["offload"]["fractions"]
    assert f["tensor_training"] == {d: 0.1 for d in ("G0", "G1", "G2", "G3")}
    assert f["memory_stream"] == {"G0": 0.4, "G1": 0.2, "G2": 0.2, "G3": 0.2}
    assert f["mixed_serving"]["G2"] == 0.3


def test_hosts_are_excluded_from_fraction_table():
    nb = vq({**MIN, "package_hosts": {"device": "asic_decoder_rt", "dies": {"G3": {"max_devices": 4}}},
             "offload": {"fractions": {"*": 0.2}}})
    assert "G3" not in nb["offload"]["fractions"]["tensor_training"]


def test_architecture_file_must_stay_inside_submission_dir(tmp_path):
    (tmp_path / "a.json").write_text('{"n_qubits": 10}')
    ok = vq({"architecture_file": "a.json", "task": {"workload": "vqe_20q"}}, submission_dir=tmp_path)
    assert ok["architecture"]["n_qubits"] == 10
    for bad in ("../a.json", "/etc/passwd", "missing.json"):
        with pytest.raises(QuantumBlockError):
            vq({"architecture_file": bad, "task": {"workload": "vqe_20q"}}, submission_dir=tmp_path)


# ---------------------------------------------------------------------------------------------
# power-map offload scaling
# ---------------------------------------------------------------------------------------------
def _fractions(value):
    return {w: {d: value for d in ("G0", "G1", "G2", "G3")} for w in WORKLOADS}


def test_identity_modifiers_leave_data_untouched():
    mods = build_modifiers(SPEC, PORTABLE, fractions=_fractions(0.0), dynamic_power_fraction=1.0,
                           traffic_coupling=0.0, replaced_mode="redistributed", hosts={})
    assert is_identity(mods)
    spec2, portable2 = apply_modifiers(SPEC, PORTABLE, mods)
    assert spec2 == SPEC and portable2 == PORTABLE
    assert apply_modifiers(SPEC, PORTABLE, None)[1] == PORTABLE


def test_offload_scales_gpu_maps_by_exactly_the_declared_fraction():
    mods = build_modifiers(SPEC, PORTABLE, fractions=_fractions(0.25), dynamic_power_fraction=0.8,
                           traffic_coupling=0.0, replaced_mode="redistributed", hosts={})
    _, portable2 = apply_modifiers(SPEC, PORTABLE, mods)
    for w in WORKLOADS:
        for die in ("G0", "G1", "G2", "G3"):
            before = PORTABLE["workloads"][w]["per_die_total_w"][die]
            after = portable2["workloads"][w]["per_die_total_w"][die]
            assert after == pytest.approx(before * (1 - 0.8 * 0.25), rel=1e-6)
        for die in ("H0", "H1", "H2", "H3"):    # HBM base power untouched
            assert (portable2["workloads"][w]["power_maps_w"][die]
                    == PORTABLE["workloads"][w]["power_maps_w"][die])


def test_offload_keeps_the_map_shape_and_the_original_is_not_mutated():
    snapshot = copy.deepcopy(PORTABLE)
    mods = build_modifiers(SPEC, PORTABLE, fractions=_fractions(0.5), dynamic_power_fraction=1.0,
                           traffic_coupling=0.0, replaced_mode="dropped", hosts={})
    _, portable2 = apply_modifiers(SPEC, PORTABLE, mods)
    assert PORTABLE == snapshot
    import numpy as np
    a = np.array(PORTABLE["workloads"]["tensor_training"]["power_maps_w"]["G0"])
    b = np.array(portable2["workloads"]["tensor_training"]["power_maps_w"]["G0"])
    assert a.shape == b.shape == (16, 16)
    assert np.allclose(b, a * 0.5, atol=1e-8)


def test_traffic_coupling_scales_link_utilisation_and_clips_at_one():
    mods = build_modifiers(SPEC, PORTABLE, fractions=_fractions(0.4), dynamic_power_fraction=1.0,
                           traffic_coupling=0.5, replaced_mode="redistributed", hosts={})
    spec2, _ = apply_modifiers(SPEC, PORTABLE, mods)
    for w in WORKLOADS:
        for link, u in SPEC["workloads"][w]["link_utilization"].items():
            assert spec2["workloads"][w]["link_utilization"][link] == pytest.approx(u * 0.8)
    with pytest.raises(ModifierError):
        apply_modifiers(SPEC, PORTABLE, {"link_utilization_scale": {"mixed_serving": {"P0": -1}}})
    over = {"link_utilization_scale": {"memory_stream": {"P0": 3.0}}}
    spec3, _ = apply_modifiers(SPEC, PORTABLE, over)
    assert spec3["workloads"]["memory_stream"]["link_utilization"]["P0"] <= 1.0


def _hosts(watts=40.0, traffic=0.0):
    return {"G3": {"power_w": {w: watts for w in WORKLOADS}, "traffic_scale": traffic}}


def test_host_die_gets_uniform_declared_power_and_redistribution_conserves_gpu_load():
    mods = build_modifiers(SPEC, PORTABLE, fractions={w: {d: 0.0 for d in ("G0", "G1", "G2")} for w in WORKLOADS},
                           dynamic_power_fraction=1.0, traffic_coupling=0.0,
                           replaced_mode="redistributed", hosts=_hosts(40.0))
    _, portable2 = apply_modifiers(SPEC, PORTABLE, mods)
    import numpy as np
    for w in WORKLOADS:
        tot = portable2["workloads"][w]["per_die_total_w"]
        maps = portable2["workloads"][w]["power_maps_w"]
        assert tot["G3"] == pytest.approx(40.0, abs=1e-4)
        g3 = np.array(maps["G3"])
        assert np.allclose(g3, g3[0, 0])                        # uniform map
        orig = PORTABLE["workloads"][w]["per_die_total_w"]
        assert sum(tot[d] for d in ("G0", "G1", "G2")) == pytest.approx(sum(orig[d] for d in ("G0", "G1", "G2", "G3")), rel=1e-6)
    dropped = build_modifiers(SPEC, PORTABLE, fractions={w: {d: 0.0 for d in ("G0", "G1", "G2")} for w in WORKLOADS},
                              dynamic_power_fraction=1.0, traffic_coupling=0.0,
                              replaced_mode="dropped", hosts=_hosts(40.0))
    _, p3 = apply_modifiers(SPEC, PORTABLE, dropped)
    for d in ("G0", "G1", "G2"):
        assert p3["workloads"]["tensor_training"]["per_die_total_w"][d] == pytest.approx(
            PORTABLE["workloads"]["tensor_training"]["per_die_total_w"][d], rel=1e-6)


def test_host_traffic_scale_applies_to_its_links_only():
    mods = build_modifiers(SPEC, PORTABLE, fractions={w: {d: 0.0 for d in ("G0", "G1", "G2")} for w in WORKLOADS},
                           dynamic_power_fraction=1.0, traffic_coupling=0.0,
                           replaced_mode="dropped", hosts=_hosts(40.0, traffic=0.0))
    spec2, _ = apply_modifiers(SPEC, PORTABLE, mods)
    util = spec2["workloads"]["memory_stream"]["link_utilization"]
    assert util["P3"] == 0.0 and util["S3"] == 0.0
    assert util["P0"] == SPEC["workloads"]["memory_stream"]["link_utilization"]["P0"]


def test_package_power_accounting_matches_original_combined_heat():
    """No modifiers: power_budgets is exactly the original interconnect model."""
    budgets = power_budgets(SPEC, PORTABLE, BASE_LAYOUT, ROUTING)
    for w in WORKLOADS:
        heat = combined_heat(SPEC, w, PORTABLE["workloads"][w]["power_maps_w"], BASE_LAYOUT, ROUTING)
        assert budgets[w]["total_w"] == round(heat["total_w"], 6)
    assert budgets["tensor_training"]["total_w"] == pytest.approx(402.634765, abs=1e-5)  # HotSpot-run total (verified)


def test_offload_lowers_package_power_by_the_declared_amount():
    mods = build_modifiers(SPEC, PORTABLE, fractions=_fractions(0.1), dynamic_power_fraction=1.0,
                           traffic_coupling=0.0, replaced_mode="redistributed", hosts={})
    spec2, portable2 = apply_modifiers(SPEC, PORTABLE, mods)
    before = power_budgets(SPEC, PORTABLE, BASE_LAYOUT, ROUTING)
    after = power_budgets(spec2, portable2, BASE_LAYOUT, ROUTING)
    for w in WORKLOADS:
        gpu_w = sum(PORTABLE["workloads"][w]["per_die_total_w"][d] for d in ("G0", "G1", "G2", "G3"))
        assert before[w]["total_w"] - after[w]["total_w"] == pytest.approx(0.1 * gpu_w, rel=1e-5)


@needs_vendor
def test_modified_inputs_for_hotspot_equal_original_when_identity(tmp_path):
    """The inputs the original judge writes for HotSpot are byte-identical through the identity path."""
    from run_simulations import create_hotspot_files
    vendor = HILL / "vendor/HotSpot"
    a = tmp_path / "a"
    b = tmp_path / "b"
    create_hotspot_files(SPEC, PORTABLE, BASE_LAYOUT, ROUTING, a, 64, vendor)
    spec2, portable2 = apply_modifiers(SPEC, PORTABLE, {"die_power_scale": {w: {"G0": 1.0} for w in WORKLOADS}})
    create_hotspot_files(spec2, portable2, BASE_LAYOUT, ROUTING, b, 64, vendor)
    for name in [f"{w}.ptrace" for w in WORKLOADS] + ["chiplets.flp", "stack.lcf", "benchmark.config"]:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


@needs_vendor
def test_modified_inputs_for_hotspot_change_only_what_was_declared(tmp_path):
    from run_simulations import create_hotspot_files
    vendor = HILL / "vendor/HotSpot"
    mods = {"die_power_scale": {"memory_stream": {"G0": 0.5}}}
    spec2, portable2 = apply_modifiers(SPEC, PORTABLE, mods)
    a, b = tmp_path / "a", tmp_path / "b"
    create_hotspot_files(SPEC, PORTABLE, BASE_LAYOUT, ROUTING, a, 64, vendor)
    create_hotspot_files(spec2, portable2, BASE_LAYOUT, ROUTING, b, 64, vendor)
    assert (a / "memory_stream.ptrace").read_bytes() != (b / "memory_stream.ptrace").read_bytes()
    for w in WORKLOADS:
        if w != "memory_stream":
            assert (a / f"{w}.ptrace").read_bytes() == (b / f"{w}.ptrace").read_bytes()


# ---------------------------------------------------------------------------------------------
# end-to-end (no HotSpot): legality first, labelling, errors
# ---------------------------------------------------------------------------------------------
def _write(tmp_path, payload):
    (tmp_path / "submission.json").write_text(json.dumps(payload))
    return tmp_path


def test_illegal_layout_is_rejected_exactly_like_the_original_even_with_a_quantum_block(tmp_path):
    from eval_quantum import evaluate_submission
    from verify_submission import verify
    bad = json.loads((HILL / "examples/invalid/submission.json").read_text())
    original = verify(HILL / "examples/invalid/submission.json")
    report = evaluate_submission(_write(tmp_path, {**bad, "quantum": MIN}), no_thermal=True)
    assert not report["passed"] and report["status"] == "invalid_layout"
    assert report["reason"] == original["reason"]
    assert [m["value"] for m in report["metrics"]] == [1_000_000.0] * 3
    assert report["leaderboard_comparable"] is False and "NOT" in report["notice"].upper()


def test_other_unknown_top_level_keys_are_still_rejected(tmp_path):
    from eval_quantum import evaluate_submission
    report = evaluate_submission(_write(tmp_path, {"placements_mm": BASE_LAYOUT, "score": 0.1}), no_thermal=True)
    assert report["status"] == "invalid_layout" and "top-level keys" in report["reason"]


def test_missing_and_garbled_submission_files(tmp_path):
    from eval_quantum import evaluate_submission
    assert evaluate_submission(tmp_path, no_thermal=True)["status"] == "invalid_layout"
    (tmp_path / "submission.json").write_text("{nope")
    assert evaluate_submission(tmp_path, no_thermal=True)["status"] == "invalid_layout"


def test_no_quantum_block_is_the_classical_core(tmp_path):
    from eval_quantum import evaluate_submission
    report = evaluate_submission(_write(tmp_path, {"placements_mm": BASE_LAYOUT}), no_thermal=True)
    assert report["status"] == "ok_no_thermal" and report["quantum"] == {"present": False}
    assert report["modifiers"] is None
    pw = report["system"]["power_by_workload"]
    assert all(v["package_w_delta"] == 0 and v["quantum_side_outside_package_w"] == 0 for v in pw.values())
    assert report["leaderboard_comparable"] is False


def test_malformed_quantum_block_is_a_clear_error_not_a_crash(tmp_path):
    pytest.importorskip("scipy")
    from eval_quantum import evaluate_submission
    for bad in ({"architecture_example": "sc_rt_direct_100q", "task": {"workload": "vqe_50q"},
                 "offload": {"fractions": {"*": 7}}},
                {"architecture_example": "does_not_exist", "task": {"workload": "vqe_50q"}},
                {"architecture_example": "sc_rt_direct_100q", "task": {"workload": "no_such_task"}},
                {"architecture": {"modality": "unobtainium"}, "task": {"workload": "vqe_50q"}},
                {"architecture": {"modality": "superconducting", "scheme": "nope"}, "task": {"workload": "vqe_50q"}},
                "not an object"):
        report = evaluate_submission(_write(tmp_path, {"placements_mm": BASE_LAYOUT, "quantum": bad}), no_thermal=True)
        assert report["status"] == "invalid_quantum_block", bad
        assert not report["passed"] and report["leaderboard_comparable"] is False
        assert report["quantum"]["feasible"] is False and report["quantum"]["error"]


# ---------------------------------------------------------------------------------------------
# quantum feasibility paths (need scipy + quantum_arch)
# ---------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qe():
    pytest.importorskip("scipy")
    import quantum_eval
    try:
        quantum_eval.import_quantum()
    except quantum_eval.QuantumUnavailable as exc:
        pytest.skip(str(exc))
    return quantum_eval


def _outcome(qe, raw):
    tasks, examples = qe.catalog_names()
    return qe.evaluate_quantum(vq(raw, known_tasks=tasks, known_examples=examples))


def test_feasible_variational_task(qe):
    out = _outcome(qe, MIN)
    assert out.feasible and out.reasons == []
    assert out.task_runtime_s == pytest.approx(34.2, rel=0.02)
    assert out.summary["cryostat"]["fridge_units"] >= 1
    assert out.external_power_w == pytest.approx(out.summary["power_w"]["quantum_arch_total"])
    # honesty rule: no classical-alternative / advantage field is forwarded
    assert not {"energy_advantage", "classical_energy_j", "classical_ops"} & set(out.summary["task"])


def test_infeasible_fault_tolerant_task_is_reported_not_raised(qe):
    out = _outcome(qe, {"architecture_example": "sc_cryo_cmos_100k", "task": {"workload": "chemistry_small"}})
    assert not out.feasible
    assert out.task_runtime_s is None
    assert any("chemistry_small" in r for r in out.reasons)


def test_fridge_unit_and_power_limits_make_the_block_infeasible(qe):
    out = _outcome(qe, {**MIN, "architecture_example": "sc_cryo_cmos_100k", "limits": {"max_fridge_units": 5}})
    assert not out.feasible and any("limit is 5" in r for r in out.reasons)
    out = _outcome(qe, {**MIN, "limits": {"max_total_power_w": 100}})
    assert not out.feasible and any("exceeds limit" in r for r in out.reasons)


def test_decoder_bank_moves_to_package_hosts_and_leaves_room_temperature(qe):
    base = _outcome(qe, {**MIN, "architecture_example": "sc_cryo_cmos_100k"})
    hosted = _outcome(qe, {**MIN, "architecture_example": "sc_cryo_cmos_100k",
                           "package_hosts": {"device": "asic_decoder_rt",
                                             "dies": {"G3": {"max_devices": 8, "extra_power_w": 2.0}}}})
    pl = hosted.summary["decoder"]["placement"]
    assert pl["room_temperature"] == 0 and pl["package"]["G3"] == pl["total_devices"] >= 1
    host = hosted.host_power["G3"]
    assert host["active_w"] > host["idle_w"] >= 2.0
    # power moved, not created: quantum_arch total counts the bank once, split between package and outside
    total = hosted.summary["power_w"]
    assert total["hosted_on_package"] + total["outside_package"] == pytest.approx(total["quantum_arch_total"])
    assert total["hosted_on_package"] == pytest.approx(host["active_w"] - 2.0)
    assert base.summary["power_w"]["hosted_on_package"] == 0


def test_hosting_capacity_overflow_stays_at_room_temperature(qe):
    out = _outcome(qe, {**MIN, "architecture_example": "sc_cryo_cmos_100k",
                        "package_hosts": {"device": "asic_decoder_rt", "dies": {"G3": {"max_devices": 1}}}})
    pl = out.summary["decoder"]["placement"]
    assert pl["package"] == {"G3": 1} and pl["room_temperature"] == pl["total_devices"] - 1 > 0
    assert any("stay at room temperature" in w for w in out.warnings)


def test_allocate_devices_round_robin_and_caps(qe):
    assert qe.allocate_devices(5, {"G0": 2, "G3": 8}) == {"G0": 2, "G3": 3}
    assert qe.allocate_devices(100, {"G0": 2, "G3": 3}) == {"G0": 2, "G3": 3}
    assert qe.allocate_devices(0, {"G0": 2}) == {"G0": 0}


def test_cold_decoder_cannot_also_be_hosted_on_the_package(qe):
    raw = {**MIN, "architecture": {"modality": "superconducting", "scheme": "cryo_cmos_4k", "n_qubits": 1000,
                                   "qec": {"decoder_location": "4K"}},
           "package_hosts": {"device": "asic_decoder_rt", "dies": {"G3": {"max_devices": 8}}}}
    raw.pop("architecture_example")
    with pytest.raises(qe.QuantumEvalError):
        _outcome(qe, raw)


def test_full_report_for_hybrid_example_without_thermal(qe):
    from eval_quantum import evaluate_submission
    report = evaluate_submission(HILL / "examples/combined", no_thermal=True)
    assert report["status"] == "ok_no_thermal" and report["quantum"]["feasible"]
    assert report["leaderboard_comparable"] is False
    assert "NOT" in report["notice"].upper() and "leaderboard" in report["notice"]
    sysd = report["system"]
    assert sysd["task"]["energy_per_task_j"] > 0
    mixed = sysd["power_by_workload"]["mixed_serving"]
    assert mixed["total_electrical_w"] == pytest.approx(mixed["package_w_with_offload"]
                                                        + mixed["quantum_side_outside_package_w"])
    json.dumps(report, allow_nan=False)    # strictly JSON-safe


def test_infeasible_example_gets_penalty_status(qe):
    from eval_quantum import evaluate_submission
    report = evaluate_submission(HILL / "examples/infeasible_task", no_thermal=True)
    assert report["status"] == "hybrid_infeasible" and not report["passed"]
    assert report["quantum"]["feasible"] is False and report["quantum"]["infeasible_reasons"]


def test_original_examples_still_work_unchanged(qe):
    from eval_quantum import evaluate_submission
    report = evaluate_submission(HILL / "examples/baseline", no_thermal=True)
    assert report["passed"] and report["layout"]["legal"]
    assert not evaluate_submission(HILL / "examples/invalid", no_thermal=True)["passed"]


def test_hills_entry_point_shape(qe):
    from eval_quantum import eval as hills_eval
    out = hills_eval(HILL / "examples/invalid")
    assert out["passed"] is False and out["leaderboard_comparable"] is False
    assert [m["name"] for m in out["metrics"]] == ["score", "worst_gpu_c", "worst_hbm_c"]


def test_missing_container_runtime_gives_clear_status_and_no_fake_temperatures(tmp_path, monkeypatch):
    import eval_quantum as eq
    monkeypatch.setattr(eq, "docker_ready", lambda: (False, "the Docker daemon is not running"))
    report = eq.evaluate_submission(_write(tmp_path, {"placements_mm": BASE_LAYOUT}), runtime="docker")
    assert report["status"] == "thermal_unavailable" and not report["passed"]
    assert report["thermal"]["status"] == "unavailable" and "never estimated" in report["thermal"]["note"]
    assert "worst_gpu_c" not in report["classical"]
    assert report["system"].get("package") is None and report["leaderboard_comparable"] is False


# ---------------------------------------------------------------------------------------------
# real HotSpot (opt-in)
# ---------------------------------------------------------------------------------------------
@pytest.mark.skipif(os.environ.get("RUN_HOTSPOT") != "1", reason="set RUN_HOTSPOT=1 (needs Docker or Linux x86-64)")
def test_hotspot_baseline_reproduces_official_numbers_and_mirror_judge_agrees():
    pytest.importorskip("scipy")
    import eval_quantum as eq
    base = json.loads((HILL / "examples/baseline/submission.json").read_text())
    runtime = eq.choose_runtime("auto")
    results = eq.run_thermal(base, 64, [
        {"name": "original", "modifiers": None},
        {"name": "mirror", "modifiers": None, "force_mirror": True}], runtime)
    original, mirror = results["original"], results["mirror"]
    assert original["path"] == "original_judge" and mirror["path"] == "judge_modified"
    assert (original["worst_gpu_c"], original["worst_hbm_c"]) == (104.59, 97.68)
    assert original["score"] == 1.0
    assert (mirror["worst_gpu_c"], mirror["worst_hbm_c"], mirror["score"]) == (104.59, 97.68, 1.0)
    for w in WORKLOADS:
        assert mirror["workloads"][w]["per_die_peak_c"] == original["workloads"][w]["per_die_peak_c"]
