import {useEffect,useState} from 'react';
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription,DialogFooter} from '@/components/ui/dialog';
import {Button} from '@/components/ui/button';
import {FolderOpen} from 'lucide-react';
import {useApp} from '../../context/AppContext';
import {api} from '../../lib/api';
export default function DirectoryDialog({open,onOpenChange}) {
 const {service,loadKb,busy}=useApp();
 const [path,setPath]=useState(''); const [listing,setListing]=useState(null); const [error,setError]=useState(''); const [loading,setLoading]=useState(false);
 async function browse(target) {setError('');setLoading(true);try {const d=await api(`/directories?path=${encodeURIComponent(target||service.defaultKnowledgeBase||'')}`);setListing(d);setPath(d.path);}catch(e){setError(e.message);}finally{setLoading(false);}}
 useEffect(()=>{if(open) browse(service.defaultKnowledgeBase);},[open]);
 async function load(){if(busy)return;setLoading(true);if(await loadKb(path))onOpenChange(false);setLoading(false);}
 return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="sm:max-w-2xl"><DialogHeader><DialogTitle>Select a local knowledge base</DialogTitle><DialogDescription>Browse directories on this computer. Select a prepared M4 workspace containing m3_data, runtime_chroma and model_cache. Files stay on this computer.</DialogDescription></DialogHeader>
 <div className="flex gap-2"><input aria-label="Directory path" className="flex-1 min-w-0 border rounded px-3 py-2 text-sm" value={path} onChange={e=>setPath(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')browse(path);}}/><Button variant="outline" disabled={loading} onClick={()=>browse(path)}>Browse</Button></div>
 <div className="flex gap-2"><Button size="sm" variant="outline" disabled={loading} onClick={()=>browse(listing?.parent)}>Parent folder</Button><Button size="sm" variant="outline" disabled={loading} onClick={()=>browse(service.defaultKnowledgeBase)}>Project workspace</Button></div>
 <div className="max-h-56 overflow-auto border rounded divide-y">{listing?.directories.map(d=><button key={d.path} className="flex items-center gap-2 px-3 py-2 text-sm w-full text-left hover:bg-gray-50" onClick={()=>browse(d.path)}><FolderOpen className="w-4 h-4"/>{d.name}</button>)}{listing?.directories.length===0&&<p className="p-4 text-sm text-gray-500">No visible subdirectories. You can select this folder.</p>}</div>
 {error&&<p role="alert" className="text-red-600 text-sm">{error}</p>}
 <DialogFooter><Button variant="outline" onClick={()=>onOpenChange(false)}>Cancel</Button><Button disabled={!path||loading||busy} onClick={load}>Load selected folder</Button></DialogFooter>
 </DialogContent></Dialog>;
}
