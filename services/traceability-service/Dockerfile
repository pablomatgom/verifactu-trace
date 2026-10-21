# syntax=docker/dockerfile:1

# ---- Build stage: install the dependencies into an isolated virtualenv ----
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create a virtualenv in /opt/venv and add it to PATH.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the requirements first so this layer is cached until it changes.
WORKDIR /build
COPY requirements.txt .

# Install prebuilt wheels only: a package without a wheel fails the build instead of
# running the setup script of a source distribution.
RUN pip install --only-binary :all: -r requirements.txt


# ---- Runtime stage: only the virtualenv and the application code ----
FROM python:3.12-slim AS runtime

# Set the environment variables for the runtime.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Run as an unprivileged user.
# A fixed numeric UID lets orchestrators verify that the container does not run as root.
RUN groupadd --system --gid 10001 appgroup \
    && useradd --system --uid 10001 --gid appgroup --no-create-home --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
COPY --chown=appuser:appgroup app ./app

USER 10001:10001

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8002/health').status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
