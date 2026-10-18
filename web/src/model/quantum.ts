// The science-tool comparison behind the problem statement: an agent's chemistry tool call
// served by a GPU sandbox versus a QPU wing.
// Numbers come from the team's simulators (thermal_lab/page/snapshots/meta.json, which reads
// dc_sim's assumptions and quantum_arch's mid-2030s base scenario). They are scenarios, not forecasts.

import { GPU_RACK } from './brief.ts';

// One call = quantum_arch's `chemistry_small`: 100 logical qubits, 1e8 Toffoli gates.
export const CHEM_TOOL = {
  label: 'small-molecule chemistry at high accuracy (100 logical qubits)',
  // Best classical method at the same accuracy: 64 GPUs for 12 h. ASSUMPTION (dc_sim), the
  // largest uncertainty of the whole comparison.
  gpuHoursPerCall: 768,
};

// quantum_arch `dc2035_cat_40k`: 40k cat qubits, repetition code, base 2035 scenario.
export const CAT_QPU = {
  label: '40k-cat-qubit QPU',
  systemMw: 0.27, // includes its own refrigeration; draws ~0.26 MW even when idle
  usd: 120e6, // ASSUMPTION (dc_sim)
  // Accepted chemistry_small jobs per hour, after error-budget acceptance, a 60 s host
  // allowance and calibration downtime (thermal_lab estimate, not a queue result).
  callsPerHour: 11.7,
};

export interface ToolFleet {
  units: number;
  facilityMw: number;
  capexUsd: number;
}

// Background tasks run for up to 4 h, so tool calls can be spread evenly over the day.
export function scienceToolFleets(callsPerDay: number, pue: number): { gpu: ToolFleet; qpu: ToolFleet } {
  const gpus = (callsPerDay * CHEM_TOOL.gpuHoursPerCall) / 24;
  const racks = gpus / GPU_RACK.chips;
  const qpus = Math.ceil(callsPerDay / (CAT_QPU.callsPerHour * 24));
  return {
    gpu: { units: gpus, facilityMw: (racks * GPU_RACK.kw * pue) / 1000, capexUsd: racks * GPU_RACK.usd },
    qpu: { units: qpus, facilityMw: qpus * CAT_QPU.systemMw * pue, capexUsd: qpus * CAT_QPU.usd },
  };
}
