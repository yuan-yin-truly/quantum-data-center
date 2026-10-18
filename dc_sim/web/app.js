/* DC Sim front end: vanilla JS, no dependencies, works offline. Live mode talks to the local Python API; replay mode
   (window.DC_REPLAY, embedded trace) plays recorded frames from the same engine without a server. */
(function () {
"use strict";
const $ = (s, r) => (r || document).querySelector(s);
const el = (tag, attrs, html) => { const e = document.createElement(tag); Object.assign(e, attrs || {}); if (html !== undefined) e.innerHTML = html; return e; };
const REPLAY = window.DC_REPLAY || null;
const TYPE_COLOR = ["--gpu", "--lpu", "--pre", "--qpu", "--ann", "--mix", "--ctx"];
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtT = s => { s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h}h${String(m).padStart(2, "0")}` : `${m}m${String(s % 60).padStart(2, "0")}`; };
const fmtUsd = x => { const a = Math.abs(x); return a >= 1e9 ? `$${(x / 1e9).toFixed(2)}B` : a >= 1e6 ? `$${(x / 1e6).toFixed(2)}M` : a >= 1e3 ? `$${(x / 1e3).toFixed(1)}k` : `$${x.toFixed(0)}`; };
const pct = x => x == null ? "-" : x.toFixed(1) + " %";

let meta = null, layout = null, st = null, playing = false, timer = null, frameIdx = 0;
let tiles = {};            // site id -> {canvas, pos:[{x,y,s}], idx}
let particles = [], decisions = [], series = { t: [], mw: [], slo: [], pend: [] };
let lastTick = 0;

// ------------------------------------------------------------------------------------------ data sources
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const Live = {
  meta: () => api("/api/meta"),
  reset: (preset, policy, taskset) => api("/api/reset", taskset ? { taskset, policy } : { preset, policy }),
  step: n => api("/api/step", { n }),
  state: () => api("/api/state"),
};
const Replay = {
  meta: async () => ({ layout: REPLAY.layout, policies: Object.keys(REPLAY.labels).filter(k => k !== "ref_gpu_only_fleet").map(k => ({ id: k, label: REPLAY.labels[k] })),
    presets: [{ name: REPLAY.taskset, description: "recorded replay" }], preset: REPLAY.taskset, policy: REPLAY.policy, tick_s: REPLAY.tick_s, workloads: [], task_types: [] }),
  reset: async () => { frameIdx = 0; return REPLAY.frames[0]; },
  step: async n => { frameIdx = Math.min(REPLAY.frames.length - 1, frameIdx + Math.max(1, Math.round(n / REPLAY.every))); const f = REPLAY.frames[frameIdx];
    const rec = []; for (let i = Math.max(0, frameIdx - Math.max(1, Math.round(n / REPLAY.every)) + 1); i <= frameIdx; i++) rec.push(...REPLAY.frames[i].recent); return Object.assign({}, f, { recent: rec }); },
  state: async () => REPLAY.frames[frameIdx],
};
const Src = REPLAY ? Replay : Live;

// ------------------------------------------------------------------------------------------ build UI
function buildSites() {
  const host = $("#sites"); host.innerHTML = ""; tiles = {};
  layout.sites.forEach(s => {
    const card = el("div", { className: "site", id: "site-" + s.id });
    card.innerHTML = `<h3><span>${esc(s.name)}</span><span class="badge">${esc(s.cooling)}</span></h3>
      <div class="gauge"><i></i></div><div class="gtxt"><span class="pw">-</span><span class="pu">-</span></div>
      <canvas class="tiles"></canvas><div class="gtxt"><span class="q">-</span><span class="ut">-</span></div>`;
    host.appendChild(card);
    const cv = $("canvas", card);
    tiles[s.id] = { canvas: cv, pos: [], site: s };
    cv.addEventListener("mousemove", ev => hoverTile(s.id, ev));
    cv.addEventListener("mouseleave", () => $("#tip").hidden = true);
  });
  $("#legend").innerHTML = ["GPU rack", "LPU rack", "Prefill card rack", "QPU", "Annealer", "Mixed GPU+QPU", "Context memory"].map((n, i) => `<span style="--c:var(${TYPE_COLOR[i]})">${n}</span>`).join("") +
    `<span style="--c:var(--bad)">down</span><span style="--c:var(--pre)">calibrating (outline)</span><span style="--c:var(--qpu)">flow: quantum</span><span style="--c:var(--gpu)">flow: classical</span>`;
  layoutTiles();
}
function layoutTiles() {
  Object.values(tiles).forEach(t => {
    const cv = t.canvas, dpr = window.devicePixelRatio || 1, W = cv.clientWidth || 300, H = cv.clientHeight || 120;
    cv.width = W * dpr; cv.height = H * dpr; t.W = W; t.H = H; t.dpr = dpr;
    const nodes = t.site.nodes, pos = new Array(nodes.length);
    const big = [], mid = [], small = [];
    nodes.forEach((n, i) => (n[1] >= 3 && n[1] <= 5 ? big : n[1] === 6 ? mid : small).push(i));
    let y = 2;
    const place = (list, size, gap) => { let x = 2; list.forEach(i => { if (x + size > W - 2) { x = 2; y += size + gap; } pos[i] = { x, y, s: size }; x += size + gap; }); if (list.length) y += size + gap + 2; };
    place(big, 16, 3); place(mid, 8, 2);
    const rest = H - y - 2, n = small.length;
    let s = n ? Math.max(2, Math.min(10, Math.floor(Math.sqrt(Math.max(rest, 8) * (W - 4) / n)) - 1)) : 4;
    place(small, s, 1);
    t.pos = pos;
  });
}
function drawTiles(sd) {
  const t = tiles[sd.id]; if (!t || !sd.nodes) return;
  const g = t.canvas.getContext("2d"); g.setTransform(t.dpr, 0, 0, t.dpr, 0, 0); g.clearRect(0, 0, t.W, t.H);
  const colors = TYPE_COLOR.map(css), bad = css("--bad"), pre = css("--pre"), grid = css("--grid");
  t.site.nodes.forEach((n, i) => {
    const p = t.pos[i]; if (!p) return;
    const code = sd.nodes[i], u = (code % 1000) / 100, flag = Math.floor(code / 1000), c = colors[n[1]];
    g.globalAlpha = 1; g.fillStyle = grid; g.fillRect(p.x, p.y, p.s, p.s);
    g.globalAlpha = (flag & 4) ? 1 : 0.18 + 0.82 * u; g.fillStyle = (flag & 4) ? bad : c;
    if (n[1] === 5) { g.fillRect(p.x, p.y, p.s, p.s / 2); g.fillStyle = colors[3]; g.globalAlpha = (flag & 1) ? 1 : 0.35; g.fillRect(p.x, p.y + p.s / 2, p.s, p.s / 2); }
    else g.fillRect(p.x, p.y, p.s, p.s);
    g.globalAlpha = 1;
    if (flag & 2) { g.strokeStyle = pre; g.lineWidth = 2; g.strokeRect(p.x + 1, p.y + 1, p.s - 2, p.s - 2); }
    else if ((flag & 1) && n[1] >= 3) { g.strokeStyle = css("--ink"); g.lineWidth = 1.5; g.strokeRect(p.x + .5, p.y + .5, p.s - 1, p.s - 1); }
  });
}
async function hoverTile(sid, ev) {
  const t = tiles[sid], r = t.canvas.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
  const i = t.pos.findIndex(p => p && x >= p.x && x <= p.x + p.s && y >= p.y && y <= p.y + p.s);
  const tip = $("#tip");
  if (i < 0) { tip.hidden = true; return; }
  const n = t.site.nodes[i], sd = st.sites.find(s => s.id === sid), code = sd.nodes[i];
  let html = `<b>${esc(n[0])}</b><br>${esc(meta.layout.type_names[n[1]])} - ${esc(meta.layout.node_cfg_labels[n[2]] || n[2])}<br>utilisation ${code % 1000}%` + (n[3] ? `, ${n[3]} modules` : "");
  const f = Math.floor(code / 1000); if (f & 4) html += "<br><b class=bad>down (failed)</b>"; if (f & 2) html += "<br>calibrating"; if (f & 1) html += "<br>QPU busy";
  tip.innerHTML = html; tip.hidden = false; tip.style.left = Math.min(innerWidth - 400, ev.clientX + 12) + "px"; tip.style.top = ev.clientY + 12 + "px";
  if (!REPLAY && (n[1] >= 3 && n[1] <= 5 || Math.random() < 0.0)) {
    try { const d = await api("/api/node?id=" + encodeURIComponent(n[0])); if (!tip.hidden) tip.innerHTML = html + `<br>queue: ${d.queue.length} job(s)` + (d.qpu ? `<br>${esc(d.qpu.label)}, ${d.qpu.busy_kw.toFixed(0)} kW busy / ${d.qpu.standby_kw.toFixed(0)} kW standby, jobs done ${d.qpu.jobs_done}` : "") + (d.running.length ? `<br>running: ${d.running.map(r => esc(r.task)).join(", ")}` : ""); } catch (e) { /* ignore */ }
  }
}

// ------------------------------------------------------------------------------------------ render
function render() {
  if (!st) return;
  $("#clock").textContent = `t = ${fmtT(st.t)} / ${fmtT(st.horizon_s)}  (UTC ${String(Math.floor((st.start_utc_hour + st.t / 3600) % 24)).padStart(2, "0")}:${String(Math.floor(st.t / 60 % 60)).padStart(2, "0")})`;
  st.sites.forEach(sd => {
    const card = $("#site-" + sd.id); if (!card) return;
    const f = sd.power_mw / sd.cap_mw; const i = $(".gauge i", card); i.style.width = Math.min(100, 100 * f) + "%"; i.className = f > 0.97 ? "hot" : "";
    $(".pw", card).textContent = `${sd.power_mw.toFixed(1)} / ${sd.cap_mw.toFixed(0)} MW`;
    $(".pu", card).textContent = `PUE ${sd.pue.toFixed(2)}`;
    $(".q", card).textContent = `QPU queue ${sd.qpu_queue} | tasks ${sd.running}`;
    $(".ut", card).textContent = `GPU ${(100 * sd.gpu_util).toFixed(0)} % | KV hit ${(100 * sd.hit).toFixed(0)} %`;
    drawTiles(sd);
  });
  $("#hubInfo").textContent = `policy ${st.policy} | pending ${st.n_pending} | decisions/tick ${(st.metrics.decisions.assign + st.metrics.decisions.defer + st.metrics.decisions.reject)}`;
  $("#hubQueue").innerHTML = st.pending.slice(0, 24).map(p => `<span title="${esc(p.reason)}">${esc(p.uid)}</span>`).join("");
  renderMetrics(); renderLog();
}
function stat(label, val, sub, cls) { return `<div class="stat"><small>${label}</small><b class="${cls || ""}">${val}</b><small>${sub || ""}</small></div>`; }
function renderMetrics() {
  const m = st.metrics, u = m.users, q = m.quantum, c = m.cost, e = m.energy, tk = m.tasks;
  let h = '<div class="tiles4">';
  Object.keys(u).forEach(k => h += stat(`Case ${k} within SLO`, pct(u[k].slo_pct), `worst tick ${pct(u[k].worst)}; ${(u[k].users / 1e6).toFixed(0)} M users`, u[k].slo_pct < 99.9 ? "bad" : "good"));
  h += stat("Tasks within SLO", pct(tk.slo_pct), `${tk.ok}/${tk.n} ok, late ${tk.late}, rejected ${tk.rejected}, open ${tk.open}`, tk.slo_pct != null && tk.slo_pct < 99 ? "bad" : "");
  h += stat("Facility power", `${st.total_mw.toFixed(0)} MW`, `cap sum ${st.cap_mw.toFixed(0)} MW (grid 500)`);
  h += stat("Energy (facility)", `${e.facility_mwh.toFixed(0)} MWh`, `module ${e.module_mwh.toFixed(0)}, system ${e.system_mwh.toFixed(0)} MWh`);
  h += stat("Cost per day", fmtUsd(c.total_usd_per_day), `energy ${fmtUsd(c.energy_usd_per_day)} + capex ${fmtUsd(c.capex_amortised_usd_per_day)}`);
  h += stat("QPU utilisation", `${q.utilisation_pct.toFixed(1)} %`, `${q.n_qpu_nodes} QPU nodes`);
  h += stat("Quantum offloads", `${q.on_qpu}`, `classical ${q.classical_alt}, rejected ${q.rejected}, fallbacks ${q.fallbacks}`);
  h += stat("Power cap", m.power_cap.never_exceeded ? "never exceeded" : "EXCEEDED", `max site ratio ${m.power_cap.max_site_ratio.toFixed(3)}`, m.power_cap.never_exceeded ? "good" : "bad");
  h += `</div><h4>Facility power (MW) and worst-case SLO (%)</h4><canvas class="spark" id="spark"></canvas><div class="reason">All numbers are results of an illustrative model; demand, cost and node counts are assumptions (see README_DC_SIM.md). Energy boundary: facility = system x (1+network) x PUE.</div>`;
  const t = $("#tab-metrics"); t.innerHTML = h; spark();
}
function spark() {
  const cv = $("#spark"); if (!cv) return; const dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight; cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr); const n = series.t.length; if (n < 2) return;
  const t0 = series.t[0], t1 = series.t[n - 1] || 1, X = t => 4 + (W - 8) * (t - t0) / Math.max(1, t1 - t0);
  const mx = Math.max(1, st.cap_mw, ...series.mw);
  g.lineWidth = 1.5; g.strokeStyle = css("--accent"); g.beginPath(); series.t.forEach((t, i) => { const y = H - 4 - (H - 8) * series.mw[i] / mx; i ? g.lineTo(X(t), y) : g.moveTo(X(t), y); }); g.stroke();
  g.strokeStyle = css("--ok"); g.beginPath(); series.t.forEach((t, i) => { const y = H - 4 - (H - 8) * (series.slo[i] / 100); i ? g.lineTo(X(t), y) : g.moveTo(X(t), y); }); g.stroke();
}
function renderLog() {
  const tab = $("#tab-log"); if (tab.hidden && tab.dataset.built === String(decisions.length)) return;
  const f = ($("#logFilter") || {}).value || "";
  const rows = decisions.filter(d => d.action !== "event" && (!f || JSON.stringify(d).toLowerCase().includes(f.toLowerCase()))).slice(-250).reverse();
  tab.dataset.built = String(decisions.length);
  tab.innerHTML = `<div class="row"><input id="logFilter" placeholder="filter (task, node, action, site)" value="${esc(f)}" style="flex:1"></div>
   <table><tr><th>t</th><th>unit</th><th>action</th><th>where</th><th>route</th><th>end</th><th>cost</th></tr>${rows.map((d, i) => `<tr class="click" data-i="${i}"><td>${fmtT(d.t)}</td><td>${esc(d.uid)}<br><small>${esc(d.type)}</small></td><td>${esc(d.action)}</td><td>${esc(d.node || "-")}</td><td>${esc(d.route || "")}</td><td>${d.end ? fmtT(d.end) : ""}</td><td>${d.cost_usd != null ? "$" + d.cost_usd : ""}</td></tr><tr hidden><td colspan="7"><div class="reason">${esc(d.reason)}${(d.alts || []).length ? "\n\nalternatives:\n" + d.alts.map(a => `${a.node} ${a.route} cost $${a.cost_usd} end ${fmtT(a.end_t)} wait ${a.wait_s}s`).join("\n") : ""}</div></td></tr>`).join("")}</table>`;
  $("#logFilter").addEventListener("input", () => { tab.dataset.built = ""; renderLog(); $("#logFilter").focus(); });
  tab.querySelectorAll("tr.click").forEach(tr => tr.addEventListener("click", () => tr.nextElementSibling.hidden = !tr.nextElementSibling.hidden));
}

// ------------------------------------------------------------------------------------------ animation of allocations
function siteCenter(sid, nodeId) {
  const stage = $("#stage").getBoundingClientRect(), t = tiles[sid]; if (!t) return null; const r = t.canvas.getBoundingClientRect();
  let x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (nodeId) { const i = t.site.nodes.findIndex(n => n[0] === nodeId); if (i >= 0 && t.pos[i]) { x = r.left + t.pos[i].x + t.pos[i].s / 2; y = r.top + t.pos[i].y + t.pos[i].s / 2; } }
  return { x: x - stage.left, y: y - stage.top };
}
function launch(dec) {
  const hub = $("#hub").getBoundingClientRect(), stage = $("#stage").getBoundingClientRect();
  const x0 = hub.left + hub.width / 2 - stage.left, y0 = hub.top + hub.height / 2 - stage.top;
  if (dec.action === "assign") { const c = siteCenter(dec.site, dec.node); if (!c) return; particles.push({ x0, y0, x1: c.x, y1: c.y, t0: performance.now(), dur: 900, color: dec.route === "quantum" ? css("--qpu") : css("--gpu"), dec }); }
  else if (dec.action === "reject") particles.push({ x0, y0, x1: x0, y1: y0 - 10, t0: performance.now(), dur: 1100, color: css("--bad"), dec, bad: true });
}
function animate(now) {
  const svg = $("#flows"); const stage = $("#stage").getBoundingClientRect(); svg.setAttribute("width", stage.width); svg.setAttribute("height", stage.height);
  let h = ""; particles = particles.filter(p => now - p.t0 < p.dur);
  particles.forEach(p => { const k = (now - p.t0) / p.dur, e = k * k * (3 - 2 * k), x = p.x0 + (p.x1 - p.x0) * e, y = p.y0 + (p.y1 - p.y0) * e;
    h += p.bad ? `<text x="${x}" y="${y}" fill="${p.color}" font-size="14" opacity="${1 - k}">x ${esc(p.dec.uid)}</text>` : `<circle cx="${x}" cy="${y}" r="5" fill="${p.color}" opacity="${1 - 0.5 * k}"/><text x="${x + 7}" y="${y - 6}" font-size="10" fill="${css("--ink2")}" opacity="${1 - k}">${esc(p.dec.uid)}</text>`; });
  svg.innerHTML = h; requestAnimationFrame(animate);
}

// ------------------------------------------------------------------------------------------ actions
function ingest(s) {
  st = s; (s.recent || []).forEach(d => { decisions.push(d); if (d.action === "assign" || d.action === "reject") { if (particles.length < 60) launch(d); } });
  if (decisions.length > 6000) decisions = decisions.slice(-4000);
  const n = series.t.length; if (!n || s.t > series.t[n - 1]) { series.t.push(s.t); series.mw.push(s.total_mw); series.slo.push(Math.min(...Object.values(s.metrics.users).map(u => u.slo_pct == null ? 100 : u.slo_pct))); series.pend.push(s.n_pending); }
  else if (s.t < series.t[n - 1]) series = { t: [s.t], mw: [s.total_mw], slo: [100], pend: [s.n_pending] };
  render();
}
async function doReset() {
  stop(); particles = []; decisions = []; series = { t: [], mw: [], slo: [], pend: [] };
  try { ingest(await Src.reset($("#preset").value, $("#policy").value)); } catch (e) { banner(e.message); }
}
function banner(msg) { const b = $("#banner"); b.textContent = msg; b.hidden = !msg; if (msg) setTimeout(() => b.hidden = true, 6000); }
async function step(n) { try { ingest(await Src.step(n)); if (st.done) stop(); } catch (e) { banner(e.message); stop(); } }
function stop() { playing = false; clearInterval(timer); $("#btnPlay").textContent = "Play"; $("#btnPlay").classList.remove("on"); }
function play() {
  if (playing) return stop(); playing = true; $("#btnPlay").textContent = "Pause"; $("#btnPlay").classList.add("on");
  let busy = false; timer = setInterval(async () => { if (busy) return; busy = true; await step(Math.max(1, Math.round(+$("#speed").value / 10))); busy = false; }, 100);
}
function injectTab() {
  const t = $("#tab-inject");
  if (REPLAY) { t.innerHTML = '<div class="reason">Replay mode: injection and policy switching need the live server (python -m dc_sim serve). Recorded policy: ' + esc(REPLAY.policy) + ".</div>"; return; }
  const types = meta.task_types.map(x => `<option>${x}</option>`).join(""), wl = meta.workloads.map(x => `<option>${x}</option>`).join("");
  t.innerHTML = `<h4>Quick inject</h4><div class="row"><label>Type <select id="iType">${types}</select></label><label>Count <input id="iCount" type="number" value="5" min="1" max="500" style="width:64px"></label>
   <label>Size x <input id="iSize" type="number" value="1" min="0.1" step="0.5" style="width:64px"></label></div>
   <div class="row"><label>Workload <select id="iWl">${wl}</select></label><label>Region <select id="iReg"><option value="mixed">mixed</option><option>americas</option><option>emea</option><option>apac</option></select></label>
   <label>Priority <input id="iPrio" type="number" value="3" min="1" max="5" style="width:48px"></label><label>SLO h <input id="iSlo" type="number" value="3" step="0.5" style="width:56px"></label></div>
   <div class="row"><button id="iGo">Submit tasks now</button><span id="iMsg"></span></div>
   <h4>Task JSON (dc_sim.tasks/1)</h4><textarea id="iJson" placeholder='{"format":"dc_sim.tasks/1","tasks":[...]} or a list of task objects'></textarea>
   <div class="row"><button id="iInj">Inject into running sim</button><button id="iLoad">Load as new scenario</button><input type="file" id="iFile" accept=".json"></div>
   <div class="row"><button id="iExport">Download task file</button><button id="iTrace">Download trace</button><button id="iReplay">Export static replay HTML</button></div>`;
  const sub = async body => { try { const r = await api("/api/inject", body); $("#iMsg").textContent = `submitted ${r.n} task(s) at t=${fmtT(r.t)}`; ingest(await Live.state()); } catch (e) { $("#iMsg").textContent = e.message; banner(e.message); } };
  $("#iGo").onclick = () => sub({ spec: { type: $("#iType").value, count: +$("#iCount").value, size: +$("#iSize").value, workload: $("#iWl").value, region: $("#iReg").value, priority: +$("#iPrio").value, slo_h: +$("#iSlo").value } });
  const parse = () => { const j = JSON.parse($("#iJson").value); return Array.isArray(j) ? { tasks: j } : j; };
  $("#iInj").onclick = () => { try { const j = parse(); sub({ tasks: j.tasks }); } catch (e) { banner("invalid JSON: " + e.message); } };
  $("#iLoad").onclick = async () => { try { stop(); decisions = []; series = { t: [], mw: [], slo: [], pend: [] }; ingest(await Live.reset(null, $("#policy").value, parse())); } catch (e) { banner(e.message); } };
  $("#iFile").onchange = ev => { const f = ev.target.files[0]; if (f) f.text().then(x => $("#iJson").value = x); };
  const dl = async (url, name, post) => { const r = await fetch(url, post ? { method: "POST", body: "{}" } : {}); const b = await r.blob(); const a = el("a", { href: URL.createObjectURL(b), download: name }); a.click(); };
  $("#iExport").onclick = () => dl("/api/taskset", "tasks_export.json"); $("#iTrace").onclick = () => dl("/api/trace", "trace.json");
  $("#iReplay").onclick = () => { banner("recording replay (all policies are compared too)..."); dl("/api/replay", "dc_sim_replay.html", true); };
}
function compareTab() {
  const t = $("#tab-compare");
  if (REPLAY) { t.innerHTML = tableRows(REPLAY.compare_rows, REPLAY.labels); return; }
  t.innerHTML = '<div class="row"><button id="cGo">Run all policies on this task set (from t=0)</button><span id="cMsg"></span></div><div id="cOut"></div>';
  $("#cGo").onclick = async () => { $("#cMsg").textContent = "running..."; try { const r = await api("/api/compare", {}); $("#cMsg").textContent = `${r.n_tasks} tasks`; $("#cOut").innerHTML = tableRows(r.rows, r.labels) + '<h4>Facility power (MW), all policies</h4><canvas class="spark" id="cp"></canvas><h4>Worst-case SLO % over time</h4><canvas class="spark" id="cs"></canvas>'; lines($("#cp"), r.series, "power_mw", r.labels); lines($("#cs"), r.series, "slo", r.labels, 100); } catch (e) { $("#cMsg").textContent = e.message; } };
}
function tableRows(rows, labels) {
  return `<table><tr><th>policy</th><th>served %</th><th>A/B/C %</th><th>tasks %</th><th>k$/day</th><th>vs ref k$/day</th><th>QPU/cls/rej</th></tr>${rows.map(r => `<tr><td>${esc(labels[r.policy] || r.policy)}</td><td>${r.served.toFixed(2)}</td><td>${["A", "B", "C"].map(k => r.slo[k] == null ? "-" : r.slo[k].toFixed(1)).join(" / ")}</td><td>${r.slo.tasks == null ? "-" : r.slo.tasks.toFixed(1)}</td><td>${(r.usd_day_m * 1e3).toFixed(0)}</td><td>${r.saved_vs_ref_total_usd_day == null ? "-" : (r.saved_vs_ref_total_usd_day / 1e3).toFixed(0)}</td><td>${r.q_on_qpu}/${r.q_classical}/${r.q_rejected}</td></tr>`).join("")}</table><div class="reason">Ranked by users served at the constraints first, then dollars. Saved vs the GPU-only reference fleet (same site caps) per day; negative = costs more. Illustrative model.</div>`;
}
const PCOL = { batch: "--gpu", greedy: "--lpu", fifo: "--ann", gpu_only: "--ink2", ref_gpu_only_fleet: "--qpu" };
function lines(cv, series, key, labels, fixedMax) {
  const dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight; cv.width = W * dpr; cv.height = H * dpr; const g = cv.getContext("2d"); g.scale(dpr, dpr);
  const names = Object.keys(series); let mx = fixedMax || Math.max(1, ...names.map(n => Math.max(...series[n][key]))); const t1 = Math.max(...names.map(n => series[n].t[series[n].t.length - 1]));
  names.forEach((n, k) => { g.strokeStyle = css(PCOL[n] || "--accent"); g.lineWidth = 1.5; g.beginPath(); series[n].t.forEach((t, i) => { const x = 4 + (W - 8) * t / t1, y = H - 4 - (H - 8) * series[n][key][i] / mx; i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); g.fillStyle = css(PCOL[n] || "--accent"); g.fillText((labels[n] || n).split(" (")[0], 6 + k * 100, 10); });
}
async function init() {
  try { meta = await Src.meta(); } catch (e) { banner("cannot reach the local server: " + e.message); return; }
  layout = meta.layout;
  $("#preset").innerHTML = meta.presets.map(p => `<option value="${esc(p.name)}" title="${esc(p.description)}">${esc(p.name)}</option>`).join("");
  $("#policy").innerHTML = meta.policies.map(p => `<option value="${p.id}">${esc(p.label)}</option>`).join("");
  $("#preset").value = meta.preset; $("#policy").value = meta.policy;
  buildSites(); injectTab(); compareTab();
  $("#btnReset").onclick = doReset; $("#btnPlay").onclick = play; $("#btnStep").onclick = () => step(1); $("#btnStep10").onclick = () => step(10);
  $("#preset").onchange = doReset;
  $("#policy").onchange = async () => { if (REPLAY) return; try { ingest(await api("/api/policy", { name: $("#policy").value })); } catch (e) { banner(e.message); } };
  $("#speed").oninput = () => $("#speedLbl").textContent = `${Math.max(1, Math.round($("#speed").value / 10) * 10)} ticks/s`;
  document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => { document.querySelectorAll("#tabs button").forEach(x => x.classList.toggle("on", x === b)); document.querySelectorAll(".tab").forEach(t => t.hidden = t.id !== "tab-" + b.dataset.tab); if (b.dataset.tab === "log") { $("#tab-log").dataset.built = ""; renderLog(); } });
  addEventListener("resize", () => { layoutTiles(); if (st) render(); });
  try { ingest(await Src.state()); } catch (e) { banner(e.message); }
  requestAnimationFrame(animate);
  window.__dc = { step, get state() { return st; }, get decisions() { return decisions; } };
}
init();
})();
