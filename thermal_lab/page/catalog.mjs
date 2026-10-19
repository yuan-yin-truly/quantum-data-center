import SOURCE from './fleet-reference.mjs';
export {SOURCE};
export const CASES=Object.fromEntries(Object.entries(SOURCE.cases).map(([id,c])=>[id,{...c,racks:c.routed.racks}]));
export const COOLING={air:{name:SOURCE.cooling.airChillers.label,...SOURCE.cooling.airChillers.pue,max:SOURCE.cooling.airChillers.maxRackKw},evaporative:{name:SOURCE.cooling.airEvap.label,...SOURCE.cooling.airEvap.pue,max:SOURCE.cooling.airEvap.maxRackKw},liquid:{name:SOURCE.cooling.directLiquid.label,...SOURCE.cooling.directLiquid.pue,max:SOURCE.cooling.directLiquid.maxRackKw},immersion:{name:SOURCE.cooling.immersion.label,...SOURCE.cooling.immersion.pue,max:SOURCE.cooling.immersion.maxRackKw}};
export function policyVariant(c,p){return c[p.policyBasis==='website'?(p.specDecode?'siteSpeculative':'siteRouted'):(p.specDecode?'speculative':'routed')];}
