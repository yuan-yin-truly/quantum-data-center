# quantum-data-center

Our entry for SUNDAI @ MIT Track 1, "Build the AI data center of 2035": serve 100% of one user case on Earth, inside 500 MW and $30B, then make it cheap.

The team page lives in `web/`. It opens with the fleet card (requirements, what we know, the gap, and the bridges each of us owns), followed by a section per workstream.

## Run the page

```bash
cd web
npm install
npm run dev      # http://localhost:5173
npm run build    # typecheck + static build into web/dist
```

Pushing to `main` deploys to GitHub Pages through `.github/workflows/pages.yml`. Turn it on once under Settings → Pages → Source: GitHub Actions.

## Add your work

- **Your workstream section:** edit `docs/workstreams/<name>.md`. The page renders it as-is.
- **Research notes:** `docs/research-notes.md`.
- **Fleet model numbers:** `web/src/model/brief.ts` holds every number from the brief, each tagged with its page. `web/src/model/fleet.ts` is the napkin model. Both are plain TypeScript that Node 24 runs directly, so a quick script can import `computeFleet` to try numbers.
- **Simulation output for the web** (thermal runs, sweeps): put JSON under `web/public/data/<workstream>/`.

The brief and deck live in `data/`, which isn't committed. Ask a teammate for the files.
