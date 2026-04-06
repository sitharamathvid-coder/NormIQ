import os
from dotenv import load_dotenv

# ── Load .env file ──────────────────────────────────────────
load_dotenv()

# ── OpenAI ──────────────────────────────────────────────────
OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL       = "text-embedding-3-small"
EMBEDDING_DIMENSIONS  = 1536
LLM_MODEL             = "gpt-4o-mini"

# ── Pinecone ─────────────────────────────────────────────────
PINECONE_API_KEY      = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX        = os.getenv("PINECONE_INDEX", "compliance-rag")

# Namespace names — must match exactly when ingesting
NAMESPACE_HIPAA       = "HIPAA"
NAMESPACE_GDPR        = "GDPR"
NAMESPACE_NIST        = "NIST"


# ── Cohere ───────────────────────────────────────────────────
COHERE_API_KEY        = os.getenv("COHERE_API_KEY")
COHERE_RERANK_MODEL   = "rerank-english-v3.0"
COHERE_TOP_N          = 6

# ── Database ─────────────────────────────────────────────────
DATABASE_URL          = os.getenv("DATABASE_URL")
CACHE_EXPIRY_DAYS     = int(os.getenv("CACHE_EXPIRY_DAYS", "90"))

# ── Telegram ─────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN        = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_OFFICER_CHAT_ID  = os.getenv("TELEGRAM_OFFICER_CHAT_ID")

# ── Pipeline ─────────────────────────────────────────────────
CONFIDENCE_THRESHOLD  = float(os.getenv("CONFIDENCE_THRESHOLD", "0.80"))
MAX_QUESTION_LENGTH   = 1000
MIN_QUESTION_LENGTH   = 10
MAX_QUESTIONS_PER_MIN = 10
RETRIEVAL_TOP_K       = 20
RERANK_TOP_N          = 6

# ── Data file paths ──────────────────────────────────────────
import pathlib
BASE_DIR              = pathlib.Path(__file__).parent.parent
DATA_DIR              = BASE_DIR / "data" / "raw"

NIST_JSON             = DATA_DIR / "nist_rag_ready_final_v4.json"
HIPAA_JSON            = DATA_DIR / "hipaa_final_rag1.json"
GDPR_CSV              = DATA_DIR / "gdpr_text.csv"
PENALTIES_JSON        = DATA_DIR / "hipaa_penalties_rag.json"
CROSSWALK_JSON        = DATA_DIR / "hipaa_nist_crosswalk.json"

# ── Verify all keys loaded ───────────────────────────────────
def verify_settings():
    required = {
        "OPENAI_API_KEY":       OPENAI_API_KEY,
        "PINECONE_API_KEY":     PINECONE_API_KEY,
        "COHERE_API_KEY":       COHERE_API_KEY,
        "DATABASE_URL":         DATABASE_URL,
        "TELEGRAM_BOT_TOKEN":   TELEGRAM_BOT_TOKEN,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        print(f"WARNING - Missing keys in .env: {missing}")
    else:
        print("All settings loaded successfully!")

if __name__ == "__main__":
    verify_settings()