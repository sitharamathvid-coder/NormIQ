import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import OpenAI
from pinecone import Pinecone
from config.settings import (
    OPENAI_API_KEY,
    PINECONE_API_KEY,
    PINECONE_INDEX,
    NAMESPACE_HIPAA,
    EMBEDDING_MODEL,
)

# ── Clients ──────────────────────────────────────────────────
openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc            = Pinecone(api_key=PINECONE_API_KEY)
index         = pc.Index(PINECONE_INDEX)

# ── The single chunk to upsert ───────────────────────────────
CHUNK = {
    "id": "hipaa_164_310_summary_f98501",
    "embedding_text": (
        "164.310 Physical safeguards HIPAA requirements. "
        "Facility access controls workstation use workstation security device media controls "
        "disposal media re-use physical safeguards ePHI electronic protected health information "
        "required addressable implementation specifications 164.310(a)(1) 164.310(b) 164.310(c) 164.310(d)."
    ),
    "text": (
        "HIPAA Physical Safeguards — 45 CFR § 164.310. "
        "Physical safeguards are physical measures, policies, and procedures to protect "
        "electronic information systems and related buildings from natural and environmental "
        "hazards and unauthorized intrusion. Under §164.310, covered entities and business "
        "associates must implement four standards: "
        "(1) Facility access controls (§164.310(a)(1)): Implement policies and procedures to "
        "limit physical access to electronic information systems and the facilities in which "
        "they are housed, including contingency operations, facility security plan, access "
        "control and validation procedures, and maintenance records. "
        "(2) Workstation use (§164.310(b), Required): Implement policies specifying proper "
        "functions, manner of performance, and physical attributes of workstation surroundings "
        "that access electronic protected health information. "
        "(3) Workstation security (§164.310(c), Required): Implement physical safeguards for "
        "all workstations that access ePHI to restrict access to authorized users only. "
        "(4) Device and media controls (§164.310(d)(1)): Govern the receipt and removal of "
        "hardware and electronic media containing ePHI. Required specifications include: "
        "Disposal — final disposition of ePHI and hardware; "
        "Media re-use — remove ePHI before media is reused. "
        "Addressable specifications include: Accountability — track hardware movements; "
        "Data backup and storage — create exact copy before moving equipment."
    ),
    "metadata": {
        "regulation":     "HIPAA",
        "section":        "164.310",
        "section_title":  "Physical safeguards",
        "subpart":        "Security Rule",
        "section_type":   "Security Rule",
        "citation":       "45 CFR § 164.310",
        "nist_crosswalk": ["PE-2", "PE-3", "PE-6", "PE-8", "MP-6", "MP-7"],
        "gdpr_crosswalk": ["Article 32"],
        "source":         "eCFR 45 CFR Part 164",
        "chunk_type":     "hipaa_production_chunk",
        "subsection":     "",
        "text": (
            "HIPAA Physical Safeguards — 45 CFR § 164.310. "
            "Physical safeguards are physical measures, policies, and procedures to protect "
            "electronic information systems and related buildings from natural and environmental "
            "hazards and unauthorized intrusion. Under §164.310, covered entities and business "
            "associates must implement four standards: "
            "(1) Facility access controls (§164.310(a)(1)): Implement policies and procedures to "
            "limit physical access to electronic information systems and the facilities in which "
            "they are housed, including contingency operations, facility security plan, access "
            "control and validation procedures, and maintenance records. "
            "(2) Workstation use (§164.310(b), Required): Implement policies specifying proper "
            "functions, manner of performance, and physical attributes of workstation surroundings "
            "that access electronic protected health information. "
            "(3) Workstation security (§164.310(c), Required): Implement physical safeguards for "
            "all workstations that access ePHI to restrict access to authorized users only. "
            "(4) Device and media controls (§164.310(d)(1)): Govern the receipt and removal of "
            "hardware and electronic media containing ePHI. Required specifications include: "
            "Disposal — final disposition of ePHI and hardware; "
            "Media re-use — remove ePHI before media is reused. "
            "Addressable specifications include: Accountability — track hardware movements; "
            "Data backup and storage — create exact copy before moving equipment."
        ),
    }
}


def upsert_chunk():
    print("=" * 50)
    print("Upserting §164.310 Summary Chunk...")
    print("=" * 50)
    print(f"ID:        {CHUNK['id']}")
    print(f"Citation:  {CHUNK['metadata']['citation']}")
    print(f"Namespace: {NAMESPACE_HIPAA}")
    print()

    # Get embedding from the optimised embedding_text
    print("Generating embedding...")
    response = openai_client.embeddings.create(
        input = CHUNK["embedding_text"],
        model = EMBEDDING_MODEL
    )
    embedding = response.data[0].embedding
    print(f"Embedding dimensions: {len(embedding)}")

    # Upsert single vector
    print("Upserting to Pinecone...")
    index.upsert(
        vectors = [{
            "id":       CHUNK["id"],
            "values":   embedding,
            "metadata": CHUNK["metadata"],
        }],
        namespace = NAMESPACE_HIPAA
    )

    print()
    print("=" * 50)
    print("Done! §164.310 summary chunk upserted.")
    print("Physical safeguards queries will now retrieve §164.310 correctly.")
    print("=" * 50)


if __name__ == "__main__":
    upsert_chunk()
