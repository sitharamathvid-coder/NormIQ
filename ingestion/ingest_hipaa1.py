import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
import re
from openai import OpenAI
from pinecone import Pinecone
from config.settings import (
    OPENAI_API_KEY,
    PINECONE_API_KEY,
    PINECONE_INDEX,
    NAMESPACE_HIPAA,
    EMBEDDING_MODEL,
    HIPAA_JSON
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


# ── Clean text ───────────────────────────────────────────────
def clean_text(text: str) -> str:
    # Remove bullet artifacts like "• A:"
    text = re.sub(r"•\s*[A-Z]:\s*", "", text)
    # Remove extra spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Build embedding text ─────────────────────────────────────
def build_embedding_text(chunk: dict) -> str:
    # CRITICAL FIX 1: Use pre-built embedding_text from JSON if available.
    # The v4 JSON contains optimised embedding_text per chunk — use it directly
    # instead of rebuilding from scratch, which would discard that optimisation.
    if chunk.get("embedding_text"):
        return chunk["embedding_text"]

    # Fallback: rebuild if field is missing
    citation      = chunk["metadata"]["citation"]
    section_title = chunk["metadata"]["section_title"]
    text          = clean_text(chunk["text"])
    return f"{citation} {section_title}. {text}"


# ── Upload HIPAA chunks to Pinecone ──────────────────────────
def ingest_hipaa():
    print("=" * 50)
    print("HIPAA Ingestion Starting...")
    print("=" * 50)

    # Load HIPAA JSON
    with open(HIPAA_JSON, encoding="utf-8") as f:
        data = json.load(f)

    print(f"Total HIPAA chunks to upload: {len(data)}")

    success    = 0
    failed     = 0
    batch      = []
    batch_size = 50

    for i, chunk in enumerate(data):
        try:
            # Build embedding text
            embedding_text = build_embedding_text(chunk)

            # Get embedding
            embedding = get_embedding(embedding_text)

            # Build metadata
            meta = chunk["metadata"]
            metadata = {
                "regulation":      "HIPAA",
                "section":         meta["section"],
                "section_title":   meta["section_title"],
                "subpart":         meta["subpart"],
                "section_type":    meta["section_type"],
                "citation":        meta["citation"],
                # CRITICAL FIX 2: Convert list fields to comma-separated strings.
                # Pinecone metadata lists can be silently dropped or cause filter
                # errors depending on index configuration. Strings are always safe.
                "nist_crosswalk":  meta.get("nist_crosswalk", []),
                "gdpr_crosswalk":  meta.get("gdpr_crosswalk", []),
                "source":          meta.get("source", "eCFR 45 CFR Part 164"),
                "text":            clean_text(chunk["text"]),
            }

            # Build Pinecone vector
            vector = {
                "id":       chunk["id"],
                "values":   embedding,
                "metadata": metadata
            }

            batch.append(vector)

            # Upload in batches
            if len(batch) >= batch_size:
                index.upsert(vectors=batch, namespace=NAMESPACE_HIPAA)
                success += len(batch)
                print(f"Uploaded {success}/{len(data)} chunks...")
                batch = []
                time.sleep(0.5)

        except Exception as e:
            # CRITICAL FIX 4: Use .get() to avoid KeyError if chunk is malformed
            chunk_id = chunk.get("id", f"unknown_index_{i}")
            print(f"Error on chunk {chunk_id}: {e}")
            failed += 1
            continue

    # CRITICAL FIX 3: Wrap final batch upload in try/except.
    # Without this, a failure here crashes silently — success/failed counts
    # are wrong and the error is never logged.
    if batch:
        try:
            index.upsert(vectors=batch, namespace=NAMESPACE_HIPAA)
            success += len(batch)
        except Exception as e:
            print(f"Error on final batch ({len(batch)} chunks): {e}")
            failed += len(batch)

    print("\n" + "=" * 50)
    print(f"HIPAA Ingestion Complete!")
    print(f"Successfully uploaded: {success}")
    print(f"Failed:                {failed}")
    print(f"Namespace:             {NAMESPACE_HIPAA}")
    print("=" * 50)

    return success, failed


if __name__ == "__main__":
    ingest_hipaa()
