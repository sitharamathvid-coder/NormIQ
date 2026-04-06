import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

from retrieval.pinecone_search import pinecone_search
from retrieval.bm25_search     import get_bm25
from retrieval.cohere_rerank   import hybrid_rerank, calculate_confidence
from config.settings           import RETRIEVAL_TOP_K, COHERE_TOP_N


def hybrid_search(query: str,
                  regulations: list,
                  use_crosswalk: bool = False,
                  top_k: int = RETRIEVAL_TOP_K,
                  intent: str = "lookup") -> dict:

    import re

    # Detect if question asks for specific article/section
    is_specific = bool(
        re.search(r'article\s+\d+', query.lower()) or
        re.search(r'§\s*\d+', query.lower()) or
        re.search(r'section\s+\d+', query.lower()) or
        re.search(r'\bac-\d+\b', query.lower()) or
        re.search(r'\bra-\d+\b', query.lower()) or
        re.search(r'\bau-\d+\b', query.lower())
    )

    # Step 1 — Pinecone always
    pinecone_chunks = pinecone_search(
        query         = query,
        regulations   = regulations,
        use_crosswalk = use_crosswalk,
        top_k         = top_k
    )

    # Step 2 — BM25 only for general questions
    bm25_chunks = []
    if not is_specific:
        bm25        = get_bm25()
        bm25_chunks = bm25.search_multiple(
            query       = query,
            regulations = regulations,
            top_k       = 5
        )
        print(f"BM25 used — general question")
    else:
        print(f"BM25 skipped — specific article/section detected")

    # Step 3 — Merge + Cohere rerank
    reranked = hybrid_rerank(
        query           = query,
        pinecone_chunks = pinecone_chunks,
        bm25_chunks     = bm25_chunks,
        top_n           = COHERE_TOP_N
    )

    # Step 4 — Confidence
    confidence    = calculate_confidence(reranked, pinecone_chunks, intent)
    chunks_good   = _are_chunks_relevant(reranked)

    print(f"Chunks quality: {'Good' if chunks_good else 'Weak'}")
    print(f"Confidence: {confidence}")

    return {
        "chunks":      reranked,
        "confidence":  confidence,
        "chunks_good": chunks_good,
        "count":       len(reranked),
        "bm25_used":   not is_specific
    }


def _are_chunks_relevant(chunks: list,
                         threshold: float = 0.30) -> bool:
    """
    Agent decision — are retrieved chunks good enough?
    If top chunk Cohere score < threshold → chunks are weak
    → trigger multi-query
    """
    if not chunks:
        return False
    top_score = chunks[0].get("cohere_score", 0.0)
    return top_score >= threshold


# ════════════════════════════════════════════════════════════
# TEST
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing hybrid search...\n")

    # Test 1 — Simple HIPAA
    print("=" * 50)
    print("Test 1 — HIPAA breach notification")
    result = hybrid_search(
        query       = "What is the HIPAA breach notification deadline?",
        regulations = ["HIPAA"]
    )
    print(f"\nResults:")
    print(f"  Chunks found:  {result['count']}")
    print(f"  Confidence:    {result['confidence']}")
    print(f"  Chunks good:   {result['chunks_good']}")
    print(f"\nTop 3 chunks:")
    for c in result["chunks"][:3]:
        print(f"  [{c.get('cohere_score', 0):.3f}] "
              f"{c['citation']} — {c['text'][:70]}...")

    # Test 2 — Cross regulation
    print("\n" + "=" * 50)
    print("Test 2 — HIPAA + GDPR comparison")
    result = hybrid_search(
        query       = "breach notification deadline",
        regulations = ["HIPAA", "GDPR"]
    )
    print(f"\nResults:")
    print(f"  Chunks found:  {result['count']}")
    print(f"  Confidence:    {result['confidence']}")
    print(f"\nTop 3 chunks:")
    for c in result["chunks"][:3]:
        print(f"  [{c.get('cohere_score', 0):.3f}] "
              f"{c.get('regulation','')}: "
              f"{c['citation']} — {c['text'][:60]}...")

    print("\nHybrid search test complete!")