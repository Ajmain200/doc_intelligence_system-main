"""End-to-end API workflows. TestClient runs background tasks before returning."""
import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.services.search_service import search_service
from tests.pdf_utils import make_text_pdf, INVOICE_LINES

INVOICE_CSV = (
    "InvoiceNumber,Date,Supplier,Customer,Currency,Subtotal,Tax,Total\n"
    "{num},2024-03-15,Apex Logistics,Global Corp,USD,1000.00,100.00,{total}\n"
)
LEDGER_CSV = "Invoice_ID,Date,Vendor,Total_Amount\n{num},2024-03-15,Apex Logistics,1100.00\nOTHER-1,2024-03-16,X,5\n"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # runs lifespan (init_db + index rebuild)
        yield c


def upload(client, name, content: bytes, mime="text/csv"):
    res = client.post("/api/v1/documents/upload", files=[("files", (name, io.BytesIO(content), mime))])
    assert res.status_code == 200, res.text
    return client.get(f"/api/v1/documents/{res.json()[0]['id']}").json()


def test_csv_upload_is_processed_end_to_end(client):
    doc = upload(client, "inv_e2e.csv", INVOICE_CSV.format(num="E2E-1", total="1100.00").encode())
    assert doc["status"] in ("COMPLETED", "NEEDS_REVIEW")
    ext = doc["extracted_data"]
    assert ext["invoice_number"] == "E2E-1"
    assert ext["total"] == 1100.0
    assert doc["validation_result"]["math_checks"]["expected_total"] == 1100.0


def test_pdf_upload_is_processed_end_to_end(client, tmp_path):
    pdf = make_text_pdf(tmp_path / "nw.pdf", INVOICE_LINES)
    doc = upload(client, "nw.pdf", pdf.read_bytes(), "application/pdf")
    assert doc["status"] == "COMPLETED", doc["validation_result"]
    assert doc["extracted_data"]["invoice_number"] == "NW-2024-0042"
    assert len(doc["extracted_data"]["line_items"]) == 2


def test_math_error_flags_review_and_correction_resolves_it(client):
    doc = upload(client, "bad_math.csv", INVOICE_CSV.format(num="MATH-1", total="999.00").encode())
    assert doc["status"] == "NEEDS_REVIEW"
    rules = [e["rule_name"] for e in doc["validation_result"]["errors"]]
    assert "CALCULATION_TAX_SUBTOTAL_TOTAL_MISMATCH" in rules

    res = client.patch(f"/api/v1/documents/{doc['id']}/correct", json={"total": 1100.0})
    assert res.status_code == 200
    fixed = res.json()
    rules = [e["rule_name"] for e in fixed["validation_result"]["errors"]]
    assert "CALCULATION_TAX_SUBTOTAL_TOTAL_MISMATCH" not in rules
    assert fixed["extracted_data"]["total"] == 1100.0

    history = client.get(f"/api/v1/documents/{doc['id']}/history").json()
    assert [h["action"] for h in history][-1] == "MANUAL_CORRECTION_APPLIED"


def test_correction_without_line_items_keeps_existing_items(client, tmp_path):
    pdf = make_text_pdf(tmp_path / "keep.pdf", [l.replace("NW-2024-0042", "KEEP-1") for l in INVOICE_LINES])
    doc = upload(client, "keep.pdf", pdf.read_bytes(), "application/pdf")
    # Change only the subtotal: the line-item check must still run against stored items
    fixed = client.patch(f"/api/v1/documents/{doc['id']}/correct", json={"subtotal": 150.0}).json()
    assert len(fixed["extracted_data"]["line_items"]) == 2
    rules = [e["rule_name"] for e in fixed["validation_result"]["errors"]]
    assert "LINE_ITEMS_SUBTOTAL_MISMATCH" in rules


def test_duplicate_invoice_detected(client):
    upload(client, "dup_a.csv", INVOICE_CSV.format(num="DUP_7", total="1100.00").encode())
    second = upload(client, "dup_b.csv", INVOICE_CSV.format(num="DUP_7", total="1100.00").encode())
    assert second["validation_result"]["duplicate_detected"] is True
    assert second["status"] == "NEEDS_REVIEW"


def test_underscore_is_not_a_wildcard_in_duplicate_check(client):
    upload(client, "wild_a.csv", INVOICE_CSV.format(num="WILD_9", total="1100.00").encode())
    other = upload(client, "wild_b.csv", INVOICE_CSV.format(num="WILDX9", total="1100.00").encode())
    assert other["validation_result"]["duplicate_detected"] is False


def test_corrupted_file_fails_and_can_be_reprocessed(client):
    doc = upload(client, "broken.pdf", b"not a pdf" * 20, "application/pdf")
    assert doc["status"] == "FAILED"
    assert doc["error_message"]
    res = client.post(f"/api/v1/documents/{doc['id']}/reprocess")
    assert res.status_code == 200
    assert client.get(f"/api/v1/documents/{doc['id']}").json()["status"] == "FAILED"


def test_filename_path_traversal_is_neutralized(client):
    res = client.post("/api/v1/documents/upload",
                      files=[("files", ("../../evil.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv"))])
    assert res.status_code == 200
    assert res.json()[0]["filename"] == "evil.csv"
    assert not (settings.STORAGE_DIR.parent / "evil.csv").exists()


def test_batch_with_unsupported_file_writes_nothing(client):
    before = set(settings.STORAGE_DIR.iterdir())
    res = client.post("/api/v1/documents/upload", files=[
        ("files", ("ok.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")),
        ("files", ("bad.exe", io.BytesIO(b"MZ"), "application/octet-stream")),
    ])
    assert res.status_code == 400
    assert set(settings.STORAGE_DIR.iterdir()) == before


def test_oversized_upload_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_MB", 0)
    res = client.post("/api/v1/documents/upload",
                      files=[("files", ("big.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv"))])
    assert res.status_code == 413


def test_cross_verify_invoice_against_ledger(client):
    inv = upload(client, "xv_inv.csv", INVOICE_CSV.format(num="XV-100", total="1100.00").encode())
    ledger = upload(client, "xv_ledger.csv", LEDGER_CSV.format(num="XV-100").encode())
    res = client.post("/api/v1/cross-verify", json={"primary_doc_id": inv["id"], "reference_doc_id": ledger["id"]})
    assert res.status_code == 200, res.text
    assert res.json()["match_status"] == "MATCH"

    # Substring of another invoice number must not match (XV-10 vs XV-100)
    inv2 = upload(client, "xv_inv2.csv", INVOICE_CSV.format(num="XV-10", total="1100.00").encode())
    res = client.post("/api/v1/cross-verify", json={"primary_doc_id": inv2["id"], "reference_doc_id": ledger["id"]})
    assert res.json()["match_status"] == "MISMATCH"


def test_search_finds_page_text_after_index_rebuild(client, tmp_path):
    pdf = make_text_pdf(tmp_path / "s.pdf", INVOICE_LINES[:2] + ["Invoice Number: SRCH-1", "Quantum flux capacitor", "Total: USD 9.00"])
    doc = upload(client, "search_me.pdf", pdf.read_bytes(), "application/pdf")

    search_service._vector_index.clear()  # simulate a server restart
    search_service._loaded = False

    for mode in ("keyword", "semantic", "hybrid"):
        res = client.post("/api/v1/search", json={"query": "flux capacitor", "search_type": mode})
        ids = [r["document_id"] for r in res.json()["results"]]
        assert doc["id"] in ids, mode


def test_search_with_like_wildcards_is_literal(client):
    res = client.post("/api/v1/search", json={"query": "%", "search_type": "keyword"})
    assert res.status_code == 200
    assert res.json()["count"] == 0


def test_delete_single_document_removes_record_and_file(client):
    doc = upload(client, "to_delete.csv", INVOICE_CSV.format(num="DEL-1", total="1100.00").encode())
    stored = [p for p in settings.STORAGE_DIR.iterdir() if p.name.endswith("_to_delete.csv")]
    assert len(stored) == 1

    res = client.delete(f"/api/v1/documents/{doc['id']}")
    assert res.status_code == 200
    assert client.get(f"/api/v1/documents/{doc['id']}").status_code == 404
    assert not stored[0].exists()
    assert client.delete(f"/api/v1/documents/{doc['id']}").status_code == 404

    # Its invoice number no longer counts as a duplicate
    again = upload(client, "to_delete_again.csv", INVOICE_CSV.format(num="DEL-1", total="1100.00").encode())
    assert again["validation_result"]["duplicate_detected"] is False


def test_clear_all_requires_confirmation_and_empties_everything(client):
    upload(client, "clear_me.csv", INVOICE_CSV.format(num="CLR-1", total="1100.00").encode())
    assert client.delete("/api/v1/documents").status_code == 400  # no ?confirm=true
    assert len(client.get("/api/v1/documents").json()) > 0

    res = client.delete("/api/v1/documents?confirm=true")
    assert res.status_code == 200
    assert res.json()["deleted"] > 0
    assert client.get("/api/v1/documents").json() == []
    assert [p.name for p in settings.STORAGE_DIR.iterdir()] == []
    res = client.post("/api/v1/search", json={"query": "Apex", "search_type": "hybrid"})
    assert res.json()["count"] == 0
