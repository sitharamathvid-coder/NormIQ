import requests
import json
import time

API_URL = "http://localhost:8000"

def run_tests():
    try:
        print("🔍 1. Testing Backend Health Check...")
        r1 = requests.get(f"{API_URL}/")
        assert r1.status_code == 200
        print("   ✅ Passed!")

        print("\n🔍 2. Testing /stats (Pinecone & SQLite Aggregation)...")
        r2 = requests.get(f"{API_URL}/stats")
        assert r2.status_code == 200
        assert "total_queries" in r2.json()
        print(f"   ✅ Passed! (Pinecone vectors found: HIPAA={r2.json().get('vectors_hipaa')})")

        print("\n🔍 3. Testing /query (RAG Pipeline)...")
        r3 = requests.post(f"{API_URL}/query", json={"query": "What is the penalty for a HIPAA violation?"})
        assert r3.status_code == 200
        data = r3.json()
        assert "answer" in data
        assert "confidence" in data
        print(f"   ✅ Passed! (Generated response with {data.get('confidence')} confidence).")
        
        # Give the background DB logger a split second
        time.sleep(1)

        print("\n🔍 4. Testing /audit (Database Persistence)...")
        r4 = requests.get(f"{API_URL}/audit")
        assert r4.status_code == 200
        logs = r4.json().get("logs", [])
        assert len(logs) > 0 
        print(f"   ✅ Passed! ({len(logs)} rows successfully read from SQL database).")

        print("\n==================================")
        print("✅ ALL ENTERPRISE SYSTEMS VERIFIED")
        print("==================================")
    except AssertionError as e:
        print(f"\n❌ Test Failed: API returned unexpected result.")
    except Exception as e:
        print(f"\n❌ Connectivity Error: Is uvicorn running? Details: {e}")

if __name__ == "__main__":
    run_tests()