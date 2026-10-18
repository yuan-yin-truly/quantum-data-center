import { useMemo, type ReactNode } from 'react';
import { MEMORY_OPTIONS, makeTasks, simulate, type LayoutId } from '../model/layouts.ts';
import { secsLabel } from '../model/taskflow.ts';

const C = { gpu: '#22d3ee', qpu: '#d946ef', park: '#e69f00', ink: '#ebeff7', mute: '#8691aa', line: '#3a4463', box: '#111828' };

function Box({ x, y, w, h, color, label, sub }: { x: number; y: number; w: number; h: number; color: string; label: string; sub?: string }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="8" fill={C.box} stroke={color} strokeWidth="1.5" />
      <text x={x + 8} y={y + 16} fill={C.ink} fontSize="11" fontWeight="650">
        {label}
      </text>
      {sub && (
        <text x={x + 8} y={y + 30} fill={C.mute} fontSize="9.5">
          {sub}
        </text>
      )}
    </g>
  );
}
function Racks({ x, y, n, color = C.gpu }: { x: number; y: number; n: number; color?: string }) {
  return (
    <g>
      {Array.from({ length: n }, (_, i) => (
        <rect key={i} x={x + i * 9} y={y} width="7" height="16" rx="1.5" fill={color} opacity="0.85" />
      ))}
    </g>
  );
}
function Cryo({ x, y, color = C.qpu }: { x: number; y: number; color?: string }) {
  return (
    <g>
      <rect x={x} y={y + 3} width="11" height="15" fill={color} />
      <ellipse cx={x + 5.5} cy={y + 3} rx="5.5" ry="2.6" fill="#f3a8f5" />
      <ellipse cx={x + 5.5} cy={y + 18} rx="5.5" ry="2.6" fill={color} />
    </g>
  );
}
function Arrow({ d, color = C.line, dashed = false }: { d: string; color?: string; dashed?: boolean }) {
  return <path d={d} stroke={color} strokeWidth="1.6" fill="none" strokeDasharray={dashed ? '4 3' : undefined} markerEnd="url(#pa)" />;
}

function Diagram({ children }: { children: ReactNode }) {
  return (
    <svg className="ap-svg" viewBox="0 0 300 150" role="img" aria-hidden="true">
      <defs>
        <marker id="pa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill="#6c7898" />
        </marker>
      </defs>
      {children}
    </svg>
  );
}

const SCHED = <Box x={2} y={52} w={66} h={40} color={C.line} label="Sched." sub="node" />;

function Traditional() {
  return (
    <Diagram>
      {SCHED}
      <Arrow d="M66 72 H100" />
      <Box x={100} y={30} w={190} h={84} color={C.gpu} label="GPU racks" sub="LLM steps and every tool call" />
      <Racks x={110} y={72} n={14} />
      <text x={110} y={136} fill={C.mute} fontSize="9.5">
        QPU-eligible calls run on GPUs
      </text>
    </Diagram>
  );
}
function Mixed() {
  return (
    <Diagram>
      {SCHED}
      <Arrow d="M66 72 H80" />
      {[0, 1, 2].map((i) => (
        <g key={i}>
          <rect x={84 + i * 72} y={22} width={66} height={96} rx="8" fill={C.box} stroke={C.line} strokeWidth="1.5" />
          <text x={90 + i * 72} y={38} fill={C.ink} fontSize="10" fontWeight="650">
            Node {i + 1}
          </text>
          <Racks x={90 + i * 72} y={46} n={5} />
          <Cryo x={96 + i * 72} y={78} />
          <text x={112 + i * 72} y={92} fill={C.mute} fontSize="9">
            QPU
          </text>
        </g>
      ))}
      <text x={84} y={138} fill={C.mute} fontSize="9.5">
        a task stays on its node and its QPU
      </text>
    </Diagram>
  );
}
function SeparatedNoPark() {
  return (
    <Diagram>
      {SCHED}
      <Arrow d="M66 72 H88" />
      <Box x={88} y={24} w={96} h={88} color={C.gpu} label="GPU node pool" sub="shared" />
      <Racks x={96} y={74} n={8} />
      <Box x={212} y={24} w={84} h={88} color={C.qpu} label="QPU service" sub="shared" />
      <Cryo x={224} y={66} />
      <Cryo x={244} y={66} />
      <Cryo x={264} y={66} />
      <Arrow d="M184 56 H212" color={C.qpu} />
      <path d="M100 118 C100 138 190 138 190 118" stroke={C.park} strokeWidth="1.6" fill="none" strokeDasharray="4 3" />
      <text x={104} y={146} fill={C.park} fontSize="9.5">
        session keeps its GPU memory slot
      </text>
    </Diagram>
  );
}
function SeparatedPark() {
  return (
    <Diagram>
      {SCHED}
      <Arrow d="M66 72 H80" />
      <Box x={80} y={14} w={96} h={62} color={C.gpu} label="GPU node pool" sub="shared" />
      <Racks x={88} y={50} n={8} />
      <Box x={212} y={14} w={84} h={62} color={C.qpu} label="QPU service" sub="shared" />
      <Cryo x={224} y={46} />
      <Cryo x={244} y={46} />
      <Cryo x={264} y={46} />
      <Arrow d="M176 38 H212" color={C.qpu} />
      <Box x={110} y={96} w={140} h={44} color={C.park} label="Parking memory" sub="QPU jobs only" />
      <Arrow d="M128 76 V96" color={C.park} />
      <Arrow d="M220 96 V76" color={C.park} dashed />
    </Diagram>
  );
}

export function ArchPanel() {
  // numbers come from the toy simulation shown further down (burst, tight GPU memory)
  const runs = useMemo(() => {
    const tasks = makeTasks('burst');
    return Object.fromEntries((['current', 'noPark', 'mixed'] as LayoutId[]).map((id) => [id, simulate(id, tasks, MEMORY_OPTIONS.tight)])) as Record<LayoutId, ReturnType<typeof simulate>>;
  }, []);
  const infX = (id: LayoutId) => (runs[id].summary.meanBy.inference / runs[id].summary.unloadedBy.inference).toFixed(1);
  const cards: Array<{ title: string; tag: string; diagram: ReactNode; qpuCall: string; good: string; bad: string }> = [
    {
      title: 'Traditional data center',
      tag: 'GPU racks only',
      diagram: <Traditional />,
      qpuCall: 'Runs classically on the GPUs. A call that would cost more than about 200 GPU-hours is not served at all.',
      good: 'Simple, no cryostats. Best when the classical method is cheap.',
      bad: 'Expensive science calls either eat a lot of GPU capacity or go unserved. In our pod example 12,000 chemistry calls a day are unserved.',
    },
    {
      title: 'Mixed nodes',
      tag: 'GPUs and a QPU in every node',
      diagram: <Mixed />,
      qpuCall: 'Goes to the QPU of the task’s own node; the session keeps its GPU memory slot meanwhile.',
      good: 'Shortest path for quantum-classical loops: no network hop, which matters above about 100,000 optimiser round trips per call.',
      bad: `A QPU cannot serve another node. In the toy below QPUs are busy only ${Math.round(runs.mixed.summary.qpuUtil * 100)}% of the time, and all tasks finish after ${secsLabel(runs.mixed.makespan)} instead of ${secsLabel(runs.current.makespan)}. One QPU per server is also unaffordable at about 270 kW each.`,
    },
    {
      title: 'Separated, no parking memory',
      tag: 'shared GPU pool + shared QPU service',
      diagram: <SeparatedNoPark />,
      qpuCall: 'Goes to the shared QPU service. The session keeps its GPU memory slot while the job waits or runs.',
      good: `QPUs are shared, so they stay busy (${Math.round(runs.noPark.summary.qpuUtil * 100)}% in the toy), and there is no extra memory pool.`,
      bad: `Sessions waiting for a QPU hold GPU memory. With tight memory the toy’s inference tasks take ${infX('noPark')}× their unloaded time. With roomy memory the effect disappears.`,
    },
    {
      title: 'Separated, with parking memory',
      tag: 'shared GPU pool + QPU service + parking memory',
      diagram: <SeparatedPark />,
      qpuCall: 'The session moves to the parking memory and frees its GPU memory slot, then resumes on any GPU node when the result is back. Only QPU jobs use the parking memory.',
      good: `GPU memory stays free for other tasks: inference tasks take ${infX('current')}× their unloaded time in the same toy run.`,
      bad: 'Needs a parking memory pool and about a second to resume. In our pod simulation the saving is within 0.5% when GPU memory is roomy and QPU calls are rare.',
    },
  ];
  return (
    <section className="flow" aria-labelledby="ap-title">
      <div className="section-head">
        <h2 id="ap-title">Four ways to build it</h2>
        <p>The same work, four architectures. The two simulations below follow the three that include QPUs.</p>
      </div>
      <div className="ap-grid">
        {cards.map((c) => (
          <article key={c.title} className="ap-card">
            <h3>{c.title}</h3>
            <p className="ap-tag">{c.tag}</p>
            {c.diagram}
            <dl>
              <dt>A QPU-eligible call</dt>
              <dd>{c.qpuCall}</dd>
              <dt className="good">Strength</dt>
              <dd>{c.good}</dd>
              <dt className="bad">Weakness</dt>
              <dd>{c.bad}</dd>
            </dl>
          </article>
        ))}
      </div>
      <p className="fine" style={{ marginTop: 10 }}>
        Toy figures come from the burst scenario with tight GPU memory in the simulation below; pod-scale figures come from our dc_design study. Both rest on assumed call densities and
        classical costs.
      </p>
    </section>
  );
}
