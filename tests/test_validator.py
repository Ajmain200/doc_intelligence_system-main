import pytest
import pandas as pd
from app.services.validator import FinancialValidator
from app.models.schemas import InvoiceExtractionSchema, LineItemSchema

@pytest.fixture
def validator():
    return FinancialValidator(tolerance=0.05)

def test_validation_passes_for_consistent_invoice(validator):
    invoice = InvoiceExtractionSchema(
        invoice_number="INV-100",
        invoice_date="2024-03-01",
        supplier_name="Alpha Supplies",
        customer_name="Beta Corp",
        currency="USD",
        subtotal=100.00,
        tax=10.00,
        total=110.00,
        line_items=[
            LineItemSchema(description="Item 1", quantity=2, unit_price=50.0, amount=100.0)
        ],
        overall_confidence=0.95
    )
    result = validator.validate(invoice)
    assert result.is_valid is True
    assert result.requires_manual_review is False
    assert len(result.errors) == 0

def test_validation_flags_math_inconsistency(validator):
    # Stated total 150.00 does not equal subtotal (100) + tax (10) = 110.00
    invoice = InvoiceExtractionSchema(
        invoice_number="INV-101",
        invoice_date="2024-03-01",
        supplier_name="Alpha Supplies",
        currency="USD",
        subtotal=100.00,
        tax=10.00,
        total=150.00,
        line_items=[
            LineItemSchema(description="Item 1", quantity=1, unit_price=100.0, amount=100.0)
        ]
    )
    result = validator.validate(invoice)
    assert result.is_valid is False
    assert result.requires_manual_review is True
    err_rules = [e.rule_name for e in result.errors]
    assert "CALCULATION_TAX_SUBTOTAL_TOTAL_MISMATCH" in err_rules

def test_validation_flags_line_item_sum_mismatch(validator):
    # Line items sum to 60.00, but stated subtotal is 100.00
    invoice = InvoiceExtractionSchema(
        invoice_number="INV-102",
        invoice_date="2024-03-01",
        supplier_name="Alpha Supplies",
        currency="USD",
        subtotal=100.00,
        tax=0.0,
        total=100.00,
        line_items=[
            LineItemSchema(description="Item 1", quantity=1, unit_price=60.0, amount=60.0)
        ]
    )
    result = validator.validate(invoice)
    assert result.is_valid is False
    assert any(e.rule_name == "LINE_ITEMS_SUBTOTAL_MISMATCH" for e in result.errors)

def test_cross_verify_pdf_pdf(validator):
    po = InvoiceExtractionSchema(
        invoice_number="PO-555",
        supplier_name="Vendor X",
        currency="USD",
        total=1200.00,
        line_items=[LineItemSchema(description="Part A", quantity=10, unit_price=120.0, amount=1200.0)]
    )
    inv = InvoiceExtractionSchema(
        invoice_number="INV-999",
        supplier_name="Vendor X",
        currency="USD",
        total=1200.00,
        line_items=[LineItemSchema(description="Part A", quantity=10, unit_price=120.0, amount=1200.0)]
    )
    res = validator.cross_verify_pdf_pdf(po, inv)
    assert res.match_status == "MATCH"
    assert len(res.discrepancies) == 0

def test_cross_verify_pdf_excel(validator):
    invoice = InvoiceExtractionSchema(
        invoice_number="INV-4040",
        total=750.00,
        supplier_name="Mega Supplies"
    )
    df_ledger = pd.DataFrame([
        {"Invoice_ID": "INV-4040", "Vendor": "Mega Supplies", "Total_Amount": 750.00},
        {"Invoice_ID": "INV-4041", "Vendor": "Other Co", "Total_Amount": 200.00}
    ])
    res = validator.cross_verify_pdf_excel(invoice, df_ledger)
    assert res.match_status == "MATCH"
    assert len(res.discrepancies) == 0
