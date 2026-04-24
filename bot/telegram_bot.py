import sys
import os
import re
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_OFFICER_CHAT_ID
)

logging.basicConfig(
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level  = logging.INFO
)
logger = logging.getLogger(__name__)

API_URL = "http://localhost:8000"

pending_reviews = {}


# ════════════════════════════════════════════════════════════
# SECURITY LAYER 1 — OFFICER AUTHORIZATION
# ════════════════════════════════════════════════════════════

def is_authorized(update: Update) -> bool:
    """
    Check if the sender is the authorized compliance officer.

    Every Telegram user has a unique numeric chat_id.
    We compare the sender's chat_id to TELEGRAM_OFFICER_CHAT_ID
    stored in .env. If they don't match -> silently ignore.

    WHY SILENT? If we reply "not authorized", we tell the
    attacker the bot is active and they can keep trying.
    Silence gives them nothing to work with.

    BLOCKS:
      - Strangers who find the bot username
      - Stolen phone used with a different Telegram account
      - Anyone who is not the exact authorized officer
    """
    sender_id  = str(update.effective_chat.id)
    officer_id = str(TELEGRAM_OFFICER_CHAT_ID)
    allowed    = (sender_id == officer_id)

    if not allowed:
        logger.warning(
            f"BLOCKED unauthorized sender: {sender_id} "
            f"(expected: {officer_id})"
        )
    return allowed


# ════════════════════════════════════════════════════════════
# SECURITY LAYER 2 — INPUT SANITIZATION
# ════════════════════════════════════════════════════════════

def sanitize_ref_id(raw: str) -> str:
    """
    Clean ref_id input before sending to the API.

    ALLOWED:  letters, digits, hyphens, underscores
    BLOCKED:  spaces, semicolons, quotes, slashes, dots,
              SQL keywords, shell commands, long strings

    EXAMPLES:
      "REF-abc123"          -> "REF-abc123"   OK
      "REF-123; DROP TABLE" -> ""             BLOCKED
      "../../../etc/passwd" -> ""             BLOCKED
      "' OR 1=1 --"         -> ""             BLOCKED
      200 chars long         -> ""             BLOCKED

    NOTE: SQL injection is already blocked in app.py
    by psycopg2 parameterized queries. This is a second
    layer of defence - belt AND braces.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9\-_]", "", raw)

    if len(cleaned) > 60:
        logger.warning(f"Ref ID too long, rejected: {raw[:30]}")
        return ""

    if not cleaned:
        logger.warning(f"Ref ID empty after sanitize: {raw[:30]}")
        return ""

    return cleaned


# ════════════════════════════════════════════════════════════
# START COMMAND
# ════════════════════════════════════════════════════════════

async def start(update: Update,
                context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return  # Silent — do not reply to strangers

    await update.message.reply_text(
        "👮 NormIQ — Compliance Officer Bot\n\n"
        "You will receive alerts here when\n"
        "nurse answers need your review.\n\n"
        "Tap Approve or Rewrite on each alert.\n\n"
        "📋 <b>Commands:</b>\n"
        "/status REF-abc123 — check status of any question\n"
        "/pending — see all questions waiting for review",
        parse_mode = "HTML"
    )


# ════════════════════════════════════════════════════════════
# STATUS COMMAND — /status REF-abc123
# ════════════════════════════════════════════════════════════

async def status_check(update: Update,
                       context: ContextTypes.DEFAULT_TYPE):

    # SECURITY CHECK 1 — authorized officer only
    if not is_authorized(update):
        return

    text  = update.message.text.strip()
    parts = text.split()

    if len(parts) < 2:
        await update.message.reply_text(
            "⚠ Please include the Ref ID.\n\n"
            "Example: <code>/status REF-abc123</code>",
            parse_mode = "HTML"
        )
        return

    # SECURITY CHECK 2 — sanitize the ref_id
    ref_id = sanitize_ref_id(parts[1].strip())

    if not ref_id:
        await update.message.reply_text(
            "⚠ Invalid Ref ID format.\n\n"
            "Ref IDs only contain letters, numbers and hyphens.\n"
            "Example: <code>/status REF-abc123</code>",
            parse_mode = "HTML"
        )
        return

    await update.message.chat.send_action("typing")

    try:
        response = requests.get(
            f"{API_URL}/audit/ref/{ref_id}",
            timeout = 10
        )
    except requests.exceptions.ConnectionError:
        await update.message.reply_text(
            "❌ Cannot reach the NormIQ API server.\n"
            "Make sure the server is running."
        )
        return
    except Exception as e:
        logger.error(f"Status check error: {e}")
        await update.message.reply_text("❌ Something went wrong.")
        return

    if response.status_code == 404:
        await update.message.reply_text(
            f"❌ Ref ID <code>{ref_id}</code> not found.\n\n"
            f"Please check the ID and try again.",
            parse_mode = "HTML"
        )
        return

    if response.status_code != 200:
        await update.message.reply_text(
            f"❌ Server error ({response.status_code})."
        )
        return

    data = response.json()

    raw_status = (
        data.get("approval_status") or
        data.get("status")          or
        "unknown"
    )

    status_display = {
        "answered":       ("✅", "ANSWERED — Sent directly to nurse"),
        "pending_review": ("⏳", "PENDING — Waiting for your review"),
        "pending":        ("⏳", "PENDING — Waiting for your review"),
        "approved":       ("✅", "APPROVED — You approved this answer"),
        "rewritten":      ("✏",  "REWRITTEN — You rewrote this answer"),
        "rejected":       ("❌", "REJECTED"),
        "unknown":        ("❓", "UNKNOWN STATUS"),
    }
    icon, status_label = status_display.get(
        raw_status, ("❓", raw_status.upper())
    )

    question    = data.get("question", "N/A")
    confidence  = data.get("confidence")
    regulation  = data.get("regulation", "N/A")
    timestamp   = data.get("created_at") or data.get("timestamp", "N/A")
    approved_by = data.get("approved_by") or data.get("officer_id") or "—"
    summary     = data.get("summary", "")
    answer      = data.get("answer", "")
    was_cached  = data.get("was_cached", False)

    if confidence is not None:
        try:
            conf_display = f"{float(confidence) * 100:.0f}%"
        except (ValueError, TypeError):
            conf_display = str(confidence)
    else:
        conf_display = "N/A"

    if timestamp and "T" in str(timestamp):
        timestamp = str(timestamp).split(".")[0].replace("T", " ")

    cache_note = " (cached)" if was_cached else ""

    if len(question) > 200:
        question = question[:200] + "..."

    reply = (
        f"{icon} <b>Status Report</b>\n\n"
        f"📋 <b>Ref ID:</b> <code>{ref_id}</code>\n"
        f"📊 <b>Status:</b> {status_label}\n"
        f"🎯 <b>Confidence:</b> {conf_display}{cache_note}\n"
        f"⚖ <b>Regulation:</b> {regulation}\n"
        f"🕐 <b>Submitted:</b> {timestamp}\n"
        f"👤 <b>Reviewed by:</b> {approved_by}\n"
    )

    if summary:
        reply += f"\n📌 <b>Summary:</b>\n{summary}\n"
    
    if answer:
        # Trim if very long — Telegram has a 4096 char limit
        display_answer = answer if len(answer) <= 800 else answer[:800] + "...\n<i>(truncated — full answer in Streamlit)</i>"
        reply += f"\n🤖 <b>AI Draft Answer:</b>\n{display_answer}\n"

    reply += f"\n❓ <b>Question:</b>\n{question}"

    if raw_status in ("pending_review", "pending"):
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
        await update.message.reply_text(
            reply, parse_mode="HTML", reply_markup=keyboard
        )
    else:
        await update.message.reply_text(reply, parse_mode="HTML")

    logger.info(f"Status check: {ref_id} -> {raw_status}")


# ════════════════════════════════════════════════════════════
# PENDING COMMAND — /pending
# ════════════════════════════════════════════════════════════

async def pending_list(update: Update,
                       context: ContextTypes.DEFAULT_TYPE):

    if not is_authorized(update):
        return

    await update.message.chat.send_action("typing")

    try:
        response = requests.get(f"{API_URL}/audit/pending", timeout=10)
    except requests.exceptions.ConnectionError:
        await update.message.reply_text("❌ Cannot reach the API server.")
        return
    except Exception as e:
        logger.error(f"Pending list error: {e}")
        await update.message.reply_text("❌ Something went wrong.")
        return

    if response.status_code != 200:
        await update.message.reply_text(f"❌ Server error ({response.status_code}).")
        return

    data    = response.json()
    pending = data.get("pending", [])
    count   = data.get("count", 0)

    if count == 0:
        await update.message.reply_text(
            "✅ No questions pending review right now.\n\nAll caught up! 🎉"
        )
        return

    reply = f"⏳ <b>{count} Question(s) Pending Review</b>\n\n"

    for i, item in enumerate(pending[:10], 1):
        ref  = item.get("ref_id", "?")
        q    = item.get("question", "N/A")
        conf = item.get("confidence")
        ts   = item.get("created_at") or item.get("timestamp", "")

        if len(q) > 80:
            q = q[:80] + "..."

        if conf is not None:
            try:
                conf_str = f"{float(conf) * 100:.0f}%"
            except (ValueError, TypeError):
                conf_str = str(conf)
        else:
            conf_str = "N/A"

        if ts and "T" in str(ts):
            ts = str(ts).split(".")[0].replace("T", " ")

        reply += (
            f"<b>{i}.</b> <code>{ref}</code>\n"
            f"   🎯 {conf_str} | 🕐 {ts}\n"
            f"   ❓ {q}\n\n"
        )

    if count > 10:
        reply += f"<i>...and {count - 10} more. Check the dashboard.</i>\n"

    reply += "\nUse <code>/status REF-xxx</code> to act on any one."

    await update.message.reply_text(reply, parse_mode="HTML")
    logger.info(f"Pending list: {count} items")


# ════════════════════════════════════════════════════════════
# SEND ALERT TO OFFICER — called from agent.py
# ════════════════════════════════════════════════════════════

async def send_officer_alert(bot, ref_id: str,
                              question: str, answer: str,
                              citations: list, confidence: float,
                              regulation: list, user_id: str):

    if not TELEGRAM_OFFICER_CHAT_ID:
        logger.warning("No officer chat ID set!")
        return

    pending_reviews[ref_id] = {
        "question": question, "answer": answer,
        "citations": citations, "user_id": user_id
    }

    cite_text = "\n".join([
        f"  • {c.get('regulation')} — {c.get('citation')}"
        for c in citations
    ]) if citations else "None found"

    message = (
        f"⚠ <b>Review Required</b>\n\n"
        f"📋 <b>Ref:</b> <code>{ref_id}</code>\n"
        f"👤 <b>User:</b> {user_id}\n"
        f"📊 <b>Confidence:</b> {confidence}\n"
        f"⚖ <b>Regulation:</b> {', '.join(regulation)}\n\n"
        f"❓ <b>Question:</b>\n{question}\n\n"
        f"🤖 <b>AI Draft:</b>\n{answer}\n\n"
        f"📋 <b>Citations:</b>\n{cite_text}\n\n"
        f"<i>Nurse is waiting. Please review.</i>\n\n"
        f"💡 Use <code>/status {ref_id}</code> to check later."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{ref_id}"),
            InlineKeyboardButton("✏ Rewrite", callback_data=f"rewrite:{ref_id}")
        ]
    ])

    await bot.send_message(
        chat_id=TELEGRAM_OFFICER_CHAT_ID,
        text=message, parse_mode="HTML", reply_markup=keyboard
    )
    logger.info(f"Officer alerted for {ref_id}")


# ════════════════════════════════════════════════════════════
# OFFICER BUTTON CALLBACKS
# ════════════════════════════════════════════════════════════

async def handle_callback(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):

    # SECURITY CHECK — authorized officer only
    if not is_authorized(update):
        await update.callback_query.answer(
            "Not authorized.", show_alert=True
        )
        return

    query = update.callback_query
    await query.answer()

    # SECURITY: sanitize ref_id from callback_data
    parts  = query.data.split(":")
    action = parts[0]
    ref_id = sanitize_ref_id(parts[1]) if len(parts) > 1 else ""

    if not ref_id:
        await query.edit_message_text("❌ Invalid Ref ID in button.")
        return

    officer_id   = str(update.effective_user.id)
    officer_name = update.effective_user.first_name or "Officer"

    if action == "approve":
        try:
            requests.post(
                f"{API_URL}/officer/action",
                json={"ref_id": ref_id, "officer_id": officer_id, "action": "approved"}
            )
        except Exception as e:
            logger.error(f"Approve API error: {e}")

        await query.edit_message_text(
            f"✅ <b>Approved</b> — <code>{ref_id}</code>\n\n"
            f"Confirmed by {officer_name}. Nurse will see the answer.",
            parse_mode="HTML"
        )
        pending_reviews.pop(ref_id, None)
        logger.info(f"Officer approved {ref_id}")

    elif action == "rewrite":
        context.user_data["rewriting"] = ref_id
        await query.edit_message_text(
            f"✏ <b>Rewrite</b> — <code>{ref_id}</code>\n\n"
            f"Type your corrected answer now.\n"
            f"Your next message will be sent to the nurse.",
            parse_mode="HTML"
        )


# ════════════════════════════════════════════════════════════
# OFFICER TYPES REWRITTEN ANSWER
# ════════════════════════════════════════════════════════════

async def handle_message(update: Update,
                         context: ContextTypes.DEFAULT_TYPE):

    # SECURITY CHECK — authorized officer only
    if not is_authorized(update):
        return  # Silent rejection

    rewriting = context.user_data.get("rewriting")

    if not rewriting:
        await update.message.reply_text(
            "👮 You will receive alerts here when\n"
            "nurse answers need your review.\n\n"
            "📋 <b>Commands:</b>\n"
            "/status REF-abc123 — check question status\n"
            "/pending — see all pending reviews",
            parse_mode="HTML"
        )
        return

    ref_id         = rewriting
    officer_answer = update.message.text
    officer_id     = str(update.effective_user.id)

    # SECURITY: limit answer length — blocks huge payloads
    if len(officer_answer) > 5000:
        await update.message.reply_text(
            "⚠ Answer too long (max 5000 characters).\n"
            "Please shorten it and try again."
        )
        return

    try:
        requests.post(
            f"{API_URL}/officer/action",
            json={
                "ref_id":         ref_id,
                "officer_id":     officer_id,
                "action":         "rewritten",
                "officer_answer": officer_answer
            }
        )
    except Exception as e:
        logger.error(f"Rewrite API error: {e}")

    await update.message.reply_text(
        f"✅ Submitted for <code>{ref_id}</code>\n\n"
        f"Nurse will see your answer in Streamlit.\n"
        f"Use <code>/status {ref_id}</code> to verify.",
        parse_mode="HTML"
    )

    context.user_data.pop("rewriting", None)
    pending_reviews.pop(ref_id, None)
    logger.info(f"Officer rewrote {ref_id}")


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR — TELEGRAM_BOT_TOKEN not set in .env!")
        return

    print("Starting NormIQ Officer Bot...")
    print(f"Officer Chat ID: {TELEGRAM_OFFICER_CHAT_ID}")
    print("Security: Only officer chat ID is authorized")
    print("Commands: /start  /status  /pending")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("status",  status_check))
    app.add_handler(CommandHandler("pending", pending_list))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    print("Officer bot running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
