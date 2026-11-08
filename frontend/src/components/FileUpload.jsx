import React, { useState } from 'react';
import { UploadCloud, File, CheckCircle2, AlertCircle } from 'lucide-react';

export default function FileUpload({ onUploadSuccess, apiBaseUrl }) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null);

  const ALLOWED = ['.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.xlsx', '.xls', '.csv'];

  const handleFiles = (files) => {
    const all = Array.from(files);
    const valid = all.filter(f => ALLOWED.some(ext => f.name.toLowerCase().endsWith(ext)));
    if (valid.length < all.length) {
      setUploadStatus({ type: 'error', message: `Skipped ${all.length - valid.length} unsupported file(s).` });
    }
    setSelectedFiles(prev => [...prev, ...valid]);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleUpload = async () => {
    if (selectedFiles.length === 0) return;
    setUploading(true);
    setUploadStatus(null);

    const formData = new FormData();
    selectedFiles.forEach(file => {
      formData.append('files', file);
    });

    try {
      const res = await fetch(`${apiBaseUrl}/documents/upload`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Upload failed (${res.status})`);
      }
      const data = await res.json();
      setUploadStatus({ type: 'success', message: `Successfully queued ${data.length} document(s)!` });
      setSelectedFiles([]);
      if (onUploadSuccess) onUploadSuccess(data);
    } catch (err) {
      setUploadStatus({ type: 'error', message: err.message || 'Error uploading files' });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <h2 className="text-lg font-semibold text-slate-800 mb-1">Batch Document Ingestion</h2>
      <p className="text-sm text-slate-500 mb-4">
        Upload PDF (digital/scanned), TIFF, JPG, PNG, XLSX, or CSV files. Multi-page up to 1000 pages supported.
      </p>

      <div
        onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-lg p-8 text-center transition-all cursor-pointer ${
          dragActive ? 'border-indigo-500 bg-indigo-50/50' : 'border-slate-300 hover:border-slate-400 bg-slate-50'
        }`}
        onClick={() => document.getElementById('file-input').click()}
      >
        <UploadCloud className="mx-auto h-12 w-12 text-slate-400 mb-3" />
        <p className="text-sm font-medium text-slate-700">Drag & drop business documents here, or browse</p>
        <p className="text-xs text-slate-400 mt-1">Supports PDF, XLSX, XLS, CSV, PNG, JPG, TIFF up to 100MB</p>
        <input
          id="file-input"
          type="file"
          multiple
          accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv"
          className="hidden"
          onChange={(e) => { handleFiles(e.target.files); e.target.value = ''; }}
        />
      </div>

      {selectedFiles.length > 0 && (
        <div className="mt-4">
          <div className="text-xs font-semibold text-slate-600 mb-2 uppercase">Selected Files ({selectedFiles.length})</div>
          <div className="max-h-40 overflow-y-auto space-y-1.5 pr-2">
            {selectedFiles.map((f, i) => (
              <div key={i} className="flex items-center justify-between text-xs bg-slate-100 p-2 rounded">
                <span className="flex items-center gap-2 truncate text-slate-700">
                  <File size={14} className="text-indigo-500" /> {f.name}
                </span>
                <span className="text-slate-400 shrink-0">{(f.size / 1024).toFixed(1)} KB</span>
              </div>
            ))}
          </div>

          <button
            onClick={handleUpload}
            disabled={uploading}
            className="mt-4 w-full bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-2 px-4 rounded-lg text-sm transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {uploading ? 'Processing Upload & Queueing...' : `Submit ${selectedFiles.length} File(s) to AI Pipeline`}
          </button>
        </div>
      )}

      {uploadStatus && (
        <div className={`mt-4 p-3 rounded-lg text-xs flex items-center gap-2 ${
          uploadStatus.type === 'success' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-rose-50 text-rose-700 border border-rose-200'
        }`}>
          {uploadStatus.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
          {uploadStatus.message}
        </div>
      )}
    </div>
  );
}
