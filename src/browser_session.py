"""localStorage bridge for the session id, built on `streamlit-js-eval` (no cookies, no URL).

`streamlit-local-storage` was rejected by the bridge check: its `getAll()` answers `{}` before
the browser round-trip, so "not loaded yet" and "no session" look the same, and a blocked
`localStorage` throws uncaught in its frontend, so it would never answer. Every expression
here catches storage errors in JS, so the browser always answers.

js-eval evaluates once per mounted component, so writes and redirects mount a fresh one keyed
by a generation counter that the read key follows: the next run re-reads the browser instead
of returning the value cached before the write. Call `read_session_id()` once per run, first.
"""

import html
import json
import uuid

import streamlit as st
from streamlit_js_eval import streamlit_js_eval

from src.config.constants import SESSION_ID_STORAGE_KEY

BRIDGE_KEY_PREFIX = "_apg_bridge"  # Prefix of every session_state key the bridge owns
GENERATION_KEY = f"{BRIDGE_KEY_PREFIX}_generation"  # Bumped by each write or redirect
UNAVAILABLE = "__unavailable__"  # JS sentinel returned when the browser blocks localStorage
STORAGE_KEY_JS = json.dumps(SESSION_ID_STORAGE_KEY)  # The localStorage key as a JS literal
SPOTIFY_GREEN = "#1DB954"  # Spotify brand colour, reserved for Spotify-branded controls
FALLBACK_LABEL = "Continue to Spotify"  # Text of the same-tab link shown if scripts are blocked
FALLBACK_STYLE = (  # Inline style of that link: a Spotify-green pill button
    f"display:inline-block;background:{SPOTIFY_GREEN};color:#000;font-weight:600;"
    "padding:0.6rem 1.4rem;border-radius:999px;text-decoration:none"
)


def _guarded(body: str, fallback: str) -> str:
    """Wrap JS statements so the iframe collapses and any exception still yields an answer.

    Args:
        body: JS statements ending with a `return`.
        fallback: JS literal returned when the body throws.

    Returns:
        A JS expression for js-eval.
    """
    collapse = "try { setFrameHeight(0); } catch (e) {}"
    return f"(() => {{ {collapse} try {{ {body} }} catch (e) {{ return {fallback}; }} }})()"


def _generation() -> int:
    """Read the bridge generation of this Streamlit session.

    Returns:
        The current generation (0 before any write).
    """
    return int(st.session_state.get(GENERATION_KEY, 0))


def _mount_once(expression: str, kind: str) -> None:
    """Mount a fresh component for a one-shot browser action and bump the generation.

    Args:
        expression: JS expression to evaluate in the browser.
        kind: Short action name used in the component key.
    """
    generation = _generation() + 1
    st.session_state[GENERATION_KEY] = generation
    streamlit_js_eval(js_expressions=expression, key=f"{BRIDGE_KEY_PREFIX}_{kind}_{generation}")


def _parse_session_id(value: object) -> str | None:
    """Accept only a canonical UUID4 string.

    Args:
        value: Raw value returned by the browser.

    Returns:
        The session id, or None for anything else (empty, sentinel, tampered).
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return None
    return value if parsed.version == 4 and str(parsed) == value else None


def read_session_id() -> tuple[bool, str | None]:
    """Read the session id from localStorage (tri-state).

    Must be rendered on every run: a component that is not rendered loses its value.

    Returns:
        (False, None) until the browser answers, then (True, session id or None).
    """
    body = f'return localStorage.getItem({STORAGE_KEY_JS}) ?? "";'
    expression = _guarded(body, json.dumps(UNAVAILABLE))
    value = streamlit_js_eval(
        js_expressions=expression, key=f"{BRIDGE_KEY_PREFIX}_read_{_generation()}"
    )
    if value is None:
        return False, None
    return True, _parse_session_id(value)


def store_session_id(session_id: str) -> None:
    """Persist the session id; let the run finish (no st.rerun()) so the write reaches the browser.

    Args:
        session_id: Canonical UUID4 of the session.
    """
    if _parse_session_id(session_id) is None:
        raise ValueError("session_id must be a canonical UUID4")
    body = f"localStorage.setItem({STORAGE_KEY_JS}, {json.dumps(session_id)}); return true;"
    _mount_once(_guarded(body, "false"), "store")


def clear_session_id() -> None:
    """Remove the session id; let the run finish (no st.rerun()) so it reaches the browser."""
    body = f"localStorage.removeItem({STORAGE_KEY_JS}); return true;"
    _mount_once(_guarded(body, "false"), "clear")


def redirect_same_tab(url: str) -> None:
    """Navigate the app's own tab to `url` (e.g. Spotify's authorize page).

    The component iframe has no `allow-top-navigation`, so the script clicks a `_self` link
    created in the parent document; if that is blocked too, the rendered link costs one click.

    Args:
        url: Absolute https:// URL to open.
    """
    if not url.startswith("https://"):
        raise ValueError("redirect_same_tab only accepts https:// URLs")
    body = (
        "const doc = window.parent.document; const link = doc.createElement('a');"
        f" link.href = {json.dumps(url)}; link.target = '_self';"
        " doc.body.appendChild(link); link.click(); return true;"
    )
    _mount_once(_guarded(body, "false"), "redirect")
    href = html.escape(url, quote=True)
    st.markdown(
        f'<a href="{href}" target="_self" style="{FALLBACK_STYLE}">{FALLBACK_LABEL}</a>',
        unsafe_allow_html=True,
    )
