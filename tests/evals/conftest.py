"""Shared eval fixtures: live credentials check, fresh model clients and the final summary.

The evals call the real Gemini, Gemma and Spotify APIs, so they never run in CI or in
`make test`; run them with `make eval` (see README "AI evals").
"""

from collections.abc import Iterator

import pytest

from src.config.errors import ConfigError
from src.config.secrets import get_secrets
from src.config.settings import get_settings
from tests.evals.harness import report
from tests.evals.harness.live import clear_model_caches


@pytest.fixture(scope="session", autouse=True)
def live_credentials() -> Iterator[None]:
    """Skip the whole run when `.env` or config/base.toml are incomplete.

    Returns:
        Nothing; yields once the secrets and the settings load.
    """
    clear_model_caches()
    get_secrets.cache_clear()
    try:
        get_settings()
        get_secrets()
    except ConfigError as exc:
        pytest.skip(f"AI evals require .env and config/base.toml: {exc}")
    yield
    clear_model_caches()


@pytest.fixture(autouse=True)
def fresh_model_clients() -> Iterator[None]:
    """Drop cached settings and clients after each case, once its model patch is undone.

    Returns:
        Nothing; yields during the test.
    """
    yield
    clear_model_caches()


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print the per-suite, per-model eval summary after the test report.

    Args:
        terminalreporter: Pytest's terminal reporter.
    """
    lines = report.summary_lines()
    if lines:
        terminalreporter.section("AI eval summary")
        for line in lines:
            terminalreporter.write_line(line)
