"""Tests for dc_sim: caps, determinism, policies, quantum feasibility, API == CLI, task file round trip, budget/power checks."""

import copy
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

from dc_sim import api, costs, presets, qfeas, server
from dc_sim.config import PRESET_DIR
from dc_sim.engine import Engine
from dc_sim.fleet import Fleet
from dc_sim.scheduler import POLICIES
from dc_sim.tasks import TaskError, load_taskset, normalise_taskset, save_taskset

ROOT = Path(__file__).resolve().parents[1]


def _tiny_stress() -> dict:
    """Small scenario with a power-cap drop, a node failure, a demand surge and a mix of tasks (3 simulated hours)."""
    ts = load_taskset("ui_demo")
    ts["name"] = "tiny_stress"
    ts["case"] = "mix"
    ts["demand_scale"] = 1.1
    ts["events"] = [{"t": 1800, "type": "site_power_cap", "site": "eu_north", "mw": 40},
                    {"t": 2400, "type": "node_failure", "site": "us_east", "node_type": "gpu_rack", "count": 4, "duration_s": 3600},
                    {"t": 3000, "type": "demand_surge", "multiplier": 1.4, "duration_s": 3600},
                    {"t": 3600, "type": "qpu_calibration", "site": "apac", "node_type": "qpu_cat40k", "duration_s": 1800}]
    return normalise_taskset(ts)


@pytest.fixture(scope="module")
def stress_runs():
    ts = _tiny_stress()
    return {p: api.run_policy(None, copy.deepcopy(ts), p) for p in POLICIES}


def test_power_caps_never_exceeded(stress_runs):
    for p, e in stress_runs.items():
        n = len(e.fleet.sites)
        for row in e.hist:
            for i in range(n):
                fac, cap = row[1 + 3 * i], row[2 + 3 * i]
                assert fac <= cap * 1.0 + 1.0, (p, row[0], i, fac, cap)
        m = e.metrics()
        assert m["power_cap"]["never_exceeded"], p
        assert m["power_cap"]["sum_caps_mw"] <= 500.0 + 1e-9


def test_determinism_by_seed():
    a = api.simulate(None, "ui_demo", "batch", seed=3)
    b = api.simulate(None, "ui_demo", "batch", seed=3)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    e1, e2 = Engine(None, "ui_demo", "greedy", seed=5), Engine(None, "ui_demo", "greedy", seed=5)
    e1.run(); e2.run()
    assert e1.decisions == e2.decisions and e1.hist == e2.hist


def test_seed_changes_quantum_outcomes():
    ts = load_taskset("ui_demo")
    outs = {s: Engine(None, ts, "batch", seed=s) for s in range(6)}
    atts = set()
    for s, e in outs.items():
        e.run()
        atts.add(sum(u.attempts_used for u in e.units.values()))
    assert len(atts) >= 2        # the seeded attempt draws differ between seeds


def test_gpu_only_never_uses_qpus(stress_runs):
    e = stress_runs["gpu_only"]
    assert all(d.get("route") != "quantum" for d in e.decisions if d["action"] == "assign")
    assert e.metrics()["quantum"]["on_qpu"] == 0
    assert all(n.qpu.busy_s_total == 0 and not n.qpu.queue for n in e.fleet.all_nodes() if n.qpu)


def test_infeasible_quantum_never_placed(stress_runs):
    ts = normalise_taskset({"name": "inf", "horizon_s": 7200, "case": "C", "demand_scale": 0.1, "tasks": [
        {"id": "f1", "arrival_s": 0, "type": "quantum_fault_tolerant", "priority": 3, "deadline_s": 7000, "quantum": {"kind": "gate", "workload": "femoco_thc"}},
        {"id": "s1", "arrival_s": 0, "type": "quantum_fault_tolerant", "priority": 3, "deadline_s": 7000, "quantum": {"kind": "gate", "workload": "shor_rsa2048"}},
        {"id": "ok", "arrival_s": 0, "type": "quantum_fault_tolerant", "priority": 3, "deadline_s": 7000, "quantum": {"kind": "gate", "workload": "chemistry_small"}}]})
    for pol in POLICIES:
        e = api.run_policy(None, copy.deepcopy(ts), pol)
        assert e.task_rec["f1"]["state"] == "rejected" and e.task_rec["s1"]["state"] == "rejected"
        assert "qubits" in e.task_rec["f1"]["reason"] or "no feasible" in e.task_rec["f1"]["reason"]
    # on every policy that uses QPUs, every quantum assignment is feasible on that node type
    for pol, e in stress_runs.items():
        for u in e.units.values():
            if u.route == "quantum" and u.node:
                node = e._nidx[u.node]
                assert qfeas.quantum_check(e.fleet.node_cfg[node.type_key], u.q)["feasible"]
    # direct check: the 40k-qubit machines cannot run FeMoco
    f = Fleet.load()
    for n in f.all_nodes():
        if n.qpu and n.qpu.kind == "gate":
            assert not qfeas.quantum_check(f.node_cfg[n.type_key], {"kind": "gate", "workload": "femoco_thc"})["feasible"]


def test_decision_reasons_present(stress_runs):
    for p, e in stress_runs.items():
        acts = [d for d in e.decisions if d["action"] in ("assign", "defer", "reject")]
        assert acts
        assert all(isinstance(d["reason"], str) and len(d["reason"]) > 10 for d in acts), p


def test_hybrid_pipeline_stages_in_order(stress_runs):
    e = stress_runs["batch"]
    for tid, us in e.units_of.items():
        if len(us) > 1:
            done = [u for u in us if u.state == "done"]
            for a, b in zip(done, done[1:]):
                assert a.end_t <= b.start_t + 1e-6


def test_task_file_round_trip(tmp_path):
    for name in ("ui_demo", "failure_overload_stress", "qpu_contention_burst"):
        ts = load_taskset(name)
        p = tmp_path / f"{name}.json"
        save_taskset(ts, p)
        assert load_taskset(p) == ts
    with pytest.raises(TaskError):
        normalise_taskset({"tasks": [{"type": "nonsense"}]})
    with pytest.raises(TaskError):
        normalise_taskset({"tasks": [{"type": "quantum_fault_tolerant", "quantum": {"kind": "gate", "workload": "nope"}}]})


def test_all_presets_valid():
    for p in PRESET_DIR.glob("*.json"):
        ts = load_taskset(p)
        assert ts["tasks"], p


def test_budget_and_power_feasibility():
    f = Fleet.load()
    b = costs.budget_power_check(f)
    assert b["power_ok"] and b["sum_site_caps_mw"] <= 500.0 + 1e-9
    assert b["budget_ok"] and b["total_5y_usd"] <= 30e9
    spec = f.to_dict()
    spec["sites"][0]["power_cap_mw"] += 100
    bad = costs.budget_power_check(Fleet(spec))
    assert not bad["power_ok"]
    spec = f.to_dict()
    spec["sites"][0]["nodes"]["gpu_rack"] = 20000
    assert not costs.budget_power_check(Fleet(spec))["budget_ok"]


def test_reference_fleet_has_no_quantum_and_equal_power():
    f = Fleet.load()
    r = f.without_quantum()
    assert not r.has_quantum()
    assert sum(s.cap_w for s in r.site_list) == sum(s.cap_w for s in f.site_list)
    for s in r.site_list:
        assert r.peak_facility_w(s) <= s.cap_w * 1.02


def test_policies_differ_under_overload(stress_runs):
    m = {p: e.metrics() for p, e in stress_runs.items()}
    assert m["batch"]["users_slo_pct"] >= m["fifo"]["users_slo_pct"] - 1e-9


# ---------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def live():
    srv, sess = server.make_server(0)
    assert srv.server_address[0] == "127.0.0.1"          # localhost only
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    port = srv.server_address[1]

    def call(path, body=None):
        url = f"http://127.0.0.1:{port}{path}"
        if body is None:
            return json.load(urllib.request.urlopen(url))
        r = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(r))
    yield call, port
    srv.shutdown()
    srv.server_close()


def _drive_to_end(call):
    st = call("/api/state")
    while not st["done"]:
        st = call("/api/step", {"n": 200})
    return st


def test_api_equals_cli_and_simulate(live, tmp_path):
    call, _ = live
    for pol in ("batch", "fifo"):
        call("/api/reset", {"preset": "ui_demo", "policy": pol})
        st = _drive_to_end(call)
        trace = call("/api/trace")
        m_api = trace["metrics"]
        m_sim = api.simulate(None, "ui_demo", pol)
        out = tmp_path / pol
        r = subprocess.run([sys.executable, "-m", "dc_sim", "run", "--tasks", "ui_demo", "--policy", pol, "--out", str(out), "--quiet"], cwd=ROOT,
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stderr
        m_cli = json.loads((out / "result.json").read_text())["metrics"]
        a, b, c = (json.dumps(x, sort_keys=True) for x in (m_api, m_sim, m_cli))
        assert a == b == c, pol
        assert abs(st["metrics"]["cost"]["total_usd_per_day"] - m_sim["cost"]["total_usd_per_day"]) < 1e-6


def test_api_inject_matches_file_run(live):
    call, _ = live
    call("/api/reset", {"preset": "ui_demo", "policy": "greedy"})
    call("/api/step", {"n": 10})
    r = call("/api/inject", {"spec": {"type": "quantum_fault_tolerant", "count": 3, "workload": "chemistry_small", "slo_h": 2}})
    assert r["n"] == 3
    r2 = call("/api/inject", {"tasks": [{"type": "agent_job", "size": {"steps": 100}, "priority": 4}]})
    st = call("/api/step", {"n": 5})
    assert any(d["action"] == "assign" for d in st["recent"])
    _drive_to_end(call)
    exported = call("/api/taskset")
    assert len(exported["tasks"]) == 20 + 4
    m_api = call("/api/trace")["metrics"]
    m_file = api.simulate(None, exported, "greedy")
    assert json.dumps(m_api, sort_keys=True) == json.dumps(m_file, sort_keys=True)


def test_api_basic_cycle_and_policy_switch(live):
    call, port = live
    meta = call("/api/meta")
    assert {"fifo", "greedy", "batch", "gpu_only"} == {p["id"] for p in meta["policies"]}
    assert len(meta["layout"]["sites"]) == 6
    call("/api/reset", {"preset": "ui_demo"})
    call("/api/policy", {"name": "fifo"})
    st = call("/api/step", {"n": 3})
    assert st["policy"] == "fifo" and st["t"] == 180.0
    d = call(f"/api/node?id={meta['layout']['sites'][0]['nodes'][0][0]}")
    assert d["id"]
    html = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode()
    assert "DC Sim" in html
    with pytest.raises(Exception):
        call("/api/inject", {"tasks": [{"type": "bogus"}]})
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(req)


def test_replay_html_is_self_contained():
    from dc_sim import replay
    html = replay.build_html(None, "ui_demo", "greedy", None, 30)
    assert "window.DC_REPLAY=" in html and "<link rel=\"stylesheet\"" not in html and 'src="/app.js"' not in html


def test_cli_commands_run(tmp_path):
    for args in (["presets"], ["list"], ["fleet"], ["compare", "--tasks", "ui_demo", "--out", str(tmp_path)]):
        r = subprocess.run([sys.executable, "-m", "dc_sim", *args], cwd=ROOT, capture_output=True, text=True, timeout=600)
        assert r.returncode == 0, (args, r.stderr[-800:])
    assert (tmp_path / "ui_demo" / "compare.md").exists()
