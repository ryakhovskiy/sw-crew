FROM python:3.12-slim AS base

# Prevent bytecode files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install git (needed by GitPython at runtime)
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer caching)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Copy source code
COPY src/ src/

# Create runtime directories
RUN mkdir -p workspace db logs

# Non-root user
RUN groupadd -r crew && useradd -r -g crew -d /app crew && \
    chown -R crew:crew /app
USER crew

EXPOSE 8080

# Default: run the gateway (which also starts the orchestrator)
CMD ["uvicorn", "crew.gateway.app:app", "--host", "0.0.0.0", "--port", "8080"]
