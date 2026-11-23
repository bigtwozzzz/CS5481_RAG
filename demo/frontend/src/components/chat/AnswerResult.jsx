import {useState} from 'react';
import AnswerStatusBadge from './AnswerStatusBadge';
import {Sheet,SheetContent,SheetHeader,SheetTitle,SheetDescription} from '@/components/ui/sheet';
import {Button} from '@/components/ui/button';
import {seconds,count} from '../../lib/api';
const safeUrl=url=>{try{const u=new URL(url);return ['https:','http:'].includes(u.protocol)?u.href:null;}catch{return null;}};
export default function AnswerResult({result}){
 const [source,setSource]=useState(null);const [copied,setCopied]=useState(false);const d=result.runDetails;
 const sources=result.sources||[];
 function choose(id){setSource(id||'all');setTimeout(()=>document.getElementById(`source-${id}`)?.scrollIntoView({block:'start'}),100);}
 const segments=(result.content||'').split(/(\[S\d+\])/g);
 async function copy(){try{await navigator.clipboard.writeText(result.content||'');setCopied(true);setTimeout(()=>setCopied(false),1500);}catch{setCopied(false);}}
 return <div className="min-w-0"><AnswerStatusBadge result={result}/>
 {result.error&&<p role="alert" className="text-red-700 bg-red-50 rounded p-3 mb-3">{result.errorCode&&`${result.errorCode}: `}{result.error}</p>}
 {result.content&&<div className="whitespace-pre-wrap break-words leading-relaxed text-sm">{segments.map((part,i)=>/^\[S\d+\]$/.test(part)?<button key={i} className="text-blue-700 underline underline-offset-2 font-medium" onClick={()=>choose(part.slice(1,-1))}>{part}</button>:<span key={i}>{part}</span>)}</div>}
 {result.missingFields?.length>0&&<div className="mt-3 text-sm text-gray-600"><p className="font-medium">Missing information</p><ul className="list-disc pl-5">{result.missingFields.map((s,i)=><li key={i}>{typeof s==='string'?s:JSON.stringify(s)}</li>)}</ul></div>}
 <div className="flex flex-wrap gap-2 mt-4">{sources.length>0&&<Button size="sm" variant="outline" onClick={()=>choose()}>View sources ({sources.length})</Button>}{result.content&&<Button size="sm" variant="ghost" onClick={copy}>{copied?'Copied':'Copy answer'}</Button>}</div>
 {d&&<details className="mt-4 border-t pt-3"><summary className="cursor-pointer text-sm text-gray-500">Run details</summary><dl className="grid sm:grid-cols-2 gap-x-6 gap-y-3 text-sm mt-4">{[['Protocol',d.protocol],['Model',d.model],['Run status',d.runStatus],['Output check',d.outputCheck],['Automatic review',d.autoReview],['End-to-end time',seconds(d.durationMs)],['API calls',count(d.apiCalls)],['Input token',count(d.inputTokens)],['Output token',count(d.outputTokens)],['Repairs',d.repairCount],['Cost',d.cost==null?'Unknown':d.cost]].map(([k,v])=><div key={k}><dt className="text-xs text-gray-500">{k}</dt><dd className="break-words mt-1">{v??'Unknown'}</dd></div>)}</dl><p className="text-xs text-gray-500 mt-4">Completion, citation validation and automatic review are not human confirmation of correctness.</p></details>}
 <Sheet open={source!==null} onOpenChange={v=>{if(!v)setSource(null);}}><SheetContent className="w-full sm:max-w-xl overflow-y-auto"><SheetHeader><SheetTitle>Source evidence</SheetTitle><SheetDescription>Original passages from the selected knowledge base.</SheetDescription></SheetHeader>
 {sources.length===0&&<p className="mt-6 text-sm">No structured source is available. G0 does not perform hard citation validation.</p>}
 {sources.map(s=><section id={`source-${s.id}`} key={s.id} className={`mt-6 border-b pb-6 ${source===s.id?'bg-blue-50 p-3 rounded':''}`}><span className="text-blue-700 font-semibold">{s.id}</span><h3 className="font-semibold mt-2">{s.title}</h3><p className="text-xs text-gray-500 mt-2">{s.site} · {s.date||'Date not provided'}</p>{safeUrl(s.url)&&<a className="inline-block mt-2 text-sm text-blue-700 underline" href={safeUrl(s.url)} target="_blank" rel="noopener noreferrer">Open original article</a>}<p className="text-xs text-gray-500 mt-4 mb-2">EVIDENCE PASSAGE</p><p className="text-sm whitespace-pre-wrap leading-relaxed">{s.snippet}</p></section>)}
 </SheetContent></Sheet></div>;
}
