# syntax=docker/dockerfile:1

# ---- Build stage: install the dependencies into an isolated virtualenv ----
FROM python:3.12-slim AS builder

# Build tools live only in this stage: they are needed to compile native extensions
# and are discarded, so they never reach the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create a virtualenv in /opt/venv and add it to PATH.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the requirements first so this layer is cached until it changes.
WORKDIR /build
COPY requirements.txt .
RUN pip install -r requirements.txt


# ---- Runtime stage: only the virtualenv and the application code ----
FROM python:3.12-slim AS runtime

# Set the environment variables for the runtime.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Run as an unprivileged user.
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
COPY --chown=appuser:appgroup app ./app

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
