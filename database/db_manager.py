import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psycopg2
import psycopg2.extras
import uuid
import hashlib
import json
from datetime import datetime, timedelta
from config.settings import DATABASE_URL, CACHE_EXPIRY_DAYS


# ── Connect to PostgreSQL ────────────────────────────────────
def get_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"Database connection failed: {e}")
        return None


# ── Generate reference ID for pending reviews ────────────────
def generate_ref_id():
    return "REF-" + str(uuid.uuid4())[:8].upper()


# ── Generate hash for cache lookup ──────────────────────────
def generate_hash(question: str) -> str:
    return hashlib.md5(question.strip().lower().encode()).hexdigest()


# ════════════════════════════════════════════════════════════
# CACHE FUNCTIONS
# ════════════════════════════════════════════════════════════

def cache_get(question: str):
    """Check if question exists in cache and is not expired."""
    conn = get_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        question_hash = generate_hash(question)
        cur.execute("""
            SELECT * FROM cache_store
            WHERE question_hash = %s
            AND expires_at > NOW()
        """, (question_hash,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            print(f"Cache HIT for: {question[:50]}...")
            return dict(row)
        return None
    except Exception as e:
        print(f"Cache get error: {e}")
        return None


def cache_set(question: str, answer: str, citations: list,
              regulation: str, confidence: float):
    """Save answer to cache with expiry date."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        question_hash = generate_hash(question)
        expires_at    = datetime.now() + timedelta(days=CACHE_EXPIRY_DAYS)
        cur.execute("""
            INSERT INTO cache_store
            (question_hash, question_text, answer, citations,
             regulation, confidence, expires_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (question_hash) DO UPDATE
            SET answer     = EXCLUDED.answer,
                citations  = EXCLUDED.citations,
                confidence = EXCLUDED.confidence,
                expires_at = EXCLUDED.expires_at
        """, (
            question_hash, question, answer,
            json.dumps(citations), regulation,
            confidence, expires_at
        ))
        conn.commit()
        cur.close()
        conn.close()
        print(f"Cache SET for: {question[:50]}...")
        return True
    except Exception as e:
        print(f"Cache set error: {e}")
        return False


def cache_delete_expired():
    """Delete all expired cache entries."""
    conn = get_connection()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM cache_store WHERE expires_at < NOW()")
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        print(f"Deleted {deleted} expired cache entries")
    except Exception as e:
        print(f"Cache cleanup error: {e}")


# ════════════════════════════════════════════════════════════
# AUDIT LOG FUNCTIONS
# ════════════════════════════════════════════════════════════

def audit_log_create(user_id: str, question: str,
                     regulation: str, was_cached: bool = False):
    """Create audit log entry when question is received."""
    conn = get_connection()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        ref_id = generate_ref_id()
        cur.execute("""
            INSERT INTO audit_log
            (ref_id, user_id, question, regulation,
             was_cached, status, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            RETURNING ref_id
        """, (ref_id, user_id, question, regulation,
              was_cached, "pending"))
        conn.commit()
        cur.close()
        conn.close()
        print(f"Audit log created — Ref: {ref_id}")
        return ref_id
    except Exception as e:
        print(f"Audit log create error: {e}")
        return None


def audit_log_update_answer(ref_id: str, answer: str,
                            citations: list, confidence: float):
    """Update audit log when answer is generated."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE audit_log
            SET answer     = %s,
                citations  = %s,
                confidence = %s,
                status     = 'answered',
                answer_sent_at = NOW()
            WHERE ref_id = %s
        """, (answer, json.dumps(citations), confidence, ref_id))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Audit log update error: {e}")
        return False


def audit_log_update_officer(ref_id: str, officer_id: str,
                             action: str, officer_answer: str = None):
    """Update audit log when officer approves or rewrites."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE audit_log
            SET officer_id     = %s,
                officer_action = %s,
                officer_answer = %s,
                status         = 'reviewed',
                answer_sent_at = NOW()
            WHERE ref_id = %s
        """, (officer_id, action, officer_answer, ref_id))
        conn.commit()
        cur.close()
        conn.close()
        print(f"Audit log officer update — Ref: {ref_id} — Action: {action}")
        return True
    except Exception as e:
        print(f"Audit log officer update error: {e}")
        return False


def audit_log_get_all(limit: int = 100):
    """Get all audit log entries for admin dashboard."""
    conn = get_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM audit_log
            ORDER BY timestamp DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"Audit log get all error: {e}")
        return []


def audit_log_get_pending():
    """Get all questions pending officer review."""
    conn = get_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM audit_log
            WHERE status = 'pending'
            ORDER BY timestamp ASC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"Audit log get pending error: {e}")
        return []


# ════════════════════════════════════════════════════════════
# CHAT HISTORY FUNCTIONS
# ════════════════════════════════════════════════════════════

def chat_history_add(user_id: str, role: str,
                     message: str, ref_id: str = None,
                     status: str = "answered"):
    """Save a message to chat history."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO chat_history
            (user_id, ref_id, role, message, status, timestamp)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (user_id, ref_id, role, message, status))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Chat history add error: {e}")
        return False


def chat_history_get(user_id: str, limit: int = 20):
    """Get last N messages for a user — restores chat on refresh."""
    conn = get_connection()
    if not conn:
        return []
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT * FROM chat_history
            WHERE user_id = %s
            ORDER BY timestamp DESC
            LIMIT %s
        """, (user_id, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # Reverse so oldest message is first
        return [dict(row) for row in reversed(rows)]
    except Exception as e:
        print(f"Chat history get error: {e}")
        return []


def chat_history_update_status(ref_id: str, status: str):
    """Update chat message status when officer responds."""
    conn = get_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE chat_history
            SET status = %s
            WHERE ref_id = %s
        """, (status, ref_id))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Chat history update error: {e}")
        return False


# ════════════════════════════════════════════════════════════
# TEST CONNECTION
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing database connection...")
    conn = get_connection()
    if conn:
        print("Connection successful!")
        conn.close()

        print("\nTesting cache...")
        cache_set(
            question   = "What is HIPAA breach notification deadline?",
            answer     = "Under HIPAA §164.404 — 60 days",
            citations  = ["§164.404"],
            regulation = "HIPAA",
            confidence = 0.91
        )
        result = cache_get("What is HIPAA breach notification deadline?")
        print(f"Cache result: {result['answer'] if result else 'Not found'}")

        print("\nTesting audit log...")
        ref = audit_log_create(
            user_id    = "nurse_test",
            question   = "What is HIPAA breach notification deadline?",
            regulation = "HIPAA"
        )
        print(f"Ref ID created: {ref}")

        print("\nTesting chat history...")
        chat_history_add(
            user_id = "nurse_test",
            role    = "nurse",
            message = "What is HIPAA breach notification deadline?"
        )
        history = chat_history_get("nurse_test")
        print(f"Chat history entries: {len(history)}")

        print("\nAll database tests passed!")
    else:
        print("Connection failed — check DATABASE_URL in .env")