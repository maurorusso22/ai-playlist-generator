"""Existence eval: share of each model's suggestions that the app's resolver finds on Spotify.

Spotify Developer Terms: the lookup is the app's own catalog search (Client Credentials,
public data, bounded retries). Only two counts survive the call: the resolved tracks are
discarded at once, nothing is stored or cached, and no Spotify data ever reaches an LLM
(the model has already answered when the search runs).
"""

import pytest

from src.conversation.chain import AssistantUnavailableError
from src.spotify.resolver import resolve_tracks
from tests.evals.harness import report
from tests.evals.harness.cases import ExistenceCase, load_cases
from tests.evals.harness.config import get_eval_config, models_for
from tests.evals.harness.conversation import run_conversation
from tests.evals.harness.live import ModelUnavailableError, use_model

SUITE = "existence on Spotify"  # Section title in the summary
CASES = load_cases("existence.yaml", ExistenceCase)  # Requests from mainstream to niche

report.define_ratio(SUITE, "suggestions found", "found", "suggested")
report.define_ratio(SUITE, "playlists filled to target size", "filled", "playlists")


def _found_count(model: str, case: ExistenceCase) -> tuple[int, int, int, tuple[float, ...]]:
    """Generate a draft and count how many of its suggestions resolve on Spotify.

    Args:
        model: Model id under evaluation.
        case: The request.

    Returns:
        Found suggestions, suggested tracks, target size and the LLM latencies.
    """
    run = run_conversation([case.request], model)
    playlist = run.final.playlist
    assert playlist is not None, f"{model} returned no playlist (intent {run.final.intent})"
    found = len(resolve_tracks(playlist.tracks, len(playlist.tracks)))  # Kept as a count only
    return found, len(playlist.tracks), playlist.target_size, run.latencies


@pytest.mark.parametrize("model", models_for("llm"))
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_existence(case: ExistenceCase, model: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Enough suggestions exist on Spotify to fill the playlist to its target size."""
    use_model(monkeypatch, "llm", model)
    try:
        found, suggested, size, latencies = _found_count(model, case)
    except ModelUnavailableError as exc:
        report.record(report.CaseResult(SUITE, model, case.id, "unavailable"))
        pytest.skip(f"{model} unavailable: {exc}")
    except AssistantUnavailableError:
        report.record(report.CaseResult(SUITE, model, case.id, "fail", {"parsable": False}))
        pytest.fail(f"{model} returned unparsable structured output")
    rate = found / suggested
    checks = {
        "resolution_rate": rate >= get_eval_config().conversation.min_resolution_rate,
        "filled": found >= size,
    }
    counts = {"found": found, "suggested": suggested, "filled": int(found >= size), "playlists": 1}
    passed = all(checks.values())
    status: report.Status = "pass" if passed else "fail"
    report.record(report.CaseResult(SUITE, model, case.id, status, checks, latencies, counts))
    assert passed, f"{model}: {found}/{suggested} found ({rate:.0%}), target {size}"
