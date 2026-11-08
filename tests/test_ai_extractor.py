import pytest
from app.services.ai_extractor import AIExtractor
from app.models.schemas import InvoiceExtractionSchema

@pytest.fixture
def extractor():
    # Uses deterministic fallback engine for reliable unit testing
    return AIExtractor(provider="heuristic_fallback")

def test_ai_extraction_standard_invoice(extractor):
    sample_text = """
    TAX INVOICE
    From: Global Tech Solutions Inc.
    Bill To: Apex Enterprises
    Invoice Number: INV-998822
    Date: 2024-04-15
    Currency: USD

    Items:
    Cloud Server Hosting  2  150.00  300.00
    Database Maintenance 1  200.00  200.00

    Subtotal: $500.00
    Tax: $50.00
    Total Amount: $550.00
    """
    res = extractor.extract(sample_text)

    assert isinstance(res, InvoiceExtractionSchema)
    assert res.invoice_number == "INV-998822"
    assert "Global Tech Solutions" in res.supplier_name
    assert res.subtotal == 500.00
    assert res.tax == 50.00
    assert res.total == 550.00
    assert len(res.line_items) == 2
    assert res.overall_confidence > 0.70

def test_zero_hallucination_for_missing_fields(extractor):
    # Text with missing tax, missing invoice number, missing line items
    sparse_text = """
    Receipt
    From: Downtown Cafe
    Total: $42.50
    """
    res = extractor.extract(sparse_text)

    assert res.invoice_number is None
    assert "invoice_number" in res.missing_fields
    assert res.subtotal is None
    assert res.tax is None
    assert res.total == 42.50
    # Guard against inventing values
    assert len(res.line_items) == 0

def test_empty_text_handling(extractor):
    res = extractor.extract("")
    assert res.overall_confidence == 0.0
    assert len(res.missing_fields) > 0
