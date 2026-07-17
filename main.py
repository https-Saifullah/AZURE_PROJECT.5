
import os
import hashlib
from collections import Counter

import fitz
import streamlit as st
from dotenv import load_dotenv
from openai import AzureOpenAI

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
)

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

load_dotenv()

st.set_page_config(
    page_title="AskMyDocs",
    page_icon="📚",
    layout="wide"
)

# ---------------------------------------------------------
# CSS
# ---------------------------------------------------------

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

.block-container{
    padding-top:1.5rem;
    max-width:1200px;
}

[data-testid="stSidebar"]{
    background:linear-gradient(180deg,#0f172a,#111827);
    border-right:1px solid var(--amd-border);
}

.stButton>button{
    width:100%;
    border-radius:10px;
}

.amd-hero{
    padding:1.2rem;
    border-radius:16px;
    background:linear-gradient(135deg,#4338ca,#6366f1,#818cf8);
    margin-bottom:1rem;
}

.amd-doc-card{
    border:1px solid var(--amd-border);
    border-radius:12px;
    padding:.6rem;
    margin-bottom:.5rem;
}

.amd-source-badge{
    display:inline-block;
    padding:.3rem .6rem;
    border-radius:999px;
    margin:.2rem;
    background:#2d3b77;
}

.amd-empty{
    border:1px dashed #555;
    border-radius:10px;
    padding:2rem;
    text-align:center;
    color:#999;
}

.amd-section-label{
    font-size:.8rem;
    color:#94a3b8;
    font-weight:bold;
    margin-bottom:.5rem;
}

</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

REQUIRED_ENV_VARS = [
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_SEARCH_KEY",
    "AZURE_SEARCH_INDEX",
    "AZURE_OPENAI_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_DEPLOYMENT",
]

missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]

if missing:
    st.error(
        "Missing environment variables:\n\n"
        + "\n".join(missing)
    )
    st.stop()

search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
search_key = os.getenv("AZURE_SEARCH_KEY")
index_name = os.getenv("AZURE_SEARCH_INDEX")

openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)

search_index_client = SearchIndexClient(
    endpoint=search_endpoint,
    credential=AzureKeyCredential(search_key),
)

search_client = SearchClient(
    endpoint=search_endpoint,
    index_name=index_name,
    credential=AzureKeyCredential(search_key),
)

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def safe_doc_id(filename: str, page: int, offset: int):
    digest = hashlib.md5(filename.encode()).hexdigest()[:12]
    return f"{digest}_{page}_{offset}"


def create_index():

    fields = [

        SimpleField(
            name="id",
            type=SearchFieldDataType.String,
            key=True,
        ),

        SearchableField(
            name="content",
            type=SearchFieldDataType.String,
        ),

        SearchableField(
            name="filename",
            type=SearchFieldDataType.String,
        ),

        SimpleField(
            name="page",
            type=SearchFieldDataType.Int32,
        ),
    ]

    index = SearchIndex(
        name=index_name,
        fields=fields,
    )

    search_index_client.create_index(index)


def ensure_index():

    try:

        idx = search_index_client.get_index(index_name)

        names = {field.name for field in idx.fields}

        expected = {
            "id",
            "content",
            "filename",
            "page",
        }

        if names != expected:

            st.warning(
                "Index schema changed. Recreating search index..."
            )

            search_index_client.delete_index(index_name)

            create_index()

    except ResourceNotFoundError:

        create_index()
     # ---------------------------------------------------------
# Initialize
# ---------------------------------------------------------

if "index_ready" not in st.session_state:

    ensure_index()
    st.session_state.index_ready = True

if "messages" not in st.session_state:
    st.session_state.messages = []

if "indexed_files" not in st.session_state:
    st.session_state.indexed_files = set()

# ---------------------------------------------------------
# Header
# ---------------------------------------------------------

st.markdown("""
<div class="amd-hero">
<h1>📚 AskMyDocs</h1>
<p>Upload PDFs, index them and ask questions across all documents.</p>
</div>
""", unsafe_allow_html=True)

left, right = st.columns([1,2])

# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------

with st.sidebar:

    st.header("📚 AskMyDocs")

    files = st.file_uploader(
        "Upload PDFs",
        type=["pdf"],
        accept_multiple_files=True,
    )

    st.divider()

    st.subheader("Uploaded PDFs")

    if files:

        for pdf in files:

            status = (
                "✅ Indexed"
                if pdf.name in st.session_state.indexed_files
                else "⏳ Waiting"
            )

            st.markdown(
                f"""
<div class="amd-doc-card">
<b>{pdf.name}</b><br>
{status}
</div>
""",
                unsafe_allow_html=True,
            )

    else:

        st.markdown(
            '<div class="amd-empty">No PDFs uploaded</div>',
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------
# Left Panel
# ---------------------------------------------------------

with left:

    st.subheader("Index Documents")

    if files:

        if st.button(
            "⚡ Index PDFs",
            use_container_width=True,
        ):

            docs = []

            pages = 0

            CHUNK_SIZE = 800
            OVERLAP = 150
            STEP = CHUNK_SIZE - OVERLAP

            progress = st.progress(0)

            total_files = len(files)

            for file_no, pdf in enumerate(files):

                # Skip already indexed files

                if pdf.name in st.session_state.indexed_files:
                    continue

                document = fitz.open(
                    stream=pdf.read(),
                    filetype="pdf",
                )

                pages += len(document)

                for page_number, page in enumerate(document, start=1):

                    text = page.get_text()

                    if not text.strip():
                        continue

                    for start in range(0, len(text), STEP):

                        chunk = text[start:start + CHUNK_SIZE]

                        docs.append(
                            {
                                "id": safe_doc_id(
                                    pdf.name,
                                    page_number,
                                    start,
                                ),
                                "content": chunk,
                                "filename": pdf.name,
                                "page": page_number,
                            }
                        )

                document.close()

                progress.progress((file_no + 1) / total_files)

            if docs:

                with st.spinner("Uploading to Azure AI Search..."):

                    result = search_client.upload_documents(
                        documents=docs
                    )

                failures = [
                    r for r in result
                    if not r.succeeded
                ]

                if failures:

                    st.error(
                        f"{len(failures)} chunks failed."
                    )

                else:

                    for pdf in files:
                        st.session_state.indexed_files.add(pdf.name)

                    st.success(
                        f"Successfully indexed {len(docs)} chunks."
                    )

                    c1, c2, c3 = st.columns(3)

                    c1.metric(
                        "PDFs",
                        len(st.session_state.indexed_files),
                    )

                    c2.metric(
                        "Pages",
                        pages,
                    )

                    c3.metric(
                        "Chunks",
                        len(docs),
                    )

            else:

                st.info(
                    "All uploaded PDFs are already indexed."
                )

    else:

        st.markdown(
            '<div class="amd-empty">Upload one or more PDFs.</div>',
            unsafe_allow_html=True,
        )

    st.divider()

    if st.button(
        "🗑 Clear Chat",
        use_container_width=True,
    ):

        st.session_state.messages.clear()

        st.rerun()
     # ---------------------------------------------------------
# Right Panel (Chat)
# ---------------------------------------------------------

with right:

    st.subheader("💬 Ask Questions")

    if not st.session_state.messages:

        st.markdown(
            """
<div class="amd-empty">
Ask a question about your uploaded documents.
</div>
""",
            unsafe_allow_html=True,
        )

    # Display previous conversation

    for message in st.session_state.messages:

        avatar = "🧑" if message["role"] == "user" else "📚"

        with st.chat_message(
            message["role"],
            avatar=avatar,
        ):
            st.markdown(message["content"])

    question = st.chat_input(
        "Ask across all uploaded PDFs..."
    )

    if question:

        st.session_state.messages.append(
            {
                "role": "user",
                "content": question,
            }
        )

        with st.chat_message(
            "user",
            avatar="🧑",
        ):
            st.markdown(question)

        with st.chat_message(
            "assistant",
            avatar="📚",
        ):

            with st.spinner("Searching documents..."):

                results = list(
                    search_client.search(
                        search_text=question,
                        top=10,
                    )
                )

            if len(results) == 0:

                answer = (
                    "I couldn't find that information "
                    "in the uploaded documents."
                )

                st.warning(answer)

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": answer,
                    }
                )

            else:

                ranking = Counter()

                context = []

                sources = []

                for hit in results:

                    filename = hit.get(
                        "filename",
                        "Unknown",
                    )

                    page = hit.get(
                        "page",
                        "?",
                    )

                    content = hit.get(
                        "content",
                        "",
                    )

                    ranking[filename] += 1

                    sources.append(
                        (
                            filename,
                            page,
                        )
                    )

                    context.append(
                        f"""
Document: {filename}
Page: {page}

{content}
"""
                    )

                prompt = f"""
You are AskMyDocs.

Answer ONLY using the retrieved document excerpts.

If multiple documents contain relevant
information, combine them.

If the answer is unavailable, reply exactly:

I couldn't find that information in the uploaded documents.

Context:

{chr(10).join(context)}
"""

                with st.spinner("Generating answer..."):

                    response = openai_client.chat.completions.create(

                        model=os.getenv(
                            "AZURE_OPENAI_DEPLOYMENT"
                        ),

                        messages=[
                            {
                                "role": "system",
                                "content": prompt,
                            },
                            {
                                "role": "user",
                                "content": question,
                            },
                        ],

                        temperature=0,

                        max_tokens=700,
                    )

                answer = response.choices[0].message.content

                st.markdown(answer)
             # ---------------------------------------------------------


# ---------------------------------------------------------
# Sources
# ---------------------------------------------------------

if "sources" in locals() and sources:

    st.markdown("---")
    st.markdown("### 📚 Sources")

    shown = set()

    for filename, page in sources:

        if (filename, page) in shown:
            continue

        shown.add((filename, page))

        st.markdown(
            f"""
<span class="amd-source-badge">
📄 <b>{filename}</b> &nbsp;|&nbsp; Page {page}
</span>
""",
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------
# Relevance Ranking
# ---------------------------------------------------------

if "ranking" in locals() and ranking:

    st.markdown("---")
    st.markdown("### ⭐ Top Matching Documents")

    total_hits = sum(ranking.values())

    for i, (filename, hits) in enumerate(
        ranking.most_common(),
        start=1,
    ):

        percent = round(hits * 100 / total_hits)

        st.markdown(f"**{i}. {filename}**")

        st.progress(percent / 100)

# ---------------------------------------------------------
# Save Conversation
# ---------------------------------------------------------

if "answer" in locals():

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
        }
    )

    try:

        index = search_index_client.get_index(index_name)

        fields = {field.name for field in index.fields}

        expected = {
            "id",
            "content",
            "filename",
            "page",
        }

        if fields != expected:

            st.warning("Updating Azure Search index schema...")

            search_index_client.delete_index(index_name)

            create_index()

    except ResourceNotFoundError:

        create_index()

    except Exception as ex:

        st.error(f"Index initialization failed:\n\n{ex}")

        st.stop()
