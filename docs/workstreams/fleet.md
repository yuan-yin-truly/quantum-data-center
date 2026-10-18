## Fleet model & website

**Owner:** Yuan · **Status:** napkin model live on the fleet card

**Question:** How many racks, MW and dollars does it take to serve 100% of case B on Earth, and which levers get us under 500 MW and $30B?

**Gap it bridges:** the whole fleet card. Every other workstream lands as a row in its bridges table.

**Done**

- Napkin model in `web/src/model/` that reproduces the brief's per-GPU numbers (Brief p.10)
- Fleet card: requirements, the chain from users to dollars, the gap, bridges with owners
- This page, with workstream sections built from `docs/workstreams/*.md`

**Next**

- [ ] Get score.py and the 2035 catalog (tinyurl.com/chipsdata2035, needs sign-in)
- [ ] Pick sites from the catalog's power prices and carbon
- [ ] Add prefill, LPU decode racks and a context-memory tier
- [ ] Add pages for thermal heatmaps and the quantum wing
