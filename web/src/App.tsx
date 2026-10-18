import { ProblemStatement } from './components/ProblemStatement.tsx';
import { Markdown } from './components/Markdown.tsx';
import researchNotes from '../../docs/research-notes.md?raw';
import fleetMd from '../../docs/workstreams/fleet.md?raw';
import thermalMd from '../../docs/workstreams/thermal.md?raw';
import quantumMd from '../../docs/workstreams/quantum.md?raw';

const WORKSTREAMS = [
  { id: 'ws-fleet', file: 'fleet.md', source: fleetMd },
  { id: 'ws-thermal', file: 'thermal.md', source: thermalMd },
  { id: 'ws-quantum', file: 'quantum.md', source: quantumMd },
];

export default function App() {
  return (
    <>
      <header className="topbar">
        <a className="brand" href="#top">
          <span className="brand-mark" aria-hidden="true" />
          Quantum Data Center 2035
        </a>
        <nav aria-label="Sections">
          <a href="#problem">Problem statement</a>
          <a href="#status-quo">Status quo</a>
          <a href="#workstreams">Workstreams</a>
          <a href="./thermal_lab/">QC Hybrid Simulator</a>
          <a href="#notes">Research notes</a>
        </nav>
      </header>

      <main id="top">
        <ProblemStatement />

        <section id="workstreams" className="workstreams" aria-labelledby="ws-title">
          <div className="section-head">
            <h2 id="ws-title">Workstreams</h2>
            <p>
              To update your section, edit <code>docs/workstreams/&lt;name&gt;.md</code> and push. The page rebuilds from those files.
            </p>
          </div>
          <div className="ws-grid">
            {WORKSTREAMS.map((ws) => (
              <article key={ws.id} id={ws.id} className="card ws-card">
                <Markdown source={ws.source} />
                <p className="ws-file">
                  <code>docs/workstreams/{ws.file}</code>
                </p>
              </article>
            ))}
          </div>
        </section>

        <section id="notes" className="notes-section" aria-labelledby="notes-title">
          <div className="section-head">
            <h2 id="notes-title">Research notes</h2>
            <p>
              The plan review behind the problem statement: the brief in numbers, the gaps, quantum, 2035 projections and the thermal tool. Source:{' '}
              <code>docs/research-notes.md</code>.
            </p>
          </div>
          <details className="card notes">
            <summary>Open the research notes</summary>
            <Markdown source={researchNotes} />
          </details>
        </section>
      </main>

      <footer className="footer">
        <p>
          Numbers come from the Track 1 brief and the team’s simulators (quantum_arch, dc_sim, thermal_lab). “Brief p.N” is <code>data/data center design requirements.pdf</code>;
          “Deck s.15” is slide 15 of <code>data/145 - Chips and data center 2035.pptx</code>. The model lives in <code>web/src/model/</code>.
        </p>
      </footer>
    </>
  );
}
