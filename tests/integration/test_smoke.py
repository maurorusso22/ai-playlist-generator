"""Smoke tests for the deployed Cloud Run service.

They need the public service URL, read from the environment or from the project `.env`:

    export CLOUD_RUN_URL=https://playlist-generator-<hash>-uc.a.run.app
    make test-smoke

Without `CLOUD_RUN_URL` the whole module is skipped, so `pytest tests/` passes offline.
"""

import os
from pathlib import Path

import httpx
import pytest
from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"  # Project-level .env, optional
TIMEOUT_S = 30.0  # Generous request timeout that absorbs a scale-from-zero cold start


def _cloud_run_url() -> str:
    """Read the deployed service URL without loading `.env` into the process environment.

    `dotenv_values` keeps the smoke settings from leaking into other tests of the same run.

    Returns:
        The URL without a trailing slash, or an empty string when it is not configured.
    """
    url = os.environ.get("CLOUD_RUN_URL") or dotenv_values(ENV_FILE).get("CLOUD_RUN_URL") or ""
    return url.strip().rstrip("/")


CLOUD_RUN_URL = _cloud_run_url()  # Base URL of the live service; empty skips the module

pytestmark = pytest.mark.skipif(
    not CLOUD_RUN_URL,
    reason="Smoke tests require CLOUD_RUN_URL in the environment or in .env",
)


def test_root_serves_streamlit_html() -> None:
    """The public URL answers 200 with the Streamlit HTML shell."""
    response = httpx.get(f"{CLOUD_RUN_URL}/", timeout=TIMEOUT_S)
    assert response.status_code == 200, f"GET {CLOUD_RUN_URL}/ returned {response.status_code}"
    assert "text/html" in response.headers.get("content-type", "")


def test_streamlit_health_endpoint() -> None:
    """Streamlit's liveness endpoint answers 200."""
    response = httpx.get(f"{CLOUD_RUN_URL}/_stcore/health", timeout=TIMEOUT_S)
    assert response.status_code == 200, f"Health check returned {response.status_code}"
