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

# ── Two chunks to upsert ─────────────────────────────────────
# 1. §164.312 encryption summary — fixes SC-8/SC-28/SC-13 retrieval
# 2. §164.312 base chunk — fix SC-12 from nist_crosswalk

CHUNKS = [
    {
        "id": "hipaa_164_312_encryption_summary",
        "embedding_text": (
            "164.312 HIPAA encryption requirements ePHI at rest in transit. "
            "SC-28 protection information at rest SC-8 transmission confidentiality "
            "SC-13 cryptographic protection encryption decryption addressable specification "
            "164.312(a)(2)(iv) 164.312(e)(2)(ii) technical safeguards NIST crosswalk."
        ),
        "text": (
            "HIPAA Encryption Requirements — 45 CFR §164.312 and NIST Crosswalk. "
            "Under §164.312, two addressable encryption specifications apply: "
            "(1) Encryption at rest — §164.312(a)(2)(iv): Implement a mechanism to encrypt "
            "and decrypt ePHI. This is an addressable specification — covered entities must "
            "implement encryption at rest if reasonable and appropriate, or document why not "
            "and implement an equivalent alternative. "
            "NIST mapping: SC-28 (Protection of Information at Rest) — cryptographic mechanisms "
            "to protect confidentiality of ePHI stored on systems, devices, and media. "
            "(2) Encryption in transit — §164.312(e)(2)(ii): Implement a mechanism to encrypt "
            "ePHI whenever deemed appropriate during electronic transmission. Also addressable. "
            "NIST mapping: SC-8 (Transmission Confidentiality and Integrity) — protect ePHI "
            "transmitted over electronic communications networks. "
            "Both encryption specifications also map to: "
            "SC-13 (Cryptographic Protection) — use of FIPS-validated or NSA-approved cryptography. "
            "Note: Addressable does not mean optional. Entities must implement or document "
            "why not and apply an equivalent alternative measure. "
            "Summary of NIST controls for HIPAA encryption: "
            "SC-28 → ePHI at rest; SC-8 → ePHI in transit; SC-13 → cryptographic standards."
        ),
        "metadata": {
            "regulation":     "HIPAA",
            "section":        "164.312",
            "section_title":  "Technical safeguards - Encryption",
            "subpart":        "Security Rule",
            "section_type":   "Security Rule",
            "citation":       "45 CFR § 164.312",
            "nist_crosswalk": ["SC-28", "SC-8", "SC-13"],   # SC-12 excluded
            "gdpr_crosswalk": ["Article 32"],
            "source":         "eCFR 45 CFR Part 164",
            "chunk_type":     "hipaa_production_chunk",
            "subsection":     "(a)(2)(iv), (e)(2)(ii)",
            "text": (
                "HIPAA Encryption Requirements — 45 CFR §164.312 and NIST Crosswalk. "
                "Under §164.312, two addressable encryption specifications apply: "
                "(1) Encryption at rest — §164.312(a)(2)(iv): Implement a mechanism to encrypt "
                "and decrypt ePHI. This is an addressable specification — covered entities must "
                "implement encryption at rest if reasonable and appropriate, or document why not "
                "and implement an equivalent alternative. "
                "NIST mapping: SC-28 (Protection of Information at Rest) — cryptographic mechanisms "
                "to protect confidentiality of ePHI stored on systems, devices, and media. "
                "(2) Encryption in transit — §164.312(e)(2)(ii): Implement a mechanism to encrypt "
                "ePHI whenever deemed appropriate during electronic transmission. Also addressable. "
                "NIST mapping: SC-8 (Transmission Confidentiality and Integrity) — protect ePHI "
                "transmitted over electronic communications networks. "
                "Both encryption specifications also map to: "
                "SC-13 (Cryptographic Protection) — use of FIPS-validated or NSA-approved cryptography. "
                "Note: Addressable does not mean optional. Entities must implement or document "
                "why not and apply an equivalent alternative measure. "
                "Summary of NIST controls for HIPAA encryption: "
                "SC-28 → ePHI at rest; SC-8 → ePHI in transit; SC-13 → cryptographic standards."
            ),
        }
    },
    {
        # Fix the base §164.312 chunk — remove SC-12 from nist_crosswalk
        # This chunk currently has SC-12 which causes wrong crosswalk retrieval
        "id": "hipaa_164_312_5f4e49",   # existing chunk id from the data
        "embedding_text": (
            "164.312 Technical safeguards access control audit controls integrity "
            "transmission security person entity authentication ePHI."
        ),
        "text": (
            "A covered entity or business associate must, in accordance with §164.306, "
            "implement the following technical safeguard standards: "
            "Access Control (§164.312(a)(1)) — allow access only to authorized persons or programs. "
            "Audit Controls (§164.312(b), Required) — record and examine activity in systems containing ePHI. "
            "Integrity (§164.312(c)(1)) — protect ePHI from improper alteration or destruction. "
            "Person or Entity Authentication (§164.312(d), Required) — verify identity before granting access. "
            "Transmission Security (§164.312(e)(1)) — guard against unauthorized access to ePHI in transit. "
            "Implementation specifications are either Required or Addressable as specified per standard."
        ),
        "metadata": {
            "regulation":     "HIPAA",
            "section":        "164.312",
            "section_title":  "Technical safeguards",
            "subpart":        "Security Rule",
            "section_type":   "Security Rule",
            "citation":       "45 CFR § 164.312",
            "nist_crosswalk": ["AC-3", "AC-6", "IA-2", "AU-2", "SC-8", "SC-28", "SC-13"],  # SC-12 removed
            "gdpr_crosswalk": ["Article 32"],
            "source":         "eCFR 45 CFR Part 164",
            "chunk_type":     "hipaa_production_chunk",
            "subsection":     "",
            "text": (
                "A covered entity or business associate must, in accordance with §164.306, "
                "implement the following technical safeguard standards: "
                "Access Control (§164.312(a)(1)) — allow access only to authorized persons or programs. "
                "Audit Controls (§164.312(b), Required) — record and examine activity in systems containing ePHI. "
                "Integrity (§164.312(c)(1)) — protect ePHI from improper alteration or destruction. "
                "Person or Entity Authentication (§164.312(d), Required) — verify identity before granting access. "
                "Transmission Security (§164.312(e)(1)) — guard against unauthorized access to ePHI in transit. "
                "Implementation specifications are either Required or Addressable as specified per standard."
            ),
        }
    }
]


def upsert_chunks():
    print("=" * 50)
    print("Upserting §164.312 Encryption Chunks...")
    print("=" * 50)

    for chunk in CHUNKS:
        print(f"\nProcessing: {chunk['id']}")
        print(f"  Citation: {chunk['metadata']['citation']}")
        print(f"  NIST:     {chunk['metadata']['nist_crosswalk']}")

        # Embed
        response = openai_client.embeddings.create(
            input = chunk["embedding_text"],
            model = EMBEDDING_MODEL
        )
        embedding = response.data[0].embedding

        # Upsert
        index.upsert(
            vectors = [{
                "id":       chunk["id"],
                "values":   embedding,
                "metadata": chunk["metadata"],
            }],
            namespace = NAMESPACE_HIPAA
        )
        print(f"  ✅ Upserted")

    print()
    print("=" * 50)
    print("Done! 2 chunks upserted:")
    print("  1. New encryption summary — SC-28/SC-8/SC-13 all in text")
    print("  2. Base §164.312 chunk — SC-12 removed from crosswalk")
    print("=" * 50)


if __name__ == "__main__":
    upsert_chunks()
