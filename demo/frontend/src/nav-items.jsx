import {Database,MessageSquare,ListChecks} from 'lucide-react';
import KnowledgeBasePage from './pages/KnowledgeBasePage';
import ChatPage from './pages/ChatPage';
import BatchPage from './pages/BatchPage';
export const navItems=[
 {title:'Knowledge base',to:'/',icon:<Database className="h-4 w-4 shrink-0"/>,page:<KnowledgeBasePage/>},
 {title:'Chat',to:'/chat',icon:<MessageSquare className="h-4 w-4 shrink-0"/>,page:<ChatPage/>},
 {title:'Batch questions',to:'/batch',icon:<ListChecks className="h-4 w-4 shrink-0"/>,page:<BatchPage/>},
];
