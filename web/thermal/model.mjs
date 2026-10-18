// Scenario exploration, not a calibrated hardware forecast or official scorer.
export const CASES = {A:{name:'Prompters',users:4e9,racks:1157.4074074074074},B:{name:'Agent developers',users:50e6,racks:360.84284737993465},C:{name:'Knowledge workers',users:400e6,racks:397.7774796983645}};
export const PRESETS = {conservative:{qGrowth:10,qPriceDrop:3,qPowerDrop:2,eligibilityGrowth:1},moderate:{qGrowth:25,qPriceDrop:8,qPowerDrop:5,eligibilityGrowth:3},optimistic:{qGrowth:50,qPriceDrop:15,qPowerDrop:10,eligibilityGrowth:6}};
export const DEFAULTS = {caseId:'B',preset:'moderate',years:10,start:2031,add:2,maxQ:16,gpuKeep:100,demandGrowth:3,gpuGrowth:5,toolShare:15,eligible:20,qGrowth:25,qPriceDrop:8,qPowerDrop:5,eligibilityGrowth:3,qLogical:100,requiredLogical:100,qJobs:100,jobHours:1,qMw:16,qPrice:100,routerGain:0,routerMs:100,routerKw:10,router:'classical',cooling:'liquid',climate:'cold',coolant:25,resistance:0.009,tempLimit:85,util:65,electricity:0.08,building:2,network:10,maintenance:2,prefill:10,otherMw:5,qAnchorYear:2030,qAvailableFrom:2030,engineProfile:null,policyEvidence:null};
export const COOLING = {air:{name:'Air + chillers',cold:1.16,desert:1.54,max:50,capex:100},liquid:{name:'Direct liquid',cold:1.07,desert:1.14,max:1500,capex:250},immersion:{name:'Immersion',cold:1.06,desert:1.10,max:2000,capex:400}};
export function simulate(p) {
 const c=CASES[p.caseId], cooling=COOLING[p.cooling], pue=cooling[p.climate];
 const cohorts=[]; let baseInstalled=0,hybridInstalled=0,baseCapital=0,hybridCapital=0,bc=0,hc=0;
 const rows=[];
 for(let t=0;t<p.years;t++) {
  const year=2030+t, vintage=year-p.qAnchorYear, demand=c.racks*(1+p.demandGrowth/100)**t/(1+p.gpuGrowth/100)**t;
  // Extra scientific tool work is additional to LLM demand, never offloaded tokens.
  const tools=demand*p.toolShare/100, required=demand+tools;
  const eligible=Math.min(1,(p.eligible+t*p.eligibilityGrowth)/100);
  const newQ=year>=Math.max(p.start,p.qAvailableFrom)?Math.min(p.add,Math.max(0,p.maxQ-cohorts.length)):0;
  for(let i=0;i<newQ;i++) cohorts.push({logical:p.qLogical*(1+p.qGrowth/100)**vintage,jobs:p.qJobs*(1+p.qGrowth/100)**vintage,mw:p.qMw*(1-p.qPowerDrop/100)**vintage,price:p.qPrice*1e6*(1-p.qPriceDrop/100)**vintage});
  const capable=cohorts.filter(q=>p.engineProfile?.feasible || q.logical>=p.requiredLogical);
  // Jobs/hour and GPU-hours/job are for ONE selected scientific task and matched accuracy.
  const toolSystems=p.router==='quantum'?capable.slice(1):capable;
  const qCapacity=toolSystems.reduce((s,q)=>s+q.jobs*p.jobHours/144,0);
  const offload=Math.min(tools*eligible,qCapacity);
  const gain=p.router==='quantum'&&capable.length? p.routerGain/100:0;
  const routerAvailable=p.router==='classical'||capable.length>0;
  const target=Math.ceil((required-offload)/(1+gain));
  const baseRacks=Math.ceil(required), hybridRacks=Math.max(0,Math.ceil(target*p.gpuKeep/100));
  const gpuCapacity=hybridRacks*(1+gain), gpuNeed=required-offload;
  const capacityFraction=gpuNeed>0?Math.min(1,gpuCapacity/gpuNeed):1;
  const qPower=cohorts.reduce((s,q)=>s+q.mw,0);
  const routingPower=p.router==='quantum'?p.routerKw/1000:0;
  const infrastructure=p.prefill/100;
  const baseIt=baseRacks*.792*(1+infrastructure)+p.otherMw;
  const hybridIt=hybridRacks*.792*(1+infrastructure)+p.otherMw;
  const baseMw=baseIt*pue,hybridMw=(hybridIt+qPower+routingPower)*pue;
  // Full fridge wall draw is already in qPower. PUE adds only external facility overhead.
  const baseAvg=(baseRacks*.792*(.3+.7*p.util/100)*(1+infrastructure)+p.otherMw)*pue;
  const rawHybridAvg=(hybridRacks*.792*(.3+.7*p.util/100)*(1+infrastructure)+p.otherMw+qPower+routingPower)*pue;
  // Only electricity and energy are extrapolated. Never infer peak power or capacity savings.
  const linked=p.policyEvidence;
  const energyFraction=linked?.energy_fraction??0, costFraction=linked?.electricity_cost_fraction??0;
  const hybridAvg=rawHybridAvg*(1-energyFraction);
  const purchasedBase=Math.max(0,baseRacks-baseInstalled), purchasedHybrid=Math.max(0,hybridRacks-hybridInstalled);
  baseInstalled=Math.max(baseInstalled,baseRacks); hybridInstalled=Math.max(hybridInstalled,hybridRacks);
  const bHardware=purchasedBase*23.8e6, hHardware=purchasedHybrid*23.8e6;
  const qPurchase=cohorts.slice(cohorts.length-newQ).reduce((s,q)=>s+q.price,0)*(newQ?1:0);
  const bInfra=bHardware*p.network/100+purchasedBase*792*(cooling.capex+p.building*1000);
  const hInfra=hHardware*p.network/100+(purchasedHybrid*792+cohorts.slice(cohorts.length-newQ).reduce((s,q)=>s+q.mw*1000,0)*(newQ?1:0))*(cooling.capex+p.building*1000);
  baseCapital+=bHardware+bInfra; hybridCapital+=hHardware+hInfra+qPurchase;
  const bEnergy=baseAvg*1000*8760*p.electricity,hEnergy=rawHybridAvg*(1-costFraction)*1000*8760*p.electricity;
  const baseSpend=bHardware+bInfra+bEnergy+baseCapital*p.maintenance/100;
  const hybridSpend=hHardware+hInfra+qPurchase+hEnergy+hybridCapital*p.maintenance/100;
  bc+=baseSpend; hc+=hybridSpend;
  const chipWatts=5500*Math.min(1,gpuNeed/Math.max(1,hybridRacks));
  const temperature=p.coolant+chipWatts*p.resistance;
  const thermalOk=temperature<=p.tempLimit&&792<=cooling.max;
  const baselineThermal=p.coolant+5500*p.resistance<=p.tempLimit&&792<=cooling.max;
  const fixedMw=(p.otherMw+qPower+routingPower)*pue;
  const gridFraction=Math.max(0,Math.min(1,(500-fixedMw)/Math.max(1e-9,hybridMw-fixedMw)));
  const served=Math.min(capacityFraction,gridFraction)*(thermalOk?1:0);
  const baseServed=Math.min(1,500/baseMw)*(baselineThermal?1:0);
  const evidenceOk=!p.policyEvidence||(p.policyEvidence.full_service_both&&p.policyEvidence.caps_held);
  const schedulingOk=evidenceOk&&(p.router==='classical'||(routerAvailable&&p.routerMs<=100));
  rows.push({year,demand,tools,eligible,offload,qCapacity,newQ,qCount:cohorts.length,capable:capable.length,logical:cohorts.at(-1)?.logical??0,baseRacks,hybridRacks,qPower,baseMw,hybridMw,baseGwh:baseAvg*8.76,hybridGwh:hybridAvg*8.76,policyEnergyDeltaGwh:(rawHybridAvg-hybridAvg)*8.76,policyCostDelta:(rawHybridAvg*costFraction)*1000*8760*p.electricity,baseSpend,hybridSpend,baseCumulative:bc,hybridCumulative:hc,savings:bc-hc,annualSavings:baseSpend-hybridSpend,temperature,thermalOk,served,baseServed,schedulingOk,capacityFraction,costs:{gpu:hHardware,quantum:qPurchase,infrastructure:hInfra,electricity:hEnergy,maintenance:hybridCapital*p.maintenance/100},retired:Math.max(0,hybridInstalled-hybridRacks)});
 }
 const window=rows.slice(0,5), budgetOk=window.at(-1).hybridCumulative<=30e9;
 return {rows,budgetOk,windowCost:window.at(-1).hybridCumulative,feasible:budgetOk&&window.every(r=>r.served>=.999999&&r.schedulingOk),breakEven:rows.find((r,i)=>budgetOk&&r.qCount>0&&r.savings>0&&rows.slice(0,i+1).every(a=>a.served>=.999999&&a.baseServed>=.999999&&a.schedulingOk))?.year??null};
}
