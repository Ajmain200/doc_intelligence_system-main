import traceback
from pathlib import Path
from sqlalchemy.orm import Session

from app.models.database import (
    SessionLocal,
    DocumentModel,
    DocumentPageModel,
    ExtractedInvoiceModel,
    LineItemModel,
    ValidationErrorModel,
    AuditLogModel
)
from app.services.document_processor import DocumentProcessor
from app.services.ai_extractor import AIExtractor
from app.services.validator import FinancialValidator
from app.models.schemas import ValidationErrorDetail
from app.services.search_service import search_service
from app.core.logging import logger

def process_document_job(doc_id: str):
    """
    Task 4: Background processing pipeline.
    Orchestrates Document Processing (OCR/PDF/Excel) -> AI Extraction -> Data Validation -> Indexing.
    Handles failures, retries, and manual review routing.
    """
    db: Session = SessionLocal()
    try:
        doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
        if not doc:
            logger.error(f"Job failed: Document {doc_id} not found in database.")
            return

        doc.status = "PROCESSING"
        doc.error_message = None
        db.commit()

        # 1. Document Ingestion & Parsing
        processor = DocumentProcessor()
        file_path = Path(doc.file_path)
        logger.info(f"Starting processing for document {doc.filename} (ID: {doc.id})...")

        parsed_data = processor.process(file_path)
        doc.page_count = parsed_data.get("page_count", 1)

        # 2. Persist Page Records
        full_text_chunks = []
        # Clear any prior pages if reprocessing
        db.query(DocumentPageModel).filter(DocumentPageModel.document_id == doc.id).delete()
        
        for p in parsed_data.get("pages", []):
            page_obj = DocumentPageModel(
                document_id=doc.id,
                page_number=p["page_number"],
                raw_text=p["text"],
                ocr_applied=p.get("ocr_applied", False),
                confidence=p.get("confidence", 1.0)
            )
            db.add(page_obj)
            full_text_chunks.append(p["text"])

        full_document_text = "\n\n".join(full_text_chunks)
        page_warnings = sorted({p["warning"] for p in parsed_data.get("pages", []) if p.get("warning")})

        # 3. Index for Keyword & Semantic Search
        search_service.index_document(doc.id, f"{doc.filename} {full_document_text}")

        # 4. AI Information Extraction
        extractor = AIExtractor()
        extracted = extractor.extract(full_document_text, tables=parsed_data.get("tables"))

        # Clear prior extraction if reprocessing (ORM delete so line items cascade too)
        if doc.extraction is not None:
            db.delete(doc.extraction)
            db.flush()

        extracted_record = ExtractedInvoiceModel(
            document_id=doc.id,
            invoice_number=extracted.invoice_number,
            invoice_date=extracted.invoice_date,
            supplier_name=extracted.supplier_name,
            customer_name=extracted.customer_name,
            currency=extracted.currency,
            subtotal=extracted.subtotal,
            tax=extracted.tax,
            total=extracted.total,
            overall_confidence=extracted.overall_confidence,
            confidence_scores=extracted.confidence_scores,
            missing_fields=extracted.missing_fields,
            raw_summary=extracted.raw_summary
        )
        db.add(extracted_record)
        db.flush()

        for item in extracted.line_items:
            db.add(LineItemModel(
                extraction_id=extracted_record.id,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
                confidence=item.confidence
            ))

        # 5. Financial Validation & Sanity Rules
        validator = FinancialValidator()
        validation_res = validator.validate(extracted, db=db, current_doc_id=doc.id)

        # Clear prior validation errors
        db.query(ValidationErrorModel).filter(ValidationErrorModel.document_id == doc.id).delete()

        for warning in page_warnings:
            validation_res.errors.append(ValidationErrorDetail(
                rule_name="TEXT_EXTRACTION_WARNING",
                severity="WARNING",
                message=warning,
            ))
            validation_res.requires_manual_review = True

        for err in validation_res.errors:
            db.add(ValidationErrorModel(
                document_id=doc.id,
                rule_name=err.rule_name,
                severity=err.severity,
                field=err.field,
                message=err.message,
                expected_value=str(err.expected_value) if err.expected_value is not None else None,
                actual_value=str(err.actual_value) if err.actual_value is not None else None
            ))

        # 6. Audit Logging & Final Status
        if validation_res.requires_manual_review:
            doc.status = "NEEDS_REVIEW"
        else:
            doc.status = "COMPLETED"

        db.add(AuditLogModel(
            document_id=doc.id,
            action="AI_PROCESS_AND_VALIDATE",
            changed_by="worker_engine",
            details={
                "status": doc.status,
                "is_valid": validation_res.is_valid,
                "error_count": len(validation_res.errors),
                "confidence": extracted.overall_confidence,
                "extraction_method": extractor.last_method,
            }
        ))

        db.commit()
        logger.info(f"Finished processing document {doc.filename}. Final status: {doc.status}")

    except Exception as e:
        logger.error(f"Fatal background worker failure for doc {doc_id}: {traceback.format_exc()}")
        db.rollback()
        search_service.remove_document(doc_id)
        doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
        if doc:
            doc.status = "FAILED"
            doc.error_message = str(e)
            db.add(AuditLogModel(
                document_id=doc.id,
                action="JOB_FAILED",
                changed_by="worker_engine",
                details={"error": str(e), "traceback": traceback.format_exc()}
            ))
            db.commit()
    finally:
        db.close()
