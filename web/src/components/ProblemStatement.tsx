import { Fragment, useState, type ReactNode } from 'react';
import { CASES, COOLING, GPU_RACK, LIMITS, type CaseId } from '../model/brief.ts';
import { NO_LEVERS, computeFleet, type Scenario } from '../model/fleet.ts';
import { CAT_QPU, CHEM_TOOL, USD_PER_KWH, breakEvenGpuHours, scienceToolFleets } from '../model/quantum.ts';
import { compact, mw, usd } from '../format.ts';
import { Meter } from './Meter.tsx';
import { TaskFlow } from './TaskFlow.tsx';
import { LayoutCompare } from './LayoutCompare.tsx';

// 2035 GPU racks from the brief, direct liquid cooling at a cold site.
const SITE = { cooling: 'directLiquid', climate: 'cold' } as const;
const PUE = COOLING[SITE.cooling].pue[SITE.climate];
const BREAK_EVEN = breakEvenGpuHours(PUE);
// The brief's efficiency settings that cut decode power (Brief p.6). Routing chat to gpt-oss-120b is left
// off: it stores more cache per token, so it adds power.
const BRIEF_LEVERS = { ...NO_LEVERS, bgAtSlo: true, subAgents: true };

const fleetFor = (caseId: CaseId, levers = BRIEF_LEVERS) => computeFleet({ caseId, ...SITE, levers } satisfies Scenario);

const SHARES = [1e7, 1e6, 1e5];

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
          GPU-only data center can serve all of their tokens in {mw(tokens.facilityMw)}. But suppose just one task in a million calls a
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
              baselineLabel="tokens only"
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
              baselineLabel="tokens only"
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
              <li>
                A QPU only wins when the classical method is expensive. A call has to cost more than about{' '}
                <strong>{Math.round(BREAK_EVEN.cost)} GPU-hours</strong> for the QPU to be cheaper, and more than about{' '}
                {Math.round(BREAK_EVEN.energy)} GPU-hours for it to use less energy. We assume {CHEM_TOOL.gpuHoursPerCall}.
              </li>
            </ul>
          </div>
        </div>
        <p className="fine">
          Assumptions: {CHEM_TOOL.gpuHoursPerCall} GPU-hours per call on GPUs and {usd(CAT_QPU.usd)} per QPU are dc_sim inputs. QPU power and
          throughput come from quantum_arch’s mid-2030s base scenario. Tool calls are spread over the day, which the 4 h deadline allows. Break-even uses 5-year amortisation and ${USD_PER_KWH}/kWh (EIA 2025 US industrial average).
          Direct liquid cooling at a cold site, PUE {PUE}.
        </p>
      </div>

      <figure className="arch">
        <img
          src={`${import.meta.env.BASE_URL}images/architecture.svg`}
          alt="Architecture: coding agents and scientists send work to a scheduler node. LLM steps go to pooled GPU nodes, optional LPU racks and a context-memory pool where agents park their sessions. Tool calls go to a CPU sandbox pool, a classical GPU fallback, or a shared QPU service for chemistry, materials and biology."
          width={1200}
          height={660}
          loading="lazy"
        />
      </figure>

      <TaskFlow />
      <LayoutCompare />

      <Comparison />
    </section>
  );
}

// How many background agent tasks make one deep tool call, such as a high-accuracy chemistry simulation.
const FREQUENCIES = [
  { oneIn: 0, label: 'None' },
  { oneIn: 1e7, label: '1 in 10M' },
  { oneIn: 1e6, label: '1 in 1M' },
  { oneIn: 1e5, label: '1 in 100k' },
];

const mwFine = (n: number) => (n < 10 ? `${n.toFixed(1)} MW` : mw(n));

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Budget({ value }: { value: number }) {
  return (
    <>
      <span className={value > LIMITS.budgetUsd ? 'over' : ''}>{usd(value)}</span> <span className="muted">of {usd(LIMITS.budgetUsd)}</span>
    </>
  );
}

function hybridNote(caseId: CaseId, calls: number, qpus: number): string {
  if (CASES[caseId].perDay.background === 0) return 'Chat only: no tool calls, so there is nothing to send to a QPU. Same as GPU-only.';
  if (calls === 0) return 'No deep tool calls, so no QPUs are needed. Same as GPU-only.';
  return `Same token fleet. Deep tool calls go to ${qpus} QPU${qpus === 1 ? '' : 's'} next to the background-agent sandbox.`;
}

function Comparison() {
  const [oneIn, setOneIn] = useState(1e6);
  const ids = Object.keys(CASES) as CaseId[];
  const callsFor = (id: CaseId) => (oneIn ? backgroundTasksPerDay(id) / oneIn : 0);

  return (
    <section id="comparison" className="comparison" aria-labelledby="cmp-title">
      <div className="section-head">
        <h2 id="cmp-title">Comparison: GPU-only vs GPU + QPU</h2>
        <p>
          Both rows use the brief’s 2035 chips, which read memory about 15× faster than today’s GPUs. A GPU-only data center built from today’s
          chips would need several times this power. The switch sets how many background agent tasks make one deep tool call, such as a
          high-accuracy chemistry simulation.
        </p>
      </div>
      <div className="cmp-controls">
        <div className="seg" role="radiogroup" aria-label="Background agent tasks that make one deep tool call">
          {FREQUENCIES.map((f) => (
            <button
              key={f.label}
              role="radio"
              aria-checked={oneIn === f.oneIn}
              className={`seg-btn${oneIn === f.oneIn ? ' is-on' : ''}`}
              onClick={() => setOneIn(f.oneIn)}
            >
              <span className="seg-text">{f.label}</span>
            </button>
          ))}
        </div>
        <p className="cmp-calls">
          Deep tool calls a day:{' '}
          {ids.map((id) => `${id} ${callsFor(id) ? compact(callsFor(id), 0) : 'none'}`).join(' · ')}
        </p>
      </div>
      <div className="cmp-grid">
        {ids.map((id) => {
          const c = CASES[id];
          const tokens = fleetFor(id);
          const naive = fleetFor(id, NO_LEVERS);
          const spec = fleetFor(id, { ...BRIEF_LEVERS, specDecode: true });
          const calls = callsFor(id);
          const { gpu, qpu } = scienceToolFleets(calls, PUE);
          const gpuOnly = { mw: tokens.facilityMw + gpu.facilityMw, usd: tokens.rackCapexUsd + gpu.capexUsd };
          const hybrid = { mw: tokens.facilityMw + qpu.facilityMw, usd: tokens.rackCapexUsd + qpu.capexUsd };
          return (
            <Fragment key={id}>
              <article className={`card cmp-card${id === 'B' ? ' is-focus' : ''}`}>
                <header className="sq-head">
                  <span className="seg-letter">{id}</span>
                  <div>
                    <h3>{c.name}</h3>
                    <p>
                      {compact(c.users, 0)} users · {c.blurb}
                    </p>
                  </div>
                </header>
                <p className="cmp-row">GPU-only</p>
                <Meter
                  label="Facility power"
                  value={gpuOnly.mw}
                  cap={LIMITS.gridMw}
                  capLabel="500 MW"
                  baseline={tokens.facilityMw}
                  baselineLabel="tokens only"
                  format={mw}
                />
                <dl className="sq-stats">
                  <Stat label="Tokens, with efficiency settings">{mw(tokens.facilityMw)}</Stat>
                  <Stat label="Tokens, no efficiency settings">{mw(naive.facilityMw)}</Stat>
                  <Stat label="Tokens, + speculative decoding">{mw(spec.facilityMw)}</Stat>
                  <Stat label="Deep tool calls on GPUs">{calls ? `${compact(gpu.units, 0)} GPUs · ${mwFine(gpu.facilityMw)}` : 'none'}</Stat>
                  <Stat label="Rack cost">
                    <Budget value={gpuOnly.usd} />
                  </Stat>
                </dl>
              </article>
              <article className="card cmp-card cmp-hybrid">
                <p className="cmp-row cmp-row-q">{id} · GPU + QPU</p>
                <Meter label="Facility power" value={hybrid.mw} cap={LIMITS.gridMw} capLabel="500 MW" format={mw} />
                <dl className="sq-stats">
                  <Stat label="Deep tool calls on QPUs">{calls ? `${qpu.units} QPU${qpu.units === 1 ? '' : 's'} · ${mwFine(qpu.facilityMw)}` : 'none'}</Stat>
                  <Stat label="Rack + QPU cost">
                    <Budget value={hybrid.usd} />
                  </Stat>
                  <Stat label="Saved vs GPU-only">
                    {calls ? `${mwFine(gpuOnly.mw - hybrid.mw)} · ${usd(gpuOnly.usd - hybrid.usd)}` : '—'}
                  </Stat>
                </dl>
                <p className="sq-gap">{hybridNote(id, calls, qpu.units)}</p>
              </article>
            </Fragment>
          );
        })}
      </div>
      <div className="sq-notes">
        <h3>Key assumptions</h3>
        <ul>
          <li>
            <strong>GPU-only data center:</strong> every rack is the brief’s 2035 GPU rack ({GPU_RACK.chips} GPUs, {GPU_RACK.kw} kW,{' '}
            {usd(GPU_RACK.usd)}), with no LPUs and no quantum hardware. These GPUs read memory about 15× faster than today’s (120 vs 8 TB/s), and that
            speed sets how many users each one can serve.
          </li>
          <li>
            <strong>Efficiency settings (from the brief):</strong> background agents run at the 30 tokens/s they promise instead of 100, and half of all
            agent steps go to a smaller sub-agent model (Qwen3.5-122B on a 32k context). Sending chat to gpt-oss-120b is left off, because it stores
            more memory per token and adds power.
          </li>
          <li>
            <strong>Speculative decoding is our assumption</strong> (2 tokens accepted per memory read), so it is shown as a separate line, not in the
            meter.
          </li>
          <li>
            <strong>Deep tool call:</strong> one small-molecule chemistry simulation at high accuracy (100 logical qubits). On GPUs it takes {CHEM_TOOL.gpuHoursPerCall}{' '}
            GPU-hours (assumed). On a 2035 {CAT_QPU.label} it takes about 5 minutes: {CAT_QPU.callsPerHour} calls an hour at {CAT_QPU.systemMw} MW and{' '}
            {usd(CAT_QPU.usd)} each. Only background tasks make these calls, because interactive agents run their tools on the user’s laptop. Calls
            are spread over the day, which the 4 h deadline allows.
          </li>
          <li>
            <strong>Only writing tokens (decode) is counted.</strong> Prefill, spare racks for failures and bursts, buildings and energy bills are not,
            so real figures are higher. Cost covers racks and QPUs only.
          </li>
          <li>
            <strong>Cooling and demand:</strong> direct liquid cooling at a cold site (PUE {PUE}: {Math.round((PUE - 1) * 100)}% on top of chip power), and
            the brief’s peak tokens per second per user, served at its speed targets.
          </li>
        </ul>
      </div>
    </section>
  );
}
