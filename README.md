# DocLore — RAG Document Chatbot

DocLore is a Flask web application for asking questions about PDF handbooks and documents. It extracts and chunks PDF text, embeds passages with Sentence Transformers, retrieves relevant passages using semantic and lexical search, reranks candidates, and asks a Groq model to write an answer grounded in those passages.

## Features

- Email and password accounts with email verification through SMTP
- Optional Google OAuth sign-in
- User profile settings, including display name, avatar, role, and light or dark theme
- Upload and manage a personal PDF library (up to 50 MB per file)
- Ask questions about one saved PDF or search across all saved PDFs
- Semantic retrieval with FAISS, BM25 term matching, spelling normalization, and cross-encoder reranking
- Source passages, answer confidence and grounding indicators, and PDF passage highlighting
- Persistent account and document metadata in SQLite

## How it works

1. The app extracts page text from a PDF and splits it into overlapping chunks.
2. `all-MiniLM-L6-v2` creates normalized embeddings and FAISS indexes them.
3. A question is matched against the document using semantic and lexical retrieval; a cross-encoder reranks candidate passages.
4. The selected context is sent to the configured Groq model, which is instructed to answer from that context and cite page labels.

## Requirements

- Python 3.10 or newer (Python 3.13 is used in the development environment)
- A Groq API key for answer generation
- Internet access on first run to download the embedding and reranker models
- SMTP credentials to enable email verification; Google OAuth credentials are optional

## Setup

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   # macOS/Linux: source .venv/bin/activate
   ```

2. Install the pinned dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env`, then configure at least:

   ```env
   GROQ_API_KEY=your-groq-api-key
   GROQ_MODEL=openai/gpt-oss-120b
   FLASK_SECRET_KEY=replace-with-a-long-random-secret
   ```

   `GROQ_MODEL` defaults to `openai/gpt-oss-120b`. Set it to a model available to your Groq account if needed. Never commit `.env` or real credentials.

4. Configure account providers as needed:

   - For email verification, set `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, and `MAIL_DEFAULT_SENDER`. For Gmail, use an App Password and SMTP with TLS.
   - For Google sign-in, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from a Google Cloud OAuth 2.0 Web application. Add `http://127.0.0.1:5000/auth/google/callback` as an authorized redirect URI.

## Run locally

```bash
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000), create or sign in to an account, and upload a PDF. Email/password accounts must verify their email before logging in. Google sign-in is available only when its credentials are configured.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | Required API key for answer generation |
| `GROQ_MODEL` | Groq model ID; defaults to `openai/gpt-oss-120b` |
| `GROQ_MAX_TOKENS` | Maximum completion tokens; defaults to `2048` |
| `FLASK_SECRET_KEY` | Stable Flask session/signing key; set this in deployments |
| `APP_DATA_DIR` | Optional persistent directory for `uploads/` and `instance/` |
| `PUBLIC_BASE_URL` | Public app origin used to build verification links |
| `FLASK_HTTPS_ONLY` | Set to `1` to mark session cookies secure behind HTTPS |
| `MAIL_*` | SMTP settings for verification messages; see `.env.example` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Enable Google OAuth sign-in |
| `RAG_CANDIDATE_POOL` | Initial retrieval candidate count; defaults to `60` |
| `RAG_RERANK_CANDIDATES` | Candidates passed to reranking; defaults to `40` |
| `RAG_RERANKER_MODEL` | Cross-encoder model; set to `off` to disable reranking |
| `RAG_MIN_SIMILARITY` | Minimum semantic similarity threshold; defaults to `0.23` |
| `RAG_EMBED_BATCH_SIZE` | Embedding batch size; defaults to `64` |

The complete example configuration is in [`.env.example`](.env.example).

## Data and persistence

By default, account data and document metadata are stored in `instance/accounts.sqlite3`, and uploaded PDFs are stored in `uploads/`. These paths are ignored by Git. Set `APP_DATA_DIR` to a persistent mounted directory when deploying so the database and uploaded files survive restarts or redeploys.

Document metadata and PDF files persist, while FAISS indexes are held in memory and rebuilt from the saved PDF when it is queried after an app restart. The app creates its Flask secret key in the instance directory if `FLASK_SECRET_KEY` is not set; configure an explicit stable secret for deployments. Run behind an HTTPS-capable production WSGI server in production; `python app.py` starts Flask's development server.

## Project layout

```text
.
├── app.py                    # Flask routes, authentication, uploads, chat
├── config.py                 # Project configuration
├── requirements.txt          # Pinned Python dependencies
├── services/
│   ├── embedding.py          # Sentence Transformer embeddings
│   ├── llm.py                # Groq answer generation
│   ├── pdf_highlighter.py    # Highlight cited passages in PDFs
│   ├── pdf_loader.py         # Page-aware PDF text extraction
│   ├── reranker.py           # Cross-encoder reranking
│   ├── retrieval.py          # BM25 and query normalization helpers
│   ├── retriever.py          # Passage retrieval helpers
│   ├── text_splitter.py      # Text chunking
│   └── vector_store.py       # FAISS index creation and search
├── templates/                # Landing, workspace, and profile pages
├── static/                   # CSS, JavaScript, icons, and audio
├── uploads/                  # Runtime PDF storage
└── instance/                 # Runtime SQLite database and Flask key
```

## Retrieval notes

PDF extraction preserves page labels for source references. Text is split into 900-character chunks with 160-character overlap, and embeddings are generated in batches. The cross-encoder model downloads the first time a question is reranked; if it cannot load, retrieval falls back to semantic and lexical ranking. Set `RAG_RERANKER_MODEL=off` to disable it explicitly.
