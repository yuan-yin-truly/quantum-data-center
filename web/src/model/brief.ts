// Every number the fleet model uses, copied from the Track 1 brief.
// Source tags: "Brief p.N" = data/data center design requirements.pdf, page N.
// "Deck s.15" = slide 15 of data/145 - Chips and data center 2035.pptx
// (power & cooling; it is not in the PDF).

export type CaseId = 'A' | 'B' | 'C';
export type WorkloadId = 'chat' | 'interactive' | 'background';
export type ModelId = 'kimiK3' | 'qwen397' | 'qwen122' | 'gptOss';
export type CoolingId = 'airChillers' | 'airEvap' | 'directLiquid' | 'immersion';
export type Climate = 'cold' | 'desert';

export const LIMITS = {
  budgetUsd: 30e9, // Brief p.5: 5 years of chips, buildings, energy
  gridMw: 500, // Brief p.5: all Earth sites together
};

export const GPU_RACK = { kw: 792, usd: 23.8e6, chips: 144 }; // Brief p.8
export const LPU_RACK = { kw: 516, usd: 14.3e6, chips: 256 }; // Brief p.8
export const GPU = { memBytes: 3e12, peakBytesPerS: 120e12 }; // Brief p.10
export const LPU = { memBytes: 160e9, peakBytesPerS: 200e12 }; // Brief p.10
// The brief's per-GPU math reads KV caches at 72 TB/s, 60% of the 120 TB/s peak (Brief p.10).
export const GPU_READ_BYTES_PER_S = 72e12;

export const MODELS: Record<
  ModelId,
  { name: string; totalB: number; activeB: number; kvBytesPerToken: number; stateBytes: number; maxContext: number }
> = {
  kimiK3: { name: 'Kimi K3', totalB: 2800, activeB: 104, kvBytesPerToken: 14e3, stateBytes: 217e6, maxContext: 1e6 },
  qwen397: { name: 'Qwen3.5-397B', totalB: 397, activeB: 17, kvBytesPerToken: 15e3, stateBytes: 94e6, maxContext: 262e3 },
  qwen122: { name: 'Qwen3.5-122B', totalB: 122, activeB: 10, kvBytesPerToken: 12e3, stateBytes: 75e6, maxContext: 262e3 },
  gptOss: { name: 'gpt-oss-120b', totalB: 117, activeB: 5.1, kvBytesPerToken: 18e3, stateBytes: 2e6, maxContext: 131e3 },
}; // Brief p.6

export const WORKLOADS: Record<
  WorkloadId,
  {
    label: string;
    model: ModelId;
    contextTokens: number;
    outTokens: number;
    stepsPerTask: number;
    ttftS: number;
    tokPerUserS: number;
    toolWaitS: number;
  }
> = {
  // The brief sizes the chat cache at 66k tokens (Brief p.10): 64k read plus the reply.
  chat: { label: 'Chat prompt', model: 'qwen397', contextTokens: 66_000, outTokens: 3_500, stepsPerTask: 1, ttftS: 0.6, tokPerUserS: 60, toolWaitS: 0 },
  interactive: { label: 'Agent step, interactive', model: 'kimiK3', contextTokens: 256_000, outTokens: 500, stepsPerTask: 80, ttftS: 2, tokPerUserS: 100, toolWaitS: 8 },
  // "Sandbox next door": the brief gives no tool time, so no cache waits between steps.
  background: { label: 'Agent step, background', model: 'kimiK3', contextTokens: 256_000, outTokens: 500, stepsPerTask: 80, ttftS: 10, tokPerUserS: 30, toolWaitS: 0 },
}; // Brief p.6

export const CASES: Record<
  CaseId,
  {
    name: string;
    blurb: string;
    users: number;
    peakOutPerUser: number;
    peakInPerUser: number;
    readsPerUserDay: number;
    perDay: Record<WorkloadId, number>;
  }
> = {
  A: { name: 'Prompters', blurb: '30 chat prompts a day', users: 4e9, peakOutPerUser: 2.4, peakInPerUser: 5.6, readsPerUserDay: 1.9e6, perDay: { chat: 30, interactive: 0, background: 0 } },
  B: { name: 'Agent developers', blurb: '12 interactive + 30 background agent tasks a day', users: 50e6, peakOutPerUser: 28, peakInPerUser: 333, readsPerUserDay: 860e6, perDay: { chat: 0, interactive: 12, background: 30 } },
  C: { name: 'Knowledge workers', blurb: '20 prompts + 1 interactive + 4 background tasks a day', users: 400e6, peakOutPerUser: 4.6, peakInPerUser: 40, readsPerUserDay: 104e6, perDay: { chat: 20, interactive: 1, background: 4 } },
}; // Brief p.7

// The two per-GPU decode points the brief publishes (Brief p.10).
export const PER_GPU_POINTS = {
  chat: { model: 'qwen397' as ModelId, contextTokens: 66_000, tokPerUserS: 60, users: 960, tokPerS: 58_000 },
  agent: { model: 'kimiK3' as ModelId, contextTokens: 256_000, tokPerUserS: 100, users: 117, tokPerS: 11_700 },
};

export const COOLING: Record<CoolingId, { label: string; pue: Record<Climate, number>; maxRackKw: number }> = {
  airChillers: { label: 'Air + chillers', pue: { cold: 1.16, desert: 1.54 }, maxRackKw: 50 },
  airEvap: { label: 'Air + evaporative', pue: { cold: 1.1, desert: 1.26 }, maxRackKw: 50 },
  directLiquid: { label: 'Direct liquid', pue: { cold: 1.07, desert: 1.14 }, maxRackKw: 1500 },
  immersion: { label: 'Immersion', pue: { cold: 1.06, desert: 1.1 }, maxRackKw: 2000 },
}; // Deck s.15
export const CARBON_USD_PER_T = 100; // Deck s.15
export const EVAP_WATER_L_PER_KWH = 1.8; // Deck s.15

// Round trip to users (Brief p.9). Earth only: we are not building in orbit.
export const EARTH_SITES = [
  { name: 'N. Virginia', rttMs: 25 },
  { name: 'Midwest', rttMs: 35 },
  { name: 'West Texas', rttMs: 45 },
  { name: 'Nordics', rttMs: 70 },
  { name: 'Iceland', rttMs: 80 },
  { name: 'Gulf', rttMs: 110 },
];
