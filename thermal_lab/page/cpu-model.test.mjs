import {test} from 'node:test';import assert from 'node:assert/strict';
import {CPU_DEFAULTS,START_YEAR,END_YEAR,simulateCPU,routeScientific,missingCPU,qpuCosts,recommendQpuCount} from './cpu-model.mjs';
import {SOURCE} from './model.mjs';import {workloadCapacity,perGpuCapacity} from './bandwidth.mjs';
const near=(a,b)=>assert.ok(Math.abs(a-b)<Math.max(.00001,Math.abs(b)*1e-12),`${a} != ${b}`);
test('the GPU fleet stays installed in both comparisons for every year and QPU count',()=>{
 for(const qInitial of [0,1,2,6]){const s=simulateCPU({...CPU_DEFAULTS,qInitial});for(const r of s.rows){near(r.hybridRacks,r.baseRacks);assert.equal(r.installedGpuCount,s.rows[0].installedGpuCount);assert.equal(r.retiredGpuRacks,0);assert.equal(r.gpuRacksReleased,0);}}
});
test('installed QPUs follow the explicit count and yearly additions, including unused systems',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,start:2040,qInitial:6,add:1,maxQ:8,algorithmSupported:false});assert.deepEqual(s.rows.slice(5,9).map(r=>r.qCount),[6,7,8,8]);for(const r of s.rows.slice(5)){assert.equal(r.qpuJobsDay,0);assert.ok(r.wingCapital>0);assert.ok(r.toolGwh>0);assert.ok(r.hybridCumulative>r.baseCumulative);}
});
test('both fleets match before availability; peak power increases when the wing is installed',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,start:2040});for(const r of s.rows){if(r.year<2040){near(r.baseMw,r.hybridMw);near(r.baseRunning,r.hybridRunning);near(r.savings,0);}else{assert.ok(r.hybridMw>r.baseMw);assert.ok(r.averageOperatingMw<r.baseAverageOperatingMw);}}
});
test('scientific capacity and overflow are bounded by actual installed QPUs',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,qInitial:1});for(const r of s.rows){near(r.qpuJobsDay+r.gpuJobsDay,r.jobsDay);assert.ok(r.qpuJobsDay<=r.qCount*CPU_DEFAULTS.qJobs*24+1e-9);}assert.ok(s.rows.at(-1).gpuJobsDay>0);
});
test('whole-system price is split once; internal cooler and controls shares never double charge it',()=>{
 const c=qpuCosts(CPU_DEFAULTS);near(c.compute+c.refrigeration+c.controls,c.system);near(c.total,c.system+c.installation+c.network+c.infrastructure);assert.ok(c.refrigeration>0);assert.ok(c.installation>0);assert.ok(c.infrastructure>0);
 assert.ok(missingCPU({...CPU_DEFAULTS,qCoolingShare:90,qControlsShare:20}).length>0);
});
test('capital, energy, annual costs and cumulative totals reconcile including all QPU components',()=>{
 for(const includeInflation of [false,true]){const s=simulateCPU({...CPU_DEFAULTS,includeInflation});let base=0,hybrid=0,capital=0;
 for(const r of s.rows){base+=r.baseRunning;hybrid+=r.hybridRunning;capital+=r.hybridInitial;near(r.hybridCapital,capital);near(r.baseCapital+base,r.baseCumulative);near(r.hybridCapital+hybrid,r.hybridCumulative);near(r.baseCumulative-r.hybridCumulative,r.savings);near(Object.values(r.costs).reduce((a,b)=>a+b,0),r.hybridSpend);near(r.gpuGwh+r.supportGwh+r.toolGwh,r.hybridGwh);near(r.baseMw+r.toolFacilityMw+r.qpuSupportFacilityMw,r.hybridMw);}
 near(s.windowCost,s.rows[4].hybridCumulative);}
});
test('retained scientific GPUs have idle draw; 100% idle eliminates GPU-energy savings',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,gpuIdlePercent:100,util:100});for(const r of s.rows){near(r.qpuJobsDay,0);assert.ok(r.hybridGwh>=r.baseGwh);assert.ok(r.hybridRunning>=r.baseRunning);}
});
test('aggregate GPU HBM and QPU host-link bandwidth use their own units and count every installed system',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,qLinkGbps:100});for(const r of s.rows){near(r.aggregateGpuBandwidthTbps,r.installedGpuCount*120);near(r.aggregateGpuReadTbps,r.installedGpuCount*72);near(r.aggregateGpuMemoryTb,r.installedGpuCount*3);near(r.qpuHostLinkGbps,r.qCount*100);near(r.qpuCapacityDay,r.qCount*CPU_DEFAULTS.qJobs*24);}
 assert.equal(simulateCPU(CPU_DEFAULTS).rows.at(-1).qpuHostLinkGbps,null);
});
test('the formal five-year and additional full-rollout budget screens include late QPU purchases',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,start:2040,qPrice:10000});assert.ok(s.windowCost<30e9);assert.ok(s.rows.at(-1).hybridCumulative>30e9);assert.equal(s.rows.at(-1).rolloutBudgetOk,false);assert.equal(s.forecastFeasible,false);
});
test('500 MW checks the full retained GPU fleet plus the QPU wing, not only the dispatched workload',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,qMw:200});assert.ok(s.rows.at(-1).hybridMw>500);assert.equal(s.rows.at(-1).gridOk,false);assert.equal(s.forecastFeasible,false);
});
test('zero science does not erase explicitly installed QPU overhead',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,caseId:'A'});for(const r of s.rows){assert.equal(r.jobsDay,0);assert.equal(r.qpuJobsDay,0);}assert.equal(s.rows.at(-1).qCount,2);assert.ok(s.rows.at(-1).savings<0);
});
test('unsupported or unmatched scientific work stays classical without erasing installed hardware',()=>{
 for(const change of [{algorithmSupported:false},{accuracyMatched:false},{profileFeasible:false},{domain:'ordinary'},{deadlineHours:.01}]){const s=simulateCPU({...CPU_DEFAULTS,...change});assert.ok(s.rows.every(r=>r.qpuJobsDay===0));assert.equal(s.rows.at(-1).qCount,2);}
});
test('default cases pass the modeled slide restrictions and preserve workload accounting',()=>{
 for(const caseId of ['A','B','C']){const s=simulateCPU({...CPU_DEFAULTS,caseId});assert.ok(s.constraintsFeasible);assert.equal(s.hybridSuccess,caseId!=='A');for(const r of s.rows){near(r.served,1);near(r.gpuWorkFraction+r.quantumToolWorkFraction+r.unservedFraction,1);assert.ok(r.hybridMw<=500);assert.ok(r.hybridCumulative<=30e9);}}
 const p=CPU_DEFAULTS,s=simulateCPU(p),c=workloadCapacity(p,s.rows.at(-1));assert.equal(c.users,50e6);assert.equal(c.peakOutTokensPerSecond,1.4e9);assert.equal(c.interactiveTasksDay,600e6);assert.equal(c.backgroundTasksDay,1.5e9);
});
test('slide bandwidth calibration is unchanged and meaningful only for the GPU catalog',()=>{
 assert.equal(SOURCE.gpu.peakBytesPerS,120e12);assert.equal(SOURCE.gpu.memBytes,3e12);near(perGpuCapacity('chat',120).users,960);near(perGpuCapacity('agent',120).users,117);assert.equal(SOURCE.gpuRack.chips,144);assert.equal(SOURCE.gpuRack.kw,792);
});
test('inflation toggle changes operating bills but not installed capacity or purchase prices',()=>{
 const normal=simulateCPU(CPU_DEFAULTS),inflated=simulateCPU({...CPU_DEFAULTS,includeInflation:true});for(let i=0;i<normal.rows.length;i++){const a=normal.rows[i],b=inflated.rows[i];near(b.baseRunning,a.baseRunning*1.032**i);near(b.hybridRunning,a.hybridRunning*1.032**i);near(b.hybridCapital,a.hybridCapital);near(b.hybridMw,a.hybridMw);near(b.aggregateGpuBandwidthTbps,a.aggregateGpuBandwidthTbps);}
 assert.deepEqual(simulateCPU({...CPU_DEFAULTS,includeInflation:false,inflationRate:null}).rows,normal.rows);
});
test('missing QPU hardware, cooling and installation values block cost claims; optional host bandwidth can be unknown',()=>{
 for(const k of ['qPrice','qCoolingShare','qControlsShare','qInstallPrice','qNetworkPrice','qExternalKw'])assert.ok(missingCPU({...CPU_DEFAULTS,[k]:null}).includes(k));assert.deepEqual(missingCPU({...CPU_DEFAULTS,qLinkGbps:null}),[]);
});

test('running-cost success is mandatory for every deployed year and neutral before deployment',()=>{
 const s=simulateCPU(CPU_DEFAULTS);assert.ok(s.hybridSuccess);assert.ok(s.runningCostGoalMet);for(const r of s.rows){if(r.qCount===0){assert.equal(r.runningCostOk,null);assert.equal(r.runningCostStatus,'not-deployed');near(r.runningCostSaving,0);}else{assert.equal(r.runningCostOk,true);assert.ok(r.hybridRunning<r.baseRunning);near(r.runningCostSaving,r.baseRunning-r.hybridRunning);}}
});
test('already installed extra QPUs do not block useful dispatch because of sunk acquisition cost',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,qInitial:6});const r=s.rows.at(-1);assert.equal(r.qCount,6);near(r.qpuJobsDay,500);assert.ok(r.runningCostOk);assert.ok(s.hybridSuccess);
});
test('passing power and budget is insufficient when the hybrid running-cost target fails',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,qInitial:25,maxQ:25});assert.ok(s.constraintsFeasible);assert.equal(s.runningCostGoalMet,false);assert.equal(s.hybridSuccess,false);assert.equal(s.forecastFeasible,false);assert.equal(s.rows.at(-1).runningCostStatus,'target-failed');assert.ok(s.rows.at(-1).hybridRunning>s.rows.at(-1).baseRunning);
});
test('the recommendation selects a genuinely cheaper feasible count without changing prices, workloads or GPUs',()=>{
 const best=recommendQpuCount(CPU_DEFAULTS);assert.equal(best.count,2);assert.ok(best.result.hybridSuccess);assert.equal(best.parameters.qPrice,CPU_DEFAULTS.qPrice);assert.equal(best.parameters.jobsDay,CPU_DEFAULTS.jobsDay);for(const r of best.result.rows)near(r.baseRacks,r.hybridRacks);
 assert.equal(recommendQpuCount({...CPU_DEFAULTS,caseId:'A'}),null);assert.equal(recommendQpuCount({...CPU_DEFAULTS,algorithmSupported:false}),null);
});
test('inflation preserves the running-cost comparison on the same price basis',()=>{
 for(const qInitial of [2,6,25]){const a=simulateCPU({...CPU_DEFAULTS,qInitial,maxQ:25}),b=simulateCPU({...CPU_DEFAULTS,qInitial,maxQ:25,includeInflation:true});assert.equal(a.runningCostGoalMet,b.runningCostGoalMet);for(let i=0;i<a.rows.length;i++)near(a.rows[i].runningCostSavingPercent,b.rows[i].runningCostSavingPercent);}
});


test('forecast begins at the slide catalog year and budgets the first five deployed calendar years',()=>{
 const s=simulateCPU(CPU_DEFAULTS);assert.equal(START_YEAR,2035);assert.equal(END_YEAR,2045);assert.deepEqual(s.budgetYears,[2035,2039]);assert.equal(s.rows[0].qCount,2);near(s.windowCost,s.rows.slice(0,5).reduce((n,r)=>n+r.hybridSpend,0));
});
test('GPU progress benefits both comparators equally and keeps the installed idle floor',()=>{
 const fixed=simulateCPU({...CPU_DEFAULTS,gpuEnergyReduction:0}),progress=simulateCPU(CPU_DEFAULTS);
 for(let i=0;i<progress.rows.length;i++){
  const a=fixed.rows[i],b=progress.rows[i],f=.97**i;
  near(b.energyFactor,f);near(b.baseGpuDynamicGwh,a.baseGpuDynamicGwh*f);near(b.hybridGpuDynamicGwh,a.hybridGpuDynamicGwh*f);near(b.fixedGpuIdleGwh,a.fixedGpuIdleGwh);near(b.gpuGwh,b.fixedGpuIdleGwh+b.hybridGpuDynamicGwh);near(b.baseMw,a.baseMw);near(b.baseCapital,a.baseCapital);near(b.qpuJobsDay,a.qpuJobsDay);
 }
});
test('fixed workloads use less absolute energy over time with progress; no progress gives flat energy',()=>{
 for(const gpuEnergyReduction of [0,3]){const s=simulateCPU({...CPU_DEFAULTS,gpuEnergyReduction});for(let i=1;i<s.rows.length;i++){const a=s.rows[i-1],b=s.rows[i];near(a.totalDailyTasks,b.totalDailyTasks);if(gpuEnergyReduction){assert.ok(b.hybridGwh<a.hybridGwh);assert.ok(b.baseGwh<a.baseGwh);}else{near(a.hybridGwh,b.hybridGwh);near(a.baseGwh,b.baseGwh);}}}
});
test('full energy bridge reconciles and joules per task use an identical workload denominator',()=>{
 const s=simulateCPU(CPU_DEFAULTS);for(const r of s.rows){near(r.noProgressBaseGwh-r.gpuEfficiencySavedGwh,r.baseGwh);near(r.baseGwh-r.avoidedGpuGwh+r.toolGwh+r.wingSupportGwh,r.hybridGwh);near(r.energySavingGwh,r.avoidedGpuGwh-r.toolGwh-r.wingSupportGwh);near(r.hybridJoulesPerTask,r.hybridGwh*3.6e12/(r.totalDailyTasks*365));near(r.baseJoulesPerTask/r.hybridJoulesPerTask,r.baseGwh/r.hybridGwh);assert.ok(r.energyOk);}
 assert.ok(s.energyGoalMet&&s.hybridSuccess);
});
test('sufficient GPU progress can remove quantum advantage; no values are clipped or forced',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,gpuEnergyReduction:60});const r=s.rows.at(-1);assert.equal(r.qpuJobsDay,0);assert.ok(r.hybridGwh>r.baseGwh);assert.equal(r.energyOk,false);assert.equal(s.energyGoalMet,false);assert.equal(s.hybridSuccess,false);
});
test('unavoidable maintenance does not prevent useful energy-saving dispatch but can fail annual cost success',()=>{
 const s=simulateCPU({...CPU_DEFAULTS,qPrice:1000,maintenance:5});const r=s.rows[0];near(r.qpuJobsDay,500);assert.ok(r.energyOk);assert.ok(!r.runningCostOk);assert.equal(s.hybridSuccess,false);
});
test('inflation changes bills but never physical energy or the energy verdict',()=>{
 const a=simulateCPU(CPU_DEFAULTS),b=simulateCPU({...CPU_DEFAULTS,includeInflation:true});for(let i=0;i<a.rows.length;i++){near(a.rows[i].hybridGwh,b.rows[i].hybridGwh);near(a.rows[i].baseGwh,b.rows[i].baseGwh);near(b.rows[i].inflationFactor,1.032**i);}assert.equal(a.energyGoalMet,b.energyGoalMet);
});
test('invalid rates, fractional systems and blank progress inputs cannot produce a result',()=>{
 for(const change of [{gpuEnergyReduction:null},{gpuEnergyReduction:100},{qInitial:1.5},{start:2030}])assert.ok(missingCPU({...CPU_DEFAULTS,...change}).length);
});
test('the active model has no Track 2 temperature inputs or exported chip-temperature fields',()=>{
 for(const k of ['coolant','tempLimit','resistance'])assert.ok(!(k in CPU_DEFAULTS));for(const r of simulateCPU(CPU_DEFAULTS).rows)for(const k of ['temperature','thermalOk','thermalKnown'])assert.ok(!(k in r));
});
