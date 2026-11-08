import os
import re
import json
from typing import Dict, Any, List, Optional
from app.core.logging import logger
from app.models.schemas import InvoiceExtractionSchema, LineItemSchema
from app.config import settings

EXTRACTION_SYSTEM_PROMPT = """You are a senior financial document intelligence AI.
Your task is to accurately extract invoice details from the provided document text into a structured JSON schema.

CRITICAL INSTRUCTIONS TO PREVENT HALLUCINATIONS:
1. ONLY extract information that is explicitly stated in the document text.
2. If any field (e.g. tax, customer name, purchase order) is NOT clearly found, return null for that field. DO NOT guess, fabricate, or invent values.
3. For numeric values (subtotal, tax, total, quantity, unit_price, amount), extract clean float numbers without currency symbols or commas.
4. If a date is found, normalize it to YYYY-MM-DD if possible, or preserve the exact textual date.
5. Extract all line items listed in tables or itemized breakdowns.
6. Provide a confidence score (between 0.0 and 1.0) for each field based on its legibility and clarity in the text.
7. List any expected standard fields that are missing in the 'missing_fields' array.

You MUST respond strictly with a valid JSON object matching the exact schema below:
{
  "invoice_number": string or null,
  "invoice_date": string or null,
  "supplier_name": string or null,
  "customer_name": string or null,
  "currency": string or null,
  "subtotal": float or null,
  "tax": float or null,
  "total": float or null,
  "line_items": [
    {
      "description": string,
      "quantity": float or null,
      "unit_price": float or null,
      "amount": float or null,
      "confidence": float
    }
  ],
  "missing_fields": [string],
  "confidence_scores": {
    "invoice_number": float,
    "invoice_date": float,
    "supplier_name": float,
    "customer_name": float,
    "total": float
  },
  "overall_confidence": float,
  "raw_summary": string
}
"""

# Fields whose absence is reported in `missing_fields`
TRACKED_FIELDS = [
    "invoice_number", "invoice_date", "supplier_name", "customer_name",
    "currency", "subtotal", "tax", "total",
]

# Max characters sent to the LLM. Head + tail are kept because invoice totals
# usually sit at the end of the document.
LLM_HEAD_CHARS = 12000
LLM_TAIL_CHARS = 4000

# Normalized spreadsheet header -> canonical invoice field
_HEADER_SYNONYMS: Dict[str, List[str]] = {
    "invoice_number": ["invoicenumber", "invoiceno", "invoiceid", "invoicenum", "invoice", "invno",
                       "invnumber", "billno", "billnumber", "documentnumber", "docno", "ponumber",
                       "pono", "purchaseorder", "purchaseordernumber", "orderno", "ordernumber"],
    "invoice_date": ["invoicedate", "date", "billdate", "issuedate", "documentdate", "orderdate", "podate"],
    "supplier_name": ["supplier", "suppliername", "vendor", "vendorname", "seller", "billedby", "from"],
    "customer_name": ["customer", "customername", "client", "clientname", "billto", "buyer", "soldto"],
    "currency": ["currency", "currencycode", "curr", "ccy"],
    "subtotal": ["subtotal", "netamount", "net", "amountbeforetax", "nettotal"],
    "tax": ["tax", "taxamount", "vat", "vatamount", "gst", "salestax"],
    "total": ["total", "totalamount", "grandtotal", "amountdue", "totaldue", "gross", "grossamount",
              "invoicetotal", "invoiceamount", "balancedue"],
}
_LINE_SYNONYMS: Dict[str, List[str]] = {
    "description": ["description", "itemdescription", "item", "itemname", "product", "service", "details"],
    "quantity": ["quantity", "qty", "units"],
    "unit_price": ["unitprice", "price", "rate", "unitcost"],
    "amount": ["amount", "lineamount", "linetotal", "extendedprice", "lineitemtotal"],
}


def _norm_header(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def to_float(value: Any) -> Optional[float]:
    """Parses '1,234.50', '$99', '(12.00)', 12 -> float. Returns None if not numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None  # filters NaN
    s = str(value).strip()
    if not s:
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in {"-", ".", "-."}:
        return None
    try:
        num = float(s)
    except ValueError:
        return None
    return -abs(num) if negative else num


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _detect_currency(text: str) -> Optional[str]:
    """Detects currency from explicit codes or symbols. Returns None when absent."""
    for code in ["USD", "EUR", "GBP", "INR", "CAD", "AUD", "JPY", "BDT", "AED", "SGD"]:
        if re.search(rf"\b{code}\b", text):
            return code
    for symbol, code in [("€", "EUR"), ("£", "GBP"), ("₹", "INR"), ("৳", "BDT"), ("¥", "JPY"), ("$", "USD")]:
        if symbol in text:
            return code
    return None


def compute_missing_fields(ext: InvoiceExtractionSchema) -> List[str]:
    missing = []
    for f in TRACKED_FIELDS:
        val = getattr(ext, f, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(f)
    return missing


class AIExtractor:
    """
    Task 2: AI Information Extraction Engine.
    - Structured spreadsheets (CSV/XLSX) are mapped column-by-column (deterministic).
    - Text documents use an LLM (Gemini / OpenAI) with JSON output enforcement.
    - A deterministic rule-based extractor is the offline / failure fallback.
    Missing values are always returned as null, never invented.
    """

    def __init__(self, provider: Optional[str] = None):
        self.provider = provider or settings.LLM_PROVIDER
        self.gemini_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        self.gemini_model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
        self.openai_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")
        self.openai_model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")
        self.last_method: str = "none"

    def extract(self, document_text: str, tables: Optional[List[Dict[str, Any]]] = None) -> InvoiceExtractionSchema:
        """
        Extracts structured invoice data. `tables` (from spreadsheet parsing) is tried first,
        then the configured LLM provider, then the heuristic fallback.
        """
        if tables:
            table_res = self.extract_from_tables(tables)
            if table_res is not None:
                self.last_method = "spreadsheet_mapping"
                return table_res

        if not document_text or not document_text.strip():
            logger.warning("Empty document text passed to AIExtractor.")
            self.last_method = "empty"
            return self._empty_extraction("Document text is empty (no digital text and no OCR output).")

        if self.provider == "gemini" and self.gemini_key:
            try:
                logger.info(f"Invoking Google Gemini ({self.gemini_model}) for financial extraction...")
                res = self._extract_with_gemini(document_text)
                self.last_method = "gemini"
                return res
            except Exception as e:
                logger.error(f"Gemini extraction failed: {type(e).__name__}: {e}. Falling back to heuristic extractor.")

        if self.provider == "openai" and self.openai_key:
            try:
                res = self._extract_with_openai(document_text)
                self.last_method = "openai"
                return res
            except Exception as e:
                logger.error(f"OpenAI extraction failed: {type(e).__name__}: {e}. Falling back to heuristic extractor.")

        self.last_method = "heuristic"
        return self._extract_heuristically(document_text)

    # ------------------------------------------------------------------ LLM
    @staticmethod
    def _truncate_for_llm(text: str) -> str:
        if len(text) <= LLM_HEAD_CHARS + LLM_TAIL_CHARS:
            return text
        return text[:LLM_HEAD_CHARS] + "\n\n[... document truncated ...]\n\n" + text[-LLM_TAIL_CHARS:]

    @staticmethod
    def _strip_code_fences(raw: str) -> str:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?", "", raw).strip()
        if raw.endswith("```"):
            raw = raw[:-3]
        return raw.strip()

    def _normalize_llm_output(self, parsed: Dict[str, Any]) -> InvoiceExtractionSchema:
        """Coerces loosely-typed LLM JSON into the strict schema without inventing data."""
        if not isinstance(parsed, dict):
            raise ValueError("LLM response is not a JSON object")

        def clamp(v: Any, default: float = 0.0) -> float:
            f = to_float(v)
            if f is None:
                return default
            if 2.0 <= f <= 100.0:  # model answered in percent (e.g. 95)
                f = f / 100.0
            return max(0.0, min(1.0, f))

        line_items = []
        for item in parsed.get("line_items") or []:
            if not isinstance(item, dict):
                continue
            li = LineItemSchema(
                description=_clean_str(item.get("description")),
                quantity=to_float(item.get("quantity")),
                unit_price=to_float(item.get("unit_price")),
                amount=to_float(item.get("amount")),
                confidence=clamp(item.get("confidence"), 0.8),
            )
            if li.description or li.amount is not None:
                line_items.append(li)

        scores_raw = parsed.get("confidence_scores") or {}
        scores = {k: clamp(v) for k, v in scores_raw.items() if to_float(v) is not None} if isinstance(scores_raw, dict) else {}

        ext = InvoiceExtractionSchema(
            invoice_number=_clean_str(parsed.get("invoice_number")),
            invoice_date=_clean_str(parsed.get("invoice_date")),
            supplier_name=_clean_str(parsed.get("supplier_name")),
            customer_name=_clean_str(parsed.get("customer_name")),
            currency=_clean_str(parsed.get("currency")),
            subtotal=to_float(parsed.get("subtotal")),
            tax=to_float(parsed.get("tax")),
            total=to_float(parsed.get("total")),
            line_items=line_items,
            confidence_scores=scores,
            overall_confidence=clamp(parsed.get("overall_confidence"), 0.5),
            raw_summary=_clean_str(parsed.get("raw_summary")),
        )
        ext.missing_fields = compute_missing_fields(ext)
        return ext

    def _extract_with_gemini(self, text: str) -> InvoiceExtractionSchema:
        """Call Google Gemini API via httpx (API key sent in a header, never in the URL)."""
        import httpx

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent"
        prompt = f"{EXTRACTION_SYSTEM_PROMPT}\n\nDOCUMENT TEXT TO EXTRACT:\n{self._truncate_for_llm(text)}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0.0},
        }
        headers = {"x-goog-api-key": self.gemini_key, "Content-Type": "application/json"}

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            raw_json = data["candidates"][0]["content"]["parts"][0]["text"]
            return self._normalize_llm_output(json.loads(self._strip_code_fences(raw_json)))

    def _extract_with_openai(self, text: str) -> InvoiceExtractionSchema:
        """Call OpenAI API with response_format json_object."""
        import httpx

        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.openai_model,
            "messages": [
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"DOCUMENT TEXT:\n{self._truncate_for_llm(text)}"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            raw_json = resp.json()["choices"][0]["message"]["content"]
            return self._normalize_llm_output(json.loads(self._strip_code_fences(raw_json)))

    # ----------------------------------------------------------- Spreadsheets
    @staticmethod
    def _map_columns(columns: List[str], synonyms: Dict[str, List[str]]) -> Dict[str, str]:
        """Returns {canonical_field: original_column}, preferring the earliest synonym match."""
        normalized = {c: _norm_header(c) for c in columns}
        mapping: Dict[str, str] = {}
        for field, names in synonyms.items():
            for name in names:  # synonym order = priority
                match = next((c for c, n in normalized.items() if n == name and c not in mapping.values()), None)
                if match:
                    mapping[field] = match
                    break
        return mapping

    def extract_from_tables(self, tables: List[Dict[str, Any]]) -> Optional[InvoiceExtractionSchema]:
        """
        Deterministic extraction from spreadsheet rows. Supports:
          1. One-invoice-per-row tables (header columns like InvoiceNumber / Supplier / Total)
          2. Line-item tables (Description / Qty / Unit Price / Amount)
          3. Key-value sheets ("Invoice Number" | "INV-1")
        Returns None when no table looks like invoice data.
        """
        header: Dict[str, Any] = {}
        line_items: List[LineItemSchema] = []
        record_count = 0
        found_any = False

        for table in tables:
            rows = [r for r in (table.get("rows") or []) if any(v not in (None, "") for v in r.values())]
            if not rows:
                continue
            columns = list(rows[0].keys())
            head_map = self._map_columns(columns, _HEADER_SYNONYMS)
            line_map = self._map_columns(columns, _LINE_SYNONYMS)
            has_lines = "description" in line_map and ({"quantity", "unit_price", "amount"} & set(line_map))

            # "Amount" means line amount on item tables, invoice total otherwise
            if not has_lines and "total" not in head_map and "amount" in line_map:
                head_map["total"] = line_map["amount"]

            # Key-value layout: 2 columns, first column holds field labels
            # (the first pair became the column headers when the sheet was parsed)
            if len(columns) == 2:
                kv_pairs = [(columns[0], columns[1])] + [(r.get(columns[0]), r.get(columns[1])) for r in rows]
                label_hits = [
                    (field, value)
                    for label, value in kv_pairs
                    for field, names in _HEADER_SYNONYMS.items()
                    if _norm_header(label) in names and value not in (None, "")
                ]
                if len({f for f, _ in label_hits}) >= 2:
                    found_any = True
                    for field, value in label_hits:
                        header.setdefault(field, value)
                    continue

            if head_map:
                found_any = True
                inv_col = head_map.get("invoice_number")
                distinct_invoices = {str(r.get(inv_col)).strip() for r in rows if r.get(inv_col) not in (None, "")} if inv_col else set()
                record_count = max(record_count, len(distinct_invoices) or (len(rows) if not has_lines else 1))
                if len(distinct_invoices) > 1:
                    continue  # ledger / register with many invoices: don't pick one arbitrarily
                for field, col in head_map.items():
                    if field in header:
                        continue
                    values = [r.get(col) for r in rows if r.get(col) not in (None, "")]
                    if values and (has_lines or len(set(map(str, values))) == 1 or len(rows) == 1):
                        header[field] = values[-1] if field in {"subtotal", "tax", "total"} and has_lines else values[0]

            if has_lines:
                found_any = True
                for r in rows:
                    desc = _clean_str(r.get(line_map.get("description"))) if "description" in line_map else None
                    if not desc or _norm_header(desc) in {"subtotal", "tax", "total", "grandtotal", "vat"}:
                        continue
                    qty = to_float(r.get(line_map["quantity"])) if "quantity" in line_map else None
                    price = to_float(r.get(line_map["unit_price"])) if "unit_price" in line_map else None
                    amount = to_float(r.get(line_map["amount"])) if "amount" in line_map else None
                    if amount is None and qty is not None and price is not None:
                        amount = round(qty * price, 2)
                    line_items.append(LineItemSchema(description=desc, quantity=qty, unit_price=price,
                                                     amount=amount, confidence=0.98))

        if not found_any:
            return None

        if record_count > 1 and not header:
            return InvoiceExtractionSchema(
                missing_fields=list(TRACKED_FIELDS),
                overall_confidence=0.0,
                raw_summary=(f"Spreadsheet is a ledger/register containing {record_count} records. "
                             "No single invoice was extracted; use Cross-Verification to reconcile against it."),
            )

        all_values_text = " ".join(str(v) for v in header.values())
        currency = _clean_str(header.get("currency")) or _detect_currency(all_values_text)
        ext = InvoiceExtractionSchema(
            invoice_number=_clean_str(header.get("invoice_number")),
            invoice_date=_clean_str(header.get("invoice_date")),
            supplier_name=_clean_str(header.get("supplier_name")),
            customer_name=_clean_str(header.get("customer_name")),
            currency=currency.upper() if currency else None,
            subtotal=to_float(header.get("subtotal")),
            tax=to_float(header.get("tax")),
            total=to_float(header.get("total")),
            line_items=line_items,
        )
        scores = {f: (0.98 if getattr(ext, f) is not None else 0.0) for f in TRACKED_FIELDS}
        ext.confidence_scores = scores
        ext.missing_fields = compute_missing_fields(ext)
        # Confidence reflects how certain the extracted values are; absent fields are
        # already reported separately via missing_fields / validation rules.
        present = [v for v in scores.values() if v > 0]
        ext.overall_confidence = round(sum(present) / len(present), 2) if present else 0.0
        ext.raw_summary = (f"Spreadsheet invoice {ext.invoice_number or 'Unknown'} from "
                           f"{ext.supplier_name or 'Unknown'} with {len(line_items)} line items.")
        return ext

    # -------------------------------------------------------------- Heuristic
    @staticmethod
    def _looks_like_supplier_line(line: str) -> bool:
        lowered = line.lower()
        if any(kw in lowered for kw in ["invoice", "bill", "tax", "receipt", "statement", "page"]):
            return False
        if line.startswith(("[", "---", "#")) or "," in line or len(line) > 80:
            return False
        letters = sum(ch.isalpha() for ch in line)
        return letters >= 3 and letters >= len(line) * 0.5

    def _extract_heuristically(self, text: str) -> InvoiceExtractionSchema:
        """
        Deterministic, rule-based extraction engine.
        Parses invoice number, dates, amounts, taxes, suppliers, and line items.
        Strictly sets unidentifiable fields to None.
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        scores: Dict[str, float] = {}

        # 1. Invoice Number
        inv_match = re.search(r"\binvoice\s*(?:number|no\.?|num\.?|id)[:\s#]+([a-zA-Z0-9\-_/]+)", text, re.IGNORECASE)
        if not inv_match:
            inv_match = re.search(r"\binvoice\s*#\s*([a-zA-Z0-9\-_/]+)", text, re.IGNORECASE)
        if not inv_match:
            inv_match = re.search(r"\binv[:\s#]+([a-zA-Z0-9][a-zA-Z0-9\-_/]*\d[a-zA-Z0-9\-_/]*)", text, re.IGNORECASE)
        invoice_number = inv_match.group(1).strip() if inv_match else None
        scores["invoice_number"] = 0.95 if invoice_number else 0.0

        # 2. Date
        date_match = re.search(
            r"(?:invoice\s*date|date|dated)[:\s]+(\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
            text, re.IGNORECASE
        )
        invoice_date = date_match.group(1).strip() if date_match else None
        scores["invoice_date"] = 0.90 if invoice_date else 0.0

        # 3. Currency (None when no explicit code/symbol - never defaulted)
        currency = _detect_currency(text)

        # 4. Supplier Name (explicit label, else a name-like first line)
        supplier_name = None
        from_match = re.search(r"^\s*(?:from|vendor|supplier|seller|billed\s*by)\s*[:\-]\s*([^\n\r,]+)", text, re.IGNORECASE | re.MULTILINE)
        if from_match:
            supplier_name = from_match.group(1).strip()
        elif lines and self._looks_like_supplier_line(lines[0]):
            supplier_name = lines[0]
        scores["supplier_name"] = 0.85 if supplier_name else 0.0

        # 5. Customer Name
        customer_name = None
        to_match = re.search(r"^\s*(?:bill\s*to|billed\s*to|customer|client|sold\s*to)\s*[:\-]\s*([^\n\r,]+)", text, re.IGNORECASE | re.MULTILINE)
        if to_match:
            customer_name = to_match.group(1).strip()
        scores["customer_name"] = 0.85 if customer_name else 0.0

        # 6. Financial Totals
        amount_re = r"[:\s]+(?:[A-Z]{3}\s*)?[\$€£₹]?\s*(\d[\d,]*(?:\.\d{1,2})?)"

        def find_amount(label_pattern: str) -> Optional[float]:
            match = re.search(label_pattern + amount_re, text, re.IGNORECASE)
            return to_float(match.group(1)) if match else None

        subtotal = find_amount(r"\b(?:subtotal|sub-total|sub\s*total|net\s*amount)\b")
        tax = find_amount(r"\b(?:sales\s*tax|tax\s*amount|tax|vat|gst)\b(?:\s*\(?\d+(?:\.\d+)?%\)?)?")
        total = find_amount(r"(?<!sub)(?<!sub-)(?<!sub\s)\b(?:total\s*amount|total\s*due|grand\s*total|amount\s*due|balance\s*due|total)\b")

        scores["subtotal"] = 0.90 if subtotal is not None else 0.0
        scores["tax"] = 0.85 if tax is not None else 0.0
        scores["total"] = 0.95 if total is not None else 0.0

        # 7. Line Items: "<description> <qty> <unit price> <amount>"
        line_items: List[LineItemSchema] = []
        row_pattern = re.compile(
            r"^\s*([A-Za-z][A-Za-z0-9\s\-_.,/&()]*?)\s+(\d+(?:\.\d+)?)\s+[\$€£₹]?\s*(\d[\d,]*(?:\.\d+)?)\s+[\$€£₹]?\s*(\d[\d,]*(?:\.\d+)?)\s*$",
            re.MULTILINE
        )
        for match in row_pattern.finditer(text):
            desc, qty, unit_price, amt = match.groups()
            desc = desc.strip()
            if any(h in desc.lower() for h in ["description", "qty", "subtotal", "total"]):
                continue
            q, p, a = to_float(qty), to_float(unit_price), to_float(amt)
            if None in (q, p, a):
                continue
            line_items.append(LineItemSchema(description=desc, quantity=q, unit_price=p, amount=a, confidence=0.90))

        present_scores = [v for v in scores.values() if v > 0]
        overall_confidence = round(sum(present_scores) / len(scores), 2) if present_scores else 0.0

        ext = InvoiceExtractionSchema(
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            supplier_name=supplier_name,
            customer_name=customer_name,
            currency=currency,
            subtotal=subtotal,
            tax=tax,
            total=total,
            line_items=line_items,
            confidence_scores=scores,
            overall_confidence=overall_confidence,
            raw_summary=f"Invoice {invoice_number or 'Unknown'} from {supplier_name or 'Unknown'} with {len(line_items)} line items."
        )
        ext.missing_fields = compute_missing_fields(ext)
        return ext

    def _empty_extraction(self, reason: str) -> InvoiceExtractionSchema:
        return InvoiceExtractionSchema(
            missing_fields=list(TRACKED_FIELDS),
            overall_confidence=0.0,
            raw_summary=f"Extraction empty: {reason}"
        )
