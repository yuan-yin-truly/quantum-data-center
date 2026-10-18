"""Tests of the design loop (no HotSpot needed; the thermal side is a stub or the surrogate)."""

import json
import os
import random
from pathlib import Path

import pytest

from design_loop import integration as I
from design_loop.archive import Archive
from design_loop.config import load_config
from design_loop.evaluators.base import EvalResult, OK, UNAVAILABLE
from design_loop.evaluators.datacentre import DataCentreEvaluator
from design_loop.evaluators.quantum import QuantumSystemEvaluator
from design_loop.genes import Design, Gene, Space, SpaceError
from design_loop.hill import get_hill
from design_loop.loop import DesignLoop
from design_loop.objectives import Assessment, assess, dominates, nondominated_sort, pareto_front, scalar_scores

HILL = get_hill()
needs_hill = pytest.mark.skipif(HILL is None, reason="no hill directory")
needs_variant = pytest.mark.skipif(HILL is None or not HILL.supports_modifiers, reason="LOCAL quantum variant not present")


def small_cfg(**over):
    cfg = {"name": "t", "seed": 11, "budget": {"max_generations": 2, "max_designs": 60, "stagnation_generations": 9,
                                              "max_wallclock_s": 600},
           "population": {"candidates_per_generation": 8, "layout_search_per_generation": 0},
           "evaluators": {"package": {"mode": "stub", "hotspot": "never"}}, "final": {"hotspot_finalists": 0}}
    for k, v in over.items():
        cfg[k] = {**cfg.get(k, {}), **v} if isinstance(v, dict) else v
    return load_config(cfg)


# ---------------------------------------------------------------------------------------------------- genes
def test_canonicalisation_is_stable_and_hashable():
    sp = I.make_space()
    a = sp.canonicalize({"mode": "add", "n_qubits": 123456, "cryostat_scale": 17.3})
    b = sp.canonicalize({"cryostat_scale": 17, "n_qubits": 120000, "mode": "add"})
    assert a.id == b.id and a == b and hash(a) == hash(b)
    assert len({a, b}) == 1
    assert sp.canonicalize({"mode": "add", "n_qubits": 120000}).id != sp.canonicalize({"mode": "add", "n_qubits": 130000}).id


def test_gpu_only_collapses_quantum_genes():
    sp = I.make_space()
    a = sp.canonicalize({"mode": "gpu_only", "modality": "trapped_ion", "n_qubits": 5000, "offload_fraction": 0.5, "support_G1": True})
    b = sp.canonicalize({"mode": "gpu_only"})
    assert a.id == b.id
    assert a.genes["offload_fraction"] == 0.0 and not I.support_dies(a.genes)


def test_repair_rules():
    sp = I.make_space()
    d = sp.canonicalize({"mode": "add", "modality": "photonic", "scheme": "rt_direct", "code": "surface", "decoder": "mwpm"})
    assert d.genes["scheme"] in ("ambient", "fbqc_snspd") and d.genes["code"] == "fusion_network" and d.genes["decoder"] == "fusion_matching"
    d = sp.canonicalize({"mode": "add", "modality": "neutral_atom", "decoder_location": "4K"})
    assert d.genes["decoder_location"] == "RT"                      # no cryostat stage to host a 4 K decoder
    d = sp.canonicalize({"mode": "add", "decoder_location": "package"})
    assert d.genes["decoder_location"] == "RT" and not I.support_dies(d.genes)   # ADD has no support dies
    d = sp.canonicalize({"mode": "replace", "decoder_location": "package"})
    k = len(I.support_dies(d.genes))
    assert 1 <= k <= 3 and d.genes["decoder_location"] == "package"


def test_unknown_gene_and_bad_value_rejected():
    sp = I.make_space()
    with pytest.raises(SpaceError):
        sp.canonicalize({"nonsense": 1})
    with pytest.raises(SpaceError):
        sp.canonicalize({"modality": "unobtainium"})


def test_mutation_stays_in_bounds_and_choices():
    sp = I.make_space()
    rng = random.Random(3)
    d = sp.canonicalize({"mode": "replace"})
    for _ in range(300):
        d, changed = sp.mutate(d, rng)
        for k, v in d.genes.items():
            g = sp.genes.get(k)
            if g is None:
                continue
            if g.type in ("cat", "bool"):
                assert v in g.choices, (k, v)
            else:
                assert g.lo <= v <= g.hi, (k, v)
        assert d.genes["pue"] == sp.fixed["pue"]                     # fixed genes never move
    assert d.id == sp.recanonicalize(d).id                           # mutation output is already canonical


def test_space_roundtrip_json(tmp_path):
    sp = I.make_space()
    p = tmp_path / "space.json"
    p.write_text(json.dumps(sp.to_dict()))
    sp2 = Space.load(p)
    sp2.repair = sp.repair
    d = {"mode": "replace", "modality": "spin_silicon", "n_qubits": 50000}
    assert sp.canonicalize(d).id == sp2.canonicalize(d).id


def test_gene_validation():
    with pytest.raises(SpaceError):
        Gene("x", "cat", "a")
    with pytest.raises(SpaceError):
        Gene("x", "float", 1.0, lo=2.0, hi=1.0)
    with pytest.raises(SpaceError):
        Gene("x", "logfloat", 1.0, lo=0.0, hi=1.0)


def test_crossover_and_neighbours_are_canonical():
    sp = I.make_space()
    rng = random.Random(1)
    a, b = sp.canonicalize({"mode": "add"}), sp.canonicalize({"mode": "replace", "modality": "trapped_ion"})
    c, _ = sp.crossover(a, b, rng)
    assert c.id == sp.recanonicalize(c).id
    for nb, gene in sp.neighbours(a):
        assert nb.id != a.id and nb.id == sp.recanonicalize(nb).id


# ---------------------------------------------------------------------------------------------------- layout
@needs_hill
def test_layout_moves_are_legal():
    from design_loop import layout as L
    seeds = HILL.seed_layouts()
    assert "baseline_example" in seeds
    rng = random.Random(5)
    cur = seeds["baseline_example"]
    n = 0
    for _ in range(25):
        p = L.propose_layout(HILL, cur, rng, 1.5)
        if p:
            assert HILL.legality(p[0])[0]
            cur = p[0]
            n += 1
    assert n > 5


# ---------------------------------------------------------------------------------------------------- objectives
OBJ = [{"name": "a", "direction": "min"}, {"name": "b", "direction": "max"}]


def _asm(i, a, b, status="complete", tier="screened"):
    return Assessment(i, status, tier, {"a": a, "b": b})


def test_pareto_non_domination_property():
    rng = random.Random(0)
    pts = [(f"p{i}", {"a": rng.random(), "b": rng.random()}) for i in range(60)]
    fronts = nondominated_sort(pts, OBJ)
    ids = {i for f in fronts for i in f}
    assert ids == {i for i, _ in pts}                                # every point gets a rank
    vec = {i: (o["a"], -o["b"]) for i, o in pts}
    first = fronts[0]
    for i in first:
        assert not any(dominates(vec[j], vec[i]) for j in vec if j != i)
    for later in fronts[1:]:
        for i in later:
            assert any(dominates(vec[j], vec[i]) for j in first + [x for f in fronts for x in f])


def test_partial_and_infeasible_never_on_front():
    al = [_asm("good", 5.0, 1.0), _asm("better_but_partial", 1.0, 9.0, status="partial"),
          _asm("better_but_infeasible", 0.5, 9.5, status="infeasible"), _asm("worse", 6.0, 0.5)]
    assert pareto_front(al, OBJ) == ["good"]
    assert "better_but_partial" not in scalar_scores(al, OBJ)
    conf = _asm("c", 4.0, 1.0, tier="confirmed")
    assert pareto_front(al + [conf], OBJ, tier="confirmed") == ["c"]


def _ev(name, ok=True, **metrics):
    return EvalResult(name, OK if ok else UNAVAILABLE, "model", metrics=metrics)


def test_assess_flags_partial_when_an_evaluator_is_missing():
    ev = {"quantum": _ev("quantum", present=False), "package_legality": _ev("package_legality", legal=True),
          "package_surrogate": _ev("package_surrogate", worst_gpu_c=100.0, worst_hbm_c=90.0)}
    a = assess("x", ev)                                              # no data-centre result
    assert a.status == "partial" and any("datacentre" in m for m in a.missing)
    ev["datacentre"] = _ev("datacentre", ok=False)                   # unavailable
    assert assess("x", ev).status == "partial"
    ev["datacentre"] = _ev("datacentre", facility_j_per_work_unit=9000.0, capacity_rel=1.0, served_fraction=1.0)
    a = assess("x", ev)
    assert a.status == "complete" and a.tier == "screened"


def test_assess_constraints_make_infeasible_and_hotspot_confirms():
    q = EvalResult("quantum", OK, "real", metrics={"present": True}, violations=["task not feasible"])
    ev = {"quantum": q, "package_legality": _ev("package_legality", legal=True)}
    assert assess("x", ev).status == "infeasible"
    ok = {"quantum": _ev("quantum", present=False), "package_legality": _ev("package_legality"),
          "package_hotspot": EvalResult("package_hotspot", OK, "real", metrics={"worst_gpu_c": 90.0, "worst_hbm_c": 80.0,
                                                                              "support_peak_c": 130.0}),
          "datacentre": _ev("datacentre", facility_j_per_work_unit=1.0, capacity_rel=1.0, served_fraction=1.0)}
    a = assess("x", ok)
    assert a.status == "infeasible" and "support chiplet" in a.violations[0] and a.tier == "confirmed"


# ---------------------------------------------------------------------------------------------------- evaluators
def test_quantum_evaluator_matrix_and_gpu_only():
    sp = I.make_space()
    q = QuantumSystemEvaluator()
    r0 = q.evaluate(sp.canonicalize({"mode": "gpu_only"}))
    assert r0.metrics == {"present": False}
    d = sp.canonicalize({"mode": "add", "n_qubits": 300000, "cryostat_scale": 112, "task": "chemistry_small"})
    r = q.evaluate(d)
    assert r.ok and r.metrics["present"] and r.metrics["task_feasible"]
    assert set(r.per_workload) >= {"shor_rsa2048", "vqe_50q", "chemistry_small"}        # the whole quantum workload matrix
    assert all(w["advantage_claimed"] is False for w in r.per_workload.values())
    assert r.metrics["power_facility_w"] >= r.metrics["power_system_w"] >= r.metrics["power_module_w"] > 0
    assert q.evaluate(d).key == r.key


def test_quantum_infeasible_task_is_a_violation():
    sp = I.make_space()
    d = sp.canonicalize({"mode": "add", "n_qubits": 2000, "task": "shor_rsa2048"})
    r = QuantumSystemEvaluator().evaluate(d)
    assert r.ok and not r.metrics["task_feasible"] and r.violations


def test_datacentre_stand_in_fallback_is_labelled():
    sp = I.make_space()
    d = sp.canonicalize({"mode": "replace", "n_qubits": 300000, "cryostat_scale": 112, "task": "chemistry_small",
                         "offload_fraction": 0.3})
    q = QuantumSystemEvaluator().evaluate(d)
    r = DataCentreEvaluator(force_stand_in=True).evaluate(d, {"quantum": q})
    assert r.ok and r.source == "stub" and r.metrics["stand_in"] is True
    assert r.metrics["break_even_movable_share_capacity"] == pytest.approx(0.25)    # = fraction of GPUs removed
    base = DataCentreEvaluator(force_stand_in=True).evaluate(sp.canonicalize({"mode": "gpu_only"}))
    assert base.metrics["capacity_rel"] == 1.0


def test_datacentre_scheduler_adapter_when_present():
    ev = DataCentreEvaluator()
    if not ev.uses_scheduler:
        pytest.skip("quantum_arch.datacenter not present")
    sp = I.make_space()
    d = sp.canonicalize({"mode": "replace", "n_qubits": 300000, "cryostat_scale": 112, "task": "chemistry_small",
                         "offload_fraction": 0.3, "n_quantum_systems": 1})
    q = QuantumSystemEvaluator().evaluate(d)
    r = ev.evaluate(d, {"quantum": q})
    assert r.ok and r.source == "model" and r.metrics["capacity_rel"] is not None
    assert r.metrics["energy_ratio_vs_gpu_only"] > 0
    base = ev.evaluate(sp.canonicalize({"mode": "gpu_only"}))
    assert base.metrics["energy_ratio_vs_gpu_only"] == 1.0 and base.metrics["facility_j_per_work_unit"] > 0


def test_missing_hill_degrades_to_partial(tmp_path, monkeypatch):
    from design_loop import hill as H
    monkeypatch.setattr(H, "_HILL", None)                            # as if no hill directory existed
    from design_loop.pipeline import Pipeline
    cfg = load_config({"evaluators": {"package": {"hotspot": "never"}}})
    pipe = Pipeline(cfg)
    assert pipe.hill is None
    sp = I.make_space()
    d = sp.canonicalize({"mode": "gpu_only"})
    arch = Archive(tmp_path)
    arch.add_design(d)
    pipe.stage_a(d, arch)
    pipe.stage_b(d, arch)
    a = assess(d.id, arch.results(d.id))
    assert a.status == "partial" and a.missing and a.tier is None
    assert pareto_front([a]) == []


def test_hotspot_runner_reports_unavailable_never_fakes(monkeypatch):
    from design_loop import hotspot as HS
    monkeypatch.setattr(HS, "docker_bin", lambda: None)
    r = HS.HotspotRunner()
    ok, why = r.available()
    # Unavailable either because there is no pinned HotSpot binary (a clone without vendor/HotSpot) or
    # because there is no Docker; both must be said, neither may be faked.
    assert not ok and ("docker" in why.lower() or "hotspot" in why.lower())
    out = r.run_many([{"key": "k", "placements_mm": {}, "modifiers": None}])
    assert out["k"]["ok"] is False and "result" not in out["k"]


# ---------------------------------------------------------------------------------------------------- archive / loop
def test_archive_roundtrip_and_truncated_line(tmp_path):
    sp = I.make_space()
    d = sp.canonicalize({"mode": "add"})
    a = Archive(tmp_path)
    assert a.add_design(d, [], "seed") and not a.add_design(d)       # second add is a no-op
    a.add_eval(d.id, EvalResult("quantum", OK, "model", metrics={"x": 1}, key="k1"))
    a.close()
    with (tmp_path / "archive.jsonl").open("a") as fh:
        fh.write('{"t": "eval", "id": "zzz", "resu')                 # simulated crash mid-write
    b = Archive(tmp_path)
    assert d.id in b and b.results(d.id)["quantum"].metrics["x"] == 1
    assert b.cached("quantum", "k1") is not None and b.cached("quantum", "nope") is None


def test_loop_end_to_end_with_stub_package(tmp_path):
    loop = DesignLoop(small_cfg(), tmp_path / "run", log=lambda *a: None)
    state = loop.run()
    assert state["generation_done"] == 1
    al = loop.assess_all()
    modes = {loop.archive.designs[i].genes["mode"] for i in al}
    assert modes == {"gpu_only", "add", "replace"}
    assert any(a.status == "complete" for a in al.values())
    fr = loop.fronts(al)
    assert fr["screening"] and not fr["confirmed"]                    # stub thermal is never "confirmed"
    for did in fr["screening"]:
        assert al[did].eligible
    # the quantum workload matrix is stored for every quantum design
    for did, a in al.items():
        if loop.archive.designs[did].genes["mode"] != "gpu_only" and a.status != "partial":
            q = loop.archive.results(did).get("quantum")
            assert q is not None and (q.per_workload or q.violations)
    # provenance
    for did in al:
        meta = loop.archive.meta[did]
        assert meta["operator"] and meta["generation"] in (0, 1)
    assert (tmp_path / "run" / "config.json").is_file() and (tmp_path / "run" / "generations.jsonl").is_file()
    cfg = json.loads((tmp_path / "run" / "config.json").read_text())
    assert cfg["leaderboard_comparable"] is False


def test_determinism_by_seed(tmp_path):
    ids = []
    for name, seed in (("a", 11), ("b", 11), ("c", 12)):
        loop = DesignLoop(small_cfg(seed=seed), tmp_path / name, log=lambda *a: None)
        loop.run()
        ids.append(list(loop.archive.designs))
    assert ids[0] == ids[1]
    assert ids[0] != ids[2]


def test_resume_equals_uninterrupted_run(tmp_path):
    full = DesignLoop(small_cfg(budget={"max_generations": 3}), tmp_path / "full", log=lambda *a: None)
    full.run()
    part = DesignLoop(small_cfg(budget={"max_generations": 2}), tmp_path / "part", log=lambda *a: None)
    part.run()
    n_evals_before = part.archive.n_lines
    cfg2 = small_cfg(budget={"max_generations": 3})
    resumed = DesignLoop(cfg2, tmp_path / "part", log=lambda *a: None)
    assert resumed.state["generation_done"] == 1                     # picks up where it stopped
    resumed.run()
    assert list(resumed.archive.designs) == list(full.archive.designs)
    assert resumed.archive.n_lines > n_evals_before
    # nothing evaluated twice: every design has exactly one result per evaluator in the file
    seen = {}
    for line in (tmp_path / "part" / "archive.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r["t"] == "eval":
            k = (r["id"], r["result"]["evaluator"])
            assert k not in seen
            seen[k] = 1


def test_resume_after_crash_mid_generation(tmp_path):
    cfg = small_cfg(budget={"max_generations": 2})
    ref = DesignLoop(cfg, tmp_path / "ref", log=lambda *a: None)
    ref.run()
    crashed = DesignLoop(cfg, tmp_path / "crash", log=lambda *a: None)
    orig = crashed.pipe.stage_b
    calls = {"n": 0}

    def boom(d, archive):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("simulated crash")
        return orig(d, archive)

    crashed.pipe.stage_b = boom
    with pytest.raises(RuntimeError):
        crashed.run()
    again = DesignLoop(cfg, tmp_path / "crash", log=lambda *a: None)
    assert again.state["generation_done"] == -1                      # generation 0 never finished
    again.run()
    assert list(again.archive.designs) == list(ref.archive.designs)  # same designs as the uninterrupted run


def test_budget_stops(tmp_path):
    loop = DesignLoop(small_cfg(budget={"max_generations": 9, "max_designs": 10}), tmp_path / "r", log=lambda *a: None)
    st = loop.run()
    assert st["stop_reason"] == "design budget"
    assert len(loop.archive.designs) <= 10 + 8


def test_report_files_and_flag(tmp_path):
    from design_loop.report import write_report
    loop = DesignLoop(small_cfg(), tmp_path / "r", log=lambda *a: None)
    loop.run()
    out = write_report(tmp_path / "r")
    for f in ("report.md", "results.json", "matrix.json", "designs.csv", "pareto.png", "convergence.png"):
        assert (out / f).is_file(), f
    res = json.loads((out / "results.json").read_text())
    assert res["leaderboard_comparable"] is False
    md = (out / "report.md").read_text()
    assert "leaderboard_comparable: false" in md and "NOT RUN in this run" in md   # no HotSpot -> no claim
    m = json.loads((out / "matrix.json").read_text())
    assert m["leaderboard_comparable"] is False and m["matrix"]


# ---------------------------------------------------------------------------------------------------- package + surrogate
@needs_variant
def test_package_modifiers_and_surrogate_monotone():
    from design_loop.evaluators.package import PackageModel, PackageSurrogateEvaluator, PackageLegalityEvaluator
    from design_loop.surrogate import ThermalSurrogate
    sp = I.make_space()
    model = PackageModel(HILL)
    q = QuantumSystemEvaluator()
    base = sp.canonicalize({"mode": "gpu_only"}, HILL.seed_layouts()["baseline_example"])
    off = sp.canonicalize({"mode": "add", "offload_fraction": 0.4}, HILL.seed_layouts()["baseline_example"])
    host = sp.canonicalize({"mode": "replace", "decoder_location": "package", "offload_fraction": 0.1, "devices_per_support_die": 8},
                           HILL.seed_layouts()["baseline_example"])
    assert model.modifiers(base, None)[0] is None
    mods, info = model.modifiers(off, q.evaluate(off))
    assert mods and not mods["replaced_dies"]
    mods_h, info_h = model.modifiers(host, q.evaluate(host))
    assert mods_h["replaced_dies"] == I.support_dies(host.genes)
    assert PackageLegalityEvaluator(model).evaluate(base).metrics["legal"]
    sur = PackageSurrogateEvaluator(model)
    t0 = sur.evaluate(base, {})
    t1 = sur.evaluate(off, {"quantum": q.evaluate(off)})
    assert t0.ok and t0.source == "surrogate" and t0.metrics["worst_gpu_c"] > 25
    assert t1.metrics["worst_gpu_c"] < t0.metrics["worst_gpu_c"]      # offloading work unloads the GPUs
    assert set(t0.per_workload) == set(HILL.workloads)                 # all five hill workloads
    # keys: identical thermal problems share a cache key, different ones do not
    assert sur.cache_key(base, {}) == sur.cache_key(base, {})
    assert sur.cache_key(base, {}) != sur.cache_key(off, {"quantum": q.evaluate(off)})


@needs_hill
def test_illegal_layout_is_a_violation():
    from design_loop.evaluators.package import PackageLegalityEvaluator, PackageModel
    sp = I.make_space()
    lay = {d: [1.0, 1.0] for d in HILL.DIES}                          # everything on top of each other
    d = sp.canonicalize({"mode": "gpu_only"}, lay)
    r = PackageLegalityEvaluator(PackageModel(HILL)).evaluate(d)
    assert r.ok and not r.metrics["legal"] and r.violations
    a = assess(d.id, {"package_legality": r, "quantum": _ev("quantum", present=False)})
    assert a.status == "infeasible"


@pytest.mark.skipif(not os.environ.get("RUN_HOTSPOT"), reason="set RUN_HOTSPOT=1 (needs Docker and the pinned image)")
def test_real_hotspot_reproduces_the_baseline():
    from design_loop.evaluators.package import PackageHotspotEvaluator, PackageModel
    sp = I.make_space()
    d = sp.canonicalize({"mode": "gpu_only"}, HILL.seed_layouts()["baseline_example"])
    r = PackageHotspotEvaluator(PackageModel(HILL)).evaluate(d, {})
    assert r.ok and r.source == "real"
    assert r.metrics["worst_gpu_c"] == pytest.approx(104.59, abs=0.01)
    assert r.metrics["worst_hbm_c"] == pytest.approx(97.68, abs=0.01)
