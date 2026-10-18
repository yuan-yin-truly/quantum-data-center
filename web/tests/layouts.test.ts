// Run: node --test --experimental-strip-types tests/layouts.test.ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { MEMORY_OPTIONS, TASK_MIX, makeTasks, panelAt, simulate, stateAt, type LayoutId } from '../src/model/layouts.ts';
import { buildFlow, totals } from '../src/model/taskflow.ts';

const IDS: LayoutId[] = ['current', 'noPark', 'mixed'];

test('every task finishes and the task list is deterministic', () => {
  for (const pattern of ['spread', 'burst'] as const) {
    const a = makeTasks(pattern);
    const b = makeTasks(pattern);
    assert.deepEqual(a, b);
    assert.equal(a.length, Object.values(TASK_MIX).reduce((x, y) => x + y, 0));
    for (const id of IDS) {
      const run = simulate(id, a);
      for (const r of run.tasks) {
        assert.ok(r.end > r.spec.arrival, `${id} task ${r.spec.id} did not finish`);
        const work = r.spec.ops.reduce((s, o) => s + o.dur, 0);
        assert.ok(r.end - r.spec.arrival >= work - 1e-6, 'a task cannot finish faster than its work');
      }
      assert.equal(stateAt(run, run.makespan + 1).filter((s) => s.kind === 'done').length, a.length);
    }
  }
});

test('mixed nodes strand QPU capacity; burst without parking blocks inference tasks', () => {
  const spread = makeTasks('spread');
  const cur = simulate('current', spread);
  const mixed = simulate('mixed', spread);
  assert.equal(cur.summary.strandedQpuSecs, 0);
  assert.ok(mixed.summary.strandedQpuSecs > 1000);
  assert.ok(mixed.summary.qpuUtil < cur.summary.qpuUtil);
  const burst = makeTasks('burst');
  const park = simulate('current', burst);
  const hold = simulate('noPark', burst);
  assert.ok(hold.summary.meanBy.inference > 2 * park.summary.meanBy.inference);
  assert.ok(hold.summary.waitTotals.llmMemory > 1000 && park.summary.waitTotals.llmMemory < 0.05 * hold.summary.waitTotals.llmMemory);
});

test('single-task flow: parking frees the GPU, holding does not; a long queue stretches the task', () => {
  const park = totals(buildFlow('mixed', 'park', 'short'));
  const hold = totals(buildFlow('mixed', 'hold', 'short'));
  assert.ok(park.gpuHeldIdle === 0 && hold.gpuHeldIdle > 40);
  assert.ok(park.parked > 40 && hold.parked === 0);   // parking memory is used only for the QPU wait, and only with parking
  assert.equal(totals(buildFlow('inference', 'park', 'short')).qpuBusy, 0);
  assert.ok(totals(buildFlow('mixed', 'park', 'long')).elapsed > 1500 && totals(buildFlow('mixed', 'park', 'short')).elapsed < 200);
});

test('panel view: slots never exceed capacity, parking holds none, no parking holds some, roomy memory removes blocking', () => {
  const mem = MEMORY_OPTIONS.tight;
  const burst = makeTasks('burst');
  const park = simulate('current', burst, mem);
  const hold = simulate('noPark', burst, mem);
  let maxHeld = 0;
  for (let t = 0; t < hold.makespan; t += 15) {
    for (const [run, isPark] of [[park, true], [hold, false]] as const) {
      for (const g of panelAt(run, t, mem)) {
        assert.ok(g.mem.running + g.mem.held <= g.mem.cap + 1e-9, 'memory slots over capacity');
        assert.ok(g.qpu.busy <= g.qpu.cap + 1e-9, 'QPUs over capacity');
        if (isPark) assert.equal(g.mem.held, 0);
        else maxHeld = Math.max(maxHeld, g.mem.held);
      }
    }
  }
  assert.ok(maxHeld >= mem - 1, 'without parking the held sessions should fill the GPU memory');
  const roomy = simulate('noPark', burst, MEMORY_OPTIONS.roomy);
  assert.ok(roomy.summary.waitTotals.llmMemory === 0 && roomy.summary.meanBy.inference < 1.2 * roomy.summary.unloadedBy.inference);
});
