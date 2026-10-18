# Calibration of the `today` profile against published figures

Published figures are a mix of ratings, maxima, averages and vendor claims at different boundaries; they are not matched benchmarks. `anchored` rows hold by construction (the catalog was set from that figure). The first column of each row names the measurement boundary of BOTH numbers.

| case | reference | kind / status | model (today) | model / ref. | boundary | anchored | old default / ref. |
|---|---|---|---|---|---|---|---|
| Trapped-ion system, 98 qubits (Helios class), today profile | 40 kW | confirmed | 34.1 kW | 0.85 | system (excl. facility); reference is an UPPER BOUND | no | 0.17 |
| Same system against the Oracle announcement (about 60 kW without HVAC) | 60 kW | confirmed_secondary | 34.1 kW | 0.57 | system; reference excludes HVAC | no | 0.12 |
| Annealer, Advantage2 class (QPU system only, no user host) | 12.5 kW | confirmed | 12.5 kW | 1.00 | system | yes | — |
| Photonic, 6 qubits (Ascella class), cryostat inside the rack | 3 kW | confirmed | 3 kW | 1.00 | system (excluding the user's host CPU) | yes | — |
| Neutral atoms, 256 qubits (QuEra Aquila fit) | 7 kW | confirmed_secondary | 7 kW | 1.00 | system (excluding host CPU) | yes | 0.77 |
| Neutral atoms, 10,000 qubits (QuEra Aquila fit) | 10 kW | confirmed_secondary | 10 kW | 1.00 | system (excluding host CPU) | yes | 2.00 |
| Neutral atoms, about 100 qubits against the unconfirmed 'Pasqal 2.6 kW' | 2.6 kW | unconfirmed | 6.95 kW | 2.67 | system | no | 1.98 |
| GPU server, 8 x B200-class: system boundary | 14.3 kW | confirmed | 14.3 kW | 1.00 | system (maximum) | yes | 0.56 |
| GPU server, 8 x B200-class: module boundary (8 x 1 kW) | 8 kW | confirmed | 8 kW | 1.00 | module (maximum) | yes | — |
| H200-class module | 700 W | confirmed | 700 W | 1.00 | module (maximum) | yes | — |
| MI350X-class module | 1 kW | confirmed_secondary | 1 kW | 1.00 | module (maximum) | yes | — |
| MI355X-class module | 1.4 kW | confirmed_secondary | 1.4 kW | 1.00 | module (maximum) | yes | — |
| Eight MI355X, GPUs only (11.2 kW in the overview) | 11.2 kW | confirmed_secondary | 11.2 kW | 1.00 | module (maximum) | yes | — |

## Notes

- **Trapped-ion system, 98 qubits (Helios class), today profile**: Reference is 'less than 40 kW'; the model sits below it by design. Old default (3 kW + 40 W/qubit) was 5.8x too low.
- **Same system against the Oracle announcement (about 60 kW without HVAC)**: Sources disagree (40 vs 60 kW); the model is calibrated to the vendor's own <40 kW upper bound, so it is expected to lie below 60 kW.
- **Annealer, Advantage2 class (QPU system only, no user host)**: Anchored: the catalog takes the vendor's 12.5 kW; 12.5 kW = 208 V x 60 A, so it may be a rating.
- **Photonic, 6 qubits (Ascella class), cryostat inside the rack**: Anchored by construction. Not a statement about fault-tolerant photonic machines.
- **Neutral atoms, 256 qubits (QuEra Aquila fit)**: Reference is PaQit's fitted P0 + alpha N (6.92 kW + 0.308 W/qubit), itself fitted to QuEra data.
- **Neutral atoms, 10,000 qubits (QuEra Aquila fit)**: Reference is PaQit's fitted P0 + alpha N (6.92 kW + 0.308 W/qubit), itself fitted to QuEra data.
- **Neutral atoms, about 100 qubits against the unconfirmed 'Pasqal 2.6 kW'**: Reference NOT confirmed from a primary source; Pasqal's own brochure lists 3.5 kW average laser power alone (10 kW installed) and a 380 V 32 A supply, so a 7 kW system is not in conflict with Pasqal's documents.
- **GPU server, 8 x B200-class: system boundary**: Anchored: the server overhead ratio 1.79 is derived from this very figure (max-to-max).
- **GPU server, 8 x B200-class: module boundary (8 x 1 kW)**: NVIDIA guide: 1,000 W per GPU maximum with five PSUs.
- **Eight MI355X, GPUs only (11.2 kW in the overview)**: The server around them adds power (not stated by AMD); the model's ratio for this class is an assumption.
