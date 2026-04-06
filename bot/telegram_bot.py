import sys
import os
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

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level  = logging.INFO
)
logger = logging.getLogger(__name__)

API_URL = "http://localhost:8000"

# Store pending reviews
# ref_id → question, answer, citations
pending_reviews = {}


# ── Start command ────────────────────────────────────────────
async def start(update: Update,
                context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👮 NormIQ — Compliance Officer Bot\n\n"
        "You will receive alerts here when\n"
        "nurse answers need your review.\n\n"
        "Tap Approve or Rewrite on each alert."
    )


# ════════════════════════════════════════════════════════════
# SEND ALERT TO OFFICER — called from agent.py
# ════════════════════════════════════════════════════════════

async def send_officer_alert(bot, ref_id: str,
                              question: str,
                              answer: str,
                              citations: list,
                              confidence: float,
                              regulation: list,
                              user_id: str):
    """Send low confidence alert to officer."""

    if not TELEGRAM_OFFICER_CHAT_ID:
        logger.warning("No officer chat ID set!")
        return

    # Store pending
    pending_reviews[ref_id] = {
        "question":   question,
        "answer":     answer,
        "citations":  citations,
        "user_id":    user_id
    }

    # Format citations
    cite_text = "\n".join([
        f"  • {c.get('regulation')} — {c.get('citation')}"
        for c in citations
    ]) if citations else "None found"

    # Alert message
    message = (
        f"⚠ <b>Review Required</b>\n\n"
        f"📋 <b>Ref:</b> <code>{ref_id}</code>\n"
        f"👤 <b>User:</b> {user_id}\n"
        f"📊 <b>Confidence:</b> {confidence}\n"
        f"⚖ <b>Regulation:</b> {', '.join(regulation)}\n\n"
        f"❓ <b>Question:</b>\n{question}\n\n"
        f"🤖 <b>AI Draft:</b>\n{answer}\n\n"
        f"📋 <b>Citations:</b>\n{cite_text}\n\n"
        f"<i>Nurse is waiting. Please review.</i>"
    )

    # Approve / Rewrite buttons
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

    await bot.send_message(
        chat_id      = TELEGRAM_OFFICER_CHAT_ID,
        text         = message,
        parse_mode   = "HTML",
        reply_markup = keyboard
    )

    logger.info(f"Officer alerted for {ref_id}")


# ════════════════════════════════════════════════════════════
# OFFICER BUTTON CALLBACKS
# ════════════════════════════════════════════════════════════

async def handle_callback(update: Update,
                          context: ContextTypes.DEFAULT_TYPE):
    """Handle officer approve/rewrite button taps."""

    query  = update.callback_query
    await query.answer()

    data   = query.data.split(":")
    action = data[0]
    ref_id = data[1]

    officer_id   = str(update.effective_user.id)
    officer_name = update.effective_user.first_name or "Officer"

    # ── Approve ──────────────────────────────────────────────
    if action == "approve":
        try:
            requests.post(
                f"{API_URL}/officer/action",
                json = {
                    "ref_id":     ref_id,
                    "officer_id": officer_id,
                    "action":     "approved"
                }
            )
        except Exception as e:
            logger.error(f"API error: {e}")

        await query.edit_message_text(
            f"✅ <b>Approved</b> — {ref_id}\n\n"
            f"Answer confirmed by {officer_name}.\n"
            f"Nurse will see the answer in Streamlit.",
            parse_mode = "HTML"
        )

        pending_reviews.pop(ref_id, None)
        logger.info(f"Officer approved {ref_id}")

    # ── Rewrite ──────────────────────────────────────────────
    elif action == "rewrite":
        context.user_data["rewriting"] = ref_id

        await query.edit_message_text(
            f"✏ <b>Rewrite</b> — {ref_id}\n\n"
            f"Please type your corrected answer now.\n"
            f"Your next message will be sent to the nurse.",
            parse_mode = "HTML"
        )


# ════════════════════════════════════════════════════════════
# OFFICER TYPES REWRITTEN ANSWER
# ════════════════════════════════════════════════════════════

async def handle_message(update: Update,
                         context: ContextTypes.DEFAULT_TYPE):
    """Handle officer typing rewritten answer."""

    rewriting = context.user_data.get("rewriting")

    if not rewriting:
        await update.message.reply_text(
            "👮 You will receive alerts here when\n"
            "nurse answers need your review."
        )
        return

    ref_id         = rewriting
    officer_answer = update.message.text
    officer_id     = str(update.effective_user.id)

    try:
        requests.post(
            f"{API_URL}/officer/action",
            json = {
                "ref_id":         ref_id,
                "officer_id":     officer_id,
                "action":         "rewritten",
                "officer_answer": officer_answer
            }
        )
    except Exception as e:
        logger.error(f"API error on rewrite: {e}")

    await update.message.reply_text(
        f"✅ Answer submitted for {ref_id}\n\n"
        f"Nurse will see your answer in Streamlit."
    )

    # Clear rewriting state
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

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    ))

    print("Officer bot running! Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()