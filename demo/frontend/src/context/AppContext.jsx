import { createContext, useContext, useState, useRef, useEffect, useCallback } from 'react';
import { api, activeTask } from '../lib/api';
const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);
export const AppProvider = ({children}) => {
  const [service, setService] = useState({connected: false, kb: {status: 'unloaded', info: null}});
  const [protocol, setProtocol] = useState('G1');
  const [error, setError] = useState('');
  const [messages, setMessages] = useState([]);
  const [batch, setBatch] = useState({step: 1, questions: [], fileName: '', importError: '', task: null});
  const [current, setCurrent] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const refresh = useCallback(async () => {
    try { const s = await api('/status'); setService(s); }
    catch { setService(s => ({...s, connected: false})); }
  }, []);
  useEffect(() => { refresh(); const id = setInterval(refresh, 2000); return () => clearInterval(id); }, [refresh]);
  useEffect(() => {
    if (!current) return;
    let alive = true, timer;
    const poll = async () => {
      try {
        const t = await api(`/tasks/${current.id}`);
        if (!alive) return;
        setError('');
        if (current.type === 'chat') setMessages(ms => ms.map(m => m.id === current.messageId ? {...m, task: t, result: t.results[0]} : m));
        else setBatch(b => ({...b, task: t}));
        if (activeTask(t)) timer = setTimeout(poll, 700);
        else { setCurrent(null); refresh(); }
      } catch (e) {
        if (!alive) return;
        setError(`${e.message} Retrying status checks; no model request will be resent.`);
        timer = setTimeout(poll, 2500);
      }
    };
    poll(); return () => { alive = false; clearTimeout(timer); };
  }, [current, refresh]);
  const start = async (type, questions) => {
    if (submittingRef.current || current) return;
    submittingRef.current = true; setSubmitting(true); setError('');
    try {
      const t = await api('/tasks', {questions, protocol, knowledgeBaseId: service.kb.info?.id});
      if (type === 'chat') {
        const id = `answer-${t.id}`;
        setMessages(ms => [...ms, {id: `user-${t.id}`, role: 'user', content: questions[0].question},
          {id, role: 'assistant', task: t, result: t.results[0]}]);
        setCurrent({id: t.id, type, messageId: id});
      } else { setBatch(b => ({...b, step: 3, task: t})); setCurrent({id: t.id, type}); }
      refresh();
      return true;
    } catch (e) { setError(e.message); return false; }
    finally { submittingRef.current = false; setSubmitting(false); }
  };
  const stop = async () => {
    if (!current) return;
    try {
      const t = await api(`/tasks/${current.id}/stop`, {});
      if (current.type === 'batch') setBatch(b => ({...b, task: t}));
      else setMessages(ms => ms.map(m => m.id === current.messageId ? {...m, task: t} : m));
    } catch (e) { setError(e.message); }
  };
  const loadKb = async path => {
    setError('');
    try { await api('/knowledge-base/load', {path}); await refresh(); return true; }
    catch (e) { setError(e.message); return false; }
  };
  const unloadKb = async () => { try { await api('/knowledge-base/unload', {}); refresh(); } catch(e) {setError(e.message);} };
  const importFile = async file => {
    setBatch(b => ({...b, importError: ''}));
    try {
      if (!file || file.size > 1_000_000) throw new Error('Select a JSONL file smaller than 1 MB.');
      const data = await api('/questions/validate', {text: await file.text()});
      setBatch({step: 2, fileName: file.name, questions: data.questions, task: null, importError: ''});
    } catch (e) { setBatch(b => ({...b, importError: e.message})); }
  };
  const busy = submitting || Boolean(current) || service.busy;
  return <AppContext.Provider value={{service, kb: service.kb, protocol, setProtocol, error, setError, refresh,
    busy, submitting, loadKb, unloadKb,
    chat: {messages, running: current?.type === 'chat', sendQuestion: q => start('chat', [{id:'question-1',question:q.trim()}]),
      stopChat: stop, clearChat: () => {if (!current) setMessages([]);}},
    batch: {...batch, running: current?.type === 'batch'}, importFile,
    startBatch: () => start('batch', batch.questions), stopBatch: stop,
    newTask: () => setBatch({step:1, questions:[], fileName:'', importError:'', task:null}),
    changeFile: () => setBatch(b=>({...b,step:1,importError:''})),
  }}>{children}</AppContext.Provider>;
};
