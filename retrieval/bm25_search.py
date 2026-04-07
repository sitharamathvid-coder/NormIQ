import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
 
import json
import pickle
from rank_bm25 import BM25Okapi
from config.settings import (
    NIST_JSON,
    HIPAA_JSON,
    GDPR_CSV,
    PENALTIES_JSON
)
import pandas as pd
import re
 
# ── Cache path ───────────────────────────────────────────────
CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "bm25_cache.pkl"
)
 
# ── Text tokeniser ───────────────────────────────────────────
def tokenise(text: str) -> list:
    """Convert text to lowercase tokens for BM25."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = text.split()
    return tokens
 
 
# ── Load and build BM25 indexes ─────────────────────────────
class BM25Search:
 
    def __init__(self):
        self.hipaa_corpus  = []
        self.gdpr_corpus   = []
        self.nist_corpus   = []
        self.hipaa_bm25    = None
        self.gdpr_bm25     = None
        self.nist_bm25     = None
        self._build_indexes()
 
 
    def _build_indexes(self):
 
        # ── Load from pickle cache if exists ─────────────────
        if os.path.exists(CACHE_PATH):
            print("Loading BM25 indexes from cache...")
            try:
                with open(CACHE_PATH, "rb") as f:
                    cached = pickle.load(f)
                self.hipaa_corpus = cached["hipaa_corpus"]
                self.gdpr_corpus  = cached["gdpr_corpus"]
                self.nist_corpus  = cached["nist_corpus"]
                self.hipaa_bm25   = cached["hipaa_bm25"]
                self.gdpr_bm25    = cached["gdpr_bm25"]
                self.nist_bm25    = cached["nist_bm25"]
                print(f"BM25 loaded from cache:")
                print(f"  HIPAA: {len(self.hipaa_corpus)} docs")
                print(f"  GDPR:  {len(self.gdpr_corpus)} docs")
                print(f"  NIST:  {len(self.nist_corpus)} docs")
                return
            except Exception as e:
                print(f"Cache load failed: {e} — rebuilding...")
                self.hipaa_corpus = []
                self.gdpr_corpus  = []
                self.nist_corpus  = []
 
        # ── Build from scratch ────────────────────────────────
        print("Building BM25 indexes from scratch...")
 
        # ── HIPAA ────────────────────────────────────────────
        with open(HIPAA_JSON) as f:
            hipaa_data = json.load(f)
 
        with open(PENALTIES_JSON) as f:
            penalties_data = json.load(f)
 
        all_hipaa = hipaa_data + penalties_data
 
        for chunk in all_hipaa:
            text     = chunk.get("text", "")
            metadata = chunk.get("metadata", {})
            self.hipaa_corpus.append({
                "id":         chunk.get("id", chunk.get("chunk_id", "")),
                "text":       text,
                "citation":   metadata.get("citation",
                              chunk.get("control_id", "")),
                "section":    metadata.get("section",
                              chunk.get("control_id", "")),
                "regulation": "HIPAA",
                "tokens":     tokenise(text)
            })
 
        # ── GDPR ─────────────────────────────────────────────
        df      = pd.read_csv(GDPR_CSV)
        grouped = df.groupby("article")
 
        for article_num, group in grouped:
            texts = []
            for _, row in group.iterrows():
                t = str(row["gdpr_text"]).replace("\n", " ").strip()
                if t and t != "nan":
                    texts.append(t)
 
            combined = " ".join(texts)
            citation = f"GDPR Article {int(article_num)}"
 
            self.gdpr_corpus.append({
                "id":         f"gdpr_article_{int(article_num)}",
                "text":       combined,
                "citation":   citation,
                "article":    int(article_num),
                "regulation": "GDPR",
                "tokens":     tokenise(combined)
            })
 
        # ── NIST ─────────────────────────────────────────────
        with open(NIST_JSON) as f:
            nist_data = json.load(f)
 
        for chunk in nist_data:
            text = chunk.get("text", "")
            self.nist_corpus.append({
                "id":         chunk["chunk_id"],
                "text":       text,
                "citation":   chunk["control_id"],
                "control_id": chunk["control_id"],
                "regulation": "NIST",
                "tokens":     tokenise(text)
            })
 
        # ── Build BM25 objects ────────────────────────────────
        self.hipaa_bm25 = BM25Okapi(
            [c["tokens"] for c in self.hipaa_corpus]
        )
        self.gdpr_bm25  = BM25Okapi(
            [c["tokens"] for c in self.gdpr_corpus]
        )
        self.nist_bm25  = BM25Okapi(
            [c["tokens"] for c in self.nist_corpus]
        )
 
        print(f"BM25 indexes built:")
        print(f"  HIPAA: {len(self.hipaa_corpus)} docs")
        print(f"  GDPR:  {len(self.gdpr_corpus)} docs")
        print(f"  NIST:  {len(self.nist_corpus)} docs")
 
        # ── Save to pickle cache ──────────────────────────────
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH, "wb") as f:
                pickle.dump({
                    "hipaa_corpus": self.hipaa_corpus,
                    "gdpr_corpus":  self.gdpr_corpus,
                    "nist_corpus":  self.nist_corpus,
                    "hipaa_bm25":   self.hipaa_bm25,
                    "gdpr_bm25":    self.gdpr_bm25,
                    "nist_bm25":    self.nist_bm25,
                }, f)
            print("BM25 indexes saved to cache!")
        except Exception as e:
            print(f"Cache save failed: {e}")
 
 
    def search(self, query: str,
               regulation: str,
               top_k: int = 5) -> list:
        """Search BM25 index for a regulation."""
 
        tokens = tokenise(query)
 
        if regulation == "HIPAA":
            scores = self.hipaa_bm25.get_scores(tokens)
            corpus = self.hipaa_corpus
        elif regulation == "GDPR":
            scores = self.gdpr_bm25.get_scores(tokens)
            corpus = self.gdpr_corpus
        elif regulation == "NIST":
            scores = self.nist_bm25.get_scores(tokens)
            corpus = self.nist_corpus
        else:
            return []
 
        import numpy as np
        top_indices = np.argsort(scores)[::-1][:top_k]
 
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                doc = corpus[idx]
                results.append({
                    "id":         doc["id"],
                    "score":      float(scores[idx]),
                    "text":       doc["text"],
                    "citation":   doc["citation"],
                    "regulation": doc["regulation"],
                    "metadata":   doc,
                    "source":     "bm25"
                })
 
        return results
 
 
    def search_multiple(self, query: str,
                        regulations: list,
                        top_k: int = 5) -> list:
        """Search multiple regulations and combine results."""
        all_results = []
 
        for regulation in regulations:
            results = self.search(query, regulation, top_k)
            all_results.extend(results)
            print(f"BM25 found {len(results)} chunks from {regulation}")
 
        all_results.sort(key=lambda x: x["score"], reverse=True)
        return all_results
 
 
# ── Singleton instance ───────────────────────────────────────
_bm25_instance = None
 
def get_bm25() -> BM25Search:
    global _bm25_instance
    if _bm25_instance is None:
        _bm25_instance = BM25Search()
    return _bm25_instance
 
 
# ════════════════════════════════════════════════════════════
# TEST
# ════════════════════════════════════════════════════════════
 
if __name__ == "__main__":
    print("Testing BM25 search...\n")
 
    bm25 = get_bm25()
 
    print("\nTest 1 — HIPAA breach notification")
    results = bm25.search(
        "breach notification deadline 60 days",
        "HIPAA", top_k=3
    )
    for r in results:
        print(f"  [{r['score']:.2f}] {r['citation']} — "
              f"{r['text'][:80]}...")
 
    print("\nTest 2 — GDPR breach notification")
    results = bm25.search(
        "breach notification 72 hours supervisory authority",
        "GDPR", top_k=3
    )
    for r in results:
        print(f"  [{r['score']:.2f}] {r['citation']} — "
              f"{r['text'][:80]}...")
 
    print("\nTest 3 — NIST access control")
    results = bm25.search(
        "access control account management",
        "NIST", top_k=3
    )
    for r in results:
        print(f"  [{r['score']:.2f}] {r['citation']} — "
              f"{r['text'][:80]}...")
 
    print("\nBM25 search test complete!")
 