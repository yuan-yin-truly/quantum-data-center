export const INFLATION_REFERENCE={years:[2023,2024,2025],rates:[4.1,2.9,2.6],average:3.2,baseYear:2030,label:'2023–2025 U.S. CPI-U annual-average changes, arithmetic mean',url:'https://www.bls.gov/regions/mid-atlantic/data/consumerpriceindexannualandsemiannual_table.htm'};
export function applyRunningInflation(rows,enabled,annualRate,baseYear=INFLATION_REFERENCE.baseYear){
 let baseOperating=0,hybridOperating=0,unoptimizedOperating=0;
 return rows.map(r=>{
  const factor=enabled?(1+annualRate/100)**(r.year-baseYear):1;
  const baseRunning=r.baseRunning*factor,hybridRunning=r.hybridRunning*factor;
  baseOperating+=baseRunning;hybridOperating+=hybridRunning;unoptimizedOperating+=r.unoptimizedRunning*factor;
  const baseCumulative=r.baseCapital+baseOperating,hybridCumulative=r.hybridCapital+hybridOperating;
  return {...r,unoptimizedRunning:r.unoptimizedRunning*factor,unoptimizedOperating,unoptimizedCumulative:r.unoptimizedCapital+unoptimizedOperating,policySavings:r.unoptimizedCapital+unoptimizedOperating-baseCumulative,inflationApplied:enabled,inflationFactor:factor,constantBaseRunning:r.baseRunning,constantHybridRunning:r.hybridRunning,baseRunning,hybridRunning,baseOperating,hybridOperating,baseCumulative,hybridCumulative,baseSpend:r.baseInitial+baseRunning,hybridSpend:r.hybridInitial+hybridRunning,savings:Math.abs(baseCumulative-hybridCumulative)<.01?0:baseCumulative-hybridCumulative,optimizedCapital:r.baseCapital,optimizedOperating:baseOperating,optimizedCumulative:baseCumulative,qcIncrementalSavings:baseCumulative-hybridCumulative,costs:{...r.costs,electricity:r.costs.electricity*factor,maintenance:r.costs.maintenance*factor}};
 });
}
