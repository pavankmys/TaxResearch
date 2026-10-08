# API service Dockerfile
FROM docker.io/library/python:3.12-slim

# Set working directory
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 appuser

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and source
COPY apps/api/pyproject.toml /app/
COPY apps/api/app /app/app
COPY apps/api/alembic /app/alembic
COPY apps/api/alembic.ini /app/
COPY packages/legal-core /app/packages/legal-core
COPY scripts /app/scripts

# Install dependencies
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir -e /app/packages/legal-core

# Change ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# Default environment
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Run the application
CMD ["sh", "-c", "python scripts/wait_for_db.py && alembic upgrade head && uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000"]
