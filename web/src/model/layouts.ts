// TOY discrete-event simulation: the same 24 tasks (3 archetypes) on three data-center layouts.
// A task keeps a GPU memory slot while it is on its GPU node (LLM steps and tool calls). Parking memory is used ONLY
// for sessions whose QPU job is waiting or running, and only in the layout with parking.
// Capacities are toy values chosen so contention is visible; durations follow web/src/model/taskflow.ts
// (QPU run times from quantum_arch, the rest dc_sim assumptions). It shows mechanisms, not pod-scale results.

import { LLM_STEP_S, PARK_S, QPU_CHEMISTRY_S, QPU_MATERIALS_S, RESUME_S, TOOL_S, type TaskKind } from './taskflow.ts';

export type LayoutId = 'current' | 'noPark' | 'mixed';
export type ArrivalPattern = 'spread' | 'burst';
export type ResKind = 'llm' | 'tool' | 'qpu';
export type SegState = 'run-llm' | 'run-tool' | 'run-qpu' | 'wait-llm-compute' | 'wait-llm-memory' | 'wait-tool' | 'wait-qpu' | 'held-wait-qpu';

export const LAYOUTS: Record<LayoutId, { label: string; blurb: string; groups: number; park: boolean }> = {
  current: { label: 'Current layout', blurb: 'Pooled GPU nodes, shared QPU service, sessions park while a QPU job waits or runs.', groups: 1, park: true },
  noPark: { label: 'No parking', blurb: 'Same pools, but a session keeps its GPU memory slot while its QPU job waits or runs.', groups: 1, park: false },
  mixed: { label: 'Mixed nodes', blurb: 'Three nodes, each with its own GPUs, CPU sandbox and one QPU; a task stays on its node.', groups: 3, park: false },
};

/** Toy capacities of the WHOLE pod (split evenly over the groups of a layout). */
export const TOY_CAPACITY = { gpuCompute: 6, gpuMemory: 9, cpu: 6, qpu: 3 };
/** GPU memory slots of the whole pod: tight makes held sessions hurt, roomy hides the effect. */
export const MEMORY_OPTIONS = { tight: 9, roomy: 24 } as const;

export interface Op {
  kind: ResKind;
  dur: number;
}
export interface TaskSpec {
  id: number;
  arche: TaskKind;
  arrival: number;
  ops: Op[];
}
export interface Seg {
  state: SegState;
  t0: number;
  t1: number;
}
export interface TaskResult {
  spec: TaskSpec;
  group: number;
  segs: Seg[];
  /** intervals during which the task occupied a GPU memory slot */
  mem: Array<[number, number]>;
  start: number;
  end: number;
  wait: Record<ResKind, number>;
  waitMemory: number;
  heldIdle: number;
  stuckAt: string;
}
export interface Sample {
  t: number;
  qLlm: number;
  qTool: number;
  qQpu: number;
  memHeldIdle: number;
  gpuBusy: number;
  qpuBusy: number;
  qpuStranded: number;
}
export interface LayoutRun {
  layout: LayoutId;
  tasks: TaskResult[];
  samples: Sample[];
  makespan: number;
  summary: {
    meanBy: Record<TaskKind, number>;
    unloadedBy: Record<TaskKind, number>;
    peakQLlm: number;
    peakQQpu: number;
    peakHeld: number;
    qpuUtil: number;
    strandedQpuSecs: number;
    waitTotals: { llmCompute: number; llmMemory: number; tool: number; qpu: number };
    bottleneck: string;
  };
}

function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const L = (): Op => ({ kind: 'llm', dur: LLM_STEP_S });
const T = (): Op => ({ kind: 'tool', dur: TOOL_S });

function opsFor(arche: TaskKind, jitter: () => number): Op[] {
  const q = (s: number): Op => ({ kind: 'qpu', dur: Math.round(s * (0.85 + 0.3 * jitter())) });
  if (arche === 'inference') return [L(), T(), L(), T(), L(), T(), L(), T(), L()];
  if (arche === 'mixed') return [L(), T(), L(), q(QPU_MATERIALS_S), L(), T(), L()];
  return [L(), T(), L(), q(QPU_CHEMISTRY_S), L(), L(), q(QPU_CHEMISTRY_S), L(), L(), q(QPU_CHEMISTRY_S), L(), T(), L()];
}

export const TASK_MIX: Record<TaskKind, number> = { inference: 10, mixed: 8, sim: 6 };

export function makeTasks(pattern: ArrivalPattern): TaskSpec[] {
  const r = rng(7);
  const kinds: TaskKind[] = [];
  (Object.keys(TASK_MIX) as TaskKind[]).forEach((k) => {
    for (let i = 0; i < TASK_MIX[k]; i++) kinds.push(k);
  });
  for (let i = kinds.length - 1; i > 0; i--) {
    const j = Math.floor(r() * (i + 1));
    [kinds[i], kinds[j]] = [kinds[j]!, kinds[i]!];
  }
  const window = pattern === 'spread' ? 480 : 120;
  const arrivals = kinds.map(() => r() * window).sort((a, b) => a - b);
  return kinds.map((arche, i) => ({ id: i + 1, arche, arrival: Math.round(arrivals[i]!), ops: opsFor(arche, r) }));
}

interface Group {
  free: { gpu: number; mem: number; cpu: number; qpu: number };
  cap: { gpu: number; mem: number; cpu: number; qpu: number };
  q: Record<ResKind, number[]>;
  assigned: number;
}
interface Live {
  spec: TaskSpec;
  group: number;
  idx: number;
  hasMem: boolean;
  memSince: number;
  mem: Array<[number, number]>;
  resumed: boolean;
  waitSince: number;
  blocked: 'compute' | 'memory';
  segs: Seg[];
  end: number;
  start: number;
}

export function simulate(layout: LayoutId, tasks: TaskSpec[], memorySlots: number = TOY_CAPACITY.gpuMemory): LayoutRun {
  const cfg = LAYOUTS[layout];
  const n = cfg.groups;
  const groups: Group[] = Array.from({ length: n }, () => {
    const cap = {
      gpu: TOY_CAPACITY.gpuCompute / n,
      mem: memorySlots / n,
      cpu: TOY_CAPACITY.cpu / n,
      qpu: TOY_CAPACITY.qpu / n,
    };
    return { free: { ...cap }, cap, q: { llm: [], tool: [], qpu: [] }, assigned: 0 };
  });
  const live: Live[] = tasks.map((spec) => ({ spec, group: 0, idx: 0, hasMem: false, memSince: 0, mem: [], resumed: false, waitSince: 0, blocked: 'compute', segs: [], end: 0, start: spec.arrival }));
  // event list: [time, order, kind, taskIndex]
  type Ev = [number, number, 'arrive' | 'end', number];
  const events: Ev[] = tasks.map((t, i) => [t.arrival, i, 'arrive', i]);
  let seq = tasks.length;
  const samples: Sample[] = [];
  let stranded = 0;
  let qpuBusySecs = 0;
  let lastT = 0;

  const takeMem = (l: Live, now: number) => {
    groups[l.group]!.free.mem--;
    l.hasMem = true;
    l.memSince = now;
  };
  const giveMem = (l: Live, now: number) => {
    if (!l.hasMem) return;
    groups[l.group]!.free.mem++;
    l.hasMem = false;
    l.mem.push([l.memSince, now]);
  };

  const snapshot = (t: number) => {
    let qLlm = 0, qTool = 0, qQpu = 0, held = 0, gpuBusy = 0, qpuBusy = 0;
    for (const g of groups) {
      qLlm += g.q.llm.length;
      qTool += g.q.tool.length;
      qQpu += g.q.qpu.length;
      gpuBusy += g.cap.gpu - g.free.gpu;
      qpuBusy += g.cap.qpu - g.free.qpu;
    }
    for (const l of live) if (l.hasMem && l.idx < l.spec.ops.length && l.spec.ops[l.idx]!.kind === 'qpu' && l.waitSince >= 0) held++;
    let str = 0;
    const someQueue = groups.some((g) => g.q.qpu.length > 0);
    if (someQueue) for (const g of groups) if (g.q.qpu.length === 0 && g.free.qpu > 0) str += g.free.qpu;
    samples.push({ t, qLlm, qTool, qQpu, memHeldIdle: held, gpuBusy, qpuBusy, qpuStranded: str });
    return { str, qpuBusy };
  };

  const enqueue = (li: number, now: number) => {
    const l = live[li]!;
    if (l.idx >= l.spec.ops.length) {
      l.end = now;
      giveMem(l, now);
      return;
    }
    l.waitSince = now;
    groups[l.group]!.q[l.spec.ops[l.idx]!.kind].push(li);
  };

  const tryStart = (gi: number, now: number) => {
    const g = groups[gi]!;
    let progress = true;
    while (progress) {
      progress = false;
      for (const kind of ['llm', 'tool', 'qpu'] as ResKind[]) {
        const queue = g.q[kind];
        for (let k = 0; k < queue.length; k++) {
          const li = queue[k]!;
          const l = live[li]!;
          const op = l.spec.ops[l.idx]!;
          let ok = false;
          if (kind === 'llm') {
            const needMem = !l.hasMem;
            if (g.free.gpu >= 1 && (!needMem || g.free.mem >= 1)) ok = true;
            else l.blocked = g.free.gpu >= 1 ? 'memory' : 'compute';
          } else if (kind === 'tool') ok = g.free.cpu >= 1;
          else ok = g.free.qpu >= 1;
          if (!ok) continue;
          queue.splice(k, 1);
          k--;
          progress = true;
          // close the waiting segment
          if (now > l.waitSince + 1e-9) {
            const prevHeld = kind === 'qpu' && l.hasMem;
            const state: SegState = kind === 'llm' ? (l.blocked === 'memory' ? 'wait-llm-memory' : 'wait-llm-compute') : kind === 'tool' ? 'wait-tool' : prevHeld ? 'held-wait-qpu' : 'wait-qpu';
            l.segs.push({ state, t0: l.waitSince, t1: now });
          }
          let dur = op.dur;
          if (kind === 'llm') {
            g.free.gpu--;
            if (!l.hasMem) takeMem(l, now);
            if (l.resumed) {
              dur += RESUME_S;
              l.resumed = false;
            }
          } else if (kind === 'tool') g.free.cpu--;
          else {
            g.free.qpu--;
            if (cfg.park) giveMem(l, now);
          }
          l.segs.push({ state: kind === 'llm' ? 'run-llm' : kind === 'tool' ? 'run-tool' : 'run-qpu', t0: now, t1: now + dur });
          events.push([now + dur, seq++, 'end', li]);
        }
      }
    }
  };

  const nextOp = (l: Live) => l.spec.ops[l.idx + 1];

  for (;;) {
    if (!events.length) break;
    events.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const [t, , type, li] = events.shift()!;
    // time-integrated metrics between lastT and t
    const s = samples.length ? samples[samples.length - 1]! : null;
    if (s) {
      stranded += s.qpuStranded * (t - lastT);
      qpuBusySecs += s.qpuBusy * (t - lastT);
    }
    lastT = t;
    const l = live[li]!;
    if (type === 'arrive') {
      let best = 0;
      groups.forEach((g, i) => {
        if (g.assigned < groups[best]!.assigned) best = i;
      });
      l.group = best;
      groups[best]!.assigned++;
      enqueue(li, t);
      tryStart(best, t);
    } else {
      const g = groups[l.group]!;
      const op = l.spec.ops[l.idx]!;
      if (op.kind === 'llm') {
        g.free.gpu++;
        const nxt = nextOp(l);
        // The session stays on its GPU node (and keeps its memory slot) through tool calls. Only a layout with
        // parking memory gives the slot back, and only when the next step is a QPU job.
        if (nxt && nxt.kind === 'qpu' && cfg.park) giveMem(l, t);
      } else if (op.kind === 'tool') g.free.cpu++;
      else {
        g.free.qpu++;
        if (cfg.park) l.resumed = true;
      }
      l.idx++;
      if (l.idx >= l.spec.ops.length) {
        l.end = t;
        giveMem(l, t);
      } else enqueue(li, t);
      for (let gi = 0; gi < groups.length; gi++) tryStart(gi, t);
    }
    snapshot(t);
  }

  const results: TaskResult[] = live.map((l) => {
    const wait: Record<ResKind, number> = { llm: 0, tool: 0, qpu: 0 };
    let waitMemory = 0;
    let heldIdle = 0;
    for (const sg of l.segs) {
      const d = sg.t1 - sg.t0;
      if (sg.state === 'wait-llm-compute') wait.llm += d;
      else if (sg.state === 'wait-llm-memory') {
        wait.llm += d;
        waitMemory += d;
      } else if (sg.state === 'wait-tool') wait.tool += d;
      else if (sg.state === 'wait-qpu' || sg.state === 'held-wait-qpu') {
        wait.qpu += d;
        if (sg.state === 'held-wait-qpu') heldIdle += d;
      }
    }
    const entries: Array<[string, number]> = [
      ['the QPU queue', wait.qpu],
      ['GPU memory held by other sessions', waitMemory],
      ['a free GPU', wait.llm - waitMemory],
      ['the CPU sandbox', wait.tool],
    ];
    entries.sort((a, b) => b[1] - a[1]);
    const stuckAt = entries[0]![1] > 5 ? entries[0]![0] : 'nothing (ran without waiting)';
    return { spec: l.spec, group: l.group, segs: l.segs, mem: l.mem, start: l.start, end: l.end, wait, waitMemory, heldIdle, stuckAt };
  });

  const makespan = Math.max(...results.map((r) => r.end));
  const meanBy = { inference: 0, mixed: 0, sim: 0 } as Record<TaskKind, number>;
  const unloadedBy = { inference: 0, mixed: 0, sim: 0 } as Record<TaskKind, number>;
  (Object.keys(meanBy) as TaskKind[]).forEach((k) => {
    const rs = results.filter((r) => r.spec.arche === k);
    meanBy[k] = rs.reduce((a, r) => a + (r.end - r.spec.arrival), 0) / Math.max(1, rs.length);
    unloadedBy[k] = rs.reduce((a, r) => a + r.spec.ops.reduce((x, o) => x + o.dur, 0), 0) / Math.max(1, rs.length);
  });
  const waitTotals = {
    llmCompute: results.reduce((a, r) => a + r.wait.llm - r.waitMemory, 0),
    llmMemory: results.reduce((a, r) => a + r.waitMemory, 0),
    tool: results.reduce((a, r) => a + r.wait.tool, 0),
    qpu: results.reduce((a, r) => a + r.wait.qpu, 0),
  };
  const bn: Array<[string, number]> = [
    ['QPU queue', waitTotals.qpu],
    ['GPU memory held by parked-less sessions', waitTotals.llmMemory],
    ['GPU compute', waitTotals.llmCompute],
    ['CPU sandbox', waitTotals.tool],
  ];
  bn.sort((a, b) => b[1] - a[1]);
  return {
    layout,
    tasks: results,
    samples,
    makespan,
    summary: {
      meanBy,
      unloadedBy,
      peakQLlm: Math.max(0, ...samples.map((s) => s.qLlm)),
      peakQQpu: Math.max(0, ...samples.map((s) => s.qQpu)),
      peakHeld: Math.max(0, ...samples.map((s) => s.memHeldIdle)),
      qpuUtil: qpuBusySecs / (TOY_CAPACITY.qpu * Math.max(1, makespan)),
      strandedQpuSecs: stranded,
      waitTotals,
      bottleneck: bn[0]![0],
    },
  };
}

export type Cat = 'pending' | 'gpu' | 'tool' | 'qpu' | 'waitqpu' | 'held' | 'blockmem' | 'waitgpu' | 'waittool' | 'done';

const CAT_OF: Record<SegState, Cat> = {
  'run-llm': 'gpu',
  'run-tool': 'tool',
  'run-qpu': 'qpu',
  'wait-llm-compute': 'waitgpu',
  'wait-llm-memory': 'blockmem',
  'wait-tool': 'waittool',
  'wait-qpu': 'waitqpu',
  'held-wait-qpu': 'held',
};
export const CAT_TEXT: Record<Cat, string> = {
  pending: 'not yet arrived',
  gpu: 'running an LLM step on a GPU',
  tool: 'running a tool (the session stays on its GPU node)',
  qpu: 'running on a QPU',
  waitqpu: 'parked, waiting in the QPU queue',
  held: 'holding a GPU memory slot, waiting in the QPU queue',
  blockmem: 'blocked: GPU memory is held by sessions waiting for a QPU',
  waitgpu: 'waiting for a free GPU',
  waittool: 'waiting for a tool slot',
  done: 'done',
};

export function stateAt(run: LayoutRun, t: number): Array<{ id: number; arche: TaskKind; group: number; cat: Cat; state: string; kind: 'pending' | 'run' | 'wait' | 'held' | 'done' }> {
  return run.tasks.map((r) => {
    let cat: Cat;
    if (t < r.spec.arrival) cat = 'pending';
    else if (t >= r.end) cat = 'done';
    else {
      const sg = r.segs.find((s) => t >= s.t0 && t < s.t1);
      cat = sg ? CAT_OF[sg.state] : 'gpu';
    }
    const kind = cat === 'pending' ? 'pending' : cat === 'done' ? 'done' : cat === 'held' ? 'held' : cat === 'gpu' || cat === 'tool' || cat === 'qpu' ? 'run' : 'wait';
    return { id: r.spec.id, arche: r.spec.arche, group: r.group, cat, state: CAT_TEXT[cat], kind };
  });
}

export interface PanelGroup {
  tasks: Array<{ id: number; arche: TaskKind; cat: Cat }>;
  mem: { cap: number; running: number; resident: number; held: number; parked: number };
  qpu: { cap: number; busy: number; queued: number };
}

/** State of each node group at time t: the tasks pinned to it, GPU-memory use and QPU use. */
export function panelAt(run: LayoutRun, t: number, memorySlots: number): PanelGroup[] {
  const n = LAYOUTS[run.layout].groups;
  const st = stateAt(run, t);
  const groups: PanelGroup[] = Array.from({ length: n }, () => ({
    tasks: [],
    mem: { cap: memorySlots / n, running: 0, resident: 0, held: 0, parked: 0 },
    qpu: { cap: TOY_CAPACITY.qpu / n, busy: 0, queued: 0 },
  }));
  const holds = !LAYOUTS[run.layout].park;
  st.forEach((s, i) => {
    const r = run.tasks[i]!;
    const g = groups[r.group]!;
    g.tasks.push({ id: s.id, arche: s.arche, cat: s.cat });
    const hasSlot = r.mem.some(([a, b]) => t >= a && t < b);
    if (s.cat === 'qpu') g.qpu.busy++;
    if (s.cat === 'waitqpu' || s.cat === 'held') g.qpu.queued++;
    if (!hasSlot) {
      if (!holds && (s.cat === 'waitqpu' || s.cat === 'qpu')) g.mem.parked++; // parked in the parking memory
      return;
    }
    if (s.cat === 'gpu') g.mem.running++;
    else if (holds && (s.cat === 'held' || s.cat === 'qpu')) g.mem.held++;
    else g.mem.resident++;
  });
  return groups;
}

export { PARK_S };
