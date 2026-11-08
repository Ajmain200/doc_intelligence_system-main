import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, ForeignKey, Boolean, JSON, create_engine, event
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from app.config import settings

Base = declarative_base()

def generate_uuid() -> str:
    return str(uuid.uuid4())

class DocumentModel(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size_bytes = Column(Integer, default=0)
    page_count = Column(Integer, default=1)
    status = Column(String(50), default="QUEUED", index=True) # QUEUED, PROCESSING, COMPLETED, FAILED, NEEDS_REVIEW
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    pages = relationship("DocumentPageModel", back_populates="document", cascade="all, delete-orphan")
    extraction = relationship("ExtractedInvoiceModel", back_populates="document", uselist=False, cascade="all, delete-orphan")
    validation_errors = relationship("ValidationErrorModel", back_populates="document", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLogModel", back_populates="document", cascade="all, delete-orphan")

class DocumentPageModel(Base):
    __tablename__ = "document_pages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    raw_text = Column(Text, default="")
    ocr_applied = Column(Boolean, default=False)
    confidence = Column(Float, default=1.0)

    document = relationship("DocumentModel", back_populates="pages")

class ExtractedInvoiceModel(Base):
    __tablename__ = "extracted_invoices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False)
    invoice_number = Column(String(100), index=True, nullable=True)
    invoice_date = Column(String(50), nullable=True)
    supplier_name = Column(String(255), index=True, nullable=True)
    customer_name = Column(String(255), nullable=True)
    currency = Column(String(20), nullable=True)
    subtotal = Column(Float, nullable=True)
    tax = Column(Float, nullable=True)
    total = Column(Float, nullable=True)
    overall_confidence = Column(Float, default=1.0)
    confidence_scores = Column(JSON, default=dict)
    missing_fields = Column(JSON, default=list)
    raw_summary = Column(Text, nullable=True)

    document = relationship("DocumentModel", back_populates="extraction")
    line_items = relationship("LineItemModel", back_populates="extraction", cascade="all, delete-orphan")

class LineItemModel(Base):
    __tablename__ = "line_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    extraction_id = Column(String(36), ForeignKey("extracted_invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(String(500), nullable=True)
    quantity = Column(Float, nullable=True)
    unit_price = Column(Float, nullable=True)
    amount = Column(Float, nullable=True)
    confidence = Column(Float, default=1.0)

    extraction = relationship("ExtractedInvoiceModel", back_populates="line_items")

class ValidationErrorModel(Base):
    __tablename__ = "validation_errors"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_name = Column(String(100), nullable=False)
    severity = Column(String(20), default="ERROR") # ERROR, WARNING
    field = Column(String(100), nullable=True)
    message = Column(Text, nullable=False)
    expected_value = Column(String(255), nullable=True)
    actual_value = Column(String(255), nullable=True)
    is_resolved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("DocumentModel", back_populates="validation_errors")

class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(100), nullable=False)  # 'UPLOAD', 'AI_EXTRACT', 'AUTO_VALIDATE', 'MANUAL_CORRECT', 'REPROCESS'
    changed_by = Column(String(100), default="system")
    details = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=datetime.utcnow)

    document = relationship("DocumentModel", back_populates="audit_logs")

# Database engine & session setup
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")   # enforce ON DELETE CASCADE
        cursor.execute("PRAGMA journal_mode=WAL")  # API reads while the worker writes
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
