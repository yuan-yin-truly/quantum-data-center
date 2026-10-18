import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DEFAULTS,SOURCE,simulate} from './model.mjs';
import {SOURCED_PROPOSAL} from './sources.mjs';
import {SCENARIOS,buildCaseScenario,missingInputs} from './scenarios.mjs';
const near=(a,b)=>assert.ok(Math.abs(a-b)<Math.max(1e-6,Math.abs(b)*1e-12),`${a} != ${b}`);
const run=extra=>simulate({...DEFAULTS,qcRouterMax:1,qcRouterCoverage:100,qcRouterGain:0,...extra});
test('all base cases match the shared research-note reference exactly',()=>{
 for(const id of ['A','B','C']){const c=SOURCE.cases[id],r=run({caseId:id}).rows[0];near(r.baseMw,c.baseline.facilityMw);near(r.hybridMw,c.routed.facilityMw);near(r.baseInitial,c.baseline.rackCapexUsd);near(r.hybridInitial,c.routed.rackCapexUsd);}
});
test('speculative decoding uses the existing source variant',()=>{for(const id of ['A','B','C'])near(run({caseId:id,specDecode:true}).rows[0].hybridMw,SOURCE.cases[id].speculative.facilityMw);});
test('reference spans 2030 through 2040 and no annual efficiency trend is invented',()=>{const r=run({}).rows;assert.equal(r.length,11);assert.equal(r[0].year,2030);assert.equal(r.at(-1).year,2040);for(const y of r)near(y.hybridMw,r[0].hybridMw);});
test('dedicated QC router is counted separately from optional tool QPUs',()=>{const r=run({}).rows;assert.equal(r[0].qcRouterNew,1);assert.equal(r[1].qcRouterNew,0);for(const y of r){assert.equal(y.qcRouterCount,1);assert.equal(y.qCount,0);assert.equal(y.totalQuantumCount,1);}});
test('missing QC and operating inputs remain unknown and block full feasibility/savings claim',()=>{const s=run({});assert.equal(s.budgetComplete,false);assert.equal(s.feasible,false);assert.equal(s.breakEven,null);for(const y of s.rows){assert.equal(y.powerComplete,false);assert.equal(y.costsComplete,false);assert.equal(y.energyKnown,false);assert.equal(y.schedulerKnown,false);}});
test('optional rollout respects availability, start and installed maximum',()=>{const r=run({start:2032,qAvailableFrom:2035,add:3,maxQ:5}).rows;assert.equal(r[4].qCount,0);assert.equal(r[5].qCount,3);assert.equal(r[6].qCount,5);assert.equal(r.at(-1).qCount,5);});
test('tool QPUs cannot offload LLM work and retained cohort power is fixed',()=>{const r=run({start:2030,qAvailableFrom:2030,qAnchorYear:2030,add:1,maxQ:1,toolShare:0,qJobs:10000,jobHours:100,eligible:100,qPowerDrop:30}).rows;for(const y of r){assert.equal(y.offload,0);near(y.qPower,r[0].qPower);}});
test('annual and accumulated capital/running costs reconcile without retirement refunds',()=>{const s=run({qcRouterStart:2033,qcRouterPrice:40,qcRouterMw:.1,qcRouterLatencyMs:10,electricity:.1,util:60,maintenance:2,building:0,network:0,coolingCapex:0});let sum=0;for(const y of s.rows){sum+=Object.values(y.costs).reduce((a,b)=>a+b,0);near(sum,y.hybridCumulative);near(y.hybridCapital+y.hybridOperating,y.hybridCumulative);}assert.ok(s.rows[3].retired>0);assert.ok(s.rows[3].hybridInitial>=40e6);near(s.windowCost,s.rows[4].hybridCumulative);});
test('classically optimized comparison does not invent a QC advantage',()=>{const r=run({reference:'optimizedGpu',qcRouterPrice:40,qcRouterMw:.1}).rows[0];assert.ok(r.savings<0);near(r.baseRacks,r.hybridRacks);});
test('insufficient capacity and unsuitable cooling cannot pass service checks',()=>{assert.ok(run({gpuKeep:20}).rows.every(r=>r.served<1));assert.ok(run({cooling:'air'}).rows.every(r=>!r.thermalOk));});

test('QC routing rollout counts units, caps coverage, and releases GPU capacity progressively',()=>{
 const rows=simulate({...DEFAULTS,qcRouterMw:.0125,qcRouterPrice:20}).rows;
 assert.deepEqual(rows.slice(0,5).map(r=>r.qcRouterCount),[1,2,3,4,4]);
 assert.deepEqual(rows.slice(0,5).map(r=>r.routingCoverage),[.25,.5,.75,1,1]);
 for(let i=1;i<4;i++)assert.ok(rows[i].hybridRacks<rows[i-1].hybridRacks);
 near(rows[4].hybridRacks,rows[3].hybridRacks);
 near(rows[3].routerFacilityMw,4*.0125*1.07);
 near(rows[0].costs.qc_router,20e6);near(rows[4].costs.qc_router,0);
});
test('extra QC advantage is an assumption that can be turned off',()=>{
 const zero=run({qcRouterGain:0,qcRouterMw:0}).rows[0],up=run({qcRouterGain:10,qcRouterMw:0}).rows[0];
 near(zero.hybridRacks,zero.optimizedRacks);assert.ok(up.hybridRacks<zero.hybridRacks);
 near(up.qcExtraRacksAvoided,zero.hybridRacks-up.hybridRacks);
});
test('buying routers beyond coverage saturation adds overhead, never a fictitious benefit',()=>{
 const r=simulate({...DEFAULTS,qcRouterCoverage:100,qcRouterMax:10,qcRouterMw:1}).rows;
 near(r[0].hybridRacks,r[1].hybridRacks);assert.ok(r[1].hybridMw>r[0].hybridMw);
});
test('all workload shares sum to 100 percent under offload, grid limits and underprovisioning',()=>{
 for(const settings of [{},{gpuKeep:20},{qcRouterMw:600},{toolShare:20,eligible:100,start:2030,qAvailableFrom:2030,qJobs:100000,jobHours:100,add:1,maxQ:1,qMw:1}]){
  for(const r of run(settings).rows){near(r.gpuWorkFraction+r.quantumToolWorkFraction+r.unservedFraction,1);near(r.gpuWorkFraction+r.quantumToolWorkFraction,r.served);assert.ok(r.served<=1);}
 }
});
test('unused scientific QPUs do not inflate completed work and all quantum counts reconcile',()=>{
 const rows=run({add:8,maxQ:16,start:2030,qAvailableFrom:2031,toolShare:0}).rows;
 assert.equal(rows[0].totalQuantumCount,1);assert.equal(rows[2].totalQuantumCount,17);
 for(const r of rows){assert.equal(r.quantumToolWorkFraction,0);assert.equal(r.totalQuantumCount,r.qcRouterCount+r.qCount);}
});
test('higher workload growth dilutes fixed router assignment capacity',()=>{
 const r=run({demandGrowth:10}).rows;assert.ok(r.at(-1).routingCoverage<r[0].routingCoverage);
});

test('published optimistic proposal reduces cost and grid power while covering the same modeled B workload',()=>{
 const s=simulate(buildCaseScenario('B','optimistic','bestCost'));
 assert.ok(s.budgetComplete);assert.ok(s.windowCost<=30e9);
 for(const r of s.rows){assert.ok(r.hybridMw<r.unoptimizedMw);assert.ok(r.hybridCumulative<r.unoptimizedCumulative);assert.ok(r.hybridMw<=500);near(r.served,1);}
 assert.deepEqual(s.rows.slice(0,4).map(r=>r.qcRouterCount),[4,4,4,4]);
 assert.equal(s.feasible,true); // Passes entered assumptions; does not certify measured service.
});

test('all use cases load distinct complete profiles that pass the entered five-year screens',()=>{
 const profiles=['A','B','C'].map(id=>buildCaseScenario(id,'optimistic','bestCost'));
 assert.deepEqual(profiles.map(p=>p.qcRouterInitial),[4,4,4]);
 for(const p of profiles){assert.deepEqual(missingInputs(p),[]);const s=simulate(p);assert.equal(s.feasible,true);assert.ok(s.rows.every(r=>r.served>.999999&&r.hybridMw<=500));}
 assert.equal(new Set(profiles.map(p=>simulate(p).windowCost)).size,3);
});
test('scenario presets affect active QC work rather than an unused scientific pool',()=>{
 for(const id of ['A','B','C']){
  const outputs=Object.keys(SCENARIOS).map(mode=>{const p=buildCaseScenario(id,mode);assert.deepEqual(missingInputs(p),[]);return simulate(p).rows.at(-1).hybridMw;});
  assert.equal(new Set(outputs).size,4);
 }
});
test('deleting active required inputs is detected; zero remains a valid explicit allowance',()=>{
 const p=buildCaseScenario('B','optimistic');
 for(const field of ['qcRouterPrice','qcRouterMw','qcRouterGain','electricity','util','resistance','tempLimit','qcRouterLatencyMs','prefill'])assert.ok(missingInputs({...p,[field]:null}).includes(field));
 assert.deepEqual(missingInputs({...p,prefill:0,coolingCapex:0,otherMw:0}),[]);
});
test('scientific requirements are conditional on enabling the optional pool',()=>{
 const p=buildCaseScenario('B','optimistic');assert.deepEqual(missingInputs(p),[]);
 const missing=missingInputs({...p,add:1});for(const field of ['qJobs','jobHours','qPrice'])assert.ok(missing.includes(field));
});

test('case-specific recommendation minimizes modeled five-year spend over the documented candidate set',()=>{
 for(const caseId of ['A','B','C'])for(const mode of ['conservative','moderate','optimistic']){
  const best=buildCaseScenario(caseId,mode,'bestCost'),staged=buildCaseScenario(caseId,mode,'staged');
  assert.ok(simulate(best).windowCost<=simulate(staged).windowCost);
  for(const count of [1,2,3,4]){const candidate=simulate({...best,qcRouterInitial:count});if(candidate.feasible)assert.ok(simulate(best).windowCost<=candidate.windowCost+.01);}
 }
});

test('annual deployment decreases grid demand and running cost every year through 2040 for every QC case',()=>{
 for(const id of ['A','B','C'])for(const mode of ['conservative','moderate','optimistic']){
  const p=buildCaseScenario(id,mode),s=simulate(p);
  assert.equal(p.rolloutStrategy,'staged');assert.equal(p.qcAdoptionEndYear,2040);assert.ok(s.feasible);
  for(let i=1;i<s.rows.length;i++){
   assert.ok(s.rows[i].routingCoverage>s.rows[i-1].routingCoverage,`${id}/${mode} coverage ${i}`);
   assert.ok(s.rows[i].hybridMw<s.rows[i-1].hybridMw,`${id}/${mode} power ${i}`);
   assert.ok(s.rows[i].hybridRunning<s.rows[i-1].hybridRunning,`${id}/${mode} running ${i}`);
   assert.ok(s.rows[i].hybridCumulative>=s.rows[i-1].hybridCumulative);
  }
  near(s.rows.at(-1).routingCoverage,1);
 }
});
test('deployment coverage never exceeds installed routing hardware',()=>{
 const p=buildCaseScenario('B','optimistic');
 const s=simulate({...p,qcRouterInitial:1,qcRouterAdd:0,qcRouterMax:1,qcAdoptionStart:80});
 for(const row of s.rows)assert.ok(row.routingCoverage<=row.hardwareCoverage);
});
test('turning off routing QPUs does not turn on the scientific pool',()=>{
 const p=buildCaseScenario('B','optimistic');
 const row=simulate({...p,qcRouterOn:false}).rows[0];
 assert.equal(row.qcRouterCount,0);assert.equal(row.qCount,0);assert.equal(row.routingCoverage,0);
});
