import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI
from pinecone import Pinecone
from config.settings import (
    OPENAI_API_KEY,
    PINECONE_API_KEY,
    PINECONE_INDEX,
    EMBEDDING_MODEL,
    NAMESPACE_HIPAA,
    NAMESPACE_GDPR,
    NAMESPACE_NIST,
    RETRIEVAL_TOP_K
)

# ── Initialise clients ───────────────────────────────────────
openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc            = Pinecone(api_key=PINECONE_API_KEY)
index         = pc.Index(PINECONE_INDEX)


# ── Get embedding ────────────────────────────────────────────
def get_embedding(text: str) -> list:
    response = openai_client.embeddings.create(
        input = text,
        model = EMBEDDING_MODEL
    )
    return response.data[0].embedding


# ── Map regulation to namespace ──────────────────────────────
def get_namespace(regulation: str) -> str:
    mapping = {
        "HIPAA":      NAMESPACE_HIPAA,
        "GDPR":       NAMESPACE_GDPR,
        "NIST":       NAMESPACE_NIST,
        "PENALTIES":  NAMESPACE_HIPAA,
    }
    return mapping.get(regulation.upper(), NAMESPACE_HIPAA)


# ── Single namespace search ──────────────────────────────────
def vector_search(query: str, namespace: str,
                  top_k: int = RETRIEVAL_TOP_K) -> list:
    """Search one namespace and return chunks."""
    try:
        embedding = get_embedding(query)
        results   = index.query(
            vector    = embedding,
            top_k     = top_k,
            namespace = namespace,
            include_metadata = True
        )
        chunks = []
        for match in results.matches:
            chunks.append({
                "id":         match.id,
                "score":      match.score,
                "namespace":  namespace,
                "metadata":   match.metadata,
                "text":       match.metadata.get("text", ""),
                "citation":   match.metadata.get("citation", ""),
                "regulation": match.metadata.get("regulation", ""),
            })
        return chunks

    except Exception as e:
        print(f"Vector search error in {namespace}: {e}")
        return []


# ── Multi namespace search ───────────────────────────────────
def search_regulations(query: str,
                       regulations: list,
                       top_k: int = RETRIEVAL_TOP_K) -> list:
    """
    Search multiple namespaces based on detected regulations.
    Returns combined and sorted chunks.
    """
    all_chunks = []

    for regulation in regulations:
        namespace = get_namespace(regulation)
        chunks    = vector_search(query, namespace, top_k)
        all_chunks.extend(chunks)
        print(f"Retrieved {len(chunks)} chunks from {namespace}")

    # Sort by score — highest first
    all_chunks.sort(key=lambda x: x["score"], reverse=True)

    return all_chunks


# ── Crosswalk search ─────────────────────────────────────────
def crosswalk_search(chunks: list) -> list:
    """
    For each HIPAA chunk with nist_crosswalk —
    fetch the corresponding NIST chunks automatically.
    """
    extra_chunks = []
    fetched_ids  = set()

    for chunk in chunks:
        regulation     = chunk.get("regulation", "")
        nist_crosswalk = chunk.get("metadata", {}).get("nist_crosswalk", [])

        # Only do crosswalk for HIPAA chunks
        if regulation != "HIPAA" or not nist_crosswalk:
            continue

        for control_id in nist_crosswalk[:3]:  # max 3 controls per chunk
            if control_id in fetched_ids:
                continue

            try:
                # Search NIST namespace for this control
                results = index.query(
                    vector    = [0.0] * 1536,  # dummy vector
                    top_k     = 2,
                    namespace = NAMESPACE_NIST,
                    include_metadata = True,
                    filter    = {"control_id": {"$eq": control_id}}
                )

                for match in results.matches:
                    if match.id not in fetched_ids:
                        extra_chunks.append({
                            "id":         match.id,
                            "score":      0.75,  # crosswalk score
                            "namespace":  NAMESPACE_NIST,
                            "metadata":   match.metadata,
                            "text":       match.metadata.get("text", ""),
                            "citation":   match.metadata.get("citation",
                                          control_id),
                            "regulation": "NIST",
                            "crosswalk":  True
                        })
                        fetched_ids.add(match.id)

            except Exception as e:
                print(f"Crosswalk search error for {control_id}: {e}")
                continue

    if extra_chunks:
        print(f"Crosswalk found {len(extra_chunks)} additional NIST chunks")

    return extra_chunks


# ── Deduplicate chunks ───────────────────────────────────────
def deduplicate(chunks: list) -> list:
    """Remove duplicate chunks by ID."""
    seen = set()
    unique = []
    for chunk in chunks:
        if chunk["id"] not in seen:
            seen.add(chunk["id"])
            unique.append(chunk)
    return unique


# ── Main search function ─────────────────────────────────────
def pinecone_search(query: str,
                    regulations: list,
                    use_crosswalk: bool = False,
                    top_k: int = RETRIEVAL_TOP_K) -> list:
    """
    Full Pinecone search:
    1. Vector search across regulation namespaces
    2. Optional crosswalk search
    3. Deduplicate
    4. Return top_k chunks
    """
    # Step 1 — Vector search
    chunks = search_regulations(query, regulations, top_k)

    # Step 2 — Crosswalk search (if needed)
    if use_crosswalk:
        extra = crosswalk_search(chunks)
        chunks.extend(extra)

    # Step 3 — Deduplicate
    chunks = deduplicate(chunks)

    # Step 4 — Return top chunks
    return chunks[:top_k]


# ════════════════════════════════════════════════════════════
# TEST
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing Pinecone search...\n")

    # Test 1 — HIPAA search
    print("Test 1 — HIPAA breach notification")
    chunks = pinecone_search(
        query       = "What is the HIPAA breach notification deadline?",
        regulations = ["HIPAA"],
        top_k       = 3
    )
    for c in chunks:
        print(f"  [{c['score']:.3f}] {c['citation']} — {c['text'][:80]}...")

    print()

    # Test 2 — GDPR search
    print("Test 2 — GDPR breach notification")
    chunks = pinecone_search(
        query       = "What is the GDPR breach notification deadline?",
        regulations = ["GDPR"],
        top_k       = 3
    )
    for c in chunks:
        print(f"  [{c['score']:.3f}] {c['citation']} — {c['text'][:80]}...")

    print()

    # Test 3 — Multi regulation
    print("Test 3 — Both HIPAA and GDPR")
    chunks = pinecone_search(
        query       = "breach notification deadline",
        regulations = ["HIPAA", "GDPR"],
        top_k       = 4
    )
    for c in chunks:
        print(f"  [{c['score']:.3f}] {c['regulation']:5} — "
              f"{c['citation']} — {c['text'][:60]}...")

    print("\nPinecone search test complete!")