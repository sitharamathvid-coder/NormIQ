import sys
sys.path.append('.')
from retrieval.pinecone_search import pinecone_search
from retrieval.bm25_search import get_bm25
from retrieval.cohere_rerank import hybrid_rerank, calculate_confidence

query = "GDPR Article 5 data processing principles"

# Pinecone
p_chunks = pinecone_search(query, ["GDPR"], top_k=5)
print("Pinecone scores:")
for c in p_chunks:
    print(f"  {c['score']:.3f} — {c['citation']}")

# BM25
bm25 = get_bm25()
b_chunks = bm25.search_multiple(query, ["GDPR"], top_k=5)
print("\nBM25 scores:")
for c in b_chunks:
    print(f"  {c['score']:.2f} — {c['citation']}")

# Rerank
reranked = hybrid_rerank(query, p_chunks, b_chunks, top_n=3)
print("\nCohere scores:")
for c in reranked:
    print(f"  {c.get('cohere_score',0):.3f} — {c['citation']}")

# Confidence
conf = calculate_confidence(reranked, p_chunks)
print(f"\nFinal confidence: {conf}")