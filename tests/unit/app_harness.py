"""Shared AppTest harness: patched bridge, Firestore, LLMs, Spotify and rate limiter.

Session-store writes are replaced by the pure `merge_state`, so the cached state evolves as
it would in Firestore. Each test module wraps `install_mocks` in its own `mocks` fixture.
"""

import pathlib
from dataclasses import dataclass
from unittest.mock import MagicMock

from pytest_mock import MockerFixture
from streamlit.testing.v1 import AppTest

from src.models.session.session_state import SessionState
from src.session_merge import merge_state
from tests.unit.app_builders import clarify_turn, make_tokens
from tests.unit.session_factory import make_state

APP_PATH = str(pathlib.Path(__file__).parents[2] / "app.py")  # Streamlit entry point
TIMEOUT_S = 30  # AppTest run timeout, generous for the first heavy imports
PLAYLIST_ID = "pl123"  # Id returned by the mocked POST /me/playlists
OAUTH_STATE = "oauth-state-123"  # Value returned by the mocked new_oauth_state()


@dataclass
class Mocks:
    """Every patched dependency of the app."""

    read: MagicMock
    store: MagicMock
    clear: MagicMock
    redirect: MagicMock
    load: MagicMock
    create: MagicMock
    save: MagicMock
    touch: MagicMock
    delete: MagicMock
    expired: MagicMock
    run_turn: MagicMock
    resolve: MagicMock
    exchange: MagicMock
    refresh: MagicMock
    spotify: MagicMock
    limited: MagicMock
    gate: MagicMock


def install_mocks(mocker: MockerFixture) -> Mocks:
    """Patch the app's dependencies with offline defaults (no stored session, clarify turns).

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        The mocks, for per-test configuration and assertions.
    """
    bridge, store, auth = "src.browser_session.", "src.session_store.", "src.spotify.auth."
    mocker.patch(auth + "new_oauth_state", return_value=OAUTH_STATE)
    mocker.patch(auth + "ensure_fresh", side_effect=lambda tokens: tokens)
    mocker.patch("src.rate_limiter.get_client_ip", return_value="203.0.113.7")
    spotify = mocker.patch("src.spotify.client.SpotifyClient").return_value
    spotify.create_playlist.return_value = {"id": PLAYLIST_ID}
    spotify.get_me.return_value = {"id": "user1", "display_name": "Mauro"}
    return Mocks(
        read=mocker.patch(bridge + "read_session_id", return_value=(True, None)),
        store=mocker.patch(bridge + "store_session_id"),
        clear=mocker.patch(bridge + "clear_session_id"),
        redirect=mocker.patch(bridge + "redirect_same_tab"),
        load=mocker.patch(store + "load_session", return_value=("missing", None)),
        create=mocker.patch(store + "create_session", return_value=make_state()),
        save=mocker.patch(
            store + "save_turn",
            side_effect=lambda s, m, **c: merge_state(s, [*s.messages, *m], **c),
        ),
        touch=mocker.patch(
            store + "touch", side_effect=lambda s, **c: merge_state(s, s.messages, **c)
        ),
        delete=mocker.patch(store + "delete_session"),
        expired=mocker.patch(store + "is_expired", return_value=False),
        run_turn=mocker.patch("src.chain.run_turn", return_value=clarify_turn()),
        resolve=mocker.patch("src.spotify.resolver.resolve_tracks", return_value=[]),
        exchange=mocker.patch(auth + "exchange_code", return_value=make_tokens(None)),
        refresh=mocker.patch(auth + "refresh_tokens", side_effect=lambda tokens: tokens),
        spotify=spotify,
        limited=mocker.patch("src.rate_limiter.is_rate_limited", return_value=False),
        gate=mocker.patch("src.intent_gate.gate_turn", return_value=None),
    )


def run_app(
    mocks: Mocks, stored: SessionState | None = None, params: dict[str, str] | None = None
) -> AppTest:
    """Run the app once, restoring `stored` as the browser's session when given.

    Args:
        mocks: The installed mocks.
        stored: Session returned by the bootstrap's load, or None for no stored session.
        params: Query parameters of the page load (e.g. an OAuth callback).

    Returns:
        The AppTest after the first script run.
    """
    if stored is not None:
        mocks.read.return_value = (True, stored.session_id)
        mocks.load.return_value = ("active", stored)
    at = AppTest.from_file(APP_PATH, default_timeout=TIMEOUT_S)
    for name, value in (params or {}).items():
        at.query_params[name] = value
    return at.run()


def labels(at: AppTest) -> list[str]:
    """Collect the visible button labels in render order.

    Args:
        at: The AppTest after a run.

    Returns:
        Button labels.
    """
    return [button.label for button in at.button]


def click(at: AppTest, label: str) -> AppTest:
    """Click the first button with `label` and rerun.

    Args:
        at: The AppTest after a run.
        label: Visible button label.

    Returns:
        The AppTest after the rerun.
    """
    return next(b for b in at.button if b.label == label).click().run()


def texts(at: AppTest) -> str:
    """Join every markdown, alert and caption text of the page.

    Args:
        at: The AppTest after a run.

    Returns:
        All visible texts, newline-separated.
    """
    elements = [*at.markdown, *at.error, *at.warning, *at.info, *at.caption]
    return "\n".join(str(element.value) for element in elements)
