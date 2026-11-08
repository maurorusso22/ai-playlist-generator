"""Intent-gate eval: IN/OUT classification quality per model, plus latency against the app budget.

A blocked IN message breaks the product, a missed OUT costs one Gemini call: the summary
reports both rates apart, and the share of calls that would fit the app's 3 s timeout.
"""

import pytest

from src.guards import intent_gate
from src.models.session.chat_message import ChatMessage
from tests.evals.harness import report
from tests.evals.harness.cases import GateCase, load_cases
from tests.evals.harness.config import models_for
from tests.evals.harness.live import (
    APP_GATE_TIMEOUT_S,
    ModelUnavailableError,
    timed_with_retry,
    use_model,
)

SUITE = "intent gate"  # Section title in the summary
CASES = load_cases("gate.yaml", GateCase)  # Labeled messages

report.define_ratio(SUITE, "IN passed (must be ~100%)", "in_ok", "in_total")
report.define_ratio(SUITE, "OUT blocked", "out_ok", "out_total")
report.define_ratio(
    SUITE, f"calls within the app's {APP_GATE_TIMEOUT_S:.0f} s budget", "fast", "calls"
)
report.define_ratio(SUITE, "answers other than IN/OUT", "odd", "calls")


@pytest.mark.parametrize("model", models_for("intent_gate"))
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_gate(case: GateCase, model: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate blocks exactly the OUT messages."""
    use_model(monkeypatch, "intent_gate", model)
    history = [ChatMessage(role="assistant", content=case.context)] if case.context else []
    try:
        word, latency = timed_with_retry(model, lambda: intent_gate.classify(case.text, history))
    except ModelUnavailableError as exc:
        report.record(report.CaseResult(SUITE, model, case.id, "unavailable"))
        pytest.skip(f"{model} unavailable: {exc}")
    passed = (word == intent_gate.BLOCK_WORD) == (case.label == "OUT")
    label = case.label.lower()
    counts = {
        f"{label}_total": 1,
        f"{label}_ok": int(passed),
        "calls": 1,
        "fast": int(latency <= APP_GATE_TIMEOUT_S),
        "odd": int(word not in (intent_gate.ALLOW_WORD, intent_gate.BLOCK_WORD)),
    }
    status: report.Status = "pass" if passed else "fail"
    report.record(report.CaseResult(SUITE, model, case.id, status, {}, (latency,), counts))
    assert passed, f"{model} answered {word or '(nothing)'!r} to a {case.label} message"
