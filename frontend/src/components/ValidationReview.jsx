import React from 'react';
import { AlertTriangle, XCircle, CheckCircle2, ShieldAlert } from 'lucide-react';

export default function ValidationReview({ document }) {
  if (!document || !document.validation_result) {
    return null;
  }

  const { is_valid, requires_manual_review, errors, math_checks, duplicate_detected } = document.validation_result;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <div className="flex items-center justify-between pb-4 border-b border-slate-200 mb-4">
        <div className="flex items-center gap-2">
          {is_valid ? (
            <span className="p-2 bg-emerald-100 text-emerald-700 rounded-lg"><CheckCircle2 size={18} /></span>
          ) : (
            <span className="p-2 bg-rose-100 text-rose-700 rounded-lg"><XCircle size={18} /></span>
          )}
          <div>
            <h3 className="text-sm font-semibold text-slate-800">
              {is_valid ? 'Automated Rules Validation Passed' : 'Validation Anomalies Detected'}
            </h3>
            <p className="text-xs text-slate-500">
              {requires_manual_review ? 'Human reviewer action is required before ingestion.' : 'All financial rules passed integrity checks.'}
            </p>
          </div>
        </div>

        {duplicate_detected && (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-300">
            <ShieldAlert size={14} /> Duplicate Invoice Alert
          </span>
        )}
      </div>

      {/* Validation Errors List */}
      {errors.length > 0 && (
        <div className="space-y-2 mb-4">
          <h4 className="text-xs font-semibold text-slate-700 uppercase">Triggered Rules & Flags</h4>
          {errors.map((err, idx) => (
            <div
              key={idx}
              className={`p-3 rounded-lg border text-xs flex items-start gap-2.5 ${
                err.severity === 'ERROR'
                  ? 'bg-rose-50 border-rose-200 text-rose-800'
                  : 'bg-amber-50 border-amber-200 text-amber-800'
              }`}
            >
              {err.severity === 'ERROR' ? <XCircle size={16} className="shrink-0 mt-0.5 text-rose-600" /> : <AlertTriangle size={16} className="shrink-0 mt-0.5 text-amber-600" />}
              <div>
                <div className="font-semibold">{err.rule_name}</div>
                <div className="text-slate-700 mt-0.5">{err.message}</div>
                {(err.expected_value !== null || err.actual_value !== null) && (
                  <div className="mt-1 text-[11px] font-mono text-slate-600">
                    Expected: <span className="font-bold">{String(err.expected_value)}</span> | Found: <span className="font-bold">{String(err.actual_value)}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Math Consistency Summary */}
      {math_checks && Object.keys(math_checks).length > 0 && (
        <div className="bg-slate-50 rounded-lg p-3 border border-slate-200">
          <h4 className="text-xs font-semibold text-slate-700 mb-2">Financial Calculation Audit</h4>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <div>
              <span className="text-slate-400 block text-[10px]">Sum of Line Items</span>
              <span className="font-semibold text-slate-700">${math_checks.line_items_sum ?? 'N/A'}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px]">Stated Subtotal</span>
              <span className="font-semibold text-slate-700">${math_checks.subtotal ?? 'N/A'}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px]">Expected Total</span>
              <span className="font-semibold text-slate-700">${math_checks.expected_total ?? 'N/A'}</span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px]">Declared Total</span>
              <span className="font-semibold text-slate-700">${math_checks.actual_total ?? 'N/A'}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
