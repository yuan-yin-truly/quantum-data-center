// Napkin fleet model: users -> peak tokens/s -> GPUs -> racks -> MW -> $.
// It follows the brief's own decode math (Brief p.10) so its numbers can be checked
// by hand.

import {
  CASES,
  COOLING,
  GPU,
  GPU_RACK,
  GPU_READ_BYTES_PER_S,
  LIMITS,
  MODELS,
  PER_GPU_POINTS,
  WORKLOADS,
  type CaseId,
  type Climate,
  type CoolingId,
  type ModelId,
  type WorkloadId,
} from './brief.ts';

export type LeverId = 'bgAtSlo' | 'subAgents' | 'routeChat' | 'specDecode';
export type Levers = Record<LeverId, boolean>;

export interface Scenario {
  caseId: CaseId;
  cooling: CoolingId;
  climate: Climate;
  levers: Levers;
}

export const NO_LEVERS: Levers = { bgAtSlo: false, subAgents: false, routeChat: false, specDecode: false };

// Assumptions the brief leaves open. Each one is listed on the card.
export const ASSUME = {
  // Speculative decoding: accepted tokens per cache read. Draft-model cost ignored.
  specTokensPerStep: 2,
  // Weights and activations take this much of each GPU's 3 TB; the rest holds KV caches.
  reservedBytes: 200e9,
  // Sub-agents (Qwen3.5-122B) take this share of agent steps, at this context (Brief p.6: up to half, 32k).
  subAgentShare: 0.5,
  subAgentContext: 32_000,
  // Routed chat share to gpt-oss-120b (Brief p.6: up to 50%).
  routedChatShare: 0.5,
};

export const WORKLOAD_IDS: WorkloadId[] = ['chat', 'interactive', 'background'];

export function kvBytes(model: ModelId, contextTokens: number): number {
  const m = MODELS[model];
  return m.kvBytesPerToken * contextTokens + m.stateBytes;
}

// Brief p.10: each decode step gives every user in the batch one token and reads
// each user's whole KV cache once, so  step = overhead + users x KV / read bandwidth.
// The overhead (sync + weights + math) is backed out of the brief's two published points.
function overheadS(p: typeof PER_GPU_POINTS.chat): number {
  return 1 / p.tokPerUserS - (p.users * kvBytes(p.model, p.contextTokens)) / GPU_READ_BYTES_PER_S;
}
export const CHAT_OVERHEAD_S = overheadS(PER_GPU_POINTS.chat); // ~2.2 ms
export const AGENT_OVERHEAD_S = overheadS(PER_GPU_POINTS.agent); // ~3.8 ms
// The smaller models get the Qwen3.5-397B overhead; their weights are lighter, so this is conservative.
const OVERHEAD_S: Record<ModelId, number> = {
  kimiK3: AGENT_OVERHEAD_S,
  qwen397: CHAT_OVERHEAD_S,
  qwen122: CHAT_OVERHEAD_S,
  gptOss: CHAT_OVERHEAD_S,
};

export interface Serving {
  model: ModelId;
  contextTokens: number;
  tokPerUserS: number;
  tokensPerStep: number;
  // Caches parked while their agent waits for a tool, per cache being decoded.
  parkedPerActive: number;
}

export interface PerGpu {
  users: number;
  tokPerS: number;
  kvBytes: number;
  bound: 'bandwidth' | 'memory';
}

export function perGpu(s: Serving): PerGpu {
  const kv = kvBytes(s.model, s.contextTokens);
  const stepS = s.tokensPerStep / s.tokPerUserS;
  const byBandwidth = Math.max(0, ((stepS - OVERHEAD_S[s.model]) * GPU_READ_BYTES_PER_S) / kv);
  const byMemory = (GPU.memBytes - ASSUME.reservedBytes) / (kv * (1 + s.parkedPerActive));
  const users = Math.min(byBandwidth, byMemory);
  return { users, tokPerS: users * s.tokPerUserS, kvBytes: kv, bound: byBandwidth <= byMemory ? 'bandwidth' : 'memory' };
}

function servings(w: WorkloadId, levers: Levers): { frac: number; serving: Serving }[] {
  const wl = WORKLOADS[w];
  const tokensPerStep = levers.specDecode ? ASSUME.specTokensPerStep : 1;
  if (w === 'chat') {
    const main: Serving = { model: wl.model, contextTokens: wl.contextTokens, tokPerUserS: wl.tokPerUserS, tokensPerStep, parkedPerActive: 0 };
    if (!levers.routeChat) return [{ frac: 1, serving: main }];
    return [
      { frac: 1 - ASSUME.routedChatShare, serving: main },
      { frac: ASSUME.routedChatShare, serving: { ...main, model: 'gptOss' } },
    ];
  }
  // Without the lever, background steps share the interactive pool and its 100 tok/s.
  const speed = w === 'background' && !levers.bgAtSlo ? WORKLOADS.interactive.tokPerUserS : wl.tokPerUserS;
  const parkedPerActive = wl.toolWaitS / (wl.outTokens / speed);
  const main: Serving = { model: wl.model, contextTokens: wl.contextTokens, tokPerUserS: speed, tokensPerStep, parkedPerActive };
  if (!levers.subAgents) return [{ frac: 1, serving: main }];
  return [
    { frac: 1 - ASSUME.subAgentShare, serving: main },
    { frac: ASSUME.subAgentShare, serving: { ...main, model: 'qwen122', contextTokens: ASSUME.subAgentContext } },
  ];
}

// Output tokens a user generates per day, by workload.
export function outTokensPerDay(caseId: CaseId): Record<WorkloadId, number> {
  const c = CASES[caseId];
  return {
    chat: c.perDay.chat * WORKLOADS.chat.outTokens,
    interactive: c.perDay.interactive * WORKLOADS.interactive.stepsPerTask * WORKLOADS.interactive.outTokens,
    background: c.perDay.background * WORKLOADS.background.stepsPerTask * WORKLOADS.background.outTokens,
  };
}

export interface WorkloadRow {
  workload: WorkloadId;
  share: number;
  tokPerS: number;
  gpus: number;
  parts: { frac: number; serving: Serving; perGpu: PerGpu; gpus: number }[];
}

export interface Fleet {
  peakOutTokPerS: number;
  rows: WorkloadRow[];
  gpus: number;
  tokPerGpu: number;
  racks: number;
  itMw: number;
  pue: number;
  coolingFitsRack: boolean;
  facilityMw: number;
  rackCapexUsd: number;
  powerRatio: number;
  budgetRatio: number;
  // Share of the case's users the fleet could serve inside both caps (racks-only capex).
  usersServed: number;
}

export function computeFleet(sc: Scenario): Fleet {
  const c = CASES[sc.caseId];
  const peakOutTokPerS = c.users * c.peakOutPerUser;
  const day = outTokensPerDay(sc.caseId);
  const dayTotal = WORKLOAD_IDS.reduce((sum, w) => sum + day[w], 0);
  // The brief gives one peak rate per user; we split it by each workload's share of daily output.
  const rows: WorkloadRow[] = WORKLOAD_IDS.filter((w) => day[w] > 0).map((w) => {
    const share = day[w] / dayTotal;
    const tokPerS = peakOutTokPerS * share;
    const parts = servings(w, sc.levers).map((p) => {
      const g = perGpu(p.serving);
      return { ...p, perGpu: g, gpus: (tokPerS * p.frac) / g.tokPerS };
    });
    return { workload: w, share, tokPerS, gpus: parts.reduce((s, p) => s + p.gpus, 0), parts };
  });
  const gpus = rows.reduce((s, r) => s + r.gpus, 0);
  const racks = gpus / GPU_RACK.chips;
  const itMw = (racks * GPU_RACK.kw) / 1000;
  const cooling = COOLING[sc.cooling];
  const pue = cooling.pue[sc.climate];
  const facilityMw = itMw * pue;
  const rackCapexUsd = racks * GPU_RACK.usd;
  return {
    peakOutTokPerS,
    rows,
    gpus,
    tokPerGpu: peakOutTokPerS / gpus,
    racks,
    itMw,
    pue,
    coolingFitsRack: GPU_RACK.kw <= cooling.maxRackKw,
    facilityMw,
    rackCapexUsd,
    powerRatio: facilityMw / LIMITS.gridMw,
    budgetRatio: rackCapexUsd / LIMITS.budgetUsd,
    usersServed: Math.min(1, LIMITS.gridMw / facilityMw, LIMITS.budgetUsd / rackCapexUsd),
  };
}

export function leverApplies(lever: LeverId, caseId: CaseId): boolean {
  const day = outTokensPerDay(caseId);
  if (lever === 'routeChat') return day.chat > 0;
  if (lever === 'bgAtSlo') return day.background > 0;
  if (lever === 'subAgents') return day.interactive + day.background > 0;
  return true;
}

// Facility MW saved by switching one lever on, given the others as they are.
export function leverEffectMw(sc: Scenario, lever: LeverId): number {
  const off = computeFleet({ ...sc, levers: { ...sc.levers, [lever]: false } });
  const on = computeFleet({ ...sc, levers: { ...sc.levers, [lever]: true } });
  return off.facilityMw - on.facilityMw;
}
