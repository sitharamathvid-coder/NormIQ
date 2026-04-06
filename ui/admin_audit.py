import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import pandas as pd
import requests
from datetime import datetime
from database.db_manager import (
    audit_log_get_all,
    audit_log_get_pending
)

# ── Config ───────────────────────────────────────────────────
API_URL = "http://localhost:8000"

st.set_page_config(
    page_title = "NormIQ — Audit Dashboard",
    page_icon  = "📋",
    layout     = "wide"
)

# ── Custom CSS ───────────────────────────────────────────────
st.markdown("""
<style>
    .metric-card {
        background: #1f2937;
        border: 1px solid #374151;
        border-radius: 8px;
        padding: 16px;
        text-align: center;
    }
    .metric-num {
        font-size: 32px;
        font-weight: 600;
        color: #f3f4f6;
    }
    .metric-label {
        font-size: 12px;
        color: #6b7280;
        margin-top: 4px;
    }
    .status-answered {
        background: #134e4a;
        color: #4ade80;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
    }
    .status-pending {
        background: #422006;
        color: #fbbf24;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
    }
    .status-reviewed {
        background: #1e3a5f;
        color: #60a5fa;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────
st.markdown("## 📋 NormIQ — Audit Dashboard")
st.markdown("*Admin view — all compliance queries and officer actions*")
st.divider()

# ── Load data ────────────────────────────────────────────────
@st.cache_data(ttl=30)  # refresh every 30 seconds
def load_audit_data():
    return audit_log_get_all(limit=500)

@st.cache_data(ttl=30)
def load_pending_data():
    return audit_log_get_pending()

# Refresh button
col_title, col_refresh = st.columns([5, 1])
with col_refresh:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# Load data
all_logs     = load_audit_data()
pending_logs = load_pending_data()

# ── Summary metrics ──────────────────────────────────────────
st.markdown("### Summary")

total     = len(all_logs)
answered  = len([l for l in all_logs if l.get("status") == "answered"])
pending   = len([l for l in all_logs if l.get("status") == "pending"])
reviewed  = len([l for l in all_logs if l.get("status") == "reviewed"])
cached    = len([l for l in all_logs if l.get("was_cached")])

avg_conf  = 0.0
if all_logs:
    confs    = [l.get("confidence", 0) or 0 for l in all_logs]
    avg_conf = round(sum(confs) / len(confs), 3)

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    st.metric("Total Queries",    total)
with col2:
    st.metric("Answered",         answered)
with col3:
    st.metric("Pending Review",   pending)
with col4:
    st.metric("Officer Reviewed", reviewed)
with col5:
    st.metric("From Cache",       cached)
with col6:
    st.metric("Avg Confidence",   avg_conf)

st.divider()

# ── Pending reviews section ──────────────────────────────────
if pending_logs:
    st.markdown(f"### ⚠ Pending Reviews ({len(pending_logs)})")

    for log in pending_logs:
        with st.expander(
            f"🔍 {log.get('ref_id')} — "
            f"{log.get('question', '')[:60]}... — "
            f"User: {log.get('user_id', '')}",
            expanded=True
        ):
            col_q, col_a = st.columns(2)

            with col_q:
                st.markdown("**Question:**")
                st.info(log.get("question", ""))
                st.markdown(f"**User:** `{log.get('user_id', '')}`")
                st.markdown(
                    f"**Regulation:** `{log.get('regulation', '')}`"
                )
                st.markdown(
                    f"**Confidence:** `{log.get('confidence', 0)}`"
                )
                st.markdown(
                    f"**Time:** "
                    f"`{log.get('timestamp', '')}`"
                )

            with col_a:
                st.markdown("**AI Draft Answer:**")
                st.warning(log.get("answer", "No answer generated"))

                if log.get("citations"):
                    import json
                    try:
                        cites = log["citations"]
                        if isinstance(cites, str):
                            cites = json.loads(cites)
                        for c in cites:
                            st.caption(
                                f"📋 {c.get('regulation')} — "
                                f"{c.get('citation')}"
                            )
                    except Exception:
                        pass

    st.divider()

# ── Full audit log ────────────────────────────────────────────
st.markdown("### All Queries")

# Filters
col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    filter_status = st.selectbox(
        "Filter by status",
        ["All", "answered", "pending", "reviewed"]
    )

with col_f2:
    filter_reg = st.selectbox(
        "Filter by regulation",
        ["All", "HIPAA", "GDPR", "NIST", "HIPAA, GDPR"]
    )

with col_f3:
    filter_conf = st.selectbox(
        "Filter by confidence",
        ["All", "High (≥0.80)", "Low (<0.80)"]
    )

# Apply filters
filtered = all_logs

if filter_status != "All":
    filtered = [
        l for l in filtered
        if l.get("status") == filter_status
    ]

if filter_reg != "All":
    filtered = [
        l for l in filtered
        if filter_reg.lower() in
        str(l.get("regulation", "")).lower()
    ]

if filter_conf == "High (≥0.80)":
    filtered = [
        l for l in filtered
        if (l.get("confidence") or 0) >= 0.80
    ]
elif filter_conf == "Low (<0.80)":
    filtered = [
        l for l in filtered
        if (l.get("confidence") or 0) < 0.80
    ]

st.caption(f"Showing {len(filtered)} of {total} records")

# Build table
if filtered:
    table_data = []
    for log in filtered:
        status = log.get("status", "")
        if status == "answered":
            status_display = "✅ Answered"
        elif status == "pending":
            status_display = "⏳ Pending"
        elif status == "reviewed":
            status_display = "👮 Reviewed"
        else:
            status_display = status

        table_data.append({
            "Ref ID":      log.get("ref_id", ""),
            "User":        log.get("user_id", ""),
            "Question":    log.get("question", "")[:80] + "...",
            "Regulation":  log.get("regulation", ""),
            "Confidence":  log.get("confidence", 0),
            "Status":      status_display,
            "Cached":      "⚡" if log.get("was_cached") else "",
            "Officer":     log.get("officer_id", ""),
            "Time":        str(log.get("timestamp", ""))[:16]
        })

    df = pd.DataFrame(table_data)
    st.dataframe(
        df,
        use_container_width = True,
        hide_index          = True
    )

    # Download button
    csv = df.to_csv(index=False)
    st.download_button(
        label     = "📥 Download CSV",
        data      = csv,
        file_name = f"normiq_audit_{datetime.now().strftime('%Y%m%d')}.csv",
        mime      = "text/csv"
    )

else:
    st.info("No records found for selected filters.")

# ── Regulation breakdown ──────────────────────────────────────
if all_logs:
    st.divider()
    st.markdown("### Regulation Breakdown")

    reg_counts = {}
    for log in all_logs:
        reg = log.get("regulation", "Unknown")
        reg_counts[reg] = reg_counts.get(reg, 0) + 1

    col_r1, col_r2 = st.columns(2)

    with col_r1:
        st.markdown("**Queries by regulation:**")
        for reg, count in sorted(
            reg_counts.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            pct = round(count / total * 100)
            st.markdown(f"`{reg}` — {count} queries ({pct}%)")

    with col_r2:
        st.markdown("**Confidence distribution:**")
        high = len([l for l in all_logs
                   if (l.get("confidence") or 0) >= 0.80])
        low  = len([l for l in all_logs
                   if (l.get("confidence") or 0) < 0.80])
        st.markdown(f"✅ High confidence (≥0.80): **{high}**")
        st.markdown(f"⚠ Low confidence (<0.80): **{low}**")
        if total > 0:
            rate = round(high / total * 100)
            st.markdown(f"📊 Direct answer rate: **{rate}%**")