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
    NAMESPACE_NIST,
    EMBEDDING_MODEL,
    NIST_JSON
)

# ── Initialise clients ───────────────────────────────────────
openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc            = Pinecone(api_key=PINECONE_API_KEY)
index         = pc.Index(PINECONE_INDEX)


# ── Get embedding for a text ─────────────────────────────────
def get_embedding(text: str) -> list:
    response = openai_client.embeddings.create(
        input = text,
        model = EMBEDDING_MODEL
    )
    return response.data[0].embedding


# ── Upload NIST chunks to Pinecone ───────────────────────────
def ingest_nist():
    print("=" * 50)
    print("NIST Ingestion Starting...")
    print("=" * 50)

    # Load NIST JSON
    with open(NIST_JSON) as f:
        data = json.load(f)

    print(f"Total NIST chunks to upload: {len(data)}")

    success = 0
    failed  = 0
    batch   = []
    batch_size = 50  # upload 50 at a time

    for i, chunk in enumerate(data):

        try:
            # Get embedding — use embedding_text for better quality
            embedding = get_embedding(chunk["embedding_text"])

            # Build metadata
            metadata = {
                "regulation":      "NIST",
                "control_id":      chunk["control_id"],
                "title":           chunk["title"],
                "control_family":  chunk["control_family"],
                "domain":          chunk["domain"],
                "control_prefix":  chunk["control_prefix"],
                "framework":       chunk["framework"],
                "text":            chunk["text"],
                "hipaa_crosswalk": chunk.get("hipaa_crosswalk", []),
                "chunk_id":        chunk["chunk_id"],
            }

            # Build Pinecone vector
            vector = {
                "id":       chunk["chunk_id"],
                "values":   embedding,
                "metadata": metadata
            }

            batch.append(vector)

            # Upload in batches of 50
            if len(batch) >= batch_size:
                index.upsert(vectors=batch, namespace=NAMESPACE_NIST)
                success += len(batch)
                print(f"Uploaded {success}/{len(data)} chunks...")
                batch = []
                time.sleep(0.5)  # avoid rate limit

        except Exception as e:
            print(f"Error on chunk {chunk['chunk_id']}: {e}")
            failed += 1
            continue

    # Upload remaining batch
    if batch:
        index.upsert(vectors=batch, namespace=NAMESPACE_NIST)
        success += len(batch)

    print("\n" + "=" * 50)
    print(f"NIST Ingestion Complete!")
    print(f"Successfully uploaded: {success}")
    print(f"Failed:                {failed}")
    print(f"Namespace:             {NAMESPACE_NIST}")
    print("=" * 50)

    return success, failed


if __name__ == "__main__":
    ingest_nist()