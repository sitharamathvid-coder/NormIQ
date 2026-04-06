import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import json
from openai import OpenAI
from config.settings import OPENAI_API_KEY, LLM_MODEL
from agent.prompts.query_understanding_prompt import MULTI_QUERY_PROMPT
from retrieval.pinecone_search import pinecone_search
from retrieval.bm25_search     import get_bm25
from retrieval.cohere_rerank   import hybrid_rerank, calculate_confidence
from config.settings           import COHERE_TOP_N

# ── Initialise OpenAI ────────────────────────────────────────
client = OpenAI(api_key=OPENAI_API_KEY)


# ── Generate query variations ────────────────────────────────
def generate_queries(question: str, regulations: list) -> list:
    """Generate 3 rephrased versions of the question."""
    try:
        prompt = MULTI_QUERY_PROMPT.format(
            question    = question,
            regulations = ", ".join(regulations)
        )

        response = client.chat.completions.create(
            model       = LLM_MODEL,
            messages    = [{"role": "user", "content": prompt}],
            temperature = 0.3
        )

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        queries = json.loads(raw)

        # Always include original question
        all_queries = [question] + queries
        print(f"Generated {len(all_queries)} query variations")
        return all_queries

    except Exception as e:
        print(f"Query generation error: {e}")
        # Fallback — return original only
        return [question]


# ── Deduplicate chunks ───────────────────────────────────────
def deduplicate_chunks(all_chunks: list) -> list:
    """Remove duplicate chunks keeping highest score."""
    seen    = {}
    for chunk in all_chunks:
        cid = chunk["id"]
        if cid not in seen:
            seen[cid] = chunk
        else:
            # Keep highest score
            if chunk.get("score", 0) > seen[cid].get("score", 0):
                seen[cid] = chunk
    return list(seen.values())


# ── Multi query search ───────────────────────────────────────
def multi_query_search(question: str,
                       regulations: list,
                       top_n: int = COHERE_TOP_N) -> dict:
    """
    Tool 3 — Multi Query Search
    Only called when hybrid search chunks are weak.
    1. Generate 3 query variations
    2. Search each variation
    3. Merge all results
    4. Rerank with Cohere
    """
    print(f"\nMulti-query search triggered for: '{question[:60]}'")

    # Step 1 — Generate variations
    queries = generate_queries(question, regulations)

    all_pinecone = []
    all_bm25     = []
    bm25         = get_bm25()

    # Step 2 — Search each query variation
    for i, query in enumerate(queries):
        print(f"Searching variation {i+1}/{len(queries)}: "
              f"'{query[:50]}'")

        # Pinecone search
        p_chunks = pinecone_search(
            query       = query,
            regulations = regulations,
            top_k       = 10
        )
        all_pinecone.extend(p_chunks)

        # BM25 search
        b_chunks = bm25.search_multiple(
            query       = query,
            regulations = regulations,
            top_k       = 5
        )
        all_bm25.extend(b_chunks)

    # Step 3 — Deduplicate
    all_pinecone = deduplicate_chunks(all_pinecone)
    all_bm25     = deduplicate_chunks(all_bm25)

    print(f"After dedup: Pinecone={len(all_pinecone)}, "
          f"BM25={len(all_bm25)}")

    # Step 4 — Rerank with Cohere
    reranked = hybrid_rerank(
        query           = question,
        pinecone_chunks = all_pinecone,
        bm25_chunks     = all_bm25,
        top_n           = top_n
    )

    # Step 5 — Calculate confidence
    confidence = calculate_confidence(reranked, all_pinecone, "lookup")

    print(f"Multi-query confidence: {confidence}")

    return {
        "chunks":      reranked,
        "confidence":  confidence,
        "chunks_good": True,
        "count":       len(reranked),
        "queries_used": len(queries)
    }


# ════════════════════════════════════════════════════════════
# TEST
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing multi-query search...\n")

    result = multi_query_search(
        question    = "What happens if we violate HIPAA?",
        regulations = ["HIPAA"],
        top_n       = 6
    )

    print(f"\nResults:")
    print(f"  Queries used:  {result['queries_used']}")
    print(f"  Chunks found:  {result['count']}")
    print(f"  Confidence:    {result['confidence']}")

    print(f"\nTop 3 chunks:")
    for c in result["chunks"][:3]:
        print(f"  [{c.get('cohere_score', 0):.3f}] "
              f"{c['citation']} — {c['text'][:70]}...")

    print("\nMulti-query test complete!")