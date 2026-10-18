import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CAT_TEXT,
  LAYOUTS,
  MEMORY_OPTIONS,
  TASK_MIX,
  TOY_CAPACITY,
  makeTasks,
  panelAt,
  simulate,
  type ArrivalPattern,
  type Cat,
  type LayoutId,
  type LayoutRun,
  type SegState,
} from '../model/layouts.ts';
import { TASKS, secsLabel, type TaskKind } from '../model/taskflow.ts';

const PLAY_SECONDS = 26;
const ORDER: LayoutId[] = ['current', 'noPark', 'mixed'];
const TITLE: Record<LayoutId, string> = { current: 'Current layout: parking', noPark: 'No parking', mixed: 'Mixed nodes' };
const ONE_LINE: Record<LayoutId, string> = {
  current: 'One shared pool of GPU nodes and one shared QPU service. A session whose QPU job waits or runs moves to the parking memory and frees its GPU memory slot. Nothing else is parked.',
  noPark: 'Same shared pool and QPU service, but no parking memory: a session keeps its GPU memory slot while its QPU job waits or runs.',
  mixed: 'Three separate nodes, each with its own GPUs and one QPU. A task stays on its node, keeps its GPU memory slot while its QPU job waits or runs, and cannot use another node’s QPU.',
};
const ARCHE_LETTER: Record<TaskKind, string> = { inference: 'I', mixed: 'M', sim: 'S' };
const ARCHE_NAME: Record<TaskKind, string> = { inference: 'inference', mixed: 'mixed', sim: 'sim-heavy' };
const C = { gpu: '#22d3ee', tool: '#8691aa', qpu: '#d946ef', amber: '#e69f00', red: '#f07575' };

// Colour of a task square by what it is doing right now.
const CAT_CLASS: Record<Cat, string> = {
  pending: 'sq-pending',
  gpu: 'sq-gpu',
  tool: 'sq-tool',
  qpu: 'sq-qpu',
  waitqpu: 'sq-waitqpu',
  held: 'sq-held',
  blockmem: 'sq-block',
  waitgpu: 'sq-block',
  waittool: 'sq-block',
  done: 'sq-done',
};
const LEGEND: Array<[string, string]> = [
  ['sq-gpu', 'LLM step on a GPU'],
  ['sq-tool', 'tool running (session stays on its GPU node)'],
  ['sq-qpu', 'running on a QPU'],
  ['sq-waitqpu', 'parked in parking memory, waiting for or running on a QPU'],
  ['sq-held', 'waiting for a QPU while holding GPU memory'],
  ['sq-block', 'blocked: no GPU memory free'],
  ['sq-done', 'done'],
  ['sq-pending', 'not arrived yet'],
];

const SEG_COLOR: Record<SegState, string> = {
  'run-llm': C.gpu,
  'run-tool': C.tool,
  'run-qpu': C.qpu,
  'wait-llm-compute': C.red,
  'wait-llm-memory': 'url(#stripe-mem)',
  'wait-tool': '#a35a5a',
  'wait-qpu': 'url(#stripe-qpu)',
  'held-wait-qpu': 'url(#stripe-held)',
};

export function LayoutCompare() {
  const [pattern, setPattern] = useState<ArrivalPattern>('burst');
  const [memory, setMemory] = useState<'tight' | 'roomy'>('tight');
  const [layout, setLayout] = useState<LayoutId>('current');
  const [pos, setPos] = useState(0); // fraction of the horizon
  const [playing, setPlaying] = useState(false);
  const raf = useRef<number | null>(null);

  const memSlots = MEMORY_OPTIONS[memory];
  const runs = useMemo(() => {
    const tasks = makeTasks(pattern);
    return Object.fromEntries(ORDER.map((id) => [id, simulate(id, tasks, memSlots)])) as Record<LayoutId, LayoutRun>;
  }, [pattern, memSlots]);
  const horizon = Math.max(...ORDER.map((id) => runs[id].makespan)) * 1.02;
  const t = pos * horizon;
  const finished = pos >= 1 - 1e-6;

  useEffect(() => {
    setPos(0);
    setPlaying(false);
  }, [pattern, memory]);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setPos((p) => {
        const np = p + dt / PLAY_SECONDS;
        if (np >= 1) {
          setPlaying(false);
          return 1;
        }
        return np;
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [playing]);

  const sum = (id: LayoutId) => runs[id].summary;
  const infX = (id: LayoutId) => sum(id).meanBy.inference / sum(id).unloadedBy.inference;
  const takeaway = (id: LayoutId): string => {
    if (id === 'current') {
      return `Sessions whose QPU job waits or runs move to the parking memory, so their GPU memory slots stay free for other tasks: inference tasks take ${infX('current').toFixed(1)}× their unloaded time, and the QPUs are busy ${Math.round(sum('current').qpuUtil * 100)}% of the time.`;
    }
    if (id === 'noPark') {
      return infX('noPark') > 1.2
        ? `Without parking memory, sessions keep their GPU memory slots while their QPU job waits (up to ${sum('noPark').peakHeld} at once). Pure-inference tasks turn red because no slot is free: they take ${infX('noPark').toFixed(1)}× their unloaded time, against ${infX('current').toFixed(1)}× with parking.`
        : `With this much GPU memory nothing is blocked: inference tasks take ${infX('noPark').toFixed(1)}× their unloaded time, the same as with parking. Parking only helps when GPU memory is tight.`;
    }
    return `Each node keeps its sessions and cannot borrow a QPU: all tasks are done after ${secsLabel(runs.mixed.makespan)} instead of ${secsLabel(runs.current.makespan)}, a QPU sits idle for ${secsLabel(sum('mixed').strandedQpuSecs)} in total while another node’s queue waits${infX('mixed') > 1.2 ? `, and inference tasks take ${infX('mixed').toFixed(1)}× their unloaded time because node memory is held by sessions waiting for a QPU` : ''}.`;
  };

  // ---- detailed timeline (collapsed)
  const run = runs[layout];
  const GX = 112;
  const GW = 1200 - GX - 16;
  const x = (sec: number) => GX + (sec / horizon) * GW;
  const ROW = 13;
  const wfH = run.tasks.length * ROW + 26;
  const chartH = 150;
  const qMax = Math.max(4, ...ORDER.flatMap((id) => runs[id].samples.map((s) => Math.max(s.qLlm, s.qQpu, s.memHeldIdle))));
  const y = (v: number) => chartH - 22 - (v / qMax) * (chartH - 56);
  const line = (pick: (s: LayoutRun['samples'][number]) => number) => {
    let d = '';
    let prev = 0;
    run.samples.forEach((s, i) => {
      const px = x(s.t);
      d += i === 0 ? `M${x(0)} ${y(0)} L${px} ${y(0)}` : ` L${px} ${y(prev)}`;
      d += ` L${px} ${y(pick(s))}`;
      prev = pick(s);
    });
    return d + ` L${x(horizon)} ${y(prev)}`;
  };
  const stuck = [...run.tasks]
    .map((r) => ({ r, total: r.wait.llm + r.wait.tool + r.wait.qpu }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 5);

  return (
    <section className="flow" aria-labelledby="layout-title">
      <div className="section-head">
        <h2 id="layout-title">Why parking matters: the same 24 tasks, one layout at a time</h2>
        <p>
          Pick a layout, then press play. Each square is one task ({TASK_MIX.inference} pure inference “I”, {TASK_MIX.mixed} mixed “M”, {TASK_MIX.sim} simulation-heavy “S”). Watch the GPU memory slots
          and the QPUs: where squares turn red, tasks are stuck. This is a toy with {TOY_CAPACITY.qpu} QPUs and a few GPU slots, built to show the mechanism, not real sizes.
        </p>
      </div>

      <div className="card flow-card">
        <div className="flow-controls">
          <div className="flow-opts">
            <div className="seg" role="radiogroup" aria-label="How tasks arrive">
              {(['burst', 'spread'] as ArrivalPattern[]).map((p) => (
                <button key={p} role="radio" aria-checked={pattern === p} className={`seg-btn${pattern === p ? ' is-on' : ''}`} onClick={() => setPattern(p)}>
                  <span className="seg-text">
                    {p === 'burst' ? 'Burst' : 'Steady'}
                    <small>{p === 'burst' ? 'all tasks arrive within 2 min' : 'tasks arrive over 8 min'}</small>
                  </span>
                </button>
              ))}
            </div>
            <div className="seg" role="radiogroup" aria-label="GPU memory">
              {(['tight', 'roomy'] as const).map((m) => (
                <button key={m} role="radio" aria-checked={memory === m} className={`seg-btn${memory === m ? ' is-on' : ''}`} onClick={() => setMemory(m)}>
                  <span className="seg-text">
                    GPU memory {m}
                    <small>{MEMORY_OPTIONS[m]} slots in the pod</small>
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="seg" role="tablist" aria-label="Layout" style={{ marginTop: 14 }}>
          {ORDER.map((id) => (
            <button key={id} role="tab" aria-selected={layout === id} className={`seg-btn${layout === id ? ' is-on' : ''}`} onClick={() => setLayout(id)}>
              <span className="seg-text">
                {TITLE[id]}
                <small>
                  done after {secsLabel(runs[id].makespan)} · inference {infX(id).toFixed(1)}×
                </small>
              </span>
            </button>
          ))}
        </div>
        <p className="flow-blurb" style={{ marginTop: 12 }}>
          {ONE_LINE[layout]}
        </p>

        {(() => {
          const groups = panelAt(run, t, memSlots);
          const park = LAYOUTS[layout].park;
          return (
            <div className="lc-panel lc-wide">
              <div className="lc-nodes">
                {groups.map((g, gi) => (
                  <div key={gi} className="lc-node">
                    <div className="lc-node-title">{groups.length > 1 ? `Node ${gi + 1}` : 'Pod: shared GPU nodes and QPU service'}</div>
                    <div className="lc-row">
                      <span className="lc-label">QPU</span>
                      <span className="lc-icons">
                        {Array.from({ length: Math.round(g.qpu.cap) }, (_, i) => (
                          <span key={i} className={`qpu-icon${i < g.qpu.busy ? ' is-busy' : ''}`} title={i < g.qpu.busy ? 'QPU busy' : 'QPU idle'} />
                        ))}
                      </span>
                      <span className="lc-count">{g.qpu.queued > 0 ? `${g.qpu.queued} waiting` : g.qpu.busy ? 'no queue' : 'idle'}</span>
                    </div>
                    <div className="lc-row">
                      <span className="lc-label">GPU memory</span>
                      <span className="lc-icons">
                        {Array.from({ length: Math.round(g.mem.cap) }, (_, i) => {
                          const cls = i < g.mem.held ? 'mem-held' : i < g.mem.held + g.mem.running ? 'mem-run' : i < g.mem.held + g.mem.running + g.mem.resident ? 'mem-res' : 'mem-free';
                          const tip = { 'mem-held': 'held by a session whose QPU job waits or runs', 'mem-run': 'serving an LLM step', 'mem-res': 'session on its GPU node (tool call or waiting for a GPU)', 'mem-free': 'free' }[cls]!;
                          return <span key={i} className={`mem-icon ${cls}`} title={tip} />;
                        })}
                      </span>
                      <span className="lc-count">{g.mem.held > 0 ? `${g.mem.held} held for a QPU job` : ''}</span>
                    </div>
                    {park && (
                      <div className="lc-row">
                        <span className="lc-label">Parking memory</span>
                        <span className="lc-icons">
                          {Array.from({ length: Math.min(g.mem.parked, 18) }, (_, i) => (
                            <span key={i} className="mem-icon mem-parked" title="session parked while its QPU job waits or runs" />
                          ))}
                        </span>
                        <span className="lc-count">{g.mem.parked > 0 ? `${g.mem.parked} parked` : 'empty'}</span>
                      </div>
                    )}
                    <div className="lc-squares">
                      {g.tasks.map((tk) => (
                        <span key={tk.id} className={`sq ${CAT_CLASS[tk.cat]}`} title={`#${tk.id} ${TASKS[tk.arche].label}: ${CAT_TEXT[tk.cat]}`}>
                          {ARCHE_LETTER[tk.arche]}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="lc-stats">
                <div>
                  <span>Blocked now (no slot or GPU free)</span>
                  <strong>{groups.reduce((a, g) => a + g.tasks.filter((tk) => tk.cat === 'blockmem' || tk.cat === 'waitgpu').length, 0)}</strong>
                </div>
                <div>
                  <span>Waiting for a QPU now</span>
                  <strong>{groups.reduce((a, g) => a + g.qpu.queued, 0)}</strong>
                </div>
                <div>
                  <span>Done</span>
                  <strong>
                    {groups.reduce((a, g) => a + g.tasks.filter((tk) => tk.cat === 'done').length, 0)} / {run.tasks.length}
                  </strong>
                </div>
              </div>
            </div>
          );
        })()}

        <div className="flow-legend">
          {LEGEND.map(([cls, label]) => (
            <span key={cls}>
              <i className={`sq sq-key ${cls}`} aria-hidden="true" />
              {label}
            </span>
          ))}
          <span>
            <i className="mem-icon mem-held" aria-hidden="true" />
            GPU memory slot held by a session whose QPU job waits or runs
          </span>
          <span>
            <i className="mem-icon mem-run" aria-hidden="true" />
            slot serving an LLM step
          </span>
          <span>
            <i className="mem-icon mem-res" aria-hidden="true" />
            slot of a session on its GPU node (tool call)
          </span>
        </div>

        <div className="flow-bar">
          <button className="flow-btn" onClick={() => (finished ? (setPos(0), setPlaying(true)) : setPlaying(!playing))}>
            {finished ? 'Replay' : playing ? 'Pause' : 'Play'}
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.002}
            value={pos}
            aria-label="Move through time"
            onChange={(e) => {
              setPlaying(false);
              setPos(Number(e.target.value));
            }}
          />
          <strong className="flow-time">t = {secsLabel(t)}</strong>
        </div>

        <h3 className="panel-title" style={{ marginTop: 22 }}>
          What it adds up to: {TITLE[layout]}
        </h3>
        <div className="lc-card lc-card-wide">
          <dl>
            <div>
              <dt>All 24 tasks done after</dt>
              <dd className={runs[layout].makespan > 1.1 * runs.current.makespan ? 'bad' : undefined}>
                {secsLabel(runs[layout].makespan)} {layout !== 'current' && <small>(current layout: {secsLabel(runs.current.makespan)})</small>}
              </dd>
            </div>
            <div>
              <dt>Inference tasks take on average</dt>
              <dd className={infX(layout) > 1.2 ? 'bad' : undefined}>
                {secsLabel(sum(layout).meanBy.inference)} <small>({infX(layout).toFixed(1)}× unloaded{layout !== 'current' ? `; current layout ${infX('current').toFixed(1)}×` : ''})</small>
              </dd>
            </div>
            <div>
              <dt>Simulation-heavy tasks take on average</dt>
              <dd className={sum(layout).meanBy.sim > 1.1 * sum('current').meanBy.sim ? 'bad' : undefined}>
                {secsLabel(sum(layout).meanBy.sim)} {layout !== 'current' && <small>(current layout: {secsLabel(sum('current').meanBy.sim)})</small>}
              </dd>
            </div>
            <div>
              <dt>QPU idle while another queue waits</dt>
              <dd className={sum(layout).strandedQpuSecs > 300 ? 'bad' : undefined}>{secsLabel(sum(layout).strandedQpuSecs)}</dd>
            </div>
          </dl>
        </div>
        <p className="flow-blurb" style={{ marginTop: 12 }}>
          {takeaway(layout)}
        </p>

        <details className="flow-log">
          <summary>Detailed timeline: every task and every queue</summary>
          <svg className="flow-gantt" viewBox={`0 0 1200 ${chartH}`} role="img" aria-label="Queue lengths over time">
            <defs>
              <pattern id="stripe-mem" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="#4a1f1f" />
                <rect width="3" height="6" fill="#f07575" />
              </pattern>
              <pattern id="stripe-qpu" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="#2a1233" />
                <rect width="3" height="6" fill="#d946ef" opacity="0.7" />
              </pattern>
              <pattern id="stripe-held" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="#3a2a05" />
                <rect width="3" height="6" fill="#e69f00" opacity="0.8" />
              </pattern>
            </defs>
            <text x="8" y="16" fill="#b3bccf" fontSize="12" fontWeight="600">
              Queue length over time
            </text>
            <rect x={GX} y={y(qMax)} width={GW} height={y(0) - y(qMax)} fill="#0f1626" rx="4" />
            {[0, Math.round(qMax / 2), qMax].map((v) => (
              <g key={v}>
                <line x1={GX} x2={GX + GW} y1={y(v)} y2={y(v)} stroke="rgba(255,255,255,0.07)" />
                <text x={GX - 6} y={y(v) + 4} fill="#8691aa" fontSize="11" textAnchor="end">
                  {v}
                </text>
              </g>
            ))}
            <path d={line((s) => s.memHeldIdle)} fill="none" stroke={C.amber} strokeWidth="2" strokeDasharray="5 3" />
            <path d={line((s) => s.qLlm)} fill="none" stroke={C.gpu} strokeWidth="2.5" />
            <path d={line((s) => s.qQpu)} fill="none" stroke={C.qpu} strokeWidth="2.5" />
            <g fontSize="11">
              <text x={GX + 8} y={chartH - 4} fill={C.qpu}>
                ━ waiting for a QPU
              </text>
              <text x={GX + 150} y={chartH - 4} fill={C.gpu}>
                ━ waiting for a GPU (or its memory)
              </text>
              <text x={GX + 360} y={chartH - 4} fill={C.amber}>
                ┅ sessions holding a GPU memory slot while their QPU job waits or runs
              </text>
            </g>
            <line x1={x(t)} x2={x(t)} y1={y(qMax)} y2={y(0)} stroke="#ebeff7" strokeWidth="1.5" />
          </svg>
          <svg className="flow-gantt" viewBox={`0 0 1200 ${wfH}`} role="img" aria-label="Timeline of every task and where it waits">
            <text x="8" y="14" fill="#b3bccf" fontSize="12" fontWeight="600">
              Every task, left to right: running or waiting
            </text>
            {run.tasks.map((r, i) => (
              <g key={r.spec.id}>
                <text x="8" y={32 + i * ROW} fill="#8691aa" fontSize="10.5">
                  #{r.spec.id} {ARCHE_NAME[r.spec.arche]}
                  {LAYOUTS[layout].groups > 1 ? ` · node ${r.group + 1}` : ''}
                </text>
                <rect x={GX} y={22 + i * ROW} width={GW} height={ROW - 3} fill="#0f1626" />
                {r.segs.map((s, j) => (
                  <rect key={j} x={x(s.t0)} y={22 + i * ROW} width={Math.max(1, x(s.t1) - x(s.t0))} height={ROW - 3} fill={SEG_COLOR[s.state]} />
                ))}
                <rect x={x(r.spec.arrival) - 1} y={22 + i * ROW} width="2" height={ROW - 3} fill="#ebeff7" opacity="0.6" />
              </g>
            ))}
            <line x1={x(t)} x2={x(t)} y1="20" y2={wfH - 4} stroke="#ebeff7" strokeWidth="1.5" />
          </svg>
          <h4 className="panel-title" style={{ marginTop: 14 }}>
            Most delayed tasks in “{TITLE[layout]}”
          </h4>
          <ul className="flow-stuck">
            {stuck.map(({ r, total }) => (
              <li key={r.spec.id}>
                <strong>
                  #{r.spec.id} {TASKS[r.spec.arche].label.toLowerCase()}
                </strong>
                : waited {secsLabel(total)} in total, mostly for {r.stuckAt}.
              </li>
            ))}
          </ul>
        </details>

        <p className="fine">
          Toy model: every layout has the same total capacity ({TOY_CAPACITY.gpuCompute} GPU slots, {TOY_CAPACITY.cpu} tool slots, {TOY_CAPACITY.qpu} QPUs, and {memSlots} GPU memory slots).
          A task keeps one GPU memory slot while it is on its GPU node (LLM steps and tool calls). Parking memory is used only while a QPU job waits or runs, and only in the
          layout with parking; without it, and on the mixed nodes, the session keeps its slot. A QPU queue longer than 30 minutes would be run classically; that is not modelled
          here. At pod scale our simulation found parking and holding within 0.5% of each other, because only a tiny share of sessions wait on a QPU at any moment; this toy makes
          that share large, and GPU memory scarce, so the mechanism shows.
        </p>
      </div>
    </section>
  );
}
