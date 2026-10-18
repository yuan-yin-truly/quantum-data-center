import SOURCE from './fleet-reference.mjs';
export {SOURCE};
export const CASES=Object.fromEntries(Object.entries(SOURCE.cases).map(([id,c])=>[id,{...c,racks:c.routed.racks}]));
export const PRESETS={reference:{qGrowth:0,qPriceDrop:0,qPowerDrop:0,eligibilityGrowth:0,gpuGrowth:0,demandGrowth:0},conservative:{qGrowth:10,qPriceDrop:3,qPowerDrop:2,eligibilityGrowth:1},moderate:{qGrowth:25,qPriceDrop:8,qPowerDrop:5,eligibilityGrowth:3},optimistic:{qGrowth:50,qPriceDrop:15,qPowerDrop:10,eligibilityGrowth:6}};
export const DEFAULTS={caseId:'B',preset:'reference',years:11,start:2031,add:0,maxQ:16,gpuKeep:100,demandGrowth:0,gpuGrowth:0,toolShare:0,eligible:0,qGrowth:0,qPriceDrop:0,qPowerDrop:0,eligibilityGrowth:0,qLogical:100,requiredLogical:100,qJobs:null,jobHours:null,qMw:16,qPrice:null,routerGain:0,routerMs:100,routerKw:0,router:'classical',cooling:'liquid',climate:'cold',coolant:25,resistance:null,tempLimit:null,util:null,electricity:null,building:null,network:null,maintenance:null,prefill:0,otherMw:0,qAnchorYear:2035,qAvailableFrom:2035,engineProfile:null,policyEvidence:null,reference:'unoptimizedGpu',specDecode:false,qcRouterOn:true,qcRouterStart:2030,qcRouterInitial:1,qcRouterAdd:1,qcRouterMax:4,qcRouterCoverage:25,qcAdoptionStart:100,qcAdoptionEndYear:2030,qcRouterGain:0,qcRouterMw:null,qcRouterPrice:null,qcRouterLatencyMs:null,coolingCapex:null};
export const COOLING={air:{name:SOURCE.cooling.airChillers.label,...SOURCE.cooling.airChillers.pue,max:SOURCE.cooling.airChillers.maxRackKw},evaporative:{name:SOURCE.cooling.airEvap.label,...SOURCE.cooling.airEvap.pue,max:SOURCE.cooling.airEvap.maxRackKw},liquid:{name:SOURCE.cooling.directLiquid.label,...SOURCE.cooling.directLiquid.pue,max:SOURCE.cooling.directLiquid.maxRackKw},immersion:{name:SOURCE.cooling.immersion.label,...SOURCE.cooling.immersion.pue,max:SOURCE.cooling.immersion.maxRackKw}};
const known=x=>Number.isFinite(x);
const value=x=>known(x)?x:0;
export function simulate(input){
 const p={...DEFAULTS,...input};
 if(!CASES[p.caseId])throw new Error('Select case A, B or C.');
 const c=CASES[p.caseId],routed=c[p.specDecode?'speculative':'routed'],cooling=COOLING[p.cooling],pue=cooling[p.climate],rack=SOURCE.gpuRack;
 let baselineInstalled=0,classicalInstalled=0,hybridInstalled=0,baseCapital=0,classicalCapital=0,hybridCapital=0,baseOperating=0,classicalOperating=0,hybridOperating=0;
 let cumulativeBase=0,cumulativeClassical=0,cumulativeHybrid=0;
 const cohorts=[],rows=[];
 let routerCount=0;
 for(let t=0;t<p.years;t++){
  const year=2030+t,scale=(1+p.demandGrowth/100)**t/(1+p.gpuGrowth/100)**t,vintage=year-p.qAnchorYear;
  const demand=routed.racks*scale,tools=demand*p.toolShare/100,required=demand+tools;
  const beforeRequired=c.baseline.racks*scale+tools;
  // Router rollout covers a share of the 2030 assignment workload per system.
  // Coverage and incremental advantage are scenario assumptions, not quantum benchmarks.
  const newRouter=p.qcRouterOn&&year>=p.qcRouterStart?Math.min(Math.max(0,Math.floor(year===Math.max(2030,p.qcRouterStart)?p.qcRouterInitial:p.qcRouterAdd)),Math.max(0,Math.floor(p.qcRouterMax)-routerCount)):0;
  routerCount+=newRouter;
  const routerActive=routerCount>0;
  const deploymentProgress=p.qcAdoptionEndYear>p.qcRouterStart?Math.max(0,Math.min(1,(year-p.qcRouterStart)/(p.qcAdoptionEndYear-p.qcRouterStart))):1;
  const plannedCoverage=(p.qcAdoptionStart+(100-p.qcAdoptionStart)*deploymentProgress)/100;
  const hardwareCoverage=Math.max(0,Math.min(1,routerCount*p.qcRouterCoverage/100/(1+p.demandGrowth/100)**t));
  const routingCoverage=p.qcRouterOn?Math.min(hardwareCoverage,plannedCoverage):0;
  const policyRacksAvoided=(c.baseline.racks-routed.racks)*scale*routingCoverage;
  const afterPolicyLlm=c.baseline.racks*scale-policyRacksAvoided;
  const routedLlm=afterPolicyLlm/(1+routingCoverage*p.qcRouterGain/100);
  const routingRequired=p.qcRouterOn?routedLlm+tools:required;
  const qcGpuRacksAvoided=p.qcRouterOn?beforeRequired-routingRequired:0;
  const newQ=year>=Math.max(p.start,p.qAvailableFrom)?Math.min(Math.max(0,Math.floor(p.add)),Math.max(0,Math.floor(p.maxQ)-cohorts.length)):0;
  for(let i=0;i<newQ;i++)cohorts.push({jobs:value(p.qJobs)*(1+p.qGrowth/100)**vintage,logical:p.qLogical*(1+p.qGrowth/100)**vintage,mw:known(p.qMw)?p.qMw*(1-p.qPowerDrop/100)**vintage:null,price:known(p.qPrice)?p.qPrice*1e6*(1-p.qPriceDrop/100)**vintage:null});
  const capable=cohorts.filter(q=>p.engineProfile?.feasible||q.logical>=p.requiredLogical);
  const toolSystems=p.router==='quantum'?capable.slice(1):capable;
  const qCapacity=toolSystems.reduce((sum,q)=>sum+q.jobs*value(p.jobHours)/rack.chips,0);
  const eligible=Math.min(1,(p.eligible+t*p.eligibilityGrowth)/100),offload=Math.min(tools*eligible,qCapacity);
  const gain=p.router==='quantum'&&capable.length?p.routerGain/100:0;
  const target=(routingRequired-offload)/(1+gain);
  const hybridRacks=target*p.gpuKeep/100;
  const capacityFraction=Math.min(1,hybridRacks*(1+gain)/Math.max(1e-12,routingRequired-offload));
  const qPower=cohorts.reduce((sum,q)=>sum+value(q.mw),0),routerMw=routerCount*value(p.qcRouterMw);
  const extraSupport=p.otherMw+(p.router==='quantum'?p.routerKw/1000:0);
  const facility=racks=>(racks*rack.kw/1000*(1+p.prefill/100)+p.otherMw)*pue;
  const unoptimizedMw=facility(beforeRequired),optimizedMw=facility(required);
  const hybridMw=(hybridRacks*rack.kw/1000*(1+p.prefill/100)+extraSupport+qPower+routerMw)*pue;
  const powerComplete=(!routerActive||known(p.qcRouterMw))&&cohorts.every(q=>known(q.mw));
  const basePurchased=Math.max(0,beforeRequired-baselineInstalled),classicalPurchased=Math.max(0,required-classicalInstalled),hybridPurchased=Math.max(0,hybridRacks-hybridInstalled);
  baselineInstalled=Math.max(baselineInstalled,beforeRequired);classicalInstalled=Math.max(classicalInstalled,required);hybridInstalled=Math.max(hybridInstalled,hybridRacks);
  const infrastructure=(racks,extraKw=0)=>racks*rack.usd*value(p.network)/100+(racks*rack.kw+extraKw)*(value(p.building)*1000+value(p.coolingCapex));
  const newCohorts=newQ?cohorts.slice(-newQ):[];
  const routerPurchase=newRouter*value(p.qcRouterPrice)*1e6;
  const baseInitial=basePurchased*rack.usd+infrastructure(basePurchased);
  const classicalInitial=classicalPurchased*rack.usd+infrastructure(classicalPurchased);
  const toolPurchase=newCohorts.reduce((sum,q)=>sum+value(q.price),0);
  const hybridInfra=infrastructure(hybridPurchased,newCohorts.reduce((sum,q)=>sum+value(q.mw)*1000,0)+newRouter*value(p.qcRouterMw)*1000);
  const hybridInitial=hybridPurchased*rack.usd+hybridInfra+toolPurchase+routerPurchase;
  baseCapital+=baseInitial;classicalCapital+=classicalInitial;hybridCapital+=hybridInitial;
  // Energy is only an estimate after the user provides an annual average-load factor.
  const averageFactor=known(p.util)?p.util/100:0;
  const baseGwh=unoptimizedMw*averageFactor*8.76,classicalGwh=optimizedMw*averageFactor*8.76;
  const rawHybridGwh=(hybridRacks*rack.kw/1000*(1+p.prefill/100)*averageFactor+extraSupport+qPower+routerMw)*pue*8.76;
  const energyFraction=p.policyEvidence?.energy_fraction??0,costFraction=p.policyEvidence?.electricity_cost_fraction??0;
  const hybridGwh=rawHybridGwh*(1-energyFraction);
  const baseRun=baseGwh*1e6*value(p.electricity)+baseCapital*value(p.maintenance)/100;
  const classicalRun=classicalGwh*1e6*value(p.electricity)+classicalCapital*value(p.maintenance)/100;
  const electricity=rawHybridGwh*(1-costFraction)*1e6*value(p.electricity),maintenance=hybridCapital*value(p.maintenance)/100;
  const hybridRun=electricity+maintenance;
  baseOperating+=baseRun;classicalOperating+=classicalRun;hybridOperating+=hybridRun;
  cumulativeBase+=baseInitial+baseRun;cumulativeClassical+=classicalInitial+classicalRun;cumulativeHybrid+=hybridInitial+hybridRun;
  const initialComplete=known(p.building)&&known(p.network)&&known(p.coolingCapex)&&(!routerActive||known(p.qcRouterPrice))&&cohorts.every(q=>known(q.price));
  const operatingComplete=known(p.electricity)&&known(p.util)&&known(p.maintenance)&&powerComplete;
  const costsComplete=initialComplete&&operatingComplete;
  const temperature=known(p.resistance)?p.coolant+5500*Math.min(1,(routingRequired-offload)/Math.max(1e-9,hybridRacks))*p.resistance:null;
  const thermalKnown=known(temperature)&&known(p.tempLimit),thermalOk=rack.kw<=cooling.max&&(!thermalKnown||temperature<=p.tempLimit);
  const fixedMw=(extraSupport+qPower+routerMw)*pue;
  const gridFraction=Math.max(0,Math.min(1,(500-fixedMw)/Math.max(1e-12,hybridMw-fixedMw)));
  const gpuExecutionFraction=Math.min(1,hybridRacks*(1+gain)*gridFraction/Math.max(1e-12,routingRequired-offload))*(thermalOk?1:0);
  // Use one common workload denominator; routing decisions are not extra execution.
  const gpuWorkFraction=(beforeRequired-offload)*gpuExecutionFraction/Math.max(1e-12,beforeRequired);
  const quantumToolWorkFraction=fixedMw<=500?offload/Math.max(1e-12,beforeRequired):0;
  const served=Math.min(1,gpuWorkFraction+quantumToolWorkFraction);
  const unservedFraction=Math.max(0,1-served);
  const evidenceOk=!p.policyEvidence||(p.policyEvidence.full_service_both&&p.policyEvidence.caps_held);
  const schedulerKnown=!routerActive||known(p.qcRouterLatencyMs),schedulingOk=evidenceOk&&(!routerActive||(schedulerKnown&&p.qcRouterLatencyMs<=100));
  const base=p.reference==='optimizedGpu'?{racks:required,mw:optimizedMw,gwh:classicalGwh,cumulative:cumulativeClassical,spend:classicalInitial+classicalRun,initial:classicalInitial,running:classicalRun,capital:classicalCapital,operating:classicalOperating}:{racks:beforeRequired,mw:unoptimizedMw,gwh:baseGwh,cumulative:cumulativeBase,spend:baseInitial+baseRun,initial:baseInitial,running:baseRun,capital:baseCapital,operating:baseOperating};
  const rackCapexSavings=(c.baseline.racks-routed.racks)*scale*rack.usd;
  rows.push({year,demand,tools,eligible,offload,qCapacity,toolsEligible:tools*eligible,newQ,qCount:cohorts.length,capable:capable.length,logical:cohorts.at(-1)?.logical??0,qPower,
   toolCapital:cohorts.reduce((sum,q)=>sum+value(q.price),0),toolCapitalKnown:cohorts.every(q=>known(q.price)),qcRouterActive:routerActive,qcRouterNew:newRouter,qcRouterCount:routerCount,qcRouterPowerMw:routerActive?(known(p.qcRouterMw)?routerMw:null):0,
   routingCoverage,plannedCoverage,hardwareCoverage,routingRequired,policyRacksAvoided,qcGpuRacksAvoided,qcExtraRacksAvoided:afterPolicyLlm-routedLlm,
   routingGrossMwAvoided:qcGpuRacksAvoided*rack.kw/1000*(1+p.prefill/100)*pue,routerFacilityMw:routerMw*pue,
   routerNetMwKnown:!routerActive||known(p.qcRouterMw),
   totalQuantumNew:newQ+newRouter,totalQuantumCount:cohorts.length+routerCount,
   baseRacks:base.racks,hybridRacks,hybridPhysicalRacks:Math.ceil(hybridRacks),gpuRacksRequired:target,gpuRacksReleased:base.racks-hybridRacks,gpuRacksOffloaded:offload,
   baseMw:base.mw,hybridMw,powerComplete,baseGwh:base.gwh,hybridGwh,energyKnown:known(p.util)&&powerComplete,
   baseSpend:base.spend,hybridSpend:hybridInitial+hybridRun,baseCumulative:base.cumulative,hybridCumulative:cumulativeHybrid,
   unoptimizedRacks:beforeRequired,unoptimizedMw,unoptimizedCumulative:cumulativeBase,optimizedRacks:required,optimizedMw,optimizedCumulative:cumulativeClassical,
   policySavings:cumulativeBase-cumulativeClassical,policyRackSavings:rackCapexSavings,qcIncrementalSavings:cumulativeClassical-cumulativeHybrid,savings:base.cumulative-cumulativeHybrid,
   baseInitial:base.initial,baseRunning:base.running,hybridInitial,hybridRunning:hybridRun,baseCapital:base.capital,baseOperating:base.operating,hybridCapital,hybridOperating,
   initialComplete,operatingComplete,costsComplete,temperature,thermalKnown,thermalOk,served,gpuWorkFraction,quantumToolWorkFraction,unservedFraction,baselineWork:beforeRequired,baseServed:Math.min(1,500/base.mw),schedulingOk,schedulerKnown,capacityFraction,
   policyEnergyDeltaGwh:rawHybridGwh-hybridGwh,policyCostDelta:rawHybridGwh*costFraction*1e6*value(p.electricity),
   costs:{gpu:hybridPurchased*rack.usd,quantum:toolPurchase,infrastructure:hybridInfra,electricity,maintenance,qc_router:routerPurchase},retired:Math.max(0,hybridInstalled-hybridRacks)});
 }
 const window=rows.slice(0,5),windowCost=window.at(-1).hybridCumulative,budgetComplete=window.every(r=>r.costsComplete),budgetOk=windowCost<=SOURCE.limits.budgetUsd;
 const feasible=budgetComplete&&budgetOk&&window.every(r=>r.served>=.999999&&r.schedulingOk&&r.powerComplete&&r.thermalKnown);
 return {rows,windowCost,budgetComplete,budgetOk,feasible,breakEven:budgetComplete?rows.find(r=>r.savings>0&&r.served>=.999999&&r.schedulingOk)?.year??null:null,
  source:SOURCE.source,attribution:'QC coverage and extra scheduling advantage are explicit assumptions. Source policy savings are not measured quantum scheduling advantages. Unspecified costs and QC power are omitted from numeric subtotals and visibly marked incomplete.'};
}
