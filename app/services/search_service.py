import math
import re
import threading
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import or_, exists, and_

from app.models.database import DocumentModel, DocumentPageModel, ExtractedInvoiceModel
from app.core.logging import logger

class HybridSearchService:
    """
    Task 5: Hybrid Search Service.
    Combines keyword-based full-text filtering with semantic vector search.
    Provides rank fusion for high-precision retrieval across thousands of business documents.
    """

    def __init__(self):
        # In-memory document vector index cache: doc_id -> list of float weights
        self._vector_index: Dict[str, Dict[str, float]] = {}
        self._lock = threading.Lock()
        self._loaded = False

    def _tokenize(self, text: str) -> List[str]:
        """Simple lowercase word tokenizer."""
        return re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())

    def _compute_tf_idf_vector(self, text: str) -> Dict[str, float]:
        """Generates normalized term-frequency sparse embedding vector."""
        tokens = self._tokenize(text)
        if not tokens:
            return {}
        counts: Dict[str, float] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0.0) + 1.0

        total = float(len(tokens))
        norm_sq = 0.0
        vec = {}
        for term, cnt in counts.items():
            val = (cnt / total)
            vec[term] = val
            norm_sq += val * val

        # Normalize to unit vector
        norm = math.sqrt(norm_sq) if norm_sq > 0 else 1.0
        return {k: v / norm for k, v in vec.items()}

    def _cosine_similarity(self, vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
        """Computes dot product of two normalized sparse vectors."""
        dot = 0.0
        for token, val in vec1.items():
            if token in vec2:
                dot += val * vec2[token]
        return dot

    def index_document(self, doc_id: str, text: str):
        """Indexes or updates a document into the semantic search engine."""
        vec = self._compute_tf_idf_vector(text)
        with self._lock:
            self._vector_index[doc_id] = vec

    def remove_document(self, doc_id: str):
        with self._lock:
            self._vector_index.pop(doc_id, None)

    def rebuild_index(self, db: Session) -> int:
        """(Re)builds the in-memory index from page text persisted in the database."""
        texts: Dict[str, List[str]] = {}
        names = dict(db.query(DocumentModel.id, DocumentModel.filename).all())
        for doc_id, raw_text in (
            db.query(DocumentPageModel.document_id, DocumentPageModel.raw_text)
            .order_by(DocumentPageModel.document_id, DocumentPageModel.page_number)
        ):
            texts.setdefault(doc_id, []).append(raw_text or "")
        new_index = {
            doc_id: self._compute_tf_idf_vector(f"{names.get(doc_id, '')} " + " ".join(parts))
            for doc_id, parts in texts.items()
        }
        with self._lock:
            self._vector_index = new_index
            self._loaded = True
        return len(new_index)

    def search(
        self,
        query: str,
        db: Session,
        search_type: str = "hybrid",
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Executes search across the document repository.
        Supported modes: 'keyword', 'semantic', 'hybrid'.
        """
        query = query.strip()
        if not query:
            return []
        if not self._loaded:
            self.rebuild_index(db)
        limit = max(1, min(int(limit or 10), 100))

        # 1. Keyword search via DB filters
        keyword_results = self._keyword_search(query, db)

        # 2. Semantic vector search
        semantic_results = self._semantic_search(query)

        # 3. Fuse results based on mode
        final_scores: Dict[str, float] = {}
        doc_details: Dict[str, Any] = {}

        if search_type == "keyword":
            for doc_id, item in keyword_results.items():
                final_scores[doc_id] = item["score"]
                doc_details[doc_id] = item["data"]
        elif search_type == "semantic":
            for doc_id, score in semantic_results.items():
                final_scores[doc_id] = score
                # Fetch details from DB
                doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
                if doc:
                    doc_details[doc_id] = self._format_doc_summary(doc)
        else: # Hybrid (Reciprocal / Weighted Score Fusion)
            all_ids = set(keyword_results.keys()).union(set(semantic_results.keys()))
            for doc_id in all_ids:
                k_score = keyword_results.get(doc_id, {}).get("score", 0.0)
                s_score = semantic_results.get(doc_id, 0.0)
                # 50% keyword exact match + 50% semantic vector match
                final_scores[doc_id] = (0.5 * k_score) + (0.5 * s_score)
                
                if doc_id in keyword_results:
                    doc_details[doc_id] = keyword_results[doc_id]["data"]
                else:
                    doc = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
                    if doc:
                        doc_details[doc_id] = self._format_doc_summary(doc)

        # Sort descending by fused score
        sorted_docs = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

        return [
            {
                "document_id": doc_id,
                "score": round(score, 4),
                "details": doc_details.get(doc_id, {})
            }
            for doc_id, score in sorted_docs if score > 0.01
        ]

    def _keyword_search(self, query: str, db: Session) -> Dict[str, Dict[str, Any]]:
        """
        Filters DB records matching the query in filename, extracted fields, or full page text.
        Metadata/field hits score 1.0, body-text-only hits score 0.6.
        """
        escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        like_term = f"%{escaped}%"
        matches: Dict[str, Dict[str, Any]] = {}

        field_match = or_(
            DocumentModel.filename.ilike(like_term, escape="!"),
            ExtractedInvoiceModel.supplier_name.ilike(like_term, escape="!"),
            ExtractedInvoiceModel.customer_name.ilike(like_term, escape="!"),
            ExtractedInvoiceModel.invoice_number.ilike(like_term, escape="!"),
            ExtractedInvoiceModel.raw_summary.ilike(like_term, escape="!"),
        )
        text_match = exists().where(and_(
            DocumentPageModel.document_id == DocumentModel.id,
            DocumentPageModel.raw_text.ilike(like_term, escape="!"),
        ))

        docs = db.query(DocumentModel).outerjoin(ExtractedInvoiceModel).filter(
            or_(field_match, text_match)
        ).limit(500).all()

        q_lower = query.lower()
        for doc in docs:
            ext = doc.extraction
            fields = [doc.filename] + ([ext.supplier_name, ext.customer_name, ext.invoice_number, ext.raw_summary] if ext else [])
            in_fields = any(f and q_lower in f.lower() for f in fields)
            matches[doc.id] = {
                "score": 1.0 if in_fields else 0.6,
                "data": self._format_doc_summary(doc)
            }
        return matches

    def _semantic_search(self, query: str) -> Dict[str, float]:
        """Computes semantic similarity against all indexed document vectors."""
        query_vec = self._compute_tf_idf_vector(query)
        scores: Dict[str, float] = {}

        with self._lock:
            index_items = list(self._vector_index.items())
        for doc_id, doc_vec in index_items:
            sim = self._cosine_similarity(query_vec, doc_vec)
            if sim > 0:
                scores[doc_id] = sim
        return scores

    def _format_doc_summary(self, doc: DocumentModel) -> Dict[str, Any]:
        ext = doc.extraction
        return {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "status": doc.status,
            "invoice_number": ext.invoice_number if ext else None,
            "supplier_name": ext.supplier_name if ext else None,
            "total": ext.total if ext else None,
            "currency": ext.currency if ext else None,
            "created_at": doc.created_at.isoformat() if doc.created_at else None
        }

search_service = HybridSearchService()
