# save as delete_hipaa_namespace.py
import os
from pinecone import Pinecone
from dotenv import load_dotenv

load_dotenv()
pc    = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
index = pc.Index("normiq")

# Check current count first
stats = index.describe_index_stats()
hipaa_count = stats["namespaces"].get("HIPAA", {}).get("vector_count", 0)
print(f"Current HIPAA vectors: {hipaa_count}")

# Delete the namespace
index.delete(delete_all=True, namespace="HIPAA")
print("✅ HIPAA namespace deleted")

# Verify
stats = index.describe_index_stats()
hipaa_count = stats["namespaces"].get("HIPAA", {}).get("vector_count", 0)
print(f"HIPAA vectors after delete: {hipaa_count}")