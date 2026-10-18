// TOY discrete-event simulation: the same 24 tasks (3 archetypes) on three data-center layouts.
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
export const TOY_CAPACITY = { gpuCompute: 6, gpuMemory: 12, cpu: 6, qpu: 3 };

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
  resumed: boolean;
  waitSince: number;
  blocked: 'compute' | 'memory';
  segs: Seg[];
  end: number;
  start: number;
}

export function simulate(layout: LayoutId, tasks: TaskSpec[]): LayoutRun {
  const cfg = LAYOUTS[layout];
  const n = cfg.groups;
  const groups: Group[] = Array.from({ length: n }, () => {
    const cap = {
      gpu: TOY_CAPACITY.gpuCompute / n,
      mem: TOY_CAPACITY.gpuMemory / n,
      cpu: TOY_CAPACITY.cpu / n,
      qpu: TOY_CAPACITY.qpu / n,
    };
    return { free: { ...cap }, cap, q: { llm: [], tool: [], qpu: [] }, assigned: 0 };
  });
  const live: Live[] = tasks.map((spec) => ({ spec, group: 0, idx: 0, hasMem: false, resumed: false, waitSince: 0, blocked: 'compute', segs: [], end: 0, start: spec.arrival }));
  // event list: [time, order, kind, taskIndex]
  type Ev = [number, number, 'arrive' | 'end', number];
  const events: Ev[] = tasks.map((t, i) => [t.arrival, i, 'arrive', i]);
  let seq = tasks.length;
  const samples: Sample[] = [];
  let stranded = 0;
  let qpuBusySecs = 0;
  let lastT = 0;

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
      if (l.hasMem) {
        groups[l.group]!.free.mem++;
        l.hasMem = false;
      }
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
            if (!l.hasMem) {
              g.free.mem--;
              l.hasMem = true;
            }
            if (l.resumed) {
              dur += RESUME_S;
              l.resumed = false;
            }
          } else if (kind === 'tool') g.free.cpu--;
          else {
            g.free.qpu--;
            if (cfg.park && l.hasMem) {
              g.free.mem++;
              l.hasMem = false;
            }
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
        // keep the memory slot only if the next step is a QPU job and the layout does not park
        if (!(nxt && nxt.kind === 'qpu' && !cfg.park)) {
          if (l.hasMem) {
            g.free.mem++;
            l.hasMem = false;
          }
        }
      } else if (op.kind === 'tool') g.free.cpu++;
      else {
        g.free.qpu++;
        if (cfg.park) l.resumed = true;
      }
      l.idx++;
      if (l.idx >= l.spec.ops.length) {
        l.end = t;
        if (l.hasMem) {
          g.free.mem++;
          l.hasMem = false;
        }
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
    return { spec: l.spec, group: l.group, segs: l.segs, start: l.start, end: l.end, wait, waitMemory, heldIdle, stuckAt };
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

export function stateAt(run: LayoutRun, t: number): Array<{ id: number; arche: TaskKind; state: string; kind: 'pending' | 'run' | 'wait' | 'held' | 'done' }> {
  return run.tasks.map((r) => {
    if (t < r.spec.arrival) return { id: r.spec.id, arche: r.spec.arche, state: 'not yet arrived', kind: 'pending' as const };
    if (t >= r.end) return { id: r.spec.id, arche: r.spec.arche, state: 'done', kind: 'done' as const };
    const sg = r.segs.find((s) => t >= s.t0 && t < s.t1);
    if (!sg) return { id: r.spec.id, arche: r.spec.arche, state: 'between steps', kind: 'run' as const };
    const map: Record<SegState, [string, 'run' | 'wait' | 'held']> = {
      'run-llm': ['running an LLM step on a GPU', 'run'],
      'run-tool': ['running a tool in the CPU sandbox', 'run'],
      'run-qpu': ['running on a QPU', 'run'],
      'wait-llm-compute': ['waiting for a free GPU', 'wait'],
      'wait-llm-memory': ['waiting: GPU memory is held by other sessions', 'wait'],
      'wait-tool': ['waiting for the CPU sandbox', 'wait'],
      'wait-qpu': ['parked, waiting in the QPU queue', 'wait'],
      'held-wait-qpu': ['holding a GPU memory slot, waiting in the QPU queue', 'held'],
    };
    const [state, kind] = map[sg.state];
    return { id: r.spec.id, arche: r.spec.arche, state, kind };
  });
}

export { PARK_S };
