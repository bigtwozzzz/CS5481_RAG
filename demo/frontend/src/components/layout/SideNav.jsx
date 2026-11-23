import { NavLink } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { navItems } from '../../nav-items';
export default function SideNav() {
 const {kb,chat,batch}=useApp();
 return <aside className="w-[210px] max-sm:w-[150px] shrink-0 bg-white border-r flex flex-col">
 <nav className="p-3 space-y-1">{navItems.map(item=><NavLink key={item.to} to={item.to} end={item.to==='/'} className={({isActive})=>`flex items-center gap-2 px-3 py-3 rounded-md text-sm ${isActive?'bg-blue-700 text-white':'text-gray-700 hover:bg-gray-100'}`}>{item.icon}<span>{item.title}</span>{((item.to==='/chat'&&chat.running)||(item.to==='/batch'&&batch.running))&&<span className="ml-auto text-xs">Running</span>}</NavLink>)}</nav>
 <div className="mt-auto p-4 border-t text-sm"><p className="text-xs text-gray-500 mb-2">CURRENT KNOWLEDGE BASE</p><p className="font-medium break-words">{kb.info?.name||'Not selected'}</p>{kb.info&&<p className="text-xs text-green-700 mt-1">Loaded · {Number(kb.info.docCount).toLocaleString('en')} documents</p>}</div>
 </aside>;
}
