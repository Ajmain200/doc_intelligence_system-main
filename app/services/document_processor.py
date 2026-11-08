import csv
import io
from pathlib import Path
from typing import List, Dict, Any, Generator, Optional
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.core.logging import logger
from app.core.exceptions import CorruptedFileError, DocumentProcessingError
from app.config import settings

# PDF library imports with fallback
try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    PYTESSERACT_AVAILABLE = False

# Pages with less digital text than this are treated as scanned and sent to OCR
MIN_DIGITAL_TEXT_CHARS = 30
# Cap the number of rows serialized per sheet into the text representation
MAX_ROWS_IN_TEXT = 5000

_tesseract_checked: Optional[bool] = None


def tesseract_available() -> bool:
    """Returns True if both pytesseract and the Tesseract binary are usable (cached)."""
    global _tesseract_checked
    if _tesseract_checked is None:
        if not PYTESSERACT_AVAILABLE:
            _tesseract_checked = False
        else:
            try:
                pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
                pytesseract.get_tesseract_version()
                _tesseract_checked = True
            except Exception as e:
                logger.warning(
                    f"Tesseract OCR binary not found ({e}). Scanned pages and images will "
                    "produce no text until Tesseract is installed (set TESSERACT_CMD)."
                )
                _tesseract_checked = False
    return _tesseract_checked


def _clean_cell(value: Any) -> Any:
    """Converts pandas cell values into JSON-friendly python values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):  # datetime / date / pandas Timestamp
        is_midnight = getattr(value, "hour", 0) == 0 and getattr(value, "minute", 0) == 0
        return value.isoformat()[:10] if is_midnight else value.isoformat()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


def dataframe_to_rows(df: "pd.DataFrame") -> List[Dict[str, Any]]:
    """Converts a DataFrame into a list of {column: value} dicts with clean values."""
    columns = [str(c).strip() for c in df.columns]
    rows = []
    for record in df.itertuples(index=False, name=None):
        rows.append({col: _clean_cell(val) for col, val in zip(columns, record)})
    return rows


class DocumentProcessor:
    """
    Task 1: Universal Document Processing Pipeline.
    Supports PDF (Digital & Scanned), Images (JPG/PNG/TIFF), Excel (XLSX/XLS), and CSV.
    Features:
      - Memory-safe streaming for multi-page documents (1000+ pages)
      - OCR of scanned PDF pages (embedded page images) and image files
      - Image preprocessing (grayscale, contrast, denoise, binarization)
      - Corrupted file detection
      - Multi-sheet spreadsheet parsing into text + structured row tables
    """

    SUPPORTED_EXTENSIONS = {
        ".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".xlsx", ".xls", ".csv"
    }
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}
    SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".csv"}

    def __init__(self, tesseract_cmd: Optional[str] = None):
        self.tesseract_cmd = tesseract_cmd or settings.TESSERACT_CMD
        if PYTESSERACT_AVAILABLE and self.tesseract_cmd:
            try:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
            except Exception as e:
                logger.warning(f"Failed to set Tesseract path: {e}")

    def validate_file(self, file_path: Path) -> str:
        """Validates file existence, non-empty size, size limit, and extension."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise DocumentProcessingError(
                f"Unsupported format '{ext}'. Supported: {', '.join(sorted(self.SUPPORTED_EXTENSIONS))}"
            )

        file_size = file_path.stat().st_size
        if file_size == 0:
            raise CorruptedFileError(f"File {file_path.name} is completely empty (0 bytes).")
        if file_size > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
            raise DocumentProcessingError(
                f"File {file_path.name} exceeds the {settings.MAX_FILE_SIZE_MB} MB size limit."
            )
        return ext

    # ------------------------------------------------------------------ OCR
    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocesses poor quality or scanned images before OCR:
        - EXIF orientation fix, grayscale conversion
        - Upscaling of small images (Tesseract works best at ~300 DPI)
        - Auto-contrast enhancement, median denoising, binarization
        """
        try:
            img = ImageOps.exif_transpose(image)
            gray = img.convert("L")
            if min(gray.size) < 1000:
                scale = 1000 / max(1, min(gray.size))
                gray = gray.resize((int(gray.width * scale), int(gray.height * scale)), Image.LANCZOS)
            enhanced = ImageEnhance.Contrast(ImageOps.autocontrast(gray)).enhance(2.0)
            denoised = enhanced.filter(ImageFilter.MedianFilter(size=3))
            threshold = 140
            return denoised.point(lambda p: 255 if p > threshold else 0, mode="1")
        except Exception as e:
            logger.warning(f"Image preprocessing warning: {e}. Falling back to original image.")
            return image

    def _ocr_image(self, image: Image.Image) -> Dict[str, Any]:
        """Runs OCR on a PIL image. Returns text plus a confidence estimate (0-1)."""
        if not tesseract_available():
            return {"text": "", "confidence": 0.0, "ocr_applied": False,
                    "warning": "OCR engine (Tesseract) is not installed; no text extracted."}

        processed = self.preprocess_image(image)
        try:
            data = pytesseract.image_to_data(processed, output_type=pytesseract.Output.DICT)
            confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
            text = pytesseract.image_to_string(processed)
            confidence = round(sum(confs) / len(confs) / 100.0, 2) if confs else 0.0
            return {"text": text.strip(), "confidence": confidence, "ocr_applied": True}
        except Exception as ocr_err:
            logger.warning(f"OCR execution failed: {ocr_err}")
            return {"text": "", "confidence": 0.0, "ocr_applied": False, "warning": f"OCR failed: {ocr_err}"}

    def extract_from_image(self, image_path: Path) -> Dict[str, Any]:
        """Processes an image file (PNG, JPG, multi-frame TIFF) via OCR with preprocessing."""
        try:
            with Image.open(image_path) as img:
                img.verify()  # Detect truncated / corrupted files
        except Exception as e:
            raise CorruptedFileError(f"Corrupted or unreadable image file '{image_path.name}': {e}")

        pages = []
        try:
            with Image.open(image_path) as img:
                frame_count = getattr(img, "n_frames", 1)
                for frame_idx in range(frame_count):
                    img.seek(frame_idx)
                    result = self._ocr_image(img.copy())
                    pages.append({"page_number": frame_idx + 1, **result})
        except Exception as e:
            raise CorruptedFileError(f"Corrupted or unreadable image file '{image_path.name}': {e}")

        return {"page_count": len(pages), "pages": pages}

    # ------------------------------------------------------------------ PDF
    def _ocr_pdf_page(self, page, page_num: int, pdf_name: str) -> Dict[str, Any]:
        """OCRs the embedded raster image(s) of a scanned PDF page."""
        texts, confs, warning = [], [], None
        try:
            images = list(page.images)
        except Exception as e:
            logger.warning(f"Could not read images on page {page_num} of {pdf_name}: {e}")
            images = []

        if not images:
            return {"text": "", "confidence": 0.0, "ocr_applied": False,
                    "warning": "Page has no extractable text or images."}

        for pdf_img in images:
            try:
                result = self._ocr_image(pdf_img.image)
            except Exception as e:
                logger.warning(f"Failed to decode image on page {page_num} of {pdf_name}: {e}")
                continue
            if result.get("warning"):
                warning = result["warning"]
            if result["text"]:
                texts.append(result["text"])
                confs.append(result["confidence"])

        return {
            "text": "\n".join(texts),
            "confidence": round(sum(confs) / len(confs), 2) if confs else 0.0,
            "ocr_applied": bool(texts),
            **({"warning": warning} if warning and not texts else {}),
        }

    def stream_pdf_pages(
        self, pdf_path: Path, chunk_size: int = 15
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Memory-safe generator for large multi-page PDFs (up to 1000+ pages).
        Yields batches of parsed pages; pages without a digital text layer are OCR'd.
        """
        if not PYPDF_AVAILABLE:
            raise DocumentProcessingError("pypdf is required to process PDF files.")

        try:
            reader = PdfReader(str(pdf_path), strict=False)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:
                    raise CorruptedFileError(f"PDF '{pdf_path.name}' is password protected.")
            total_pages = len(reader.pages)
        except CorruptedFileError:
            raise
        except Exception as e:
            raise CorruptedFileError(f"Corrupted PDF file '{pdf_path.name}': {e}")

        if total_pages == 0:
            raise CorruptedFileError(f"PDF file has 0 pages: {pdf_path.name}")

        logger.info(f"Processing PDF '{pdf_path.name}' with {total_pages} pages in batches of {chunk_size}...")

        batch = []
        for idx in range(total_pages):
            page_num = idx + 1
            page_record: Dict[str, Any] = {"page_number": page_num, "ocr_applied": False, "confidence": 1.0}
            page = None
            try:
                page = reader.pages[idx]
                page_text = page.extract_text() or ""
            except Exception as page_err:
                logger.warning(f"Error reading page {page_num} of {pdf_path.name}: {page_err}")
                page_text = ""

            if len(page_text.strip()) < MIN_DIGITAL_TEXT_CHARS and page is not None:
                # Likely a scanned page: OCR its embedded image(s)
                ocr = self._ocr_pdf_page(page, page_num, pdf_path.name)
                if ocr["text"]:
                    page_text = ocr["text"]
                page_record.update({k: v for k, v in ocr.items() if k != "text"})

            page_record["text"] = page_text.strip()
            batch.append(page_record)

            if len(batch) >= chunk_size:
                yield batch
                batch = []

        if batch:
            yield batch

    def extract_from_pdf(self, pdf_path: Path) -> Dict[str, Any]:
        """Full extraction for PDFs, aggregating all page batches."""
        all_pages = []
        for batch in self.stream_pdf_pages(pdf_path, chunk_size=settings.PDF_PAGE_CHUNK_SIZE):
            all_pages.extend(batch)
        return {"page_count": len(all_pages), "pages": all_pages}

    # ------------------------------------------------------------ Spreadsheets
    def _sheet_to_page(self, df: "pd.DataFrame", idx: int, sheet_name: str) -> Dict[str, Any]:
        df = df.dropna(how="all").dropna(axis=1, how="all")
        text_buffer = io.StringIO()
        text_buffer.write(f"--- Sheet: {sheet_name} ---\n")
        df.head(MAX_ROWS_IN_TEXT).to_csv(text_buffer, index=False)
        return {
            "page_number": idx,
            "sheet_name": sheet_name,
            "text": text_buffer.getvalue().strip(),
            "row_count": len(df),
            "col_count": len(df.columns),
            "ocr_applied": False,
            "confidence": 1.0,
        }, {"sheet_name": sheet_name, "rows": dataframe_to_rows(df)}

    def extract_from_spreadsheet(self, excel_path: Path) -> Dict[str, Any]:
        """
        Parses Excel files (.xlsx, .xls) across ALL sheets.
        Returns readable text per sheet plus structured row tables.
        """
        if not PANDAS_AVAILABLE:
            raise DocumentProcessingError("pandas is required for spreadsheet parsing.")
        try:
            with pd.ExcelFile(excel_path) as excel_file:
                sheet_names = excel_file.sheet_names
                pages, tables = [], []
                for idx, sheet_name in enumerate(sheet_names, start=1):
                    df = excel_file.parse(sheet_name=sheet_name)
                    page, table = self._sheet_to_page(df, idx, sheet_name)
                    pages.append(page)
                    tables.append(table)
        except ImportError as e:
            raise DocumentProcessingError(f"Missing spreadsheet engine for '{excel_path.name}': {e}")
        except Exception as e:
            raise CorruptedFileError(f"Corrupted or invalid spreadsheet '{excel_path.name}': {e}")

        return {"page_count": len(pages), "sheets": sheet_names, "pages": pages, "tables": tables}

    def extract_from_csv(self, csv_path: Path) -> Dict[str, Any]:
        """Parses CSV files with delimiter sniffing and encoding fallback."""
        content = None
        for enc in ["utf-8-sig", "latin-1", "cp1252"]:
            try:
                with open(csv_path, mode="r", encoding=enc, newline="") as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            raise CorruptedFileError(f"Unable to decode CSV file '{csv_path.name}' with standard encodings.")
        if "\x00" in content:
            raise CorruptedFileError(f"CSV file '{csv_path.name}' contains binary data.")

        try:
            try:
                delimiter = csv.Sniffer().sniff(content[:4096], delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","

            reader = csv.reader(io.StringIO(content), delimiter=delimiter)
            rows = [r for r in reader if any(cell.strip() for cell in r)]
            table_rows: List[Dict[str, Any]] = []
            if rows:
                header = [h.strip() for h in rows[0]]
                for r in rows[1:]:
                    table_rows.append({
                        header[i] if i < len(header) else f"column_{i}": (cell.strip() or None)
                        for i, cell in enumerate(r)
                    })

            return {
                "page_count": 1,
                "pages": [{
                    "page_number": 1,
                    "text": content.strip(),
                    "row_count": len(rows),
                    "ocr_applied": False,
                    "confidence": 1.0
                }],
                "tables": [{"sheet_name": csv_path.stem, "rows": table_rows}],
            }
        except Exception as e:
            raise CorruptedFileError(f"Error parsing CSV '{csv_path.name}': {e}")

    def process(self, file_path: Path) -> Dict[str, Any]:
        """Unified entrypoint: routes file to the appropriate extraction pipeline."""
        file_path = Path(file_path)
        ext = self.validate_file(file_path)

        if ext == ".pdf":
            return self.extract_from_pdf(file_path)
        elif ext in self.IMAGE_EXTENSIONS:
            return self.extract_from_image(file_path)
        elif ext in {".xlsx", ".xls"}:
            return self.extract_from_spreadsheet(file_path)
        elif ext == ".csv":
            return self.extract_from_csv(file_path)
        raise DocumentProcessingError(f"Unhandled extension: {ext}")
