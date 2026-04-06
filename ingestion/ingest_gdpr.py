import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import time
import re
from openai import OpenAI
from pinecone import Pinecone
from config.settings import (
    OPENAI_API_KEY,
    PINECONE_API_KEY,
    PINECONE_INDEX,
    NAMESPACE_GDPR,
    EMBEDDING_MODEL,
    GDPR_CSV
)

# ── Initialise clients ───────────────────────────────────────
openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc            = Pinecone(api_key=PINECONE_API_KEY)
index         = pc.Index(PINECONE_INDEX)


# ── Get embedding ────────────────────────────────────────────
def get_embedding(text: str) -> list:
    response = openai_client.embeddings.create(
        input = text,
        model = EMBEDDING_MODEL
    )
    return response.data[0].embedding


# ── Clean text ───────────────────────────────────────────────
def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── Group sub-articles into one chunk per article ────────────
def group_by_article(df: pd.DataFrame) -> list:
    chunks = []
    grouped = df.groupby("article")

    for article_num, group in grouped:
        # Combine all sub-article texts
        texts = []
        for _, row in group.iterrows():
            text = clean_text(str(row["gdpr_text"]))
            if text:
                texts.append(text)

        if not texts:
            continue

        # Get article info from first row
        first_row     = group.iloc[0]
        article_title = str(first_row["article_title"]).strip()
        chapter       = int(first_row["chapter"]) if pd.notna(first_row["chapter"]) else 0
        chapter_title = str(first_row["chapter_title"]).strip()

        # Combine all sub-articles into one text
        combined_text = " ".join(texts)

        # Build citation
        citation = f"GDPR Article {int(article_num)}"

        # Build embedding text
        embedding_text = f"{citation} {article_title}. {combined_text}"

        chunks.append({
            "article_num":     int(article_num),
            "article_title":   article_title,
            "chapter":         chapter,
            "chapter_title":   chapter_title,
            "citation":        citation,
            "text":            combined_text,
            "embedding_text":  embedding_text,
        })

    print(f"Grouped into {len(chunks)} article chunks")
    return chunks


# ── Upload GDPR chunks to Pinecone ───────────────────────────
def ingest_gdpr():
    print("=" * 50)
    print("GDPR Ingestion Starting...")
    print("=" * 50)

    # Load CSV
    df = pd.read_csv(GDPR_CSV)
    print(f"Total rows in CSV: {len(df)}")

    # Drop href column — not needed
    if "href" in df.columns:
        df = df.drop(columns=["href"])

    # Group by article
    chunks = group_by_article(df)
    print(f"Total chunks to upload: {len(chunks)}")

    success    = 0
    failed     = 0
    batch      = []
    batch_size = 50

    for chunk in chunks:
        try:
            # Get embedding
            embedding = get_embedding(chunk["embedding_text"])

            # Build metadata
            metadata = {
                "regulation":    "GDPR",
                "jurisdiction":  "EU",
                "article_num":   chunk["article_num"],
                "article_title": chunk["article_title"],
                "chapter":       chunk["chapter"],
                "chapter_title": chunk["chapter_title"],
                "citation":      chunk["citation"],
                "text":          chunk["text"],
                "source":        "GDPR Official Text",
                "is_deprecated": False,
            }

            # Build Pinecone vector
            vector = {
                "id":       f"gdpr_article_{chunk['article_num']}",
                "values":   embedding,
                "metadata": metadata
            }

            batch.append(vector)

            # Upload in batches
            if len(batch) >= batch_size:
                index.upsert(vectors=batch, namespace=NAMESPACE_GDPR)
                success += len(batch)
                print(f"Uploaded {success}/{len(chunks)} chunks...")
                batch = []
                time.sleep(0.5)

        except Exception as e:
            print(f"Error on Article {chunk['article_num']}: {e}")
            failed += 1
            continue

    # Upload remaining
    if batch:
        index.upsert(vectors=batch, namespace=NAMESPACE_GDPR)
        success += len(batch)

    print("\n" + "=" * 50)
    print(f"GDPR Ingestion Complete!")
    print(f"Successfully uploaded: {success}")
    print(f"Failed:                {failed}")
    print(f"Namespace:             {NAMESPACE_GDPR}")
    print("=" * 50)

    return success, failed


if __name__ == "__main__":
    ingest_gdpr()