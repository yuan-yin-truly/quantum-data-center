// QPU sizing from the team's quantum_arch simulator (see README_QUANTUM.md).
// Superconducting transmons, cryo-CMOS control at 4 K, `projected` hardware profile.
// Its own caveat applies: illustrative parameters, a demonstration of the method, not a forecast.

// System wall power per physical qubit at scale: 1M qubits draw 27.1 MW across 267 fridges
// (quantum_arch/example_outputs/sweep_sc_cryo_cmos/sweep.json). Excludes facility overhead.
export const QPU_WATTS_PER_PHYSICAL_QUBIT = 27_080_400 / 1_000_000;

// Physical qubits for a reference design with 10 magic-state factories
// (quantum_arch/example_outputs/compare/architectures/sc_cryo_cmos_100k/summary.md).
export const QPU_TOOLS = [
  { id: 'chemistry_small', label: 'Small chemistry (100 logical qubits)', physicalQubits: 588_350 },
  { id: 'femoco', label: 'FeMoco catalyst energy (2,196 logical qubits)', physicalQubits: 12_431_454 },
];

export function qpuSystemMw(physicalQubits: number): number {
  return (physicalQubits * QPU_WATTS_PER_PHYSICAL_QUBIT) / 1e6;
}
