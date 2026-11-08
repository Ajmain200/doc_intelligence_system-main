import re
import uuid
from typing import List, Optional
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Query
from sqlalchemy.orm import Session
import pandas as pd

from app.models.database import (
    get_db,
    DocumentModel,
    ExtractedInvoiceModel,
    ValidationErrorModel,
    AuditLogModel,
    LineItemModel
)
from app.models.schemas import (
    DocumentResponseSchema,
    InvoiceExtractionSchema,
    ValidationResultSchema,
    ValidationErrorDetail,
    LineItemSchema,
    ManualCorrectionRequest,
    CrossVerificationRequest,
    CrossVerificationResult,
    SearchQuerySchema
)
from app.services.worker import process_document_job
from app.services.validator import FinancialValidator
from app.services.search_service import search_service
from app.services.document_processor import DocumentProcessor
from app.services.ai_extractor import compute_missing_fields
from app.config import settings
from app.core.logging import logger

router = APIRouter()

UPLOAD_CHUNK_BYTES = 1024 * 1024
SPREADSHEET_TYPES = {".xlsx", ".xls", ".csv"}


def _safe_filename(name: str) -> str:
    """Strips directories and unsafe characters from a client-supplied filename."""
    base = Path((name or "").replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._\- ()]", "_", base).strip(" .")
    return base[:150] or "upload"


def _extraction_to_schema(ext: ExtractedInvoiceModel) -> InvoiceExtractionSchema:
    return InvoiceExtractionSchema(
        invoice_number=ext.invoice_number,
        invoice_date=ext.invoice_date,
        supplier_name=ext.supplier_name,
        customer_name=ext.customer_name,
        currency=ext.currency,
        subtotal=ext.subtotal,
        tax=ext.tax,
        total=ext.total,
        line_items=[
            LineItemSchema(
                description=i.description, quantity=i.quantity, unit_price=i.unit_price,
                amount=i.amount, confidence=i.confidence if i.confidence is not None else 1.0
            )
            for i in ext.line_items
        ],
        missing_fields=ext.missing_fields or [],
        confidence_scores=ext.confidence_scores or {},
        overall_confidence=ext.overall_confidence if ext.overall_confidence is not None else 0.0,
        raw_summary=ext.raw_summary,
    )


def _read_spreadsheet_all_sheets(path: str, file_type: str) -> pd.DataFrame:
    """Loads a CSV, or every sheet of an Excel workbook stacked into one DataFrame."""
    if file_type == ".csv":
        return pd.read_csv(path, dtype=str, sep=None, engine="python", encoding_errors="replace")
    sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    frames = [df.dropna(how="all") for df in sheets.values() if not df.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)

def serialize_document_response(doc: DocumentModel, db: Session) -> DocumentResponseSchema:
    """Helper to assemble full DocumentResponseSchema from DB entities."""
    extracted_schema = _extraction_to_schema(doc.extraction) if doc.extraction else None
    math_checks = {}
    if extracted_schema is not None:
        # Cheap, DB-free recomputation so the UI can show the calculation audit
        math_checks = FinancialValidator().validate(extracted_schema).math_checks

    val_errors = db.query(ValidationErrorModel).filter(
        ValidationErrorModel.document_id == doc.id
    ).all()

    error_details = [
        ValidationErrorDetail(
            rule_name=e.rule_name,
            severity=e.severity,
            field=e.field,
            message=e.message,
            expected_value=e.expected_value,
            actual_value=e.actual_value
        )
        for e in val_errors
    ]

    val_result = ValidationResultSchema(
        is_valid=len([e for e in error_details if e.severity == "ERROR"]) == 0,
        requires_manual_review=(doc.status == "NEEDS_REVIEW"),
        errors=error_details,
        math_checks=math_checks,
        duplicate_detected=any(e.rule_name == "DUPLICATE_INVOICE_FOUND" for e in error_details)
    )

    return DocumentResponseSchema(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size_bytes=doc.file_size_bytes,
        page_count=doc.page_count,
        status=doc.status,
        error_message=doc.error_message,
        extracted_data=extracted_schema,
        validation_result=val_result,
        created_at=doc.created_at,
        updated_at=doc.updated_at
    )


# 1. Multi-document Upload
@router.post("/documents/upload", response_model=List[DocumentResponseSchema])
def upload_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Accepts multiple PDF, PNG, JPG, TIFF, XLSX, XLS, and CSV files.
    Enqueues files for background OCR, AI extraction, and validation.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files were provided.")

    # Validate the whole batch before writing anything, so a bad file doesn't leave a partial upload
    for upload in files:
        ext = Path(upload.filename or "").suffix.lower()
        if ext not in DocumentProcessor.SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format '{ext}' for file {upload.filename}."
            )

    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    results = []
    for upload in files:
        ext = Path(upload.filename).suffix.lower()
        original_name = _safe_filename(upload.filename)
        target_path = settings.STORAGE_DIR / f"{uuid.uuid4().hex}_{original_name}"

        file_size = 0
        too_large = False
        with open(target_path, "wb") as buffer:
            while chunk := upload.file.read(UPLOAD_CHUNK_BYTES):
                file_size += len(chunk)
                if file_size > max_bytes:
                    too_large = True
                    break
                buffer.write(chunk)
        if too_large:
            target_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=413,
                detail=f"File {original_name} exceeds the {settings.MAX_FILE_SIZE_MB} MB limit."
            )

        doc = DocumentModel(
            filename=original_name,
            file_path=str(target_path),
            file_type=ext,
            file_size_bytes=file_size,
            status="QUEUED"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        db.add(AuditLogModel(
            document_id=doc.id,
            action="FILE_UPLOADED",
            changed_by="user",
            details={"original_filename": original_name, "size_bytes": file_size}
        ))
        db.commit()

        # Enqueue background processing
        background_tasks.add_task(process_document_job, doc.id)
        results.append(serialize_document_response(doc, db))

    return results


# 2. Get All Documents (List with status filter)
@router.get("/documents", response_model=List[DocumentResponseSchema])
def list_documents(
    status: Optional[str] = Query(None, description="Filter by status: QUEUED, PROCESSING, COMPLETED, NEEDS_REVIEW, FAILED"),
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    query = db.query(DocumentModel).order_by(DocumentModel.created_at.desc())
    if status:
        query = query.filter(DocumentModel.status == status.upper())
    docs = query.offset(offset).limit(limit).all()
    return [serialize_document_response(doc, db) for doc in docs]


# 3. Get Document Status & Results by ID
@router.get("/documents/{doc_id}", response_model=DocumentResponseSchema)
def get_document(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return serialize_document_response(doc, db)


def _delete_document_record(doc: DocumentModel, db: Session) -> None:
    """Deletes a document, its DB children (cascade), its search entry and its uploaded file."""
    file_path = Path(doc.file_path)
    doc_id = doc.id
    db.delete(doc)
    db.flush()
    search_service.remove_document(doc_id)
    # Only remove files inside the uploads folder (never follow a path stored elsewhere)
    try:
        if file_path.resolve().is_relative_to(settings.STORAGE_DIR.resolve()):
            file_path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"Could not delete uploaded file {file_path}: {e}")


# 3b. Delete a single document
@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.status == "PROCESSING":
        raise HTTPException(status_code=409, detail="Document is being processed; try again when it finishes.")
    _delete_document_record(doc, db)
    db.commit()
    return {"deleted": 1}


# 3c. Clear all documents (requires ?confirm=true to avoid accidental wipes)
@router.delete("/documents")
def delete_all_documents(confirm: bool = Query(False), db: Session = Depends(get_db)):
    if not confirm:
        raise HTTPException(status_code=400, detail="Add ?confirm=true to delete all documents.")
    docs = db.query(DocumentModel).all()
    deleted, skipped = 0, 0
    for doc in docs:
        if doc.status == "PROCESSING":
            skipped += 1
            continue
        _delete_document_record(doc, db)
        deleted += 1
    db.commit()
    logger.info(f"Cleared {deleted} documents ({skipped} still processing were kept).")
    return {"deleted": deleted, "skipped_processing": skipped}


# 4. Reprocess Failed or Review Document
@router.post("/documents/{doc_id}/reprocess", response_model=DocumentResponseSchema)
def reprocess_document(
    doc_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Triggers background reprocessing for failed jobs or documents needing re-extraction."""
    doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.status in ("QUEUED", "PROCESSING"):
        raise HTTPException(status_code=409, detail=f"Document is already {doc.status.lower()}.")

    doc.status = "QUEUED"
    doc.error_message = None
    db.commit()

    db.add(AuditLogModel(
        document_id=doc.id,
        action="REPROCESS_TRIGGERED",
        changed_by="user"
    ))
    db.commit()

    background_tasks.add_task(process_document_job, doc.id)
    return serialize_document_response(doc, db)


# 5. Manual Corrections
@router.patch("/documents/{doc_id}/correct", response_model=DocumentResponseSchema)
def submit_manual_correction(
    doc_id: str,
    correction: ManualCorrectionRequest,
    db: Session = Depends(get_db)
):
    """
    Allows human reviewers to modify extracted values, re-runs mathematical validation,
    and updates document status to COMPLETED if resolved.
    """
    doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
    if not doc or not doc.extraction:
        raise HTTPException(status_code=404, detail="Document or extraction record not found.")

    ext = doc.extraction
    audit_diff = {}

    # Only fields present in the request body are changed; an explicit null clears a field
    provided = correction.model_dump(exclude_unset=True)
    for field in ["invoice_number", "invoice_date", "supplier_name", "customer_name", "currency", "subtotal", "tax", "total"]:
        if field not in provided:
            continue
        new_val = provided[field]
        if isinstance(new_val, str):
            new_val = new_val.strip() or None
        old_val = getattr(ext, field)
        if old_val != new_val:
            setattr(ext, field, new_val)
            audit_diff[field] = {"old": old_val, "new": new_val}

    if correction.line_items is not None:
        audit_diff["line_items"] = {"old_count": len(ext.line_items), "new_count": len(correction.line_items)}
        for old_item in list(ext.line_items):
            db.delete(old_item)
        db.flush()
        for item in correction.line_items:
            db.add(LineItemModel(
                extraction_id=ext.id,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
                confidence=1.0
            ))

    # Human-verified values are fully trusted
    ext.overall_confidence = 1.0
    ext.confidence_scores = {k: 1.0 for k in (ext.confidence_scores or {})}
    db.flush()
    db.refresh(ext)

    # Re-validate with corrected values (including the stored line items if none were sent)
    current_schema = _extraction_to_schema(ext)
    ext.missing_fields = compute_missing_fields(current_schema)
    current_schema.missing_fields = ext.missing_fields
    val_res = FinancialValidator().validate(current_schema, db=db, current_doc_id=doc.id)

    db.query(ValidationErrorModel).filter(ValidationErrorModel.document_id == doc.id).delete()
    for err in val_res.errors:
        db.add(ValidationErrorModel(
            document_id=doc.id,
            rule_name=err.rule_name,
            severity=err.severity,
            field=err.field,
            message=err.message,
            expected_value=str(err.expected_value) if err.expected_value is not None else None,
            actual_value=str(err.actual_value) if err.actual_value is not None else None
        ))

    doc.status = "NEEDS_REVIEW" if val_res.requires_manual_review else "COMPLETED"

    db.add(AuditLogModel(
        document_id=doc.id,
        action="MANUAL_CORRECTION_APPLIED",
        changed_by="human_reviewer",
        details={
            "diff": audit_diff,
            "notes": correction.reviewer_notes,
            "new_status": doc.status
        }
    ))
    db.commit()
    db.refresh(doc)
    return serialize_document_response(doc, db)


# 6. Keyword and Semantic Hybrid Search
@router.post("/search")
def search_documents(payload: SearchQuerySchema, db: Session = Depends(get_db)):
    """
    Full-text keyword filtering and semantic search over all processed documents.
    """
    results = search_service.search(
        query=payload.query,
        db=db,
        search_type=payload.search_type,
        limit=payload.limit
    )
    return {"query": payload.query, "search_type": payload.search_type, "count": len(results), "results": results}


# 7. Cross-Verification Endpoint (PDF vs PDF / PDF vs Excel)
@router.post("/cross-verify", response_model=CrossVerificationResult)
def cross_verify_documents(
    payload: CrossVerificationRequest,
    db: Session = Depends(get_db)
):
    """
    Executes cross-verification between two documents.
    Supports PDF-to-PDF (e.g. Purchase Order vs Invoice) and PDF-to-Excel (Invoice vs Ledger).
    """
    doc_a = db.query(DocumentModel).filter(DocumentModel.id == payload.primary_doc_id).first()
    doc_b = db.query(DocumentModel).filter(DocumentModel.id == payload.reference_doc_id).first()

    if not doc_a or not doc_b:
        raise HTTPException(status_code=404, detail="One or both documents not found.")

    validator = FinancialValidator(tolerance=payload.tolerance)

    # Convert doc_a extraction to schema
    if not doc_a.extraction:
        raise HTTPException(status_code=400, detail="Primary document has no extracted data yet.")

    if payload.primary_doc_id == payload.reference_doc_id:
        raise HTTPException(status_code=400, detail="Select two different documents to cross-verify.")

    schema_a = _extraction_to_schema(doc_a.extraction)

    # Spreadsheet reference = ledger lookup, unless it is itself a single extracted invoice/PO
    is_single_record_sheet = bool(doc_b.extraction and doc_b.extraction.invoice_number)
    if doc_b.file_type in SPREADSHEET_TYPES and not is_single_record_sheet:
        try:
            df = _read_spreadsheet_all_sheets(doc_b.file_path, doc_b.file_type)
        except Exception as e:
            logger.error(f"Failed to read spreadsheet {doc_b.id} for cross check: {e}")
            raise HTTPException(status_code=422, detail="Reference spreadsheet could not be read.")
        if df.empty:
            raise HTTPException(status_code=422, detail="Reference spreadsheet has no rows.")
        return validator.cross_verify_pdf_excel(schema_a, df)
    else:
        # PDF-PDF cross check
        if not doc_b.extraction:
            raise HTTPException(status_code=400, detail="Reference document has no extracted data yet.")
        schema_b = _extraction_to_schema(doc_b.extraction)
        return validator.cross_verify_pdf_pdf(schema_a, schema_b)


# 8. Processing history (audit trail) for a document
@router.get("/documents/{doc_id}/history")
def get_document_history(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    logs = sorted(doc.audit_logs, key=lambda log: log.timestamp)
    return [
        {"action": log.action, "changed_by": log.changed_by, "details": log.details,
         "timestamp": log.timestamp.isoformat() if log.timestamp else None}
        for log in logs
    ]


# 9. Extracted raw text per page (for inspection / debugging OCR)
@router.get("/documents/{doc_id}/text")
def get_document_text(doc_id: str, db: Session = Depends(get_db)):
    doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return [
        {"page_number": pg.page_number, "ocr_applied": pg.ocr_applied, "confidence": pg.confidence, "text": pg.raw_text}
        for pg in sorted(doc.pages, key=lambda pg: pg.page_number)
    ]
