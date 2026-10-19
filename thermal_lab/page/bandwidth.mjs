import SOURCE from './fleet-reference.mjs';
export function perGpuCapacity(kind,tbps,memoryBytes=SOURCE.gpu.memBytes){
 const point=SOURCE.perGpuPoints[kind==='chat'?'chat':'agent'];
 const kv=kind==='chat'?SOURCE.decodeCalibration.chatKvBytes:SOURCE.decodeCalibration.agentKvBytes;
 const overhead=kind==='chat'?SOURCE.decodeCalibration.chatOverheadS:SOURCE.decodeCalibration.agentOverheadS;
 const effective=tbps*1e12*(SOURCE.gpuEffectiveReadBytesPerS/SOURCE.gpu.peakBytesPerS);
 const bandwidthUsers=Math.max(0,(1/point.tokPerUserS-overhead)*effective/kv);
 const memoryUsers=Math.max(0,(memoryBytes-SOURCE.decodeCalibration.reservedBytes)/kv);
 const users=Math.min(bandwidthUsers,memoryUsers);
 return {users,tokensPerSecond:users*point.tokPerUserS,bound:bandwidthUsers<=memoryUsers?'bandwidth':'memory'};
}
export function workloadCapacity(p,row){
 const c=SOURCE.cases[p.caseId],work=SOURCE.caseWorkloads[p.caseId];
 const totalDailyTasks=c.users*Object.values(work.perDay).reduce((a,b)=>a+b,0);
 return {users:c.users,peakOutTokensPerSecond:c.users*work.peakOutPerUser,chatPromptsDay:c.users*work.perDay.chat,interactiveTasksDay:c.users*work.perDay.interactive,backgroundTasksDay:c.users*work.perDay.background,totalDailyTasks,scienceJobsDay:row.jobsDay,scienceQpuJobsDay:row.qpuJobsDay,scienceGpuJobsDay:row.gpuJobsDay,modeledCoverage:row.served};
}
