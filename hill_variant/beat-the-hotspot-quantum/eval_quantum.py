#!/usr/bin/env python3
"""LOCAL-ONLY hybrid evaluator: classical chiplet package + quantum subsystem.

    python eval_quantum.py <submission_dir> [--grid 64|128] [--no-thermal] [--output report.json]

Run it with a Python that has numpy, scipy and matplotlib (the chiplet-thermal-gui venv).
HotSpot runs in the pinned container image (or directly on Linux x86-64); see
README_QUANTUM_VARIANT.md.

NOT LEADERBOARD COMPARABLE. Using quantum hardware here is not allowed on the official
hill, so nothing this script prints may be compared with, or submitted to, the official
beat-the-hotspot leaderboard.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from geometry import validate_layout  # noqa: E402  (original hill module)
from generate_workloads import generate  # noqa: E402
from verify_submission import parse_submission, verify  # noqa: E402
from hybrid_power import (ModifierError, apply_modifiers, build_modifiers, is_identity,  # noqa: E402
                          power_budgets)
from quantum_block import QuantumBlockError, validate_quantum_block  # noqa: E402

VARIANT = "beat-the-hotspot-quantum"
NOTICE = ("LOCAL-ONLY VARIANT. These results use quantum hardware and a modified power model and must NOT be "
          "compared with, or submitted to, the official beat-the-hotspot leaderboard (quantum hardware there "
          "would be unfair). The original hill is unchanged and remains the only valid reference for ranking.")
PENALTY = 1_000_000.0
MAX_SUBMISSION_BYTES = 256_000
EXIT_OK, EXIT_INVALID, EXIT_INFEASIBLE, EXIT_NO_THERMAL = 0, 2, 3, 4


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------
def pinned_image() -> str:
    text = (HERE / "hill.yaml").read_text()
    match = re.search(r"^\s*image:\s*(\S+)", text, re.M)
    return match.group(1) if match else ""


def _stamp(report: dict) -> dict:
    """Every output carries the not-comparable flag and the visible notice."""
    report["variant"] = VARIANT
    report["leaderboard_comparable"] = False
    report["notice"] = NOTICE
    return report


def _invalid(status: str, reason: str, grid: int, extra: dict | None = None) -> dict:
    report = {"passed": False, "status": status, "reason": reason, "grid": grid,
              "metrics": [{"name": n, "value": PENALTY, "direction": "min"}
                          for n in ("score", "worst_gpu_c", "worst_hbm_c")]}
    report.update(extra or {})
    return _stamp(report)


def _round(x, n=4):
    return None if x is None else round(float(x), n)


# ---------------------------------------------------------------------------------------------
# thermal runtime
# ---------------------------------------------------------------------------------------------
def choose_runtime(requested: str) -> str:
    if requested == "host":
        return "host"
    if requested == "docker":
        return "docker"
    if sys.platform == "linux" and platform.machine() in ("x86_64", "AMD64"):
        return "host"
    return "docker"


def docker_ready() -> tuple[bool, str]:
    docker = shutil.which("docker") or "/usr/local/bin/docker"
    if not Path(docker).exists():
        return False, "docker is not installed"
    try:
        proc = subprocess.run([docker, "info"], capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"docker info failed: {exc}"
    if proc.returncode:
        return False, "the Docker daemon is not running (start Docker Desktop: `open -a Docker`)"
    return True, docker


def run_thermal(stripped: dict, grid: int, runs: list[dict], runtime: str) -> dict:
    """Run thermal_job.py (host or container). Raises RuntimeError with a clear reason."""
    workroot = HERE / ".job_tmp"
    workroot.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="job_", dir=workroot))
    try:
        (work / "submission.json").write_text(json.dumps(stripped))
        rel = work.relative_to(HERE).as_posix()
        if runtime == "host":
            base, python = HERE, [sys.executable]
        else:
            ok, info = docker_ready()
            if not ok:
                raise RuntimeError(info)
            base, python = Path("/hill"), None
        job = {"submission": str(base / rel / "submission.json"), "grid": grid, "runs": runs}
        (work / "job.json").write_text(json.dumps(job))
        out = base / rel / "result.json"
        if runtime == "host":
            cmd = python + [str(HERE / "thermal_job.py"), str(work / "job.json"), "--output", str(work / "result.json")]
        else:
            image = pinned_image()
            cmd = [info, "run", "--rm", "--platform", "linux/amd64", "-u", f"{os.getuid()}:{os.getgid()}",
                   "-v", f"{HERE}:/hill", "-w", "/hill", image, "python", "/hill/thermal_job.py",
                   str(base / rel / "job.json"), "--output", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode or not (work / "result.json").is_file():
            raise RuntimeError(f"thermal job failed (exit {proc.returncode}): {(proc.stderr or proc.stdout)[-1500:]}")
        return json.loads((work / "result.json").read_text())
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            workroot.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------
# report assembly
# ---------------------------------------------------------------------------------------------
def _classical_group(result: dict | None, workloads: list[str]) -> dict | None:
    if result is None:
        return None
    if not result.get("passed"):
        return {"passed": False, "reason": result.get("reason")}
    return {"path": result.get("path"), "score": result.get("score"), "worst_gpu_c": result["worst_gpu_c"],
            "worst_hbm_c": result["worst_hbm_c"], "reference_c": result.get("reference_c"),
            "per_workload": {w: {"gpu_peak_c": result["workloads"][w]["gpu_peak_c"],
                                 "hbm_peak_c": result["workloads"][w]["hbm_peak_c"],
                                 "total_w": result["workloads"][w]["total_w"],
                                 "per_die_peak_c": result["workloads"][w]["per_die_peak_c"]} for w in workloads},
            "hotspot_sha256": result.get("hotspot_sha256")}


def evaluate_submission(submission, *, final: bool = False, grid: int | None = None, no_thermal: bool = False,
                        runtime: str = "auto", skip_classical_run: bool = False) -> dict:
    """Full hybrid evaluation. Returns the report dict (always stamped not-comparable)."""
    grid = grid or (128 if final else 64)
    submission = Path(submission)
    sub_file = submission / "submission.json"
    spec = json.loads((HERE / "challenge_spec.json").read_text())
    workloads = list(spec["workloads"])

    # ---- 1. classical legality, exactly as the original (quantum key stripped first) ----
    stripped, has_quantum, quantum_raw = None, False, None
    if sub_file.is_file() and sub_file.stat().st_size <= MAX_SUBMISSION_BYTES:
        try:
            raw = json.loads(sub_file.read_text(encoding="utf-8"),
                             parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
        except (json.JSONDecodeError, UnicodeError, ValueError):
            raw = None
        if isinstance(raw, dict):
            has_quantum = "quantum" in raw
            quantum_raw = raw.pop("quantum", None)
            stripped = raw
    if stripped is None:
        validity = verify(sub_file, HERE / "challenge_spec.json")   # original wording for missing/invalid JSON
        reason = validity.get("reason", "submission.json is missing or exceeds the size limit")
        if validity["passed"]:   # pragma: no cover (cannot happen: parse failed above)
            reason = "submission.json could not be parsed"
        return _invalid("invalid_layout", reason, grid)
    with tempfile.TemporaryDirectory(prefix="qsub_") as tmp:
        stripped_file = Path(tmp) / "submission.json"
        stripped_file.write_text(json.dumps(stripped))
        validity = verify(stripped_file, HERE / "challenge_spec.json")
        if not validity["passed"]:
            return _invalid("invalid_layout", validity["reason"], grid,
                            {"classical": {"passed": False, "reason": validity["reason"]}})
        layout, paths = parse_submission(stripped_file, spec)
        routing = validate_layout(spec, layout, wire_routes_grid=paths)

    # ---- 2. quantum block: schema, then quantum_arch ----
    nb, outcome, quantum_group = None, None, {"present": False}
    if has_quantum:
        try:
            from quantum_eval import (QuantumEvalError, QuantumUnavailable, catalog_names,
                                      evaluate_quantum)
            tasks, examples = catalog_names()
            nb = validate_quantum_block(quantum_raw, spec=spec, submission_dir=submission,
                                        known_tasks=tasks, known_examples=examples)
            outcome = evaluate_quantum(nb)
        except QuantumBlockError as exc:
            return _invalid("invalid_quantum_block", f"quantum block: {exc}", grid,
                            {"classical": {"layout_legal": True}, "quantum": {"present": True, "valid": False,
                                                                              "feasible": False, "error": str(exc)}})
        except QuantumEvalError as exc:
            return _invalid("invalid_quantum_block", f"quantum block: {exc}", grid,
                            {"quantum": {"present": True, "valid": False, "feasible": False, "error": str(exc)}})
        except QuantumUnavailable as exc:
            return _invalid("quantum_unavailable", str(exc), grid,
                            {"quantum": {"present": True, "valid": None, "feasible": None, "error": str(exc)}})
        quantum_group = {"present": True, "valid": True, "feasible": outcome.feasible,
                         "infeasible_reasons": outcome.reasons, **outcome.summary}

    # ---- 3. modifiers, power accounting (cheap, no HotSpot) ----
    portable = generate(spec)
    modifiers, host_by_wl = None, {}
    if nb is not None:
        hosts_for_mod = {}
        for die, host in nb["package_hosts"]["dies"].items():
            hp = outcome.host_power[die]
            power_w = {w: (hp["active_w"] if w in nb["offload"]["active_in"] else hp["idle_w"]) for w in workloads}
            hosts_for_mod[die] = {"power_w": power_w, "traffic_scale": host["traffic_scale"]}
            host_by_wl[die] = power_w
        try:
            modifiers = build_modifiers(spec, portable, fractions=nb["offload"]["fractions"],
                                        dynamic_power_fraction=nb["offload"]["dynamic_power_fraction"],
                                        traffic_coupling=nb["offload"]["traffic_coupling"],
                                        replaced_mode=nb["offload"]["replaced_die_work"], hosts=hosts_for_mod)
            spec_m, portable_m = apply_modifiers(spec, portable, modifiers)
        except ModifierError as exc:
            return _invalid("invalid_quantum_block", f"quantum block: {exc}", grid)
    else:
        spec_m, portable_m = spec, portable
    identity = is_identity(modifiers)
    budgets_classical = power_budgets(spec, portable, layout, routing)
    budgets_system = budgets_classical if identity else power_budgets(spec_m, portable_m, layout, routing)

    # ---- 4. thermal ----
    thermal = {"status": "skipped (--no-thermal)" if no_thermal else "pending", "runtime": None}
    results = {}
    if not no_thermal:
        rt = choose_runtime(runtime)
        runs = [] if skip_classical_run and not identity else [{"name": "classical", "modifiers": None}]
        if not identity:
            runs.append({"name": "system", "modifiers": modifiers})
        try:
            results = run_thermal(stripped, grid, runs, rt)
            thermal = {"status": "ok", "runtime": rt, "image": pinned_image() if rt == "docker" else "host",
                       "grid": grid, "hotspot": "pinned HotSpot build via the original judge"}
        except RuntimeError as exc:
            thermal = {"status": "unavailable", "runtime": rt, "reason": str(exc),
                       "note": "No temperatures are reported: they are never estimated or faked."}
    classical_res = results.get("classical")
    system_res = results.get("system", classical_res if identity else None)
    classical_group = _classical_group(classical_res, workloads)

    # ---- 5. system metrics ----
    replaced = sorted(nb["package_hosts"]["dies"]) if nb else []
    system = {"hybrid_feasible": None, "infeasible_reasons": [], "credit": None}
    reasons = list(outcome.reasons) if outcome else []
    pue = (outcome.summary["power_w"]["pue"] if outcome else 1.0)
    per_workload = {}
    task_s = outcome.task_runtime_s if outcome else None
    for w in workloads:
        pkg_w = budgets_system[w]["total_w"]
        q_w = outcome.external_power_w if outcome else 0.0
        per_workload[w] = {"package_w_with_offload": pkg_w, "package_w_classical": budgets_classical[w]["total_w"],
                           "package_w_delta": round(pkg_w - budgets_classical[w]["total_w"], 6),
                           "quantum_side_outside_package_w": q_w,
                           "total_electrical_w": pkg_w + q_w, "facility_w": (pkg_w + q_w) * pue,
                           "energy_per_task_j": (None if task_s is None else (pkg_w + q_w) * task_s)}
    system["power_by_workload"] = per_workload
    if outcome:
        pw = nb["task"]["package_workload"]
        system["task"] = {"quantum_workload": nb["task"]["workload"], "runtime_s": task_s,
                          "package_workload_during_task": pw,
                          "energy_per_task_j": per_workload[pw]["energy_per_task_j"],
                          "energy_definition": "(quantum side outside package + package power with offload for the "
                                               "declared package_workload) x quantum task runtime; no comparison with "
                                               "an all-classical run is made (that would need an assumed speedup)",
                          "cryostat_wall_power_w": (outcome.summary["cryostat"] or {}).get("wall_power_w", 0.0)}
        system["pue"] = pue
        system["package_hosted_decoder_w"] = outcome.summary["power_w"]["hosted_on_package"]
    if system_res is not None and system_res.get("passed"):
        peaks_by_wl = {w: {"gpu_peak_c": system_res["workloads"][w]["gpu_peak_c"],
                           "hbm_peak_c": system_res["workloads"][w]["hbm_peak_c"],
                           "per_die_peak_c": system_res["workloads"][w]["per_die_peak_c"]} for w in workloads}
        support = {}
        for die in replaced:
            limit = nb["package_hosts"]["dies"][die]["max_junction_c"]
            peak = max(system_res["workloads"][w]["per_die_peak_c"][die] for w in workloads)
            ok = limit is None or peak <= limit
            support[die] = {"peak_c": peak, "max_junction_c": limit, "within_limit": ok,
                            "power_w_by_workload": host_by_wl.get(die)}
            if not ok:
                reasons.append(f"support chiplet {die} reaches {peak:.2f} C > declared limit {limit:g} C")
        system["package"] = {"label": "package peak temperatures with the quantum offload applied",
                             "score_vs_official_reference_INFORMATIONAL": system_res.get("score"),
                             "worst_gpu_c": system_res["worst_gpu_c"], "worst_hbm_c": system_res["worst_hbm_c"],
                             "per_workload": peaks_by_wl, "support_chiplets": support,
                             "replaced_dies": replaced}
    system["hybrid_feasible"] = not reasons
    if system.get("package"):
        system["package"]["credible"] = not reasons
        if reasons:
            system["package"]["label"] += " (HYPOTHETICAL: the hybrid is infeasible, do not rely on these)"
    system["infeasible_reasons"] = reasons
    system["credit"] = ("temperatures reflect the declared offload; they are credible only if hybrid_feasible"
                        if nb else "no quantum block: identical to the classical core")

    # ---- 6. assemble ----
    report = {"grid": grid, "final": bool(final or grid == 128), "thermal": thermal,
              "layout": {"legal": True, "weighted_route_gb_s_mm": validity["weighted_route_gb_s_mm"],
                         "route_limit_gb_s_mm": validity["route_limit_gb_s_mm"],
                         "minimum_die_separation_mm": validity["minimum_die_separation_mm"],
                         "die_edge_margin_mm": validity["die_edge_margin_mm"]},
              "classical": classical_group or {"note": "thermal run not available", "power_budget_w": {
                  w: budgets_classical[w]["total_w"] for w in workloads}},
              "quantum": quantum_group, "system": system,
              "declared_assumptions": ({"offload": {k: v for k, v in nb["offload"].items()},
                                        "package_hosts": nb["package_hosts"], "task": nb["task"],
                                        "limits": nb["limits"],
                                        "honesty_rule": "offload fractions are INPUTS; quantum_arch only decides "
                                                        "feasibility and cost of the offloaded task; no quantum "
                                                        "speedup or advantage is assumed or reported"}
                                       if nb else None),
              "modifiers": modifiers}
    if thermal["status"] == "unavailable":
        report.update(passed=False, status="thermal_unavailable", reason=thermal["reason"])
    elif no_thermal:
        report.update(passed=system["hybrid_feasible"], status="ok_no_thermal" if system["hybrid_feasible"]
                      else "hybrid_infeasible", metrics=None,
                      reason=None if system["hybrid_feasible"] else "; ".join(reasons))
    elif system_res is None or not system_res.get("passed"):
        report.update(passed=False, status="invalid_layout", reason=(system_res or {}).get("reason"))
    elif not system["hybrid_feasible"]:
        report.update(passed=False, status="hybrid_infeasible", reason="; ".join(reasons),
                      metrics=[{"name": n, "value": PENALTY, "direction": "min"}
                               for n in ("score", "worst_gpu_c", "worst_hbm_c")])
    else:
        pkg = system["package"]
        report.update(passed=True, status="ok", reason=None,
                      metrics=[{"name": "score", "value": pkg["score_vs_official_reference_INFORMATIONAL"], "direction": "min"},
                               {"name": "worst_gpu_c", "value": pkg["worst_gpu_c"], "direction": "min"},
                               {"name": "worst_hbm_c", "value": pkg["worst_hbm_c"], "direction": "min"}])
    return _stamp(report)


def eval(submission, *, final: bool = False, **params) -> dict:  # noqa: A001  (hills evaluator contract)
    """AutoLab-style entry point, LOCAL variant only."""
    report = evaluate_submission(submission, final=final, runtime=params.get("runtime", "auto"),
                                 no_thermal=bool(params.get("no_thermal", False)))
    grid = report["grid"]
    return {"passed": report["passed"], "metrics": report.get("metrics") or [],
            "config": [{"name": "thermal_grid", "value": f"{grid}x{grid}", "primary": True},
                       {"name": "variant", "value": f"{VARIANT} LOCAL-ONLY", "primary": True},
                       {"name": "leaderboard_comparable", "value": "false", "primary": True}],
            "details": report, "leaderboard_comparable": False, "notice": NOTICE}


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------
def _fmt(x, unit="", nd=2):
    return "n/a" if x is None else f"{x:.{nd}f}{unit}"


def summary_lines(report: dict) -> list[str]:
    lines = ["=" * 78, "LOCAL-ONLY quantum variant. NOT LEADERBOARD COMPARABLE. Do not submit.", "=" * 78,
             f"status: {report['status']}  passed: {report['passed']}  mesh: {report['grid']}"]
    if report.get("reason"):
        lines.append(f"reason: {report['reason']}")
    c = report.get("classical") or {}
    if "worst_gpu_c" in c:
        lines.append(f"classical (original workloads): GPU {_fmt(c['worst_gpu_c'], ' C')}  "
                     f"HBM {_fmt(c['worst_hbm_c'], ' C')}  score {c.get('score')}")
    q = report.get("quantum") or {}
    if q.get("present") and q.get("valid"):
        t, cap, cry = q["task"], q["capability"], q.get("cryostat")
        lines.append(f"quantum: feasible={q['feasible']}  arch={q['architecture']['name']}  task={t['workload']}  "
                     f"runtime={t.get('runtime', 'n/a')}  logical qubits={cap['logical_qubits']}  rQOPS={cap['rqops']:.3g}")
        if cry:
            lines.append(f"  cryostat: {cry['fridge_units']} fridge unit(s), wall power {cry['wall_power_w']:.3g} W")
        for r in q.get("infeasible_reasons", []):
            lines.append(f"  - {r}")
    s = report.get("system") or {}
    pkg = s.get("package")
    if pkg:
        tag = "" if pkg.get("credible", True) else "  [HYPOTHETICAL: hybrid infeasible]"
        lines.append(f"system package with offload: GPU {_fmt(pkg['worst_gpu_c'], ' C')}  "
                     f"HBM {_fmt(pkg['worst_hbm_c'], ' C')}{tag}")
    if s.get("task"):
        lines.append(f"system energy per task: {s['task']['energy_per_task_j']:.4g} J" if s["task"]["energy_per_task_j"]
                     is not None else "system energy per task: n/a (task cannot run)")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("submission", type=Path, help="directory holding submission.json")
    parser.add_argument("--grid", type=int, choices=(64, 128), default=64)
    parser.add_argument("--no-thermal", action="store_true",
                        help="legality, quantum evaluation and power accounting only (no HotSpot)")
    parser.add_argument("--runtime", choices=("auto", "docker", "host"), default="auto")
    parser.add_argument("--output", type=Path, help="also write the JSON report here")
    args = parser.parse_args(argv)
    report = evaluate_submission(args.submission, grid=args.grid, no_thermal=args.no_thermal, runtime=args.runtime)
    payload = json.dumps(report, indent=2, allow_nan=False, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")
    print("\n".join(summary_lines(report)), file=sys.stderr)
    status = report["status"]
    if status in ("invalid_layout", "invalid_quantum_block", "quantum_unavailable"):
        return EXIT_INVALID
    if status == "hybrid_infeasible":
        return EXIT_INFEASIBLE
    if status == "thermal_unavailable":
        return EXIT_NO_THERMAL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
