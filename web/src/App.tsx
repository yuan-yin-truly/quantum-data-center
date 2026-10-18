import { FleetCard } from './components/FleetCard.tsx';
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
          <a href="#fleet">Fleet card</a>
          <a href="#workstreams">Workstreams</a>
          <a href="#notes">Research notes</a>
        </nav>
      </header>

      <main id="top">
        <section className="intro">
          <p className="eyebrow">SUNDAI @ MIT · Track 1 · Build the AI data center of 2035</p>
          <h1>Serve every user in one case, on Earth, inside 500 MW and $30B. Then make it cheap.</h1>
          <p className="lede">
            This is our team’s shared page. The fleet card sets the story: what the brief fixes, what we can already calculate, where the gap is,
            and which bridge each of us is working on. Workstream sections below come straight from markdown files anyone can edit.
          </p>
          <ul className="facts">
            <li>Earth only: no orbit, Moon or Mars</li>
            <li>Score: users served at the speed targets, then dollars saved</li>
            <li>Demo Sun Oct 18, 8 PM · no slides allowed</li>
          </ul>
        </section>

        <FleetCard />

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
              The plan review behind the fleet card: the brief in numbers, the gaps, quantum, 2035 projections and the thermal tool. Source:{' '}
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
          Numbers come from the Track 1 brief and are tagged with their page. “Brief p.N” is <code>data/data center design requirements.pdf</code>;
          “Deck s.15” is slide 15 of <code>data/145 - Chips and data center 2035.pptx</code>. The model lives in <code>web/src/model/</code>.
        </p>
      </footer>
    </>
  );
}
