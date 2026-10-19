import {INFLATION_REFERENCE,applyRunningInflation} from './inflation.mjs';
import {CASES,SOURCE,COOLING,policyVariant} from './catalog.mjs';
export const START_YEAR=SOURCE.hardwareYear,END_YEAR=START_YEAR+10;
// The deck fixes a 2035 catalog, not a technology forecast. The 3% annual
// reduction below is an editable serving-efficiency what-if, applied equally.
export const CPU_DEFAULTS={caseId:'B',includeInflation:false,inflationRate:INFLATION_REFERENCE.average,domain:'chemistry',jobsDay:500,profileId:'qpu_cat40k:chemistry_small',gpuHours:768,qJobs:11.700747173175559,qMw:.26976355225,qPrice:120,profileFeasible:true,algorithmSupported:true,accuracyMatched:true,deadlineHours:4,start:2035,available:2035,qInitial:2,add:0,maxQ:16,qCoolingShare:25,qControlsShare:15,qInstallPrice:2,qNetworkPrice:.5,qExternalKw:5,gpuIdlePercent:20,qLinkGbps:null,routerKw:5,routerPrice:.05,specDecode:true,gpuEnergyReduction:3,electricity:.0862,util:60,building:13.3,network:5,maintenance:2,prefill:5,otherMw:2,coolingCapex:0,cooling:'liquid',climate:'cold'};
export const DOMAINS={chemistry:'Quantum chemistry / materials',biology:'Biology · molecular electronic-structure kernel',physics:'Physics · many-body quantum kernel',ordinary:'Ordinary code, AI or classical science'};
export function missingCPU(p){
 const errors=Object.keys(CPU_DEFAULTS).filter(k=>(k!=='inflationRate'||p.includeInflation)&&typeof CPU_DEFAULTS[k]==='number'&&(!Number.isFinite(p[k])||p[k]<0));
 for(const key of ['qJobs','gpuHours','deadlineHours'])if(p[key]<=0)errors.push(key);
 if(p.qCoolingShare+p.qControlsShare>100)errors.push('QPU cooling + controls shares must total at most 100%');
 if(p.gpuIdlePercent>100)errors.push('gpuIdlePercent');
 if(p.util>100||p.util<p.gpuIdlePercent)errors.push('Average GPU power must be between the idle floor and 100%');
 if(p.gpuEnergyReduction>=100)errors.push('gpuEnergyReduction');
 for(const key of ['qInitial','add','maxQ','start','available'])if(!Number.isInteger(p[key]))errors.push(key);
 for(const key of ['start','available'])if(p[key]<START_YEAR||p[key]>END_YEAR)errors.push(key);
 if(p.maxQ>100)errors.push('maxQ');
 if(p.qLinkGbps!=null&&(!Number.isFinite(p.qLinkGbps)||p.qLinkGbps<0))errors.push('qLinkGbps');
 if(!CASES[p.caseId])errors.push('caseId');
 if(!COOLING[p.cooling]?.[p.climate])errors.push('cooling / climate');
 return [...new Set(errors)];
}
export function gpuEnergyFactor(p,year){return (1-p.gpuEnergyReduction/100)**(year-START_YEAR);}
export function qpuCosts(p){const system=p.qPrice*1e6,refrigeration=system*p.qCoolingShare/100,controls=system*p.qControlsShare/100;return {compute:system-refrigeration-controls,refrigeration,controls,system,installation:p.qInstallPrice*1e6,network:p.qNetworkPrice*1e6,infrastructure:(p.qMw*1000+p.qExternalKw)*(p.building*1000+p.coolingCapex),get total(){return this.system+this.installation+this.network+this.infrastructure;}};}
export function routeScientific(p,year,installed){
 if(p.domain==='ordinary')return {eligible:false,reason:'Ordinary classical work stays on CPU/GPU; subject labels alone do not establish a quantum algorithm.'};
 if(!p.algorithmSupported||!p.profileFeasible)return {eligible:false,reason:'No supported, feasible quantum method for this workload/profile. Installed QPUs still cost money and draw power.'};
 if(!p.accuracyMatched)return {eligible:false,reason:'Matched output quality is not established in this scenario; use GPU fallback.'};
 if(year<Math.max(p.start,p.available))return {eligible:false,reason:`QPU hardware is unavailable until ${Math.max(p.start,p.available)}; use GPU fallback.`};
 if(installed===0)return {eligible:false,reason:'No QPUs installed in this inspection year; use GPU fallback.'};
 if(1/p.qJobs>p.deadlineHours)return {eligible:false,reason:'The modeled mean QPU service-time screen exceeds the scientific deadline.'};
 if(p.qLinkGbps===0)return {eligible:false,reason:'The entered host-link bandwidth is zero; no scientific jobs can be admitted to the QPU wing.'};
 if(p.jobsDay===0)return {eligible:false,reason:'No scientific jobs requested. Installed QPUs remain powered and charged.'};
 const n=installed??Math.ceil(p.jobsDay/(p.qJobs*24)),jobs=Math.min(p.jobsDay,n*p.qJobs*24),pue=COOLING[p.cooling][p.climate];
 const gpuKwh=p.gpuHours*(SOURCE.gpuRack.kw/SOURCE.gpuRack.chips)*(1+p.prefill/100)*pue*(1-p.gpuIdlePercent/100)*gpuEnergyFactor(p,year);
 const qKwh=(p.qMw*1000+p.qExternalKw)*pue*24*n/jobs;
 const gpuCost=gpuKwh*p.electricity,qCost=qKwh*p.electricity+n*qpuCosts(p).total*p.maintenance/100/(365*jobs);
 // Dispatch installed hardware on net energy benefit. Unavoidable maintenance
 // is assessed by the full-year cost verdict, not used to leave useful QPUs idle.
 const eligible=qKwh<gpuKwh;
 return {eligible,gpuKwh,qKwh,gpuCost,qCost,reason:eligible?'Supported kernel, assumed matched quality and a net energy benefit after whole-wing power. GPU progress is included in this year’s avoided energy. Annual running-cost success is checked separately.':'The full installed QPU wing consumes at least as much energy as the GPU activity it could avoid this year. Use GPU fallback; installed QPU overhead remains charged.'};
}
export function simulateCPU(p){
 const missing=missingCPU(p);if(missing.length)throw new Error('Required input missing or invalid: '+missing.join(', '));
 const c=CASES[p.caseId],routed=policyVariant(c,{policyBasis:'website',specDecode:p.specDecode}),jobs=p.caseId==='A'?0:p.jobsDay;
 const pue=COOLING[p.cooling][p.climate],rack=SOURCE.gpuRack,cost=qpuCosts(p),gpuMwPerRack=rack.kw/1000*(1+p.prefill/100),idle=p.gpuIdlePercent/100;
 const tools=jobs*p.gpuHours/(24*rack.chips),llmRacks=routed.racks,baseRacks=llmRacks+tools,unoptimizedRacks=c.baseline.racks+tools;
 const supportMw=(p.otherMw+p.routerKw/1000)*pue,baseMw=baseRacks*gpuMwPerRack*pue+supportMw;
 const infrastructure=racks=>racks*rack.usd*p.network/100+(racks*rack.kw*(1+p.prefill/100)+(p.otherMw+p.routerKw/1000)*1000)*(p.building*1000+p.coolingCapex);
 const cpuCapital=p.routerPrice*1e6,baseCapital=baseRacks*rack.usd+infrastructure(baseRacks)+cpuCapital,unoptimizedCapital=unoptimizedRacks*rack.usd+infrastructure(unoptimizedRacks)+cpuCapital;
 const toGwh=gpuMwPerRack*pue*8.76,fixedGpuIdleGwh=baseRacks*idle*toGwh,supportGwh=supportMw*8.76;
 const noProgressGpuGwh=(llmRacks*p.util/100+tools)*toGwh,installedGpuCount=Math.ceil(baseRacks*rack.chips);
 let count=0,wingCapital=0;
 const rows=Array.from({length:END_YEAR-START_YEAR+1},(_,i)=>{
  const year=START_YEAR+i,first=Math.max(p.start,p.available),requested=year<first?0:year===first?p.qInitial:p.add,newQ=Math.min(requested,Math.max(0,p.maxQ-count));count+=newQ;wingCapital+=newQ*cost.total;
  const energyFactor=gpuEnergyFactor(p,year),decision=routeScientific({...p,jobsDay:jobs},year,count),qpuJobsDay=decision.eligible?Math.min(jobs,count*p.qJobs*24):0,offload=qpuJobsDay*p.gpuHours/(24*rack.chips);
  const baseGpuDynamicGwh=(llmRacks*(p.util/100-idle)+tools*(1-idle))*toGwh*energyFactor;
  const avoidedGpuGwh=offload*(1-idle)*toGwh*energyFactor,baseGpuGwh=fixedGpuIdleGwh+baseGpuDynamicGwh,gpuGwh=baseGpuGwh-avoidedGpuGwh;
  const qPower=count*p.qMw,toolFacilityMw=qPower*pue,qpuSupportFacilityMw=count*p.qExternalKw/1000*pue,toolGwh=toolFacilityMw*8.76,wingSupportGwh=qpuSupportFacilityMw*8.76;
  const baseGwh=baseGpuGwh+supportGwh,hybridGwh=gpuGwh+supportGwh+wingSupportGwh+toolGwh,hybridMw=baseMw+toolFacilityMw+qpuSupportFacilityMw;
  const hybridCapital=baseCapital+wingCapital,baseInitial=i===0?baseCapital:0,hybridInitial=baseInitial+newQ*cost.total,baseRunning=baseGwh*1e6*p.electricity+baseCapital*p.maintenance/100,electricity=hybridGwh*1e6*p.electricity,maintenance=hybridCapital*p.maintenance/100;
  const unoptimizedGwh=(unoptimizedRacks*idle+(c.baseline.racks*(p.util/100-idle)+tools*(1-idle))*energyFactor)*toGwh+supportGwh;
  // Peak is conservative installed-nameplate capacity. Energy improvements do
  // not create extra memory, speed, slots or permission to exceed the grid cap.
  const gridOk=hybridMw<=SOURCE.limits.gridMw,coolingOk=rack.kw*(1+p.prefill/100)<=COOLING[p.cooling].max;
  const gpuWorkFraction=(baseRacks-offload)/Math.max(1e-12,baseRacks),quantumToolWorkFraction=offload/Math.max(1e-12,baseRacks),served=gridOk&&coolingOk?1:0;
  const totalDailyTasks=c.users*Object.values(SOURCE.caseWorkloads[p.caseId].perDay).reduce((a,b)=>a+b,0)+jobs;
  return {year,baseRacks,hybridRacks:baseRacks,hybridPhysicalRacks:Math.ceil(baseRacks),llmRacks,tools,jobsDay:jobs,qpuJobsDay,gpuJobsDay:jobs-qpuJobsDay,offload,decision,qCount:count,newQ,qPower,toolCapital:count*cost.system,wingCapital,qpuCostComponents:cost,qpuSupportFacilityMw,toolFacilityMw,supportFacilityMw:supportMw+qpuSupportFacilityMw,baseMw,hybridMw,baseGwh,hybridGwh,gpuGwh,supportGwh:supportGwh+wingSupportGwh,toolGwh,baseGpuGwh,baseSupportGwh:supportGwh,wingSupportGwh,fixedGpuIdleGwh,baseGpuDynamicGwh,hybridGpuDynamicGwh:baseGpuDynamicGwh-avoidedGpuGwh,avoidedGpuGwh,gpuEfficiencySavedGwh:noProgressGpuGwh-baseGpuGwh,energyFactor,noProgressBaseGwh:noProgressGpuGwh+supportGwh,baseAverageOperatingMw:baseGwh/8.76,averageOperatingMw:hybridGwh/8.76,baseCapital,hybridCapital,baseInitial,hybridInitial,baseRunning,hybridRunning:electricity+maintenance,unoptimizedCapital,unoptimizedInitial:i===0?unoptimizedCapital:0,unoptimizedRunning:unoptimizedGwh*1e6*p.electricity+unoptimizedCapital*p.maintenance/100,installedGpuCount,aggregateGpuBandwidthTbps:installedGpuCount*SOURCE.gpu.peakBytesPerS/1e12,aggregateGpuReadTbps:installedGpuCount*SOURCE.gpuEffectiveReadBytesPerS/1e12,aggregateGpuMemoryTb:installedGpuCount*SOURCE.gpu.memBytes/1e12,qpuCapacityDay:count*p.qJobs*24,qpuHostLinkGbps:Number.isFinite(p.qLinkGbps)?count*p.qLinkGbps:null,retiredGpuRacks:0,retired:0,gpuRacksReleased:0,cpuRouterCount:1,routingQpuCount:0,totalQuantumCount:count,totalQuantumNew:newQ,served,gpuWorkFraction:gpuWorkFraction*served,quantumToolWorkFraction:quantumToolWorkFraction*served,unservedFraction:1-served,gridOk,coolingOk,totalDailyTasks,baseJoulesPerTask:baseGwh*3.6e12/(totalDailyTasks*365),hybridJoulesPerTask:hybridGwh*3.6e12/(totalDailyTasks*365),costs:{gpu:i===0?baseRacks*rack.usd:0,quantum:newQ*cost.compute,qpu_refrigeration:newQ*cost.refrigeration,qpu_controls:newQ*cost.controls,qpu_installation:newQ*cost.installation,qpu_network:newQ*cost.network,infrastructure:(i===0?infrastructure(baseRacks):0)+newQ*cost.infrastructure,cpu_router:i===0?cpuCapital:0,electricity,maintenance}};
 });
 const adjusted=applyRunningInflation(rows,p.includeInflation,p.inflationRate,START_YEAR),windowCost=adjusted[4].hybridCumulative,budgetOk=windowCost<=SOURCE.limits.budgetUsd;
 for(const r of adjusted){r.rolloutBudgetOk=r.hybridCumulative<=SOURCE.limits.budgetUsd;r.energySavingGwh=r.baseGwh-r.hybridGwh;r.energySavingPercent=r.energySavingGwh/r.baseGwh*100;r.energyOk=r.qCount===0?null:r.energySavingGwh>1e-9;r.runningCostSaving=r.baseRunning-r.hybridRunning;r.runningCostSavingPercent=r.runningCostSaving/r.baseRunning*100;r.runningCostOk=r.qCount===0?null:r.runningCostSaving>.01;r.runningCostStatus=r.qCount===0?'not-deployed':r.runningCostOk?'lower':'target-failed';}
 const valid=r=>r.gridOk&&r.rolloutBudgetOk&&r.served===1&&r.coolingOk,deployed=adjusted.filter(r=>r.qCount>0),runningCostGoalMet=deployed.length>0&&deployed.every(r=>r.runningCostOk),energyGoalMet=deployed.length>0&&deployed.every(r=>r.energyOk),constraintsFeasible=budgetOk&&adjusted.every(valid);
 return {rows:adjusted,startYear:START_YEAR,endYear:END_YEAR,budgetYears:[START_YEAR,START_YEAR+4],runningCostGoalMet,energyGoalMet,constraintsFeasible,hybridSuccess:constraintsFeasible&&runningCostGoalMet&&energyGoalMet,windowCost,budgetComplete:true,budgetOk,forecastFeasible:budgetOk&&adjusted.every(r=>valid(r)&&r.runningCostOk!==false&&r.energyOk!==false),breakEven:adjusted.find(r=>r.savings>.01&&valid(r)&&r.energyOk&&r.runningCostOk)?.year??null};
}
export function recommendQpuCount(p){let best=null;for(let count=1;count<=p.maxQ;count++){const candidate={...p,qInitial:count,add:0},result=simulateCPU(candidate);if(!result.hybridSuccess)continue;const running=result.rows.reduce((sum,r)=>sum+r.hybridRunning,0);if(!best||running<best.running-.01)best={count,running,parameters:candidate,result};}return best;}
