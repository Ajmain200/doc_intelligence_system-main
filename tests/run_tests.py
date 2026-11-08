import sys
import unittest
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_extractor import AIExtractor
from app.services.validator import FinancialValidator
from app.models.schemas import InvoiceExtractionSchema, LineItemSchema

class TestAIExtractionAndValidation(unittest.TestCase):
    def setUp(self):
        self.extractor = AIExtractor(provider="heuristic_fallback")
        self.validator = FinancialValidator(tolerance=0.05)

    def test_standard_invoice_extraction(self):
        sample = """
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
        res = self.extractor.extract(sample)
        self.assertEqual(res.invoice_number, "INV-998822")
        self.assertEqual(res.subtotal, 500.00)
        self.assertEqual(res.tax, 50.00)
        self.assertEqual(res.total, 550.00)
        self.assertEqual(len(res.line_items), 2)

    def test_zero_hallucination_for_sparse_receipt(self):
        sample = "Coffee Shop Receipt\nSupplier: Joe's Cafe\nTotal: $6.50"
        res = self.extractor.extract(sample)
        self.assertIsNone(res.invoice_number)
        self.assertIn("invoice_number", res.missing_fields)
        self.assertEqual(res.total, 6.50)
        self.assertEqual(len(res.line_items), 0)

    def test_validator_detects_math_inconsistency(self):
        # 100 subtotal + 10 tax != 180 total
        bad_inv = InvoiceExtractionSchema(
            invoice_number="INV-BAD-MATH",
            invoice_date="2024-01-01",
            supplier_name="Acme",
            currency="USD",
            subtotal=100.00,
            tax=10.00,
            total=180.00,
            line_items=[LineItemSchema(description="Item", quantity=1, unit_price=100.0, amount=100.0)]
        )
        res = self.validator.validate(bad_inv)
        self.assertFalse(res.is_valid)
        self.assertTrue(res.requires_manual_review)
        rule_names = [e.rule_name for e in res.errors]
        self.assertIn("CALCULATION_TAX_SUBTOTAL_TOTAL_MISMATCH", rule_names)

    def test_validator_cross_verify_pdf_pdf(self):
        po = InvoiceExtractionSchema(
            invoice_number="PO-100",
            supplier_name="Vendor A",
            currency="USD",
            total=500.00,
            line_items=[LineItemSchema(description="Part", quantity=5, unit_price=100.0, amount=500.0)]
        )
        inv = InvoiceExtractionSchema(
            invoice_number="INV-200",
            supplier_name="Vendor A",
            currency="USD",
            total=500.00,
            line_items=[LineItemSchema(description="Part", quantity=5, unit_price=100.0, amount=500.0)]
        )
        cross_res = self.validator.cross_verify_pdf_pdf(po, inv)
        self.assertEqual(cross_res.match_status, "MATCH")
        self.assertEqual(len(cross_res.discrepancies), 0)

if __name__ == "__main__":
    unittest.main()
