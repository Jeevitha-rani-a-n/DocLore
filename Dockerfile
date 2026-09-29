FROM python:3.13-slim

RUN useradd -m -u 1000 user
WORKDIR /app

# CPU-only PyTorch (the default wheel is ~2 GB of GPU libraries)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY --chown=user requirements.txt .
RUN python -c "from pathlib import Path; Path('req.txt').write_text('\n'.join(line for line in Path('requirements.txt').read_text().splitlines() if not line.lower().startswith('torch==')) + '\n')" \
    && pip install --no-cache-dir -r req.txt gunicorn

COPY --chown=user . .
RUN mkdir -p /app/uploads /app/instance && chown -R user /app

USER user
ENV APP_DATA_DIR=/app FLASK_HTTPS_ONLY=0 HF_HOME=/app/.cache

# Pre-download the models so the first request isn't slow
RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer('all-MiniLM-L6-v2'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L6-v2')"

EXPOSE 7860
CMD ["gunicorn", "app:app", "-b", "0.0.0.0:7860", "--workers", "1", "--threads", "4", "--timeout", "180"]
