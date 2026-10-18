import { useEffect, useMemo, useRef, useState } from 'react';
import {
  QUEUES,
  TASKS,
  buildFlow,
  secsLabel,
  totals,
  weight,
  type NodeId,
  type QueueState,
  type SegKind,
  type Segment,
  type TaskKind,
  type WaitMode,
} from '../model/taskflow.ts';

const PLAY_SECONDS = 16; // wall-clock length of a full playback
const NODES: Record<NodeId, { x: number; y: number; title: string; sub: string }> = {
  sched: { x: 40, y: 50, title: 'Scheduler node', sub: 'picks the node and the path' },
  gpu: { x: 490, y: 50, title: 'GPU node pool', sub: 'prefill + decode' },
  ctx: { x: 490, y: 190, title: 'Context memory', sub: 'parked sessions, tool waits' },
  qpu: { x: 940, y: 50, title: 'Shared QPU service', sub: 'queue + run' },
};
const W = 200;
const H = 66;
const COLORS = { gpu: '#22d3ee', park: '#e69f00', tool: '#8691aa', qpu: '#d946ef' };

const KIND_COLOR: Record<SegKind, string> = {
  schedule: '#8691aa',
  llm: COLORS.gpu,
  tool: COLORS.tool,
  park: COLORS.park,
  wait: COLORS.qpu,
  qpu: COLORS.qpu,
  held: COLORS.park,
  resume: COLORS.gpu,
  done: '#3ccf3c',
};

/** Where a dot sits: just below its node (session on the left, job on the right). */
function dotPos(id: NodeId, side: 'session' | 'job'): [number, number] {
  const n = NODES[id];
  return [side === 'session' ? n.x + 26 : n.x + W - 26, n.y + H + 17];
}

const EDGES: Array<[NodeId, NodeId, boolean]> = [
  ['sched', 'gpu', false],
  ['gpu', 'ctx', true],
  ['ctx', 'qpu', false],
  ['gpu', 'qpu', false],
];

function edgePath(a: NodeId, b: NodeId): string {
  const A = NODES[a];
  const B = NODES[b];
  const ax = A.x + W / 2;
  const ay = A.y + H / 2;
  const bx = B.x + W / 2;
  const by = B.y + H / 2;
  if (A.y === B.y) return `M${A.x + (B.x > A.x ? W : 0)} ${ay} L${B.x + (B.x > A.x ? 0 : W)} ${by}`;
  if (A.x === B.x) return `M${ax} ${ay + (by > ay ? H / 2 : -H / 2)} L${bx} ${by + (by > ay ? -H / 2 : H / 2)}`;
  return `M${A.x + W} ${ay} L${B.x} ${by}`;
}

export function TaskFlow() {
  const [task, setTask] = useState<TaskKind>('mixed');
  const [mode, setMode] = useState<WaitMode>('park');
  const [queue, setQueue] = useState<QueueState>('short');
  const [pos, setPos] = useState(0);
  const [playing, setPlaying] = useState(false);
  const raf = useRef<number | null>(null);

  const segs = useMemo(() => buildFlow(task, mode, queue), [task, mode, queue]);
  const widths = useMemo(() => segs.map((s) => weight(s.secs)), [segs]);
  const total = useMemo(() => widths.reduce((a, b) => a + b, 0), [widths]);
  const starts = useMemo(() => {
    let acc = 0;
    return widths.map((w) => {
      const s = acc;
      acc += w;
      return s;
    });
  }, [widths]);
  const realStarts = useMemo(() => {
    let acc = 0;
    return segs.map((s) => {
      const r = acc;
      acc += s.secs;
      return r;
    });
  }, [segs]);
  const tot = useMemo(() => totals(segs), [segs]);

  // restart when the task changes
  useEffect(() => {
    setPos(0);
    setPlaying(false);
  }, [task, mode, queue]);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setPos((p) => {
        const np = p + (dt * total) / PLAY_SECONDS;
        if (np >= total) {
          setPlaying(false);
          return total;
        }
        return np;
      });
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [playing, total]);

  let idx = starts.findIndex((s, i) => pos >= s && pos < s + widths[i]!);
  if (idx < 0) idx = segs.length - 1;
  const cur: Segment = segs[idx]!;
  const finished = pos >= total - 1e-6;
  const sessionAt = cur.session;
  const lastSession = useMemo(() => {
    for (let i = idx; i >= 0; i--) if (segs[i]!.session) return segs[i]!.session as NodeId;
    return 'sched' as NodeId;
  }, [segs, idx]);
  const sessionNode: NodeId = sessionAt ?? lastSession;
  const jobNode = cur.job;
  const progress = (pos - starts[idx]!) / widths[idx]!;
  const realNow = realStarts[idx]! + cur.secs * Math.min(1, Math.max(0, progress));

  const GX = 130;
  const GW = 1200 - GX - 20;
  const gx = (w: number) => GX + (w / total) * GW;
  const rows: Array<{ key: string; label: string; match: (s: Segment) => boolean }> = [
    { key: 'gpu', label: 'GPU reserved', match: (s) => s.gpuReserved },
    { key: 'ctx', label: 'In context memory', match: (s) => s.session === 'ctx' },
    { key: 'qpu', label: 'QPU', match: (s) => s.job === 'qpu' },
  ];

  const nodeActive = (id: NodeId) => id === sessionNode || id === jobNode;

  return (
    <section className="flow" aria-labelledby="flow-title">
      <div className="section-head">
        <h2 id="flow-title">Follow one task through the data center</h2>
        <p>
          Pick a task, press play, and watch where its session (cyan dot) and any offloaded job (magenta dot) sit. This is an illustration with
          assumed durations, not a measurement; bar widths are compressed.
        </p>
      </div>

      <div className="card flow-card">
        <div className="flow-controls">
          <div className="seg" role="radiogroup" aria-label="Task type">
            {(Object.keys(TASKS) as TaskKind[]).map((k) => (
              <button key={k} role="radio" aria-checked={task === k} className={`seg-btn${task === k ? ' is-on' : ''}`} onClick={() => setTask(k)}>
                <span className="seg-text">
                  {TASKS[k].label}
                  <small>{TASKS[k].calls === 0 ? 'no QPU call' : `${TASKS[k].calls} QPU call${TASKS[k].calls > 1 ? 's' : ''}`}</small>
                </span>
              </button>
            ))}
          </div>
          <div className="flow-opts">
            <div className="seg" role="radiogroup" aria-label="What the session does while the QPU job runs">
              {(['park', 'hold'] as WaitMode[]).map((m) => (
                <button key={m} role="radio" aria-checked={mode === m} className={`seg-btn${mode === m ? ' is-on' : ''}`} onClick={() => setMode(m)} disabled={TASKS[task].calls === 0}>
                  <span className="seg-text">
                    {m === 'park' ? 'Park the session' : 'Hold the GPU'}
                    <small>{m === 'park' ? 'GPU released' : 'GPU stays reserved'}</small>
                  </span>
                </button>
              ))}
            </div>
            <div className="seg" role="radiogroup" aria-label="QPU queue state">
              {(Object.keys(QUEUES) as QueueState[]).map((q) => (
                <button key={q} role="radio" aria-checked={queue === q} className={`seg-btn${queue === q ? ' is-on' : ''}`} onClick={() => setQueue(q)} disabled={TASKS[task].calls === 0}>
                  <span className="seg-text">
                    {QUEUES[q].label}
                    <small>{QUEUES[q].blurb}</small>
                  </span>
                </button>
              ))}
            </div>
          </div>
          <p className="flow-blurb">{TASKS[task].blurb}</p>
        </div>

        <svg className="flow-svg" viewBox="0 0 1200 300" role="img" aria-label="Where the task is now in the data center">
          <defs>
            <marker id="fa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0 0 L10 5 L0 10 z" fill="#4a5470" />
            </marker>
            <pattern id="hold" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="#3a2a05" />
              <rect width="3" height="6" fill="#e69f00" opacity="0.55" />
            </pattern>
          </defs>
          {EDGES.map(([a, b, both]) => (
            <path key={`${a}-${b}`} d={edgePath(a, b)} stroke="#3a4463" strokeWidth="2" fill="none" markerEnd="url(#fa)" markerStart={both ? 'url(#fa)' : undefined} />
          ))}
          <path d="M4 83 H36" stroke="#4a5470" strokeWidth="2" markerEnd="url(#fa)" />
          <text x="4" y="73" fill="#8691aa" fontSize="12">
            task
          </text>
          {(Object.keys(NODES) as NodeId[]).map((id) => {
            const n = NODES[id];
            const on = nodeActive(id);
            const accent = id === 'qpu' ? COLORS.qpu : id === 'ctx' ? COLORS.park : COLORS.gpu;
            return (
              <g key={id}>
                <rect x={n.x} y={n.y} width={W} height={H} rx="12" fill={on ? '#16203a' : '#111828'} stroke={on ? accent : 'rgba(255,255,255,0.14)'} strokeWidth={on ? 2.5 : 1} />
                <text x={n.x + 16} y={n.y + 28} fill="#ebeff7" fontSize="15" fontWeight="650">
                  {n.title}
                </text>
                <text x={n.x + 16} y={n.y + 48} fill="#8691aa" fontSize="12">
                  {n.sub}
                </text>
              </g>
            );
          })}
          {/* QPU run pulse */}
          {cur.kind === 'qpu' && !finished && <circle cx={NODES.qpu.x + W - 24} cy={NODES.qpu.y + 22} r="7" fill={COLORS.qpu} className="pulse" />}
          {/* job dot */}
          {jobNode && (
            <g style={{ transform: `translate(${dotPos(jobNode, 'job')[0]}px, ${dotPos(jobNode, 'job')[1]}px)` }} className="dot-move">
              <circle r="9" fill={COLORS.qpu} stroke="#0c111d" strokeWidth="2" />
              <text x="-16" y="4" fill={COLORS.qpu} fontSize="11" fontWeight="600" textAnchor="end">
                job
              </text>
            </g>
          )}
          {/* session dot */}
          <g style={{ transform: `translate(${dotPos(sessionNode, 'session')[0]}px, ${dotPos(sessionNode, 'session')[1]}px)`, opacity: sessionAt || (!finished && cur.kind !== 'done') ? 1 : 0.0 }} className="dot-move">
            <circle r="10" fill={cur.kind === 'held' || (cur.kind === 'qpu' && mode === 'hold') ? COLORS.park : COLORS.gpu} stroke="#0c111d" strokeWidth="2" />
            <text x="17" y="4" fill="#ebeff7" fontSize="11" fontWeight="600">
              session
            </text>
          </g>
        </svg>

        <div className="flow-now" aria-live="polite">
          <span className="flow-dot" style={{ background: KIND_COLOR[cur.kind] }} aria-hidden="true" />
          <strong>{finished && cur.kind === 'done' ? 'Done' : cur.label}</strong>
          <span className="muted">{cur.detail}</span>
          <span className="flow-time">t = {secsLabel(realNow)}</span>
        </div>

        <svg className="flow-gantt" viewBox={`0 0 1200 ${rows.length * 30 + 34}`} role="img" aria-label="Timeline of resources used by the task">
          {rows.map((r, i) => (
            <g key={r.key}>
              <text x="8" y={26 + i * 30} fill="#b3bccf" fontSize="12">
                {r.label}
              </text>
              <rect x={GX} y={12 + i * 30} width={GW} height="22" rx="4" fill="#0f1626" />
              {segs.map((s, j) => {
                if (!r.match(s)) return null;
                const idle = r.key === 'gpu' && s.gpuReserved && !s.gpuBusy;
                const color = r.key === 'gpu' ? (idle ? 'url(#hold)' : COLORS.gpu) : r.key === 'ctx' ? (s.kind === 'tool' ? COLORS.tool : COLORS.park) : s.kind === 'wait' ? '#6b2a78' : COLORS.qpu;
                return <rect key={j} x={gx(starts[j]!)} y={14 + i * 30} width={Math.max(2, gx(starts[j]! + widths[j]!) - gx(starts[j]!) - 1)} height="18" rx="3" fill={color} opacity={j <= idx ? 1 : 0.38} />;
              })}
            </g>
          ))}
          <line x1={gx(pos)} x2={gx(pos)} y1="6" y2={rows.length * 30 + 14} stroke="#ebeff7" strokeWidth="2" />
          <text x={GX} y={rows.length * 30 + 30} fill="#8691aa" fontSize="11">
            schematic time axis: wide bars are long in reality (labels give real durations); striped amber = GPU reserved but idle
          </text>
        </svg>

        <div className="flow-bar">
          <button className="flow-btn" onClick={() => (finished ? (setPos(0), setPlaying(true)) : setPlaying(!playing))}>
            {finished ? 'Replay' : playing ? 'Pause' : 'Play'}
          </button>
          <input
            type="range"
            min={0}
            max={total}
            step={total / 400}
            value={pos}
            aria-label="Scrub through the task"
            onChange={(e) => {
              setPlaying(false);
              setPos(Number(e.target.value));
            }}
          />
        </div>

        <div className="flow-tiles">
          <div className="tile">
            <span>Task time</span>
            <strong>{secsLabel(tot.elapsed)}</strong>
          </div>
          <div className="tile">
            <span>GPU busy</span>
            <strong>{secsLabel(tot.gpuBusy)}</strong>
          </div>
          <div className="tile">
            <span>GPU reserved but idle</span>
            <strong>{secsLabel(tot.gpuHeldIdle)}</strong>
          </div>
          <div className="tile">
            <span>In context memory</span>
            <strong>{secsLabel(tot.parked)}</strong>
          </div>
          <div className="tile">
            <span>QPU busy</span>
            <strong>{secsLabel(tot.qpuBusy)}</strong>
          </div>
        </div>

        <details className="flow-log">
          <summary>Event log</summary>
          <ol>
            {segs.map((s, j) => (
              <li key={j} className={j === idx ? 'is-now' : undefined}>
                <span className="flow-dot" style={{ background: KIND_COLOR[s.kind] }} aria-hidden="true" />
                <span className="flow-t">{secsLabel(realStarts[j]!)}</span>
                <strong>{s.label}</strong> <span className="muted">{s.detail}</span>
              </li>
            ))}
          </ol>
        </details>

        <p className="fine">
          Illustrative. QPU run times come from quantum_arch (40k cat-qubit QPU, mid-2030s base scenario): 44 s for a 50-qubit variational call, 227 s for a
          small chemistry call. LLM step (6 s), tool call (8 s), park (0.2 s), resume (about 1 s) and the queue waits are dc_sim assumptions. Tool calls run
          outside the nodes drawn here; the session waits in the context-memory pool meanwhile. In our pod simulation, parking and holding cost within 0.5% of
          each other at this call volume; parking matters when GPU memory is tight or QPU calls are frequent. Only a few of a task’s 80 steps are shown.
        </p>
      </div>
    </section>
  );
}
