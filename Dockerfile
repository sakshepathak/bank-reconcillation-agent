FROM python:3.11-slim

LABEL name=bank-reconciliation-agent

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps needed by some wheels (rapidfuzz, onnxruntime via fastembed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (cached layer)
COPY requirements.txt .
RUN pip install --default-timeout=300 --retries=5 -r requirements.txt

# Source is mounted by docker-compose, but copy as a fallback for `docker run`
COPY . .

EXPOSE 8501

# Default command — docker-compose overrides this per service
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
