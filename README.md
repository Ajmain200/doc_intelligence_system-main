# AI-Powered Document Intelligence & Reconciliation System

An enterprise-grade document intelligence platform designed to process thousands of multi-format business documents daily (PDFs up to 1000 pages, scanned images, Excel workbooks, and CSV files), extract structured financial invoice details, execute automated mathematical validation, and perform cross-document reconciliation (PDF-to-PDF & PDF-to-Excel).

---

## 1. System Architecture

```mermaid
flowchart TD
    subgraph Ingestion["Task 1: Universal Document Ingestion"]
        Upload[Multi-Format Upload<br/>PDF, JPG, PNG, TIFF, XLSX, CSV] --> TypeRouter{Format Router}
        TypeRouter -->|1000-page PDF| Streamer[Stream Chunk Generator<br/>Batch size: 15 pages]
        TypeRouter -->|Scanned / Image| Preprocessor[Image Preprocessor<br/>Deskew, Grayscale, Denoise, Binarize]
        Preprocessor --> OCR[OCR Engine<br/>PyTesseract]
        TypeRouter -->|Spreadsheets| SheetParser[Multi-Sheet Excel / CSV<br/>OpenPyXL / Pandas]
    end

    subgraph Extraction["Task 2: AI Information Extraction"]
        Streamer & OCR & SheetParser --> Aggregator[Text Aggregator]
        Aggregator --> LLMExtractor[Zero-Hallucination AI Extractor<br/>Gemini / OpenAI / Heuristic]
        LLMExtractor --> StrictSchema[Strict Pydantic JSON Schema<br/>Confidence Scores + Provenance]
    end

    subgraph Validation["Task 3: Validation & Reconciliation"]
        StrictSchema --> RulesEngine[Financial Validation Engine]
        RulesEngine --> MathCheck["Math Consistency<br/>Line Items Sum == Subtotal<br/>Subtotal + Tax == Total"]
        RulesEngine --> DupCheck["Duplicate Invoice Detection<br/>DB (Vendor + Invoice #)"]
        RulesEngine --> CrossRecon["Cross-Verification Studio<br/>PDF-PDF (PO vs Invoice)<br/>PDF-Excel (Invoice vs Ledger)"]
    end

    subgraph StorageSearch["Task 5: Storage & Hybrid Search"]
        MathCheck & DupCheck --> SQLiteDB[(Relational DB<br/>SQLAlchemy Documents, Pages, Audit)]
        Aggregator --> VectorIndex[(Hybrid Search Engine<br/>FTS Keyword + Dense Embeddings)]
    end

    subgraph Presentation["Task 4 & 6: API & UI Dashboard"]
        SQLiteDB & VectorIndex --> FastAPI[FastAPI REST API<br/>Async Background Workers]
        FastAPI --> ReactUI[Modern React / Tailwind Dashboard<br/>Upload, Track, Review, Cross-Verify, Search]
    end
```

---

## 2. Database Schema (ER Diagram)

```mermaid
erDiagram
    DOCUMENTS ||--o{ DOCUMENT_PAGES : "contains"
    DOCUMENTS ||--o| EXTRACTED_INVOICES : "has"
    DOCUMENTS ||--o{ VALIDATION_ERRORS : "flags"
    DOCUMENTS ||--o{ AUDIT_LOGS : "tracks"
    EXTRACTED_INVOICES ||--o{ LINE_ITEMS : "itemizes"

    DOCUMENTS {
        string id PK
        string filename
        string file_type
        int file_size_bytes
        int page_count
        string status
        string error_message
        datetime created_at
        datetime updated_at
    }

    DOCUMENT_PAGES {
        string id PK
        string document_id FK
        int page_number
        text raw_text
        boolean ocr_applied
        float confidence
    }

    EXTRACTED_INVOICES {
        string id PK
        string document_id FK
        string invoice_number
        string invoice_date
        string supplier_name
        string customer_name
        string currency
        float subtotal
        float tax
        float total
        float overall_confidence
        json confidence_scores
        json missing_fields
        text raw_summary
    }

    LINE_ITEMS {
        string id PK
        string extraction_id FK
        string description
        float quantity
        float unit_price
        float amount
        float confidence
    }

    VALIDATION_ERRORS {
        string id PK
        string document_id FK
        string rule_name
        string severity
        string field
        text message
        string expected_value
        string actual_value
        boolean is_resolved
        datetime created_at
    }

    AUDIT_LOGS {
        string id PK
        string document_id FK
        string action
        string changed_by
        json details
        datetime timestamp
    }
```

---

## 3. Benchmark Evaluation Results

Evaluated against the labeled financial test dataset in `evaluation/benchmark_dataset.json`:

| Metric | Result | Target Standard |
| :--- | :--- | :--- |
| **Total Test Documents** | 4 | Diverse multi-format set |
| **Document Success Rate** | **100.0%** | > 95% |
| **Document Failure Rate** | **0.0%** | < 5% |
| **Average Processing Time** | **1.19 ms / doc** | < 1000 ms |
| **Overall Extraction Accuracy** | **100.00%** | > 90% |
| **Invoice Number Accuracy** | **100.0%** (3/3) | Strict matching |
| **Invoice Date Accuracy** | **100.0%** (3/3) | Date normalization |
| **Supplier Name Accuracy** | **100.0%** (4/4) | Entity recognition |
| **Subtotal Accuracy** | **100.0%** (3/3) | Exact numeric match |
| **Tax Amount Accuracy** | **100.0%** (3/3) | Exact numeric match |
| **Total Amount Accuracy** | **100.0%** (4/4) | Exact numeric match |
| **Line Items Count Accuracy** | **100.0%** (4/4) | Full item breakdown |

---

## 4. REST API Endpoints Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/v1/documents/upload` | Multi-file upload (`PDF, PNG, JPG, TIFF, XLSX, CSV`) with async queueing |
| `GET` | `/api/v1/documents` | List all documents with status filtering (`QUEUED`, `PROCESSING`, `COMPLETED`, `NEEDS_REVIEW`, `FAILED`) |
| `GET` | `/api/v1/documents/{id}` | Retrieve document status, extracted structured fields, and validation errors |
| `PATCH` | `/api/v1/documents/{id}/correct` | Submit human reviewer corrections, re-runs mathematical validation rules |
| `POST` | `/api/v1/documents/{id}/reprocess` | Reprocess a failed or flagged document |
| `POST` | `/api/v1/cross-verify` | Execute PDF-PDF (PO vs Invoice) or PDF-Excel (Invoice vs Ledger) cross-reconciliation |
| `POST` | `/api/v1/search` | Execute Keyword, Semantic, or Hybrid Vector search across document texts |
| `DELETE` | `/api/v1/documents/{id}` | Delete one document (DB records, search entry and uploaded file) |
| `DELETE` | `/api/v1/documents?confirm=true` | Clear all documents (documents still processing are kept) |
| `GET` | `/api/v1/documents/{id}/history` | Processing history / audit trail for a document |
| `GET` | `/api/v1/documents/{id}/text` | Raw extracted text per page (digital or OCR) |
| `GET` | `/health` | System health check and version metadata |

---

## 5. Quick Start Instructions

### 0. Prerequisites
- Python 3.11+ and Node.js 18+
- **Tesseract OCR** (needed for scanned PDFs and images; without it those files produce no text
  and are flagged `TEXT_EXTRACTION_WARNING` for manual review):
  - Windows: install from https://github.com/UB-Mannheim/tesseract/wiki, then set
    `TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"` in `.env` if it is not on PATH
  - macOS: `brew install tesseract` · Ubuntu: `sudo apt install tesseract-ocr`

### 1. Install backend dependencies
```bash
python -m venv venv
venv\Scripts\activate          # Windows  (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env
```
Set `GEMINI_API_KEY` (or `LLM_PROVIDER="openai"` + `OPENAI_API_KEY`) in `.env` for LLM extraction.
With no key the system uses the offline rule-based extractor. Spreadsheets with invoice-style
columns are always mapped deterministically, without the LLM.

### 2. Run Automated Tests
```bash
pytest tests/ -v
```
Tests use a temporary database and uploads folder, so they never touch `doc_intelligence.db`.

### 3. Run Benchmark Evaluation
```bash
python evaluation/evaluate.py
```
Note: the benchmark currently scores the text extractor on 4 labeled text samples. It does not yet
run real PDF / image / spreadsheet files through the full pipeline.

### 4. Start Backend REST API
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# Interactive Swagger API Docs at: http://localhost:8000/docs
```

### 5. Start Frontend Dashboard
```bash
cd frontend
npm install
npm --prefix frontend run dev
# Dashboard opens at: http://localhost:5173
```

### 6. Try it with the sample files
Upload everything in `sample_data/` from the dashboard. `sample_invoice.pdf` and `sample_invoice.csv`
are the same invoice (so the second one is flagged as a duplicate); cross-verify the PDF against
`accounting_ledger.csv` (PDF-to-Excel) or `purchase_order.csv` (invoice vs PO).
