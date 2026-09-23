# ---- base ----
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Laya: never probe TensorFlow (avoids abseil deadlock on model load)
    USE_TF=0 \
    USE_TORCH=1 \
    # HuggingFace cache inside the volume
    HF_HOME=/cache/huggingface \
    TORCH_HOME=/cache/torch \
    # CPU inference threads (override via compose)
    OMP_NUM_THREADS=8 \
    MKL_NUM_THREADS=8 \
    TORCH_NUM_THREADS=8 \
    LAYA_DEVICE=cpu \
    LAYA_PRELOAD=1 \
    LAYA_MAX_LOADED=2

WORKDIR /app

# ---- deps ----
FROM base AS deps
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

# ---- runtime ----
FROM base AS runtime
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY app.py .

RUN mkdir -p /cache/huggingface /cache/torch

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

# Single worker: the model lives in process memory; multiple workers = duplicated RAM + no shared cache.
# --no-access-log cuts per-request I/O overhead.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--log-level", "info"]
