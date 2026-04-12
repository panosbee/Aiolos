# ══════════════════════════════════════════════════════════════
#  XDART-Φ × XHEART — Production Dockerfile
#  Multi-stage build: slim Python 3.12 + all dependencies
# ══════════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

# System deps for SQLite WAL, SSL, feedparser XML parsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd -r xdart && useradd -r -g xdart -d /app -s /sbin/nologin xdart

WORKDIR /app

# Install Python dependencies (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY xdart/ ./xdart/
COPY run.py .
COPY ui.html .
COPY dashboard.html .

# Copy knowledge/state files (these persist via volume mount in production)
COPY character_state.json .
COPY immediate_memory.json .
COPY self_awareness_brief.json .
COPY wisdom_calibration.json .
COPY seed_concepts.py .

# Copy data files that ship with the app
COPY *.md ./
COPY *.txt ./

# Create data directories with correct permissions
RUN mkdir -p /app/data /app/qdrant_storage /app/logs && \
    chown -R xdart:xdart /app

# Switch to non-root user
USER xdart

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/xdart/health || exit 1

# Expose API port
EXPOSE 8000

# Production: uvicorn with workers
# Workers = 1 because background tasks (perception, curiosity, proactive)
# use asyncio.create_task which is not fork-safe.
# Scale horizontally via Docker replicas instead.
CMD ["uvicorn", "xdart.api:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-keep-alive", "120", \
     "--access-log", \
     "--log-level", "info"]
