"""Tiny dependency-free generator for single-page text PDFs used in tests."""
from pathlib import Path
from typing import List


def make_text_pdf(path: Path, lines: List[str]) -> Path:
    # Note: lines must not contain unbalanced parentheses or backslashes
    content = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    path.write_bytes(out)
    return path


INVOICE_LINES = [
    "Northwind Traders Ltd",
    "TAX INVOICE",
    "Invoice Number: NW-2024-0042",
    "Date: 2024-07-01",
    "Bill To: Contoso Retail",
    "Widget Pro 4 25.00 100.00",
    "Gadget Max 2 50.00 100.00",
    "Subtotal: USD 200.00",
    "Tax: USD 20.00",
    "Total: USD 220.00",
]
