import { useEffect, useState, type ReactNode } from 'react';
import {
  CASES,
  COOLING,
  EARTH_SITES,
  GPU_RACK,
  LIMITS,
  MODELS,
  WORKLOADS,
  type CaseId,
  type Climate,
  type CoolingId,
  type WorkloadId,
} from '../model/brief.ts';
import {
  AGENT_OVERHEAD_S,
  ASSUME,
  CHAT_OVERHEAD_S,
  NO_LEVERS,
  computeFleet,
  kvBytes,
  leverApplies,
  leverEffectMw,
  type LeverId,
  type Levers,
  type Scenario,
} from '../model/fleet.ts';
import { compact, gb, mw, pct, usd } from '../format.ts';
import { Meter, StatusChip } from './Meter.tsx';

type Owner = 'fleet' | 'thermal' | 'research';
const OWNERS: Record<Owner, { label: string; href: string }> = {
  fleet: { label: 'Fleet & web', href: '#ws-fleet' },
  thermal: { label: 'Thermal', href: '#ws-thermal' },
  research: { label: 'Quantum research', href: '#ws-quantum' },
};

const SERVING_LEVERS: { id: LeverId; label: string; how: string; source: string }[] = [
  {
    id: 'bgAtSlo',
    label: 'Serve background agents at their own speed',
    how: '30 tok/s instead of 100 makes each step 3.3× longer, so about 4.8× more caches get read per step.',
    source: 'Brief p.6',
  },
  {
    id: 'subAgents',
    label: 'Give half the agent steps to Qwen3.5-122B sub-agents',
    how: `On a 32k context a sub-agent cache is ${gb(kvBytes('qwen122', ASSUME.subAgentContext))}, against ${gb(kvBytes('kimiK3', 256_000))} for Kimi K3.`,
    source: 'Brief p.6',
  },
  {
    id: 'routeChat',
    label: 'Route half of chat to gpt-oss-120b',
    how: 'A smaller model, but it stores 18 KB of cache per token against 15 KB, so decode reads more, not less.',
    source: 'Brief p.6',
  },
  {
    id: 'specDecode',
    label: 'Speculative decoding',
    how: `Assumes ${ASSUME.specTokensPerStep} accepted tokens per cache read and ignores the draft model's cost.`,
    source: 'Brief p.8 lists it; the acceptance rate is ours',
  },
];

const WORKLOAD_NOUN: Record<WorkloadId, string> = { chat: 'chat', interactive: 'agents', background: 'background agents' };

function OwnerTag({ owner }: { owner: Owner }) {
  return (
    <a className={`owner owner-${owner}`} href={OWNERS[owner].href}>
      {OWNERS[owner].label}
    </a>
  );
}

function Panel({ n, title, children, className = '' }: { n: number; title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className}`} aria-labelledby={`panel-${n}`}>
      <h3 id={`panel-${n}`} className="panel-title">
        <span className="panel-n">{n}</span>
        {title}
      </h3>
      {children}
    </section>
  );
}

const DEFAULT_SCENARIO: Scenario = { caseId: 'B', cooling: 'directLiquid', climate: 'cold', levers: NO_LEVERS };

// The card's state lives in the URL (?case=A&levers=bgAtSlo,specDecode&cooling=immersion&climate=desert)
// so a teammate can share a link to the exact scenario they're looking at.
function readScenario(): Scenario {
  const q = new URLSearchParams(window.location.search);
  const pick = <T extends string>(value: string | null, allowed: readonly T[], fallback: T): T =>
    allowed.includes(value as T) ? (value as T) : fallback;
  const on = new Set((q.get('levers') ?? '').split(','));
  return {
    caseId: pick(q.get('case'), Object.keys(CASES) as CaseId[], DEFAULT_SCENARIO.caseId),
    cooling: pick(q.get('cooling'), Object.keys(COOLING) as CoolingId[], DEFAULT_SCENARIO.cooling),
    climate: pick(q.get('climate'), ['cold', 'desert'] as const, DEFAULT_SCENARIO.climate),
    levers: Object.fromEntries((Object.keys(NO_LEVERS) as LeverId[]).map((id) => [id, on.has(id)])) as Levers,
  };
}

function writeScenario(sc: Scenario) {
  const q = new URLSearchParams(window.location.search);
  q.set('case', sc.caseId);
  q.set('cooling', sc.cooling);
  q.set('climate', sc.climate);
  const on = (Object.keys(sc.levers) as LeverId[]).filter((id) => sc.levers[id]);
  if (on.length) q.set('levers', on.join(','));
  else q.delete('levers');
  window.history.replaceState(null, '', `${window.location.pathname}?${q}${window.location.hash}`);
}

export function FleetCard() {
  const [sc, setSc] = useState<Scenario>(readScenario);
  useEffect(() => writeScenario(sc), [sc]);
  const { caseId, cooling, climate, levers } = sc;
  const setCaseId = (id: CaseId) => setSc((s) => ({ ...s, caseId: id }));
  const setCooling = (id: CoolingId) => setSc((s) => ({ ...s, cooling: id }));
  const setClimate = (id: Climate) => setSc((s) => ({ ...s, climate: id }));

  const fleet = computeFleet(sc);
  const baseline = computeFleet({ ...sc, levers: NO_LEVERS });
  const c = CASES[caseId];
  const workloads = fleet.rows.map((r) => r.workload);
  const tightestTtft = Math.min(...workloads.map((w) => WORKLOADS[w].ttftS));
  const farthest = EARTH_SITES.reduce((a, b) => (b.rttMs > a.rttMs ? b : a));
  const hasAgents = workloads.some((w) => w !== 'chat');
  const fits = fleet.usersServed >= 1;
  const headroomMw = LIMITS.gridMw - fleet.facilityMw;
  const headroomUsd = LIMITS.budgetUsd - fleet.rackCapexUsd;

  const toggle = (id: LeverId) => setSc((s) => ({ ...s, levers: { ...s.levers, [id]: !s.levers[id] } }));

  return (
    <section id="fleet" className="card fleet" aria-labelledby="fleet-title">
      <header className="card-head">
        <div>
          <p className="eyebrow">Fleet card · napkin model until we have score.py</p>
          <h2 id="fleet-title">
            Can we serve all {compact(c.users, 0)} {c.name.toLowerCase()} on Earth?
          </h2>
        </div>
        <div className="seg" role="radiogroup" aria-label="User case">
          {(Object.keys(CASES) as CaseId[]).map((id) => (
            <button
              key={id}
              role="radio"
              aria-checked={caseId === id}
              className={`seg-btn${caseId === id ? ' is-on' : ''}`}
              onClick={() => setCaseId(id)}
            >
              <span className="seg-letter">{id}</span>
              <span className="seg-text">
                {CASES[id].name}
                <small>{compact(CASES[id].users, 0)} users</small>
              </span>
            </button>
          ))}
        </div>
      </header>

      <div className="fleet-top">
        <Panel n={1} title="Requirements" className="req">
          <p className="panel-sub">Fixed by the brief. Same for every team.</p>
          <dl className="req-list">
            <div>
              <dt>Users</dt>
              <dd>
                {compact(c.users, 0)} {c.name.toLowerCase()}: {c.blurb} <cite>Brief p.7</cite>
              </dd>
            </div>
            <div>
              <dt>Peak demand</dt>
              <dd>
                {c.peakOutPerUser} output + {c.peakInPerUser} new input tokens/s per user = <strong>{compact(fleet.peakOutTokPerS)} output tok/s</strong>{' '}
                <cite>Brief p.7</cite>
              </dd>
            </div>
            <div>
              <dt>Speed</dt>
              <dd>
                <ul className="slo">
                  {workloads.map((w) => (
                    <li key={w}>
                      <span>{WORKLOADS[w].label}</span>
                      <span>
                        first token ≤ {WORKLOADS[w].ttftS} s · {WORKLOADS[w].tokPerUserS} tok/s
                      </span>
                    </li>
                  ))}
                </ul>
                <cite>Brief p.6</cite>
              </dd>
            </div>
            <div>
              <dt>Power</dt>
              <dd>
                ≤ {mw(LIMITS.gridMw)} of grid across all Earth sites <cite>Brief p.5</cite>
              </dd>
            </div>
            <div>
              <dt>Money</dt>
              <dd>
                ≤ {usd(LIMITS.budgetUsd)} over 5 years for chips, buildings and energy <cite>Brief p.5</cite>
              </dd>
            </div>
          </dl>
          <p className="callout">
            <strong>Latency doesn’t limit us on Earth.</strong> The farthest site ({farthest.name}) is {farthest.rttMs} ms round trip, against a
            tightest deadline of {tightestTtft} s. <cite>Brief p.9</cite>
          </p>
        </Panel>

        <Panel n={2} title="What we know" className="known">
          <p className="panel-sub">Decode only, all-GPU racks, the brief’s per-GPU method (p.10). Toggle bridges below to see it move.</p>
          <ol className="chain">
            <li>
              <span className="tile-label">Peak output</span>
              <span className="tile-value">{compact(fleet.peakOutTokPerS)}</span>
              <span className="tile-sub">tok/s</span>
            </li>
            <li>
              <span className="tile-label">Per GPU</span>
              <span className="tile-value">{compact(fleet.tokPerGpu)}</span>
              <span className="tile-sub">tok/s, blended</span>
            </li>
            <li>
              <span className="tile-label">GPUs</span>
              <span className="tile-value">{compact(fleet.gpus)}</span>
              <span className="tile-sub">2035 GPUs</span>
            </li>
            <li>
              <span className="tile-label">Racks</span>
              <span className="tile-value">{Math.ceil(fleet.racks).toLocaleString('en-US')}</span>
              <span className="tile-sub">
                {GPU_RACK.chips} GPUs, {GPU_RACK.kw} kW each
              </span>
            </li>
            <li>
              <span className="tile-label">IT power</span>
              <span className="tile-value">{mw(fleet.itMw)}</span>
              <span className="tile-sub">racks only</span>
            </li>
            <li>
              <span className="tile-label">Facility power</span>
              <span className="tile-value">{mw(fleet.facilityMw)}</span>
              <span className="tile-sub">PUE {fleet.pue.toFixed(2)}</span>
            </li>
            <li>
              <span className="tile-label">Rack capex</span>
              <span className="tile-value">{usd(fleet.rackCapexUsd)}</span>
              <span className="tile-sub">{usd(GPU_RACK.usd)} per rack</span>
            </li>
          </ol>

          <div className="table-wrap">
            <table className="data">
              <caption>How the GPUs split by workload</caption>
              <thead>
                <tr>
                  <th scope="col">Workload</th>
                  <th scope="col" className="num">
                    Output share
                  </th>
                  <th scope="col">Served by</th>
                  <th scope="col" className="num">
                    Cache / user
                  </th>
                  <th scope="col" className="num">
                    Users / GPU
                  </th>
                  <th scope="col">Limited by</th>
                  <th scope="col" className="num">
                    GPUs
                  </th>
                </tr>
              </thead>
              <tbody>
                {fleet.rows.flatMap((r) =>
                  r.parts.map((p, i) => (
                    <tr key={`${r.workload}-${i}`} className={i > 0 ? 'sub-row' : ''}>
                      <td>{i === 0 ? WORKLOADS[r.workload].label : ''}</td>
                      <td className="num">{i === 0 ? pct(r.share) : ''}</td>
                      <td>
                        {p.frac < 1 && <span className="frac">{pct(p.frac)} · </span>}
                        {MODELS[p.serving.model].name} @ {p.serving.tokPerUserS} tok/s
                        {p.serving.tokensPerStep > 1 && <span className="frac"> · spec ×{p.serving.tokensPerStep}</span>}
                      </td>
                      <td className="num">{gb(p.perGpu.kvBytes)}</td>
                      <td className="num">{Math.round(p.perGpu.users).toLocaleString('en-US')}</td>
                      <td>{p.perGpu.bound === 'bandwidth' ? 'bandwidth' : 'memory size'}</td>
                      <td className="num">{compact(p.gpus)}</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <Panel n={3} title="The gap" className="gap">
        <div className="gap-grid">
          <div className="hero">
            <span className="hero-value">{pct(fleet.usersServed)}</span>
            <span className="hero-label">
              of {compact(c.users, 0)} {c.name.toLowerCase()} served inside both caps
            </span>
            <StatusChip status={fits ? 'good' : 'critical'}>
              {fits ? 'The whole case fits' : `${compact(c.users * (1 - fleet.usersServed))} users left unserved`}
            </StatusChip>
            {!fleet.coolingFitsRack && (
              <StatusChip status="warning">
                {COOLING[cooling].label} can’t cool {GPU_RACK.kw} kW racks
              </StatusChip>
            )}
          </div>
          <div className="meters">
            <Meter
              label="Facility power"
              value={fleet.facilityMw}
              cap={LIMITS.gridMw}
              capLabel="500 MW grid cap"
              baseline={baseline.facilityMw}
              format={mw}
            />
            <Meter
              label="Rack capex"
              value={fleet.rackCapexUsd}
              cap={LIMITS.budgetUsd}
              capLabel="$30B budget"
              baseline={baseline.rackCapexUsd}
              format={usd}
              note="Racks only. Buildings, energy and carbon need the catalog’s site prices."
            />
          </div>
        </div>
      </Panel>

      <Panel n={4} title="Bridges: what could close the gap, and who owns it" className="bridges">
        <div className="table-wrap">
          <table className="data bridge-table">
            <thead>
              <tr>
                <th scope="col">Bridge</th>
                <th scope="col">How it works</th>
                <th scope="col" className="num">
                  Effect on case {caseId}
                </th>
                <th scope="col">Owner</th>
              </tr>
            </thead>
            <tbody>
              {SERVING_LEVERS.map((lv) => {
                const applies = leverApplies(lv.id, caseId);
                const saved = applies ? leverEffectMw(sc, lv.id) : 0;
                return (
                  <tr key={lv.id} className={applies ? '' : 'is-na'}>
                    <th scope="row">
                      <label className="toggle">
                        <input type="checkbox" checked={applies && levers[lv.id]} disabled={!applies} onChange={() => toggle(lv.id)} />
                        <span>{lv.label}</span>
                      </label>
                      <cite>{lv.source}</cite>
                    </th>
                    <td>{lv.how}</td>
                    <td className="num effect">
                      {!applies ? (
                        <span className="muted">n/a: no {lv.id === 'routeChat' ? 'chat' : WORKLOAD_NOUN[lv.id === 'bgAtSlo' ? 'background' : 'interactive']} in case {caseId}</span>
                      ) : Math.abs(saved) < 0.5 ? (
                        <span className="muted">≈ 0 MW</span>
                      ) : (
                        <span className={saved > 0 ? 'delta-good' : 'delta-bad'}>
                          <span aria-hidden="true">{saved > 0 ? '▼' : '▲'}</span> {mw(Math.abs(saved))}
                          <span className="sr-only">{saved > 0 ? ' saved' : ' added'}</span>
                        </span>
                      )}
                    </td>
                    <td>
                      <OwnerTag owner="fleet" />
                    </td>
                  </tr>
                );
              })}
              <tr>
                <th scope="row">
                  <span className="row-label">Cooling and site climate</span>
                  <div className="inline-controls">
                    <select aria-label="Cooling" value={cooling} onChange={(e) => setCooling(e.target.value as CoolingId)}>
                      {(Object.keys(COOLING) as CoolingId[]).map((id) => (
                        <option key={id} value={id}>
                          {COOLING[id].label}
                        </option>
                      ))}
                    </select>
                    <select aria-label="Climate" value={climate} onChange={(e) => setClimate(e.target.value as Climate)}>
                      <option value="cold">Cold site</option>
                      <option value="desert">Desert site</option>
                    </select>
                  </div>
                  <cite>Deck s.15</cite>
                </th>
                <td>
                  PUE sets how much grid goes to cooling. The thermal sim should tell us how warm the coolant can run with ~5.5 kW chips, and so
                  which of these rows are real.
                </td>
                <td className="num effect">
                  {fleet.coolingFitsRack ? (
                    <span>
                      PUE {fleet.pue.toFixed(2)}: {mw(fleet.itMw * (fleet.pue - 1))} to cooling
                    </span>
                  ) : (
                    <StatusChip status="critical">Air tops out at 50 kW a rack; GPU racks draw {GPU_RACK.kw} kW</StatusChip>
                  )}
                </td>
                <td>
                  <OwnerTag owner="thermal" />
                </td>
              </tr>
              <tr>
                <th scope="row">
                  <span className="row-label">Quantum co-processor next to the agent sandbox</span>
                  <cite>Placeholder</cite>
                </th>
                <td>
                  {hasAgents
                    ? 'Background agents run their tools in our building, with a 10 s first-token deadline and 4 h per task. A QPU can sit there as a tool the agent calls. It does not speed up decode.'
                    : 'No slot: chat makes no tool calls and has a 0.6 s deadline. A QPU here would add power and cost and serve no one.'}
                </td>
                <td className="num effect">
                  {!hasAgents ? (
                    <span className="muted">n/a in case {caseId}</span>
                  ) : headroomMw > 0 && headroomUsd > 0 ? (
                    <span>
                      Could use the {mw(headroomMw)} and {usd(headroomUsd)} of headroom
                    </span>
                  ) : (
                    <span className="muted">Close the gap first: no headroom yet</span>
                  )}
                </td>
                <td>
                  <OwnerTag owner="research" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="fleet-bottom">
        <section className="panel unknowns" aria-labelledby="unknowns-title">
          <h3 id="unknowns-title" className="panel-title">
            Known unknowns
          </h3>
          <ul>
            <li>
              <strong>Prefill.</strong> Not modelled; it needs the catalog’s chip FLOP/s. The brief says it takes milliseconds in 2035, so it costs
              power and money, not latency. <OwnerTag owner="fleet" />
            </li>
            <li>
              <strong>LPU decode racks.</strong> 200 TB/s but only 160 GB, about {Math.floor(160e9 / kvBytes('kimiK3', 256_000))} Kimi K3 caches.
              More bandwidth per watt, too little room for long contexts. <OwnerTag owner="fleet" />
            </li>
            <li>
              <strong>Context-memory tier.</strong> Interactive agents park their caches during 8 s tool calls. With speculative decoding on, case B
              becomes limited by memory size, so this starts to matter. <OwnerTag owner="fleet" />
            </li>
            <li>
              <strong>Site prices, carbon, buildings.</strong> In the catalog behind score.py; they decide which of the six Earth sites we use.{' '}
              <OwnerTag owner="fleet" />
            </li>
            <li>
              <strong>Quantum tool workloads.</strong> Which 2035 agent tools have a real quantum advantage, and how many tasks a day one QPU can
              serve. <OwnerTag owner="research" />
            </li>
            <li>
              <strong>Chip thermals at 2035 power.</strong> The Track 2 tool models a ~400 W package; a 2035 GPU draws {(GPU_RACK.kw / GPU_RACK.chips).toFixed(1)} kW.{' '}
              <OwnerTag owner="thermal" />
            </li>
          </ul>
        </section>
        <details className="panel assumptions">
          <summary>Assumptions in this model</summary>
          <ul>
            <li>
              Decode follows the brief: each step reads every user’s cache once at 72 TB/s (Brief p.10). Overhead per step is backed out of the
              brief’s two published points: {(CHAT_OVERHEAD_S * 1e3).toFixed(1)} ms for chat, {(AGENT_OVERHEAD_S * 1e3).toFixed(1)} ms for Kimi K3.
              The smaller models reuse the chat figure.
            </li>
            <li>{ASSUME.reservedBytes / 1e9} GB of each GPU’s 3 TB holds weights and activations; the rest holds caches.</li>
            <li>
              Interactive agents keep caches in GPU memory during 8 s tool calls. Background agents’ sandbox is next door, so they don’t wait.
            </li>
            <li>The baseline runs background steps on the interactive pool at 100 tok/s, which is how the brief’s per-GPU figure is quoted.</li>
            <li>The brief gives one peak rate per user; we split it across workloads by their share of daily output tokens.</li>
            <li>No prefill, spare capacity or failures. All racks are 2035 GPU racks.</li>
          </ul>
        </details>
      </div>
    </section>
  );
}
