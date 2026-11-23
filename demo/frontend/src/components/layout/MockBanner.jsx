import { useApp } from '../../context/AppContext';
export default function ConnectionBanner() {
 const {service,error} = useApp();
 const text = error || (!service.connected ? 'Start the local backend to load a knowledge base and run real queries.' :
  !service.credentialsConfigured ? 'The backend is running, but school gateway credentials are not configured. No model request can be started.' : 'Live mode · Answers use the selected local evidence. Automated checks do not establish factual correctness.');
 return <div role="status" className={`shrink-0 border-b px-6 py-2 text-sm ${error?'bg-red-50 text-red-700':'bg-blue-50 text-blue-800'}`}>{text}</div>;
}
