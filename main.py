
# Updated main.py with recommended improvements
import os
from collections import Counter
import fitz
import streamlit as st
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex, SimpleField, SearchableField

load_dotenv()

st.set_page_config(page_title="AskMyDocs", page_icon="📚", layout="wide")

st.markdown("""
<style>
.block-container{padding-top:2rem;}
[data-testid="stSidebar"]{background:#111827;}
.stButton>button{width:100%;border-radius:8px;}
</style>
""", unsafe_allow_html=True)

search_endpoint=os.getenv("AZURE_SEARCH_ENDPOINT")
search_key=os.getenv("AZURE_SEARCH_KEY")
index_name=os.getenv("AZURE_SEARCH_INDEX")

client=AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

def create_index():
    idx=SearchIndex(
        name=index_name,
        fields=[
            SimpleField(name="id",type="Edm.String",key=True),
            SearchableField(name="content",type="Edm.String"),
            SearchableField(name="filename",type="Edm.String"),
            SimpleField(name="page",type="Edm.Int32"),
        ]
    )
    SearchIndexClient(search_endpoint,AzureKeyCredential(search_key)).create_or_update_index(idx)

try:
    create_index()
except Exception:
    pass

if "messages" not in st.session_state:
    st.session_state.messages=[]

search=SearchClient(search_endpoint,index_name,AzureKeyCredential(search_key))

st.title("📚 AskMyDocs")
left,right=st.columns([1,2])

# ---------- Enhanced Sidebar ----------
with st.sidebar:
    st.title("📚 AskMyDocs")
    st.markdown("---")
    st.subheader("📂 Upload PDFs")

    files = st.file_uploader(
        "Choose PDFs",
        type=["pdf"],
        accept_multiple_files=True
    )

    st.markdown("---")
    st.subheader("📄 Uploaded Documents")

    if files:
        for pdf in files:
            st.container(border=True)
            with st.container(border=True):
                st.markdown(f"### 📕 {pdf.name}")
                st.caption("🟢 Ready for indexing")
    else:
        st.info("No PDFs uploaded yet.")

    st.markdown("---")


with left:
    st.subheader("📂 Upload PDFs")
    files=st.file_uploader("Choose one or more PDFs",type="pdf",accept_multiple_files=True)

    if files:
        st.markdown("### Uploaded Documents")
        for pdf in files:
            st.write(f"📄 {pdf.name}")

    if files and st.button("Index PDFs"):
        docs=[];pages=0
        CHUNK_SIZE=800
        OVERLAP=150
        STEP=CHUNK_SIZE-OVERLAP
        for pdf in files:
            doc=fitz.open(stream=pdf.read(),filetype="pdf")
            pages+=len(doc)
            for p,page in enumerate(doc,1):
                txt=page.get_text()
                for i in range(0,len(txt),STEP):
                    docs.append({
                        "id":f"{pdf.name}_{p}_{i}",
                        "content":txt[i:i+CHUNK_SIZE],
                        "filename":pdf.name,
                        "page":p
                    })
            doc.close()
        with st.spinner("Indexing PDFs..."):
            search.upload_documents(docs)
        st.success("✅ Indexing complete!")
        st.info(f"Documents: {len(files)}\n\nPages: {pages}\n\nChunks: {len(docs)}")

    if st.button("🗑 Clear Chat"):
        st.session_state.messages=[]
        st.rerun()

with right:
    st.subheader("💬 Chat")
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    q=st.chat_input("Ask across all uploaded PDFs...")
    if q:
        st.session_state.messages.append({"role":"user","content":q})
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            with st.spinner("Searching..."):
                results=list(search.search(q,top=10))
                if not results:
                    st.warning("No relevant information found.")
                    st.stop()

                ranking=Counter()
                sources=[]
                context=[]

                for r in results:
                    ranking[r["filename"]]+=1
                    sources.append((r["filename"],r["page"]))
                    context.append(
                        f"Document: {r['filename']}\n"
                        f"Page: {r['page']}\n"
                        f"{r['content']}"
                    )

                system_prompt=f"""
You are AskMyDocs.

The user has uploaded one or more PDF documents.

Answer ONLY using the retrieved context.

If multiple documents contain relevant information,
combine them into a single answer.

If only one document contains the answer,
mention the document name naturally.

If the answer cannot be found, respond exactly with:

"I couldn't find that information in the uploaded documents."

Context:

{chr(10).join(context)}
"""

                resp=client.chat.completions.create(
                    model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                    messages=[
                        {"role":"system","content":system_prompt},
                        {"role":"user","content":q}
                    ],
                    max_tokens=500
                )

                ans=resp.choices[0].message.content
                st.markdown(ans)

                st.markdown("### 📚 Sources")
                shown=set()
                for f,p in sources:
                    if (f,p) not in shown:
                        st.write(f"• {f} — Page {p}")
                        shown.add((f,p))

                st.markdown("### ⭐ Top Matching Documents")
                total=max(sum(ranking.values()),1)
                for i,(f,c) in enumerate(ranking.most_common(),1):
                    st.progress(c/total)
                    st.write(f"{i}. {f} ({round(c/total*100)}% relevance)")

                st.session_state.messages.append({"role":"assistant","content":ans})
