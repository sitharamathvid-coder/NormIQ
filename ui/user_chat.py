import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
 
import streamlit as st
import requests
from database.db_manager import chat_history_get
from config.settings import CONFIDENCE_THRESHOLD
 
# ── Config ───────────────────────────────────────────────────
API_URL = "http://localhost:8000"
 
st.set_page_config(
    page_title = "NormIQ — Compliance Assistant",
    page_icon  = "⚕",
    layout     = "centered"
)
 
# ── Custom CSS ───────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0f1117; }
    .stTextInput input {
        background-color: #1e1e2e !important;
        color: #ffffff !important;
        border: 1px solid #374151 !important;
        border-radius: 8px !important;
        caret-color: #ffffff !important;
    }
    .stTextInput input::placeholder {
        color: #6b7280 !important;
    }
    .stTextInput input:focus {
        color: #ffffff !important;
        background-color: #1e1e2e !important;
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 1px #3b82f6 !important;
    }
    .chat-message-user {
        background: #1e3a5f;
        color: #bfdbfe;
        padding: 12px 16px;
        border-radius: 12px 12px 2px 12px;
        margin: 8px 0;
        margin-left: 20%;
        font-size: 14px;
    }
    .chat-message-bot {
        background: #1f2937;
        color: #f3f4f6;
        padding: 12px 16px;
        border-radius: 2px 12px 12px 12px;
        margin: 8px 0;
        margin-right: 20%;
        font-size: 14px;
        line-height: 1.6;
    }
    .chat-message-pending {
        background: #422006;
        color: #fde68a;
        padding: 12px 16px;
        border-radius: 2px 12px 12px 12px;
        margin: 8px 0;
        margin-right: 20%;
        font-size: 14px;
    }
    .citation-box {
        background: #1e3a5f;
        border: 1px solid #3b82f6;
        border-radius: 6px;
        padding: 8px 12px;
        margin-top: 8px;
        font-size: 12px;
        color: #93c5fd;
    }
    .conflict-warning {
        background: #7f1d1d;
        border: 1px solid #f87171;
        border-radius: 6px;
        padding: 8px 12px;
        margin-top: 8px;
        font-size: 13px;
        color: #fee2e2;
    }
    .confidence-high { color: #4ade80; font-size: 12px; }
    .confidence-low  { color: #f87171; font-size: 12px; }
    .cached-badge {
        background: #134e4a;
        color: #2dd4bf;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 11px;
    }
</style>
""", unsafe_allow_html=True)
 
 
# ── Header ───────────────────────────────────────────────────
st.markdown("""
<style>
    .normiq-header {
        background: linear-gradient(135deg, #0f1117 0%, #1a1f2e 100%);
        border: 1px solid #0d9488;
        border-radius: 16px;
        padding: 24px;
        text-align: center;
        margin-bottom: 20px;
    }
    .normiq-logo {
        font-family: Georgia, serif;
        font-size: 36px;
        font-weight: 700;
        color: #2dd4bf;
        letter-spacing: 4px;
        margin-bottom: 4px;
    }
    .normiq-tagline {
        font-size: 11px;
        color: #9ca3af;
        letter-spacing: 3px;
        text-transform: uppercase;
        margin-bottom: 12px;
    }
    .normiq-pills {
        display: flex;
        justify-content: center;
        gap: 8px;
    }
    .pill-hipaa {
        background: #1e3a5f;
        border: 1px solid #3b82f6;
        color: #60a5fa;
        padding: 2px 12px;
        border-radius: 20px;
        font-size: 11px;
    }
    .pill-gdpr {
        background: #134e4a;
        border: 1px solid #0d9488;
        color: #2dd4bf;
        padding: 2px 12px;
        border-radius: 20px;
        font-size: 11px;
    }
    .pill-nist {
        background: #1e1b4b;
        border: 1px solid #6d28d9;
        color: #a78bfa;
        padding: 2px 12px;
        border-radius: 20px;
        font-size: 11px;
    }
</style>

<div class="normiq-header">
    <div class="normiq-logo">⚖ NormIQ</div>
    <div class="normiq-tagline">Compliance · Clarity · Confidence</div>
    <div class="normiq-pills">
        <span class="pill-hipaa">HIPAA</span>
        <span class="pill-gdpr">GDPR</span>
        <span class="pill-nist">NIST</span>
    </div>
</div>
""", unsafe_allow_html=True)
 
 
# ── Session state ────────────────────────────────────────────
if "user_id" not in st.session_state:
    st.session_state.user_id = "nurse_test_001"
 
if "messages" not in st.session_state:
    st.session_state.messages = []
 
if "loaded_history" not in st.session_state:
    st.session_state.loaded_history = False
 
 
# ── Load chat history on first load ─────────────────────────
if not st.session_state.loaded_history:
    try:
        history = chat_history_get(
            user_id = st.session_state.user_id,
            limit   = 20
        )
        if history:
            st.session_state.messages = [
                {
                    "role":    h["role"],
                    "content": h["message"],
                    "status":  h.get("status", "answered"),
                    "ref_id":  h.get("ref_id")
                }
                for h in history
            ]
        st.session_state.loaded_history = True
    except Exception:
        st.session_state.loaded_history = True
 
 
# ════════════════════════════════════════════════════════════
# POLL FOR OFFICER UPDATES
# ════════════════════════════════════════════════════════════
 
def check_pending_updates():
    """Check if any pending messages have been reviewed by officer."""
    updated = False
    for i, msg in enumerate(st.session_state.messages):
        if msg.get("status") == "pending":
            ref_id = msg.get("ref_id")
            if not ref_id:
                continue
            try:
                response = requests.get(
                    f"{API_URL}/audit/ref/{ref_id}",
                    timeout = 5
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "reviewed":
                        officer_answer  = data.get("officer_answer")
                        original_answer = data.get("answer", "")
                        final_answer    = officer_answer or original_answer
 
                        st.session_state.messages[i] = {
                            "role":    "bot",
                            "content": (
                                f"✅ Answer Ready — "
                                f"Ref {ref_id}\n\n"
                                f"{final_answer}\n\n"
                                f"✔ Reviewed by compliance officer."
                            ),
                            "status":  "answered",
                            "ref_id":  ref_id,
                            "result":  None    
                        }
                        updated = True
            except Exception:
                continue
    return updated
 
 
# ── Check for officer updates ────────────────────────────────
has_pending = any(
    m.get("status") == "pending"
    for m in st.session_state.messages
)
if has_pending:
    updated = check_pending_updates()
    if updated:
        st.rerun()
 
 
# ════════════════════════════════════════════════════════════
# DISPLAY MESSAGES
# ════════════════════════════════════════════════════════════
 
def display_message(msg: dict, result: dict = None):
    role    = msg["role"]
    content = msg["content"]
    status  = msg.get("status", "answered")
 
    if role == "nurse":
        st.markdown(
            f'<div class="chat-message-user">{content}</div>',
            unsafe_allow_html=True
        )
 
    elif role == "bot":
        if status == "pending":
            st.markdown(
                f'<div class="chat-message-pending">{content}</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="chat-message-bot">{content}</div>',
                unsafe_allow_html=True
            )
 
            # Show citations
            if result and result.get("citations"):
                citation_text = " · ".join([
                    f"{c['regulation']} — {c['citation']}"
                    for c in result["citations"]
                ])
                st.markdown(
                    f'<div class="citation-box">📋 {citation_text}</div>',
                    unsafe_allow_html=True
                )
 
            # Show conflict warning
            if result and result.get("conflict_warning"):
                st.markdown(
                    f'<div class="conflict-warning">'
                    f'{result["conflict_warning"]}</div>',
                    unsafe_allow_html=True
                )
 
            # Show confidence
            if result:
                conf       = result.get("confidence", 0)
                conf_class = "confidence-high" if conf >= 0.80 \
                             else "confidence-low"
                cached     = "⚡ Cached" if result.get("was_cached") \
                             else ""
                st.markdown(
                    f'<span class="{conf_class}">'
                    f'Confidence: {conf}</span>'
                    f'&nbsp;&nbsp;'
                    f'<span class="cached-badge">{cached}</span>',
                    unsafe_allow_html=True
                )
 
 
# ── Display all messages ─────────────────────────────────────
for i, msg in enumerate(st.session_state.messages):
    result = msg.get("result")
    display_message(msg, result)
 
 
# ════════════════════════════════════════════════════════════
# INPUT BOX
# ════════════════════════════════════════════════════════════
 
st.divider()
 
with st.form("chat_form", clear_on_submit=True):
    col1, col2 = st.columns([5, 1])
    with col1:
        question = st.text_input(
            label            = "Ask a compliance question",
            placeholder      = "e.g. What is the HIPAA breach notification deadline?",
            label_visibility = "collapsed"
        )
    with col2:
        submitted = st.form_submit_button("Send")
 
 
# ── Handle submission ────────────────────────────────────────
if submitted and question.strip():
 
    # Add nurse message
    st.session_state.messages.append({
        "role":    "nurse",
        "content": question,
        "status":  "answered"
    })
 
    # Call API
    with st.spinner("Searching regulations..."):
        try:
            response = requests.post(
                f"{API_URL}/query",
                json = {
                    "question": question,
                    "user_id":  st.session_state.user_id,
                    "role":     "nurse",
                    "location": "US"
                },
                timeout = 60
            )
            result = response.json()
 
            status = result.get("status")
 
            if status == "answered":
                bot_message = result["message"]
                msg_status  = "answered"
 
            elif status == "clarification":
                bot_message = result["message"]
                msg_status  = "answered"
 
            else:
                # Pending review
                bot_message = result["message"]
                msg_status  = "pending"
 
            # Add bot message
            st.session_state.messages.append({
                "role":    "bot",
                "content": bot_message,
                "status":  msg_status,
                "ref_id":  result.get("ref_id"),
                "result":  result
            })
 
        except requests.exceptions.Timeout:
            st.session_state.messages.append({
                "role":    "bot",
                "content": "⏱ Request timed out. Please try again.",
                "status":  "answered"
            })
        except Exception as e:
            st.session_state.messages.append({
                "role":    "bot",
                "content": f"❌ Error: {str(e)}",
                "status":  "answered"
            })
 
    st.rerun()
 
 
# ════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════
 
with st.sidebar:
    # Logo
    st.markdown("""
    <div style="text-align:center;padding:16px 0 8px 0">
        <svg width="50" height="50" viewBox="0 0 40 40">
            <path d="M20 4 L34 9 L34 22 Q34 32 20 37 Q6 32 6 22 L6 9 Z"
                  fill="#0d9488" opacity="0.2"/>
            <path d="M20 4 L34 9 L34 22 Q34 32 20 37 Q6 32 6 22 L6 9 Z"
                  fill="none" stroke="#0d9488" stroke-width="1.5"/>
            <text x="20" y="26" text-anchor="middle"
                  font-family="Georgia,serif" font-size="16"
                  font-weight="700" fill="#2dd4bf">N</text>
        </svg>
        <div style="font-family:Georgia,serif;font-size:24px;font-weight:700;
                    color:#2dd4bf;letter-spacing:3px;margin-top:6px">NormIQ</div>
        <div style="font-size:10px;color:#6b7280;letter-spacing:2px;
                    text-transform:uppercase;margin-top:4px">
            Compliance · Clarity · Confidence
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Regulations
    st.markdown("""
    <div style="background:#1e3a5f;border-left:3px solid #3b82f6;
                border-radius:0 6px 6px 0;padding:8px 10px;margin-bottom:8px">
        <div style="font-size:12px;font-weight:600;color:#60a5fa">🇺🇸 HIPAA</div>
        <div style="font-size:11px;color:#d1d5db">US Healthcare Privacy</div>
    </div>
    <div style="background:#134e4a;border-left:3px solid #0d9488;
                border-radius:0 6px 6px 0;padding:8px 10px;margin-bottom:8px">
        <div style="font-size:12px;font-weight:600;color:#2dd4bf">🇪🇺 GDPR</div>
        <div style="font-size:11px;color:#d1d5db">EU Data Protection</div>
    </div>
    <div style="background:#1e1b4b;border-left:3px solid #7c3aed;
                border-radius:0 6px 6px 0;padding:8px 10px;margin-bottom:8px">
        <div style="font-size:12px;font-weight:600;color:#a78bfa">🌐 NIST</div>
        <div style="font-size:11px;color:#d1d5db">Security Controls</div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # User ID
    st.markdown(f"""
    <div style="background:#1f2937;border-radius:6px;padding:8px 10px;
                border:1px solid #374151">
        <div style="font-size:10px;color:#d1d5db;
                    text-transform:uppercase;letter-spacing:1px">Active User</div>
        <div style="font-size:12px;color:#2dd4bf;
                    font-family:monospace;margin-top:2px">
            {st.session_state.user_id}
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Pending messages
    pending = [
        m for m in st.session_state.messages
        if m.get("status") == "pending"
    ]

    if pending:
        for p in pending:
            st.markdown(f"""
            <div style="background:#422006;border:1px solid #d97706;
                        border-radius:6px;padding:8px 10px;margin-bottom:6px">
                <div style="font-size:11px;font-weight:600;color:#fbbf24">
                    ⏳ Under Review
                </div>
                <div style="font-size:11px;color:#fde68a;font-family:monospace">
                    {p.get('ref_id', 'N/A')}
                </div>
            </div>
            """, unsafe_allow_html=True)
        st.caption("You will be notified when answered.")
        st.divider()

    # Clear chat button
    if st.button("🗑 Clear Chat", use_container_width=True):
        try:
            from database.db_manager import get_connection
            conn = get_connection()
            if conn:
                cur = conn.cursor()
                cur.execute("""
                    DELETE FROM chat_history
                    WHERE user_id = %s
                    AND status != 'pending'
                """, (st.session_state.user_id,))
                conn.commit()
                cur.close()
                conn.close()
        except Exception as e:
            print(f"Clear chat error: {e}")

        st.session_state.messages = [
            msg for msg in st.session_state.messages
            if msg.get("status") == "pending"
        ]
        st.session_state.loaded_history = False
        st.rerun()
 
# ════════════════════════════════════════════════════════════
# AUTO REFRESH IF PENDING
# ════════════════════════════════════════════════════════════
 
if any(m.get("status") == "pending"
       for m in st.session_state.messages):
    import time
    time.sleep(10)
    st.rerun()
 