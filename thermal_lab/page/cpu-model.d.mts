export type Parameters = Record<string, string | number | boolean | null> & {caseId:string;gpuEnergyReduction:number;qInitial:number};
export const CPU_DEFAULTS: Parameters;
export const START_YEAR:number, END_YEAR:number;
export interface EnergyRow {year:number;baseGwh:number;hybridGwh:number;energySavingPercent:number;baseRunning:number;hybridRunning:number;hybridMw:number;energyOk:boolean|null;runningCostOk:boolean|null;}
export interface EnergyForecast {rows:EnergyRow[];hybridSuccess:boolean;windowCost:number;}
export function simulateCPU(parameters:Parameters):EnergyForecast;
