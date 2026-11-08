from typing import List, Dict, Any, Optional

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    pd = None
    PANDAS_AVAILABLE = False

try:
    from sqlalchemy.orm import Session
    from sqlalchemy import func
except ImportError:
    Session = Any
    func = None

from app.models.schemas import (
    InvoiceExtractionSchema,
    ValidationResultSchema,
    ValidationErrorDetail,
    CrossVerificationResult
)
try:
    from app.models.database import ExtractedInvoiceModel, DocumentModel
    DB_AVAILABLE = True
except ImportError:
    ExtractedInvoiceModel = None
    DocumentModel = None
    DB_AVAILABLE = False
from app.config import settings
from app.core.logging import logger
from app.services.ai_extractor import to_float

class FinancialValidator:
    """
    Task 3: Financial Data Validation & Cross-Verification Engine.
    Executes business rules, mathematical consistency checks, duplicate invoice detection,
    and cross-document reconciliations (PDF-PDF and PDF-Excel).
    """

    MANDATORY_FIELDS = ["invoice_number", "invoice_date", "supplier_name", "total", "currency"]

    def __init__(self, tolerance: float = settings.FINANCIAL_TOLERANCE):
        self.tolerance = tolerance

    def validate(
        self,
        extracted: InvoiceExtractionSchema,
        db: Optional[Session] = None,
        current_doc_id: Optional[str] = None
    ) -> ValidationResultSchema:
        """
        Runs complete validation ruleset against an extracted invoice record.
        """
        errors: List[ValidationErrorDetail] = []
        math_checks: Dict[str, Any] = {}
        requires_manual_review = False
        duplicate_detected = False

        # --- Rule 1: Mandatory Fields Check ---
        for field in self.MANDATORY_FIELDS:
            val = getattr(extracted, field, None)
            if val is None or (isinstance(val, str) and not val.strip()):
                errors.append(ValidationErrorDetail(
                    rule_name="MANDATORY_FIELD_MISSING",
                    severity="ERROR",
                    field=field,
                    message=f"Mandatory financial field '{field}' is missing or undetectable."
                ))
                requires_manual_review = True

        # --- Rule 2: Numeric Non-Negative & Sanity Checks ---
        for num_field in ["subtotal", "tax", "total"]:
            val = getattr(extracted, num_field, None)
            if val is not None and val < 0:
                errors.append(ValidationErrorDetail(
                    rule_name="NEGATIVE_NUMERIC_VALUE",
                    severity="ERROR",
                    field=num_field,
                    message=f"Field '{num_field}' contains invalid negative amount: {val}",
                    actual_value=val
                ))
                requires_manual_review = True

        # --- Rule 3: Line Items Sum vs Subtotal Consistency ---
        if extracted.line_items and extracted.subtotal is not None:
            line_items_sum = sum(
                (item.amount if item.amount is not None else ((item.quantity or 0) * (item.unit_price or 0)))
                for item in extracted.line_items
            )
            diff = abs(line_items_sum - extracted.subtotal)
            math_checks["line_items_sum"] = round(line_items_sum, 2)
            math_checks["subtotal"] = extracted.subtotal
            math_checks["line_sum_vs_subtotal_diff"] = round(diff, 2)

            if diff > self.tolerance:
                errors.append(ValidationErrorDetail(
                    rule_name="LINE_ITEMS_SUBTOTAL_MISMATCH",
                    severity="ERROR",
                    field="subtotal",
                    message=f"Sum of itemized lines ({line_items_sum:.2f}) does not match declared subtotal ({extracted.subtotal:.2f}). Discrepancy: {diff:.2f}",
                    expected_value=extracted.subtotal,
                    actual_value=round(line_items_sum, 2)
                ))
                requires_manual_review = True
        elif not extracted.line_items and (extracted.total or 0) > 0:
            errors.append(ValidationErrorDetail(
                rule_name="NO_LINE_ITEMS_DETECTED",
                severity="WARNING",
                field="line_items",
                message="No itemized rows detected in invoice."
            ))

        # --- Rule 4: Subtotal + Tax == Total Math Consistency ---
        if extracted.total is not None and extracted.subtotal is not None:
            tax = extracted.tax or 0.0
            expected_total = extracted.subtotal + tax
            total_diff = abs(expected_total - extracted.total)
            math_checks["expected_total"] = round(expected_total, 2)
            math_checks["actual_total"] = extracted.total
            math_checks["total_diff"] = round(total_diff, 2)

            if total_diff > self.tolerance:
                errors.append(ValidationErrorDetail(
                    rule_name="CALCULATION_TAX_SUBTOTAL_TOTAL_MISMATCH",
                    severity="ERROR",
                    field="total",
                    message=f"Calculated Total (Subtotal {extracted.subtotal:.2f} + Tax {tax:.2f} = {expected_total:.2f}) does not equal stated Total ({extracted.total:.2f}). Diff: {total_diff:.2f}",
                    expected_value=round(expected_total, 2),
                    actual_value=extracted.total
                ))
                requires_manual_review = True

        # --- Rule 5: Duplicate Invoice Detection ---
        if db is not None and extracted.invoice_number and extracted.supplier_name:
            # Exact, case-insensitive comparison (ILIKE would treat '_' and '%' as wildcards)
            query = db.query(ExtractedInvoiceModel).join(DocumentModel).filter(
                func.lower(func.trim(ExtractedInvoiceModel.invoice_number)) == extracted.invoice_number.strip().lower(),
                func.lower(func.trim(ExtractedInvoiceModel.supplier_name)) == extracted.supplier_name.strip().lower()
            )
            if current_doc_id:
                query = query.filter(DocumentModel.id != current_doc_id)
            
            existing = query.first()
            if existing:
                duplicate_detected = True
                requires_manual_review = True
                errors.append(ValidationErrorDetail(
                    rule_name="DUPLICATE_INVOICE_FOUND",
                    severity="ERROR",
                    field="invoice_number",
                    message=f"Potential duplicate invoice! Invoice #{extracted.invoice_number} from supplier '{extracted.supplier_name}' already exists in document {existing.document_id}."
                ))

        # --- Rule 6: Confidence Threshold Check ---
        if extracted.overall_confidence < 0.70:
            errors.append(ValidationErrorDetail(
                rule_name="LOW_EXTRACTION_CONFIDENCE",
                severity="WARNING",
                message=f"Overall extraction confidence is low ({extracted.overall_confidence * 100:.1f}%). Document quality may be degraded."
            ))
            requires_manual_review = True

        is_valid = len([e for e in errors if e.severity == "ERROR"]) == 0

        return ValidationResultSchema(
            is_valid=is_valid,
            requires_manual_review=requires_manual_review,
            errors=errors,
            math_checks=math_checks,
            duplicate_detected=duplicate_detected
        )

    def cross_verify_pdf_pdf(
        self,
        doc_a: InvoiceExtractionSchema,
        doc_b: InvoiceExtractionSchema
    ) -> CrossVerificationResult:
        """
        Cross-verifies two documents (e.g. Purchase Order vs Supplier Invoice).
        Compares total, currency, supplier, and line items.
        """
        discrepancies = []
        matches = 0
        total_checks = 4

        # 1. Total comparison
        if doc_a.total is not None and doc_b.total is not None:
            diff = abs(doc_a.total - doc_b.total)
            if diff > self.tolerance:
                discrepancies.append({
                    "check": "TOTAL_AMOUNT",
                    "doc_a": doc_a.total,
                    "doc_b": doc_b.total,
                    "diff": round(diff, 2),
                    "status": "MISMATCH"
                })
            else:
                matches += 1
        else:
            discrepancies.append({"check": "TOTAL_AMOUNT", "status": "ONE_OR_BOTH_MISSING"})

        # 2. Currency comparison
        if doc_a.currency and doc_b.currency:
            if doc_a.currency.upper() == doc_b.currency.upper():
                matches += 1
            else:
                discrepancies.append({
                    "check": "CURRENCY",
                    "doc_a": doc_a.currency,
                    "doc_b": doc_b.currency,
                    "status": "MISMATCH"
                })

        # 3. Supplier matching
        if doc_a.supplier_name and doc_b.supplier_name:
            if doc_a.supplier_name.lower() in doc_b.supplier_name.lower() or doc_b.supplier_name.lower() in doc_a.supplier_name.lower():
                matches += 1
            else:
                discrepancies.append({
                    "check": "SUPPLIER_NAME",
                    "doc_a": doc_a.supplier_name,
                    "doc_b": doc_b.supplier_name,
                    "status": "MISMATCH"
                })

        # 4. Line items quantity check
        qty_a = sum(i.quantity or 0 for i in doc_a.line_items)
        qty_b = sum(i.quantity or 0 for i in doc_b.line_items)
        if qty_a > 0 and qty_b > 0:
            if abs(qty_a - qty_b) < 0.01:
                matches += 1
            else:
                discrepancies.append({
                    "check": "TOTAL_QUANTITY",
                    "doc_a_qty": qty_a,
                    "doc_b_qty": qty_b,
                    "status": "MISMATCH"
                })

        score = matches / total_checks
        status = "MATCH" if score >= 0.75 and len(discrepancies) == 0 else ("PARTIAL_MATCH" if score >= 0.5 else "MISMATCH")

        return CrossVerificationResult(
            match_status=status,
            discrepancies=discrepancies,
            confidence=round(score, 2),
            summary=f"PDF-PDF cross check completed with status '{status}' ({matches}/{total_checks} key checks matched)."
        )

    def cross_verify_pdf_excel(
        self,
        invoice: InvoiceExtractionSchema,
        excel_df: "pd.DataFrame"
    ) -> CrossVerificationResult:
        """
        Reconciles an extracted invoice against an Excel spreadsheet / ledger.
        Searches for invoice_number in the dataframe and compares total amount and date.
        """
        discrepancies = []
        if not invoice.invoice_number:
            return CrossVerificationResult(
                match_status="MISMATCH",
                discrepancies=[{"reason": "Invoice has no invoice_number to search in Excel"}],
                confidence=0.0,
                summary="Cannot cross-verify: Extracted invoice lacks an invoice number."
            )

        # Normalize df column names
        df_cols_lower = {str(c).strip().lower(): c for c in excel_df.columns}

        target_inv = str(invoice.invoice_number).strip().lower()

        # Prefer invoice-like columns, then search every column for an exact cell match
        def col_priority(col_name: str) -> int:
            for rank, term in enumerate(["invoice", "inv", "bill", "doc", "number", "ref", "id"]):
                if term in col_name:
                    return rank
            return 99

        candidate_cols = sorted(df_cols_lower.items(), key=lambda kv: col_priority(kv[0]))
        matched_rows = excel_df.iloc[0:0]
        for _, orig in candidate_cols:
            cells = excel_df[orig].astype(str).str.strip().str.lower()
            hits = excel_df[cells == target_inv]
            if not hits.empty:
                matched_rows = hits
                break

        if matched_rows.empty:
            return CrossVerificationResult(
                match_status="MISMATCH",
                discrepancies=[{
                    "check": "LEDGER_LOOKUP",
                    "searched_invoice": invoice.invoice_number,
                    "status": "NOT_FOUND_IN_EXCEL"
                }],
                confidence=0.0,
                summary=f"Invoice #{invoice.invoice_number} was not found in the Excel ledger."
            )

        matched_row = matched_rows.iloc[0]
        
        # Check amount column in Excel ('total' columns win over 'net'/'amount' columns)
        amt_col = None
        for term in ["total", "gross", "amount", "balance", "sum", "net"]:
            amt_col = next((orig for col_name, orig in df_cols_lower.items() if term in col_name), None)
            if amt_col is not None:
                break

        if amt_col is None or invoice.total is None:
            discrepancies.append({
                "check": "LEDGER_AMOUNT",
                "status": "NOT_COMPARED",
                "reason": "No amount column in spreadsheet" if amt_col is None else "Invoice total is missing",
            })
        else:
            try:
                excel_amt = to_float(matched_row[amt_col])
                if excel_amt is None:
                    raise ValueError(f"non-numeric ledger amount {matched_row[amt_col]!r}")
                diff = abs(excel_amt - invoice.total)
                if diff > self.tolerance:
                    discrepancies.append({
                        "check": "LEDGER_AMOUNT_MISMATCH",
                        "invoice_total": invoice.total,
                        "excel_amount": excel_amt,
                        "diff": round(diff, 2),
                        "status": "MISMATCH"
                    })
            except Exception as parse_err:
                logger.warning(f"Failed to parse Excel amount: {parse_err}")

        hard_mismatch = any(d.get("status") == "MISMATCH" for d in discrepancies)
        status = "MATCH" if not discrepancies else ("MISMATCH" if hard_mismatch else "PARTIAL_MATCH")
        return CrossVerificationResult(
            match_status=status,
            discrepancies=discrepancies,
            confidence=1.0 if status == "MATCH" else 0.5,
            summary=f"Reconciliation against Excel completed with status '{status}' for invoice #{invoice.invoice_number}."
        )
