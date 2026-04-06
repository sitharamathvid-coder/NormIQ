import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cohere
from config.settings import (
    COHERE_API_KEY,
    COHERE_RERANK_MODEL,
    COHERE_TOP_N
)

# ── Initialise Cohere client ─────────────────────────────────
co = cohere.Client(api_key=COHERE_API_KEY)


# ── Merge Pinecone + BM25 results ───────────────────────────
def merge_results(pinecone_chunks: list,
                  bm25_chunks: list) -> list:
    """
    Combine Pinecone and BM25 results.
    Remove duplicates by ID.
    Pinecone results take priority.
    """
    seen     = set()
    combined = []

    # Add Pinecone chunks first
    for chunk in pinecone_chunks:
        if chunk["id"] not in seen:
            seen.add(chunk["id"])
            chunk["source"] = "pinecone"
            combined.append(chunk)

    # Add BM25 chunks — skip duplicates
    for chunk in bm25_chunks:
        if chunk["id"] not in seen:
            seen.add(chunk["id"])
            chunk["source"] = "bm25"
            combined.append(chunk)

    print(f"Merged {len(combined)} unique chunks "
          f"(Pinecone: {len(pinecone_chunks)}, "
          f"BM25: {len(bm25_chunks)})")

    return combined


# ── Cohere rerank ────────────────────────────────────────────
def rerank(query: str,
           chunks: list,
           top_n: int = COHERE_TOP_N) -> list:
    """
    Rerank chunks using Cohere.
    Returns top_n most relevant chunks with cohere scores.
    """
    if not chunks:
        print("No chunks to rerank!")
        return []

    # Extract texts for reranking
    documents = [chunk["text"] for chunk in chunks]

    try:
        response = co.rerank(
            query     = query,
            documents = documents,
            model     = COHERE_RERANK_MODEL,
            top_n     = min(top_n, len(chunks))
        )

        # Build reranked results
        reranked = []
        for result in response.results:
            chunk = chunks[result.index].copy()
            chunk["cohere_score"]    = result.relevance_score
            chunk["original_score"] = chunk.get("score", 0)
            reranked.append(chunk)

        print(f"Cohere reranked {len(chunks)} → top {len(reranked)} chunks")
        return reranked

    except Exception as e:
        print(f"Cohere rerank error: {e}")
        # Fallback — return top chunks by original score
        chunks.sort(key=lambda x: x.get("score", 0), reverse=True)
        return chunks[:top_n]


# ── Full hybrid rerank pipeline ──────────────────────────────
def hybrid_rerank(query: str,
                  pinecone_chunks: list,
                  bm25_chunks: list,
                  top_n: int = COHERE_TOP_N) -> list:
    """
    Full pipeline:
    1. Merge Pinecone + BM25
    2. Rerank with Cohere
    3. Return top_n chunks
    """
    # Step 1 — Merge
    merged = merge_results(pinecone_chunks, bm25_chunks)

    if not merged:
        print("No chunks found for reranking!")
        return []

    # Step 2 — Rerank
    reranked = rerank(query, merged, top_n)

    return reranked


# ── Calculate confidence from Cohere score ───────────────────
def calculate_confidence(reranked_chunks: list,
                         pinecone_chunks: list,
                         intent: str = "lookup") -> float:
    """
    Week 2 confidence formula:
    confidence = (cohere_score × 0.50) + (retrieval_score × 0.50)
    """
    if not reranked_chunks:
        return 0.0

    # Top chunk scores
    top_chunk        = reranked_chunks[0]
    cohere_score     = top_chunk.get("cohere_score", 0.0)
    retrieval_score  = top_chunk.get("original_score", 0.0)

    # Normalise retrieval score to 0-1 range
    # Pinecone cosine scores are already 0-1
    # BM25 scores can be higher — normalise
    if top_chunk.get("source") == "bm25":
        # BM25 scores typically 0-30 — normalise
        max_bm25        = 30.0
        retrieval_score = min(retrieval_score / max_bm25, 1.0)

    confidence = (cohere_score * 0.50) + (retrieval_score * 0.50)
    confidence = round(min(confidence, 1.0), 3)

    print(f"Confidence: {confidence} "
          f"(Cohere: {cohere_score:.3f}, "
          f"Retrieval: {retrieval_score:.3f})")

    return confidence


# ════════════════════════════════════════════════════════════
# TEST
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Cohere rerank...\n")

    # Simulate chunks from Pinecone and BM25
    mock_pinecone = [
        {
            "id": "hipaa_164_404_1",
            "score": 0.876,
            "text": "For breaches affecting 500 or more individuals "
                    "notify the Secretary without unreasonable delay "
                    "and within 60 calendar days.",
            "citation": "45 CFR § 164.404",
            "regulation": "HIPAA"
        },
        {
            "id": "hipaa_164_400_1",
            "score": 0.821,
            "text": "The requirements of this subpart apply to "
                    "covered entities and business associates.",
            "citation": "45 CFR § 164.400",
            "regulation": "HIPAA"
        },
    ]

    mock_bm25 = [
        {
            "id": "gdpr_article_33",
            "score": 24.83,
            "text": "In the case of a personal data breach, "
                    "the controller shall notify within 72 hours.",
            "citation": "GDPR Article 33",
            "regulation": "GDPR"
        },
        {
            "id": "hipaa_164_404_1",  # duplicate — should be removed
            "score": 19.31,
            "text": "Notify within 60 calendar days of discovery.",
            "citation": "45 CFR § 164.404",
            "regulation": "HIPAA"
        },
    ]

    query = "What is the breach notification deadline?"

    # Test hybrid rerank
    reranked = hybrid_rerank(query, mock_pinecone, mock_bm25, top_n=3)

    print("\nReranked results:")
    for i, chunk in enumerate(reranked):
        print(f"  {i+1}. [{chunk['cohere_score']:.3f}] "
              f"{chunk['citation']} — {chunk['text'][:60]}...")

    # Test confidence
    print()
    confidence = calculate_confidence(reranked, mock_pinecone)
    print(f"Final confidence score: {confidence}")

    print("\nCohere rerank test complete!")