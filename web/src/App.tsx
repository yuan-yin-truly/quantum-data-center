import { ProblemStatement } from './components/ProblemStatement.tsx';
import { Markdown } from './components/Markdown.tsx';
import researchNotes from '../../docs/research-notes.md?raw';

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
          <a href="#comparison">Comparison</a>
          <a href="./thermal_lab/">QC Hybrid Simulator</a>
          <a href="#notes">Research notes</a>
        </nav>
      </header>

      <main id="top">
        <ProblemStatement />

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
