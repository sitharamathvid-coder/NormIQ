import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from openai import OpenAI
from pinecone import Pinecone
from config.settings import (
    OPENAI_API_KEY,
    PINECONE_API_KEY,
    PINECONE_INDEX,
    NAMESPACE_HIPAA,
    EMBEDDING_MODEL,
    PENALTIES_JSON
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


# ── Upload penalties to Pinecone HIPAA namespace ─────────────
def ingest_penalties():
    print("=" * 50)
    print("HIPAA Penalties Ingestion Starting...")
    print("=" * 50)

    # Load penalties JSON
    with open(PENALTIES_JSON, encoding="utf-8") as f:
        data = json.load(f)

    print(f"Total penalty chunks to upload: {len(data)}")

    success    = 0
    failed     = 0
    batch      = []
    batch_size = 50

    for i, chunk in enumerate(data):
        try:
            # Get embedding
            embedding = get_embedding(chunk["embedding_text"])

            # Build metadata
            meta = chunk.get("metadata", {})
            metadata = {
                "regulation":      "HIPAA",
                "section":         chunk["control_id"],
                "section_title":   chunk["title"],
                "subpart":         "Enforcement",
                "section_type":    "Civil Money Penalties",
                "citation":        meta.get("citation", chunk["control_id"]),
                "nist_crosswalk":  chunk.get("hipaa_crosswalk", []),
                "text":            chunk["text"],
                "keywords":        meta.get("keywords", []),
                "domain":          chunk["domain"],
                "framework":       chunk["framework"],
            }

            # Add penalty specific fields if present
            if "penalty_tier" in meta:
                metadata["penalty_tier"] = meta["penalty_tier"]
            if "max_per_violation" in meta:
                metadata["max_per_violation"] = meta["max_per_violation"]
            if "min_per_violation" in meta:
                metadata["min_per_violation"] = meta["min_per_violation"]
            if "max_per_year" in meta:
                metadata["max_per_year"] = meta["max_per_year"]

            # Build Pinecone vector
            vector = {
                "id":       chunk["chunk_id"],
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
            print(f"Error on chunk {chunk['chunk_id']}: {e}")
            failed += 1
            continue

    # Upload remaining
    if batch:
        index.upsert(vectors=batch, namespace=NAMESPACE_HIPAA)
        success += len(batch)

    print("\n" + "=" * 50)
    print(f"Penalties Ingestion Complete!")
    print(f"Successfully uploaded: {success}")
    print(f"Failed:                {failed}")
    print(f"Namespace:             {NAMESPACE_HIPAA}")
    print(f"Note: Penalties added to HIPAA namespace")
    print("=" * 50)

    return success, failed


if __name__ == "__main__":
    ingest_penalties()