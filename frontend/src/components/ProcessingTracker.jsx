import React from 'react';
import { RefreshCw, Clock, CheckCircle, AlertTriangle, XCircle, RotateCcw, Trash2 } from 'lucide-react';

export default function ProcessingTracker({ documents, selectedDoc, onSelectDoc, onRefresh, onReprocess, onDelete, onClearAll, loading }) {
  const getStatusBadge = (status) => {
    switch (status) {
      case 'COMPLETED':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800"><CheckCircle size={12} /> Completed</span>;
      case 'NEEDS_REVIEW':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800"><AlertTriangle size={12} /> Needs Review</span>;
      case 'PROCESSING':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 animate-pulse"><RefreshCw size={12} className="animate-spin" /> Processing</span>;
      case 'QUEUED':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-800"><Clock size={12} /> Queued</span>;
      case 'FAILED':
        return <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-100 text-rose-800"><XCircle size={12} /> Failed</span>;
      default:
        return <span className="px-2 py-0.5 rounded text-xs bg-slate-100 text-slate-700">{status}</span>;
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
      <div className="p-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">Live Ingestion Queue & Documents</h3>
          <p className="text-xs text-slate-500">Real-time status of OCR, extraction, and validation runs</p>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onClearAll}
            disabled={documents.length === 0}
            className="px-2 py-1 text-xs font-semibold text-rose-600 hover:text-rose-800 hover:bg-rose-50 rounded flex items-center gap-1 transition-colors disabled:opacity-40 disabled:hover:bg-transparent"
            title="Delete all documents"
          >
            <Trash2 size={14} /> Clear all
          </button>
          <button
            onClick={onRefresh}
            className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-200 rounded transition-colors"
            title="Refresh Queue"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="overflow-x-auto max-h-96">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-100 text-slate-600 font-medium border-b border-slate-200 sticky top-0">
            <tr>
              <th className="p-3">File Name</th>
              <th className="p-3">Type</th>
              <th className="p-3">Pages</th>
              <th className="p-3">Status</th>
              <th className="p-3">Confidence</th>
              <th className="p-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {documents.length === 0 ? (
              <tr>
                <td colSpan={6} className="p-8 text-center text-slate-400">
                  No documents in system. Upload files to start processing.
                </td>
              </tr>
            ) : (
              documents.map(doc => {
                const isSelected = selectedDoc && selectedDoc.id === doc.id;
                const conf = doc.extracted_data?.overall_confidence;
                return (
                  <tr
                    key={doc.id}
                    onClick={() => onSelectDoc(doc)}
                    className={`cursor-pointer transition-colors ${
                      isSelected ? 'bg-indigo-50/70 border-l-4 border-indigo-600' : 'hover:bg-slate-50'
                    }`}
                  >
                    <td className="p-3 font-medium text-slate-800 truncate max-w-xs">{doc.filename}</td>
                    <td className="p-3 uppercase text-slate-500">{doc.file_type.replace('.', '')}</td>
                    <td className="p-3 text-slate-600">{doc.page_count || 1}</td>
                    <td className="p-3">{getStatusBadge(doc.status)}</td>
                    <td className="p-3 text-slate-600">
                      {conf !== undefined ? (
                        <div className="flex items-center gap-1.5">
                          <div className="w-12 bg-slate-200 rounded-full h-1.5">
                            <div
                              className={`h-1.5 rounded-full ${conf > 0.8 ? 'bg-emerald-500' : conf > 0.5 ? 'bg-amber-500' : 'bg-rose-500'}`}
                              style={{ width: `${Math.round(conf * 100)}%` }}
                            />
                          </div>
                          <span className="text-[10px]">{Math.round(conf * 100)}%</span>
                        </div>
                      ) : '-'}
                    </td>
                    <td className="p-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {doc.status === 'FAILED' && (
                          <button
                            onClick={(e) => { e.stopPropagation(); onReprocess(doc.id); }}
                            className="text-indigo-600 hover:text-indigo-800 p-1 flex items-center gap-1 text-xs font-semibold"
                            title="Reprocess failed job"
                          >
                            <RotateCcw size={12} /> Retry
                          </button>
                        )}
                        <button
                          onClick={(e) => { e.stopPropagation(); onDelete(doc); }}
                          disabled={doc.status === 'PROCESSING'}
                          className="text-slate-400 hover:text-rose-600 p-1 disabled:opacity-30"
                          title="Delete document"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
