# AskMyDocs 📄

Upload a PDF. Ask anything from it.

AskMyDocs is a RAG (Retrieval-Augmented Generation) app built with Azure AI Search and Azure OpenAI. Upload any PDF your notes, syllabus, research paper and ask questions from it. The app finds the most relevant parts and generates a grounded answer.

---

## What it does

- 📄 Upload any PDF
- 🔍 Azure AI Search indexes the content
- 🤖 Azure OpenAI answers from what's actually in the document


---

## Stack

- Python + Streamlit
- Azure AI Search (Free tier)
- Azure OpenAI (GPT-4.1-nano)
- PyMuPDF for PDF text extraction

---

## Run it locally

```
git clone https://github.com/saishagoel27/AskMyDocs
cd AskMyDocs
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file:

```
AZURE_SEARCH_ENDPOINT=https://your-search-resource.search.windows.net
AZURE_SEARCH_KEY=your_search_key
AZURE_SEARCH_INDEX=documents
AZURE_OPENAI_KEY=your_openai_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=your_deployment_name
AZURE_OPENAI_API_VERSION=2024-12-01-preview
```

Then:

```
streamlit run main.py
```

Open `http://localhost:8501`

---

## Azure setup

**Azure AI Search:**
1. Go to portal.azure.com
2. Create Azure AI Search resource — Free tier
3. Copy endpoint URL and Primary admin key into `.env`

**Azure OpenAI:**
1. Create Azure OpenAI resource
2. Go to Azure AI Foundry → Deploy gpt-4.1-nanp
3. Copy endpoint, key and deployment name into `.env`

---

## Important

Delete your Azure App Service after the session to avoid credit usage. Go to your resource group and delete the App Service and App Service Plan.

