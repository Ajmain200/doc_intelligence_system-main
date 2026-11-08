import pytest
import os
import io
import csv
from pathlib import Path
from PIL import Image
import pandas as pd

from app.services.document_processor import DocumentProcessor
from app.core.exceptions import CorruptedFileError, DocumentProcessingError

@pytest.fixture
def processor():
    return DocumentProcessor()

@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path

def test_unsupported_file_extension(processor, tmp_dir):
    bad_file = tmp_dir / "test.exe"
    bad_file.write_text("dummy")
    with pytest.raises(DocumentProcessingError):
        processor.process(bad_file)

def test_corrupted_empty_file(processor, tmp_dir):
    empty_file = tmp_dir / "empty.pdf"
    empty_file.touch()
    with pytest.raises(CorruptedFileError):
        processor.process(empty_file)

def test_csv_processing(processor, tmp_dir):
    csv_file = tmp_dir / "sample_invoice.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["InvoiceNumber", "Date", "Supplier", "Total"])
        writer.writerow(["INV-2024-001", "2024-05-10", "Acme Supplies", "1250.00"])

    result = processor.process(csv_file)
    assert result["page_count"] == 1
    assert "INV-2024-001" in result["pages"][0]["text"]
    assert "Acme Supplies" in result["pages"][0]["text"]

def test_excel_multi_sheet_processing(processor, tmp_dir):
    excel_path = tmp_dir / "multi_sheet.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df1 = pd.DataFrame({"Item": ["Widget A", "Widget B"], "Price": [10.0, 20.0]})
        df2 = pd.DataFrame({"Vendor": ["Global Corp"], "Balance": [500.0]})
        df1.to_excel(writer, sheet_name="Invoices", index=False)
        df2.to_excel(writer, sheet_name="Ledger", index=False)

    result = processor.process(excel_path)
    assert result["page_count"] == 2
    assert "Invoices" in result["sheets"]
    assert "Ledger" in result["sheets"]

def test_image_preprocessing(processor, tmp_dir):
    img_path = tmp_dir / "test_scan.png"
    # Create simple 100x100 RGB image
    img = Image.new("RGB", (100, 100), color="white")
    img.save(img_path)

    result = processor.process(img_path)
    assert result["page_count"] == 1
    assert "pages" in result
