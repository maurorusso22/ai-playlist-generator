"""Per-IP sliding-window rate limiting of chat messages, kept in memory (FR-14).

Each IP keeps the timestamps of its counted messages, so at most `rate_limit.max_requests`
messages are allowed in any `rate_limit.window` seconds, with no burst at window boundaries.
The log lives at module level, so it persists across Streamlit reruns and sessions of the
same process; with Cloud Run `max-instances = 1` a single process serves all traffic, so no
shared store is needed. It is created lazily because settings are never read at import time.
"""

import threading
import time
from collections import deque
from functools import lru_cache

import streamlit as st
from cachetools import TTLCache

from src.config.settings import get_settings

MAX_TRACKED_IPS = 10_000  # Distinct client IPs tracked at once; the oldest are evicted
FALLBACK_IP = "127.0.0.1"  # Client IP assumed when no X-Forwarded-For header is present

_lock = threading.Lock()  # Streamlit sessions run in separate threads; TTLCache is not safe


@lru_cache(maxsize=1)
def _request_log() -> TTLCache[str, deque[float]]:
    """Create the per-IP log of message timestamps with the configured window (once).

    An entry expires one window after its latest counted message, when every timestamp in it
    is stale anyway, so idle IPs free their memory without a cleanup job.

    Returns:
        A TTL cache mapping client IP to the monotonic times of its counted messages.
    """
    return TTLCache(
        maxsize=MAX_TRACKED_IPS, ttl=get_settings().rate_limit.window, timer=time.monotonic
    )


def is_rate_limited(ip: str) -> bool:
    """Count a chat message for `ip` unless it would exceed the sliding-window limit.

    Blocked messages are not counted, so a client that keeps retrying gets through as soon as
    its oldest counted message leaves the window.

    Args:
        ip: Client IP address.

    Returns:
        True when `ip` already sent `rate_limit.max_requests` messages in the last window.
    """
    settings = get_settings()
    with _lock:
        log = _request_log()
        now = time.monotonic()
        stamps = log.get(ip, deque())
        while stamps and now - stamps[0] >= settings.rate_limit.window:
            stamps.popleft()
        if len(stamps) >= settings.rate_limit.max_requests:
            return True
        stamps.append(now)
        log[ip] = stamps  # Re-set so the entry expires one window after this message
        return False


def get_client_ip() -> str:
    """Extract the client IP from the request's X-Forwarded-For header.

    Google's front end appends the address it sees as the right-most entry; left-most
    entries are client-controlled, so trusting them would give a spoofer a fresh bucket
    per message.

    Returns:
        The right-most X-Forwarded-For entry, or FALLBACK_IP when the header is absent.
    """
    forwarded = st.context.headers.get("X-Forwarded-For")
    entries = [entry.strip() for entry in (forwarded or "").split(",") if entry.strip()]
    return entries[-1] if entries else FALLBACK_IP
