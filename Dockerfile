# ============================================================
# Stage 1: Builder — install dependencies in an isolated layer
# ============================================================
FROM python:3.13-slim AS builder

WORKDIR /build

# System dependencies required to compile Python packages
# (opencv, pdf2image, pytesseract, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ============================================================
# Stage 2: Runtime — lean final image
# ============================================================
FROM python:3.13-slim AS runtime

LABEL maintainer="ZipAI"
LABEL description="MLO_data – FastAPI service for tax-form extraction"

WORKDIR /app

# Runtime system libraries for OpenCV, Tesseract, Poppler (pdf2image)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built Python packages from builder stage
COPY --from=builder /install /usr/local

# Create a non-root user for security
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy application source code
COPY . .

# Own the app directory
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8002

# Health check against the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/health')" || exit 1

# Run with uvicorn — bind to 0.0.0.0 so Docker networking works
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
