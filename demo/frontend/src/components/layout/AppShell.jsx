import { useEffect } from 'react';
import { Routes, Route } from 'react-router-dom';
import { useApp } from '../../context/AppContext';
import { navItems } from '../../nav-items';
import TopBar from './TopBar';
import SideNav from './SideNav';
import MockBanner from './MockBanner';

const AppShell = () => {
  const { chat, batch } = useApp();

  useEffect(() => {
    const handler = (e) => { e.preventDefault(); e.returnValue = ''; };
    if (chat.running || batch.running) window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [chat.running, batch.running]);

  return (
    <div className="h-screen flex flex-col bg-gray-100">
      <TopBar />
      <div className="flex flex-1 min-h-0">
        <SideNav />
        <main className="flex-1 min-w-0 flex flex-col">
          <MockBanner />
          <div className="flex-1 min-h-0 overflow-hidden">
            <Routes>
              {navItems.map(({ to, page }) => <Route key={to} path={to} element={page} />)}
            </Routes>
          </div>
        </main>
      </div>
    </div>
  );
};

export default AppShell;
