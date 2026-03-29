# =============================================================================
# NormIQ — ingest_step2_gdpr.py  (STEP 2 OF 4: GDPR ONLY)
# =============================================================================
# What this file does:
#   1. Loads gdpr_text.csv         → articles  → Pinecone (namespace: GDPR)
#   2. Loads gdpr_recitals.csv     → recitals  → Pinecone (namespace: GDPR)
#   3. Uses gdpr_cased_articles... → bridge    → joins recital context to articles
#   4. Builds bm25_gdpr.pkl        → keyword search retriever for GDPR
#
# NO LlamaParse needed here — CSVs are already structured text.
# NO chunking needed — each row is already one article/recital (short enough).
# Citations are FREE — they come directly from the 'article' column.
# =============================================================================


# =============================================================================
# SECTION 0 — IMPORTS
# =============================================================================

import os
import re
import random
import pickle

from dotenv import load_dotenv

import pandas as pd
# pandas = the standard Python tool for reading CSV files.
# pd.read_csv("file.csv") loads a CSV into a "DataFrame" —
# think of it like an Excel table in Python.
# Each column becomes accessible as df["column_name"].

from rank_bm25 import BM25Okapi
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone


# =============================================================================
# SECTION 1 — LOAD API KEYS
# =============================================================================

load_dotenv()

OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

assert OPENAI_API_KEY,   "❌ OPENAI_API_KEY not found in .env"
assert PINECONE_API_KEY, "❌ PINECONE_API_KEY not found in .env"

print("✅ All API keys loaded.")


# =============================================================================
# SECTION 2 — CONFIGURATION
# =============================================================================

PINECONE_INDEX_NAME = "normiq"

# GDPR file paths
GDPR_ARTICLES_FILE  = "data/gdpr_text.csv"
GDPR_RECITALS_FILE  = "data/gdpr_recitals.csv"
GDPR_BRIDGE_FILE    = "data/gdpr_cased_articles_with_recitals.csv"
# Bridge file = links article_id → recital numbers
# We use it to add "related_recitals" context to article chunks.
# It does NOT go into Pinecone itself.

# Fixed metadata for all GDPR chunks
GDPR_REGULATION     = "GDPR"
GDPR_JURISDICTION   = "EU"
GDPR_VERSION        = "2016-v1"
GDPR_EFFECTIVE_DATE = "2018-05-25"
# GDPR was signed in 2016 but became enforceable on May 25, 2018.

print("✅ Configuration loaded.")


# =============================================================================
# SECTION 3 — LOAD THE BRIDGE FILE
# =============================================================================
# What is the bridge file?
# gdpr_cased_articles_with_recitals.csv links each article to its recitals.
# Example row:
#   article_id=1, article_title="Subject matter", article_recitals="1,2,3"
#
# This means Article 1 is explained by Recitals 1, 2, and 3.
# We will add this as "related_recitals" metadata on each article chunk.
# When someone asks WHY Article 33 requires 72-hour notification,
# the retriever can also pull Recital 85 which explains the reasoning.

def load_bridge() -> dict:
    """
    Loads the bridge CSV and returns a dict:
    { article_number: "1,2,3" }  ← recital numbers as a string
    """
    try:
        bridge_df = pd.read_csv(GDPR_BRIDGE_FILE)
        print(f"✅ Bridge file loaded. Columns: {bridge_df.columns.tolist()}")

        # Drop rows where article_recitals is empty
        bridge_df = bridge_df.dropna(subset=["article_recitals"])

        # Build a lookup dict: "1" → "1,2,3,4,5"
        # article_id column contains "article1", "article2" etc.
        # We extract just the number so it matches the article column in gdpr_text.csv
        bridge_dict = {}
        for _, row in bridge_df.iterrows():
            art_id_raw = str(row["article_id"]).strip()
            # "article1" → extract "1" using regex
            num_match = re.search(r"\d+", art_id_raw)
            if not num_match:
                continue
            art_num = num_match.group()  # "1", "2", "33" etc.

            recitals = str(row["article_recitals"]).strip()

            # If this article already exists in dict, skip duplicates
            if art_num not in bridge_dict:
                bridge_dict[art_num] = recitals

        print(f"   {len(bridge_dict)} article→recital mappings loaded.")
        return bridge_dict

    except Exception as e:
        # If the bridge file fails for any reason, we continue without it.
        # The articles will still be ingested — just without recital links.
        print(f"⚠️  Bridge file could not be loaded: {e}")
        print("   Continuing without recital links.")
        return {}


# =============================================================================
# SECTION 4 — LOAD GDPR ARTICLES FROM gdpr_text.csv
# =============================================================================
# Columns we have:
#   chapter, chapter_title, article, article_title, sub_article, gdpr_text, href
#
# Each row = one sub-article (a paragraph within an article).
# Example:
#   article=33, article_title="Notification of a personal data breach",
#   sub_article=1, gdpr_text="In the case of a personal data breach..."
#
# Citation = f"GDPR Article {row['article']}"  → "GDPR Article 33"
# This comes FREE from the column — no regex needed.

def load_gdpr_articles(bridge_dict: dict) -> list:
    """
    Loads gdpr_text.csv and creates ONE chunk per article (not per sub-article).
    All sub-articles of the same article are combined into one complete chunk.

    Before: Article 17 → 5 separate tiny chunks
    After:  Article 17 → 1 complete chunk with all 5 sub-articles joined

    This gives the LLM the full legal context of each article.
    Result: ~99 article chunks instead of 425 sub-article chunks.
    """

    df = pd.read_csv(GDPR_ARTICLES_FILE)

    print(f"\n📄 Loading GDPR articles from {GDPR_ARTICLES_FILE}")
    print(f"   Rows loaded: {len(df)}")

    df = df.dropna(subset=["gdpr_text"])
    print(f"   Rows after dropping empty text: {len(df)}")

    all_article_chunks = []

    # Group all rows by article number
    # Instead of looping row by row, we group by article
    # and combine all sub-articles into one text
    grouped = df.groupby("article", sort=True)

    for article_num, group in grouped:
        article_num = str(article_num).strip()

        # --- Combine all sub-article texts into one ---
        # Sort by sub_article number so the text is in correct order
        group = group.sort_values("sub_article")

        # Join all sub-article texts with a newline between them
        combined_text = "\n".join(
            str(row["gdpr_text"]).strip()
            for _, row in group.iterrows()
            if len(str(row["gdpr_text"]).strip()) > 5
        )

        if len(combined_text) < 10:
            continue

        # --- Get article metadata from first row of group ---
        first_row   = group.iloc[0]
        article_title = str(first_row.get("article_title", "")).strip()
        if not article_title or article_title == "nan":
            article_title = f"Article {article_num}"

        source_url = str(first_row.get("href", "")).strip()
        if source_url == "nan" or not source_url:
            source_url = f"https://gdpr-info.eu/art-{article_num}-gdpr/"

        # --- Citation (FREE from column) ---
        citation = f"GDPR Article {article_num}"

        # --- Related recitals from bridge dict ---
        related_recitals = bridge_dict.get(article_num, "")

        # --- Add # heading to the text so chunker can find boundaries ---
        full_text = f"# {citation} — {article_title}\n{combined_text}"

        # --- Build 13 metadata fields ---
        metadata = {
            "regulation":       GDPR_REGULATION,
            "jurisdiction":     GDPR_JURISDICTION,
            "section_type":     "Article",
            "section_title":    article_title,
            "citation":         citation,
            "version":          GDPR_VERSION,
            "effective_date":   GDPR_EFFECTIVE_DATE,
            "is_deprecated":    False,
            "page_number":      int(article_num) if str(article_num).isdigit() else 0,
            "parent_id":        f"Article {article_num}",
            "chunk_type":       "legal_text",
            "chunk_sequence":   int(article_num) if str(article_num).isdigit() else 0,
            "source_url":       source_url,
            "related_recitals": related_recitals,
        }

        all_article_chunks.append({
            "text":     full_text,
            "metadata": metadata,
        })

    print(f"   ✅ {len(all_article_chunks)} complete article chunks created "
          f"(was 425 sub-article chunks)")
    return all_article_chunks

    all_article_chunks = []

    for i, row in df.iterrows():
        # df.iterrows() = loop through each row one by one
        # i   = the row index number (0, 1, 2, ...)
        # row = the actual row data (access columns with row["column_name"])

        # --- Get the text ---
        text = str(row["gdpr_text"]).strip()
        # .strip() = remove leading/trailing whitespace

        if len(text) < 10:
            continue
        # Skip rows with very short text (less than 10 characters)
        # These are usually header rows or empty rows that slipped through.

        # --- Build citation (FREE from column — no regex) ---
        article_num = str(row["article"]).strip()
        citation = f"GDPR Article {article_num}"
        # f"..." = f-string — puts the variable value inside the string
        # Example: article_num = "33" → citation = "GDPR Article 33"

        # --- Get section title from article_title column ---
        section_title = str(row.get("article_title", "")).strip()
        if not section_title or section_title == "nan":
            section_title = f"Article {article_num}"
        # row.get("column", default) = safe way to get a value
        # "nan" = pandas puts the string "nan" when a cell is empty

        # --- Get related recitals from bridge dict ---
        related_recitals = bridge_dict.get(article_num, "")
        # If article 33 is in the bridge dict → "85,86"
        # If not found → "" (empty string)

        # --- Get sub_article for chunk_sequence ---
        sub_article = str(row.get("sub_article", i)).strip()

        # --- Get source URL from href column (FREE — no construction needed) ---
        source_url = str(row.get("href", "")).strip()
        if source_url == "nan":
            source_url = f"https://gdpr-info.eu/art-{article_num}-gdpr/"

        # --- Build 13 metadata fields ---
        metadata = {
            "regulation":        GDPR_REGULATION,       # "GDPR"
            "jurisdiction":      GDPR_JURISDICTION,     # "EU"
            "section_type":      "Article",             # This is an article row
            "section_title":     section_title,         # e.g. "Notification of breach"
            "citation":          citation,              # e.g. "GDPR Article 33"
            "version":           GDPR_VERSION,          # "2016-v1"
            "effective_date":    GDPR_EFFECTIVE_DATE,   # "2018-05-25"
            "is_deprecated":     False,
            "page_number":       int(article_num) if article_num.isdigit() else i,
            # For GDPR, article number serves as "page" for ordering
            "parent_id":         f"Article {article_num}",
            "chunk_type":        "legal_text",
            "chunk_sequence":    sub_article,           # sub_article = paragraph number
            "source_url":        source_url,
            # BONUS field — not in the original 13 but very useful:
            "related_recitals":  related_recitals,      # e.g. "85,86"
            # This helps the retriever find recitals that explain this article.
        }

        all_article_chunks.append({
            "text":     text,
            "metadata": metadata,
        })

    print(f"   ✅ {len(all_article_chunks)} article chunks created.")
    return all_article_chunks


# =============================================================================
# SECTION 5 — LOAD GDPR RECITALS FROM gdpr_recitals.csv
# =============================================================================
# Columns we have:
#   recital_id, recital_text
#
# Example row:
#   recital_id="recital85",
#   recital_text="In order to strengthen the enforcement of the rules..."
#
# Citation = "GDPR Recital 85"
# We extract the number from "recital85" → "85"

def load_gdpr_recitals() -> list:
    """
    Loads gdpr_recitals.csv and converts each row to a chunk with 13 metadata fields.
    Returns a list of dicts.
    """

    df = pd.read_csv(GDPR_RECITALS_FILE)

    print(f"\n📄 Loading GDPR recitals from {GDPR_RECITALS_FILE}")
    print(f"   Rows loaded: {len(df)}")

    df = df.dropna(subset=["recital_text"])
    print(f"   Rows after dropping empty text: {len(df)}")

    all_recital_chunks = []

    for i, row in df.iterrows():

        text = str(row["recital_text"]).strip()

        if len(text) < 10:
            continue

        # --- Extract recital number from recital_id ---
        # recital_id = "recital85" → we want "85"
        recital_id_raw = str(row["recital_id"]).strip()
        # re.search finds digits in "recital85" → "85"
        num_match = re.search(r"\d+", recital_id_raw)
        recital_num = num_match.group() if num_match else str(i)
        # If "recital85" → recital_num = "85"
        # If no digits found → use row index as fallback

        citation = f"GDPR Recital {recital_num}"
        # Example: "GDPR Recital 85"

        # --- Build 13 metadata fields ---
        metadata = {
            "regulation":       GDPR_REGULATION,
            "jurisdiction":     GDPR_JURISDICTION,
            "section_type":     "Recital",              # This is a recital row
            "section_title":    f"Recital {recital_num}",
            "citation":         citation,               # "GDPR Recital 85"
            "version":          GDPR_VERSION,
            "effective_date":   GDPR_EFFECTIVE_DATE,
            "is_deprecated":    False,
            "page_number":      int(recital_num) if recital_num.isdigit() else i,
            "parent_id":        recital_id_raw,         # "recital85"
            "chunk_type":       "legal_text",
            "chunk_sequence":   i,
            "source_url":       f"https://gdpr-info.eu/recitals/no-{recital_num}/",
            "related_recitals": "",                     # Recitals don't link to other recitals
        }

        all_recital_chunks.append({
            "text":     text,
            "metadata": metadata,
        })

    print(f"   ✅ {len(all_recital_chunks)} recital chunks created.")
    return all_recital_chunks


# =============================================================================
# SECTION 6 — VERIFY: PRINT 5 RANDOM CHUNKS
# =============================================================================

def print_sample_chunks(chunks: list, label: str, n: int = 3):
    """Prints n random chunks for visual verification."""
    print(f"\n{'='*60}")
    print(f"SAMPLE CHUNK VERIFICATION — {label} ({n} random chunks)")
    print(f"{'='*60}")

    sample = random.sample(chunks, min(n, len(chunks)))

    for idx, chunk in enumerate(sample, start=1):
        print(f"\n--- Chunk {idx} ---")
        print(f"  regulation:     {chunk['metadata']['regulation']}")
        print(f"  section_type:   {chunk['metadata']['section_type']}")
        print(f"  section_title:  {chunk['metadata']['section_title']}")
        print(f"  citation:       {chunk['metadata']['citation']}")
        print(f"  related_recit.: {chunk['metadata']['related_recitals']}")
        print(f"  source_url:     {chunk['metadata']['source_url']}")
        print(f"  text preview:   {chunk['text'][:200].strip()}")

    print(f"\n{'='*60}")


# =============================================================================
# SECTION 7 — BUILD BM25 RETRIEVER FOR GDPR
# =============================================================================

def build_bm25_gdpr(chunks: list) -> BM25Okapi:
    """Builds BM25 retriever for all GDPR chunks (articles + recitals)."""

    tokenized_corpus = [
        chunk["text"].lower().split()
        for chunk in chunks
    ]

    bm25 = BM25Okapi(tokenized_corpus)

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bm25_path = os.path.join(BASE_DIR, "data", "bm25_gdpr.pkl")
    with open(bm25_path, "wb") as f:
        pickle.dump(bm25, f)
        pickle.dump([c["text"] for c in chunks], f)

    print("✅ BM25 GDPR retriever built and saved to bm25_gdpr.pkl")
    return bm25


# =============================================================================
# SECTION 8 — UPLOAD GDPR CHUNKS TO PINECONE
# =============================================================================

def upload_to_pinecone_gdpr(chunks: list):
    """
    Embeds each chunk and uploads to Pinecone namespace 'GDPR'.
    """

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=OPENAI_API_KEY,
    )

    BATCH_SIZE = 100
    total_uploaded = 0

    for batch_start in range(0, len(chunks), BATCH_SIZE):

        batch = chunks[batch_start : batch_start + BATCH_SIZE]
        texts = [chunk["text"] for chunk in batch]
        vectors = embeddings.embed_documents(texts)

        records = []
        for j, chunk in enumerate(batch):
            record = {
                "id":     f"gdpr_{batch_start + j:04d}",
                "values": vectors[j],
                "metadata": {
                    **chunk["metadata"],
                    "text": chunk["text"],
                },
            }
            records.append(record)

        index.upsert(vectors=records, namespace="GDPR")

        total_uploaded += len(batch)
        print(f"   Uploaded batch: {batch_start}–{batch_start + len(batch) - 1}  "
              f"({total_uploaded}/{len(chunks)} total)")

    print(f"\n✅ GDPR upload complete: {total_uploaded} chunks in namespace 'GDPR'")
    return total_uploaded


# =============================================================================
# SECTION 9 — MAIN
# =============================================================================

if __name__ == "__main__":

    print("\n" + "="*60)
    print("NormIQ — ingest_step2_gdpr.py — STEP 2: GDPR")
    print("="*60 + "\n")

    # STEP A: Load bridge file (article → recital links)
    bridge_dict = load_bridge()

    # STEP B: Load articles and recitals
    article_chunks = load_gdpr_articles(bridge_dict)
    recital_chunks  = load_gdpr_recitals()

    # STEP C: Combine into one GDPR list
    all_gdpr_chunks = article_chunks + recital_chunks
    print(f"\n✅ GDPR TOTAL: {len(all_gdpr_chunks)} chunks "
          f"({len(article_chunks)} articles + {len(recital_chunks)} recitals)")

    # STEP D: Print samples — check articles AND recitals
    print_sample_chunks(article_chunks, "ARTICLES", n=3)
    print_sample_chunks(recital_chunks,  "RECITALS",  n=2)

    # STEP E: Ask before uploading
    answer = input("\nDo the sample chunks look correct? Type 'yes' to upload to Pinecone: ")
    if answer.strip().lower() != "yes":
        print("❌ Upload cancelled. Fix the issue and run again.")
        exit()

    # STEP F: Build BM25
    build_bm25_gdpr(all_gdpr_chunks)

    # STEP G: Upload to Pinecone
    count = upload_to_pinecone_gdpr(all_gdpr_chunks)

    print(f"\n{'='*60}")
    print(f"✅ STEP 2 COMPLETE")
    print(f"   {count} GDPR chunks uploaded to Pinecone namespace 'GDPR'")
    print(f"   ({len(article_chunks)} articles + {len(recital_chunks)} recitals)")
    print(f"   BM25 retriever saved to: bm25_gdpr.pkl")
    print(f"{'='*60}")
    print("\nNext step: Run STEP 3 to add NIST → python ingest_step3_nist.py")


# =============================================================================
# END OF STEP 2
# =============================================================================
# Expected output:
#   ✅ Bridge file loaded. 99 article→recital mappings loaded.
#   📄 Loading GDPR articles... ~350 article chunks created.
#   📄 Loading GDPR recitals... ~173 recital chunks created.
#   ✅ GDPR TOTAL: ~523 chunks
#   (5 sample chunks printed)
#   Type 'yes' → upload begins
#   ✅ STEP 2 COMPLETE
# =============================================================================
