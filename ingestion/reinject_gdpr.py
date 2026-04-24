import sys, os
sys.path.append('.')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import json
from openai import OpenAI
from pinecone import Pinecone
from config.settings import OPENAI_API_KEY, PINECONE_API_KEY, PINECONE_INDEX

# Load
with open('data/gdpr_rechunked.json') as f:
    chunks = json.load(f)

print(f"Total chunks to upload: {len(chunks)}")

# Clients
client = OpenAI(api_key=OPENAI_API_KEY)
pc     = Pinecone(api_key=PINECONE_API_KEY)
index  = pc.Index(PINECONE_INDEX)

# Delete existing GDPR namespace
print("Deleting existing GDPR namespace...")
index.delete(delete_all=True, namespace="GDPR")
print("GDPR namespace cleared!")

# Embed and upload in batches of 50
BATCH = 50
vectors = []

for i, chunk in enumerate(chunks):
    resp = client.embeddings.create(
        model = "text-embedding-3-small",
        input = chunk["text"]
    )
    embedding = resp.data[0].embedding
    chunk["metadata"]["text"] = chunk["text"]

    vectors.append({
        "id":       chunk["id"],
        "values":   embedding,
        "metadata": chunk["metadata"]
    })

    if len(vectors) == BATCH:
        index.upsert(vectors=vectors, namespace="GDPR")
        print(f"Uploaded {i+1}/{len(chunks)} chunks...")
        vectors = []

# Upload remaining
if vectors:
    index.upsert(vectors=vectors, namespace="GDPR")
    print(f"Uploaded final batch!")

print(f"\n✅ GDPR rechunked — {len(chunks)} sub-paragraph chunks uploaded!")
print("Now rebuild BM25 cache — delete data/bm25_cache.pkl")