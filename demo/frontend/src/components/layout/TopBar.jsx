import { useApp } from '../../context/AppContext';
export default function TopBar() {
 const {service} = useApp();
 return <header className="h-[60px] shrink-0 bg-white border-b flex items-center justify-between px-6">
  <div className="flex items-baseline gap-3"><span className="text-lg font-bold text-gray-900">News RAG</span><span className="text-sm text-gray-500 hidden sm:block">Local knowledge base</span></div>
  <span className={`text-sm ${service.connected?'text-green-700':'text-red-600'}`}>{service.connected?'Backend connected':'Backend offline'}</span>
 </header>;
}
