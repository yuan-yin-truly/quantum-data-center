"""Tests for dc_sim.dc_design (architecture v2) and its picture. Small user counts keep them fast."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from dc_sim import arch_picture, arch_study as A, dc_design as D

ROOT = Path(__file__).resolve().parents[1]
N = 2e5


@pytest.fixture(scope="module")
def ctx():
    p = D.load_params()
    return p, A._hw(p)


@pytest.fixture(scope="module")
def cell(ctx):
    p, hw = ctx
    return D.design_cell(p, hw, N, 1.0)


def test_class_shares_sum_to_one_and_calls_follow_densities(ctx):
    p, hw = ctx
    assert sum(c["share"] for c in p["design"]["classes"].values()) == pytest.approx(1.0)
    dem = D.demand(p, hw, N, 2.0)
    for nm, c in p["design"]["classes"].items():
        assert dem["classes"][nm]["calls"] == round(c["calls_per_bg_task"] * 2.0 * N * c["share"] * c["background_tasks"])


def test_every_call_is_accounted_for(cell):
    for k in ("gpu_only", "park", "hold"):
        r = cell[k]
        assert r["calls_on_qpu"] + r["calls_classical"] + r["calls_unserved"] == r["calls_day"]
        assert sum(t["on_qpu"] + t["classical"] + t["unserved"] for t in r["by_class"].values()) == r["calls_day"]


def test_reference_cannot_serve_calls_above_the_classical_cap(ctx, cell):
    p, _ = ctx
    cap = p["design"]["classical_max_module_hours"]
    ref = cell["gpu_only"]
    assert ref["calls_on_qpu"] == 0 and ref["qpus"] == 0
    assert ref["by_class"]["chemistry"]["unserved"] == ref["by_class"]["chemistry"]["calls"] > 0
    assert p["design"]["classical_fallback_module_hours"]["chemistry_small"] > cap


def test_qpu_service_admits_classes_by_value_density(cell):
    r = cell["park"]
    assert r["qpus"] > 0 and {"materials", "chemistry", "biology"} <= set(r["admitted"])
    assert cell["park"]["by_class"]["finance"]["on_qpu"] == 0          # classical cost 0.05 module-hours: never worth a QPU slot
    assert cell["park"]["by_class"]["materials"]["on_qpu"] > 0.9 * cell["park"]["by_class"]["materials"]["calls"]
    assert r["calls_unserved"] < 0.05 * cell["gpu_only"]["calls_unserved"]
    assert r["peak_facility_mw"] < cell["gpu_only"]["peak_facility_mw"]


def test_parking_and_holding_tie_at_this_call_volume(cell):
    assert abs(cell["park"]["usd_day"] - cell["hold"]["usd_day"]) < 0.01 * cell["hold"]["usd_day"]
    assert cell["park"]["ctxmem_tb"] > 0 and cell["hold"]["ctxmem_tb"] == 0


def test_cheap_classical_methods_mean_no_qpu(ctx):
    q = D.load_params({"design": {"classical_cost_scale": 0.02}})
    c = D.design_cell(q, A._hw(q), N, 1.0)
    assert c["best_mode"] == "gpu_only"


def test_picture_renders(ctx, tmp_path):
    p, hw = ctx
    res = {"params": p, "hw": {k: v for k, v in hw.items() if k != "gpu"}, "users": N, "scenarios": {"1.0": D.design_cell(p, hw, N, 1.0)}}
    f = tmp_path / "r.json"
    f.write_text(json.dumps(res, default=float))
    out = arch_picture.render(f, tmp_path / "pic.png")
    assert out.exists() and out.stat().st_size > 20_000


def test_cli_lists_dc_design():
    out = subprocess.run([sys.executable, "-m", "dc_sim", "--help"], cwd=ROOT, capture_output=True, text=True)
    assert "dc-design" in out.stdout
