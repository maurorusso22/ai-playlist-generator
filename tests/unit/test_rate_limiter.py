"""Unit tests for src/rate_limiter.py (defaults: 12 messages per sliding 60 s per IP)."""

from collections.abc import Iterator

import pytest
from pytest_mock import MockerFixture

from src import rate_limiter
from src.config.files import Sections
from src.config.settings import get_settings
from src.rate_limiter import get_client_ip, is_rate_limited

LIMIT = 12  # rate_limit.max_requests in config/base.toml
WINDOW = 60.0  # rate_limit.window in config/base.toml, in seconds


@pytest.fixture(autouse=True)
def clock(mocker: MockerFixture) -> Iterator[list[float]]:
    """Drive the limiter's monotonic clock by hand and start from an empty log.

    Args:
        mocker: Pytest-mock fixture.

    Returns:
        A one-item list holding the current time; tests advance it by assigning `clock[0]`.
    """
    now = [1000.0]
    mocker.patch("src.rate_limiter.time").monotonic.side_effect = lambda: now[0]
    rate_limiter._request_log.cache_clear()
    yield now
    rate_limiter._request_log.cache_clear()


def _headers(mocker: MockerFixture, forwarded: str | None) -> None:
    """Fake the request's X-Forwarded-For header.

    Args:
        mocker: Pytest-mock fixture.
        forwarded: Header value, or None when absent.
    """
    fake = mocker.patch("src.rate_limiter.st")
    fake.context.headers.get.side_effect = lambda name: (
        forwarded if name == "X-Forwarded-For" else None
    )


def test_twelfth_request_is_allowed_and_thirteenth_blocked() -> None:
    """Twelve messages in the window are allowed; the 13th is blocked."""
    assert [is_rate_limited("1.2.3.4") for _ in range(LIMIT)] == [False] * LIMIT
    assert is_rate_limited("1.2.3.4") is True


def test_ips_are_tracked_independently() -> None:
    """Each IP has its own log."""
    for _ in range(LIMIT):
        is_rate_limited("1.1.1.1")
    assert is_rate_limited("1.1.1.1") is True
    assert is_rate_limited("2.2.2.2") is False


def test_window_slides_one_slot_per_expired_message(clock: list[float]) -> None:
    """A slot frees up exactly when the oldest counted message is one window old."""
    start = clock[0]
    for second in range(LIMIT):
        clock[0] = start + second
        is_rate_limited("1.2.3.4")
    clock[0] = start + WINDOW - 0.001
    assert is_rate_limited("1.2.3.4") is True
    clock[0] = start + WINDOW
    assert is_rate_limited("1.2.3.4") is False
    assert is_rate_limited("1.2.3.4") is True
    clock[0] = start + WINDOW + 1
    assert is_rate_limited("1.2.3.4") is False


def test_no_burst_at_window_boundary(clock: list[float]) -> None:
    """Twelve messages late in one minute leave no room early in the next."""
    clock[0] += WINDOW - 1
    for _ in range(LIMIT):
        is_rate_limited("1.2.3.4")
    clock[0] += 2
    assert is_rate_limited("1.2.3.4") is True


def test_blocked_messages_do_not_extend_the_block(clock: list[float]) -> None:
    """Retries while blocked are not counted, so the block ends one window after the burst."""
    for _ in range(LIMIT):
        is_rate_limited("1.2.3.4")
    for _ in range(5):
        clock[0] += 10
        assert is_rate_limited("1.2.3.4") is True
    clock[0] += 10
    assert is_rate_limited("1.2.3.4") is False


def test_steady_slow_traffic_is_never_blocked(clock: list[float]) -> None:
    """One message every 50 s stays under the limit forever (no counter build-up)."""
    for _ in range(3 * LIMIT):
        clock[0] += 50
        assert is_rate_limited("1.2.3.4") is False


def test_idle_ip_entry_expires(clock: list[float]) -> None:
    """An IP's entry is evicted one window after its latest message."""
    is_rate_limited("10.0.0.1")
    assert "10.0.0.1" in rate_limiter._request_log()
    clock[0] += WINDOW + 1
    assert "10.0.0.1" not in rate_limiter._request_log()


def test_window_and_limit_come_from_settings(config: Sections) -> None:
    """The limit and the window come from the settings."""
    config["rate_limit"] |= {"max_requests": 2, "window": 5}
    get_settings.cache_clear()
    assert [is_rate_limited("9.9.9.9") for _ in range(3)] == [False, False, True]
    assert rate_limiter._request_log().ttl == 5


def test_client_ip_is_the_right_most_forwarded_entry(mocker: MockerFixture) -> None:
    """The right-most X-Forwarded-For entry is the client IP."""
    _headers(mocker, "1.2.3.4, 203.0.113.7")
    assert get_client_ip() == "203.0.113.7"


def test_forwarded_entries_are_stripped(mocker: MockerFixture) -> None:
    """Whitespace around X-Forwarded-For entries is stripped."""
    _headers(mocker, " 1.2.3.4 ,  203.0.113.7  ")
    assert get_client_ip() == "203.0.113.7"


@pytest.mark.parametrize("forwarded", [None, " , "])
def test_missing_or_blank_header_falls_back_to_loopback(
    mocker: MockerFixture, forwarded: str | None
) -> None:
    """Without a usable header the loopback address is used."""
    _headers(mocker, forwarded)
    assert get_client_ip() == "127.0.0.1"
