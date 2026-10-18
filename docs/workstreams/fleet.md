## Fleet model & website

**Owner:** Yuan · **Status:** fleet model live on the problem statement page

**Question:** How many racks, MW and dollars does it take to serve 100% of case B on Earth, and which levers get us under 500 MW and $30B?

**Gap it bridges:** the status quo for cases A, B and C, and the token-serving baseline that the QPU comparison adds to.

**Done**

- Napkin model in `web/src/model/` that reproduces the brief's per-GPU numbers (Brief p.10)
- Problem statement: GPU sandbox vs QPU wing for agent chemistry tool calls
- Comparison: GPU-only vs GPU + QPU for the three cases, with a deep-tool-call frequency switch
- This page, with workstream sections built from `docs/workstreams/*.md`

**Next**

- [ ] Pick sites from the catalog's power prices and carbon
- [ ] Add prefill, LPU decode racks and a context-memory tier
- [ ] Add pages for thermal heatmaps and the quantum wing
