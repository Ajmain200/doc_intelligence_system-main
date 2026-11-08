from typing import List, Optional, Dict, Any
from datetime import datetime

try:
    from pydantic import BaseModel, Field
except ImportError:
    def Field(default=None, default_factory=None, **kwargs):
        if default_factory is not None:
            return default_factory()
        return default

    class BaseModel:
        def __init__(self, **kwargs):
            # Collect defaults from class annotations / attributes
            for k in dir(self.__class__):
                if not k.startswith("_"):
                    v = getattr(self.__class__, k, None)
                    if not callable(v):
                        setattr(self, k, v)
            for k, v in kwargs.items():
                setattr(self, k, v)

        def dict(self, *args, **kwargs):
            return {k: getattr(self, k) for k in self.__dict__ if not k.startswith("_")}

        def model_dump(self, *args, **kwargs):
            return self.dict()

class LineItemSchema(BaseModel):
    description: Optional[str] = Field(None, description="Item or service description")
    quantity: Optional[float] = Field(None, description="Quantity billed")
    unit_price: Optional[float] = Field(None, description="Price per individual unit")
    amount: Optional[float] = Field(None, description="Total amount for this line item")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score 0.0 - 1.0")

class InvoiceExtractionSchema(BaseModel):
    invoice_number: Optional[str] = Field(None, description="Unique invoice identifier or code")
    invoice_date: Optional[str] = Field(None, description="Invoice date in YYYY-MM-DD or standard format")
    supplier_name: Optional[str] = Field(None, description="Supplier or vendor issuing the invoice")
    customer_name: Optional[str] = Field(None, description="Customer or billed entity")
    currency: Optional[str] = Field(None, description="Currency ISO code or symbol, e.g., USD, EUR, $")
    subtotal: Optional[float] = Field(None, description="Net amount before taxes")
    tax: Optional[float] = Field(None, description="Tax amount or VAT")
    total: Optional[float] = Field(None, description="Final gross payable amount")
    line_items: List[LineItemSchema] = Field(default_factory=list, description="Itemized billing rows")
    
    # Metadata & Hallucination Prevention
    missing_fields: List[str] = Field(default_factory=list, description="Explicit list of absent fields")
    confidence_scores: Dict[str, float] = Field(default_factory=dict, description="Field-level confidence scores")
    overall_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    raw_summary: Optional[str] = Field(None, description="Brief summary of document content")

class ValidationErrorDetail(BaseModel):
    rule_name: str
    severity: str  # 'ERROR' or 'WARNING'
    field: Optional[str] = None
    message: str
    expected_value: Optional[Any] = None
    actual_value: Optional[Any] = None

class ValidationResultSchema(BaseModel):
    is_valid: bool
    requires_manual_review: bool
    errors: List[ValidationErrorDetail] = Field(default_factory=list)
    math_checks: Dict[str, Any] = Field(default_factory=dict)
    duplicate_detected: bool = False

class DocumentResponseSchema(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size_bytes: int
    page_count: int
    status: str  # 'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED', 'NEEDS_REVIEW'
    error_message: Optional[str] = None
    extracted_data: Optional[InvoiceExtractionSchema] = None
    validation_result: Optional[ValidationResultSchema] = None
    created_at: datetime
    updated_at: datetime

class ManualCorrectionRequest(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    supplier_name: Optional[str] = None
    customer_name: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    line_items: Optional[List[LineItemSchema]] = None
    reviewer_notes: Optional[str] = None

class CrossVerificationRequest(BaseModel):
    primary_doc_id: str
    reference_doc_id: str  # e.g., PDF PO vs PDF Invoice, or PDF Invoice vs Excel Sheet
    tolerance: float = 0.05

class CrossVerificationResult(BaseModel):
    match_status: str  # 'MATCH', 'MISMATCH', 'PARTIAL_MATCH'
    discrepancies: List[Dict[str, Any]]
    confidence: float
    summary: str

class SearchQuerySchema(BaseModel):
    query: str
    search_type: str = "hybrid"  # 'keyword', 'semantic', 'hybrid'
    limit: int = 10
