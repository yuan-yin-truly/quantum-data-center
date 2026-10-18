## Quantum co-processor

**Owner:** heikohoppe · **Status:** simulator built (`quantum_arch/`); sizing is on the fleet card

**Question:** Is there a 2035 agent tool workload where a QPU next to the background-agent sandbox does something a GPU or CPU sandbox can't do within the 4 h task budget? If so, what does it cost in MW and dollars, and how many tasks a day can it serve?

**Gap it bridges:** the "Quantum co-processor" row of the fleet card. A QPU doesn't speed up token generation, so its value has to come from the agents' tool calls. It spends the headroom left once the classical fleet fits (case B: ~194 MW on napkin math).

**The tool:** `quantum_arch/` evaluates a quantum processor together with its classical hardware: error correction and logical qubits, wall-plug power, and the heat budget of each dilution-fridge stage. Docs are in `README_QUANTUM.md`; examples are in `quantum_arch/example_outputs/`.

```bash
python -m quantum_arch compare sc_cryo_cmos_100k spin_cmos_10k atoms_surface_10k --out out/cmp
python -m quantum_arch sweep sc_cryo_cmos_100k --min 1e4 --max 1e7 --out out/sweep
```

**What it says so far** (illustrative parameters; the method, not a forecast)

| System | Physical qubits | Logical qubits | System power | Fridges |
| --- | --- | --- | --- | --- |
| Superconducting, cryo-CMOS, projected | 100,000 | 18 | 2.7 MW | 27 |
| Same, scaled | 1,000,000 | 182 | 27 MW | 267 |
| Superconducting, room-temperature control | 100,000 | 2 | 18 MW | 1,562 |
| Neutral atoms (no cryostat) | 10,000 | 0 | 21 kW | — |

- **Cryostats are almost all of the power.** In the 100k system they take 98.6% of it, while the thermodynamic floor for the same heat is about 1,000× lower.
- **Fault-tolerant tools need big machines.** A 100-logical-qubit chemistry run needs about 588k physical qubits (about 16 MW). FeMoco (2,196 logical qubits) needs about 12.4M (about 340 MW), more than case B's headroom.
- **Variational tools fit today's sizes but lose on energy where classical can still simulate.** The 20-qubit solver uses about 400,000× more energy than exact simulation on a GPU node. At 50 qubits, classical simulation runs out of memory.

**On the fleet card:** a QPU draws about 27 W per physical qubit (projected superconducting, at scale), times the site PUE. Case B's headroom fits about 11 small-chemistry machines, and no FeMoco-class machine.

**Next**

- [ ] Pick the one or two agent tool workloads we pitch (chemistry for catalysts or batteries?) and how many background tasks a day call them
- [ ] Jobs per hour per QPU, so we can say how many tasks one machine serves
- [ ] Capital cost per QPU (not in `quantum_arch` yet)
- [ ] Export a small JSON to `web/public/data/quantum/` for a quantum section on the page
- [ ] Verify the Shor and FeMoco resource counts marked "verify" in `quantum_arch/data/workloads.json`
