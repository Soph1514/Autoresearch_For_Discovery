export type Status='running'|'pausing'|'paused'|'stopping'|'stopped'|'completed'|'failed';
export interface ProblemInput {text:string;attachments:File[];initialResults:string;resultFiles:File[];mode:'demo'}
export interface Run {id:string;title:string;status:Status;startedAt:string;endedAt?:string}
export interface Idea {id:string;title:string;description:string;parents:string[];operation:'seed'|'exploration'|'mutation'|'merge'|'merge_mutation';mutation?:string;inactive:boolean;c:number}
export interface Experiment {id:string;ideaId:string;status:'running'|'completed'|'failed'|'cancelled';valid:boolean|null;metrics:Record<string,number>;feedback:string}
export interface Elite {ideaId:string;experimentId:string;niche:string;current:boolean}
export interface Log {id:string;timestamp:string;category:string;message:string;ideaId?:string}
export type Update={type:'idea_created';payload:Idea}|{type:'experiment_updated';payload:Experiment}|{type:'elite_changed';payload:Elite}|{type:'log_added';payload:Log}|{type:'run_status_changed';payload:{status:Status;endedAt?:string}};
export type ResearchEvent=Update&{schemaVersion:1;runId:string;eventId:string;sequence:number;timestamp:string};
export interface Snapshot {run:Run;ideas:Idea[];experiments:Experiment[];elites:Elite[];logs:Log[];sequence:number}
export interface ResearchClient {startRun(input:ProblemInput):Promise<Run>;getSnapshot(id:string):Promise<Snapshot>;subscribe(id:string,after:number,listener:(e:ResearchEvent)=>void):()=>void;pauseRun(id:string):Promise<void>;resumeRun(id:string):Promise<void>;stopRun(id:string):Promise<void>}
export function applyEvent(s:Snapshot,e:ResearchEvent):Snapshot{
 if(e.runId!==s.run.id||e.sequence<=s.sequence)return s;
 if(e.sequence!==s.sequence+1)throw Error('Event sequence gap');
 const n={...s,sequence:e.sequence};switch(e.type){
 case 'idea_created':return {...n,ideas:[...s.ideas.filter(i=>i.id!==e.payload.id),e.payload]};
 case 'experiment_updated':return {...n,experiments:[...s.experiments.filter(i=>i.id!==e.payload.id),e.payload]};
 case 'elite_changed':return {...n,elites:[...s.elites.filter(i=>!(i.ideaId===e.payload.ideaId&&i.niche===e.payload.niche)),e.payload]};
 case 'log_added':return {...n,logs:[...s.logs,e.payload]};
 case 'run_status_changed':return {...n,run:{...s.run,...e.payload}};
 }}
