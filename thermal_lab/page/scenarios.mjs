import {DEFAULTS,CASES,simulate} from './model.mjs';
import {SOURCED_PROPOSAL} from './sources.mjs';
export const SCENARIOS={
 reference:{label:'Source reference · classical policies',gain:0,on:false,description:'Source-policy comparator with speculative decoding. No quantum routing advantage is assumed.'},
 conservative:{label:'Conservative QC scenario',gain:0,on:true,description:'QC rollout reaches the source-policy opportunity, with zero extra quantum throughput advantage.'},
 moderate:{label:'Moderate QC scenario',gain:5,on:true,description:'Adds 5% assumed extra throughput on QC-covered assignments.'},
 optimistic:{label:'Optimistic QC scenario',gain:10,on:true,description:'Adds 10% assumed extra throughput on QC-covered assignments.'}
};
// Search a small, visible design space, retaining a gradual one-per-year rollout.
// Choose either the least-cost feasible initial fleet or the smallest initial
// fleet for gradual rollout, passing the entered five-year
// capacity/power/cost/temperature/timing screens. No physical accuracy is implied.
export function buildCaseScenario(caseId='B',preset='optimistic',rolloutStrategy='staged'){
 if(!CASES[caseId]||!SCENARIOS[preset])throw new Error('Unknown case or scenario');
 const choice=SCENARIOS[preset];
 const base={...DEFAULTS,...SOURCED_PROPOSAL,caseId,policyBasis:'website',preset,rolloutStrategy,specDecode:true,qcRouterOn:choice.on,qcRouterGain:choice.gain,policyEvidence:null,engineProfile:null};
 if(!choice.on)return {...base,qcRouterInitial:0,qcRouterAdd:0,qcRouterMax:0};
 const candidates=[1,2,3,4].map(n=>({...base,qcRouterInitial:n}));
 const feasible=candidates.filter(p=>simulate(p).feasible);
 if(rolloutStrategy==='staged'){
  // Search the smallest initial fleet and first-year deployment share that
  // passes the supplied limits while leaving adoption work for every later year.
  for(const count of [1,2,3,4])for(let adoption=5;adoption<100;adoption+=1){
   if(adoption>count*base.qcRouterCoverage)continue;
   const candidate={...base,qcRouterInitial:count,qcAdoptionStart:adoption,qcAdoptionEndYear:2040};
   if(simulate(candidate).feasible)return candidate;
  }
  return {...candidates.at(-1),qcAdoptionStart:100,qcAdoptionEndYear:2040};
 }
 return feasible.sort((a,b)=>simulate(a).windowCost-simulate(b).windowCost)[0]??candidates.at(-1);
}
const ALWAYS=['years','gpuKeep','demandGrowth','gpuGrowth','add','maxQ','coolant','resistance','tempLimit','util','electricity','building','network','maintenance','prefill','otherMw','coolingCapex'];
const ROUTING=['qcRouterStart','qcRouterInitial','qcRouterAdd','qcRouterMax','qcRouterCoverage','qcAdoptionStart','qcAdoptionEndYear','qcRouterGain','qcRouterMw','qcRouterPrice','qcRouterLatencyMs'];
const SCIENCE=['start','qAvailableFrom','qAnchorYear','toolShare','eligible','eligibilityGrowth','qJobs','jobHours','qLogical','requiredLogical','qGrowth','qMw','qPowerDrop','qPrice','qPriceDrop'];
export function missingInputs(p){
 const fields=[...ALWAYS,...(p.qcRouterOn?ROUTING:[]),...(p.add>0?SCIENCE:[]),...(p.router==='quantum'?['routerGain','routerMs','routerKw']:[])];
 return [...new Set(fields)].filter(id=>!Number.isFinite(p[id]));
}
