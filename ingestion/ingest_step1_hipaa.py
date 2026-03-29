# =============================================================================
# NormIQ — ingest_step1_hipaa.py  (STEP 1: HIPAA ONLY)
# =============================================================================
# What this file does:
#   1. Loads 1 HIPAA eCFR PDF  → chunks → metadata → Pinecone (namespace: HIPAA)
#   2. Builds 1 BM25 retriever for HIPAA keyword search
#   3. Prints DONE — X chunks uploaded
#
# ALL FIXES INCLUDED:
#   Fix 1 — Citation regex now finds "# § 164.xxx" heading format
#   Fix 2 — Carry-forward: if chunk has no citation, use last known citation
#   Fix 3 — Clean leftover eCFR browser artifacts from chunk text
#   Fix 4 — section_title filters sub-section headers and bad titles
#   Fix 5 — extract_section_title strips § number from title
# =============================================================================


# =============================================================================
# SECTION 0 — IMPORTS
# =============================================================================

import os           # read environment variables (API keys)
import re           # regular expressions — find patterns in text
import random       # pick random chunks for verification
import pickle       # save BM25 retriever to disk

from dotenv import load_dotenv
from llama_parse import LlamaParse
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone, ServerlessSpec
from rank_bm25 import BM25Okapi


# =============================================================================
# SECTION 1 — LOAD API KEYS
# =============================================================================

load_dotenv()

OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY  = os.getenv("PINECONE_API_KEY")
LLAMA_CLOUD_KEY   = os.getenv("LLAMA_CLOUD_API_KEY")

assert OPENAI_API_KEY,   "❌ OPENAI_API_KEY not found in .env"
assert PINECONE_API_KEY, "❌ PINECONE_API_KEY not found in .env"
assert LLAMA_CLOUD_KEY,  "❌ LLAMA_CLOUD_API_KEY not found in .env"

print("✅ All API keys loaded.")


# =============================================================================
# SECTION 2 — CONFIGURATION
# =============================================================================

PINECONE_INDEX_NAME = "normiq"
PINECONE_REGION     = "us-east-1"

CHUNK_SIZE    = 800
CHUNK_OVERLAP = 150

# Separators — "\n# " first so chunks respect section boundaries
SEPARATORS = ["\n# ", "\n## ", "\n\n", "\n", ".", " "]

# Single eCFR file — replaces the 4 old HHS summary PDFs
HIPAA_FILES = [
    {
        "path":           "data/hipaa_part164_ecfr.pdf",
        "section_type":   "Regulation",
        "version":        "2024-v1",
        "effective_date": "2024-03-25",
        "source_url":     "https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-C/part-164",
    },
    {
        "path":           "data/hipaa_penalties.pdf",
        "section_type":   "Enforcement",
        "version":        "2024-v1",
        "effective_date": "2024-03-25",
        "source_url":     "https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-C/part-160/subpart-D",
    },
]

print("✅ Configuration loaded.")


# =============================================================================
# SECTION 3 — HELPER FUNCTION: EXTRACT CITATION FROM TEXT
# =============================================================================
# IMPORTANT: We NEVER ask the LLM to generate citations.
#            LLMs hallucinate section numbers.
#            We only trust regex on the actual PDF text.
#
# FIX 1 — Added Priority 1: look for "# § 164.xxx" heading format first.
# This is the most common format in LlamaParse output from eCFR PDFs.

def extract_hipaa_citation(text: str) -> str:
    """
    Extracts a HIPAA CFR citation from chunk text.
    Tries 3 patterns in order of reliability.
    Returns e.g. "45 CFR § 164.502" or "" if nothing found.
    """

    # Priority 1 — heading format: "# § 164.502 General rules"
    # LlamaParse turns eCFR section headings into "# § 164.xxx Title" lines.
    # This is the most reliable pattern in this document.
    heading_match = re.search(
        r'#\s+§\s*(\d+\.\d+(?:\([a-z0-9]\))?)', text
    )
    if heading_match:
        return f"45 CFR § {heading_match.group(1)}"

    # Priority 2 — full form in body text: "45 CFR §164.404" or "45 C.F.R. § 164.404"
    pattern1 = r"45\s+C\.?F\.?R\.?\s*§?\s*1[46]\d\.\d+(?:\([a-z0-9]\))?"
    match = re.search(pattern1, text)
    if match:
        return re.sub(r'\s+', ' ', match.group()).strip()

    # Priority 3 — short form in body text: "§ 164.404"
    pattern2 = r"§\s*1[46]\d\.\d+(?:\([a-z0-9]\))?"
    match = re.search(pattern2, text)
    if match:
        return f"45 CFR {match.group().strip()}"

    return ""  # nothing found


# Quick self-test — runs automatically when script starts
def test_citation_regex():
    test_cases = [
        ("# § 164.502 General rules\n(a) Standard...",  "45 CFR § 164.502"),
        ("# § 164.404 Notification\n...",               "45 CFR § 164.404"),
        ("...required by 45 CFR §164.530(b)...",        "45 CFR §164.530(b)"),
        ("...45 C.F.R. § 164.501 applies here",         "45 C.F.R. § 164.501"),
        ("...this is a general statement...",            ""),
    ]
    print("\n--- Citation Regex Test ---")
    all_pass = True
    for text, expected in test_cases:
        result = extract_hipaa_citation(text)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_pass = False
        print(f"  {status}  Got: '{result}'  Expected: '{expected}'")
    print(f"--- End Test {'✅ All passed' if all_pass else '❌ Some failed'} ---\n")

test_citation_regex()


# =============================================================================
# SECTION 4 — HELPER FUNCTION: EXTRACT SECTION TITLE FROM TEXT
# =============================================================================
# FIX 5 — Now strips the § 164.xxx number from the title.
# Before: "§ 164.302 Applicability."  → section_title = "§ 164.302 Applicability."
# After:  "§ 164.302 Applicability."  → section_title = "Applicability"

def extract_section_title(text: str) -> str:
    """
    Looks for a heading line at the start of the text.
    Returns the heading text without # symbols or section numbers.
    Example: "# § 164.302 Applicability." → "Applicability"
    """
    lines = text.strip().split("\n")

    for line in lines[:3]:  # only check first 3 lines
        line = line.strip()

        # Remove # markers
        if line.startswith("## "):
            line = line[3:].strip()
        elif line.startswith("# "):
            line = line[2:].strip()
        else:
            continue  # not a heading line — skip

        # FIX 5 — Remove leading "§ 164.xxx" from title
        # e.g. "§ 164.302 Applicability." → "Applicability."
        line = re.sub(r'^§\s*\d+\.\d+\s*', '', line).strip()

        # Remove trailing period
        line = line.rstrip('.')

        if line:
            return line

    return ""  # no heading found


# Quick self-test
def test_section_title():
    test_cases = [
        ("# § 164.302 Applicability.\nSome text",     "Applicability"),
        ("# § 164.502 General rules.\nText here",     "General rules"),
        ("## Uses and Disclosures of PHI\nText",       "Uses and Disclosures of PHI"),
        ("# Privacy Rule Overview\nMore text",         "Privacy Rule Overview"),
        ("This chunk has no heading\nJust body text",  ""),
    ]
    print("\n--- Section Title Test ---")
    for text, expected in test_cases:
        result = extract_section_title(text)
        status = "✅" if result == expected else "❌"
        print(f"  {status}  Got: '{result}'  Expected: '{expected}'")
    print("--- End Test ---\n")

test_section_title()


# =============================================================================
# SECTION 5 — LOAD AND CHUNK HIPAA PDF
# =============================================================================
# FIX 2 — Carry-forward citation:
#   When a chunk has no citation, use the last known citation.
#   This is needed because eCFR puts § 164.xxx ONCE as a heading,
#   and the following 5-10 sub-chunks have no section number.
#
# FIX 3 — Clean eCFR browser artifacts from chunk text.
#
# FIX 4 — Filter bad section titles (sub-section headers, navigation text).

def load_hipaa_chunks() -> list:
    """
    Loads the HIPAA eCFR PDF, chunks it, and adds metadata.
    Returns a list of dicts: [{"text": "...", "metadata": {...}}, ...]
    """

    # --- Set up the PDF parser ---
    parser = LlamaParse(
        api_key=LLAMA_CLOUD_KEY,
        result_type="markdown",  # preserves # headings
    )

    # --- Set up the text splitter ---
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=SEPARATORS,
    )

    # --- Bad titles list — FIX 4 ---
    # These are navigation artifacts, table headers, or too-generic titles.
    # Any section_title matching these will be set to "".
    BAD_TITLES = [
        "current page",
        "general",
        "ecfr",
        "ecfr.gov",
        "standards implementation specifications",
        "reserved",
        "table of contents",
    ]

    all_hipaa_chunks = []

    # --- Loop through HIPAA files (currently just 1 eCFR file) ---
    for file_info in HIPAA_FILES:
        path = file_info["path"]
        print(f"\n📄 Loading: {path}")

        # --- Parse the PDF ---
        documents = parser.load_data(path)
        full_text = "\n".join([doc.text for doc in documents])

        # Fix bullet encoding bug
        full_text = full_text.replace("(cid:127)", "•")

        print(f"   ✅ Parsed. Total characters: {len(full_text):,}")

        # --- Split into chunks ---
        raw_chunks = splitter.split_text(full_text)
        print(f"   ✅ Split into {len(raw_chunks)} chunks.")

        # --- FIX 2 — Carry-forward citation ---
        # last_citation must be OUTSIDE the for loop.
        # It remembers the last § number we found.
        last_citation = ""

        # --- Add metadata to each chunk ---
        for i, chunk_text in enumerate(raw_chunks):

            # --- FIX 3 — Clean eCFR browser artifacts ---
            # Remove any leftover URLs (e.g. from page footers)
            chunk_text = re.sub(r'https://www\.ecfr\.gov\S+', '', chunk_text)
            # Remove browser timestamp headers (e.g. "27/03/2026, 20:29 eCFR :: ...")
            chunk_text = re.sub(
                r'\d{2}/\d{2}/\d{4},\s+\d+:\d+\s+eCFR[^\n]*\n', '', chunk_text
            )
            chunk_text = chunk_text.strip()

            # --- Extract citation from this chunk ---
            citation = extract_hipaa_citation(chunk_text)

            # --- FIX 2 — Carry-forward logic ---
            if citation:
                # Found a real citation — update our memory
                last_citation = citation
            elif last_citation:
                # No citation in this chunk — carry forward from previous section
                citation = last_citation
            else:
                # No citation found anywhere yet (e.g. definitions section at start)
                citation = "HIPAA (citation pending)"

            # --- Extract section title ---
            section_title = extract_section_title(chunk_text)

            # --- FIX 4 — Filter bad section titles ---
            if section_title and (
                section_title.startswith("(")           # sub-section: "(a) Standard:"
                or (section_title and section_title[0].isdigit())  # numbered: "1) ..."
                or len(section_title) > 80              # table header (too long)
                or section_title.lower() in BAD_TITLES  # known bad titles
                or any(bad in section_title.lower() for bad in BAD_TITLES)
            ):
                section_title = ""

            # --- Build metadata dictionary ---
            metadata = {
                "regulation":     "HIPAA",
                "jurisdiction":   "US",
                "section_type":   file_info["section_type"],
                "section_title":  section_title,
                "citation":       citation,
                "version":        file_info["version"],
                "effective_date": file_info["effective_date"],
                "is_deprecated":  False,
                "page_number":    i // 3,
                "parent_id":      os.path.basename(path),
                "chunk_type":     "legal_text",
                "chunk_sequence": i,
                "source_url":     file_info["source_url"],
            }

            all_hipaa_chunks.append({
                "text":     chunk_text,
                "metadata": metadata,
            })

        print(f"   ✅ {len(raw_chunks)} chunks with metadata added.")

    # --- Citation summary ---
    total    = len(all_hipaa_chunks)
    pending  = sum(1 for c in all_hipaa_chunks
                   if c["metadata"]["citation"] == "HIPAA (citation pending)")
    real     = total - pending
    print(f"\n✅ HIPAA TOTAL: {total} chunks from 1 file.")
    print(f"   Real citations:   {real}  ({real/total*100:.1f}%)")
    print(f"   Pending:          {pending}  ({pending/total*100:.1f}%)")
    print(f"   (Pending = definitions section — expected and acceptable)")

    return all_hipaa_chunks


# =============================================================================
# SECTION 6 — VERIFY: PRINT 5 RANDOM CHUNKS BEFORE UPLOADING
# =============================================================================

def print_sample_chunks(chunks: list, n: int = 5):
    """
    Prints n randomly selected chunks for visual inspection.
    ALWAYS check these before typing 'yes' to upload.
    """
    print(f"\n{'='*60}")
    print(f"SAMPLE CHUNK VERIFICATION ({n} random chunks)")
    print(f"{'='*60}")

    sample = random.sample(chunks, min(n, len(chunks)))

    for idx, chunk in enumerate(sample, start=1):
        print(f"\n--- Chunk {idx} ---")
        print(f"  regulation:    {chunk['metadata']['regulation']}")
        print(f"  section_type:  {chunk['metadata']['section_type']}")
        print(f"  section_title: {chunk['metadata']['section_title']}")
        print(f"  citation:      {chunk['metadata']['citation']}")
        print(f"  version:       {chunk['metadata']['version']}")
        print(f"  chunk_sequence:{chunk['metadata']['chunk_sequence']}")
        print(f"  text preview:  {chunk['text'][:200].strip()}")
        print()

    print(f"{'='*60}")
    print("✅ Verify the above looks correct before proceeding.")
    print(f"{'='*60}\n")


# =============================================================================
# SECTION 7 — BUILD BM25 RETRIEVER FOR HIPAA
# =============================================================================

def build_bm25_hipaa(chunks: list) -> BM25Okapi:
    """
    Builds a BM25 keyword search retriever from HIPAA chunks.
    Saves it to bm25_hipaa.pkl for reuse.
    """
    tokenized_corpus = [
        chunk["text"].lower().split()
        for chunk in chunks
    ]

    bm25 = BM25Okapi(tokenized_corpus)

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bm25_path = os.path.join(BASE_DIR, "data", "bm25_hipaa.pkl")
    with open(bm25_path, "wb") as f:
        pickle.dump(bm25, f)
        pickle.dump([c["text"] for c in chunks], f)

    print("✅ BM25 HIPAA retriever built and saved to bm25_hipaa.pkl")
    return bm25


# =============================================================================
# SECTION 8 — UPLOAD HIPAA CHUNKS TO PINECONE
# =============================================================================

def upload_to_pinecone_hipaa(chunks: list):
    """
    Embeds each chunk as a vector and uploads to Pinecone namespace 'HIPAA'.
    Uploads in batches of 100 to avoid request size limits.
    """

    pc    = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",  # 1536 dimensions
        api_key=OPENAI_API_KEY,
    )

    BATCH_SIZE     = 100
    total_uploaded = 0

    for batch_start in range(0, len(chunks), BATCH_SIZE):

        batch   = chunks[batch_start : batch_start + BATCH_SIZE]
        texts   = [chunk["text"] for chunk in batch]
        vectors = embeddings.embed_documents(texts)

        records = []
        for j, chunk in enumerate(batch):
            record = {
                "id":     f"hipaa_{batch_start + j:04d}",
                "values": vectors[j],
                "metadata": {
                    **chunk["metadata"],
                    "text": chunk["text"],
                },
            }
            records.append(record)

        index.upsert(vectors=records, namespace="HIPAA")
        total_uploaded += len(batch)
        print(f"   Uploaded batch: {batch_start}–{batch_start + len(batch) - 1}  "
              f"({total_uploaded}/{len(chunks)} total)")

    print(f"\n✅ HIPAA upload complete: {total_uploaded} chunks in namespace 'HIPAA'")
    return total_uploaded


# =============================================================================
# SECTION 9 — MAIN: RUN EVERYTHING
# =============================================================================

if __name__ == "__main__":

    print("\n" + "="*60)
    print("NormIQ — ingest_step1_hipaa.py — STEP 1: HIPAA")
    print("="*60 + "\n")

    # STEP A — Load, chunk, add metadata
    hipaa_chunks = load_hipaa_chunks()

    # STEP B — Print 5 random chunks to verify quality
    # ⚠️  READ THESE CAREFULLY before proceeding!
    print_sample_chunks(hipaa_chunks, n=5)

    # STEP C — Ask for confirmation before uploading
    answer = input("Do the sample chunks look correct? Type 'yes' to upload to Pinecone: ")
    if answer.strip().lower() != "yes":
        print("❌ Upload cancelled. Fix the issue and run again.")
        exit()

    # STEP D — Build BM25 retriever
    bm25_hipaa = build_bm25_hipaa(hipaa_chunks)

    # STEP E — Upload to Pinecone
    count = upload_to_pinecone_hipaa(hipaa_chunks)

    print(f"\n{'='*60}")
    print(f"✅ STEP 1 COMPLETE")
    print(f"   {count} HIPAA chunks uploaded to Pinecone namespace 'HIPAA'")
    print(f"   BM25 retriever saved to: bm25_hipaa.pkl")
    print(f"{'='*60}")
    print("\nNext step: Run evaluator → python evaluator.py")


# =============================================================================
# END OF STEP 1
# =============================================================================
# Expected output when you run: python ingest_step1_hipaa.py
#
#   ✅ All API keys loaded.
#   ✅ Configuration loaded.
#   --- Citation Regex Test ---  (all ✅)
#   --- Section Title Test ---   (all ✅)
#   📄 Loading: data/hipaa_part164_ecfr.pdf
#      ✅ Parsed. Total characters: 245,377
#      ✅ Split into 481 chunks.
#      ✅ 481 chunks with metadata added.
#   ✅ HIPAA TOTAL: 481 chunks from 1 file.
#      Real citations:   ~300  (~62%)
#      Pending:          ~181  (~38%)   ← definitions section, acceptable
#   (5 sample chunks printed)
#   Do the sample chunks look correct? Type 'yes' to upload to Pinecone: yes
#   ✅ BM25 HIPAA retriever built and saved to bm25_hipaa.pkl
#   Uploaded batch: 0–99   (100/481 total)
#   Uploaded batch: 100–199 (200/481 total)
#   Uploaded batch: 200–299 (300/481 total)
#   Uploaded batch: 300–399 (400/481 total)
#   Uploaded batch: 400–480 (481/481 total)
#   ✅ HIPAA upload complete: 481 chunks in namespace 'HIPAA'
#   ✅ STEP 1 COMPLETE
# =============================================================================
