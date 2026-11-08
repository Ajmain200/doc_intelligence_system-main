import React, { useState, useEffect, useCallback } from 'react';
import { Layers, FileText, CheckSquare, GitCompare, Search, ShieldCheck } from 'lucide-react';
import FileUpload from './components/FileUpload';
import ProcessingTracker from './components/ProcessingTracker';
import InvoiceInspector from './components/InvoiceInspector';
import ValidationReview from './components/ValidationReview';
import CrossVerification from './components/CrossVerification';
import SearchBar from './components/SearchBar';

// Default goes through the Vite dev proxy (vite.config.js -> localhost:8000), so it works on any
// dev port without CORS. Set VITE_API_BASE_URL for a separately hosted backend.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

export default function App() {
  const [activeTab, setActiveTab] = useState('pipeline'); // 'pipeline', 'inspector', 'cross_verify', 'search'
  const [documents, setDocuments] = useState([]);
  // Track the selection by id and derive the document from the latest list, so the
  // 3-second poll never resets the selection (the old code captured a stale closure).
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState(null);

  const selectedDoc = documents.find(d => d.id === selectedId) || null;
  const setSelectedDoc = (doc) => setSelectedId(doc ? doc.id : null);

  const fetchDocuments = useCallback(async ({ showSpinner = false } = {}) => {
    if (showSpinner) setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/documents?limit=200`);
      if (!res.ok) throw new Error(`API responded ${res.status}`);
      const data = await res.json();
      setDocuments(data);
      setApiError(null);
      setSelectedId(prev => (prev && data.some(d => d.id === prev)) ? prev : (data[0]?.id ?? null));
    } catch (err) {
      console.error('Failed to load documents:', err);
      setApiError(`Cannot reach the backend at ${API_BASE_URL}. Is the FastAPI server running?`);
    } finally {
      if (showSpinner) setLoading(false);
    }
  }, []);

  const refreshNow = () => fetchDocuments({ showSpinner: true });

  useEffect(() => {
    fetchDocuments({ showSpinner: true });
    // Poll for queue status updates every 3 seconds
    const interval = setInterval(() => fetchDocuments(), 3000);
    return () => clearInterval(interval);
  }, [fetchDocuments]);

  const handleSelectDocById = (docId) => {
    if (documents.some(d => d.id === docId)) {
      setSelectedId(docId);
      setActiveTab('inspector');
    }
  };

  const handleReprocess = async (docId) => {
    try {
      const res = await fetch(`${API_BASE_URL}/documents/${docId}/reprocess`, { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Reprocess failed (${res.status})`);
      }
      refreshNow();
    } catch (err) {
      console.error('Reprocess failed:', err);
      setApiError(err.message);
    }
  };

  const handleDelete = async (doc) => {
    if (!window.confirm(`Delete "${doc.filename}" and its extracted data? This cannot be undone.`)) return;
    try {
      const res = await fetch(`${API_BASE_URL}/documents/${doc.id}`, { method: 'DELETE' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Delete failed (${res.status})`);
      }
      setDocuments(prev => prev.filter(d => d.id !== doc.id));
      refreshNow();
    } catch (err) {
      setApiError(err.message);
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm(`Delete ALL ${documents.length} document(s), their extracted data and uploaded files? This cannot be undone.`)) return;
    try {
      const res = await fetch(`${API_BASE_URL}/documents?confirm=true`, { method: 'DELETE' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Clear failed (${res.status})`);
      }
      const { skipped_processing } = await res.json();
      setApiError(skipped_processing ? `${skipped_processing} document(s) still processing were kept.` : null);
      setDocuments([]);
      setSelectedId(null);
      refreshNow();
    } catch (err) {
      setApiError(err.message);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100 text-slate-800 font-sans">
      {/* Top Navbar */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-3 flex flex-wrap gap-3 items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-600 rounded-lg text-white font-bold">
              <Layers size={20} />
            </div>
            <div>
              <h1 className="text-sm font-bold text-slate-900 tracking-tight">AI Document Intelligence System</h1>
              <p className="text-[11px] text-slate-400">Enterprise Multi-Format Extraction, Validation & Cross-Reconciliation</p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="flex flex-wrap items-center gap-1 bg-slate-100 p-1 rounded-xl">
            <button
              onClick={() => setActiveTab('pipeline')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'pipeline' ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <FileText size={14} /> Pipeline & Ingestion
            </button>
            <button
              onClick={() => setActiveTab('inspector')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'inspector' ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <CheckSquare size={14} /> Extraction & Review
            </button>
            <button
              onClick={() => setActiveTab('cross_verify')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'cross_verify' ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <GitCompare size={14} /> Cross-Verification
            </button>
            <button
              onClick={() => setActiveTab('search')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all ${
                activeTab === 'search' ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <Search size={14} /> Hybrid Search
            </button>
          </nav>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-6 py-6">
        {apiError && (
          <div className="mb-4 p-3 rounded-lg text-xs bg-rose-50 text-rose-700 border border-rose-200">
            {apiError}
          </div>
        )}

        {/* Tab 1: Pipeline & Ingestion */}
        {activeTab === 'pipeline' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-5">
              <FileUpload onUploadSuccess={refreshNow} apiBaseUrl={API_BASE_URL} />
            </div>
            <div className="lg:col-span-7">
              <ProcessingTracker
                documents={documents}
                selectedDoc={selectedDoc}
                onSelectDoc={(doc) => { setSelectedDoc(doc); setActiveTab('inspector'); }}
                onRefresh={refreshNow}
                onReprocess={handleReprocess}
                onDelete={handleDelete}
                onClearAll={handleClearAll}
                loading={loading}
              />
            </div>
          </div>
        )}

        {/* Tab 2: Extraction & Review */}
        {activeTab === 'inspector' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-8 space-y-6">
              <InvoiceInspector
                document={selectedDoc}
                onSaveCorrection={(updated) => {
                  setDocuments(prev => prev.map(d => (d.id === updated.id ? updated : d)));
                  refreshNow();
                }}
                apiBaseUrl={API_BASE_URL}
              />
            </div>
            <div className="lg:col-span-4 space-y-6">
              <ValidationReview document={selectedDoc} />
            </div>
          </div>
        )}

        {/* Tab 3: Cross-Verification Studio */}
        {activeTab === 'cross_verify' && (
          <CrossVerification documents={documents} apiBaseUrl={API_BASE_URL} />
        )}

        {/* Tab 4: Hybrid Search */}
        {activeTab === 'search' && (
          <div className="space-y-6">
            <SearchBar onSelectDocById={handleSelectDocById} apiBaseUrl={API_BASE_URL} />
          </div>
        )}
      </main>
    </div>
  );
}
