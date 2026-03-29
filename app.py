import os
import shutil
import json
import asyncio
from datetime import date
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from sqlalchemy.orm import Session
from sqlalchemy import func

# Import our perfectly tuned RAG engine
from rag_pipeline import NormIQRAGPipeline

# Import Database Setup
from database import get_db, AuditLog

# Dynamic upload function
from ingestion.ingest_step1_hipaa import process_and_upload_dynamic

app = FastAPI(title="NormIQ Enterprise API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize pipeline once on startup
pipeline = NormIQRAGPipeline()

class QueryRequest(BaseModel):
    query: str

@app.get("/")
def health_check():
    return {"status": "NormIQ Core Engine is Online."}

@app.post("/query")
async def ask_question(req: QueryRequest):
    """Answers compliance questions using the high-faithfulness tuning."""
    print(f"[API Hit] /query -> {req.query}")
    try:
        response = await pipeline.query(req.query)
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline Error: {str(e)}")

@app.post("/ingest")
async def upload_document(
    regulation: str = Form(...),
    file: UploadFile = File(...)
):
    print(f"[API Hit] /ingest -> Received {file.filename} for {regulation}")
    raw_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "raw")
    os.makedirs(raw_dir, exist_ok=True)
    file_path = os.path.join(raw_dir, file.filename)
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    try:
        if regulation.upper() == "HIPAA":
            chunk_count = process_and_upload_dynamic(file_path)
            return {
                "status": "success",
                "chunks_upserted": chunk_count,
                "message": f"Successfully indexed {chunk_count} chunks into Pinecone's HIPAA namespace."
            }
        else:
            raise HTTPException(status_code=400, detail="Only HIPAA dynamic ingestion is supported in Version 1.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion Error: {str(e)}")

# =====================================================================
# NEW ENTERPRISE ENDPOINTS
# =====================================================================

@app.get("/stats")
def get_system_stats(db: Session = Depends(get_db)):
    """Returns DB metrics and Pinecone vector counts for Sidebar."""
    try:
        total_queries = db.query(func.count(AuditLog.id)).scalar() or 0
        avg_conf = db.query(func.avg(AuditLog.confidence)).scalar() or 0.0
        
        # Pinecone Namespace stats
        hipaa_docs, gdpr_docs, nist_docs = 0, 0, 0
        try:
            pc_stats = pipeline.pinecone_index.describe_index_stats()
            ns = pc_stats.get("namespaces", {})
            hipaa_docs = ns.get("HIPAA", {}).get("vector_count", 0)
            gdpr_docs = ns.get("GDPR", {}).get("vector_count", 0)
            nist_docs = ns.get("NIST", {}).get("vector_count", 0)
        except Exception as e:
            print(f"Warning: Pinecone stats failed: {e}")
            
        return {
            "total_queries": total_queries,
            "avg_confidence": round(avg_conf, 3),
            "vectors_hipaa": hipaa_docs,
            "vectors_gdpr": gdpr_docs,
            "vectors_nist": nist_docs
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/audit")
def fetch_audit_logs(db: Session = Depends(get_db)):
    """Fetches the latest 500 queries for the Audit Log Dataframe."""
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(500).all()
    # Serialize to JSON-friendly format
    results = []
    for log in logs:
        results.append({
            "id": log.id,
            "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "question": log.question,
            "regulation": log.regulation,
            "confidence": log.confidence,
            "status": log.status,
            "process_time_sec": log.process_time_sec,
            "from_cache": log.from_cache
        })
    return {"logs": results}

@app.post("/evaluate")
async def run_evaluation():
    """Triggers the asynchronous Ragas Evaluation script."""
    # Run securely in a separate subprocess to avoid blocking the API loop
    try:
        process = await asyncio.create_subprocess_shell("python run_evaluation.py")
        await process.wait()
        
        # Load the newly outputted stats
        results_file = os.path.join("data", "ragas_baseline_results.json")
        if os.path.exists(results_file):
            with open(results_file, "r") as f:
                return json.load(f)
        else:
            raise Exception("No evaluation results were spawned.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eval crashed: {str(e)}")


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
