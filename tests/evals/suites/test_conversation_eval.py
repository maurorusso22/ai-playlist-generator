"""Conversation eval: deterministic checks on the structured output of the production chain.

Each case runs through `run_turn` (prompt, structured output, guard) with only the model id
swapped; the checks read the LLM's own output, never Spotify data.
"""

import pytest

from src.conversation.chain import AssistantUnavailableError
from tests.evals.harness import report
from tests.evals.harness.cases import ConversationCase, load_cases
from tests.evals.harness.config import models_for
from tests.evals.harness.conversation import run_conversation
from tests.evals.harness.live import ModelUnavailableError, use_model
from tests.evals.harness.turn_checks import evaluate

SUITE = "conversation"  # Section title in the summary
CASES = load_cases("conversations.yaml", ConversationCase)  # Scripted conversations


@pytest.mark.parametrize("model", models_for("llm"))
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_conversation(case: ConversationCase, model: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every expectation of the case holds on the final turn."""
    use_model(monkeypatch, "llm", model)
    try:
        run = run_conversation(case.turns, model)
    except ModelUnavailableError as exc:
        report.record(report.CaseResult(SUITE, model, case.id, "unavailable"))
        pytest.skip(f"{model} unavailable: {exc}")
    except AssistantUnavailableError:  # Unparsable structured output, twice: a model failure
        report.record(report.CaseResult(SUITE, model, case.id, "fail", {"parsable": False}))
        pytest.fail(f"{model} returned unparsable structured output")
    checks = {"parsable": True} | evaluate(run, case.expect)
    failed = [name for name, ok in checks.items() if not ok]
    status: report.Status = "fail" if failed else "pass"
    report.record(report.CaseResult(SUITE, model, case.id, status, checks, run.latencies))
    assert not failed, f"{model} failed {', '.join(failed)} (intent {run.final.intent})"
