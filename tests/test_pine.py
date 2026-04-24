import sys, os
sys.path.append('.')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pinecone import Pinecone
from config.settings import PINECONE_API_KEY, PINECONE_INDEX

pc    = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(PINECONE_INDEX)

# Fetch a known NIST chunk
results = index.query(
    vector           = [0.0] * 1536,
    top_k            = 3,
    namespace        = "NIST",
    include_metadata = True,
    filter           = {"control_id": {"$eq": "AC-1"}}
)

print("AC-1 chunks in Pinecone:")
for r in results.matches:
    print(f"ID: {r.id}")
    print(f"Metadata keys: {list(r.metadata.keys())}")
    print(f"control_id: {r.metadata.get('control_id', 'MISSING!')}")
    print(f"citation: {r.metadata.get('citation', 'MISSING!')}")
    print()