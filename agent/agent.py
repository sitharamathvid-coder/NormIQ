import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
 
import uuid
from pipeline.guardrails                  import check_input, check_output, check_regulation_conflict
from agent.tools.tool_query_understanding import understand_query
from agent.tools.tool_hybrid_search       import hybrid_search
from agent.tools.tool_multi_query         import multi_query_search
from agent.tools.tool_answer_generation   import generate_answer, format_answer_for_display
from database.db_manager                  import (
    cache_get, cache_set,
    audit_log_create, audit_log_update_answer,
    chat_history_add, generate_ref_id
)
from config.settings import CONFIDENCE_THRESHOLD
 
 
def alert_officer_telegram(ref_id: str, question: str,
                           answer: str, citations: list,
                           confidence: float, regulations: list,
                           user_id: str,
                           summary: str = ""):
    """Send low confidence alert to officer via Telegram."""
    try:
        import asyncio
        from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
        from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_OFFICER_CHAT_ID
 
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_OFFICER_CHAT_ID:
            print("Telegram not configured — skipping alert")
            return
 
        cite_text = "\n".join([
            f"  • {c.get('citation', '')}"
            for c in citations
        ]) if citations else "None"
 
        message = (
            f"⚠ <b>Review Required</b>\n\n"
            f"📋 <b>Ref:</b> <code>{ref_id}</code>\n"
            f"👤 <b>User:</b> {user_id}\n"
            f"📊 <b>Confidence:</b> {confidence}\n"
            f"⚖ <b>Regulation:</b> {', '.join(regulations)}\n\n"
            f"❓ <b>Question:</b>\n{question}\n\n"
            f"📌 <b>Summary:</b>\n{summary}\n\n"
            f"🤖 <b>AI Draft:</b>\n{answer}\n\n"
            f"📋 <b>Citations:</b>\n{cite_text}\n\n"
            f"<i>Nurse waiting — please review.</i>"
        )
 
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data = f"approve:{ref_id}"
                ),
                InlineKeyboardButton(
                    "✏ Rewrite",
                    callback_data = f"rewrite:{ref_id}"
                )
            ]
        ])
 
        async def send():
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(
                chat_id      = TELEGRAM_OFFICER_CHAT_ID,
                text         = message,
                parse_mode   = "HTML",
                reply_markup = keyboard
            )
 
        asyncio.run(send())
        print(f"Officer alerted via Telegram — {ref_id}")
 
    except Exception as e:
        print(f"Telegram alert error: {e}")
 
 
def run_agent(question: str, user_id: str = "user") -> dict:
    """
    Main NormIQ Agent
    Orchestrates all 4 tools with guardrails and caching.
    """
 
    print("\n" + "=" * 60)
    print(f"NormIQ Agent — Processing question from {user_id}")
    print(f"Question: {question[:80]}")
    print("=" * 60)
 
    # ── STEP 1: Input guardrails ─────────────────────────────
    guard = check_input(question)
    if not guard["passed"]:
        print(f"Input guardrail failed: {guard['reason']}")
 
        chat_history_add(user_id, "nurse", question)
        chat_history_add(user_id, "bot", guard["message"])
 
        if guard["reason"] in ["too_short", "not_compliance"]:
            return {
                "status":           "clarification",
                "summary":          "",
                "answer":           "",
                "citations":        [],
                "confidence":       0.0,
                "regulation":       [],
                "ref_id":           None,
                "conflict":         False,
                "conflict_warning": "",
                "message":          guard["message"]
            }
 
        return {
            "status":           "error",
            "summary":          "",
            "answer":           "",
            "citations":        [],
            "confidence":       0.0,
            "regulation":       [],
            "ref_id":           None,
            "conflict":         False,
            "conflict_warning": "",
            "message":          guard["message"]
        }
 
    # Use cleaned question
    question = guard["cleaned"]
 
    # ── STEP 2: Cache check ──────────────────────────────────
    cached = cache_get(question)
    if cached:
        print("Cache HIT — returning cached answer")
 
        cached_regulation  = cached.get("regulation", "HIPAA")
        cached_regulations = [cached_regulation]
 
        q_lower = question.lower()
        if "gdpr" in q_lower or "eu" in q_lower or "european" in q_lower:
            if "GDPR" not in cached_regulations:
                cached_regulations.append("GDPR")
 
        conflict_check = check_regulation_conflict(cached_regulations)
 
        chat_history_add(user_id, "nurse", question)
        chat_history_add(user_id, "bot",
                        cached["answer"], status="answered")
 
        ref_id = audit_log_create(
            user_id    = user_id,
            question   = question,
            regulation = cached.get("regulation", ""),
            was_cached = True
        )
 
        audit_log_update_answer(
            ref_id     = ref_id,
            answer     = cached["answer"],
            citations  = cached.get("citations", []),
            confidence = cached.get("confidence", 1.0),
            summary    = cached.get("summary", "")
        )
 
        return {
            "status":           "answered",
            "summary":          cached.get("summary", ""),
            "answer":           cached["answer"],
            "citations":        cached.get("citations", []),
            "confidence":       cached.get("confidence", 1.0),
            "regulation":       cached_regulations,
            "ref_id":           ref_id,
            "conflict":         conflict_check["conflict"],
            "conflict_warning": conflict_check["warning"],
            "message":          cached["answer"],
            "was_cached":       True
        }
 
    # ── STEP 3: Query understanding ──────────────────────────
    query_info = understand_query(question)
 
    if not query_info["is_clear"]:
        print("Question not clear — asking clarification")
 
        chat_history_add(user_id, "nurse", question)
        chat_history_add(user_id, "bot",
                        query_info["clarification_needed"])
 
        return {
            "status":           "clarification",
            "summary":          "",
            "answer":           "",
            "citations":        [],
            "confidence":       0.0,
            "regulation":       [],
            "ref_id":           None,
            "conflict":         False,
            "conflict_warning": "",
            "message":          query_info["clarification_needed"]
        }
 
    regulations   = query_info["regulations"]
    intent        = query_info["intent"]
    use_crosswalk = query_info["use_crosswalk"]
 
    if not regulations:
        regulations = ["HIPAA"]
 
    # ── STEP 4: Hybrid search ────────────────────────────────
    search_result = hybrid_search(
        query         = question,
        regulations   = regulations,
        use_crosswalk = use_crosswalk
    )
 
    chunks      = search_result["chunks"]
    chunks_good = search_result["chunks_good"]
 
    # ── STEP 5: Multi-query if chunks weak ───────────────────
    if not chunks_good:
        print("Chunks weak — running multi-query search...")
        search_result = multi_query_search(
            question    = question,
            regulations = regulations
        )
        chunks = search_result["chunks"]
 
    # ── STEP 6: Generate answer ──────────────────────────────
    answer_result = generate_answer(
        question    = question,
        chunks      = chunks,
        regulations = regulations,
        intent      = intent
    )
 
    answer           = answer_result["answer"]
    summary          = answer_result.get("summary", "")
    citations        = answer_result["citations"]
    has_conflict     = answer_result.get("has_conflict", False)
    conflict_warning = answer_result.get("conflict_warning", "")
 
    # ── STEP 7: Output guardrails ────────────────────────────
    out_guard = check_output(answer, citations)
 
    # ── STEP 8: Conflict detection ───────────────────────────
    conflict_check = check_regulation_conflict(regulations)
    if conflict_check["conflict"] and not conflict_warning:
        conflict_warning = conflict_check["warning"]
        has_conflict     = True
 
    # ── STEP 9: Calculate final confidence ───────────────────
    confidence = search_result.get("confidence", 0.0)
 
    if intent == "comparison" and len(regulations) > 1:
        regs_found = set(c.get("regulation", "") for c in chunks)
        if all(r in regs_found for r in regulations):
            confidence = max(confidence, 0.82)
            print(f"Comparison intent — both regulations found "
                  f"→ confidence boosted to {confidence}")
 
    if out_guard.get("force_review"):
        confidence = min(confidence, 0.75)
        print(f"Output guardrail forcing review: {out_guard['reason']}")
 
    # ── STEP 10: Save to cache if high confidence ────────────
    if confidence >= CONFIDENCE_THRESHOLD:
        cache_set(
            question   = question,
            answer     = answer,
            citations  = citations,
            regulation = regulations[0] if regulations else "HIPAA",
            confidence = confidence,
            summary    = summary    # ← add this
        )
        # Also save summary to cache
        try:
            from database.db_manager import get_connection
            import json as _json
            from database.db_manager import generate_hash
            conn = get_connection()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE cache_store
                    SET summary = %s
                    WHERE question_hash = %s
                """, (summary, generate_hash(question)))
                conn.commit()
                cur.close()
                conn.close()
        except Exception:
            pass
 
    # ── STEP 11: Create audit log entry ─────────────────────
    ref_id = audit_log_create(
        user_id    = user_id,
        question   = question,
        regulation = ", ".join(regulations)
    )
 
    if confidence >= CONFIDENCE_THRESHOLD:
        audit_log_update_answer(
            ref_id     = ref_id,
            answer     = answer,
            citations  = citations,
            confidence = confidence,
            summary    = summary
        )
    else:
        from database.db_manager import get_connection
        import json as _json
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE audit_log
                SET answer     = %s,
                    citations  = %s,
                    confidence = %s,
                    summary    = %s
                WHERE ref_id = %s
            """, (answer, _json.dumps(citations),
                  confidence, summary, ref_id))
            conn.commit()
            cur.close()
            conn.close()
 
    # ── STEP 12: Save to chat history ────────────────────────
    chat_history_add(
        user_id = user_id,
        role    = "nurse",
        message = question,
        ref_id  = ref_id
    )
 
    display_message = format_answer_for_display(answer_result)
    if conflict_warning and conflict_warning not in display_message:
        display_message += f"\n\n{conflict_warning}"
 
    # ── STEP 13: Decide status ───────────────────────────────
    if confidence >= CONFIDENCE_THRESHOLD:
        status = "answered"
        chat_history_add(
            user_id = user_id,
            role    = "bot",
            message = display_message,
            ref_id  = ref_id,
            status  = "answered"
        )
    else:
        status = "pending_review"
 
        alert_officer_telegram(
            ref_id      = ref_id,
            question    = question,
            answer      = answer,
            citations   = citations,
            confidence  = confidence,
            regulations = regulations,
            user_id     = user_id,
            summary     = summary
        )
 
        pending_message = (
            f"🔍 Your question is under expert review.\n\n"
            f"Reference ID: {ref_id}\n\n"
            f"You will receive a notification "
            f"when your answer is ready."
        )
        chat_history_add(
            user_id = user_id,
            role    = "bot",
            message = pending_message,
            ref_id  = ref_id,
            status  = "pending"
        )
        display_message = pending_message
 
    print(f"\nAgent complete:")
    print(f"  Status:     {status}")
    print(f"  Confidence: {confidence}")
    print(f"  Ref ID:     {ref_id}")
 
    return {
        "status":           status,
        "summary":          summary,
        "answer":           answer,
        "citations":        citations,
        "confidence":       confidence,
        "regulation":       regulations,
        "ref_id":           ref_id,
        "conflict":         has_conflict,
        "conflict_warning": conflict_warning,
        "message":          display_message,
        "was_cached":       False
    }
 
 
# ════════════════════════════════════════════════════════════
# TEST
# ════════════════════════════════════════════════════════════
 
if __name__ == "__main__":
    print("Testing NormIQ Agent...\n")
 
    print("=" * 60)
    print("Test 1 — HIPAA breach notification")
    result = run_agent(
        question = "What is the HIPAA breach notification deadline?",
        user_id  = "nurse_test"
    )
    print(f"\nStatus:     {result['status']}")
    print(f"Summary:    {result['summary']}")
    print(f"Confidence: {result['confidence']}")
    print(f"Ref ID:     {result['ref_id']}")
 
    print("\n" + "=" * 60)
    print("Test 2 — HIPAA vs GDPR comparison")
    result = run_agent(
        question = "Compare HIPAA and GDPR breach notification deadlines",
        user_id  = "doctor_test"
    )
    print(f"\nStatus:   {result['status']}")
    print(f"Summary:  {result['summary']}")
    print(f"Conflict: {result['conflict']}")
 
    print("\n" + "=" * 60)
    print("Test 3 — Vague question")
    result = run_agent(
        question = "Can I share?",
        user_id  = "nurse_test"
    )
    print(f"\nStatus:  {result['status']}")
    print(f"Message: {result['message']}")
 
    print("\nAgent test complete!")