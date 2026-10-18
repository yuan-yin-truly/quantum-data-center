// Illustrative timeline of ONE agent task through the data center (not a measurement).
// Durations: QPU run times come from quantum_arch (mid-2030s base, 40k cat-qubit QPU); the rest are assumptions
// of the dc_sim studies and are marked in the page footnote. Segment widths in the picture are compressed.
// Tool calls run outside the nodes drawn here: the session waits in the context-memory pool meanwhile.

export type TaskKind = 'inference' | 'mixed' | 'sim';
export type WaitMode = 'park' | 'hold';
export type QueueState = 'short' | 'long';
export type NodeId = 'sched' | 'gpu' | 'ctx' | 'qpu';
export type SegKind = 'schedule' | 'llm' | 'tool' | 'park' | 'wait' | 'qpu' | 'held' | 'resume' | 'done';

export interface Segment {
  kind: SegKind;
  /** where the agent session sits during the segment (null: it has left the data center) */
  session: NodeId | null;
  /** where the offloaded job sits (the QPU job), if any */
  job: NodeId | null;
  secs: number;
  label: string;
  detail: string;
  /** the GPU is reserved (busy or held idle) */
  gpuReserved: boolean;
  gpuBusy: boolean;
}

export const LLM_STEP_S = 6; // prefill + decode of one agent step. ASSUMPTION
export const TOOL_S = 8; // sandbox tool call (slides: 8 s).
export const SCHEDULE_S = 0.05; // decision latency of the scheduler node (dc_sim assumption)
export const PARK_S = 0.2; // session context copied to the context-memory pool. ASSUMPTION
export const RESUME_S = 1.1; // copied back (about 0.06 s) or, for a quarter of the resumes, re-prefilled (about 4 s). ASSUMPTION
export const QUEUE_WAIT_S: Record<QueueState, number> = { short: 20, long: 1500 };
export const QPU_MATERIALS_S = 44; // quantum_arch vqe_50q on the 40k cat-qubit QPU
export const QPU_CHEMISTRY_S = 227; // quantum_arch chemistry_small

export const TASKS: Record<TaskKind, { label: string; blurb: string; calls: number }> = {
  inference: { label: 'Pure inference', blurb: 'Coding agent: LLM steps and sandbox tool calls, no quantum-eligible call.', calls: 0 },
  mixed: { label: 'Mixed inference + simulation', blurb: 'Materials agent: LLM steps, then one quantum-eligible electronic-structure call.', calls: 1 },
  sim: { label: 'Simulation-heavy', blurb: 'Chemistry agent: LLM planning around three active-space chemistry calls.', calls: 3 },
};

export const QUEUES: Record<QueueState, { label: string; blurb: string }> = {
  short: { label: 'QPU queue short', blurb: 'about 20 s wait' },
  long: { label: 'QPU queue long', blurb: 'about 25 min' },
};

const seg = (s: Partial<Segment> & Pick<Segment, 'kind' | 'secs' | 'label' | 'detail'>): Segment => ({
  session: null,
  job: null,
  gpuReserved: false,
  gpuBusy: false,
  ...s,
});

function secsLabel(s: number): string {
  if (s < 1) return `${s.toFixed(2)} s`;
  if (s < 120) return `${Math.round(s)} s`;
  if (s < 7200) return `${(s / 60).toFixed(s < 600 ? 1 : 0)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

export function buildFlow(task: TaskKind, mode: WaitMode, queue: QueueState): Segment[] {
  const out: Segment[] = [];
  const llm = (label: string) =>
    out.push(seg({ kind: 'llm', session: 'gpu', secs: LLM_STEP_S, label, detail: 'prefill and decode on any free GPU node', gpuReserved: true, gpuBusy: true }));
  const tool = (label: string) =>
    out.push(seg({ kind: 'tool', session: 'ctx', secs: TOOL_S, label, detail: 'tool call runs; the session waits in the context-memory pool and the GPU serves other users' }));

  out.push(seg({ kind: 'schedule', session: 'sched', secs: SCHEDULE_S, label: 'Schedule', detail: 'scheduler node checks the task and picks a free GPU node' }));

  if (task === 'inference') {
    for (let i = 1; i <= 4; i++) {
      llm(`LLM step ${i}`);
      tool(`Tool call ${i}`);
    }
    llm('LLM step 5');
    out.push(seg({ kind: 'done', session: null, secs: 0.4, label: 'Done', detail: 'answer returned; 5 of the task’s 80 steps are shown' }));
    return out;
  }

  const isChem = task === 'sim';
  const calls = TASKS[task].calls;
  const qpuS = isChem ? QPU_CHEMISTRY_S : QPU_MATERIALS_S;
  const wait = QUEUE_WAIT_S[queue];

  llm('LLM plans');
  tool('Prepare inputs');
  for (let c = 1; c <= calls; c++) {
    llm(calls > 1 ? `LLM asks for call ${c}` : 'LLM asks for the call');
    if (mode === 'park') {
      out.push(seg({ kind: 'park', session: 'ctx', job: null, secs: PARK_S, label: 'Park session', detail: 'context copied to the context-memory pool; the GPU is released', gpuReserved: false }));
      out.push(seg({ kind: 'wait', session: 'ctx', job: 'qpu', secs: wait, label: 'QPU queue', detail: 'job waits for a free QPU; no GPU is held' }));
      out.push(seg({ kind: 'qpu', session: 'ctx', job: 'qpu', secs: qpuS, label: 'QPU runs', detail: `${isChem ? 'chemistry_small' : 'vqe_50q'} on a 40k cat-qubit QPU (quantum_arch)` }));
      out.push(seg({ kind: 'resume', session: 'gpu', job: null, secs: RESUME_S, label: 'Resume', detail: 'context restored on any free GPU node', gpuReserved: true, gpuBusy: true }));
    } else {
      out.push(seg({ kind: 'held', session: 'gpu', job: 'qpu', secs: wait, label: 'GPU held, QPU queue', detail: 'session keeps its KV cache in GPU memory while the job waits', gpuReserved: true }));
      out.push(seg({ kind: 'qpu', session: 'gpu', job: 'qpu', secs: qpuS, label: 'QPU runs (GPU held)', detail: `${isChem ? 'chemistry_small' : 'vqe_50q'} on a 40k cat-qubit QPU`, gpuReserved: true }));
    }
    llm(calls > 1 ? `LLM reads result ${c}` : 'LLM reads the result');
  }
  tool('Write the report');
  llm('LLM final answer');
  out.push(seg({ kind: 'done', session: null, secs: 0.4, label: 'Done', detail: 'answer returned' }));
  return out;
}

/** Display width of a segment: compressed so a 227 s QPU run and a 0.2 s park both stay readable. */
export function weight(secs: number): number {
  return 1.2 + 1.6 * Math.log10(1 + secs);
}

export interface Totals {
  elapsed: number;
  gpuBusy: number;
  gpuHeldIdle: number;
  qpuBusy: number;
  parked: number;
}

export function totals(segs: Segment[]): Totals {
  const t: Totals = { elapsed: 0, gpuBusy: 0, gpuHeldIdle: 0, qpuBusy: 0, parked: 0 };
  for (const s of segs) {
    t.elapsed += s.secs;
    if (s.gpuBusy) t.gpuBusy += s.secs;
    else if (s.gpuReserved) t.gpuHeldIdle += s.secs;
    if (s.kind === 'qpu') t.qpuBusy += s.secs;
    if (s.session === 'ctx') t.parked += s.secs;
  }
  return t;
}

export { secsLabel };
