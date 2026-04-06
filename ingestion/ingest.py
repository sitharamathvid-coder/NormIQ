import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.ingest_nist     import ingest_nist
from ingestion.ingest_hipaa    import ingest_hipaa
from ingestion.ingest_gdpr     import ingest_gdpr
from ingestion.ingest_penalties import ingest_penalties


def run_all():
    print("\n" + "=" * 60)
    print("   NormIQ — Full Ingestion Pipeline Starting")
    print("=" * 60 + "\n")

    results = {}

    # ── NIST ────────────────────────────────────────────────
    print("\n[1/4] Starting NIST ingestion...")
    nist_success, nist_failed = ingest_nist()
    results["NIST"] = {
        "success": nist_success,
        "failed":  nist_failed
    }

    # ── HIPAA ───────────────────────────────────────────────
    print("\n[2/4] Starting HIPAA ingestion...")
    hipaa_success, hipaa_failed = ingest_hipaa()
    results["HIPAA"] = {
        "success": hipaa_success,
        "failed":  hipaa_failed
    }

    # ── HIPAA Penalties ─────────────────────────────────────
    print("\n[3/4] Starting HIPAA Penalties ingestion...")
    pen_success, pen_failed = ingest_penalties()
    results["PENALTIES"] = {
        "success": pen_success,
        "failed":  pen_failed
    }

    # ── GDPR ────────────────────────────────────────────────
    print("\n[4/4] Starting GDPR ingestion...")
    gdpr_success, gdpr_failed = ingest_gdpr()
    results["GDPR"] = {
        "success": gdpr_success,
        "failed":  gdpr_failed
    }

    # ── Final Summary ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("   NormIQ — Full Ingestion Complete!")
    print("=" * 60)

    total_success = 0
    total_failed  = 0

    for namespace, result in results.items():
        status = "✅" if result["failed"] == 0 else "⚠️"
        print(f"{status} {namespace:12} → "
              f"Uploaded: {result['success']:4} | "
              f"Failed: {result['failed']}")
        total_success += result["success"]
        total_failed  += result["failed"]

    print("-" * 60)
    print(f"   Total uploaded: {total_success}")
    print(f"   Total failed:   {total_failed}")
    print("=" * 60)

    if total_failed == 0:
        print("\n All data successfully uploaded to Pinecone!")
        print(" Namespaces: HIPAA | GDPR | NIST")
        print(" Ready to start RAG pipeline!\n")
    else:
        print(f"\n⚠  {total_failed} chunks failed.")
        print(" Re-run individual ingest files to fix.\n")


if __name__ == "__main__":
    run_all()