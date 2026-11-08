import React, { useState } from 'react';
import { Search, Sparkles, FileText, ArrowUpRight } from 'lucide-react';

export default function SearchBar({ onSelectDocById, apiBaseUrl }) {
  const [query, setQuery] = useState('');
  const [searchType, setSearchType] = useState('hybrid');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setHasSearched(true);

    try {
      const res = await fetch(`${apiBaseUrl}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          search_type: searchType,
          limit: 10
        })
      });

      if (!res.ok) throw new Error('Search failed');
      const data = await res.json();
      setResults(data.results || []);
    } catch (err) {
      console.error(err);
      setResults([]);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="pb-3 border-b border-slate-200 mb-4">
        <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-1.5">
          <Sparkles size={16} className="text-indigo-600" /> Hybrid Search Explorer
        </h3>
        <p className="text-xs text-slate-500">
          Query across document content, invoice numbers, vendors, or semantic concepts.
        </p>
      </div>

      <form onSubmit={handleSearch} className="flex gap-2 mb-3">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-3 text-slate-400" />
          <input
            type="text"
            className="w-full text-xs pl-9 pr-4 py-2.5 border border-slate-300 rounded-lg outline-none focus:ring-1 focus:ring-indigo-500"
            placeholder="Search keywords or semantic meaning (e.g. 'Cloud hosting AWS', 'Invoice INV-9021', 'Q3 consulting')..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <select
          value={searchType}
          onChange={(e) => setSearchType(e.target.value)}
          className="text-xs border border-slate-300 rounded-lg px-3 bg-white outline-none text-slate-700"
        >
          <option value="hybrid">Hybrid (Keyword + Vector)</option>
          <option value="semantic">Semantic (Vector Only)</option>
          <option value="keyword">Keyword (Exact Match)</option>
        </select>

        <button
          type="submit"
          disabled={searching}
          className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
        >
          {searching ? 'Searching...' : 'Search'}
        </button>
      </form>

      {/* Results Dropdown / Table */}
      {hasSearched && (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <div className="text-xs text-slate-500 mb-2">
            Found {results.length} result(s) for "{query}"
          </div>

          {results.length === 0 ? (
            <div className="text-xs text-slate-400 py-3 text-center">No matching documents found.</div>
          ) : (
            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
              {results.map((res, i) => (
                <div
                  key={i}
                  onClick={() => onSelectDocById(res.document_id)}
                  className="p-2.5 rounded-lg border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/40 cursor-pointer flex items-center justify-between transition-all"
                >
                  <div className="flex items-center gap-2.5">
                    <FileText size={16} className="text-indigo-600 shrink-0" />
                    <div>
                      <div className="text-xs font-semibold text-slate-800">
                        {res.details?.filename || 'Document'}
                      </div>
                      <div className="text-[11px] text-slate-500">
                        Supplier: {res.details?.supplier_name || 'N/A'} | Inv #{res.details?.invoice_number || 'N/A'} | Total: ${res.details?.total ?? '0'}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className="text-[10px] bg-indigo-100 text-indigo-700 font-semibold px-2 py-0.5 rounded">
                      Score: {Math.round(res.score * 100)}%
                    </span>
                    <ArrowUpRight size={14} className="text-slate-400" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
