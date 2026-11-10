"""In-memory eval results and the per-model summary printed at the end of the pytest session.

Results hold only check outcomes, counts and latencies: no Spotify content is kept, and the
summary is printed, never written to disk.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import median, quantiles
from typing import Literal

Status = Literal["pass", "fail", "unavailable"]  # Outcome of one case for one model


@dataclass(frozen=True)
class CaseResult:
    """Outcome of one case for one model."""

    suite: str
    model: str
    case_id: str
    status: Status
    checks: dict[str, bool] = field(default_factory=dict)
    latencies: tuple[float, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)


_results: list[CaseResult] = []  # Every recorded case, in run order
_ratios: dict[str, list[tuple[str, str, str]]] = defaultdict(list)  # suite → (label, num, den)


def define_ratio(suite: str, label: str, numerator: str, denominator: str) -> None:
    """Declare a suite metric computed as the sum of two counts over all cases of a model.

    Args:
        suite: Suite name.
        label: Metric label in the summary.
        numerator: Count key summed as numerator.
        denominator: Count key summed as denominator.
    """
    if (label, numerator, denominator) not in _ratios[suite]:
        _ratios[suite].append((label, numerator, denominator))


def record(result: CaseResult) -> None:
    """Store one case outcome.

    Args:
        result: The outcome.
    """
    _results.append(result)


def _share(numerator: int, denominator: int) -> str:
    """Format a ratio as a percentage with its fraction.

    Args:
        numerator: Successes.
        denominator: Attempts.

    Returns:
        E.g. "95% (57/60)", or "n/a" with no attempts.
    """
    return (
        f"{100 * numerator / denominator:.0f}% ({numerator}/{denominator})"
        if denominator
        else "n/a"
    )


def _latency(rows: list[CaseResult]) -> str:
    """Summarize call latencies as median and 95th percentile.

    Args:
        rows: Results of one model.

    Returns:
        E.g. "p50 1.2s, p95 3.4s", or "n/a" without calls.
    """
    values = [v for r in rows for v in r.latencies]
    if not values:
        return "n/a"
    p95 = quantiles(values, n=20)[-1] if len(values) > 1 else values[0]
    return f"p50 {median(values):.1f}s, p95 {p95:.1f}s"


def _model_lines(suite: str, model: str, rows: list[CaseResult]) -> list[str]:
    """Summary lines of one model in one suite.

    Args:
        suite: Suite name.
        model: Model id.
        rows: Results of that model in that suite.

    Returns:
        The headline, the suite metrics and the per-check pass rates.
    """
    judged = [r for r in rows if r.status != "unavailable"]
    passed = sum(r.status == "pass" for r in judged)
    unavailable = len(rows) - len(judged)
    lines = [f"  {model}: cases {_share(passed, len(judged))}, unavailable {unavailable}"]
    lines.append(f"    latency per call: {_latency(judged)}")
    for label, num, den in _ratios[suite]:
        total = (
            sum(r.counts.get(num, 0) for r in judged),
            sum(r.counts.get(den, 0) for r in judged),
        )
        lines.append(f"    {label}: {_share(*total)}")
    names = list(dict.fromkeys(name for r in judged for name in r.checks))
    for name in names:
        outcomes = [r.checks[name] for r in judged if name in r.checks]
        lines.append(f"    check {name}: {_share(sum(outcomes), len(outcomes))}")
    return lines


def summary_lines() -> list[str]:
    """Build the end-of-session summary, suite by suite and model by model.

    Returns:
        Printable lines; empty when no eval ran.
    """
    lines: list[str] = []
    for suite in dict.fromkeys(r.suite for r in _results):
        lines.append(f"[{suite}]")
        rows = [r for r in _results if r.suite == suite]
        for model in dict.fromkeys(r.model for r in rows):
            lines += _model_lines(suite, model, [r for r in rows if r.model == model])
    return lines
