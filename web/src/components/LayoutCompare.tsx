import { useMemo, useState } from 'react';
import { LAYOUTS, TASK_MIX, TOY_CAPACITY, makeTasks, simulate, stateAt, type ArrivalPattern, type LayoutId, type LayoutRun, type SegState } from '../model/layouts.ts';
import { TASKS, secsLabel, type TaskKind } from '../model/taskflow.ts';

const C = { gpu: '#22d3ee', tool: '#8691aa', qpu: '#d946ef', amber: '#e69f00', red: '#f07575' };
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
const LEGEND: Array<[string, string]> = [
  ['LLM step on a GPU', C.gpu],
  ['tool in the CPU sandbox', C.tool],
  ['running on a QPU', C.qpu],
  ['waiting in the QPU queue (parked)', 'url(#stripe-qpu)'],
  ['waiting in the QPU queue, holding a GPU memory slot', 'url(#stripe-held)'],
  ['waiting: GPU memory held by others', 'url(#stripe-mem)'],
  ['waiting for a free GPU', C.red],
];
const ARCHE_SHORT: Record<TaskKind, string> = { inference: 'inference', mixed: 'mixed', sim: 'sim-heavy' };
const ORDER: LayoutId[] = ['current', 'noPark', 'mixed'];

export function LayoutCompare() {
  const [pattern, setPattern] = useState<ArrivalPattern>('spread');
  const [layout, setLayout] = useState<LayoutId>('current');
  const [cursor, setCursor] = useState(0.5);

  const runs = useMemo(() => {
    const tasks = makeTasks(pattern);
    return Object.fromEntries(ORDER.map((id) => [id, simulate(id, tasks)])) as Record<LayoutId, LayoutRun>;
  }, [pattern]);
  const horizon = Math.max(...ORDER.map((id) => runs[id].makespan));
  const run = runs[layout];
  const t = cursor * horizon;
  const qMax = Math.max(4, ...ORDER.flatMap((id) => runs[id].samples.map((s) => Math.max(s.qLlm, s.qQpu, s.qTool, s.memHeldIdle))));

  const GX = 112;
  const GW = 1200 - GX - 16;
  const x = (sec: number) => GX + (sec / horizon) * GW;
  const ROW = 13;
  const wfH = run.tasks.length * ROW + 26;
  const chartH = 150;
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

  const now = stateAt(run, t);
  const counts = {
    run: now.filter((s) => s.kind === 'run').length,
    waitQpu: now.filter((s) => s.state.includes('QPU queue') && s.kind === 'wait').length,
    held: now.filter((s) => s.kind === 'held').length,
    waitGpuMem: now.filter((s) => s.state.includes('memory is held')).length,
    waitGpu: now.filter((s) => s.state === 'waiting for a free GPU').length,
    waitTool: now.filter((s) => s.state === 'waiting for the CPU sandbox').length,
    done: now.filter((s) => s.kind === 'done').length,
  };
  const stuck = [...run.tasks]
    .map((r) => ({ r, total: r.wait.llm + r.wait.tool + r.wait.qpu }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 5);

  return (
    <section className="flow" aria-labelledby="layout-title">
      <div className="section-head">
        <h2 id="layout-title">Where do tasks get stuck? Three layouts, the same 24 tasks</h2>
        <p>
          A toy simulation with {TOY_CAPACITY.gpuCompute} GPU slots, {TOY_CAPACITY.gpuMemory} GPU memory slots, {TOY_CAPACITY.cpu} CPU sandbox slots and {TOY_CAPACITY.qpu} QPUs in
          every layout, fed {TASK_MIX.inference} pure-inference, {TASK_MIX.mixed} mixed and {TASK_MIX.sim} simulation-heavy tasks. Capacities are toy values chosen to make
          contention visible; the mechanisms, not the sizes, are the point.
        </p>
      </div>

      <div className="card flow-card">
        <div className="flow-controls">
          <div className="seg" role="radiogroup" aria-label="Arrival pattern">
            {(['spread', 'burst'] as ArrivalPattern[]).map((p) => (
              <button key={p} role="radio" aria-checked={pattern === p} className={`seg-btn${pattern === p ? ' is-on' : ''}`} onClick={() => setPattern(p)}>
                <span className="seg-text">
                  {p === 'spread' ? 'Tasks spread over 8 min' : 'Tasks arrive within 2 min'}
                  <small>{p === 'spread' ? 'steady load' : 'burst'}</small>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="table-wrap">
          <table className="flow-table">
            <thead>
              <tr>
                <th>Layout</th>
                <th>All done after</th>
                <th>Inference task, mean</th>
                <th>Mixed task, mean</th>
                <th>Sim-heavy task, mean</th>
                <th>Peak QPU queue</th>
                <th>Peak GPU queue</th>
                <th>QPU busy</th>
                <th>QPU idle while another queue waits</th>
                <th>Main bottleneck</th>
              </tr>
            </thead>
            <tbody>
              {ORDER.map((id) => {
                const s = runs[id].summary;
                const slow = s.meanBy.inference / s.unloadedBy.inference;
                return (
                  <tr key={id} className={id === layout ? 'is-on' : undefined}>
                    <th scope="row">
                      <button className="link-btn" onClick={() => setLayout(id)}>
                        {LAYOUTS[id].label}
                      </button>
                    </th>
                    <td>{secsLabel(runs[id].makespan)}</td>
                    <td>
                      {secsLabel(s.meanBy.inference)} <small className="muted">({slow.toFixed(1)}× its unloaded time)</small>
                    </td>
                    <td>{secsLabel(s.meanBy.mixed)}</td>
                    <td>{secsLabel(s.meanBy.sim)}</td>
                    <td>{s.peakQQpu}</td>
                    <td>{s.peakQLlm}</td>
                    <td>{Math.round(s.qpuUtil * 100)}%</td>
                    <td>{secsLabel(s.strandedQpuSecs)}</td>
                    <td>{s.bottleneck}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="seg" role="tablist" aria-label="Layout to inspect" style={{ marginTop: 16 }}>
          {ORDER.map((id) => (
            <button key={id} role="tab" aria-selected={layout === id} className={`seg-btn${layout === id ? ' is-on' : ''}`} onClick={() => setLayout(id)}>
              <span className="seg-text">
                {LAYOUTS[id].label}
                <small>{LAYOUTS[id].blurb}</small>
              </span>
            </button>
          ))}
        </div>

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
          <path d={line((s) => s.qTool)} fill="none" stroke={C.tool} strokeWidth="2" />
          <path d={line((s) => s.qLlm)} fill="none" stroke={C.gpu} strokeWidth="2.5" />
          <path d={line((s) => s.qQpu)} fill="none" stroke={C.qpu} strokeWidth="2.5" />
          <g fontSize="11">
            <text x={GX + 8} y={chartH - 4} fill={C.qpu}>
              ━ waiting for a QPU
            </text>
            <text x={GX + 150} y={chartH - 4} fill={C.gpu}>
              ━ waiting for a GPU
            </text>
            <text x={GX + 290} y={chartH - 4} fill={C.tool}>
              ━ waiting for the CPU sandbox
            </text>
            <text x={GX + 480} y={chartH - 4} fill={C.amber}>
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
                #{r.spec.id} {ARCHE_SHORT[r.spec.arche]}
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

        <div className="flow-legend">
          {LEGEND.map(([label, fill]) => (
            <span key={label}>
              <svg width="14" height="10" aria-hidden="true">
                <rect width="14" height="10" fill={fill} />
              </svg>
              {label}
            </span>
          ))}
          <span>
            <svg width="14" height="10" aria-hidden="true">
              <rect width="2" height="10" x="6" fill="#ebeff7" />
            </svg>
            task arrives
          </span>
        </div>

        <div className="flow-bar">
          <span className="muted">Time</span>
          <input type="range" min={0} max={1} step={0.002} value={cursor} aria-label="Move through time" onChange={(e) => setCursor(Number(e.target.value))} />
          <strong className="flow-time">t = {secsLabel(t)}</strong>
        </div>

        <div className="flow-tiles">
          <div className="tile">
            <span>Running</span>
            <strong>{counts.run}</strong>
          </div>
          <div className="tile">
            <span>Waiting for a QPU (parked)</span>
            <strong>{counts.waitQpu}</strong>
          </div>
          <div className="tile">
            <span>Waiting for a QPU, holding GPU memory</span>
            <strong>{counts.held}</strong>
          </div>
          <div className="tile">
            <span>Blocked by held GPU memory</span>
            <strong>{counts.waitGpuMem}</strong>
          </div>
          <div className="tile">
            <span>Waiting for a free GPU / CPU</span>
            <strong>
              {counts.waitGpu} / {counts.waitTool}
            </strong>
          </div>
          <div className="tile">
            <span>Done</span>
            <strong>
              {counts.done} of {now.length}
            </strong>
          </div>
        </div>

        <h3 className="panel-title" style={{ marginTop: 18 }}>
          Most stuck tasks in “{LAYOUTS[layout].label}”
        </h3>
        <ul className="flow-stuck">
          {stuck.map(({ r, total }) => (
            <li key={r.spec.id}>
              <strong>
                #{r.spec.id} {TASKS[r.spec.arche].label.toLowerCase()}
              </strong>
              : waited {secsLabel(total)} in total, mostly for {r.stuckAt}
              {r.heldIdle > 0 ? ` (held a GPU memory slot idle for ${secsLabel(r.heldIdle)})` : ''}.
            </li>
          ))}
        </ul>

        <p className="fine">
          Toy model: each layout has the same total capacity. “Current layout” frees a task’s GPU memory slot while it waits for a QPU; “No parking” keeps it;
          “Mixed nodes” splits the pod into three nodes, each with one QPU, and a task can only use its own node’s QPU. A QPU queue longer than 30 minutes would
          be run classically instead; that rule is not modelled here. At pod scale our simulation found parking and holding within 0.5% of each other, because
          only a tiny share of sessions wait on a QPU at any moment; this toy exaggerates that share so the mechanism is visible.
        </p>
      </div>
    </section>
  );
}
