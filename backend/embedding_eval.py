"""
embedding_eval.py — RAG Embedding Accuracy Evaluation Tool
============================================================
Run directly:
    python embedding_eval.py

Or via the FastAPI endpoint:
    POST /eval/embedding
    Body: { "test_cases": [...] }

Each test case:
    {
        "question":      "What is the dress code for men?",
        "expected_doc":  "Pership Dress Code Policy.pdf",   // filename (partial match OK)
        "expected_page": 3                                  // optional: expected page number
    }

Metrics reported:
  - Hit Rate  : % of questions where the correct document is in top-k results
  - MRR       : Mean Reciprocal Rank — rewards finding the correct doc earlier
  - Score distribution per query (min / max / mean L2 distance)
  - Per-question pass/fail detail
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from pathlib import Path
from io import BytesIO

from vector_db_create import DocumentProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bootstrap: rebuild FAISS index from temp_uploaded_docs if index is missing
# ---------------------------------------------------------------------------

TEMP_DOCS_DIR = Path("temp_uploaded_docs")
FAISS_INDEX_DIR = Path("FAISS_Index/faiss_index")


def bootstrap_index(processor: "DocumentProcessor") -> None:
    """
    If the FAISS index doesn't exist on disk, (re-)embed every PDF found
    in TEMP_DOCS_DIR so that queries have something to search.
    Skips files that are already recorded in processed_files.json.
    """
    index_file = FAISS_INDEX_DIR / "index.faiss"
    if index_file.exists():
        logger.info("FAISS index found — skipping bootstrap.")
        return

    pdfs = list(TEMP_DOCS_DIR.glob("*.pdf")) if TEMP_DOCS_DIR.exists() else []
    if not pdfs:
        logger.warning("No PDFs found in %s — index will be empty.", TEMP_DOCS_DIR)
        return

    logger.info("FAISS index missing — bootstrapping from %d PDF(s) in %s", len(pdfs), TEMP_DOCS_DIR)
    for pdf_path in pdfs:
        # Skip already-processed files
        if processor.is_file_processed(pdf_path):
            logger.info("  [skip] already processed: %s", pdf_path.name)
            continue

        logger.info("  [index] %s", pdf_path.name)
        with open(pdf_path, "rb") as f:
            buf = BytesIO(f.read())

        try:
            ok = processor.process_pdf_from_buffer(
                buffer=buf,
                filename=pdf_path.name,
                summary=f"{pdf_path.stem} document",
                keep_file=True,   # don't delete the source file from temp_uploaded_docs
            )
            if ok:
                logger.info("  [ok] indexed %s", pdf_path.name)
            else:
                logger.warning("  [fail] could not index %s", pdf_path.name)
        except Exception as exc:
            logger.error("  [error] %s — %s", pdf_path.name, exc)


# ---------------------------------------------------------------------------
# Data model (plain dicts — no Pydantic dependency needed when run standalone)
# ---------------------------------------------------------------------------

def _make_test_case(question: str, expected_doc: str, expected_page: Optional[int] = None) -> dict:
    return {
        "question": question,
        "expected_doc": expected_doc,
        "expected_page": expected_page,
    }


# ---------------------------------------------------------------------------
# Core evaluation logic
# ---------------------------------------------------------------------------

def _doc_matches(doc_metadata: dict, expected_doc: str, expected_page: Optional[int]) -> bool:
    """
    Check whether a retrieved document chunk matches the expected document.
    Uses partial filename matching (case-insensitive).
    Optionally checks page number if `expected_page` is provided.
    """
    source = doc_metadata.get("source", "")
    filename = Path(source).name.lower()
    expected_lower = expected_doc.lower()

    # Allow partial matches (e.g. "dress code" matches "Pership Dress Code Policy.pdf")
    doc_ok = expected_lower in filename or filename in expected_lower

    if not doc_ok:
        return False

    if expected_page is not None:
        page_label = str(doc_metadata.get("page_label", ""))
        page_number = doc_metadata.get("page_number", None)
        page_ok = (str(expected_page) == page_label) or (expected_page == page_number)
        return page_ok

    return True


def evaluate_embeddings(
    test_cases: List[Dict[str, Any]],
    k: int = 6,
    max_distance: float = 1.5,
) -> Dict[str, Any]:
    """
    Run the full evaluation suite against the current FAISS index.

    Args:
        test_cases:   List of test case dicts with keys:
                        - question      (str, required)
                        - expected_doc  (str, required)
                        - expected_page (int, optional)
        k:            Number of results to retrieve per query (default 6).
        max_distance: L2 distance threshold passed to query_documents.

    Returns:
        dict with keys:
          - summary:      aggregate metrics (hit_rate, mrr, total, passed, failed)
          - per_question: per-test-case breakdown
          - generated_at: ISO timestamp
    """
    processor = DocumentProcessor()
    bootstrap_index(processor)  # rebuild index if it was cleared/never built
    results_detail = []
    reciprocal_ranks = []
    hits = 0

    for idx, tc in enumerate(test_cases, 1):
        question = tc["question"]
        expected_doc = tc["expected_doc"]
        expected_page = tc.get("expected_page", None)

        logger.info(f"\n[{idx}/{len(test_cases)}] Q: {question!r}")
        logger.info(f"  Expected doc : {expected_doc!r}  page={expected_page}")

        # --- Retrieve with raw question ---
        retrieved = processor.query_documents(question, k=k, max_distance=max_distance)

        # --- Collect L2 scores for diagnostics (re-query with scores) ---
        try:
            raw_scores = processor.vector_db.similarity_search_with_score(question, k=k)
            score_values = [float(s) for _, s in raw_scores]
            score_stats = {
                "min":  round(min(score_values), 4),
                "max":  round(max(score_values), 4),
                "mean": round(sum(score_values) / len(score_values), 4),
            }
        except Exception:
            score_stats = {}

        # --- Check hit and compute reciprocal rank ---
        hit = False
        rank = None
        retrieved_pages = []
        for pos, doc in enumerate(retrieved, 1):
            src_name = Path(doc.metadata.get("source", "")).name
            page = doc.metadata.get("page_label", "?")
            retrieved_pages.append(f"{src_name} p.{page}")

            if not hit and _doc_matches(doc.metadata, expected_doc, expected_page):
                hit = True
                rank = pos

        if hit:
            hits += 1
            reciprocal_ranks.append(1.0 / rank)
            logger.info(f"  ✅ HIT at rank {rank}")
        else:
            reciprocal_ranks.append(0.0)
            logger.info(f"  ❌ MISS — retrieved: {retrieved_pages}")

        results_detail.append({
            "question":      question,
            "expected_doc":  expected_doc,
            "expected_page": expected_page,
            "hit":           hit,
            "rank":          rank,
            "retrieved_top": retrieved_pages[:k],
            "score_stats":   score_stats,
        })

    total = len(test_cases)
    hit_rate = round((hits / total) * 100, 2) if total else 0.0
    mrr = round(sum(reciprocal_ranks) / total, 4) if total else 0.0

    summary = {
        "total":    total,
        "passed":   hits,
        "failed":   total - hits,
        "hit_rate": f"{hit_rate}%",
        "mrr":      mrr,
        "k":        k,
        "max_distance_threshold": max_distance,
    }

    logger.info("\n" + "=" * 60)
    logger.info("📊  EMBEDDING EVALUATION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total questions : {total}")
    logger.info(f"  Hit Rate (top-{k}): {hit_rate}%  ({hits}/{total})")
    logger.info(f"  MRR             : {mrr:.4f}")
    logger.info("=" * 60)

    return {
        "summary":       summary,
        "per_question":  results_detail,
        "generated_at":  datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Default test suite — edit these to match your actual documents
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DEFAULT_TEST_CASES — covers all PDFs currently in temp_uploaded_docs.
# The bootstrap_index() function will auto-index them before querying.
# ---------------------------------------------------------------------------

DEFAULT_TEST_CASES = [
    # --- Pership Dress Code Policy ---
    _make_test_case(
        question="What is the dress code for male employees?",
        expected_doc="Pership Dress Code",
    ),
    _make_test_case(
        question="What should new recruits wear on their first day?",
        expected_doc="Pership Dress Code",
    ),
    # --- Mobile Phone Allowance Policy ---
    _make_test_case(
        question="What is the mobile phone allowance policy for employees?",
        expected_doc="Mobile Phone Allowance",
    ),
    # --- ICT Policy ---
    _make_test_case(
        question="What are the ICT usage rules for employees?",
        expected_doc="ICT Policy",
    ),
    _make_test_case(
        question="What is the acceptable use policy for company computers?",
        expected_doc="ICT Policy",
    ),
    # --- Finance SOP ---
    _make_test_case(
        question="What are the standard operating procedures for finance?",
        expected_doc="Finance Standard Operating",
    ),
    _make_test_case(
        question="How should petty cash be managed according to the finance SOP?",
        expected_doc="Finance Standard Operating",
    ),
    # --- Pership Holdings Overview ---
    _make_test_case(
        question="What are the main business units of Pership Holdings?",
        expected_doc="Pership Holdings Overview",
    ),
    # --- Pership Holdings Q&A ---
    _make_test_case(
        question="What is the vision of Pership Holdings?",
        expected_doc="Pership Holdings Q",
    ),
]



# ---------------------------------------------------------------------------
# Save report to file
# ---------------------------------------------------------------------------

def save_report(report: dict, output_path: str = "FAISS_Index/eval_report.json") -> str:
    """Save evaluation report as a JSON file and return the path."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"📄 Report saved to: {out.resolve()}")
    return str(out.resolve())


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Evaluate RAG embedding accuracy against the current FAISS index."
    )
    parser.add_argument(
        "--test-file",
        type=str,
        default=None,
        help="Path to a JSON file containing test cases (list of {question, expected_doc, expected_page?}). "
             "If omitted, the built-in DEFAULT_TEST_CASES are used.",
    )
    parser.add_argument(
        "--k", type=int, default=6,
        help="Number of results to retrieve per query (default: 6)."
    )
    parser.add_argument(
        "--max-distance", type=float, default=1.5,
        help="Maximum L2 distance threshold (default: 1.5). Lower = stricter."
    )
    parser.add_argument(
        "--output", type=str, default="FAISS_Index/eval_report.json",
        help="Where to save the JSON report (default: FAISS_Index/eval_report.json)."
    )
    args = parser.parse_args()

    if args.test_file:
        with open(args.test_file, "r", encoding="utf-8") as f:
            test_cases = json.load(f)
        logger.info(f"Loaded {len(test_cases)} test cases from {args.test_file}")
    else:
        test_cases = DEFAULT_TEST_CASES
        logger.info(f"Using {len(test_cases)} built-in default test cases.")

    report = evaluate_embeddings(test_cases, k=args.k, max_distance=args.max_distance)
    save_report(report, output_path=args.output)

    print("\n[OK] Evaluation complete.")
    print(f"   Hit Rate : {report['summary']['hit_rate']}")
    print(f"   MRR      : {report['summary']['mrr']}")
    print(f"   Report   : {args.output}")
