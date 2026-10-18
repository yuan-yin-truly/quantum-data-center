"""Local web server for the visual simulation: standard library only, bound to 127.0.0.1 (never 0.0.0.0).

The back end drives the SAME :class:`dc_sim.engine.Engine` as the CLI, so the visual run of a task file equals the numerical run.
Endpoints (JSON): GET /api/meta, /api/state, /api/decisions, /api/node?id=, /api/taskset, /api/trace;
POST /api/reset, /api/step, /api/advance, /api/inject, /api/policy, /api/compare, /api/import, /api/replay.
"""

from __future__ import annotations

import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import api, report
from .config import PRESET_DIR, PKG, clean_json
from .engine import Engine
from .fleet import Fleet
from .scheduler import POLICIES, POLICY_LABELS
from .tasks import TaskError, load_taskset

WEB = PKG / "web"
HOST = "127.0.0.1"
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon"}
MAX_BODY = 20 * 1024 * 1024


class Session:
    """One interactive simulation. Single user, single lock."""

    def __init__(self, fleet_path: str | None = None):
        self.lock = threading.RLock()
        self.fleet_path = fleet_path
        self.fleet = Fleet.load(fleet_path)
        self.eng: Engine | None = None
        self.preset = None
        self.policy = "batch"
        self.seed: int | None = None
        self.reset("ui_demo", "batch")

    def reset(self, taskset, policy: str = "batch", seed: int | None = None) -> None:
        with self.lock:
            ts = load_taskset(taskset)
            self.preset = taskset if isinstance(taskset, str) else ts["name"]
            self.policy, self.seed = policy, seed
            self.eng = Engine(self.fleet, ts, policy, seed=seed)
            self.eng.step_log = []

    def step(self, n: int = 1) -> dict:
        with self.lock:
            decs = []
            for _ in range(max(1, min(int(n), 600))):
                if self.eng.done:
                    break
                r = self.eng.step()
                decs += r["decisions"]
            st = self.eng.state(nodes=True, recent=0)
            st["recent"] = decs[-200:]
            st["n_recent_total"] = len(decs)
            return st

    def state(self) -> dict:
        with self.lock:
            return self.eng.state(nodes=True, recent=0)

    def meta(self) -> dict:
        with self.lock:
            presets = []
            for p in api.list_presets():
                ts = json.loads((PRESET_DIR / f"{p}.json").read_text(encoding="utf-8"))
                presets.append({"name": p, "n_tasks": len(ts["tasks"]), "horizon_h": ts["horizon_s"] / 3600.0, "case": ts["case"], "description": ts["description"]})
            return {"policies": [{"id": p, "label": POLICY_LABELS[p]} for p in POLICIES], "presets": presets, "layout": self.eng.layout(),
                    "preset": self.preset, "policy": self.eng.policy.name, "task_types": list(__import__("dc_sim.tasks", fromlist=["x"]).TASK_TYPES),
                    "workloads": __import__("quantum_arch.catalog", fromlist=["x"]).keys("workloads"), "tick_s": self.eng.tick,
                    "fleet": self.fleet.summary(), "note": "illustrative model; all non-quantum_arch numbers are assumptions"}

    def inject(self, body: dict) -> dict:
        with self.lock:
            tasks = body.get("tasks")
            if tasks is None and "spec" in body:
                tasks = self._expand_spec(body["spec"])
            if tasks is None:
                raise TaskError("body needs 'tasks' (list) or 'spec'")
            ids = self.eng.inject(tasks)
            return {"ids": ids, "n": len(ids), "t": self.eng.t}

    def _expand_spec(self, sp: dict) -> list[dict]:
        """Quick-inject form: type, count, size parameters -> a list of task dicts (deterministic ids from the engine)."""
        import numpy as np
        from .config import stable_seed
        ty = sp["type"]
        n = max(1, min(int(sp.get("count", 1)), 500))
        now = self.eng.t
        rng = np.random.default_rng(stable_seed("inject", self.eng.seed, len(self.eng.tasks), ty, n))
        out = []
        slo = float(sp.get("slo_h", 3.0)) * 3600.0
        for i in range(n):
            t = {"type": ty, "arrival_s": now + (float(sp.get("spread_s", 0.0)) * i / max(1, n)), "priority": int(sp.get("priority", 3)),
                 "home_region": sp.get("region", ["americas", "emea", "apac"][i % 3] if sp.get("region") in (None, "mixed") else sp["region"]),
                 "data_gb": float(sp.get("data_gb", 10)), "deadline_s": now + slo}
            sz = float(sp.get("size", 1))
            if ty == "llm_prefill_batch":
                t["size"] = {"requests": int(200_000 * sz), "prefill_tokens": int(sp.get("tokens", 4000))}
            elif ty == "llm_decode_batch":
                t["size"] = {"requests": int(200_000 * sz), "decode_tokens": int(sp.get("tokens", 1000))}
            elif ty == "agent_job":
                t["size"] = {"steps": int(300 * sz), "ctx_gb": float(sp.get("ctx_gb", 60))}
            elif ty == "knowledge_job":
                t["size"] = {"module_hours": 60.0 * sz, "modules": int(sp.get("modules", 32)), "ctx_gb": 20}
            elif ty in ("quantum_fault_tolerant", "quantum_variational", "quantum_linear_algebra"):
                t["quantum"] = {"kind": "gate", "workload": sp.get("workload", "chemistry_small"), "repeats": max(1, int(sz))}
                t["case"] = "Q"
            elif ty == "quantum_optimisation":
                t["quantum"] = {"kind": "annealer", "p_success_per_read": float(sp.get("p_success", 0.005))}
                t["case"] = "Q"
            elif ty == "hybrid_pipeline":
                wl = sp.get("workload", "chemistry_small")
                t["case"] = "Q"
                t["stages"] = [{"name": "GPU prep", "kind": "gpu", "module_hours": 8.0 * sz, "modules": 32, "out_gb": float(sp.get("data_gb", 100))},
                               {"name": f"QPU ({wl})", "kind": "quantum", "out_gb": 10.0, "quantum": {"kind": "gate", "workload": wl, "repeats": 1}},
                               {"name": "GPU post", "kind": "gpu", "module_hours": 4.0, "modules": 16, "out_gb": 1.0}]
            out.append(t)
        return out

    def compare(self) -> dict:
        with self.lock:
            ts = self.eng.export_taskset()
            engines = api.compare_policies(self.fleet, ts, POLICIES, self.seed)
        rows = report.compare_rows(engines)
        series = {}
        for k, e in engines.items():
            h = e.hist
            step = max(1, len(h) // 160)
            nsite = len(e.fleet.sites)
            pts = h[::step]
            series[k] = {"t": [r[0] for r in pts], "power_mw": [sum(r[1 + 3 * i] for i in range(nsite)) for r in pts],
                         "slo": [min(r[1 + 3 * nsite:4 + 3 * nsite]) for r in pts], "pending": [r[4 + 3 * nsite] for r in pts]}
        return clean_json({"rows": report.rank(rows), "series": series, "taskset": ts["name"], "n_tasks": len(ts["tasks"]),
                           "labels": {k: report.POLICY_NAME.get(k, k) for k in engines}})

    def replay_html(self, every: int = 10) -> str:
        from . import replay
        with self.lock:
            ts = self.eng.export_taskset()
            pol = self.policy
        return replay.build_html(self.fleet, ts, pol, self.seed, every)


def make_handler(sess: Session):
    class H(BaseHTTPRequestHandler):
        server_version = "dc_sim/1"

        def log_message(self, fmt, *args):      # quiet
            pass

        def _ok_host(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost", "[::1]")

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(clean_json(obj)).encode("utf-8"))

        def _static(self, rel: str) -> None:
            rel = rel.lstrip("/") or "index.html"
            p = (WEB / rel).resolve()
            if WEB.resolve() not in p.parents and p != WEB.resolve():
                return self._send(404, b"not found", "text/plain")
            if not p.is_file():
                return self._send(404, b"not found", "text/plain")
            self._send(200, p.read_bytes(), MIME.get(p.suffix, "application/octet-stream"))

        def do_GET(self):
            if not self._ok_host():
                return self._send(403, b"forbidden host", "text/plain")
            u = urlparse(self.path)
            try:
                if u.path == "/api/meta":
                    return self._json(sess.meta())
                if u.path == "/api/state":
                    return self._json(sess.state())
                if u.path == "/api/decisions":
                    with sess.lock:
                        return self._json({"decisions": sess.eng.decisions[-3000:]})
                if u.path == "/api/node":
                    q = parse_qs(u.query)
                    with sess.lock:
                        return self._json(sess.eng.node_detail(q["id"][0]))
                if u.path == "/api/taskset":
                    with sess.lock:
                        return self._json(sess.eng.export_taskset())
                if u.path == "/api/trace":
                    with sess.lock:
                        e = sess.eng
                        return self._json({"format": "dc_sim.trace/1", "taskset": e.export_taskset(), "policy_log": e.policy_log, "seed": e.seed,
                                           "decisions": e.decisions, "metrics": e.metrics()})
                if u.path.startswith("/api/"):
                    return self._json({"error": "unknown endpoint"}, 404)
                return self._static(u.path)
            except KeyError as ex:
                return self._json({"error": f"missing or unknown: {ex}"}, 400)
            except Exception as ex:           # pragma: no cover
                traceback.print_exc()
                return self._json({"error": str(ex)}, 500)

        def do_POST(self):
            if not self._ok_host():
                return self._send(403, b"forbidden host", "text/plain")
            u = urlparse(self.path)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    return self._json({"error": "body too large"}, 413)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if u.path == "/api/reset":
                    ts = body.get("taskset") or body.get("preset") or sess.preset or "ui_demo"
                    sess.reset(ts, body.get("policy", sess.policy), body.get("seed"))
                    return self._json(sess.state())
                if u.path == "/api/import":
                    sess.reset(body["taskset"], body.get("policy", sess.policy), body.get("seed"))
                    return self._json(sess.state())
                if u.path == "/api/step":
                    return self._json(sess.step(int(body.get("n", 1))))
                if u.path == "/api/advance":
                    with sess.lock:
                        n_ticks = int(round(float(body.get("seconds", 60)) / sess.eng.tick))
                    return self._json(sess.step(n_ticks))
                if u.path == "/api/inject":
                    return self._json(sess.inject(body))
                if u.path == "/api/policy":
                    with sess.lock:
                        if body["name"] not in POLICIES:
                            return self._json({"error": f"unknown policy {body['name']!r}"}, 400)
                        sess.eng.set_policy(body["name"])
                        sess.policy = body["name"]
                        return self._json(sess.state())
                if u.path == "/api/compare":
                    return self._json(sess.compare())
                if u.path == "/api/replay":
                    html = sess.replay_html(int(body.get("every", 10)))
                    return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
                return self._json({"error": "unknown endpoint"}, 404)
            except TaskError as ex:
                return self._json({"error": str(ex)}, 400)
            except (KeyError, ValueError, json.JSONDecodeError) as ex:
                return self._json({"error": f"bad request: {ex}"}, 400)
            except FileNotFoundError as ex:
                return self._json({"error": str(ex)}, 404)
            except Exception as ex:           # pragma: no cover
                traceback.print_exc()
                return self._json({"error": str(ex)}, 500)
    return H


def make_server(port: int = 8765, fleet: str | None = None) -> tuple[ThreadingHTTPServer, Session]:
    sess = Session(fleet)
    srv = ThreadingHTTPServer((HOST, port), make_handler(sess))     # 127.0.0.1 only
    return srv, sess


def serve(port: int = 8765, fleet: str | None = None) -> None:
    srv, _ = make_server(port, fleet)
    print(f"dc_sim visual simulation on http://{HOST}:{srv.server_address[1]}/  (localhost only; Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    finally:
        srv.server_close()
