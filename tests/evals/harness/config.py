"""Eval settings from config/evals.toml and the model matrix of each suite."""

import tomllib
from functools import lru_cache
from typing import Literal

from pydantic import Field, PositiveFloat, PositiveInt

from src.config.files import CONFIG_DIR, load_config
from src.config.llm_settings import LlmConfig, Provider
from src.config.sections import Section

EVALS_FILE = CONFIG_DIR / "evals.toml"  # Eval-only settings, never read by the app

Suite = Literal["llm", "intent_gate"]  # Model role under evaluation: chat engine or intent gate


class EvalEngine(Section):
    """A conversation engine to compare: the provider and its model id."""

    provider: Provider
    model: str


class ConversationEvalConfig(Section):
    """[conversation]: comparison engines and the Spotify existence threshold."""

    compare_models: list[EvalEngine]
    min_resolution_rate: float = Field(ge=0, le=1)


class GateEvalConfig(Section):
    """[intent_gate]: comparison models and the eval-only client timeout."""

    compare_models: list[str]
    timeout_s: PositiveInt


class RetryConfig(Section):
    """[retry]: bounded backoff on transient model errors."""

    attempts: PositiveInt
    base_delay_s: PositiveInt


class EvalConfig(Section):
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


def llm_engines() -> dict[str, Provider]:
    """Map every conversation-engine model under evaluation to its provider.

    Returns:
        Model id → provider, the production engine of config/base.toml first.
    """
    sections = load_config()
    provider = LlmConfig.model_validate(sections["llm"]).provider
    production = {str(sections[provider]["model"]): provider}
    return production | {e.model: e.provider for e in get_eval_config().conversation.compare_models}


def models_for(suite: Suite) -> list[str]:
    """List the models a suite evaluates: the production model first, then the comparisons.

    Args:
        suite: "llm" for the conversation engine, "intent_gate" for the gate.

    Returns:
        Distinct model ids, production model first; a model without [pacing] raises.
    """
    if suite == "llm":
        models = list(llm_engines())
    else:
        production = str(load_config()["intent_gate"]["model"])
        models = list(dict.fromkeys([production, *get_eval_config().intent_gate.compare_models]))
    unpaced = [model for model in models if model not in get_eval_config().pacing]
    if unpaced:  # Fail at collection: an unpaced model could exceed its rate limits
        raise ValueError(f"Add {', '.join(unpaced)} to [pacing] in config/evals.toml")
    return models
