import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

import json
from openai import OpenAI
from config.settings import OPENAI_API_KEY, LLM_MODEL
from agent.prompts.query_understanding_prompt import QUERY_UNDERSTANDING_PROMPT

# ── Initialise OpenAI ────────────────────────────────────────
client = OpenAI(api_key=OPENAI_API_KEY)


def understand_query(question: str) -> dict:
    """
    Tool 1 — Query Understanding
    Detects regulation, jurisdiction, intent, keywords.
    Returns structured dict for the agent to use.
    """
    try:
        prompt = QUERY_UNDERSTANDING_PROMPT.format(
            question=question
        )

        response = client.chat.completions.create(
            model    = LLM_MODEL,
            messages = [{"role": "user", "content": prompt}],
            temperature = 0.0  # deterministic — always same output
        )

        raw = response.choices[0].message.content.strip()

        # Clean markdown if present
        raw = raw.replace("```json", "").replace("```", "").strip()

        result = json.loads(raw)

        # Validate required fields
        result.setdefault("regulations",           [])
        result.setdefault("jurisdictions",         [])
        result.setdefault("intent",                "lookup")
        result.setdefault("keywords",              [])
        result.setdefault("is_clear",              True)
        result.setdefault("clarification_needed",  "")
        result.setdefault("use_crosswalk",         False)
        result.setdefault("explanation",           "")

        print(f"Query understood: {result['regulations']} | "
              f"Intent: {result['intent']} | "
              f"Clear: {result['is_clear']}")

        return result

    except json.JSONDecodeError as e:
        print(f"JSON parse error in query understanding: {e}")
        # Safe fallback
        return {
            "regulations":          ["HIPAA"],
            "jurisdictions":        ["US"],
            "intent":               "lookup",
            "keywords":             question.split()[:5],
            "is_clear":             True,
            "clarification_needed": "",
            "use_crosswalk":        False,
            "explanation":          "Fallback — JSON parse failed"
        }

    except Exception as e:
        print(f"Query understanding error: {e}")
        return {
            "regulations":          ["HIPAA"],
            "jurisdictions":        ["US"],
            "intent":               "lookup",
            "keywords":             [],
            "is_clear":             True,
            "clarification_needed": "",
            "use_crosswalk":        False,
            "explanation":          f"Error: {str(e)}"
        }


# ════════════════════════════════════════════════════════════
# TEST
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Testing query understanding...\n")

    tests = [
        "What is the HIPAA breach notification deadline?",
        "Can we store EU patient data on a US server?",
        "What technical controls map to HIPAA access control?",
        "Can I share?",
        "Compare HIPAA and GDPR breach notification rules",
    ]

    for q in tests:
        print(f"Q: {q}")
        result = understand_query(q)
        print(f"   Regulations:  {result['regulations']}")
        print(f"   Intent:       {result['intent']}")
        print(f"   Is clear:     {result['is_clear']}")
        print(f"   Use crosswalk:{result['use_crosswalk']}")
        if not result['is_clear']:
            print(f"   Ask nurse:    {result['clarification_needed']}")
        print()

    print("Query understanding test complete!")