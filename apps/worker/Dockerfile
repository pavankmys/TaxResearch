# Worker service Dockerfile
FROM docker.io/library/python:3.12-slim

# Set working directory
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser

# Install system dependencies including OCR tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    tesseract-ocr \
    tesseract-ocr-eng \
    ghostscript \
    qpdf \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and source
COPY apps/worker/pyproject.toml /app/
COPY apps/worker/worker /app/worker
COPY packages/legal-core /app/packages/legal-core
COPY packages/storage /app/packages/storage
COPY scripts /app/scripts
COPY config /app/config

# Install dependencies
RUN pip install --no-cache-dir \
    ocrmypdf \
    pillow \
    pypdfium2 \
    pdfplumber && \
    pip install --no-cache-dir -e . && \
    pip install --no-cache-dir -e /app/packages/legal-core && \
    pip install --no-cache-dir -e /app/packages/storage

# Change ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Default environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV CONFIG_DIR=/app/config

# Run the worker
CMD ["sh", "-c", "python scripts/wait_for_db.py --wait-for-table job_queue && python -m worker"]
