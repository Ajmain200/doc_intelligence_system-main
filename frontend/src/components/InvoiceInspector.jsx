import React, { useState, useEffect } from 'react';
import { Save, Check, AlertCircle, Plus, Trash2 } from 'lucide-react';

export default function InvoiceInspector({ document, onSaveCorrection, apiBaseUrl }) {
  // Missing values stay empty ('' in the form, null to the API) — never defaulted to 0 / USD
  const emptyForm = {
    invoice_number: '',
    invoice_date: '',
    supplier_name: '',
    customer_name: '',
    currency: '',
    subtotal: '',
    tax: '',
    total: '',
    line_items: []
  };
  const [formData, setFormData] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);

  // Only reload the form when a different document is selected or the server copy actually
  // changed. Depending on `document` itself wiped the reviewer's edits on every 3s poll.
  const docKey = document ? `${document.id}:${document.updated_at}:${document.status}` : null;
  useEffect(() => {
    const ext = document?.extracted_data;
    if (!ext) {
      setFormData(emptyForm);
      return;
    }
    setFormData({
      invoice_number: ext.invoice_number ?? '',
      invoice_date: ext.invoice_date ?? '',
      supplier_name: ext.supplier_name ?? '',
      customer_name: ext.customer_name ?? '',
      currency: ext.currency ?? '',
      subtotal: ext.subtotal ?? '',
      tax: ext.tax ?? '',
      total: ext.total ?? '',
      line_items: ext.line_items ? ext.line_items.map(i => ({ ...i })) : []
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docKey]);

  useEffect(() => { setSaveMessage(null); }, [document?.id]);

  if (!document) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-8 text-center text-slate-400">
        Select a document from the queue to inspect extraction and financial data.
      </div>
    );
  }

  const ext = document.extracted_data;
  const scores = ext?.confidence_scores || {};
  const canEdit = Boolean(ext) && !['QUEUED', 'PROCESSING'].includes(document.status);

  const toNumberOrNull = (v) => {
    if (v === '' || v === null || v === undefined) return null;
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : null;
  };
  const toTextOrNull = (v) => (typeof v === 'string' && v.trim() ? v.trim() : null);

  const handleFieldChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  const handleLineItemChange = (index, field, value) => {
    const updated = [...formData.line_items];
    updated[index] = { ...updated[index], [field]: value };
    // Auto-calculate amount if quantity or unit_price changes
    if (field === 'quantity' || field === 'unit_price') {
      const q = toNumberOrNull(updated[index].quantity);
      const p = toNumberOrNull(updated[index].unit_price);
      if (q !== null && p !== null) {
        updated[index].amount = parseFloat((q * p).toFixed(2));
      }
    }
    setFormData(prev => ({ ...prev, line_items: updated }));
  };

  const addLineItem = () => {
    setFormData(prev => ({
      ...prev,
      line_items: [...prev.line_items, { description: '', quantity: 1, unit_price: 0, amount: 0, confidence: 1.0 }]
    }));
  };

  const removeLineItem = (index) => {
    setFormData(prev => ({
      ...prev,
      line_items: prev.line_items.filter((_, i) => i !== index)
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMessage(null);
    try {
      const payload = {
        invoice_number: toTextOrNull(formData.invoice_number),
        invoice_date: toTextOrNull(formData.invoice_date),
        supplier_name: toTextOrNull(formData.supplier_name),
        customer_name: toTextOrNull(formData.customer_name),
        currency: toTextOrNull(formData.currency)?.toUpperCase() ?? null,
        subtotal: toNumberOrNull(formData.subtotal),
        tax: toNumberOrNull(formData.tax),
        total: toNumberOrNull(formData.total),
        line_items: formData.line_items.map(i => ({
          description: toTextOrNull(i.description),
          quantity: toNumberOrNull(i.quantity),
          unit_price: toNumberOrNull(i.unit_price),
          amount: toNumberOrNull(i.amount),
          confidence: 1.0
        })),
        reviewer_notes: "Human reviewer correction via Dashboard"
      };

      const res = await fetch(`${apiBaseUrl}/documents/${document.id}/correct`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = Array.isArray(body.detail) ? body.detail.map(d => d.msg).join('; ') : body.detail;
        throw new Error(detail || `Failed to save corrections (${res.status})`);
      }
      const updatedDoc = await res.json();
      setSaveMessage({ type: 'success', text: 'Corrections saved and re-validated!' });
      if (onSaveCorrection) onSaveCorrection(updatedDoc);
    } catch (err) {
      setSaveMessage({ type: 'error', text: err.message || 'Save failed' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="flex items-center justify-between pb-4 border-b border-slate-200 mb-6">
        <div>
          <h2 className="text-base font-semibold text-slate-800">Extraction Inspector & Human Review</h2>
          <p className="text-xs text-slate-500">Document: {document.filename} ({document.file_type.toUpperCase()})</p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving || !canEdit}
          title={canEdit ? '' : 'Available once processing has finished'}
          className="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50"
        >
          <Save size={14} /> {saving ? 'Saving...' : 'Apply Correction & Re-Validate'}
        </button>
      </div>

      {saveMessage && (
        <div className={`mb-4 p-3 rounded-lg text-xs flex items-center gap-2 ${
          saveMessage.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'
        }`}>
          {saveMessage.type === 'success' ? <Check size={16} /> : <AlertCircle size={16} />}
          {saveMessage.text}
        </div>
      )}

      {/* Primary Key-Value Fields Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1 flex justify-between">
            <span>Invoice Number</span>
            {scores.invoice_number > 0 && <span className="text-[10px] text-slate-400">{Math.round(scores.invoice_number * 100)}%</span>}
          </label>
          <input
            type="text"
            className="w-full text-xs p-2 border border-slate-300 rounded focus:ring-1 focus:ring-indigo-500 outline-none"
            value={formData.invoice_number}
            onChange={(e) => handleFieldChange('invoice_number', e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1 flex justify-between">
            <span>Invoice Date</span>
            {scores.invoice_date > 0 && <span className="text-[10px] text-slate-400">{Math.round(scores.invoice_date * 100)}%</span>}
          </label>
          <input
            type="text"
            className="w-full text-xs p-2 border border-slate-300 rounded focus:ring-1 focus:ring-indigo-500 outline-none"
            value={formData.invoice_date}
            onChange={(e) => handleFieldChange('invoice_date', e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1 flex justify-between">
            <span>Supplier / Vendor</span>
            {scores.supplier_name > 0 && <span className="text-[10px] text-slate-400">{Math.round(scores.supplier_name * 100)}%</span>}
          </label>
          <input
            type="text"
            className="w-full text-xs p-2 border border-slate-300 rounded focus:ring-1 focus:ring-indigo-500 outline-none"
            value={formData.supplier_name}
            onChange={(e) => handleFieldChange('supplier_name', e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1 flex justify-between">
            <span>Customer / Billed To</span>
            {scores.customer_name > 0 && <span className="text-[10px] text-slate-400">{Math.round(scores.customer_name * 100)}%</span>}
          </label>
          <input
            type="text"
            className="w-full text-xs p-2 border border-slate-300 rounded focus:ring-1 focus:ring-indigo-500 outline-none"
            value={formData.customer_name}
            onChange={(e) => handleFieldChange('customer_name', e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Currency</label>
          <input
            type="text"
            className="w-full text-xs p-2 border border-slate-300 rounded focus:ring-1 focus:ring-indigo-500 outline-none uppercase"
            value={formData.currency}
            onChange={(e) => handleFieldChange('currency', e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Subtotal</label>
          <input
            type="number"
            step="0.01"
            className="w-full text-xs p-2 border border-slate-300 rounded focus:ring-1 focus:ring-indigo-500 outline-none"
            value={formData.subtotal}
            onChange={(e) => handleFieldChange('subtotal', e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Tax / VAT</label>
          <input
            type="number"
            step="0.01"
            className="w-full text-xs p-2 border border-slate-300 rounded focus:ring-1 focus:ring-indigo-500 outline-none"
            value={formData.tax}
            onChange={(e) => handleFieldChange('tax', e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1 font-bold text-indigo-700">Total Amount</label>
          <input
            type="number"
            step="0.01"
            className="w-full text-xs p-2 border border-indigo-300 rounded focus:ring-1 focus:ring-indigo-500 outline-none font-bold text-slate-800"
            value={formData.total}
            onChange={(e) => handleFieldChange('total', e.target.value)}
          />
        </div>
      </div>

      {/* Line Items Table */}
      <div className="mt-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-semibold text-slate-700 uppercase">Itemized Line Items ({formData.line_items.length})</h3>
          <button
            onClick={addLineItem}
            className="text-xs text-indigo-600 hover:text-indigo-800 flex items-center gap-1 font-medium"
          >
            <Plus size={14} /> Add Row
          </button>
        </div>

        <div className="border border-slate-200 rounded-lg overflow-hidden">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-600 font-medium border-b border-slate-200">
              <tr>
                <th className="p-2.5">Description</th>
                <th className="p-2.5 w-20">Qty</th>
                <th className="p-2.5 w-24">Unit Price</th>
                <th className="p-2.5 w-28">Amount</th>
                <th className="p-2.5 w-12 text-center">Del</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {formData.line_items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="p-4 text-center text-slate-400">No line items extracted.</td>
                </tr>
              ) : (
                formData.line_items.map((item, idx) => (
                  <tr key={idx} className="hover:bg-slate-50">
                    <td className="p-2">
                      <input
                        type="text"
                        className="w-full p-1 border border-slate-200 rounded text-xs"
                        value={item.description || ''}
                        onChange={(e) => handleLineItemChange(idx, 'description', e.target.value)}
                      />
                    </td>
                    <td className="p-2">
                      <input
                        type="number"
                        className="w-full p-1 border border-slate-200 rounded text-xs"
                        value={item.quantity ?? ''}
                        onChange={(e) => handleLineItemChange(idx, 'quantity', e.target.value)}
                      />
                    </td>
                    <td className="p-2">
                      <input
                        type="number"
                        step="0.01"
                        className="w-full p-1 border border-slate-200 rounded text-xs"
                        value={item.unit_price ?? ''}
                        onChange={(e) => handleLineItemChange(idx, 'unit_price', e.target.value)}
                      />
                    </td>
                    <td className="p-2">
                      <input
                        type="number"
                        step="0.01"
                        className="w-full p-1 border border-slate-200 rounded text-xs font-semibold"
                        value={item.amount ?? ''}
                        onChange={(e) => handleLineItemChange(idx, 'amount', e.target.value)}
                      />
                    </td>
                    <td className="p-2 text-center">
                      <button
                        onClick={() => removeLineItem(idx)}
                        className="text-rose-500 hover:text-rose-700"
                        title="Remove row"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
