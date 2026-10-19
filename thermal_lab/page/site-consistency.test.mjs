import {test} from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';
import {computeFleet,NO_LEVERS} from '../../web/src/model/fleet.ts';
import {scienceToolFleets} from '../../web/src/model/quantum.ts';
import {SOURCE} from './model.mjs';import {CPU_DEFAULTS,simulateCPU} from './cpu-model.mjs';
const near=(a,b)=>assert.ok(Math.abs(a-b)<Math.max(.00001,Math.abs(b)*1e-12),`${a} != ${b}`);
test('simulator reference amounts match the main-site fleet model for every source policy variant',()=>{
 for(const caseId of ['A','B','C']){const variants={baseline:NO_LEVERS,siteRouted:{...NO_LEVERS,bgAtSlo:caseId!=='A',subAgents:caseId!=='A'},siteSpeculative:{...NO_LEVERS,bgAtSlo:caseId!=='A',subAgents:caseId!=='A',specDecode:true}};for(const [variant,levers] of Object.entries(variants)){const main=computeFleet({caseId,cooling:'directLiquid',climate:'cold',levers}),local=SOURCE.cases[caseId][variant];near(main.racks,local.racks);near(main.facilityMw,local.facilityMw);near(main.rackCapexUsd,local.rackCapexUsd);}}
});
test('main-page new-build science quantities and local retained-GPU science demand share the same units',()=>{
 const main=scienceToolFleets(1500,1.07);near(main.gpu.units,48000);near(main.gpu.facilityMw,282.48);assert.equal(main.qpu.units,6);near(main.qpu.capexUsd,720e6);
 const local=simulateCPU({...CPU_DEFAULTS,jobsDay:1500,qInitial:6,specDecode:false});const row=local.rows.at(-1);near(row.tools*SOURCE.gpuRack.chips,main.gpu.units);assert.equal(row.qCount,6);near(row.hybridRacks,row.baseRacks);assert.ok(row.hybridMw>row.baseMw); // additive scope, not silently the new-build alternative.
});
test('the public local entry exposes one inflation control and no obsolete bandwidth-growth or GPU-retirement panels',()=>{
 const html=readFileSync(new URL('./index.html',import.meta.url),'utf8');assert.equal((html.match(/id="inflation-toggle"/g)||[]).length,1);assert.ok(html.includes('id="combined-capacity"'));assert.ok(html.includes('id="running-goal"'));assert.ok(!html.includes('id="gpu-replacement"'));assert.ok(!html.includes('id="bandwidth-progression"'));
});


test('the active simulator has an energy breakdown and no Task 2 controls',()=>{
 const html=readFileSync(new URL('./index.html',import.meta.url),'utf8');
 assert.ok(html.includes('id="energy-chart"'));assert.ok(!/chiplet|hotspot|interposer|chip-temperature|GPU thermal proxy/i.test(html));
 const app=readFileSync(new URL('./cpu-app.mjs',import.meta.url),'utf8');assert.ok(!app.includes('c-tempLimit'));assert.ok(!app.includes('r.temperature'));
});
