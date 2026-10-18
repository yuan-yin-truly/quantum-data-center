"""Tests for dc_sim.arch_study (use case B node-composition study). Small user counts keep them fast."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from dc_sim import arch_study as A

ROOT = Path(__file__).resolve().parents[1]
N = 2e5


@pytest.fixture(scope="module")
def ctx():
    p = A.load_params()
    return p, A._hw(p)


def test_gpu_sizing_sustains_average_load_and_grows_with_extra_work(ctx):
    p, hw = ctx
    dem = A._demand(p, hw, N)
    g0 = A.size_gpus(p, hw, dem, 0.0)
    assert g0["modules"] * p["case_b"]["rho"] >= dem["int_mod"] + dem["bg_mod"] - 1e-9     # no endless backlog
    assert g0["util_peak"] <= p["case_b"]["rho"] + 1e-9
    g1 = A.size_gpus(p, hw, dem, 200.0)
    assert g1["modules"] > g0["modules"] and g1["mean_kw"] > g0["mean_kw"]


def test_call_simulation_conserves_calls_and_respects_capacity(ctx):
    p, hw = ctx
    for topo, nl, cp in (("specialised", 0, 3), ("integrated", 3, 0), ("mix", 2, 2)):
        r = A.simulate_calls(hw, p, 500, topo, nl, cp, seed=1)
        assert r["qpu"] + r["overflow"] == 500
        assert all(b <= 86400 + 1e-6 for b in r["busy_by_qpu"])
        assert len(r["wait"]) == r["qpu"] and (r["wait"] <= p["quantum"]["max_wait_s"] + 1e-6).all()
    none = A.simulate_calls(hw, p, 500, "specialised", 0, 0, seed=1)
    assert none["overflow"] == 500 and none["qpu"] == 0
    a = A.simulate_calls(hw, p, 300, "mix", 2, 2, seed=7)
    b = A.simulate_calls(hw, p, 300, "mix", 2, 2, seed=7)
    assert a["busy_by_qpu"] == b["busy_by_qpu"] and np.array_equal(a["wait"], b["wait"])


def test_no_eligible_work_means_no_qpu_is_ever_built(ctx):
    p, hw = ctx
    cell = A.study_cell(p, hw, N, 0.0, 30.0)
    assert cell["best_topology"] == "gpu_only" and set(cell) >= {"gpu_only", "best_topology"} and "specialised" not in cell


def test_cheap_classical_calls_stay_classical_and_expensive_ones_go_to_qpus(ctx):
    p, hw = ctx
    cheap = A.study_cell(p, hw, N, 1e-3, 0.1)
    assert cheap["best_topology"] == "gpu_only"                  # a 270 kW QPU does not pay for 0.1 module-hour calls
    dear = A.study_cell(p, hw, N, 1e-3, 100.0)
    best = dear[dear["best_topology"]]
    assert dear["best_topology"] != "gpu_only" and best["usd_day"] < dear["gpu_only"]["usd_day"]
    assert best["calls_on_qpu"] > 0.8 * best["calls_day"]
    assert best["mean_facility_mw"] < dear["gpu_only"]["mean_facility_mw"]


def test_server_scale_integration_is_far_more_expensive(ctx):
    p, hw = ctx
    cell = A.study_cell(p, hw, N, 1e-3, 100.0)
    assert cell["integrated_16"]["qpus"] > 10 * cell["specialised"]["qpus"]
    assert cell["integrated_16"]["usd_day"] > 3 * cell["specialised"]["usd_day"]


def test_latency_penalty_favours_node_local_qpus(ctx):
    p, hw = ctx
    slow = A.load_params({"quantum": {"iterations_per_call": 1_000_000}})
    cell = A.study_cell(slow, A._hw(slow), N, 1e-3, 100.0)
    assert cell["integrated"]["usd_day"] < cell["specialised"]["usd_day"]


def test_energy_shares_add_up(ctx):
    p, hw = ctx
    r = A.evaluate(p, hw, N, 1e-3, 100.0, "specialised", 0, 4)
    mult = (1 + hw["net"]) * hw["pue"]
    assert r["mean_facility_mw"] == pytest.approx((r["gpu_mean_mw"] + r["cpu_mean_mw"] + r["qpu_mean_mw"]) * mult, rel=1e-9)
    assert r["peak_facility_mw"] >= r["mean_facility_mw"] - 1e-9


def test_cli_lists_arch_study():
    out = subprocess.run([sys.executable, "-m", "dc_sim", "--help"], cwd=ROOT, capture_output=True, text=True)
    assert "arch-study" in out.stdout
