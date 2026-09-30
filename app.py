import os
import re
import uuid
import logging
import sqlite3
import secrets
import hmac
import math
import json
import smtplib
import ssl
import threading
from email.message import EmailMessage
from functools import wraps
from io import BytesIO
from datetime import datetime
from time import perf_counter

from dotenv import load_dotenv

# Load .env BEFORE importing services (services/llm.py reads GROQ_* at import time)
load_dotenv()

from flask import Flask, request, jsonify, render_template, send_file, send_from_directory, abort, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from authlib.integrations.flask_client import OAuth
from pypdf import PdfReader

from services.pdf_loader import extract_pages
from services.pdf_highlighter import highlighted_pdf
from services.text_splitter import split_text
from services.embedding import create_embeddings
from services.vector_store import (
    create_vector_store,
    search_vector_store
)
from services.llm import generate_response, GROQ_MODEL
from services.retrieval import bm25_scores, build_retrieval_metadata, normalize_query
from services.reranker import rerank_passages

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DATA_DIR = os.path.abspath(os.getenv("APP_DATA_DIR") or BASE_DIR)
UPLOAD_FOLDER = os.path.join(APP_DATA_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
INSTANCE_FOLDER = os.path.join(APP_DATA_DIR, "instance")
os.makedirs(INSTANCE_FOLDER, exist_ok=True)
AUTH_DATABASE = os.path.join(INSTANCE_FOLDER, "accounts.sqlite3")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rag-chatbot")

app = Flask(__name__)
secret_key_path = os.path.join(INSTANCE_FOLDER, "flask_secret_key")
if os.getenv("FLASK_SECRET_KEY"):
    app.secret_key = os.environ["FLASK_SECRET_KEY"]
else:
    try:
        with open(secret_key_path, "rb") as secret_file:
            app.secret_key = secret_file.read()
    except FileNotFoundError:
        app.secret_key = secrets.token_bytes(32)
        with open(secret_key_path, "wb") as secret_file:
            secret_file.write(app.secret_key)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("FLASK_HTTPS_ONLY", "0") == "1",
)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload limit
oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)
GOOGLE_OAUTH_ENABLED = bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))
PROFILE_AVATARS = ["🦊", "🐼", "🦉", "🐙", "🐢", "🐝", "🐨", "🦁", "🐯", "🐰", "🐸", "🦄"]
PROFILE_ROLES = ["Student", "Faculty", "Staff", "Administrator", "Other"]

# In-memory document library: {document_id: record}
documents = {}
upload_jobs = {}
upload_jobs_lock = threading.Lock()


def init_auth_database():
    with sqlite3.connect(AUTH_DATABASE) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                email_verified INTEGER NOT NULL DEFAULT 0,
                google_sub TEXT,
                display_name TEXT NOT NULL DEFAULT '',
                avatar TEXT NOT NULL DEFAULT '🦊',
                role TEXT NOT NULL DEFAULT 'Student',
                theme TEXT NOT NULL DEFAULT 'dark',
                email_notifications INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT
            )
        """)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        migrations = {
            "email_verified": "INTEGER NOT NULL DEFAULT 0",
            "google_sub": "TEXT",
            "display_name": "TEXT NOT NULL DEFAULT ''",
            "avatar": "TEXT NOT NULL DEFAULT '🦊'",
            "role": "TEXT NOT NULL DEFAULT 'Student'",
            "theme": "TEXT NOT NULL DEFAULT 'dark'",
            "email_notifications": "INTEGER NOT NULL DEFAULT 0",
            "updated_at": "TEXT",
        }
        for column, sql_type in migrations.items():
            if column not in columns:
                connection.execute(f"ALTER TABLE users ADD COLUMN {column} {sql_type}")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub_unique ON users (google_sub)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                file_size REAL NOT NULL,
                pages INTEGER NOT NULL,
                characters INTEGER NOT NULL,
                chunks INTEGER NOT NULL,
                uploaded_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        connection.execute("CREATE INDEX IF NOT EXISTS documents_owner_created ON documents (owner_id, created_at)")
        for user_id, email in connection.execute("SELECT id, email FROM users WHERE display_name = '' OR display_name IS NULL"):
            local_name = email.split("@", 1)[0].replace(".", " ").replace("_", " ").replace("-", " ")
            connection.execute("UPDATE users SET display_name = ? WHERE id = ?", (local_name.title()[:80] or "User", user_id))


init_auth_database()


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def get_user_profile(user_id):
    with sqlite3.connect(AUTH_DATABASE) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT id, email, display_name, avatar, role, theme, email_notifications, created_at, updated_at, google_sub "
            "FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def validate_csrf():
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(submitted and expected and hmac.compare_digest(submitted, expected))


def verification_serializer():
    return URLSafeTimedSerializer(app.secret_key, salt="documind-email-verification-v1")


def send_verification_email(email, token):
    """Send a short-lived email verification link through configured SMTP."""
    host = os.getenv("MAIL_SERVER", "").strip()
    sender = os.getenv("MAIL_DEFAULT_SENDER", "").strip() or os.getenv("MAIL_USERNAME", "").strip()
    if not host or not sender:
        raise RuntimeError("Email delivery is not configured. Set MAIL_SERVER and MAIL_DEFAULT_SENDER.")

    base_url = PUBLIC_BASE_URL or request.url_root.rstrip("/")
    verify_url = f"{base_url}{url_for('verify_email', token=token)}"
    message = EmailMessage()
    message["Subject"] = "Verify your DocLore email"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        "Welcome to DocLore. Confirm your email address to finish creating your account.\n\n"
        f"Verify your email: {verify_url}\n\n"
        "This link expires in 24 hours. If you did not request this, you can ignore this message."
    )

    port = int(os.getenv("MAIL_PORT", "587"))
    username = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_PASSWORD", "")
    use_ssl = os.getenv("MAIL_USE_SSL", "0").lower() in {"1", "true", "yes"}
    use_tls = os.getenv("MAIL_USE_TLS", "1").lower() in {"1", "true", "yes"}
    timeout = float(os.getenv("MAIL_TIMEOUT", "15"))
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    smtp = smtp_class(host, port, timeout=timeout, context=context) if use_ssl else smtp_class(host, port, timeout=timeout)
    with smtp:
        if use_tls and not use_ssl:
            smtp.starttls(context=context)
        if username:
            smtp.login(username, password)
        smtp.send_message(message)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            if request.path in {"/chat", "/upload", "/documents", "/profile/theme"} or request.path.startswith("/documents/"):
                return jsonify({"error": "Please log in to use the workspace."}), 401
            return redirect(url_for("home", mode="login", next=request.path) + "#signup")
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def public_record(record):
    """Fields that are safe / useful to send to the browser."""
    keys = ("id", "filename", "file_size", "pages", "characters",
            "chunks", "uploaded_at", "document_url")
    return {key: record[key] for key in keys}


def get_document_record(document_id, owner_id):
    """Return a user's saved PDF record, restoring its metadata after restart."""
    record = documents.get(document_id)
    if record and record.get("owner_id") == owner_id:
        if os.path.isfile(os.path.join(UPLOAD_FOLDER, record["stored_name"])):
            return record
        documents.pop(document_id, None)

    with sqlite3.connect(AUTH_DATABASE) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT id, owner_id, filename, stored_name, file_size, pages, characters, chunks, uploaded_at "
            "FROM documents WHERE id = ? AND owner_id = ?",
            (document_id, owner_id),
        ).fetchone()
    if not row:
        return None

    record = dict(row)
    record["document_url"] = f"/document/{record['id']}"
    pdf_path = os.path.join(UPLOAD_FOLDER, record["stored_name"])
    if not os.path.isfile(pdf_path):
        return None
    documents[document_id] = record
    return record


def load_document_index(record):
    """Build an in-memory search index on first use; the uploaded PDF stays on disk."""
    if record.get("index") is not None and record.get("chunks_data") is not None:
        return
    pdf_path = os.path.join(UPLOAD_FOLDER, record["stored_name"])
    text, document_chunks, embeddings, document_index, retrieval_metadata = process_document(pdf_path)
    record.update({
        "characters": len(text),
        "chunks": len(document_chunks),
        "chunks_data": document_chunks,
        "index": document_index,
        "retrieval_metadata": retrieval_metadata,
    })
    with sqlite3.connect(AUTH_DATABASE) as connection:
        connection.execute(
            "UPDATE documents SET characters = ?, chunks = ? WHERE id = ? AND owner_id = ?",
            (len(text), len(document_chunks), record["id"], record["owner_id"]),
        )


def latest_document(user_id=None):
    if user_id is None:
        return next((record for record in reversed(documents.values())), None)
    with sqlite3.connect(AUTH_DATABASE) as connection:
        row = connection.execute(
            "SELECT id FROM documents WHERE owner_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    return get_document_record(row[0], user_id) if row else None


def user_documents(user_id):
    """Return all of a user's saved PDF records in library order."""
    with sqlite3.connect(AUTH_DATABASE) as connection:
        rows = connection.execute(
            "SELECT id FROM documents WHERE owner_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [
        record for (document_id,) in rows
        if (record := get_document_record(document_id, user_id)) is not None
    ]


BROAD_QUESTION = re.compile(
    r"\b(summari[sz]e|summary|overview|key points?|main points?|main ideas?|"
    r"what is (this|the) (document|pdf|handbook)|about (this|the) (document|pdf|handbook)|"
    r"who (is|are|wrote)\b.*\b(author|writer)|author|title|table of contents|topics)\b",
    re.IGNORECASE,
)


def retrieve_context(question, chunks, index, retrieval_metadata=None):
    """Use semantic + BM25 retrieval, document-aware typo correction and reranking."""
    if not chunks:
        return "", [], 0.0, question

    retrieval_metadata = retrieval_metadata or build_retrieval_metadata(chunks)
    normalized_question = normalize_query(question, retrieval_metadata)
    query_variants = list(dict.fromkeys((question, normalized_question)))
    # Users often shorten "vice chancellor" to "VC". Expand that common
    # university role before both dense and lexical retrieval.
    for query in tuple(query_variants):
        if re.search(r"\bvc\b", query, re.IGNORECASE):
            query_variants.append(re.sub(r"\bvc\b", "vice chancellor", query, flags=re.IGNORECASE))
    query_variants = list(dict.fromkeys(query_variants))
    query_embeddings = create_embeddings(query_variants)
    candidate_pool = max(10, int(os.getenv("RAG_CANDIDATE_POOL", "60")))
    search_k = min(len(chunks), candidate_pool)
    dense_scores = [-1.0] * len(chunks)
    candidates = set()
    for query_embedding in query_embeddings:
        similarities, indices = search_vector_store(index, query_embedding.reshape(1, -1), k=search_k)
        for similarity, chunk_index in zip(similarities[0], indices[0]):
            if chunk_index < 0:
                continue
            chunk_index = int(chunk_index)
            dense_scores[chunk_index] = max(dense_scores[chunk_index], float(similarity))
            candidates.add(chunk_index)

    bm25, lexical_coverage = bm25_scores(query_variants, retrieval_metadata)
    candidates.update(sorted(range(len(chunks)), key=lambda i: bm25[i], reverse=True)[:candidate_pool])
    ranked = []
    for chunk_index in candidates:
        similarity = dense_scores[chunk_index]
        semantic = max(0.0, similarity)
        hybrid = 0.70 * semantic + 0.30 * bm25[chunk_index]
        ranked.append((hybrid, similarity, bm25[chunk_index], lexical_coverage[chunk_index], chunk_index, chunks[chunk_index]))
    ranked.sort(key=lambda item: item[0], reverse=True)

    min_similarity = float(os.getenv("RAG_MIN_SIMILARITY", "0.23"))
    is_broad_question = bool(BROAD_QUESTION.search(normalized_question))
    if not is_broad_question and not any(
        item[1] >= min_similarity or item[3] >= 0.35 for item in ranked
    ):
        return "", [], 0.0, normalized_question

    rerank_count = min(max(0, int(os.getenv("RAG_RERANK_CANDIDATES", "40"))), len(ranked))
    if rerank_count and not is_broad_question:
        rerank_scores = rerank_passages(
            normalized_question,
            [item[5] for item in ranked[:rerank_count]],
        )
        if rerank_scores is not None:
            reranked = []
            for position, item in enumerate(ranked[:rerank_count]):
                raw_score = max(-50.0, min(50.0, rerank_scores[position]))
                cross_score = 1.0 / (1.0 + math.exp(-raw_score))
                final_score = 0.45 * item[0] + 0.55 * cross_score
                reranked.append((final_score, *item[1:]))
            ranked = sorted(reranked + ranked[rerank_count:], key=lambda item: item[0], reverse=True)

    # Broad questions ("summarize", "key points", "who is the author") do not resemble any
    # single passage, so similarity search rejects them. Give the model the opening pages
    # plus a small number of passages spread across the document instead.
    if is_broad_question:
        if re.search(r"\b(author|writer|title)\b", normalized_question, re.IGNORECASE):
            source_limit = 1
            picked = [0]
        elif re.search(r"\b(summari[sz]e|summary|overview|key points?|main points?|main ideas?)\b", normalized_question, re.IGNORECASE):
            source_limit = 3
            picked = [0, len(chunks) // 2, len(chunks) - 1]
        else:
            source_limit = 2
            picked = [0, len(chunks) // 2]
        picked = list(dict.fromkeys(max(0, min(len(chunks) - 1, index)) for index in picked))[:source_limit]
        selected = [chunks[i] for i in picked]
        context = "\n\n".join(f"[Passage {n}]\n{c}" for n, c in enumerate(selected, start=1))
        # Broad document-level requests intentionally sample across pages; their
        # retrieval score is capped because a few passages cannot represent every page.
        return context, selected, 0.35, normalized_question

    # Avoid sending unrelated passages to the model when even the best match is weak.
    if not ranked:
        return "", [], 0.0, normalized_question
    ranked = [
        item for item in ranked
        if item[1] >= min_similarity or item[3] >= 0.35
    ]
    if not ranked:
        return "", [], 0.0, normalized_question

    asks_for_multiple = bool(re.search(
        r"\b(and|also|compare|contrast|difference|versus|vs|both|each|all|list|multiple)\b",
        normalized_question,
        re.IGNORECASE,
    )) or question.count("?") > 1
    source_limit = 3 if asks_for_multiple else 2
    best_score = ranked[0][0]
    retrieved = [ranked[0]]
    for position, candidate in enumerate(ranked[1:], start=1):
        if len(retrieved) >= source_limit:
            break
        score_margin = 0.14 if position == 1 else 0.22
        if ((candidate[1] >= min_similarity or candidate[3] >= 0.35)
                and candidate[0] >= best_score - score_margin):
            retrieved.append(candidate)

    retrieved_chunks = [item[5] for item in retrieved]

    context = "\n\n".join(
        f"[Passage {number}]\n{chunk}"
        for number, chunk in enumerate(retrieved_chunks, start=1)
    )

    best_similarity = max(0.0, retrieved[0][1])
    semantic_relevance = max(0.0, min(1.0, (best_similarity - min_similarity) / max(0.72 - min_similarity, 0.01)))
    confidence = max(0.0, min(1.0, 0.65 * semantic_relevance + 0.35 * retrieved[0][3]))
    return context, retrieved_chunks, confidence, normalized_question


def grounding_score(answer, context):
    """Estimate answer support using content-word overlap with retrieved text."""
    stop_words = {
        "about", "after", "again", "also", "and", "are", "because", "been",
        "before", "being", "between", "could", "does", "each", "from", "have",
        "into", "more", "most", "only", "other", "over", "same", "some",
        "such", "than", "that", "their", "there", "these", "they", "this",
        "those", "through", "under", "very", "what", "when", "where", "which",
        "while", "with", "would", "your", "the", "for", "was", "were", "will",
        "has", "had", "his", "her", "its", "our", "you", "she", "him", "them",
        "then", "not", "but", "can", "may", "all", "any", "who", "how", "why",
        "does", "did", "been", "being", "a", "an", "as", "at", "by", "in", "is",
        "it", "of", "on", "or", "to", "be", "if", "we", "he", "i", "me", "my"
    }
    answer_terms = {
        term.lower() for term in re.findall(r"[\w'-]+", answer)
        if len(term) > 2 and term.lower() not in stop_words
    }
    if not answer_terms:
        return 0.0
    context_terms = {
        term.lower() for term in re.findall(r"[\w'-]+", context)
    }
    return round(100 * len(answer_terms & context_terms) / len(answer_terms), 1)


def process_document(pdf_path, progress_callback=None):
    """
    Extract text, split into chunks, create embeddings,
    and build the FAISS index.
    """
    if progress_callback:
        progress_callback(5, "Reading PDF")
    pages = extract_pages(pdf_path)
    if progress_callback:
        progress_callback(20, "Splitting document")
    text = "\n\n".join(page for page in pages if page)
    chunks = [
        f"[Page {page_number}] {chunk}"
        for page_number, page_text in enumerate(pages, start=1)
        if page_text
        for chunk in split_text(page_text)
    ]

    if not chunks:
        raise ValueError(
            "No readable text found in this PDF. It may be a scanned/image-only PDF."
        )

    if progress_callback:
        progress_callback(30, "Creating embeddings")
    embeddings = create_embeddings(
        chunks,
        progress_callback=(
            lambda completed, total: progress_callback(
                30 + int(58 * completed / total),
                "Creating embeddings",
            )
        ) if progress_callback else None,
    )
    if progress_callback:
        progress_callback(92, "Building search index")
    index = create_vector_store(embeddings)
    if progress_callback:
        progress_callback(97, "Preparing search metadata")
    retrieval_metadata = build_retrieval_metadata(chunks)
    if progress_callback:
        progress_callback(100, "Indexing complete")

    return text, chunks, embeddings, index, retrieval_metadata


# ---------------------------------------------------------------------------
# Error handlers (always answer the frontend with JSON, never an HTML page)
# ---------------------------------------------------------------------------
@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "File is too large (max 50 MB)."}), 413


@app.errorhandler(500)
def server_error(_error):
    return jsonify({"error": "Internal server error. Check the server console."}), 500


# ---------------------------------------------------------------------------
# Pages / documents
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("workspace"))
    return render_template("landing.html", csrf_token=csrf_token(), current_year=datetime.now().year,
                           google_oauth_enabled=GOOGLE_OAUTH_ENABLED)


@app.route("/signup", methods=["POST"])
def signup():
    if not validate_csrf():
        abort(400, "The form expired. Please try again.")
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        flash("Enter a valid email address.", "error")
        return redirect(url_for("home") + "#signup")
    if len(password) < 8:
        flash("Choose a password with at least 8 characters.", "error")
        return redirect(url_for("home") + "#signup")
    try:
        with sqlite3.connect(AUTH_DATABASE) as connection:
            cursor = connection.execute(
                "INSERT INTO users (email, password_hash, created_at, email_verified, display_name) VALUES (?, ?, ?, 0, ?)",
                (email, generate_password_hash(password), datetime.now().isoformat(),
                 email.split("@", 1)[0].replace(".", " ").replace("_", " ").title()[:80] or "User"),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        flash("An account with that email already exists. Log in instead.", "error")
        return redirect(url_for("home", mode="login") + "#signup")
    try:
        token = verification_serializer().dumps({"user_id": user_id, "email": email})
        send_verification_email(email, token)
    except Exception:
        log.exception("Could not send email verification message")
        flash("Your account was created, but we could not send the verification email. Check the mail settings and use Resend verification below.", "error")
        return redirect(url_for("home", mode="login") + "#signup")
    flash("Check your inbox for a verification link. You can log in after verifying your email.", "success")
    return redirect(url_for("home", mode="login") + "#signup")


@app.route("/login", methods=["POST"])
def login():
    if not validate_csrf():
        abort(400, "The form expired. Please try again.")
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    with sqlite3.connect(AUTH_DATABASE) as connection:
        user = connection.execute(
            "SELECT id, email, password_hash, email_verified FROM users WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
    if not user or not check_password_hash(user[2], password):
        flash("Email or password is incorrect.", "error")
        return redirect(url_for("home", mode="login") + "#signup")
    if not user[3]:
        flash("Please verify your email before logging in. Use Resend verification if you need a new link.", "error")
        return redirect(url_for("home", mode="login") + "#signup")
    session.clear()
    session["user_id"] = user[0]
    session["user_email"] = user[1]
    csrf_token()
    return redirect(url_for("workspace"))


@app.route("/resend-verification", methods=["POST"])
def resend_verification():
    if not validate_csrf():
        abort(400, "The form expired. Please try again.")
    email = request.form.get("email", "").strip().lower()
    with sqlite3.connect(AUTH_DATABASE) as connection:
        user = connection.execute(
            "SELECT id, email FROM users WHERE email = ? COLLATE NOCASE AND email_verified = 0",
            (email,),
        ).fetchone()
    if user:
        try:
            token = verification_serializer().dumps({"user_id": user[0], "email": user[1]})
            send_verification_email(user[1], token)
        except Exception:
            log.exception("Could not resend email verification message")
    flash("If that address has an unverified account, a new verification link has been sent.", "success")
    return redirect(url_for("home", mode="login") + "#signup")


@app.route("/verify-email/<token>")
def verify_email(token):
    try:
        payload = verification_serializer().loads(token, max_age=24 * 60 * 60)
    except SignatureExpired:
        flash("That verification link has expired. Request a new one below.", "error")
        return redirect(url_for("home", mode="login") + "#signup")
    except BadSignature:
        flash("That verification link is invalid. Request a new one below.", "error")
        return redirect(url_for("home", mode="login") + "#signup")

    with sqlite3.connect(AUTH_DATABASE) as connection:
        cursor = connection.execute(
            "UPDATE users SET email_verified = 1 WHERE id = ? AND email = ? COLLATE NOCASE",
            (payload.get("user_id"), payload.get("email", "")),
        )
        verified = cursor.rowcount > 0
    if verified:
        flash("Email verified. You can now log in.", "success")
    else:
        flash("That account could not be verified. Try signing up again.", "error")
    return redirect(url_for("home", mode="login") + "#signup")


@app.route("/auth/google")
def google_login():
    if not GOOGLE_OAUTH_ENABLED:
        flash("Google sign-in is not configured yet. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in the server environment.", "error")
        return redirect(url_for("home", mode="login") + "#signup")
    callback_path = url_for("google_callback")
    redirect_uri = f"{PUBLIC_BASE_URL}{callback_path}" if PUBLIC_BASE_URL else url_for("google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    if not GOOGLE_OAUTH_ENABLED:
        return redirect(url_for("home", mode="login") + "#signup")
    try:
        token = oauth.google.authorize_access_token()
        profile = token.get("userinfo") or {}
    except Exception:
        log.exception("Google OAuth sign-in failed")
        flash("Google sign-in could not be completed. Please try again.", "error")
        return redirect(url_for("home", mode="login") + "#signup")

    email = str(profile.get("email", "")).strip().lower()
    google_sub = str(profile.get("sub", "")).strip()
    email_verified = profile.get("email_verified") in (True, "true", "True", 1)
    if not email or not google_sub or not email_verified:
        flash("Google did not provide a verified email address.", "error")
        return redirect(url_for("home", mode="login") + "#signup")

    try:
        with sqlite3.connect(AUTH_DATABASE) as connection:
            user = connection.execute(
                "SELECT id, email, google_sub FROM users WHERE google_sub = ?",
                (google_sub,),
            ).fetchone()
            if user is None:
                user = connection.execute(
                    "SELECT id, email, google_sub FROM users WHERE email = ? COLLATE NOCASE",
                    (email,),
                ).fetchone()
                if user:
                    if user[2] and user[2] != google_sub:
                        flash("That email is already linked to a different Google account.", "error")
                        return redirect(url_for("home", mode="login") + "#signup")
                    connection.execute(
                        "UPDATE users SET email_verified = 1, google_sub = ? WHERE id = ?",
                        (google_sub, user[0]),
                    )
                else:
                    cursor = connection.execute(
                        "INSERT INTO users (email, password_hash, created_at, email_verified, google_sub, display_name) VALUES (?, ?, ?, 1, ?, ?)",
                        (email, generate_password_hash(secrets.token_urlsafe(48)), datetime.now().isoformat(), google_sub,
                         str(profile.get("name", "")).strip()[:80] or email.split("@", 1)[0].title()),
                    )
                    user = (cursor.lastrowid, email, google_sub)
    except sqlite3.IntegrityError:
        flash("That Google account is already linked to another account.", "error")
        return redirect(url_for("home", mode="login") + "#signup")

    session.clear()
    session["user_id"] = user[0]
    session["user_email"] = user[1]
    csrf_token()
    return redirect(url_for("workspace"))


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    if not validate_csrf():
        abort(400, "The form expired. Please try again.")
    session.clear()
    return redirect(url_for("home"))


@app.route("/workspace")
@login_required
def workspace():
    profile = get_user_profile(session["user_id"])
    if profile is None:
        session.clear()
        return redirect(url_for("home", mode="login") + "#signup")
    return render_template("index.html", model_name=GROQ_MODEL,
                           user_id=session["user_id"], user_email=profile["email"], profile=profile,
                           csrf_token=csrf_token())


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile_settings():
    profile = get_user_profile(session["user_id"])
    if profile is None:
        session.clear()
        return redirect(url_for("home", mode="login") + "#signup")

    if request.method == "POST":
        if not validate_csrf():
            abort(400, "The form expired. Please try again.")
        display_name = request.form.get("display_name", "").strip()
        avatar = request.form.get("avatar", "")
        role = request.form.get("role", "")
        theme = "dark" if request.form.get("dark_mode") == "on" else "light"
        email_notifications = 1 if request.form.get("email_notifications") == "on" else 0
        if not display_name or len(display_name) > 80:
            flash("Display name must be between 1 and 80 characters.", "error")
        elif avatar not in PROFILE_AVATARS:
            flash("Choose one of the available avatars.", "error")
        elif role not in PROFILE_ROLES:
            flash("Choose a role from the list.", "error")
        else:
            with sqlite3.connect(AUTH_DATABASE) as connection:
                connection.execute(
                    "UPDATE users SET display_name = ?, avatar = ?, role = ?, theme = ?, email_notifications = ?, updated_at = ? WHERE id = ?",
                    (display_name, avatar, role, theme, email_notifications, datetime.now().isoformat(), session["user_id"]),
                )
            session["display_name"] = display_name
            flash("Profile settings saved.", "success")
            return redirect(url_for("profile_settings"))
        profile = get_user_profile(session["user_id"])

    return render_template(
        "profile.html", profile=profile, profile_avatars=PROFILE_AVATARS,
        profile_roles=PROFILE_ROLES, csrf_token=csrf_token(),
    )


@app.route("/profile/theme", methods=["POST"])
@login_required
def save_profile_theme():
    if not validate_csrf():
        return jsonify({"error": "Your session expired. Reload the page and try again."}), 400
    theme = request.form.get("theme", "")
    if theme not in {"dark", "light"}:
        return jsonify({"error": "Invalid theme preference."}), 400
    with sqlite3.connect(AUTH_DATABASE) as connection:
        connection.execute(
            "UPDATE users SET theme = ?, updated_at = ? WHERE id = ?",
            (theme, datetime.now().isoformat(), session["user_id"]),
        )
    return jsonify({"message": "Theme preference saved."})


@app.route("/document/<document_id>")
@login_required
def view_document(document_id):
    """Serve the original PDF or a copy marked with a retrieved passage."""
    document = get_document_record(document_id, session["user_id"])
    if not document:
        abort(404)
    citations = request.args.getlist("highlight")[:3]
    if citations:
        try:
            highlighted = highlighted_pdf(
                os.path.join(UPLOAD_FOLDER, document["stored_name"]),
                [citation[:1200] for citation in citations],
            )
            if highlighted is not None:
                return send_file(
                    highlighted,
                    mimetype="application/pdf",
                    download_name=document["filename"],
                    as_attachment=False,
                    conditional=False,
                )
        except Exception:
            log.exception("Could not highlight the cited PDF passage")
    return send_from_directory(UPLOAD_FOLDER, document["stored_name"], mimetype="application/pdf")


@app.route("/documents")
@login_required
def list_documents():
    with sqlite3.connect(AUTH_DATABASE) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id, owner_id, filename, stored_name, file_size, pages, characters, chunks, uploaded_at "
            "FROM documents WHERE owner_id = ? ORDER BY created_at DESC",
            (session["user_id"],),
        ).fetchall()
    owned = []
    for row in rows:
        record = dict(row)
        record["document_url"] = f"/document/{record['id']}"
        if os.path.isfile(os.path.join(UPLOAD_FOLDER, record["stored_name"])):
            owned.append(public_record(record))
    return jsonify({"documents": owned})


@app.route("/documents/<document_id>", methods=["DELETE"])
@login_required
def delete_document(document_id):
    """Remove a document from the library (index + file on disk)."""
    document = get_document_record(document_id, session["user_id"])
    if not document:
        return jsonify({"error": "Document not found."}), 404
    documents.pop(document_id, None)
    with sqlite3.connect(AUTH_DATABASE) as connection:
        connection.execute(
            "DELETE FROM documents WHERE id = ? AND owner_id = ?",
            (document_id, session["user_id"]),
        )
    try:
        os.remove(os.path.join(UPLOAD_FOLDER, document["stored_name"]))
    except OSError:
        pass
    return jsonify({"message": "Document removed.", "id": document_id}), 200


@app.route("/upload", methods=["POST"])
@login_required
def upload_pdf():
    file = request.files.get("pdf") or request.files.get("file")

    if file is None or file.filename == "":
        return jsonify({"error": "Please select a PDF."}), 400

    original_name = secure_filename(file.filename)
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a PDF file."}), 400
    if not original_name.lower().endswith(".pdf"):
        # secure_filename strips non-ASCII names entirely; keep a usable name
        original_name = "document.pdf"

    document_id = uuid.uuid4().hex
    stored_name = f"{document_id}_{original_name}"
    pdf_path = os.path.join(UPLOAD_FOLDER, stored_name)

    file.save(pdf_path)
    job_id = document_id
    with upload_jobs_lock:
        upload_jobs[job_id] = {
            "owner_id": session["user_id"],
            "filename": original_name,
            "status": "processing",
            "progress": 0,
            "stage": "Preparing upload",
        }
    worker = threading.Thread(
        target=_process_upload_job,
        args=(job_id, session["user_id"], original_name, stored_name, pdf_path),
        daemon=True,
    )
    worker.start()
    return jsonify({"job_id": job_id, "filename": original_name}), 202


def _set_upload_progress(job_id, progress, stage):
    with upload_jobs_lock:
        job = upload_jobs.get(job_id)
        if job and job["status"] == "processing":
            job["progress"] = max(job["progress"], min(100, int(progress)))
            job["stage"] = stage


def _process_upload_job(job_id, owner_id, original_name, stored_name, pdf_path):
    document_id = job_id
    try:
        file_size = round(os.path.getsize(pdf_path) / 1024, 2)
        page_count = len(PdfReader(pdf_path).pages)
        text, document_chunks, embeddings, document_index, retrieval_metadata = process_document(
            pdf_path,
            progress_callback=lambda progress, stage: _set_upload_progress(job_id, progress, stage),
        )
    except ValueError as exc:
        _remove_quietly(pdf_path)
        with upload_jobs_lock:
            upload_jobs[job_id].update({"status": "failed", "error": str(exc)})
        return
    except Exception:
        log.exception("Failed to process PDF")
        _remove_quietly(pdf_path)
        with upload_jobs_lock:
            upload_jobs[job_id].update({"status": "failed", "error": "Could not process this PDF. It may be corrupted or encrypted."})
        return

    uploaded_at = datetime.now().strftime("%I:%M %p")
    record = {
        "id": document_id,
        "owner_id": owner_id,
        "filename": original_name,
        "stored_name": stored_name,
        "file_size": file_size,
        "pages": page_count,
        "characters": len(text),
        "chunks": len(document_chunks),
        "uploaded_at": uploaded_at,
        "document_url": f"/document/{document_id}",
        "chunks_data": document_chunks,
        "index": document_index,
        "retrieval_metadata": retrieval_metadata,
    }
    documents[document_id] = record
    try:
        with sqlite3.connect(AUTH_DATABASE) as connection:
            connection.execute(
                "INSERT INTO documents "
                "(id, owner_id, filename, stored_name, file_size, pages, characters, chunks, uploaded_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (document_id, owner_id, original_name, stored_name, file_size,
                 page_count, len(text), len(document_chunks), uploaded_at, datetime.now().isoformat()),
            )
    except sqlite3.Error:
        documents.pop(document_id, None)
        _remove_quietly(pdf_path)
        log.exception("Could not save uploaded PDF metadata")
        with upload_jobs_lock:
            upload_jobs[job_id].update({"status": "failed", "error": "The PDF was processed but could not be saved to your library."})
        return

    result = {
        "message": "PDF uploaded successfully!",
        "id": document_id,
        "filename": original_name,
        "document_url": record["document_url"],
        "file_size": file_size,
        "pages": page_count,
        "characters": len(text),
        "chunks": len(document_chunks),
        "embeddings": len(embeddings),
        "uploaded_at": uploaded_at
    }
    with upload_jobs_lock:
        upload_jobs[job_id].update({
            "status": "complete",
            "progress": 100,
            "stage": "Indexing complete",
            "document": result,
        })


@app.route("/upload/status/<job_id>")
@login_required
def upload_status(job_id):
    with upload_jobs_lock:
        job = upload_jobs.get(job_id)
        if not job or job["owner_id"] != session["user_id"]:
            return jsonify({"error": "Upload job not found."}), 404
        response = {
            "status": job["status"],
            "progress": job.get("progress", 0),
            "stage": job.get("stage", "Indexing"),
            "error": job.get("error"),
            "document": job.get("document"),
        }
        if job["status"] in {"complete", "failed"}:
            upload_jobs.pop(job_id, None)
    return jsonify(response), 200


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
@app.route("/chat", methods=["POST"])
@login_required
def chat():
    # Tolerate JSON or form posts, and a few common key names, so a frontend
    # tweak (e.g. "message" instead of "question") doesn't silently break chat.
    data = request.get_json(silent=True) or request.form.to_dict() or {}

    question = (
        data.get("question") or data.get("message")
        or data.get("query") or data.get("prompt") or ""
    ).strip()
    document_id = data.get("document_id") or data.get("documentId") or data.get("doc_id")
    all_documents = data.get("all_documents") in (True, "true", "1", 1)
    requested_document_ids = data.get("document_ids") or data.get("documentIds") or []
    if isinstance(requested_document_ids, str):
        try:
            requested_document_ids = json.loads(requested_document_ids)
        except (TypeError, ValueError):
            requested_document_ids = []
    if not isinstance(requested_document_ids, list):
        requested_document_ids = []
    requested_document_ids = list(dict.fromkeys(str(item) for item in requested_document_ids if item))

    if not question:
        return jsonify({"error": "Question is required."}), 400

    selected_documents = []
    if all_documents:
        selected_documents = user_documents(session["user_id"])
        if not selected_documents:
            return jsonify({"error": "Please upload a PDF before searching all handbooks."}), 400
        document = None
    elif requested_document_ids:
        selected_documents = []
        for requested_id in requested_document_ids:
            handbook = get_document_record(requested_id, session["user_id"])
            if handbook is None:
                return jsonify({"error": "One of the selected handbooks is no longer available. Please refresh your library."}), 404
            selected_documents.append(handbook)
        document = None
    elif document_id:
        document = get_document_record(document_id, session["user_id"])
        if document is None:
            return jsonify({
                "error": "This handbook is no longer available in your saved library. Please upload it again."
            }), 404
    else:
        document = latest_document(session["user_id"])
        if document is None:
            return jsonify({"error": "Please upload a PDF first."}), 400

    try:
        retrieval_started = perf_counter()
        if all_documents or requested_document_ids:
            document_results = []
            for handbook in selected_documents:
                try:
                    load_document_index(handbook)
                    result_context, result_chunks, result_confidence, result_question = retrieve_context(
                        question,
                        handbook["chunks_data"],
                        handbook["index"],
                        handbook.get("retrieval_metadata"),
                    )
                    if result_context and result_chunks:
                        document_results.append((result_confidence, handbook, result_chunks, result_question))
                except Exception:
                    log.exception("Could not search saved handbook %s", handbook.get("filename", handbook["id"]))

            document_results.sort(key=lambda item: item[0], reverse=True)
            selected_sources = []
            selected_context = []
            for result_confidence, handbook, result_chunks, _result_question in document_results:
                for chunk in result_chunks[:3]:
                    selected_sources.append(
                        f"[Document ID: {handbook['id']}] [Document: {handbook['filename']}] {chunk}"
                    )
                    selected_context.append(f"[Document: {handbook['filename']}]\n{chunk}")
                    if len(selected_sources) >= 8:
                        break
                if len(selected_sources) >= 8:
                    break
            retrieved_chunks = selected_sources
            context = "\n\n".join(selected_context)
            confidence_score = max((item[0] for item in document_results), default=0.0)
            normalized_question = document_results[0][3] if document_results else question
        else:
            load_document_index(document)
            context, retrieved_chunks, confidence_score, normalized_question = retrieve_context(
                question,
                document["chunks_data"],
                document["index"],
                document.get("retrieval_metadata"),
            )
        retrieval_time_ms = round((perf_counter() - retrieval_started) * 1000, 1)

        comparison_mode = bool(
            (all_documents or requested_document_ids)
            and len({item[1]["id"] for item in document_results if item[2]}) >= 2
        )
        generation_started = perf_counter()
        answer = generate_response(
            question,
            context,
            normalized_question=normalized_question,
            comparison_mode=comparison_mode,
        )
        conflict_details = None
        if comparison_mode:
            conflict_heading = re.search(
                r"(?i)Conflict detected\s*:\s*",
                answer,
            )
            if conflict_heading:
                conflict_start = answer.rfind("\n", 0, conflict_heading.start()) + 1
                answer, conflict_details = (
                    answer[:conflict_start].strip(),
                    answer[conflict_heading.end():].strip(),
                )
        generation_time_ms = round((perf_counter() - generation_started) * 1000, 1)
        grounding_score_value = grounding_score(answer, context)
    except Exception as exc:
        log.exception("Chat failed")
        return jsonify({
            "error": f"Could not generate an answer: {exc}"
        }), 500

    return jsonify({
        "answer": answer,
        "conflict": conflict_details,
        "document_id": document["id"] if document else None,
        "sources": [chunk[:1000] + "..." for chunk in retrieved_chunks],
        "timings": {
            "retrieval_ms": retrieval_time_ms,
            "generation_ms": generation_time_ms
        },
        "answer_info": {
            "confidence_score": round(max(0.0, min(1.0, confidence_score)) * 100, 1),
            "grounding_score": grounding_score_value
        }
    }), 200


if __name__ == "__main__":
    app.run(debug=True)
