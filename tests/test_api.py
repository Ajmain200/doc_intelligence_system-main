import io
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.database import init_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_database():
    init_db()

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_upload_unsupported_file_fails():
    file_content = b"fake binary content"
    files = [("files", ("test.bin", io.BytesIO(file_content), "application/octet-stream"))]
    response = client.post("/api/v1/documents/upload", files=files)
    assert response.status_code == 400
    assert "Unsupported format" in response.json()["detail"]

def test_upload_and_list_document():
    csv_content = b"InvoiceNumber,Date,Supplier,Total\nINV-888,2024-01-01,TestCo,300.00\n"
    files = [("files", ("test_invoice.csv", io.BytesIO(csv_content), "text/csv"))]
    upload_res = client.post("/api/v1/documents/upload", files=files)
    assert upload_res.status_code == 200
    docs = upload_res.json()
    assert len(docs) == 1
    doc_id = docs[0]["id"]
    assert docs[0]["filename"] == "test_invoice.csv"

    # List documents
    list_res = client.get("/api/v1/documents")
    assert list_res.status_code == 200
    assert any(d["id"] == doc_id for d in list_res.json())

def test_get_nonexistent_document_returns_404():
    res = client.get("/api/v1/documents/non-existent-uuid-999")
    assert res.status_code == 404

def test_search_api():
    query_payload = {
        "query": "invoice",
        "search_type": "hybrid",
        "limit": 5
    }
    res = client.post("/api/v1/search", json=query_payload)
    assert res.status_code == 200
    assert "results" in res.json()
