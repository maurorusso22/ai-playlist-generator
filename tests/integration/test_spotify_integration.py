"""Live Spotify integration tests: Client Credentials token, search and resolution rate.

Requires `SPOTIFY_CLIENT_SECRET` in `.env` and the `[spotify]` section of `config/base.toml`.
Playlist creation needs a user login and is covered by `python -m scripts.spotify_spike`.
Run with:

    pytest tests/integration/test_spotify_integration.py -s
"""

import os
import time
from collections.abc import Iterator

import pytest
from dotenv import load_dotenv

from src.config.errors import ConfigError
from src.config.secrets import get_secrets
from src.config.settings import get_settings
from src.models.conversation.track_suggestion import TrackSuggestion
from src.spotify import auth
from src.spotify.client import SpotifyClient
from src.spotify.resolver import resolve_tracks

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.getenv("SPOTIFY_CLIENT_SECRET"),
    reason="Spotify integration tests require SPOTIFY_CLIENT_SECRET in .env",
)

NFR02_BUDGET_S = 10.0  # NFR-02: generation plus resolution of a 16-track playlist (P95)
NFR05_MIN_RATE = 0.9  # NFR-05: share of mainstream suggestions found on Spotify
HOUSE_HITS = [  # 16 mainstream 2010s house hits, as an LLM would suggest them
    ("Animals", "Martin Garrix"),
    ("Levels", "Avicii"),
    ("Wake Me Up", "Avicii"),
    ("Don't You Worry Child", "Swedish House Mafia"),
    ("Titanium", "David Guetta"),
    ("Summer", "Calvin Harris"),
    ("Clarity", "Zedd"),
    ("Lean On", "Major Lazer"),
    ("Latch", "Disclosure"),
    ("How Deep Is Your Love", "Calvin Harris"),
    ("Prayer in C", "Robin Schulz"),
    ("Waiting for Love", "Avicii"),
    ("Scared to Be Lonely", "Martin Garrix"),
    ("Feel So Close", "Calvin Harris"),
    ("Hey Brother", "Avicii"),
    ("Language", "Porter Robinson"),
]


@pytest.fixture(scope="module", autouse=True)
def live_settings() -> Iterator[None]:
    """Skip the module when the secrets or the settings cannot be loaded.

    Returns:
        Nothing; yields once the settings are valid and clears the caches afterwards.
    """
    get_settings.cache_clear()
    get_secrets.cache_clear()
    try:
        get_settings()
        get_secrets()
    except ConfigError as exc:
        pytest.skip(f"Spotify integration tests require .env and config/base.toml: {exc}")
    yield
    get_settings.cache_clear()
    get_secrets.cache_clear()


def test_app_token_search_finds_martin_garrix() -> None:
    """The live app token searches the catalog and finds the Martin Garrix track."""
    client = SpotifyClient()
    try:
        items = client.search_tracks(
            auth.get_app_token(), "Animals", "Martin Garrix", get_settings().spotify.market
        )
    finally:
        client.close()
    assert any("Martin Garrix" in [a["name"] for a in item["artists"]] for item in items)


def test_resolution_rate_on_mainstream_hits() -> None:
    """At least 90% of 16 mainstream hits resolve (NFR-05); elapsed time is printed."""
    suggestions = [TrackSuggestion(title=title, artist=artist) for title, artist in HOUSE_HITS]
    started = time.perf_counter()
    resolved = resolve_tracks(suggestions, len(suggestions))
    elapsed = time.perf_counter() - started
    found = [track for track in resolved if track.found]
    missing = [track.name for track in resolved if not track.found]
    budget = f"NFR-02 budget for generation + resolution: {NFR02_BUDGET_S:.0f}s"
    print(f"\nResolved {len(found)}/{len(HOUSE_HITS)} in {elapsed:.2f}s ({budget}); {missing=}")
    assert len(found) / len(HOUSE_HITS) >= NFR05_MIN_RATE
