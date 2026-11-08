import json
import time
import sys
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.ai_extractor import AIExtractor
from app.services.validator import FinancialValidator

def evaluate_system():
    benchmark_file = Path(__file__).parent / "benchmark_dataset.json"
    with open(benchmark_file, "r") as f:
        dataset = json.load(f)

    extractor = AIExtractor(provider="heuristic_fallback")
    validator = FinancialValidator()

    total_docs = len(dataset)
    successful_docs = 0
    failed_docs = 0
    total_latency_sec = 0.0

    fields_to_track = [
        "invoice_number", "invoice_date", "supplier_name",
        "customer_name", "subtotal", "tax", "total", "line_items_count"
    ]
    field_matches = {field: 0 for field in fields_to_track}
    field_totals = {field: 0 for field in fields_to_track}

    print("=" * 70)
    print("RUNNING BENCHMARK EVALUATION ON LABELED FINANCIAL DATASET")
    print("=" * 70)

    for item in dataset:
        doc_id = item["id"]
        doc_name = item["name"]
        raw_text = item["raw_text"]
        gt = item["ground_truth"]

        start_time = time.perf_counter()
        try:
            # 1. AI Extraction
            res = extractor.extract(raw_text)
            
            # 2. Validation Run
            val_res = validator.validate(res)

            elapsed = time.perf_counter() - start_time
            total_latency_sec += elapsed
            successful_docs += 1

            # Field Accuracy Checks
            for field in fields_to_track:
                expected = gt.get(field)
                if expected is not None:
                    field_totals[field] += 1
                    if field == "line_items_count":
                        actual = len(res.line_items)
                        if actual == expected:
                            field_matches[field] += 1
                    else:
                        actual = getattr(res, field, None)
                        if actual == expected or (isinstance(expected, str) and actual and expected.lower() in str(actual).lower()):
                            field_matches[field] += 1
                        elif isinstance(expected, float) and actual is not None and abs(expected - float(actual)) < 0.05:
                            field_matches[field] += 1

            print(f"[SUCCESS] {doc_name} ({doc_id}) - Latency: {elapsed*1000:.2f}ms | Confidence: {res.overall_confidence:.2f}")

        except Exception as e:
            failed_docs += 1
            print(f"[FAILED] {doc_name} ({doc_id}) - Error: {e}")

    # Aggregated Metrics Calculation
    avg_latency_ms = (total_latency_sec / total_docs) * 1000 if total_docs > 0 else 0
    doc_success_rate = (successful_docs / total_docs) * 100 if total_docs > 0 else 0
    doc_failure_rate = (failed_docs / total_docs) * 100 if total_docs > 0 else 0

    print("\n" + "=" * 70)
    print("BENCHMARK EVALUATION METRICS SUMMARY")
    print("=" * 70)
    print(f"Total Test Documents:     {total_docs}")
    print(f"Document Success Rate:    {doc_success_rate:.1f}%")
    print(f"Document Failure Rate:    {doc_failure_rate:.1f}%")
    print(f"Average Latency:          {avg_latency_ms:.2f} ms / document")
    print("-" * 70)
    print("FIELD-LEVEL EXTRACTION ACCURACY:")
    
    total_acc_sum = 0
    valid_fields_count = 0
    for field, total_occurrences in field_totals.items():
        if total_occurrences > 0:
            acc = (field_matches[field] / total_occurrences) * 100
            total_acc_sum += acc
            valid_fields_count += 1
            print(f"  - {field.ljust(20)}: {acc:.1f}%  ({field_matches[field]}/{total_occurrences})")

    overall_accuracy = (total_acc_sum / valid_fields_count) if valid_fields_count > 0 else 0
    print("-" * 70)
    print(f"OVERALL EXTRACTION ACCURACY: {overall_accuracy:.2f}%")
    print("=" * 70)

    report_path = Path(__file__).parent / "evaluation_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "total_documents": total_docs,
            "document_success_rate": f"{doc_success_rate:.1f}%",
            "document_failure_rate": f"{doc_failure_rate:.1f}%",
            "average_processing_time_ms": round(avg_latency_ms, 2),
            "overall_extraction_accuracy": f"{overall_accuracy:.2f}%",
            "field_accuracies": {k: f"{(field_matches[k]/v)*100:.1f}%" for k, v in field_totals.items() if v > 0}
        }, f, indent=2)

if __name__ == "__main__":
    evaluate_system()
