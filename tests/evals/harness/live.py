"""Live model access for the evals: per-test model override, timing and bounded retries.

The override goes through the app's real settings path (`load_config` → `get_settings`), so
every eval exercises the production chain and gate code with only the model id (and, for the
conversation engine, its provider) swapped.
"""

import copy
import random
import time
from collections.abc import Callable

import anthropic
import httpx
import pytest
from google.genai.errors import ClientError, ServerError

from src.config.files import load_config
from src.config.secrets import get_secrets
from src.config.settings import get_settings
from src.guards import intent_gate
from src.llm import claude, gemini
from tests.evals.harness.config import Suite, get_eval_config, llm_engines

RATE_LIMITED = 429  # Quota status, retried with backoff like a server error
MAX_JITTER_S = 2.0  # Random extra delay, so retries never line up with the quota window
APP_GATE_TIMEOUT_S = intent_gate.GATE_TIMEOUT_S  # The app's gate budget, read before patching

_last_call: dict[str, float] = {}  # Model id → monotonic start time of its latest call


class ModelUnavailableError(RuntimeError):
    """Raised when a model keeps failing with transient errors after every attempt."""


def clear_model_caches() -> None:
    """Drop the cached settings and model clients, so the next call reads the current model."""
    for cached in (get_settings, gemini._build_llm, claude._client, intent_gate._build_gate):
        cached.cache_clear()


def use_model(monkeypatch: pytest.MonkeyPatch, suite: Suite, model: str) -> None:
    """Serve the real configuration with one model id replaced, for the current test.

    A Claude model without ANTHROPIC_API_KEY in `.env` skips the test instead of failing it.

    Args:
        monkeypatch: Pytest fixture; the patch is undone after the test.
        suite: Role whose model is replaced; "llm" also selects the model's provider.
        model: Model id to evaluate.
    """
    sections = copy.deepcopy(load_config())  # The files module itself is never patched
    if suite == "llm":
        provider = llm_engines()[model]
        if provider == "claude" and not get_secrets().anthropic_api_key:
            pytest.skip(f"{model} needs ANTHROPIC_API_KEY in .env")
        sections["llm"]["provider"] = provider
        sections[provider]["model"] = model
    else:  # Judge the classifier, not the 3 s budget (reported apart)
        sections["intent_gate"]["model"] = model
        timeout = get_eval_config().intent_gate.timeout_s
        monkeypatch.setattr(intent_gate, "GATE_TIMEOUT_S", float(timeout))
        monkeypatch.setattr(intent_gate, "GATE_SERVER_DEADLINE_S", timeout)
    monkeypatch.setattr("src.config.settings.load_config", lambda *_: sections)
    clear_model_caches()


def _is_transient(exc: BaseException) -> bool:
    """Tell whether an error is worth retrying: 5xx, quota 429, a timeout or a lost connection.

    Claude's monthly spend cap is a 429 too, but it lasts until the next month: not retried.

    Args:
        exc: The raised error; LangChain wraps the SDK error as its cause.

    Returns:
        True for transient errors.
    """
    claude_transient = anthropic.RateLimitError | anthropic.InternalServerError
    for error in (exc, exc.__cause__):
        if isinstance(error, anthropic.EnforcedSpendLimitReachedError):
            return False
        if isinstance(error, claude_transient | anthropic.APIConnectionError):
            return True
        if isinstance(error, ServerError | httpx.TimeoutException | TimeoutError):
            return True
        if isinstance(error, ClientError) and error.code == RATE_LIMITED:
            return True
    return False


def _pace(model: str) -> None:
    """Wait until the model's minimum interval since its previous call has passed.

    Args:
        model: Model id about to be called; its interval comes from [pacing].
    """
    last = _last_call.get(model)
    if last is not None:
        wait = last + get_eval_config().pacing[model] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
    _last_call[model] = time.monotonic()


def timed_with_retry[T](model: str, call: Callable[[], T]) -> tuple[T, float]:
    """Run a paced model call with exponential backoff on transient errors, timing the success.

    Every attempt, retries included, waits for the model's pacing interval first.

    Args:
        model: Model id the call uses.
        call: The model call; any non-transient error propagates unchanged.

    Returns:
        The call's result and the latency of the successful attempt in seconds.
    """
    retry = get_eval_config().retry
    for attempt in range(1, retry.attempts + 1):
        _pace(model)
        started = time.perf_counter()
        try:
            return call(), time.perf_counter() - started
        except Exception as exc:
            if not _is_transient(exc):
                raise
            if attempt == retry.attempts:
                raise ModelUnavailableError(f"{type(exc).__name__}: {exc}"[:160]) from exc
        time.sleep(retry.base_delay_s * 2 ** (attempt - 1) + random.uniform(0, MAX_JITTER_S))
    raise AssertionError("unreachable: the last attempt returns or raises")
