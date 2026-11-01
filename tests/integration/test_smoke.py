"""Smoke tests for the deployed Cloud Run service.

They target the canonical public URL, which is the production Spotify redirect URI: the app
serves the OAuth callback at its root. Set it in `config/production.toml`, then:

    make test-smoke

While production still uses the loopback redirect URI (no `https://` override yet), the
whole module is skipped, so `pytest tests/` passes offline.
"""

import httpx
import pytest

from src.config.files import load_config


def _service_url() -> str:
    """Read the canonical public URL from the production configuration.

    Returns:
        The URL without a trailing slash, or an empty string when it is not an https:// URL.
    """
    uri = str(load_config("production").get("spotify", {}).get("redirect_uri", "")).strip()
    return uri.rstrip("/") if uri.startswith("https://") else ""


SERVICE_URL = _service_url()  # Base URL of the live service; empty skips the module
TIMEOUT_S = 30.0  # Generous request timeout that absorbs a scale-from-zero cold start

pytestmark = pytest.mark.skipif(
    not SERVICE_URL,
    reason="Smoke tests require an https:// spotify.redirect_uri in config/production.toml",
)


def test_root_serves_streamlit_html() -> None:
    """The public URL answers 200 with the Streamlit HTML shell."""
    response = httpx.get(f"{SERVICE_URL}/", timeout=TIMEOUT_S)
    assert response.status_code == 200, f"GET {SERVICE_URL}/ returned {response.status_code}"
    assert "text/html" in response.headers.get("content-type", "")


def test_streamlit_health_endpoint() -> None:
    """Streamlit's liveness endpoint answers 200."""
    response = httpx.get(f"{SERVICE_URL}/_stcore/health", timeout=TIMEOUT_S)
    assert response.status_code == 200, f"Health check returned {response.status_code}"
