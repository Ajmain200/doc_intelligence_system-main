import React, { useState } from 'react';
import { GitCompare, CheckCircle2, XCircle, AlertCircle, ArrowRight } from 'lucide-react';

export default function CrossVerification({ documents, apiBaseUrl }) {
  const [docAId, setDocAId] = useState('');
  const [docBId, setDocBId] = useState('');
  const [tolerance, setTolerance] = useState(0.05);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleVerify = async () => {
    if (!docAId || !docBId) {
      setError('Please select both a Primary and a Reference document.');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch(`${apiBaseUrl}/cross-verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          primary_doc_id: docAId,
          reference_doc_id: docBId,
          tolerance: parseFloat(tolerance)
        })
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Cross verification failed');
      }

      const data = await res.json();
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="pb-4 border-b border-slate-200 mb-6">
        <h2 className="text-base font-semibold text-slate-800 flex items-center gap-2">
          <GitCompare className="text-indigo-600" size={20} /> Cross-Document Verification Studio
        </h2>
        <p className="text-xs text-slate-500">
          Reconcile PDF Invoices against Purchase Orders (PDF-to-PDF) or Accounting Ledgers (PDF-to-Excel).
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        {/* Document A */}
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            Primary Document (e.g. PDF Invoice)
          </label>
          <select
            className="w-full text-xs p-2.5 border border-slate-300 rounded-lg outline-none bg-white"
            value={docAId}
            onChange={(e) => setDocAId(e.target.value)}
          >
            <option value="">-- Select Primary Document --</option>
            {documents.map(d => (
              <option key={d.id} value={d.id}>
                {d.filename} ({d.file_type.toUpperCase()}) - Status: {d.status}
              </option>
            ))}
          </select>
        </div>

        {/* Document B */}
        <div>
          <label className="block text-xs font-semibold text-slate-700 mb-1">
            Reference Document (e.g. PDF PO or Excel Ledger)
          </label>
          <select
            className="w-full text-xs p-2.5 border border-slate-300 rounded-lg outline-none bg-white"
            value={docBId}
            onChange={(e) => setDocBId(e.target.value)}
          >
            <option value="">-- Select Reference Document --</option>
            {documents.map(d => (
              <option key={d.id} value={d.id}>
                {d.filename} ({d.file_type.toUpperCase()}) - Status: {d.status}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex items-center gap-4 mb-6">
        <div className="w-48">
          <label className="block text-xs font-medium text-slate-600 mb-1">Allowed Tolerance ($)</label>
          <input
            type="number"
            step="0.01"
            className="w-full text-xs p-2 border border-slate-300 rounded outline-none"
            value={tolerance}
            onChange={(e) => setTolerance(e.target.value)}
          />
        </div>

        <button
          onClick={handleVerify}
          disabled={loading || !docAId || !docBId}
          className="mt-5 bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-xs px-5 py-2.5 rounded-lg flex items-center gap-2 transition-colors disabled:opacity-50"
        >
          {loading ? 'Reconciling Documents...' : 'Execute Cross-Verification'}
        </button>
      </div>

      {error && (
        <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-700 flex items-center gap-2 mb-4">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* Result Display */}
      {result && (
        <div className="mt-6 border border-slate-200 rounded-lg overflow-hidden">
          <div className={`p-4 flex items-center justify-between ${
            result.match_status === 'MATCH' ? 'bg-emerald-50 text-emerald-900 border-b border-emerald-200' :
            result.match_status === 'PARTIAL_MATCH' ? 'bg-amber-50 text-amber-900 border-b border-amber-200' :
            'bg-rose-50 text-rose-900 border-b border-rose-200'
          }`}>
            <div className="flex items-center gap-2 font-semibold text-sm">
              {result.match_status === 'MATCH' ? <CheckCircle2 size={18} className="text-emerald-600" /> : <XCircle size={18} className="text-rose-600" />}
              Reconciliation Status: {result.match_status}
            </div>
            <div className="text-xs font-medium">
              Match Confidence: {Math.round(result.confidence * 100)}%
            </div>
          </div>

          <div className="p-4 bg-slate-50 text-xs">
            <p className="font-medium text-slate-700 mb-3">{result.summary}</p>

            {result.discrepancies.length > 0 ? (
              <div>
                <h4 className="font-semibold text-slate-600 uppercase text-[11px] mb-2">Identified Discrepancies</h4>
                <div className="space-y-1.5">
                  {result.discrepancies.map((d, i) => (
                    <div key={i} className="p-2 bg-white rounded border border-slate-200 flex items-center justify-between text-slate-700">
                      <span className="font-mono font-medium">{d.check || d.reason}</span>
                      <span className="text-rose-600 font-semibold">{d.status || `Diff: $${d.diff}`}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-emerald-700 font-medium">All financial amounts, quantities, and entities matched perfectly within tolerance.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
