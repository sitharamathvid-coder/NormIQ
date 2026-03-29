import streamlit as st
import requests
import json
import pandas as pd
import os
from io import StringIO

st.set_page_config(page_title="NormIQ | Legal AI", page_icon="⚖️", layout="wide", initial_sidebar_state="expanded")

# --- CSS AESTHETICS ---
def inject_custom_css():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif; background-color: #0b0f19; color: #E2E8F0; }
        .glass-container { background: rgba(30, 41, 59, 0.7); backdrop-filter: blur(12px); border-radius: 16px; border: 1px solid rgba(255, 255, 255, 0.1); padding: 24px; margin-bottom: 24px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3); }
        .gradient-text { background: linear-gradient(135deg, #60A5FA 0%, #A78BFA 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 700; }
        .badge-green { background-color: rgba(16, 185, 129, 0.2); color: #34D399; padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; border: 1px solid rgba(16, 185, 129, 0.3); margin-right: 8px;}
        .badge-yellow { background-color: rgba(245, 158, 11, 0.2); color: #FBBF24; padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; border: 1px solid rgba(245, 158, 11, 0.3); margin-right: 8px;}
        .stat-card { background: rgba(15, 23, 42, 0.6); padding: 15px; border-radius: 12px; text-align: center; border: 1px solid rgba(96, 165, 250, 0.2); margin-top: 10px;}
        .stat-value { font-size: 1.8rem; font-weight: bold; color: #60A5FA; }
        .stat-label { font-size: 0.8rem; color: #94A3B8; text-transform: uppercase; letter-spacing: 1px;}
        </style>
        """,
        unsafe_allow_html=True
    )
inject_custom_css()

# --- SIDEBAR GLOBALS ---
st.sidebar.markdown('<h1 class="gradient-text">⚖️ NormIQ</h1>', unsafe_allow_html=True)

API_URL = st.sidebar.text_input("API URL", value="http://localhost:8000")

@st.cache_data(ttl=5)
def fetch_system_stats(url):
    try:
        r = requests.get(f"{url}/stats", timeout=2)
        if r.status_code == 200:
            return r.json(), True
    except:
        pass
    return None, False

stats, is_connected = fetch_system_stats(API_URL)

if is_connected:
    st.sidebar.markdown("🟢 **Status:** Connected")
    st.sidebar.markdown("🧠 **Model:** `gpt-4o-mini`")
    st.sidebar.markdown("🗂️ **Pinecone:** `normiq`")
    if stats:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### Quick Stats")
        st.sidebar.metric("Total Queries", stats.get("total_queries", 0))
        st.sidebar.metric("Avg Confidence", f"{stats.get('avg_confidence', 0)*100:.1f}%")
else:
    st.sidebar.markdown("🔴 **Status:** Disconnected")
    st.sidebar.warning("API Server unreachable.")


st.markdown('<h1 class="gradient-text" style="text-align: center; margin-bottom: 20px;">Enterprise AI Compliance Officer</h1>', unsafe_allow_html=True)
tab1, tab2, tab3, tab4 = st.tabs(["💬 Chat", "📊 Evaluation", "📤 Upload", "📋 Audit Log"])


# --- TAB 1: Chat Assistant ---
with tab1:
    col_t1, col_t2 = st.columns([0.8, 0.2])
    with col_t1: st.subheader("Verify Regulatory Directives")
    with col_t2: 
        if st.button("🗑️ Clear Chat History"):
            st.session_state.messages = []
            st.rerun()

    st.markdown('<div class="glass-container">', unsafe_allow_html=True)
    
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and "confidence" in msg:
                # Meta badges
                conf = float(msg["confidence"])
                badge = "badge-green" if conf >= 0.8 else "badge-yellow"
                status = "AUTO-APPROVED" if conf >= 0.8 else "REQUIRES REVIEW"
                
                cache_str = '<span class="badge-green">⚡ Instant</span>' if msg.get("from_cache") else ''
                time_str = f'<span class="badge-yellow">⏱ {msg.get("process_time_sec", 0)}s</span>'
                
                html_str = f'{cache_str} {time_str} <span class="{badge}">Confidence: {conf*100:.1f}% ({status}) [Reg: {msg.get("regulation")}]</span>'
                st.markdown(html_str, unsafe_allow_html=True)
                
                with st.expander("View Legal Citations"):
                    for idx, cite in enumerate(msg["citations"]):
                        st.caption(f"**[{idx+1}] {cite}**")

    if prompt := st.chat_input("Ask a compliance question..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Scanning regulatory index..."):
                try:
                    res = requests.post(f"{API_URL}/query", json={"query": prompt})
                    if res.status_code == 200:
                        data = res.json()
                        st.markdown(data["answer"])
                        
                        conf = data.get("confidence", 0)
                        badge = "badge-green" if conf >= 0.8 else "badge-yellow"
                        status = data.get("threshold_status", "UNKNOWN")
                        cache_tag = data.get("from_cache", False)
                        pt = data.get("process_time_sec", 0)
                        
                        cache_str = '<span class="badge-green">⚡ Instant Cache</span>' if cache_tag else ''
                        html_str = f'{cache_str} <span class="badge-yellow">⏱ {pt}s</span> <span class="{badge}">Confidence: {conf*100:.1f}% ({status})</span>'
                        st.markdown(html_str, unsafe_allow_html=True)
                        
                        with st.expander("View Legal Citations"):
                            for idx, cite in enumerate(data.get("citations", [])):
                                st.caption(f"**[{idx+1}] {cite}**")
                        
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": data["answer"],
                            "citations": data.get("citations", []),
                            "confidence": conf,
                            "from_cache": cache_tag,
                            "process_time_sec": pt,
                            "regulation": data.get("regulation", "Unknown")
                        })
                    else:
                        st.error(f"Error: {res.text}")
                except Exception as e:
                    st.error(f"Failed to connect to backend: {e}")
    st.markdown('</div>', unsafe_allow_html=True)


# --- TAB 2: Evaluation ---
with tab2:
    st.markdown('<div class="glass-container">', unsafe_allow_html=True)
    st.subheader("RAGAS Evaluation Suite")
    st.write("Trigger automated end-to-end tests across the 30-question Compliance Set.")
    
    col_e1, col_e2 = st.columns([0.3, 0.7])
    with col_e1:
        num_q = st.number_input("Number of questions to test", min_value=1, max_value=30, value=30)
        eval_btn = st.button("🚀 Run Cloud Evaluation", use_container_width=True)
        
    if eval_btn:
        with st.spinner("Running deep RAGAS evaluation. This may take a few minutes..."):
            try:
                # Actually, our API takes no parameters for run_evaluation currently, but we can pass num_q in the future.
                res = requests.post(f"{API_URL}/evaluate")
                if res.status_code == 200:
                    eval_data = res.json()
                    st.success("Evaluation Completed Successfully!")
                    st.session_state.eval_data = eval_data
                else:
                    st.error(f"Eval Error: {res.text}")
            except Exception as e:
                st.error(f"Eval crashed: {e}")
                
    if "eval_data" in st.session_state:
        e_data = st.session_state.eval_data
        sums = e_data.get("summary_scores", {})
        
        # Colour coding function
        def get_color(val):
            if val >= 0.80: return "#34D399" # Green
            if val >= 0.60: return "#FBBF24" # Yellow
            return "#EF4444" # Red
            
        col1, col2, col3, col4, col5 = st.columns(5)
        
        f_val = sums.get("faithfulness", 0)
        with col1: st.markdown(f'<div class="stat-card"><div class="stat-label">Faithfulness</div><div class="stat-value" style="color: {get_color(f_val)}">{f_val:.3f}</div></div>', unsafe_allow_html=True)
        
        a_val = sums.get("answer_relevancy", 0)
        with col2: st.markdown(f'<div class="stat-card"><div class="stat-label">Relevancy</div><div class="stat-value" style="color: {get_color(a_val)}">{a_val:.3f}</div></div>', unsafe_allow_html=True)
        
        cp_val = sums.get("context_precision", 0)
        with col3: st.markdown(f'<div class="stat-card"><div class="stat-label">Precision</div><div class="stat-value" style="color: {get_color(cp_val)}">{cp_val:.3f}</div></div>', unsafe_allow_html=True)
        
        cr_val = sums.get("context_recall", 0)
        with col4: st.markdown(f'<div class="stat-card"><div class="stat-label">Recall</div><div class="stat-value" style="color: {get_color(cr_val)}">{cr_val:.3f}</div></div>', unsafe_allow_html=True)
        
        overall = (f_val + a_val + cp_val + cr_val) / 4 if (f_val and a_val and cp_val and cr_val) else 0.0
        with col5: st.markdown(f'<div class="stat-card" style="border-color: white;"><div class="stat-label">Overall</div><div class="stat-value" style="color: {get_color(overall)}">{overall:.3f}</div></div>', unsafe_allow_html=True)
        
        st.markdown("<br><h4>Ablation Study Matrix (Results)</h4>", unsafe_allow_html=True)
        if "results" in e_data:
            df_ab = pd.DataFrame(e_data["results"])
            st.dataframe(df_ab, use_container_width=True)
            
            json_str = json.dumps(e_data, indent=2)
            st.download_button(label="Download Evaluation JSON", data=json_str, file_name="ragas_eval.json", mime="application/json")
            
    st.markdown('</div>', unsafe_allow_html=True)


# --- TAB 3: Upload ---
with tab3:
    st.markdown('<div class="glass-container">', unsafe_allow_html=True)
    st.subheader("Knowledge Repository Status")
    
    col_k1, col_k2, col_k3 = st.columns(3)
    if stats:
        with col_k1: st.markdown(f'<div class="stat-card"><div class="stat-label">HIPAA Chunks</div><div class="stat-value">{stats.get("vectors_hipaa", 0)}</div></div>', unsafe_allow_html=True)
        with col_k2: st.markdown(f'<div class="stat-card"><div class="stat-label">GDPR Chunks</div><div class="stat-value">{stats.get("vectors_gdpr", 0)}</div></div>', unsafe_allow_html=True)
        with col_k3: st.markdown(f'<div class="stat-card"><div class="stat-label">NIST Chunks</div><div class="stat-value">{stats.get("vectors_nist", 0)}</div></div>', unsafe_allow_html=True)
    
    st.markdown("<hr>", unsafe_allow_html=True)
    st.subheader("Dynamic Bulk Ingestion")
    
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        reg_choice = st.selectbox("Target Regulation", ["HIPAA", "GDPR", "NIST"], index=0)
    with col_u2:
        file_ver = st.text_input("Ingestion Version Tag", value="2024-v1")
        
    uploaded_file = st.file_uploader("Select PDF documentation...", type=['pdf'])
    
    if st.button("🚀 Upload and Ingest", use_container_width=True):
        if not uploaded_file:
             st.warning("Please attach a PDF document.")
        elif reg_choice != "HIPAA":
             st.error("Only HIPAA ingestion logic is enabled for dynamic upload right now.")
        else:
            with st.spinner("Uploading and processing vectors on the Cloud..."):
                try:
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                    data = {"regulation": reg_choice}
                    res = requests.post(f"{API_URL}/ingest", files=files, data=data)
                    if res.status_code == 200:
                        st.success(f"✅ Ingestion successful! {res.json().get('chunks_upserted')} chunks added.")
                        st.cache_data.clear() # clear fetch cache to refresh vectors
                    else:
                        st.error(f"API Error: {res.json().get('detail')}")
                except Exception as e:
                    st.error(f"Upload failed: {e}")
                    
    st.markdown('</div>', unsafe_allow_html=True)


# --- TAB 4: Audit Log ---
with tab4:
    st.markdown('<div class="glass-container">', unsafe_allow_html=True)
    col_a1, col_a2 = st.columns([0.8, 0.2])
    with col_a1: st.subheader("Live System Audit Logs (SQLBacked)")
    with col_a2: 
        if st.button("🔄 Refresh Logs"): st.rerun()

    def load_audit_data():
        try:
            r = requests.get(f"{API_URL}/audit", timeout=5)
            if r.status_code == 200:
                logs = r.json().get("logs", [])
                if logs:
                    return pd.DataFrame(logs)
        except Exception as e:
            st.error(f"Failed to fetch DB logs: {e}")
        return pd.DataFrame()

    df_logs = load_audit_data()
    
    if not df_logs.empty:
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        
        # Compute Header Stats
        total_logs = len(df_logs)
        direct_rate = (df_logs["status"] == "AUTO_APPROVED").sum()
        human_rate = total_logs - direct_rate
        pct = (direct_rate / total_logs) * 100 if total_logs > 0 else 0.0
        
        with col_f1: st.metric("Database Entries", total_logs)
        with col_f2: st.metric("Direct (Green)", direct_rate)
        with col_f3: st.metric("Review (Amber)", human_rate)
        with col_f4: st.metric("Self-Service Rate", f"{pct:.1f}%")
        
        # Filters
        col_filt1, col_filt2 = st.columns(2)
        with col_filt1:
            reg_filter = st.selectbox("Regulation", ["All"] + list(df_logs["regulation"].dropna().unique()))
        with col_filt2:
            status_filter = st.selectbox("Routing Status", ["All", "AUTO_APPROVED", "HUMAN_REVIEW_QUEUE"])
            
        # Apply filters
        df_display = df_logs.copy()
        if reg_filter != "All":
            df_display = df_display[df_display["regulation"] == reg_filter]
        if status_filter != "All":
            df_display = df_display[df_display["status"] == status_filter]
            
        # Render stylized Dataframe
        def highlight_status(row):
            if row['status'] == 'AUTO_APPROVED':
                return ['background-color: rgba(16, 185, 129, 0.1)'] * len(row)
            return ['background-color: rgba(245, 158, 11, 0.1)'] * len(row)
            
        st.dataframe(df_display.style.apply(highlight_status, axis=1), use_container_width=True, height=500)
        
        csv_buffer = df_display.to_csv(index=False)
        st.download_button(label="📥 Download Extracted Logs as CSV", data=csv_buffer, file_name="normiq_audit_log.csv", mime="text/csv")
    else:
        st.info("No Audit Logs found in the database. Ask a chat question first to save history!")

    st.markdown('</div>', unsafe_allow_html=True)
