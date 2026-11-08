"""Eval settings from config/evals.toml and the model matrix of each suite."""

import tomllib
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from src.config.files import CONFIG_DIR, load_config

EVALS_FILE = CONFIG_DIR / "evals.toml"  # Eval-only settings, never read by the app

Suite = Literal["llm", "intent_gate"]  # config/base.toml section holding the production model


class _Section(BaseModel):
    """Base of every section: immutable, strict types, unknown keys rejected."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class ConversationEvalConfig(_Section):
    """[conversation]: comparison models and the Spotify existence threshold."""

    compare_models: list[str]
    min_resolution_rate: float = Field(ge=0, le=1)


class GateEvalConfig(_Section):
    """[intent_gate]: comparison models and the eval-only client timeout."""

    compare_models: list[str]
    timeout_s: PositiveInt


class RetryConfig(_Section):
    """[retry]: bounded backoff on transient model errors."""

    attempts: PositiveInt
    base_delay_s: PositiveInt


class EvalConfig(_Section):
    """Every eval setting, one attribute per TOML section."""

    conversation: ConversationEvalConfig
    intent_gate: GateEvalConfig
    retry: RetryConfig
    pacing: dict[str, PositiveFloat]  # Model id → minimum seconds between two calls


@lru_cache(maxsize=1)
def get_eval_config() -> EvalConfig:
    """Read and validate config/evals.toml once.

    Returns:
        The validated eval settings.
    """
    with EVALS_FILE.open("rb") as file:
        return EvalConfig.model_validate(tomllib.load(file))


def models_for(suite: Suite) -> list[str]:
    """List the models a suite evaluates: the production model first, then the comparisons.

    Args:
        suite: "llm" for the conversation engine, "intent_gate" for the gate.

    Returns:
        Distinct model ids, production model first; a model without [pacing] raises.
    """
    production = str(load_config()[suite]["model"])
    section = get_eval_config().conversation if suite == "llm" else get_eval_config().intent_gate
    models = list(dict.fromkeys([production, *section.compare_models]))
    unpaced = [model for model in models if model not in get_eval_config().pacing]
    if unpaced:  # Fail at collection: an unpaced model could exceed its free-tier limits
        raise ValueError(f"Add {', '.join(unpaced)} to [pacing] in config/evals.toml")
    return models
