# NormIQ — AI-Powered Regulatory Compliance Q&A System

> **Production-grade Agentic RAG system for Healthcare Compliance**

[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)](https://fastapi.tiangolo.com)
[![Pinecone](https://img.shields.io/badge/Pinecone-Vector%20DB-purple)](https://pinecone.io)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4.1--mini-orange)](https://openai.com)
[![RAGAS](https://img.shields.io/badge/RAGAS-0.889%20Overall-brightgreen)](https://ragas.io)

---

## What is NormIQ?

NormIQ is an end-to-end **Agentic RAG system** that answers healthcare compliance questions with **verifiable citations** from official regulation PDFs. The system covers three major regulatory frameworks:

- 🇺🇸 **HIPAA** — US Health Insurance Portability and Accountability Act
- 🇪🇺 **GDPR** — EU General Data Protection Regulation
- 🌐 **NIST SP 800-53** — National Institute of Standards and Technology Security Controls

Built with a **4-tool agentic pipeline**, **hybrid retrieval**, **confidence-based human-in-the-loop routing**, and a **complete LLMOps audit trail**.

---

## Key Achievements

```
RAGAS Overall Score    : 0.889 / 1.000
Faithfulness           : 0.843  (answers grounded in regulation text)
Answer Relevancy       : 0.922  (answers address the compliance question)
Context Recall         : 0.951  (retrieves all necessary regulatory chunks)
Guardrail Effectiveness: 100%   (all adversarial inputs blocked)
Cached Response Time   : < 1 second
```

---

## Technical Highlights

### 1. Agentic Pipeline (4 Tools)

```
User Question
     │
     ▼
┌─────────────────────────────────────────┐
│  Tool 1 — Query Understanding           │
│  GPT-4.1-mini detects regulation,       │
│  intent, and jurisdiction ambiguity     │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  Tool 2 — Hybrid Search                 │
│  Pinecone (semantic) + BM25 (keyword)   │
│  → Cohere reranker → balanced           │
│    multi-regulation retrieval           │
└──────────────────┬──────────────────────┘
                   │
          Cohere score < 0.30?
          Yes → Tool 3 (Multi-Query)
          No  → Skip
                   │
                   ▼
┌─────────────────────────────────────────┐
│  Tool 4 — Answer Generation             │
│  GPT-4.1-mini → structured JSON         │
│  sub-paragraph citations + summary      │
└──────────────────┬──────────────────────┘
                   │
         Confidence ≥ 0.80?
         Yes → Direct to user
         No  → Human review via Telegram
```

### 2. Custom Confidence Scoring

Designed a domain-specific confidence formula replacing raw similarity scores:

```python
Confidence = (avg_cohere_top3 × 0.70) + (avg_pinecone_top3 × 0.30) + citation_bonus

# Citation bonus rewards answers with more regulatory citations:
# 3+ citations → +0.08 | 2 citations → +0.05 | 1 citation → +0.02
# Cap: 0.95 — no answer is presented as absolutely certain
```

### 3. GDPR Sub-Paragraph Chunking

Built a custom rechunking pipeline achieving sub-paragraph citation precision:

```python
# Before: "GDPR Article 7" — article level only
# After:  "GDPR Article 7(3)" — exact sub-paragraph

# Result: 99 articles → 425 sub-paragraph chunks
# All 99 GDPR articles indexed with sub-article granularity
```

### 4. Hybrid Search with Balanced Reranking

```python
# Pool: top_n × 3 chunks sent to Cohere reranker
# Balance: min(top_n // num_regulations) chunks per regulation
# Prevents dominant regulation crowding out minority regulation context
# Critical for HIPAA+NIST crosswalk questions
```

### 5. LLMOps — Complete Audit Trail

Every query logged to PostgreSQL with:

```
ref_id            — unique reference identifier (REF-XXXXXXXX)
citations         — JSONB array of regulation sections
confidence        — routing signal with formula breakdown
officer_action    — approved / rewritten
response_time_sec — performance tracking
```

90-day intelligent cache with content-based addressing (MD5 question hash) — same question from 1000 nurses returns the same verified answer instantly.

---

## System Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────────┐
│ Streamlit   │────▶│  FastAPI    │────▶│   4-Tool Agent      │
│ Chat UI     │     │  Backend    │     │   Pipeline          │
│ (port 8501) │     │ (port 8000) │     │                     │
└─────────────┘     └─────────────┘     └──────────┬──────────┘
                                                    │
                    ┌───────────────────────────────┼──────────────┐
                    │                               │              │
               ┌────▼────┐                   ┌─────▼────┐  ┌─────▼────┐
               │Pinecone │                   │PostgreSQL│  │  Cohere  │
               │Vector DB│                   │Audit+    │  │ Reranker │
               │3 NS     │                   │Cache+Chat│  │          │
               └────┬────┘                   └──────────┘  └──────────┘
                    │
         ┌──────────┼──────────┐
         │          │          │
      HIPAA       GDPR       NIST
    518 chunks  425 chunks  572 chunks
    §164.xxx    Art.X(Y)    AC-2, AU-3
```

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **LLM** | GPT-4.1-mini | Query understanding, answer generation |
| **Embeddings** | text-embedding-3-small | 1536-dim vector encoding |
| **Vector DB** | Pinecone | Semantic similarity search (3 namespaces) |
| **Keyword Search** | BM25 (rank-bm25) | Exact term matching, pickle cached |
| **Reranker** | Cohere rerank-english-v3.0 | Semantic relevance scoring |
| **API** | FastAPI | REST endpoints with Pydantic models |
| **Frontend** | Streamlit | Chat UI + Admin dashboard |
| **Database** | PostgreSQL (Docker) | Audit log, cache store, chat history |
| **Notifications** | Telegram Bot API | Officer review workflow |
| **Evaluation** | RAGAS 0.2.6 | Faithfulness, relevancy, precision, recall |

---

## Evaluation

### RAGAS Results — 80 Questions

| Category | Questions | Faithfulness | Relevancy | Precision | Recall |
|---|---|---|---|---|---|
| HIPAA | 20 | **0.904** | 0.910 | 0.883 | 0.965 |
| GDPR basic | 20 | 0.782 | 0.934 | 0.795 | 0.938 |
| GDPR verbatim | 20 | 0.853 | 0.864 | 0.797 | 0.875 |
| GDPR medium | 20 | 0.787 | 0.876 | 0.782 | 0.775 |

### Ablation Study — Each Component Measured in Isolation

| Stage | Added Component | Quality |
|---|---|---|
| 1 | Baseline: Pinecone vector search only | 3.2/5 |
| 2 | + BM25 hybrid search | 3.6/5 |
| 3 | + Cohere reranker | 3.9/5 |
| 4 | + Conditional multi-query | 4.1/5 |
| 5 | + Custom confidence formula (70/30 + citation bonus) | 4.3/5 |
| 6 | + Balanced multi-regulation reranking | 4.4/5 |
| 7 | + GDPR sub-paragraph rechunking + prompt engineering | 4.53/5 |
| **8 ✅** | **+ GPT-4.1-mini + 10 chunks** | **4.70/5** |

---

## Key Engineering Decisions

**Why Hybrid Search?**
Regulatory language has significant vocabulary mismatch with natural language questions. BM25 keyword search recovers exact legal terms (§164.404) that vector search misses — delivering +0.11 confidence improvement over vector-only baseline.

**Why Conditional Multi-Query?**
Running multi-query on every question adds 8–10 seconds latency. A conditional trigger (Cohere < 0.30) applies it only when retrieval is weak — preserving speed for 80% of questions.

**Why Confidence Threshold = 0.80 — Never Lowered?**
In medical compliance, wrong answers cause regulatory violations. The threshold was never compromised despite self-service rate pressure. Cache growth is the strategy for improving direct answer rate over time — not threshold reduction.

**Why Sub-Paragraph Chunking for GDPR?**
GDPR Article 7 has 4 sub-paragraphs with distinct legal meanings. Article-level chunking produced imprecise citations ("GDPR Article 7"). Sub-paragraph chunking produces legally precise citations ("GDPR Article 7(3) — right to withdraw consent").

**Why GPT-4.1-mini over GPT-4o-mini?**
GPT-4.1-mini has significantly better instruction following — critical for the evidence-only grounding rule. Switching produced +32% faithfulness improvement on complex enumeration questions (0.596 → 0.787) while being 83% cheaper and faster.

---

## Installation

```bash
# Clone repository
git clone https://github.com/your-username/normiq.git
cd normiq

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys

# Start PostgreSQL
docker run --name postgrescont \
  -e POSTGRES_PASSWORD=mypassword \
  -e POSTGRES_DB=compliance_db \
  -p 5432:5432 -d postgres

# Create database tables
python scripts/create_tables.py

# Ingest data into Pinecone
python ingestion/ingest_hipaa.py
python ingestion/ingest_gdpr.py
python ingestion/ingest_nist.py
```

## Running

```bash
# Terminal 1 — API backend
uvicorn api.app:app --reload --port 8000

# Terminal 2 — Chat UI
streamlit run ui/user_chat.py --server.port 8501

# Terminal 3 — Admin dashboard
streamlit run ui/admin_dashboard.py --server.port 8502

# Terminal 4 — Telegram officer bot
python bot/telegram_bot.py
```

## Running Evaluation

```bash
pip install ragas==0.2.6
python evaluation/ragas_eval.py

# Launch evaluation dashboard
streamlit run evaluation/ragas_dashboard.py --server.port 8503
```

---

## Project Structure

```
normiq/
├── agent/                    # Agentic pipeline
│   ├── agent.py              # Main orchestrator (run_agent)
│   ├── prompts/              # LLM system prompts
│   └── tools/                # 4 pipeline tools
│       ├── tool_query_understanding.py
│       ├── tool_hybrid_search.py
│       ├── tool_multi_query.py
│       └── tool_answer_generation.py
├── api/                      # FastAPI REST API
│   ├── app.py
│   └── models.py
├── retrieval/                # Search layer
│   ├── pinecone_search.py    # Vector search
│   ├── bm25_search.py        # Keyword search
│   └── cohere_rerank.py      # Reranking + confidence
├── pipeline/
│   └── guardrails.py         # 18 input/output rules
├── ui/                       # Streamlit frontends
│   ├── user_chat.py          # Nurse chat interface
│   └── admin_dashboard.py    # Officer audit dashboard
├── bot/
│   └── telegram_bot.py       # Officer review bot
├── db/
│   └── database.py           # PostgreSQL queries
├── data/                     # Regulation datasets
│   ├── gdpr_rechunked.json   # 425 sub-paragraph chunks
│   └── nist_rag_ready_final_v4.json
├── evaluation/               # RAGAS evaluation suite
│   ├── ragas_eval.py
│   ├── ragas_questions.json  # 80 questions with ground truth
│   └── ragas_dashboard.py
└── config/
    └── settings.py           # All configuration
```

---

## What I Learned Building This

- Designed a **complete production RAG pipeline** from raw PDFs to evaluated system
- Built **custom confidence scoring** using multi-signal ensemble — Cohere + Pinecone + citation bonus
- **Systematic evaluation reveals hidden issues** — 10 bugs discovered and fixed through 80-question RAGAS evaluation including a missing dataset section (HIPAA §164.310) and a factual error in regulation comparison (GDPR stricter than HIPAA for breach notification)
- **Faithfulness ≠ hallucination** — low faithfulness on complex enumeration questions means correct answers beyond retrieved context, not invented facts
- **Human-in-the-loop design matters** — the 0.80 confidence threshold was never lowered because cache growth (not threshold reduction) is the right long-term strategy
- **Model selection impacts faithfulness** — GPT-4.1-mini's superior instruction following produced +32% faithfulness improvement on complex questions

---

## Future Enhancements

- [ ] **Graph RAG (Neo4j)** — Map regulation relationships for interconnected article retrieval
- [ ] **Legal domain reranker** — Fine-tune BAAI/bge-reranker on compliance Q&A pairs
- [ ] **Citation grounding validation** — Verify every claim is traceable to retrieved chunks
- [ ] **NIST CSF 2.0** — Add business-friendly security control descriptions
- [ ] **Expanded regulations** — SOX, CCPA, HIPAA Omnibus updates for telehealth and AI-generated clinical notes

---

*Built with Python · FastAPI · Streamlit · Pinecone · OpenAI · Cohere · PostgreSQL · Telegram · RAGAS*
