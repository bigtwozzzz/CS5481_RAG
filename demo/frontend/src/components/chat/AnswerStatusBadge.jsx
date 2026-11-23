import {answerStatus,answerLabels} from '../../lib/answerStatus';
export default function AnswerStatusBadge({result,compact=false}) {
 const status=answerStatus(result);
 if (!answerLabels[status]) return null;
 const style=status==='PARTIAL'?'text-blue-800 bg-blue-50 border-blue-200':
  status==='INSUFFICIENT_SOURCES'?'text-amber-800 bg-amber-50 border-amber-200':
  status==='ERROR'?'text-red-800 bg-red-50 border-red-200':
  status==='ANSWERED'?'text-green-800 bg-green-50 border-green-200':'text-gray-700 bg-gray-50 border-gray-200';
 return <div className={`${style} border rounded ${compact?'inline-block px-2 py-1 text-xs':'px-3 py-2 mb-3 text-sm'}`}>
  <span className="font-medium">{answerLabels[status]}</span>
  {!compact&&status==='PARTIAL'&&<p className="mt-1">Some parts were answered; other requested information is missing from the supplied evidence.</p>}
  {!compact&&status==='INSUFFICIENT_SOURCES'&&<p className="mt-1">The supplied evidence does not contain enough information to answer the question.</p>}
 </div>;
}
