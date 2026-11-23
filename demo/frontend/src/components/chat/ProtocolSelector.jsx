import {useState} from 'react';
import {useApp} from '../../context/AppContext';
import {Button} from '@/components/ui/button';
const choices=[['G0','Basic answer','Prompt-only citations; no hard citation check.'],['G1','Citation validation','Structured output with citation and exact-quote validation.'],['G2','Review and repair','G1 plus automatic review and at most one repair.']];
export default function ProtocolSelector(){
 const {protocol,setProtocol,busy,service}=useApp();const [open,setOpen]=useState(false);
 return <div className="border-b bg-white px-6 py-3"><div className="flex flex-wrap items-center gap-2"><span className="text-sm text-gray-500 mr-2">Protocol</span>{choices.map(([p,name,desc])=><button key={p} title={desc} disabled={busy} onClick={()=>setProtocol(p)} className={`px-3 py-2 rounded text-sm disabled:opacity-60 ${p===protocol?'bg-blue-700 text-white':'border hover:bg-gray-50'}`}>{p} · {name}</button>)}<Button variant="ghost" className="ml-auto" onClick={()=>setOpen(!open)}>{open?'Hide settings':'Run settings'}</Button></div>
 <p className="text-xs text-gray-500 mt-2">{choices.find(c=>c[0]===protocol)[2]}</p>
 {open&&<div className="text-sm text-gray-600 mt-4 grid sm:grid-cols-2 gap-3 border-t pt-4"><p>Model: {service.model||'CS5351/DeepSeek-V4-Flash'}</p><p>Connection: school gateway</p><p>Retrieval: C / Hybrid / k=5 / candidates=30 / RRF=60</p><p>M4 evidence packing: 1024 token</p><p>Per-call application limit: 8192 token</p><p>Safety margin: 512 token · Network retries: 0</p><p className="sm:col-span-2 text-xs">The application budget is not a confirmed gateway context limit. Credentials are read only by the local backend. Monetary cost is unknown.</p></div>}
 </div>;
}
