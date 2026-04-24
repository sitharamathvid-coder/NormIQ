import streamlit as st
import pandas as pd
import glob
import os

st.set_page_config(
    page_title="NormIQ — RAGAS Evaluation Dashboard",
    page_icon="📊",
    layout="wide"
)

# ── CSS ───────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0F1117; }
    .metric-card {
        background: #1F2937;
        border: 1px solid #374151;
        border-radius: 10px;
        padding: 16px 20px;
        text-align: center;
    }
    .metric-value {
        font-size: 32px;
        font-weight: 700;
        margin: 4px 0;
    }
    .metric-label {
        font-size: 12px;
        color: #9CA3AF;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-delta {
        font-size: 13px;
        margin-top: 4px;
    }
    .section-header {
        font-size: 18px;
        font-weight: 600;
        color: #14B8A6;
        margin: 24px 0 12px 0;
        padding-bottom: 6px;
        border-bottom: 1px solid #374151;
    }
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────
st.markdown("""
<div style="padding: 20px 0 10px 0;">
    <span style="font-size:32px; font-weight:700; color:#14B8A6;">NormIQ</span>
    <span style="font-size:18px; color:#6B7280; margin-left:12px;">RAGAS Evaluation Dashboard</span>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div style="display:flex; gap:8px; margin-bottom:24px;">
    <span style="background:#1E3A5F; color:#60A5FA; padding:3px 12px; border-radius:20px; font-size:12px; font-weight:600;">HIPAA</span>
    <span style="background:#134E4A; color:#2DD4BF; padding:3px 12px; border-radius:20px; font-size:12px; font-weight:600;">GDPR</span>
    <span style="background:#1E1B4B; color:#A78BFA; padding:3px 12px; border-radius:20px; font-size:12px; font-weight:600;">NIST SP 800-53</span>
</div>
""", unsafe_allow_html=True)

# ── Load CSVs ─────────────────────────────────────────────
eval_dir = os.path.dirname(os.path.abspath(__file__))
csv_files = sorted(glob.glob(os.path.join(eval_dir, "ragas_results_*.csv")))

if not csv_files:
    st.error("No RAGAS result CSV files found in evaluation/ folder!")
    st.info("Run ragas_eval.py first to generate results.")
    st.stop()

# ── Sidebar — file selection ───────────────────────────────
st.sidebar.markdown("### Select CSV files")

file_labels = [os.path.basename(f) for f in csv_files]

if len(csv_files) == 1:
    selected_files = csv_files
    st.sidebar.success(f"1 file found: {file_labels[0]}")
else:
    selected_labels = st.sidebar.multiselect(
        "Choose result files to compare:",
        options=file_labels,
        default=file_labels[-2:] if len(file_labels) >= 2 else file_labels
    )
    selected_files = [
        f for f in csv_files
        if os.path.basename(f) in selected_labels
    ]

if not selected_files:
    st.warning("Please select at least one CSV file from the sidebar.")
    st.stop()

# ── Load data ─────────────────────────────────────────────
dfs = {}
for f in selected_files:
    label = os.path.basename(f).replace("ragas_results_", "").replace(".csv", "")
    df = pd.read_csv(f)
    # Normalize column names
    col_map = {}
    for c in df.columns:
        if "faithfulness" in c.lower():  col_map[c] = "faithfulness"
        if "relevancy" in c.lower():     col_map[c] = "answer_relevancy"
        if "precision" in c.lower():     col_map[c] = "context_precision"
        if "recall" in c.lower():        col_map[c] = "context_recall"
    df = df.rename(columns=col_map)
    dfs[label] = df

# Use latest file as primary
primary_label = list(dfs.keys())[-1]
df = dfs[primary_label]

# ── Overall metrics ───────────────────────────────────────
st.markdown('<div class="section-header">Overall RAGAS Scores</div>',
            unsafe_allow_html=True)

metrics = {
    "Faithfulness":      ("faithfulness",       "#10B981"),
    "Answer Relevancy":  ("answer_relevancy",   "#14B8A6"),
    "Context Precision": ("context_precision",  "#A78BFA"),
    "Context Recall":    ("context_recall",     "#F59E0B"),
}

cols = st.columns(5)

overall_scores = {}
for i, (label, (col, color)) in enumerate(metrics.items()):
    if col in df.columns:
        score = df[col].mean()
        overall_scores[col] = score

        # Delta vs previous if 2 files
        delta_str = ""
        if len(dfs) >= 2:
            prev_label = list(dfs.keys())[-2]
            prev_df    = dfs[prev_label]
            if col in prev_df.columns:
                prev_score = prev_df[col].mean()
                delta      = score - prev_score
                sign       = "+" if delta >= 0 else ""
                col_d      = "#10B981" if delta >= 0 else "#EF4444"
                delta_str  = f'<div class="metric-delta" style="color:{col_d}">{sign}{delta:.3f}</div>'

        cols[i].markdown(f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value" style="color:{color}">{score:.3f}</div>
            {delta_str}
        </div>
        """, unsafe_allow_html=True)

# Overall average
if overall_scores:
    avg = sum(overall_scores.values()) / len(overall_scores)
    cols[4].markdown(f"""
    <div class="metric-card" style="border-color:#14B8A6;">
        <div class="metric-label">Overall Average</div>
        <div class="metric-value" style="color:#14B8A6">{avg:.3f}</div>
        <div class="metric-delta" style="color:#9CA3AF">{len(df)} questions</div>
    </div>
    """, unsafe_allow_html=True)

# ── Before vs After comparison ────────────────────────────
if len(dfs) >= 2:
    st.markdown('<div class="section-header">Before vs After Comparison</div>',
                unsafe_allow_html=True)

    labels_list = list(dfs.keys())
    compare_data = []

    for metric_label, (col, _) in metrics.items():
        row = {"Metric": metric_label}
        for lbl in labels_list:
            d = dfs[lbl]
            if col in d.columns:
                row[lbl] = round(d[col].mean(), 3)
        if len(row) > 1:
            compare_data.append(row)

    compare_df = pd.DataFrame(compare_data).set_index("Metric")

    # Color cells
    def color_cell(val):
        if val >= 0.90: return "background-color:#134E4A; color:#2DD4BF"
        if val >= 0.80: return "background-color:#1E3A5F; color:#60A5FA"
        if val >= 0.70: return "background-color:#422006; color:#FCD34D"
        return "background-color:#7F1D1D; color:#FCA5A5"

    st.dataframe(
        compare_df.style.applymap(color_cell),
        use_container_width=True
    )

# ── By category ───────────────────────────────────────────
if "category" in df.columns:
    st.markdown('<div class="section-header">Results by Regulation Category</div>',
                unsafe_allow_html=True)

    cats = df["category"].unique()
    cat_cols = st.columns(len(cats))

    for i, cat in enumerate(cats):
        cat_df  = df[df["category"] == cat]
        color   = "#60A5FA" if cat == "HIPAA" else "#2DD4BF" if cat == "GDPR" else "#A78BFA"
        bgcol   = "#1E3A5F" if cat == "HIPAA" else "#134E4A" if cat == "GDPR" else "#1E1B4B"
        direct  = len(cat_df[cat_df["status"] == "answered"]) if "status" in cat_df.columns else "N/A"
        avg_conf= cat_df["confidence"].mean() if "confidence" in cat_df.columns else 0

        cat_cols[i].markdown(f"""
        <div style="background:{bgcol}; border:1px solid {color}; border-radius:10px; padding:16px; margin-bottom:12px;">
            <div style="font-size:16px; font-weight:700; color:{color}; margin-bottom:12px;">{cat}</div>
            <div style="font-size:13px; color:#D1D5DB; line-height:2;">
                Faithfulness: <b style="color:{color}">{cat_df['faithfulness'].mean():.3f}</b><br>
                Answer Relevancy: <b style="color:{color}">{cat_df['answer_relevancy'].mean():.3f}</b><br>
                Context Precision: <b style="color:{color}">{cat_df['context_precision'].mean():.3f}</b><br>
                Context Recall: <b style="color:{color}">{cat_df['context_recall'].mean():.3f}</b><br>
                Avg Confidence: <b style="color:{color}">{avg_conf:.3f}</b><br>
                Direct answers: <b style="color:{color}">{direct}/{len(cat_df)}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ── Per question table ────────────────────────────────────
st.markdown('<div class="section-header">Per Question Results</div>',
            unsafe_allow_html=True)

# Filter controls
col1, col2, col3 = st.columns(3)
with col1:
    cat_filter = st.selectbox(
        "Filter by category:",
        ["All"] + list(df["category"].unique()) if "category" in df.columns else ["All"]
    )
with col2:
    metric_sort = st.selectbox(
        "Sort by:",
        ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    )
with col3:
    sort_order = st.selectbox("Order:", ["Lowest first", "Highest first"])

# Apply filters
filtered = df.copy()
if cat_filter != "All" and "category" in filtered.columns:
    filtered = filtered[filtered["category"] == cat_filter]

ascending = sort_order == "Lowest first"
if metric_sort in filtered.columns:
    filtered = filtered.sort_values(metric_sort, ascending=ascending)

# Display columns
display_cols = []
for c in ["id", "category", "question", "faithfulness",
          "answer_relevancy", "context_precision",
          "context_recall", "confidence", "status"]:
    if c in filtered.columns:
        display_cols.append(c)

display_df = filtered[display_cols].copy()

# Round numeric columns
for c in ["faithfulness", "answer_relevancy", "context_precision",
          "context_recall", "confidence"]:
    if c in display_df.columns:
        display_df[c] = display_df[c].round(3)

# Truncate question
if "question" in display_df.columns:
    display_df["question"] = display_df["question"].str[:60] + "..."

def highlight_row(row):
    styles = [""] * len(row)
    faith_idx = list(row.index).index("faithfulness") if "faithfulness" in row.index else -1
    if faith_idx >= 0:
        val = row["faithfulness"]
        if val < 0.50:
            styles = ["background-color:#7F1D1D; color:#FCA5A5"] * len(row)
        elif val < 0.70:
            styles = ["background-color:#422006; color:#FDE68A"] * len(row)
        elif val >= 0.90:
            styles = ["background-color:#134E4A; color:#6EE7B7"] * len(row)
    return styles

st.dataframe(
    display_df.style.apply(highlight_row, axis=1),
    use_container_width=True,
    height=400
)

# ── Low faithfulness ──────────────────────────────────────
if "faithfulness" in df.columns:
    low = df[df["faithfulness"] < 0.70]
    if len(low) > 0:
        st.markdown('<div class="section-header">Low Faithfulness Questions (&lt; 0.70)</div>',
                    unsafe_allow_html=True)
        st.warning(f"{len(low)} questions below 0.70 faithfulness — these answers go beyond retrieved chunks")

        for _, row in low.iterrows():
            cat   = row.get("category", "")
            color = "#60A5FA" if cat == "HIPAA" else "#2DD4BF"
            st.markdown(f"""
            <div style="background:#1F2937; border-left:3px solid #EF4444;
                        border-radius:0 8px 8px 0; padding:10px 14px; margin-bottom:8px;">
                <span style="color:{color}; font-size:11px; font-weight:600;">[{row.get('id','')}] {cat}</span>
                <span style="color:#EF4444; font-size:11px; margin-left:8px;">
                    Faith: {row['faithfulness']:.3f}</span>
                <div style="color:#D1D5DB; font-size:13px; margin-top:4px;">
                    {str(row.get('question',''))[:80]}...</div>
            </div>
            """, unsafe_allow_html=True)

# ── Footer ────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style="text-align:center; color:#4B5563; font-size:12px; padding:12px 0;">
    NormIQ RAGAS Evaluation Dashboard ·
    TalentSprint Applied GenAI & Agentic AI · Cohort 3 · April 2026
</div>
""", unsafe_allow_html=True)
