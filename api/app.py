import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn

from agent.agent     import run_agent
from database.db_manager import (
    audit_log_get_all,
    audit_log_get_pending,
    audit_log_update_officer,
    chat_history_get,
    chat_history_update_status
)
from config.settings import CONFIDENCE_THRESHOLD

# ── FastAPI app ──────────────────────────────────────────────
app = FastAPI(
    title       = "NormIQ — Compliance RAG API",
    description = "HIPAA · GDPR · NIST Compliance Q&A System",
    version     = "1.0.0"
)

# ── CORS — allow Streamlit and Telegram bot to call ──────────
app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


# ════════════════════════════════════════════════════════════
# REQUEST / RESPONSE MODELS
# ════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    question:  str
    user_id:   Optional[str] = "anonymous"
    role:      Optional[str] = "nurse"
    location:  Optional[str] = "US"


class QueryResponse(BaseModel):
    status:           str
    summary:          str
    answer:           str
    citations:        list
    confidence:       float
    regulation:       list
    ref_id:           Optional[str]
    conflict:         bool
    conflict_warning: str
    message:          str
    was_cached:       Optional[bool] = False


class OfficerActionRequest(BaseModel):
    ref_id:         str
    officer_id:     str
    action:         str        # "approved" or "rewritten"
    officer_answer: Optional[str] = None


# ════════════════════════════════════════════════════════════
# ROUTES
# ════════════════════════════════════════════════════════════

# ── Health check ─────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status":    "ok",
        "service":   "NormIQ Compliance RAG",
        "version":   "1.0.0",
        "threshold": CONFIDENCE_THRESHOLD
    }


# ── Main query endpoint ───────────────────────────────────────
@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest):
    try:
        result = run_agent(
            question = request.question,
            user_id  = request.user_id
        )
        return QueryResponse(
            status           = result["status"],
            summary          = result.get("summary", ""),
            answer           = result.get("answer", ""),
            citations        = result.get("citations", []),
            confidence       = result.get("confidence", 0.0),
            regulation       = result.get("regulation", []),
            ref_id           = result.get("ref_id"),
            conflict         = result.get("conflict", False),
            conflict_warning = result.get("conflict_warning", ""),
            message          = result.get("message", ""),
            was_cached       = result.get("was_cached", False)
        )
    except Exception as e:
        import traceback
        print(f"FULL ERROR: {traceback.format_exc()}")
        raise HTTPException(
            status_code = 500,
            detail      = f"Agent error: {str(e)}"
        )

# ── Officer action endpoint ───────────────────────────────────
@app.post("/officer/action")
def officer_action(request: OfficerActionRequest):
    try:
        if request.action not in ["approved", "rewritten"]:
            raise HTTPException(
                status_code = 400,
                detail      = "Action must be 'approved' or 'rewritten'"
            )

        if request.action == "rewritten" and not request.officer_answer:
            raise HTTPException(
                status_code = 400,
                detail      = "officer_answer required for rewritten action"
            )

        # Update audit log
        audit_log_update_officer(
            ref_id         = request.ref_id,
            officer_id     = request.officer_id,
            action         = request.action,
            officer_answer = request.officer_answer
        )

        # Update chat history
        chat_history_update_status(
            ref_id = request.ref_id,
            status = "answered"
        )

        # ── Update cache with confidence 1.0 ─────────────────
        # Officer verified → cache as 100% confident
        try:
            from database.db_manager import get_connection
            import psycopg2.extras
            import json as _json

            conn = get_connection()
            if conn:
                cur = conn.cursor(
                    cursor_factory=psycopg2.extras.RealDictCursor
                )

                # Get audit log entry
                cur.execute(
                    "SELECT * FROM audit_log WHERE ref_id = %s",
                    (request.ref_id,)
                )
                row = cur.fetchone()

                if row:
                    question = row["question"]
                    # Use officer answer if rewritten
                    # else use original AI answer
                    final_answer = (
                        request.officer_answer
                        if request.action == "rewritten"
                        else row["answer"]
                    )
                    citations  = row.get("citations", [])
                    regulation = row.get("regulation", "HIPAA")

                    cur.close()
                    conn.close()

                    # Save to cache with confidence 1.0
                    from database.db_manager import cache_set
                    cache_set(
                        question   = question,
                        answer     = final_answer,
                        citations  = citations if isinstance(citations, list) else [],
                        regulation = regulation,
                        confidence = 1.0   # ← officer verified!
                    )
                    print(f"Cache updated with confidence 1.0 "
                          f"for {request.ref_id}")
                else:
                    cur.close()
                    conn.close()

        except Exception as e:
            print(f"Cache update error: {e}")
            # Never fail officer action because of cache error

        return {
            "status":  "ok",
            "ref_id":  request.ref_id,
            "action":  request.action,
            "message": f"Answer {request.action} — cache updated to 1.0"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code = 500,
            detail      = f"Officer action error: {str(e)}"
        )



# ── Audit log endpoint ────────────────────────────────────────
@app.get("/audit")
def get_audit(limit: int = 100):
    """Get all audit log entries for admin dashboard."""
    try:
        logs = audit_log_get_all(limit=limit)
        return {
            "status": "ok",
            "count":  len(logs),
            "logs":   logs
        }
    except Exception as e:
        raise HTTPException(
            status_code = 500,
            detail      = f"Audit log error: {str(e)}"
        )


# ── Pending reviews endpoint ──────────────────────────────────
@app.get("/audit/pending")
def get_pending():
    """Get all questions pending officer review."""
    try:
        pending = audit_log_get_pending()
        return {
            "status":  "ok",
            "count":   len(pending),
            "pending": pending
        }
    except Exception as e:
        raise HTTPException(
            status_code = 500,
            detail      = f"Pending reviews error: {str(e)}"
        )

@app.get("/audit/ref/{ref_id}")
def get_audit_by_ref(ref_id: str):
    """Get single audit log entry by ref_id."""
    try:
        from database.db_manager import get_connection
        import psycopg2.extras

        conn = get_connection()
        if not conn:
            raise HTTPException(
                status_code = 500,
                detail      = "DB connection failed"
            )

        cur = conn.cursor(
            cursor_factory = psycopg2.extras.RealDictCursor
        )
        cur.execute(
            "SELECT * FROM audit_log WHERE ref_id = %s",
            (ref_id,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()

        if not row:
            raise HTTPException(
                status_code = 404,
                detail      = "Ref ID not found"
            )

        return dict(row)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# ── Chat history endpoint ─────────────────────────────────────
@app.get("/chat/{user_id}")
def get_chat_history(user_id: str, limit: int = 20):
    """Get chat history for a user — restores chat on refresh."""
    try:
        history = chat_history_get(user_id=user_id, limit=limit)
        return {
            "status":  "ok",
            "user_id": user_id,
            "count":   len(history),
            "history": history
        }
    except Exception as e:
        raise HTTPException(
            status_code = 500,
            detail      = f"Chat history error: {str(e)}"
        )


# ════════════════════════════════════════════════════════════
# RUN SERVER
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run(
        "api.app:app",
        host     = "0.0.0.0",
        port     = 8000,
        reload   = True
    )