"""Preset task sets (written to ``dc_sim/presets/*.json``): deterministic generators, so the files can be regenerated.

Every number here is an ASSUMPTION chosen to make the scenario instructive, not an observed workload.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .config import PRESET_DIR, stable_seed
from .tasks import normalise_taskset, save_taskset

REGIONS = ["americas", "emea", "apac"]


def _rng(name: str) -> np.random.Generator:
    return np.random.default_rng(stable_seed("preset", name))


def _agent(i, t, rng, region, prio=3, slo=3 * 3600, steps=None):
    return {"id": f"agent{i:03d}", "arrival_s": float(t), "type": "agent_job", "case": "B", "priority": prio, "deadline_s": float(t + slo),
            "home_region": region, "data_gb": float(rng.integers(2, 40)),
            "size": {"steps": int(steps or rng.integers(150, 600)), "prefill_tokens_per_step": 6000, "decode_tokens_per_step": 700,
                     "tool_wait_s_per_step": float(rng.integers(3, 8)), "modules": 8, "ctx_gb": float(rng.integers(40, 140))}}


def _know(i, t, rng, region, prio=3, slo=8 * 3600):
    return {"id": f"know{i:03d}", "arrival_s": float(t), "type": "knowledge_job", "case": "C", "priority": prio, "deadline_s": float(t + slo),
            "home_region": region, "data_gb": float(rng.integers(20, 200)),
            "size": {"module_hours": float(rng.integers(20, 200)), "modules": int(rng.choice([32, 64])), "ctx_gb": float(rng.integers(10, 60))}}


def _llm(i, t, rng, region, kind, prio=2, slo=2 * 3600):
    if kind == "prefill":
        return {"id": f"llmp{i:03d}", "arrival_s": float(t), "type": "llm_prefill_batch", "case": "A", "priority": prio, "deadline_s": float(t + slo),
                "home_region": region, "data_gb": float(rng.integers(5, 60)),
                "size": {"requests": int(rng.integers(2, 10)) * 100_000, "prefill_tokens": int(rng.choice([2000, 4000, 8000])), "max_modules": 64}}
    return {"id": f"llmd{i:03d}", "arrival_s": float(t), "type": "llm_decode_batch", "case": "A", "priority": prio, "deadline_s": float(t + slo),
            "home_region": region, "data_gb": float(rng.integers(1, 20)),
            "size": {"requests": int(rng.integers(2, 10)) * 100_000, "decode_tokens": int(rng.choice([500, 1000, 2000])), "max_modules": 64}}


def _qtask(i, t, rng, region, wl, prio=3, slo=6 * 3600, repeats=1, ty=None, min_success=0.95):
    ty = ty or {"vqe_50q": "quantum_variational", "vqe_20q": "quantum_variational", "chemistry_small": "quantum_fault_tolerant",
                "femoco_thc": "quantum_fault_tolerant", "shor_rsa2048": "quantum_fault_tolerant",
                "qla_scalar_explicit_1m": "quantum_linear_algebra", "qla_full_vector_1m": "quantum_linear_algebra"}[wl]
    return {"id": f"q{i:03d}", "arrival_s": float(t), "type": ty, "case": "Q", "priority": prio, "deadline_s": float(t + slo), "home_region": region,
            "data_gb": float(rng.integers(1, 20)), "min_success": min_success,
            "quantum": {"kind": "gate", "workload": wl, "repeats": repeats, "prep_s": 120, "post_s": 120, "mapping_quality": 0.9, "max_attempts": 2}}


def _qopt(i, t, rng, region, prio=3, slo=1800):
    return {"id": f"qo{i:03d}", "arrival_s": float(t), "type": "quantum_optimisation", "case": "Q", "priority": prio, "deadline_s": float(t + slo),
            "home_region": region, "data_gb": float(rng.integers(1, 5)), "min_success": 0.9,
            "quantum": {"kind": "annealer", "p_success_per_read": float(rng.choice([0.002, 0.005, 0.01])), "confidence": 0.99, "prep_s": 5.0,
                        "post_s": 2.0, "mapping_quality": 0.8, "max_attempts": 2},
            "classical_fallback": {"module_hours": float(rng.choice([0.03, 0.2, 1.0])), "modules": 8, "accuracy_ok": True,
                                   "note": "ASSUMPTION: classical heuristic/exact solver on GPUs at the same target quality"}}


def _pipeline(i, t, rng, region, wl="chemistry_small", prio=3, slo=8 * 3600, prep_h=None, out_gb=None):
    out = float(out_gb if out_gb is not None else rng.integers(40, 400))
    return {"id": f"hyb{i:03d}", "arrival_s": float(t), "type": "hybrid_pipeline", "case": "Q", "priority": prio, "deadline_s": float(t + slo),
            "home_region": region, "data_gb": float(rng.integers(20, 150)),
            "stages": [
                {"name": "GPU prep (integrals, active space)", "kind": "gpu", "module_hours": float(prep_h or rng.integers(4, 30)), "modules": 32, "ctx_gb": 0, "out_gb": out},
                {"name": "QPU (" + wl + ")", "kind": "quantum", "out_gb": float(rng.integers(5, 40)),
                 "quantum": {"kind": "gate", "workload": wl, "repeats": 1, "prep_s": 60, "post_s": 60, "mapping_quality": 0.9, "max_attempts": 2}},
                {"name": "GPU postprocess (analysis)", "kind": "gpu", "module_hours": float(rng.integers(2, 12)), "modules": 16, "ctx_gb": 0, "out_gb": 1.0}]}


def build(name: str) -> dict:
    rng = _rng(name)
    base = {"format": "dc_sim.tasks/1", "name": name, "seed": 1, "tasks": [], "events": []}
    tasks: list[dict] = []
    if name == "ui_demo":
        base.update(description="Small, fast scenario for the visual app: 3 simulated hours, light fluid traffic (case C scaled down), a handful of tasks of every kind.",
                    horizon_s=3 * 3600.0, start_utc_hour=7.0, case="C", demand_scale=0.4)
        for i in range(4):
            tasks.append(_agent(i, 60 + 120 * i, rng, REGIONS[i % 3]))
        for i in range(3):
            tasks.append(_know(i, 300 + 400 * i, rng, REGIONS[(i + 1) % 3]))
        tasks.append(_llm(0, 200, rng, "emea", "prefill"))
        tasks.append(_llm(1, 900, rng, "apac", "decode"))
        for i, wl in enumerate(["chemistry_small", "chemistry_small", "vqe_50q", "vqe_20q", "qla_scalar_explicit_1m", "femoco_thc", "chemistry_small"]):
            tasks.append(_qtask(i, 150 + 260 * i, rng, REGIONS[i % 3], wl, repeats=2 if wl == "chemistry_small" else 1, slo=2.5 * 3600))
        tasks.append(_qopt(0, 500, rng, "emea"))
        tasks.append(_qopt(1, 1100, rng, "americas"))
        tasks.append(_pipeline(0, 700, rng, "emea", slo=2.6 * 3600, prep_h=6))
        tasks.append(_pipeline(1, 1500, rng, "apac", slo=2.6 * 3600, prep_h=8))
    elif name == "morning_peak":
        base.update(description="Morning peak of EMEA/APAC: 6 h from 05:00 UTC with mass traffic of all three cases and a burst of agent jobs, knowledge-work research and batch LLM jobs, plus a few quantum jobs.",
                    horizon_s=6 * 3600.0, start_utc_hour=5.0, case="mix", demand_scale=1.0)
        n = 0
        for i in range(140):
            t = float(rng.uniform(0, 4 * 3600))
            tasks.append(_agent(i, t, rng, rng.choice(["emea", "apac"]), prio=int(rng.choice([2, 3, 3, 4])), slo=2.5 * 3600))
        for i in range(40):
            tasks.append(_know(i, float(rng.uniform(0, 3 * 3600)), rng, rng.choice(["emea", "apac", "americas"]), slo=5 * 3600))
        for i in range(14):
            tasks.append(_llm(i, float(rng.uniform(0, 4 * 3600)), rng, rng.choice(REGIONS), "prefill" if i % 2 else "decode", slo=2 * 3600))
        for i, wl in enumerate(["chemistry_small"] * 4 + ["vqe_50q"] * 2 + ["vqe_20q"] * 2 + ["femoco_thc"]):
            tasks.append(_qtask(i, float(rng.uniform(0, 3 * 3600)), rng, rng.choice(REGIONS), wl, repeats=2 if wl == "chemistry_small" else 1, slo=4 * 3600))
        for i in range(2):
            tasks.append(_pipeline(i, float(rng.uniform(0, 2 * 3600)), rng, rng.choice(REGIONS), slo=5 * 3600))
    elif name == "quantum_heavy_research":
        base.update(description="Quantum-heavy research batch: knowledge-worker traffic (case C) plus 12 h of chemistry/materials, variational, linear-algebra and optimisation jobs, including jobs that are infeasible on every QPU (FeMoco, RSA-2048).",
                    horizon_s=12 * 3600.0, start_utc_hour=8.0, case="C", demand_scale=0.8)
        wls = (["chemistry_small"] * 70 + ["vqe_50q"] * 40 + ["vqe_20q"] * 30 + ["qla_scalar_explicit_1m"] * 20 + ["qla_full_vector_1m"] * 6
               + ["femoco_thc"] * 4 + ["shor_rsa2048"] * 2)
        rng.shuffle(wls)
        for i, wl in enumerate(wls):
            t = float(rng.uniform(0, 8 * 3600))
            rep = int(rng.integers(1, 6)) if wl == "chemistry_small" else 1
            tasks.append(_qtask(i, t, rng, rng.choice(REGIONS), wl, prio=int(rng.choice([2, 3, 4])), repeats=rep,
                                slo=float(rng.choice([2, 3, 4])) * 3600))
        for i in range(60):
            tasks.append(_qopt(i, float(rng.uniform(0, 10 * 3600)), rng, rng.choice(REGIONS)))
        for i in range(8):
            tasks.append(_pipeline(i, float(rng.uniform(0, 6 * 3600)), rng, rng.choice(REGIONS), wl=str(rng.choice(["chemistry_small", "vqe_50q"])), slo=6 * 3600))
        for i in range(12):
            tasks.append(_know(i, float(rng.uniform(0, 6 * 3600)), rng, rng.choice(REGIONS), slo=8 * 3600))
    elif name == "mixed_hybrid_day":
        base.update(description="A full day (24 h from 00:00 UTC) with the mix of all three cases, recurring agent-job waves in each region's workday, hybrid GPU->QPU->GPU pipelines, knowledge-work research and scattered quantum jobs.",
                    horizon_s=24 * 3600.0, start_utc_hour=0.0, case="mix", demand_scale=1.0)
        i = 0
        for region, centre in (("apac", 4.0), ("emea", 11.0), ("americas", 19.0)):   # UTC hour of each region's workday centre
            for k in range(70):
                t = float(np.clip(rng.normal(centre * 3600, 2.2 * 3600), 0, 22 * 3600))
                tasks.append(_agent(i, t, rng, region, prio=int(rng.choice([2, 3, 3, 4])), slo=3 * 3600)); i += 1
        for k in range(48):
            tasks.append(_know(k, float(rng.uniform(0, 20 * 3600)), rng, rng.choice(REGIONS), slo=8 * 3600))
        for k in range(24):
            tasks.append(_llm(k, float(rng.uniform(0, 21 * 3600)), rng, rng.choice(REGIONS), "prefill" if k % 2 else "decode"))
        for k in range(12):
            tasks.append(_pipeline(k, float(rng.uniform(0, 18 * 3600)), rng, rng.choice(REGIONS), wl=str(rng.choice(["chemistry_small", "chemistry_small", "vqe_50q"])), slo=7 * 3600))
        wls = ["chemistry_small"] * 20 + ["vqe_50q"] * 10 + ["vqe_20q"] * 8 + ["qla_scalar_explicit_1m"] * 5 + ["femoco_thc"] * 2
        for k, wl in enumerate(wls):
            tasks.append(_qtask(k, float(rng.uniform(0, 20 * 3600)), rng, rng.choice(REGIONS), wl, repeats=int(rng.integers(1, 4)) if wl == "chemistry_small" else 1,
                                slo=float(rng.choice([3, 4, 6])) * 3600))
        for k in range(20):
            tasks.append(_qopt(k, float(rng.uniform(0, 22 * 3600)), rng, rng.choice(REGIONS)))
    elif name == "failure_overload_stress":
        base.update(description="Overload and failure stress, 12 h from 06:00 UTC: demand scaled up with a 2 h surge, EU North loses power (grid curtailment 85 -> 45 MW), 8 racks fail at US East, a QPU is forced into calibration, plus a large agent/knowledge batch and quantum jobs.",
                    horizon_s=12 * 3600.0, start_utc_hour=6.0, case="mix", demand_scale=1.1)
        base["events"] = [
            {"t": 2 * 3600, "type": "demand_surge", "multiplier": 1.4, "duration_s": 2 * 3600},
            {"t": 3 * 3600, "type": "site_power_cap", "site": "eu_north", "mw": 45},
            {"t": 4 * 3600, "type": "node_failure", "site": "us_east", "node_type": "gpu_rack", "count": 8, "duration_s": 4 * 3600},
            {"t": 3.5 * 3600, "type": "qpu_calibration", "site": "apac", "node_type": "qpu_cat40k", "duration_s": 3600},
            {"t": 8 * 3600, "type": "site_power_cap", "site": "eu_north", "mw": 85},
        ]
        for i in range(260):
            tasks.append(_agent(i, float(rng.uniform(0, 8 * 3600)), rng, rng.choice(REGIONS), prio=int(rng.choice([1, 2, 3, 4, 5])), slo=2.5 * 3600))
        for i in range(70):
            tasks.append(_know(i, float(rng.uniform(0, 7 * 3600)), rng, rng.choice(REGIONS), prio=int(rng.choice([2, 3, 4])), slo=6 * 3600))
        for i in range(24):
            tasks.append(_llm(i, float(rng.uniform(0, 8 * 3600)), rng, rng.choice(REGIONS), "prefill" if i % 2 else "decode"))
        wls = ["chemistry_small"] * 18 + ["vqe_50q"] * 8 + ["vqe_20q"] * 4 + ["femoco_thc"] * 2
        for k, wl in enumerate(wls):
            tasks.append(_qtask(k, float(rng.uniform(0, 7 * 3600)), rng, rng.choice(REGIONS), wl, repeats=int(rng.integers(1, 4)) if wl == "chemistry_small" else 1, slo=4 * 3600))
        for i in range(6):
            tasks.append(_pipeline(i, float(rng.uniform(0, 5 * 3600)), rng, rng.choice(REGIONS), slo=6 * 3600))
    elif name == "qpu_contention_burst":
        base.update(description="QPU contention: light case-C traffic and a burst of 130 chemistry/variational jobs inside 10 minutes with 75-minute SLOs and mixed priorities. Classical fallback for chemistry (768 module-hours) cannot meet the SLO, so QPU slots are the scarce resource.",
                    horizon_s=5 * 3600.0, start_utc_hour=9.0, case="C", demand_scale=0.3)
        for i in range(130):
            wl = "chemistry_small" if i % 4 else "vqe_50q"
            tasks.append(_qtask(i, 1800.0 + float(rng.uniform(0, 600)), rng, rng.choice(REGIONS), wl, prio=int(rng.choice([1, 2, 3, 4, 5])),
                                repeats=int(rng.integers(1, 7)) if wl == "chemistry_small" else 1, slo=75 * 60.0))
        for i in range(10):
            tasks.append(_know(i, float(rng.uniform(0, 3600)), rng, rng.choice(REGIONS), slo=4 * 3600))
    elif name in ("case_A_prompters", "case_B_agents", "case_C_knowledge"):
        c = name[5]
        base.update(description=f"Case {c} alone for 24 h (mass traffic of that case) with a small discrete overlay.", horizon_s=24 * 3600.0, start_utc_hour=0.0,
                    case=c, demand_scale=1.0)
        if c == "A":
            for i in range(20):
                tasks.append(_llm(i, float(rng.uniform(0, 20 * 3600)), rng, rng.choice(REGIONS), "prefill" if i % 2 else "decode"))
        elif c == "B":
            for i in range(120):
                tasks.append(_agent(i, float(rng.uniform(0, 20 * 3600)), rng, rng.choice(REGIONS), slo=3 * 3600))
        else:
            for i in range(40):
                tasks.append(_know(i, float(rng.uniform(0, 18 * 3600)), rng, rng.choice(REGIONS), slo=8 * 3600))
    else:
        raise KeyError(name)
    base["tasks"] = tasks
    return normalise_taskset(base)


NAMES = ["ui_demo", "morning_peak", "quantum_heavy_research", "mixed_hybrid_day", "failure_overload_stress", "qpu_contention_burst",
         "case_A_prompters", "case_B_agents", "case_C_knowledge"]


def write_all(out_dir: Path | None = None) -> list[Path]:
    out_dir = out_dir or PRESET_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for n in NAMES:
        ts = build(n)
        p = out_dir / f"{n}.json"
        save_taskset(ts, p)
        paths.append(p)
    return paths
