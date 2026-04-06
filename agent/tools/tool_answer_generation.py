import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import json
from openai import OpenAI
from config.settings import OPENAI_API_KEY, LLM_MODEL
from agent.prompts.query_understanding_prompt import ANSWER_GENERATION_PROMPT

# ── Initialise OpenAI ────────────────────────────────────────
client = OpenAI(api_key=OPENAI_API_KEY)


# ── Format chunks for prompt ─────────────────────────────────
def format_chunks(chunks: list) -> str:
    """Format chunks into readable text for the prompt."""
    formatted = []
    for i, chunk in enumerate(chunks):
        citation   = chunk.get("citation", "")
        regulation = chunk.get("regulation", "Unknown")
        text       = chunk.get("text", "")
        score      = chunk.get("cohere_score", 0)
        metadata   = chunk.get("metadata", {})

        # For NIST chunks — get control_id from metadata
        if regulation == "NIST" and not citation:
            citation = metadata.get("control_id", 
                      metadata.get("citation", f"NIST-{i+1}"))

        # For HIPAA chunks
        if regulation == "HIPAA" and not citation:
            citation = metadata.get("citation",
                      metadata.get("section", f"HIPAA-{i+1}"))

        formatted.append(
            f"[Chunk {i+1}]\n"
            f"Regulation: {regulation}\n"
            f"Citation:   {citation}\n"
            f"Relevance:  {score:.3f}\n"
            f"Text:       {text}\n"
        )

    return "\n".join(formatted)


# ── Generate answer ──────────────────────────────────────────
def generate_answer(question: str,
                    chunks: list,
                    regulations: list,
                    intent: str) -> dict:
    """
    Tool 4 — Answer Generation
    Takes top chunks and generates structured JSON answer
    with citations and confidence.
    """
    print(f"\nGenerating answer for: '{question[:60]}'")

    if not chunks:
        return {
            "answer":             "No relevant regulation chunks found.",
            "citations":          [],
            "has_conflict":       False,
            "conflict_warning":   "",
            "regulations_covered": []
        }

    # Format chunks for prompt
    chunks_text = format_chunks(chunks)

    # Build prompt
    prompt = ANSWER_GENERATION_PROMPT.format(
        question    = question,
        regulations = ", ".join(regulations),
        intent      = intent,
        chunks      = chunks_text
    )

    try:
        response = client.chat.completions.create(
            model       = LLM_MODEL,
            messages    = [{"role": "user", "content": prompt}],
            temperature = 0.0
        )

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        result = json.loads(raw)

        # Validate fields
        result.setdefault("answer",              "")
        result.setdefault("citations",           [])
        result.setdefault("has_conflict",        False)
        result.setdefault("conflict_warning",    "")
        result.setdefault("regulations_covered", regulations)

        print(f"Answer generated successfully")
        print(f"Citations found: {len(result['citations'])}")
        print(f"Has conflict:    {result['has_conflict']}")

        return result

    except json.JSONDecodeError as e:
        print(f"JSON parse error in answer generation: {e}")
        return {
            "answer":             raw if raw else "Could not generate answer.",
            "citations":          [],
            "has_conflict":       False,
            "conflict_warning":   "",
            "regulations_covered": regulations
        }

    except Exception as e:
        print(f"Answer generation error: {e}")
        return {
            "answer":             "System error — please try again.",
            "citations":          [],
            "has_conflict":       False,
            "conflict_warning":   "",
            "regulations_covered": []
        }


# ── Format final answer for display ─────────────────────────
def format_answer_for_display(result: dict) -> str:
    """Format the JSON answer into readable text for Telegram/UI."""
    lines = []

    # Main answer
    lines.append(result["answer"])

    # Conflict warning
    if result.get("has_conflict") and result.get("conflict_warning"):
        lines.append(f"\n{result['conflict_warning']}")

    # Citations
    if result.get("citations"):
        lines.append("\n📋 Sources cited:")
        for cite in result["citations"]:
            lines.append(f"  • {cite['regulation']} — "
                        f"{cite['citation']}")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════
# TEST
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing answer generation...\n")

    # Mock chunks
    mock_chunks = [
        {
            "citation":     "45 CFR § 164.404",
            "regulation":   "HIPAA",
            "cohere_score": 0.952,
            "text": "A covered entity shall notify each individual whose "
                    "unsecured protected health information has been or is "
                    "reasonably believed to have been accessed, acquired, "
                    "used, or disclosed as a result of such breach. "
                    "Notification shall be provided without unreasonable "
                    "delay and in no case later than 60 calendar days "
                    "after discovery of a breach."
        },
        {
            "citation":     "GDPR Article 33",
            "regulation":   "GDPR",
            "cohere_score": 0.931,
            "text": "In the case of a personal data breach, the controller "
                    "shall without undue delay and, where feasible, not "
                    "later than 72 hours after having become aware of it, "
                    "notify the personal data breach to the supervisory "
                    "authority."
        },
        {
            "citation":     "45 CFR § 164.402",
            "regulation":   "HIPAA",
            "cohere_score": 0.844,
            "text": "Breach means the acquisition, access, use, or "
                    "disclosure of protected health information in a manner "
                    "not permitted under subpart E of this part which "
                    "compromises the security or privacy of the protected "
                    "health information."
        }
    ]

    # Test 1 — HIPAA only
    print("=" * 50)
    print("Test 1 — HIPAA breach notification deadline")
    result = generate_answer(
        question    = "What is the HIPAA breach notification deadline?",
        chunks      = mock_chunks[:1],
        regulations = ["HIPAA"],
        intent      = "lookup"
    )
    print(f"\nAnswer:\n{result['answer']}")
    print(f"\nCitations: {result['citations']}")

    # Test 2 — HIPAA + GDPR conflict
    print("\n" + "=" * 50)
    print("Test 2 — HIPAA vs GDPR breach notification")
    result = generate_answer(
        question    = "Compare HIPAA and GDPR breach notification deadlines",
        chunks      = mock_chunks,
        regulations = ["HIPAA", "GDPR"],
        intent      = "comparison"
    )
    print(f"\nAnswer:\n{result['answer']}")
    print(f"\nConflict: {result['has_conflict']}")
    print(f"Warning:  {result['conflict_warning']}")

    # Display formatted
    print("\n" + "=" * 50)
    print("Formatted for display:")
    print(format_answer_for_display(result))

    print("\nAnswer generation test complete!")