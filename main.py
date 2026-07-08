
# Updated main.py with recommended improvements
import os
import re
import hashlib
from collections import Counter
import fitz
import streamlit as st
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.exceptions import ResourceNotFoundError
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex, SimpleField, SearchableField
 
load_dotenv()
 
st.set_page_config(page_title="AskMyDocs", page_icon="📚", layout="wide")
 
st.markdown("""
<style>
:root{
    --amd-primary:#6366f1;
    --amd-primary-dark:#4338ca;
    --amd-bg:#0f172a;
    --amd-surface:#1e293b;
    --amd-border:#334155;
    --amd-text-soft:#94a3b8;
}
 
.block-container{padding-top:1.5rem; max-width:1200px;}
 
/* Sidebar */
[data-testid="stSidebar"]{
    background:linear-gradient(180deg,#0f172a 0%, #111827 100%);
    border-right:1px solid var(--amd-border);
}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3{
    color:#f1f5f9;
}
[data-testid="stSidebar"] hr{border-color:var(--amd-border);}
 
/* Buttons */
.stButton>button{
    width:100%;
    border-radius:10px;
    border:1px solid var(--amd-primary);
    font-weight:600;
    transition:all .15s ease;
}
.stButton>button:hover{
    border-color:var(--amd-primary-dark);
    box-shadow:0 0 0 3px rgba(99,102,241,0.25);
}
 
/* Hero header */
.amd-hero{
    padding:1.1rem 1.4rem;
    border-radius:16px;
    background:linear-gradient(135deg, #4338ca 0%, #6366f1 45%, #818cf8 100%);
    margin-bottom:1.4rem;
    box-shadow:0 8px 24px rgba(67,56,202,0.25);
}
.amd-hero h1{
    color:white; margin:0; font-size:1.9rem; font-weight:800;
}
.amd-hero p{
    color:#e0e7ff; margin:.25rem 0 0 0; font-size:0.95rem;
}
 
/* Document chip cards */
.amd-doc-card{
    border:1px solid var(--amd-border);
    background:var(--amd-surface);
    border-radius:12px;
    padding:.6rem .9rem;
    margin-bottom:.5rem;
}
.amd-doc-card .amd-doc-name{
    font-weight:600; color:#f1f5f9; font-size:0.92rem;
}
.amd-doc-card .amd-doc-status{
    color:#4ade80; font-size:0.78rem; margin-top:.1rem;
}
 
/* Section labels */
.amd-section-label{
    text-transform:uppercase;
    letter-spacing:.06em;
    font-size:0.75rem;
    font-weight:700;
    color:var(--amd-text-soft);
    margin:.2rem 0 .5rem 0;
}
 
/* Source badges */
.amd-source-badge{
    display:inline-flex;
    align-items:center;
    gap:.35rem;
    background:rgba(99,102,241,0.12);
    border:1px solid rgba(99,102,241,0.35);
    color:#c7d2fe;
    padding:.25rem .65rem;
    border-radius:999px;
    font-size:0.82rem;
    margin:.15rem .3rem .15rem 0;
}
 
/* Relevance bar */
.amd-relevance-row{margin-bottom:.55rem;}
.amd-relevance-label{
    display:flex; justify-content:space-between;
    font-size:0.85rem; color:#e2e8f0; margin-bottom:.2rem;
}
.amd-relevance-track{
    width:100%; height:8px; border-radius:999px;
    background:rgba(148,163,184,0.18); overflow:hidden;
}
.amd-relevance-fill{
    height:100%; border-radius:999px;
    background:linear-gradient(90deg, #6366f1, #a855f7);
}
 
/* Empty state */
.amd-empty{
    text-align:center; padding:2.2rem 1rem;
    border:1px dashed var(--amd-border);
    border-radius:14px; color:var(--amd-text-soft);
}
</style>
""", unsafe_allow_html=True)
 
# ---------- Env var validation ----------
REQUIRED_ENV_VARS = [
    "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY", "AZURE_SEARCH_INDEX",
    "AZURE_OPENAI_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_DEPLOYMENT",
]
missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
if missing:
    st.error(
        "Missing required environment variables:\n\n"
        + "\n".join(f"- {v}" for v in missing)
        + "\n\nAdd these to your `.env` file and restart the app."
    )
    st.stop()
 
search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
search_key = os.getenv("AZURE_SEARCH_KEY")
index_name = os.getenv("AZURE_SEARCH_INDEX")
 
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
 
 
def safe_doc_id(filename: str, page: int, chunk_start: int) -> str:
    """Azure AI Search keys only allow letters, digits, _, -, =.
    Filenames often contain spaces/dots/parentheses, so build a safe id
    from a hash of the filename instead of the raw name."""
    name_hash = hashlib.md5(filename.encode("utf-8")).hexdigest()[:12]
    return f"{name_hash}_{page}_{chunk_start}"
 
 
def index_exists(index_client: SearchIndexClient) -> bool:
    try:
        index_client.get_index(index_name)
        return True
    except ResourceNotFoundError:
        return False
 
 
def ensure_index():
    """Create the index only if it doesn't already exist. Never called on
    every rerun - Streamlit reruns the whole script on every interaction,
    so unconditionally deleting/recreating here would wipe out anything
    already indexed as soon as the user asked a question."""
    index_client = SearchIndexClient(search_endpoint, AzureKeyCredential(search_key))
    if index_exists(index_client):
        return
    idx = SearchIndex(
        name=index_name,
        fields=[
            SimpleField(name="id", type="Edm.String", key=True),
            SearchableField(name="content", type="Edm.String"),
            SearchableField(name="filename", type="Edm.String"),
            SimpleField(name="page", type="Edm.Int32"),
        ],
    )
    index_client.create_index(idx)
 
 
# Only attempt index creation once per session, not on every rerun.
if "index_ready" not in st.session_state:
    try:
        ensure_index()
        st.session_state.index_ready = True
    except Exception as e:
        st.error(f"Failed to create/verify search index: {e}")
        st.stop()
 
if "messages" not in st.session_state:
    st.session_state.messages = []
 
search = SearchClient(search_endpoint, index_name, AzureKeyCredential(search_key))
 
st.markdown("""
<div class="amd-hero">
    <h1>📚 AskMyDocs</h1>
    <p>Upload PDFs, index them, and ask questions across all of them at once.</p>
</div>
""", unsafe_allow_html=True)
 
left, right = st.columns([1, 2])
 
# ---------- Sidebar: upload + document status ----------
with st.sidebar:
    st.markdown("## 📚 AskMyDocs")
    st.caption("Your document workspace")
    st.markdown("---")
    st.markdown('<div class="amd-section-label">Upload PDFs</div>', unsafe_allow_html=True)
 
    files = st.file_uploader(
        "Choose one or more PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdf_uploader",
        label_visibility="collapsed",
    )
 
    st.markdown("---")
    st.markdown(
        f'<div class="amd-section-label">Uploaded Documents ({len(files) if files else 0})</div>',
        unsafe_allow_html=True,
    )
 
    if files:
        for pdf in files:
            size_kb = pdf.size / 1024
            st.markdown(f"""
            <div class="amd-doc-card">
                <div class="amd-doc-name">📕 {pdf.name}</div>
                <div class="amd-doc-status">🟢 Ready for indexing · {size_kb:,.0f} KB</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="amd-empty">📭<br/>No PDFs uploaded yet</div>
        """, unsafe_allow_html=True)
 
    st.markdown("---")
 
with left:
    st.markdown('<div class="amd-section-label">Indexing</div>', unsafe_allow_html=True)
 
    if files:
        with st.expander(f"📋 {len(files)} document(s) selected", expanded=True):
            for pdf in files:
                st.write(f"📄 {pdf.name}")
 
        index_clicked = st.button("⚡ Index PDFs", use_container_width=True)
 
        if index_clicked:
            docs = []
            pages = 0
            CHUNK_SIZE = 800
            OVERLAP = 150
            STEP = CHUNK_SIZE - OVERLAP
            for pdf in files:
                doc = fitz.open(stream=pdf.read(), filetype="pdf")
                pages += len(doc)
                for p, page in enumerate(doc, 1):
                    txt = page.get_text()
                    for i in range(0, len(txt), STEP):
                        docs.append({
                            "id": safe_doc_id(pdf.name, p, i),
                            "content": txt[i:i + CHUNK_SIZE],
                            "filename": pdf.name,
                            "page": p,
                        })
                doc.close()
            with st.spinner("Indexing PDFs..."):
                result = search.upload_documents(docs)
                failed = [r for r in result if not r.succeeded]
 
            if failed:
                st.error(f"⚠️ {len(failed)} chunk(s) failed to index.")
            else:
                st.success("✅ Indexing complete!")
 
            m1, m2, m3 = st.columns(3)
            m1.metric("Documents", len(files))
            m2.metric("Pages", pages)
            m3.metric("Chunks", len(docs))
    else:
        st.markdown("""
        <div class="amd-empty">⬅️<br/>Upload PDFs in the sidebar to get started</div>
        """, unsafe_allow_html=True)
 
    st.markdown("<br/>", unsafe_allow_html=True)
    if st.button("🗑 Clear Chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
 
with right:
    st.markdown('<div class="amd-section-label">Chat</div>', unsafe_allow_html=True)
 
    if not st.session_state.messages:
        st.markdown("""
        <div class="amd-empty">💬<br/>Ask a question about your uploaded documents to get started</div>
        """, unsafe_allow_html=True)
 
    for m in st.session_state.messages:
        avatar = "🧑" if m["role"] == "user" else "📚"
        with st.chat_message(m["role"], avatar=avatar):
            st.markdown(m["content"])
 
    q = st.chat_input("Ask across all uploaded PDFs...")
    if q:
        st.session_state.messages.append({"role": "user", "content": q})
        with st.chat_message("user", avatar="🧑"):
            st.markdown(q)
        with st.chat_message("assistant", avatar="📚"):
            with st.spinner("Searching..."):
                results = list(search.search(q, top=10))
 
            if not results:
                st.warning("No relevant information found.")
            else:
                ranking = Counter()
                sources = []
                context = []
 
                for r in results:
                    filename = r.get("filename", "Unknown Document")
                    page = r.get("page", "?")
                    content = r.get("content", "")
                    ranking[filename] += 1
                    sources.append((filename, page))
                    context.append(
                        f"Document: {filename}\n"
                        f"Page: {page}\n"
                        f"{content}"
                    )
 
                system_prompt = f"""
You are AskMyDocs, an assistant that answers questions using retrieved
excerpts from the user's uploaded PDF documents.
 
The context below was retrieved by a search engine because it matched
the user's question — treat it as likely relevant, not as a strict
literal-match requirement. Use your judgment to connect related
wording (e.g. synonyms, paraphrases, abbreviations) between the
question and the context, the same way a careful human reader would.
 
Guidelines:
- Base your answer on the context below. It's fine to combine
  information from multiple excerpts, and to make reasonable
  inferences that a careful reader would draw directly from the text.
- If several documents are relevant, combine them into one answer.
- If only one document is relevant, mention its name naturally.
- Only say the information isn't available if the context truly has
  nothing related to the question — not merely because the wording
  doesn't match exactly. In that case, respond with exactly:
  "I couldn't find that information in the uploaded documents."
- Do not use outside knowledge beyond what's in the context.
 

Context:
 
{chr(10).join(context)}
"""
                with st.spinner("Thinking..."):
                    resp = client.chat.completions.create(
                        model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": q},
                        ],
                        max_tokens=500,
                    )
 
                ans = resp.choices[0].message.content
                st.markdown(ans)
 
                st.markdown('<div class="amd-section-label">📚 Sources</div>', unsafe_allow_html=True)
                shown = set()
                badges = []
                for f, p in sources:
                    if (f, p) not in shown:
                        badges.append(f'<span class="amd-source-badge">📄 {f} · p.{p}</span>')
                        shown.add((f, p))
                st.markdown("".join(badges), unsafe_allow_html=True)
 
                st.markdown(
                    '<div class="amd-section-label" style="margin-top:1rem;">⭐ Top Matching Documents</div>',
                    unsafe_allow_html=True,
                )
                total = max(sum(ranking.values()), 1)
                rows = []
                for i, (f, c) in enumerate(ranking.most_common(), 1):
                    pct = round(c / total * 100)
                    rows.append(f"""
                    <div class="amd-relevance-row">
                        <div class="amd-relevance-label"><span>{i}. {f}</span><span>{pct}%</span></div>
                        <div class="amd-relevance-track">
                            <div class="amd-relevance-fill" style="width:{pct}%;"></div>
                        </div>
                    </div>
                    """)
                st.markdown("".join(rows), unsafe_allow_html=True)
 
                st.session_state.messages.append({"role": "assistant", "content": ans})

