# One image runs the web server, the worker, the eval script and the
# seeding script. Works on Apple Silicon (arm64) and Intel (amd64).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the embedding model at build time so the first review is fast
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "reviewbot.server:app", "--host", "0.0.0.0", "--port", "8000"]
