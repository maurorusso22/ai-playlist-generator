# ── Runtime image for Cloud Run (build with --platform linux/amd64) ───────────
# The base image may carry a reported CVE in an OS-level library for which Debian has
# not yet released a patch: the `apt-get upgrade` step applies every fix available at
# build time. Rebuild when a patched python:3.12.13-slim-bookworm tag is published.
FROM python:3.12.13-slim-bookworm

# No .pyc files in the image; unbuffered stdout/stderr so Cloud Logging gets lines live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Apply OS-level security patches.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

# Upgrade the packaging toolchain to its latest patched versions: unpinned on purpose.
# hadolint ignore=DL3013
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

WORKDIR /app

# Dependencies in their own layer, so source-only changes rebuild quickly.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application source only: scripts/ (the dev-only Spotify spike) is deliberately left out.
COPY src/ ./src/
COPY public/ ./public/
COPY .streamlit/ ./.streamlit/
COPY app.py .

# Unprivileged runtime user; the code stays root-owned and read-only for it.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
