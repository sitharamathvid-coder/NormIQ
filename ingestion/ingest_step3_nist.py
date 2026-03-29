# =============================================================================
# NormIQ — ingest_step3_nist.py  (STEP 3 OF 4: NIST ONLY)
# =============================================================================
# What this file does:
#   1. Loads nist_800_53.json using json.load()
#   2. Iterates catalog → groups → controls → parts
#   3. Extracts: statement text + guidance text per control
#   4. Adds 13 metadata fields to every chunk
#   5. Builds bm25_nist.pkl
#   6. Uploads to Pinecone namespace "NIST"
#
# JSON structure (what we learned from inspection):
#   data["catalog"]["groups"]          → list of 20 control families
#     group["id"]                      → "ac", "sc", "si" etc.
#     group["title"]                   → "Access Control", "System and Comms" etc.
#     group["controls"]                → list of controls in this family
#       control["id"]                  → "ac-1", "sc-28" etc.
#       control["title"]               → "Policy and Procedures" etc.
#       control["parts"]               → list of parts (statement, guidance, etc.)
#         part["name"]                 → "statement" or "guidance"
#         part["prose"]                → the actual text (sometimes missing)
#         part["parts"]                → nested sub-items (a., b., 1., 2. etc.)
#
# Citation = f"NIST {control_id.upper()}" → "NIST AC-1"
# This comes FREE from the id field — no regex needed.
#
# IMPORTANT: The prose fields contain {{ insert: param, ac-1_prm_1 }} placeholders.
# These are NIST's way of saying "fill in your organization's value here."
# We will clean them out and replace with [ORG-DEFINED VALUE].
# =============================================================================


# =============================================================================
# SECTION 0 — IMPORTS
# =============================================================================

import os
import re
import json
import random
import pickle

from dotenv import load_dotenv
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

PINECONE_INDEX_NAME  = "normiq"
NIST_JSON_FILE       = "data/nist_800_53.json"

NIST_REGULATION      = "NIST"
NIST_JURISDICTION    = "Global"
NIST_VERSION         = "rev5"
NIST_EFFECTIVE_DATE  = "2020-09-23"
NIST_SOURCE_URL      = "https://doi.org/10.6028/NIST.SP.800-53r5"

print("✅ Configuration loaded.")


# =============================================================================
# SECTION 3 — HELPER: CLEAN NIST PLACEHOLDER TEXT
# =============================================================================
# NIST prose contains strings like:
#   "Develop, document, and disseminate to {{ insert: param, ac-1_prm_1 }}:"
#
# These {{ insert: param, ... }} markers mean "your organization decides this value."
# We replace them with [ORG-DEFINED VALUE] so the text is readable.

def clean_nist_prose(text: str) -> str:
    """
    Replaces {{ insert: param, xyz }} placeholders with [ORG-DEFINED VALUE].
    Also cleans up extra whitespace.
    """
    # re.sub = find all matches of pattern and replace with replacement string
    # r'\{\{.*?\}\}' = matches {{ anything }} where .*? means "as few chars as possible"
    # The ? makes it "non-greedy" — stops at the FIRST }} it finds
    cleaned = re.sub(r'\{\{.*?\}\}', '[ORG-DEFINED VALUE]', text)

    # Clean up multiple spaces left after replacement
    cleaned = re.sub(r'  +', ' ', cleaned)
    # r'  +' = two or more spaces → replace with single space

    return cleaned.strip()


# Quick test
def test_clean_prose():
    test = "Disseminate to {{ insert: param, ac-1_prm_1 }}: policy that addresses purpose."
    result = clean_nist_prose(test)
    expected = "Disseminate to [ORG-DEFINED VALUE]: policy that addresses purpose."
    status = "✅" if result == expected else "❌"
    print(f"\n--- NIST Prose Cleaning Test ---")
    print(f"  {status}  Got: '{result}'")
    print(f"--- End Test ---\n")

test_clean_prose()


# =============================================================================
# SECTION 4 — HELPER: EXTRACT TEXT FROM NESTED PARTS
# =============================================================================
# The NIST JSON has deeply nested parts:
#   control → parts → parts → parts → prose
#
# Example for AC-1:
#   part[0] = statement
#     part[0].parts[0] = item a.
#       part[0].parts[0].parts[0] = item 1.
#         part[0].parts[0].parts[0].prose = "Develop, document..."
#
# We want to collect ALL prose text from all levels into one string.
# We use a "recursive" function — a function that calls itself.

def extract_prose_recursive(parts: list, depth: int = 0) -> str:
    """
    Walks through all nested parts and collects all prose text.
    depth = how deep we are in the nesting (used for indentation).
    Returns one big string with all text joined together.
    """
    lines = []

    for part in parts:
        # Skip assessment-objective and assessment-method parts
        # These are evaluation checklists, not the actual control text
        part_name = part.get("name", "")
        if part_name in ["assessment-objective", "assessment-method"]:
            continue

        # Get the prose text of this part (if it has one)
        prose = part.get("prose", "")
        if prose:
            prose = clean_nist_prose(prose)
            if prose:
                lines.append(prose)

        # Recursively get text from nested parts
        nested = part.get("parts", [])
        if nested:
            nested_text = extract_prose_recursive(nested, depth + 1)
            if nested_text:
                lines.append(nested_text)

    return " ".join(lines)
    # Join all collected lines with a space
    # This gives us one continuous text string per control


# =============================================================================
# SECTION 5 — LOAD NIST CONTROLS FROM JSON
# =============================================================================
# Strategy:
#   For each control we create TWO chunks if both exist:
#     Chunk A: statement text  (section_type = "Control")
#     Chunk B: guidance text   (section_type = "Guidance")
#
#   Why two chunks?
#   The statement = WHAT you must do ("Develop and document a policy...")
#   The guidance  = WHY and HOW      ("Access control policy addresses...")
#   These answer different questions so they should be separate chunks.
#
#   We SKIP:
#     assessment-objective parts (evaluation checklists — not useful for Q&A)
#     assessment-method parts    (same reason)

def load_nist_chunks() -> list:
    """
    Loads nist_800_53.json and creates one chunk per control part (statement + guidance).
    Returns a list of dicts: [{"text": "...", "metadata": {...}}, ...]
    """

    print(f"\n📄 Loading NIST controls from {NIST_JSON_FILE}")

    with open(NIST_JSON_FILE, encoding="utf-8") as f:
        data = json.load(f)
    # json.load(f) = reads the entire JSON file into a Python dict

    groups = data["catalog"]["groups"]
    # groups = list of 20 control families (AC, AT, AU, CA, CM, CP, IA, IR,
    #          MA, MP, PE, PL, PM, PS, PT, RA, SA, SC, SI, SR)

    print(f"   Control families found: {len(groups)}")

    all_nist_chunks = []
    chunk_index = 0  # Global counter across all controls

    for group in groups:
        # --- Get family information ---
        family_id    = group.get("id", "").upper()     # "AC", "SC", "SI" etc.
        family_title = group.get("title", "Unknown")   # "Access Control" etc.

        controls = group.get("controls", [])

        for control in controls:
            # --- Get control information ---
            ctrl_id    = control.get("id", "").upper()   # "AC-1", "SC-28" etc.
            ctrl_title = control.get("title", "")        # "Policy and Procedures"
            citation   = f"NIST {ctrl_id}"               # "NIST AC-1"

            parts = control.get("parts", [])

            # --- Separate statement parts from guidance parts ---
            statement_parts = [p for p in parts if p.get("name") == "statement"]
            guidance_parts  = [p for p in parts if p.get("name") == "guidance"]
            # List comprehension with condition:
            # [item for item in list if condition]
            # = loop through parts, keep only those where name == "statement"

            # --- Extract statement text ---
            if statement_parts:
                statement_text = extract_prose_recursive(statement_parts)
                statement_text = statement_text.strip()

                if len(statement_text) > 20:  # Skip if too short
                    metadata = {
                        "regulation":       NIST_REGULATION,    # "NIST"
                        "jurisdiction":     NIST_JURISDICTION,  # "Global"
                        "section_type":     "Control",          # This is the requirement
                        "section_title":    ctrl_title,         # "Policy and Procedures"
                        "citation":         citation,           # "NIST AC-1"
                        "version":          NIST_VERSION,       # "rev5"
                        "effective_date":   NIST_EFFECTIVE_DATE,
                        "is_deprecated":    False,
                        "page_number":      chunk_index,
                        "parent_id":        family_id,          # "AC"
                        "chunk_type":       "control",
                        "chunk_sequence":   chunk_index,
                        "source_url":       NIST_SOURCE_URL,
                    }
                    all_nist_chunks.append({
                        "text":     f"{ctrl_id}: {ctrl_title}\n{statement_text}",
                        # We prepend "AC-1: Policy and Procedures\n" to the text
                        # so the control ID is always searchable in BM25
                        "metadata": metadata,
                    })
                    chunk_index += 1

            # --- Extract guidance text ---
            if guidance_parts:
                guidance_text = extract_prose_recursive(guidance_parts)
                guidance_text = guidance_text.strip()

                if len(guidance_text) > 20:
                    metadata = {
                        "regulation":       NIST_REGULATION,
                        "jurisdiction":     NIST_JURISDICTION,
                        "section_type":     "Guidance",         # This is the explanation
                        "section_title":    ctrl_title,
                        "citation":         citation,
                        "version":          NIST_VERSION,
                        "effective_date":   NIST_EFFECTIVE_DATE,
                        "is_deprecated":    False,
                        "page_number":      chunk_index,
                        "parent_id":        family_id,
                        "chunk_type":       "guidance",
                        "chunk_sequence":   chunk_index,
                        "source_url":       NIST_SOURCE_URL,
                    }
                    all_nist_chunks.append({
                        "text":     f"{ctrl_id} Guidance: {ctrl_title}\n{guidance_text}",
                        "metadata": metadata,
                    })
                    chunk_index += 1

    print(f"   ✅ {len(all_nist_chunks)} NIST chunks created.")

    # Print family breakdown
    from collections import Counter
    family_counts = Counter(c["metadata"]["parent_id"] for c in all_nist_chunks)
    print(f"   Family breakdown: {dict(sorted(family_counts.items()))}")

    return all_nist_chunks


# =============================================================================
# SECTION 6 — VERIFY: PRINT 5 RANDOM CHUNKS
# =============================================================================

def print_sample_chunks(chunks: list, n: int = 5):
    """Prints n random chunks for visual verification."""
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
        print(f"  parent_id:     {chunk['metadata']['parent_id']} (family)")
        print(f"  text preview:  {chunk['text'][:250].strip()}")

    print(f"\n{'='*60}")


# =============================================================================
# SECTION 7 — BUILD BM25 RETRIEVER FOR NIST
# =============================================================================

def build_bm25_nist(chunks: list) -> BM25Okapi:
    """Builds BM25 retriever for all NIST chunks."""

    tokenized_corpus = [
        chunk["text"].lower().split()
        for chunk in chunks
    ]

    bm25 = BM25Okapi(tokenized_corpus)

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bm25_path = os.path.join(BASE_DIR, "data", "bm25_nist.pkl")
    with open(bm25_path, "wb") as f:
        pickle.dump(bm25, f)
        pickle.dump([c["text"] for c in chunks], f)

    print("✅ BM25 NIST retriever built and saved to bm25_nist.pkl")
    return bm25


# =============================================================================
# SECTION 8 — UPLOAD NIST CHUNKS TO PINECONE
# =============================================================================

def upload_to_pinecone_nist(chunks: list):
    """Embeds each chunk and uploads to Pinecone namespace 'NIST'."""

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small",
        api_key=OPENAI_API_KEY,
    )

    BATCH_SIZE = 100
    total_uploaded = 0

    for batch_start in range(0, len(chunks), BATCH_SIZE):

        batch  = chunks[batch_start : batch_start + BATCH_SIZE]
        texts  = [chunk["text"] for chunk in batch]
        vectors = embeddings.embed_documents(texts)

        records = []
        for j, chunk in enumerate(batch):
            record = {
                "id":     f"nist_{batch_start + j:04d}",
                "values": vectors[j],
                "metadata": {
                    **chunk["metadata"],
                    "text": chunk["text"],
                },
            }
            records.append(record)

        index.upsert(vectors=records, namespace="NIST")

        total_uploaded += len(batch)
        print(f"   Uploaded batch: {batch_start}–{batch_start + len(batch) - 1}  "
              f"({total_uploaded}/{len(chunks)} total)")

    print(f"\n✅ NIST upload complete: {total_uploaded} chunks in namespace 'NIST'")
    return total_uploaded


# =============================================================================
# SECTION 9 — MAIN
# =============================================================================

if __name__ == "__main__":

    print("\n" + "="*60)
    print("NormIQ — ingest_step3_nist.py — STEP 3: NIST")
    print("="*60 + "\n")

    # STEP A: Load and parse NIST JSON
    nist_chunks = load_nist_chunks()

    # STEP B: Print 5 random chunks to verify
    print_sample_chunks(nist_chunks, n=5)

    # STEP C: Ask before uploading
    answer = input("\nDo the sample chunks look correct? Type 'yes' to upload to Pinecone: ")
    if answer.strip().lower() != "yes":
        print("❌ Upload cancelled. Fix the issue and run again.")
        exit()

    # STEP D: Build BM25
    build_bm25_nist(nist_chunks)

    # STEP E: Upload to Pinecone
    count = upload_to_pinecone_nist(nist_chunks)

    print(f"\n{'='*60}")
    print(f"✅ STEP 3 COMPLETE")
    print(f"   {count} NIST chunks uploaded to Pinecone namespace 'NIST'")
    print(f"   BM25 retriever saved to: bm25_nist.pkl")
    print(f"{'='*60}")
    print("\nAll 3 namespaces loaded. Next: python ingest_step4_verify.py")


# =============================================================================
# END OF STEP 3
# =============================================================================
# Expected output:
#   Control families found: 20
#   ~900 NIST chunks created (statement + guidance per control)
#   Family breakdown: {'AC': 60, 'AT': 10, 'AU': 40, ...}
#   (5 sample chunks printed)
#   Type 'yes' → upload begins in batches of 100
#   ✅ STEP 3 COMPLETE
# =============================================================================
