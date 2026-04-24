import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config.settings import DATABASE_URL

print("Connecting to PostgreSQL...")

conn   = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

print("Creating tables...\n")

# ── audit_log ─────────────────────────────────────────────
cursor.execute("""
CREATE TABLE IF NOT EXISTS audit_log (
    id                SERIAL PRIMARY KEY,
    ref_id            VARCHAR(20) UNIQUE NOT NULL,
    user_id           VARCHAR(100),
    question          TEXT NOT NULL,
    answer            TEXT,
    summary           TEXT,
    citations         JSONB DEFAULT '[]',
    confidence        FLOAT DEFAULT 0.0,
    regulation        VARCHAR(50),
    status            VARCHAR(30) DEFAULT 'pending_review',
    was_cached        BOOLEAN DEFAULT FALSE,
    officer_id        VARCHAR(100),
    officer_action    VARCHAR(20),
    officer_answer    TEXT,
    conflict          BOOLEAN DEFAULT FALSE,
    conflict_warning  TEXT,
    response_time_sec FLOAT,
    timestamp         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")
print("  ✅ audit_log created")

# ── cache_store ───────────────────────────────────────────
cursor.execute("""
CREATE TABLE IF NOT EXISTS cache_store (
    id              SERIAL PRIMARY KEY,
    question_hash   VARCHAR(64) UNIQUE NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT,
    summary         TEXT,
    citations       JSONB DEFAULT '[]',
    confidence      FLOAT DEFAULT 1.0,
    regulation      VARCHAR(50),
    ref_id          VARCHAR(20),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at      TIMESTAMP DEFAULT (CURRENT_TIMESTAMP + INTERVAL '90 days'),
    hit_count       INTEGER DEFAULT 0
);
""")
print("  ✅ cache_store created")

# ── chat_history ──────────────────────────────────────────
cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_history (
    id        SERIAL PRIMARY KEY,
    user_id   VARCHAR(100) NOT NULL,
    role      VARCHAR(20) NOT NULL,
    message   TEXT NOT NULL,
    status    VARCHAR(30) DEFAULT 'answered',
    ref_id    VARCHAR(20),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")
print("  ✅ chat_history created")

# ── Indexes ───────────────────────────────────────────────
cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_audit_ref_id
ON audit_log(ref_id);
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_audit_status
ON audit_log(status);
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_audit_timestamp
ON audit_log(timestamp DESC);
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_cache_hash
ON cache_store(question_hash);
""")

cursor.execute("""
CREATE INDEX IF NOT EXISTS idx_chat_user_id
ON chat_history(user_id);
""")

print("  ✅ Indexes created")

conn.commit()
cursor.close()
conn.close()

print("\nAll tables created successfully!")
print("\nTables in compliance_db:")
print("  - audit_log    (every query logged)")
print("  - cache_store  (verified answers cached 90 days)")
print("  - chat_history (per-user message history)")
