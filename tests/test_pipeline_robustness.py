"""Processing, OCR-fallback, spreadsheet mapping and extraction-safety tests."""
import pandas as pd
import pytest
from PIL import Image

import app.services.document_processor as dp
from app.core.exceptions import CorruptedFileError
from app.services.ai_extractor import AIExtractor, to_float
from app.services.document_processor import DocumentProcessor
from tests.pdf_utils import make_text_pdf, INVOICE_LINES


@pytest.fixture
def processor():
    return DocumentProcessor()


@pytest.fixture
def extractor():
    return AIExtractor(provider="heuristic_fallback")


@pytest.fixture
def no_tesseract(monkeypatch):
    monkeypatch.setattr(dp, "tesseract_available", lambda: False)


# ---------------------------------------------------------------- PDFs
def test_digital_pdf_text_extraction(processor, extractor, tmp_path):
    pdf = make_text_pdf(tmp_path / "invoice.pdf", INVOICE_LINES)
    result = processor.process(pdf)
    assert result["page_count"] == 1
    page = result["pages"][0]
    assert page["ocr_applied"] is False
    assert "NW-2024-0042" in page["text"]

    ext = extractor.extract(page["text"])
    assert ext.invoice_number == "NW-2024-0042"
    assert ext.supplier_name == "Northwind Traders Ltd"
    assert ext.customer_name == "Contoso Retail"
    assert (ext.subtotal, ext.tax, ext.total) == (200.0, 20.0, 220.0)
    assert ext.currency == "USD"
    assert len(ext.line_items) == 2


def test_scanned_pdf_without_ocr_engine_yields_no_fake_text(processor, tmp_path, no_tesseract):
    pdf_path = tmp_path / "scan.pdf"
    Image.new("RGB", (400, 400), color="white").save(pdf_path)  # image-only PDF
    result = processor.process(pdf_path)
    page = result["pages"][0]
    assert page["text"] == ""  # previously a placeholder string was injected here
    assert "Tesseract" in page.get("warning", "")


def test_corrupted_pdf_raises(processor, tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"this is not a pdf at all" * 10)
    with pytest.raises(CorruptedFileError):
        processor.process(bad)


def test_corrupted_image_raises(processor, tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage" * 20)
    with pytest.raises(CorruptedFileError):
        processor.process(bad)


def test_image_without_ocr_engine_returns_empty_text(processor, tmp_path, no_tesseract):
    img = tmp_path / "receipt.jpg"
    Image.new("RGB", (200, 200), color="white").save(img)
    page = processor.process(img)["pages"][0]
    assert page["text"] == ""
    assert page["ocr_applied"] is False


def test_multi_frame_tiff_pages(processor, tmp_path, no_tesseract):
    tif = tmp_path / "multi.tiff"
    frames = [Image.new("RGB", (50, 50), color=c) for c in ("white", "gray", "black")]
    frames[0].save(tif, save_all=True, append_images=frames[1:])
    assert processor.process(tif)["page_count"] == 3


def test_file_size_limit(processor, tmp_path, monkeypatch):
    monkeypatch.setattr(dp.settings, "MAX_FILE_SIZE_MB", 0)
    f = tmp_path / "x.csv"
    f.write_text("a,b\n1,2\n")
    with pytest.raises(dp.DocumentProcessingError):
        processor.process(f)


# --------------------------------------------------------- Spreadsheets
def test_csv_invoice_is_mapped_from_columns(processor, extractor, tmp_path):
    f = tmp_path / "inv.csv"
    f.write_text("InvoiceNumber,Date,Supplier,Customer,Currency,Subtotal,Tax,Total\n"
                 "INV-2024-001,2024-03-15,Apex Logistics,Global Corp,USD,\"1,000.00\",100.00,1100.00\n")
    parsed = processor.process(f)
    ext = extractor.extract(parsed["pages"][0]["text"], tables=parsed["tables"])
    assert ext.invoice_number == "INV-2024-001"
    assert ext.supplier_name == "Apex Logistics"
    assert ext.customer_name == "Global Corp"
    assert (ext.subtotal, ext.tax, ext.total) == (1000.0, 100.0, 1100.0)
    assert ext.missing_fields == []


def test_ledger_with_many_invoices_is_not_collapsed_into_one(processor, extractor, tmp_path):
    f = tmp_path / "ledger.csv"
    f.write_text("Invoice_ID,Vendor,Total_Amount\nINV-1,A,10\nINV-2,B,20\n")
    parsed = processor.process(f)
    ext = extractor.extract(parsed["pages"][0]["text"], tables=parsed["tables"])
    assert ext.invoice_number is None and ext.total is None
    assert "ledger" in ext.raw_summary.lower()


def test_excel_line_item_sheet(processor, extractor, tmp_path):
    path = tmp_path / "items.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame([["Invoice Number", "INV-77"], ["Supplier", "Delta Parts"], ["Total", 330]],
                     columns=["Field", "Value"]).to_excel(writer, sheet_name="Header", index=False)
        pd.DataFrame({"Description": ["Bolt", "Nut"], "Qty": [10, 20], "Unit Price": [3.0, 1.5],
                      "Amount": [30.0, 30.0]}).to_excel(writer, sheet_name="Items", index=False)
    parsed = processor.process(path)
    ext = extractor.extract("", tables=parsed["tables"])
    assert ext.invoice_number == "INV-77"
    assert ext.supplier_name == "Delta Parts"
    assert ext.total == 330.0
    assert [li.description for li in ext.line_items] == ["Bolt", "Nut"]


def test_non_invoice_spreadsheet_does_not_invent_supplier(processor, extractor, tmp_path):
    f = tmp_path / "people.csv"
    f.write_text("ID,Gender,Income\n1,F,40000\n2,M,30000\n")
    parsed = processor.process(f)
    ext = extractor.extract(parsed["pages"][0]["text"], tables=parsed["tables"])
    assert ext.supplier_name is None
    assert ext.currency is None


# ------------------------------------------------------ Extraction safety
def test_currency_is_not_defaulted(extractor):
    ext = extractor.extract("Invoice Number: A-1\nFrom: Foo Corp\nTotal: 50.00")
    assert ext.currency is None
    assert "currency" in ext.missing_fields


def test_header_line_is_not_used_as_supplier(extractor):
    ext = extractor.extract("--- Sheet: Data ---\nfoo,bar\n1,2")
    assert ext.supplier_name is None


def test_to_float_parsing():
    assert to_float("$1,234.50") == 1234.5
    assert to_float("(12.00)") == -12.0
    assert to_float("n/a") is None
    assert to_float(None) is None


def test_llm_output_is_normalized_without_inventing(extractor):
    ext = extractor._normalize_llm_output({
        "invoice_number": " INV-9 ", "supplier_name": "", "total": "1,100.00", "tax": None,
        "line_items": [{"description": "Svc", "amount": "100"}, "junk"],
        "confidence_scores": {"total": 95, "invoice_number": "bad"},
        "overall_confidence": 1.7,
    })
    assert ext.invoice_number == "INV-9"
    assert ext.supplier_name is None
    assert ext.total == 1100.0
    assert len(ext.line_items) == 1
    assert ext.confidence_scores == {"total": 0.95}
    assert ext.overall_confidence == 1.0
    assert "supplier_name" in ext.missing_fields and "tax" in ext.missing_fields


def test_llm_failure_falls_back_to_heuristic(monkeypatch):
    ex = AIExtractor(provider="gemini")
    ex.gemini_key = "test-key"

    def boom(_text):
        raise RuntimeError("network down")

    monkeypatch.setattr(ex, "_extract_with_gemini", boom)
    res = ex.extract("Invoice Number: Z-1\nTotal: $5.00")
    assert ex.last_method == "heuristic"
    assert res.invoice_number == "Z-1"
