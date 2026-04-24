import sys
import os
import json
import requests
import pandas as pd
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from datasets import Dataset
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────
API_URL        = "http://localhost:8000"
QUESTIONS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ragas_questions.json"
)
RESULTS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    f"ragas_results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
)

# ── Load questions ────────────────────────────────────────
print("Loading questions from JSON...\n")
with open(QUESTIONS_FILE, encoding="utf-8") as f:
    all_questions = json.load(f)

print(f"Total questions loaded: {len(all_questions)}")

categories = {}
for q in all_questions:
    cat = q.get("category", "Unknown")
    categories[cat] = categories.get(cat, 0) + 1
for cat, count in categories.items():
    print(f"  {cat}: {count} questions")
print()

# ── Filter by category ────────────────────────────────────
FILTER_CATEGORY = "GDPR_medium"  # "HIPAA" / "GDPR" / None = all

if FILTER_CATEGORY:
    test_questions = [
        q for q in all_questions
        if q.get("category") == FILTER_CATEGORY
    ]
    print(f"Filtered to {FILTER_CATEGORY}: {len(test_questions)} questions\n")
else:
    test_questions = all_questions
    print(f"Running all {len(test_questions)} questions\n")

# ── Call NormIQ API ───────────────────────────────────────
questions_list    = []
answers_list      = []
contexts_list     = []
ground_truths_list= []
ids               = []
cats              = []
confidences       = []
statuses          = []

print("Calling NormIQ API...")
print("=" * 60)

for i, item in enumerate(test_questions):
    q_id = item.get("id", f"Q{i+1}")
    cat  = item.get("category", "Unknown")
    q    = item["question"]
    gt   = item["ground_truth"]

    print(f"[{q_id}] {q[:55]}...")

    try:
        resp = requests.post(
            f"{API_URL}/query",
            json={
                "question": q,
                "user_id":  "ragas_eval",
                "role":     "nurse",
                "location": "US"
            },
            timeout=60
        )

        if resp.status_code == 200:
            data   = resp.json()
            answer = data.get("answer", "")
            chunks = data.get("source_chunks", [])

            context = [
                c.get("text", "")
                for c in chunks[:10]
                if c.get("text", "")
            ]
            if not context:
                context = [answer]

            questions_list.append(q)
            answers_list.append(answer)
            contexts_list.append(context)
            ground_truths_list.append(gt)
            ids.append(q_id)
            cats.append(cat)
            confidences.append(data.get("confidence", 0))
            statuses.append(data.get("status", "unknown"))

            conf   = data.get("confidence", 0)
            status = data.get("status", "")
            print(f"  ✅ Conf:{conf:.3f} | Status:{status} | Chunks:{len(context)}")

        else:
            print(f"  ❌ API error: {resp.status_code}")

    except Exception as e:
        print(f"  ❌ Error: {e}")

print("=" * 60)
print(f"\nCollected {len(questions_list)} results\n")

if not questions_list:
    print("No results — check API is running!")
    sys.exit(1)

# ── Build dataset ─────────────────────────────────────────
print("Building RAGAS dataset...")
dataset = Dataset.from_dict({
    "question":     questions_list,
    "answer":       answers_list,
    "contexts":     contexts_list,
    "ground_truth": ground_truths_list,
})

# ── Run RAGAS ─────────────────────────────────────────────
print("Running RAGAS evaluation (2-3 minutes)...\n")
result = evaluate(
    dataset = dataset,
    metrics = [
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
    ]
)

# ── Print results ─────────────────────────────────────────
import numpy as np

def get_score(result, key):
    val = result[key]
    if isinstance(val, list):
        return float(np.mean([v for v in val if v is not None]))
    return float(val)

faith  = get_score(result, "faithfulness")
rel    = get_score(result, "answer_relevancy")
prec   = get_score(result, "context_precision")
recall = get_score(result, "context_recall")
overall = (faith + rel + prec + recall) / 4

print("\n" + "=" * 50)
print("  RAGAS EVALUATION RESULTS — NormIQ")
print("=" * 50)
print(f"  Questions evaluated : {len(questions_list)}")
print(f"  Categories          : {', '.join(categories.keys())}")
print("-" * 50)
print(f"  Faithfulness        : {faith:.3f}")
print(f"  Answer Relevancy    : {rel:.3f}")
print(f"  Context Precision   : {prec:.3f}")
print(f"  Context Recall      : {recall:.3f}")
print("-" * 50)
print(f"  Overall Average     : {overall:.3f}")
print("=" * 50)

# ── Save CSV ──────────────────────────────────────────────
df = result.to_pandas()
df["id"]           = ids
df["category"]     = cats
df["confidence"]   = confidences
df["status"]       = statuses
df["question"]     = questions_list
df["ground_truth"] = ground_truths_list

# ── Category breakdown ────────────────────────────────────
print("\nResults by category:")
print("-" * 50)

for cat in df["category"].unique():
    cat_df = df[df["category"] == cat]
    print(f"\n  {cat} ({len(cat_df)} questions):")
    print(f"    Faithfulness     : {cat_df['faithfulness'].mean():.3f}")
    print(f"    Answer Relevancy : {cat_df['answer_relevancy'].mean():.3f}")
    print(f"    Context Precision: {cat_df['context_precision'].mean():.3f}")
    print(f"    Context Recall   : {cat_df['context_recall'].mean():.3f}")
    print(f"    Avg Confidence   : {cat_df['confidence'].mean():.3f}")
    direct = len(cat_df[cat_df["status"] == "answered"])
    print(f"    Direct answers   : {direct}/{len(cat_df)}")

df.to_csv(RESULTS_FILE, index=False)
print(f"\nResults saved to: {RESULTS_FILE}")

# ── Low faithfulness ──────────────────────────────────────
print("\nLow faithfulness questions (< 0.70):")
print("-" * 50)
low = df[df["faithfulness"] < 0.70][
    ["id", "category", "question", "faithfulness"]
]
if len(low) > 0:
    for _, row in low.iterrows():
        print(f"  [{row['id']}] {row['category']} | Faith: {row['faithfulness']:.3f}")
        print(f"         {row['question'][:60]}")
else:
    print("  None — all above 0.70!")

print("\nRAGAS evaluation complete!")