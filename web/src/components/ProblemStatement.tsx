import { useState } from 'react';
import { CASES, COOLING, LIMITS, WORKLOADS, type CaseId } from '../model/brief.ts';
import { NO_LEVERS, computeFleet, type Scenario } from '../model/fleet.ts';
import { CAT_QPU, CHEM_TOOL, scienceToolFleets } from '../model/quantum.ts';
import { compact, mw, usd } from '../format.ts';
import { Meter, StatusChip } from './Meter.tsx';

// Status quo: 2035 GPU racks, direct liquid cooling at a cold site.
const SITE = { cooling: 'directLiquid', climate: 'cold' } as const;
const PUE = COOLING[SITE.cooling].pue[SITE.climate];
// The brief's own levers that cut decode power (Brief p.6). Routing chat to gpt-oss-120b is left
// off: it stores more cache per token, so it adds power.
const BRIEF_LEVERS = { ...NO_LEVERS, bgAtSlo: true, subAgents: true };

const fleetFor = (caseId: CaseId, levers = BRIEF_LEVERS) => computeFleet({ caseId, ...SITE, levers } satisfies Scenario);

const SHARES = [1e7, 1e6, 1e5];

const CASE_GAP: Record<CaseId, { slot: boolean; text: string }> = {
  A: {
    slot: false,
    text: 'Chat only. None of the brief’s levers help, and only speculative decoding (our assumption) gets under the cap. There are no tool calls, so there is no place for a QPU.',
  },
  B: {
    slot: true,
    text: 'Fits with the brief’s levers. Background agents run their tools in a sandbox in our building, with 4 h per task. That sandbox is where science tools, and a QPU, would go.',
  },
  C: {
    slot: true,
    text: 'Fits with the brief’s levers. It has a QPU slot too: background tasks are fewer per user, but there are more users.',
  },
};

function backgroundTasksPerDay(caseId: CaseId) {
  return CASES[caseId].users * CASES[caseId].perDay.background;
}

export function ProblemStatement() {
  const [oneIn, setOneIn] = useState(1e6);

  const tokens = fleetFor('B');
  const bgTasks = backgroundTasksPerDay('B');
  const calls = bgTasks / oneIn;
  const { gpu, qpu } = scienceToolFleets(calls, PUE);
  // Statement numbers are fixed at 1 in a million, whatever the selector shows.
  const ref = scienceToolFleets(bgTasks / 1e6, PUE);

  return (
    <section id="problem" className="problem" aria-labelledby="problem-title">
      <img
        className="hero-img"
        src={`${import.meta.env.BASE_URL}images/hero.webp`}
        alt="Isometric illustration of a data center: rows of GPU racks beside a glowing quantum computer cryostat"
        width={1376}
        height={768}
      />
      <div className="intro">
        <p className="eyebrow">Problem statement · Case B, agent developers · Earth, 2035</p>
        <h1 id="problem-title">
          AI agents will need science tools that GPUs can’t afford to run. One call in a million breaks the 500 MW grid.
        </h1>
        <p className="lede">
          In 2035, {compact(CASES.B.users, 0)} agent developers launch <strong>{compact(bgTasks, 1)} background agent tasks a day</strong>. A
          classical fleet can serve all of their tokens in {mw(tokens.facilityMw)}. But suppose just one task in a million calls a
          high-accuracy chemistry tool. At {CHEM_TOOL.gpuHoursPerCall} GPU-hours per call, the GPU sandbox needs another{' '}
          <strong>
            {compact(ref.gpu.units, 0)} GPUs: {mw(ref.gpu.facilityMw)} and {usd(ref.gpu.capexUsd)}
          </strong>
          . That takes the fleet to {mw(tokens.facilityMw + ref.gpu.facilityMw)}, over the cap. Instead, {ref.qpu.units} QPUs do the same calls in{' '}
          <strong>
            {ref.qpu.facilityMw.toFixed(1)} MW and {usd(ref.qpu.capexUsd)}
          </strong>
          .
        </p>
        <p className="lede">
          <strong>Our problem:</strong> design a GPU + QPU data center and the router that sends each task to the right machine, to cut{' '}
          <strong>energy</strong> and <strong>cost</strong> per task inside {mw(LIMITS.gridMw)} and {usd(LIMITS.budgetUsd)}, and find how many
          tool calls must reach the QPU before it pays for itself.
        </p>
      </div>

      <div className="card compare">
        <div className="compare-head">
          <h2>How many tasks call a science tool?</h2>
          <div className="seg" role="radiogroup" aria-label="Share of background tasks that make one chemistry call">
            {SHARES.map((n) => (
              <button key={n} role="radio" aria-checked={oneIn === n} className={`seg-btn${oneIn === n ? ' is-on' : ''}`} onClick={() => setOneIn(n)}>
                <span className="seg-text">
                  1 in {compact(n, 0)}
                  <small>{compact(bgTasks / n, 0)} calls/day</small>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="compare-grid">
          <div className="panel">
            <h3 className="panel-title">Status quo: GPU sandbox</h3>
            <p className="panel-sub">
              {CHEM_TOOL.gpuHoursPerCall} GPU-hours per call, on the brief’s 2035 GPU racks
            </p>
            <p className="big">
              {compact(gpu.units, 0)} <span>GPUs</span>
            </p>
            <Meter
              label="Fleet power: tokens + tool calls"
              value={tokens.facilityMw + gpu.facilityMw}
              cap={LIMITS.gridMw}
              capLabel="500 MW cap"
              baseline={tokens.facilityMw}
              format={mw}
              note={`Tool calls alone: ${mw(gpu.facilityMw)} and ${usd(gpu.capexUsd)} in racks.`}
            />
          </div>
          <div className="panel panel-q">
            <h3 className="panel-title">Hybrid: QPU wing next to the sandbox</h3>
            <p className="panel-sub">
              {CAT_QPU.label}, {CAT_QPU.callsPerHour} calls/hour, {CAT_QPU.systemMw} MW each
            </p>
            <p className="big">
              {qpu.units} <span>QPUs</span>
            </p>
            <Meter
              label="Fleet power: tokens + tool calls"
              value={tokens.facilityMw + qpu.facilityMw}
              cap={LIMITS.gridMw}
              capLabel="500 MW cap"
              baseline={tokens.facilityMw}
              format={mw}
              note={`Tool calls alone: ${qpu.facilityMw.toFixed(1)} MW and ${usd(qpu.capexUsd)}, ${Math.round(gpu.facilityMw / qpu.facilityMw)}× less power than the GPU sandbox.`}
            />
          </div>
        </div>

        <div className="scope">
          <div>
            <h3>What the hybrid targets</h3>
            <ul>
              <li>
                <strong>Energy per task:</strong> a science tool call costs megawatt-hours on GPUs and kilowatt-hours on a QPU.
              </li>
              <li>
                <strong>Cost:</strong> a few QPUs in place of thousands of GPUs keep the fleet inside {usd(LIMITS.budgetUsd)}.
              </li>
              <li>
                <strong>The router:</strong> sends a call to the QPU only when it can do the job at lower energy and cost. The 4 h background budget
                absorbs QPU queues and calibration downtime.
              </li>
            </ul>
          </div>
          <div>
            <h3>What it doesn’t claim</h3>
            <ul>
              <li>
                A QPU doesn’t make tokens. Decode is limited by memory bandwidth, and loading data into qubits is the bottleneck. LPUs and a
                context-memory tier handle that.
              </li>
              <li>
                An idle cryostat draws almost full power, so a QPU only pays off with enough calls to keep it busy.
              </li>
            </ul>
          </div>
        </div>
        <p className="fine">
          Assumptions: {CHEM_TOOL.gpuHoursPerCall} GPU-hours per classical call and {usd(CAT_QPU.usd)} per QPU are dc_sim inputs. QPU power and
          throughput come from quantum_arch’s mid-2030s base scenario. Tool calls are spread over the day, which the 4 h deadline allows.
          Direct liquid cooling at a cold site, PUE {PUE}.
        </p>
      </div>

      <figure className="arch">
        <img
          src={`${import.meta.env.BASE_URL}images/architecture.svg`}
          alt="Architecture: agent developers send work to a task router. LLM steps go to GPU racks, LPU racks and a context-memory tier. Tool calls go to a CPU sandbox, a GPU sandbox for classical simulation, or a QPU wing for chemistry and materials."
          width={1200}
          height={660}
          loading="lazy"
        />
      </figure>

      <StatusQuo />
    </section>
  );
}

function StatusQuo() {
  return (
    <section id="status-quo" className="status-quo" aria-labelledby="sq-title">
      <div className="section-head">
        <h2 id="sq-title">Status quo: a classical fleet in each case</h2>
        <p>
          All-GPU 2035 racks serving decode, with the brief’s levers on: background agents at 30 tok/s, and half the agent steps on Qwen3.5-122B
          sub-agents. Direct liquid cooling at a cold site (PUE {PUE}).
        </p>
      </div>
      <div className="sq-grid">
        {(Object.keys(CASES) as CaseId[]).map((id) => {
          const c = CASES[id];
          const naive = fleetFor(id, NO_LEVERS);
          const levered = fleetFor(id);
          const spec = fleetFor(id, { ...BRIEF_LEVERS, specDecode: true });
          const gap = CASE_GAP[id];
          const bg = backgroundTasksPerDay(id);
          return (
            <article key={id} className={`card sq-card${id === 'B' ? ' is-focus' : ''}`}>
              <header className="sq-head">
                <span className="seg-letter">{id}</span>
                <div>
                  <h3>{c.name}</h3>
                  <p>
                    {compact(c.users, 0)} users · {c.blurb}
                  </p>
                </div>
              </header>
              <Meter
                label="Facility power"
                value={levered.facilityMw}
                cap={LIMITS.gridMw}
                capLabel="500 MW"
                baseline={naive.facilityMw}
                format={mw}
              />
              <dl className="sq-stats">
                <div>
                  <dt>Without levers</dt>
                  <dd>{mw(naive.facilityMw)}</dd>
                </div>
                <div>
                  <dt>+ speculative decoding</dt>
                  <dd>{mw(spec.facilityMw)}</dd>
                </div>
                <div>
                  <dt>Rack capex</dt>
                  <dd>
                    {usd(levered.rackCapexUsd)} <span className="muted">of {usd(LIMITS.budgetUsd)}</span>
                  </dd>
                </div>
                <div>
                  <dt>Background tasks</dt>
                  <dd>{bg > 0 ? `${compact(bg, 1)}/day, ${WORKLOADS.background.ttftS} s first token` : 'none'}</dd>
                </div>
              </dl>
              <p className="sq-gap">{gap.text}</p>
              <StatusChip status={gap.slot ? 'good' : 'warning'}>{gap.slot ? 'Slot for a QPU tool' : 'No slot for a QPU'}</StatusChip>
            </article>
          );
        })}
      </div>
    </section>
  );
}
