# AI Evals

Unit and integration tests check that the software behaves as specified: parsing, size clamping, fallbacks, error mapping. They cannot tell whether the models do their job well. The evals in `tests/evals/` measure that: a fixed set of cases runs through the **production code paths** on the **live models**, each case is scored by deterministic checks, and a per-model summary makes a prompt or model change comparable with a number instead of an impression.

## How to run

```bash
# Every suite, every model (production model first, then the ones in config/evals.toml)
make eval

# One suite
make eval EVAL=tests/evals/suites/test_gate_eval.py

# One case on one model
.venv/bin/python -m pytest tests/evals -v -k "resize-draft and flash"
```

Requirements: a complete `.env` and `config/base.toml`, as for the integration tests; the Claude cases also need `ANTHROPIC_API_KEY` in `.env` and are skipped without it. The evals never run in CI or in `make test`: they spend free-tier quota on Google AI Studio and real credit on the Claude API.

## Design

- **Production code, one swap.** `harness/live.py` serves the real configuration through the app's own `load_config` → `get_settings` path with only the model id replaced (and, for the conversation engine, `llm.provider` with it), so the system prompt, the structured-output schema, the deterministic guard and the resolver are exactly the ones users hit.
- **Model matrix.** The production models in `config/base.toml` are always evaluated; `config/evals.toml` lists the comparison models: Claude Haiku 5.5 for the conversation engine, each entry with its provider; none for the gate, which stays on Gemma.
- **Failures vs unavailability.** Free-tier models return `429`, `500` and `503` under load, Claude `429` and `529` (overloaded). Those are retried with exponential backoff and jitter (`[retry]` in `config/evals.toml`); a case that still fails is reported as *unavailable* and excluded from the pass rate, so infrastructure noise is never counted as a wrong answer. Claude's monthly spend cap is a `429` too but is not retried: it lasts until the next month. Unparsable structured output, on the other hand, is a model failure.
- **Pacing under the rate limits.** See [Rate limits](#rate-limits) below.
- **Datasets in YAML** (`tests/evals/datasets/`), validated by Pydantic schemas that reject unknown keys, so a misspelled expectation fails loudly instead of being silently skipped.
- **Report.** Each case is a pytest test (failures name the checks that failed); the end-of-session summary prints, per suite and per model, the pass rate, the latency per call (p50/p95), the suite metrics and the pass rate of every check.

## Rate limits

The evals call the models one at a time, so without a floor the pace is set by the model's own latency: the gate eval on Gemma 4 26B (about 1 s per answer) reached **34 requests per minute against a limit of 30**. The 429 retries absorbed it, but a run that only works thanks to retries also burns quota on rejected calls and can starve the app if it shares the project. `[pacing]` in `config/evals.toml` therefore sets a minimum interval between the starts of two calls to the same model, sized on its limits (free tier on Google AI Studio, usage tier on the Claude API):

| Model | Limits | Tokens per call (input) | Interval | Resulting pace |
| :--- | :--- | :--- | :--- | :--- |
| Gemma 4 26B (gate) | 30 RPM, 16K TPM | ~350 | 2.5 s | ≤ 24 RPM, ≤ ~8K TPM |
| Gemini 3.5 Flash-Lite | 15 RPM, 250K TPM | ~1.4K, up to ~2.5K in a revision | 5 s | ≤ 12 RPM |
| Claude Haiku 5.5 | Start tier: 4,000 RPM, 2M ITPM, 400K OTPM | similar (own tokenizer) | 1 s | ≤ 60 RPM |

- **Why a margin below the limit.** One paced call can hide more than one request: `run_turn` retries an unparsable reply once and the SDK retries once on errors, and Google counts the minute in its own window. Claude's 1 s interval sits far below the Start tier because new organizations may begin on a lower Evaluation tier.
- **Cost of the Claude cases.** Claude is billed per token (Haiku 5.5: $0.10 per million input tokens and $0.50 per million output tokens for prompts up to 100K tokens), thinking included. A full run makes about 32 Claude calls of a few thousand tokens each, an estimate of a few cents; the Console's Usage page shows the real figure.
- **Daily limits.** A full run makes about 32 conversation-engine calls per model (24 conversation turns and 8 existence requests) and 54 gate calls per gate model: about 6% of Flash-Lite's 500 requests a day, which the deployed app shares when the key belongs to the same project. Run the evals deliberately, not in a loop.
- **One process per model.** Pacing is kept in memory per process: two processes may run in parallel on different models (each has its own quota), never on the same one.
- **Running one engine only.** Select cases by model id, e.g. `-k "haiku"` for Claude or `-k "flash"` for Gemini.

## Suites

### 1. Intent gate — classification

`test_gate_eval.py` sends 54 messages, labeled by the gate's own lenient policy (35 IN, 19 OUT), to `intent_gate.classify`: the same prompt and framing as production, without the fail-open wrapper, so a failed call is told apart from a verdict. Messages cover requests in five languages, moods and activities, small talk, short follow-ups judged with the assistant's last reply, mixed topics and prompt injection.

| Metric | Why it matters |
| :--- | :--- |
| IN passed | A blocked music request breaks the product: must stay ~100%. |
| OUT blocked | A missed off-topic message only costs one conversation-engine call (and the engine still declines it). |
| Calls within the app's 3 s budget | The eval uses a long timeout to judge the classifier; in the app a slower call fails open, which silently turns the gate off. |
| Answers other than IN/OUT | Format drift: the app treats them as IN. |

### 2. Conversation — deterministic checks on structured output

`test_conversation_eval.py` runs 18 scripted conversations (1–2 turns) through `chain.run_turn`, threading history and draft exactly like `src/ui/turn.py`. The checks read only the LLM's own output:

| Check | Example case |
| :--- | :--- |
| `intent` | "Make me a playlist" → `clarify`; "Rename it to …" → `revise_playlist` |
| `candidates` (always on) | Every playlist holds `size + 20%` candidates, so not-found tracks can be replaced |
| `criteria` | "rock anni '90" → genres contain *rock*, years contain *90* |
| `target_size` | 10 when asked, 16 by default, 30 for "50 songs" or "100 songs" |
| `includes_artists` / `excludes_artists` / `only_artists` | "niente Nirvana", "only by The Beatles" |
| `year_range` | Era constraints, on the years the model reports for its own tracks |
| `title`, `title_unchanged` | User-given names kept verbatim; title stable across revisions |
| `keeps_previous`, `excludes_titles` | A revision changes only what was asked: at least 80% of the rest of the draft survives |
| `language` | The reply is in the user's language (Italian, English, Spanish) |
| `message_contains` / `message_excludes` | The reply mentions the 30-track cap; no system-prompt fragment leaks |

### 3. Existence on Spotify — invented tracks

`test_existence_eval.py` asks for 8 playlists, from mainstream hits to niche genres where invented tracks are more likely (Japanese city pop, krautrock deep cuts, Nigerian afrobeat), and looks every suggestion up with the app's resolver.

| Metric | Threshold |
| :--- | :--- |
| Suggestions found | ≥ 80% per playlist (`min_resolution_rate`) |
| Playlists filled to their target size | Found tracks ≥ target size |

**Spotify Developer Terms.** The lookup is the same catalog search the app runs for every playlist (Client Credentials, public data, bounded retries with `Retry-After`). The resolved tracks are discarded as soon as they are counted: the eval keeps two integers per case, stores and caches nothing, and no Spotify data ever reaches an LLM, because the model has already answered when the search runs.

## Limitations

- **Non-determinism.** One run is one sample: a single case flipping between runs is noise; trends across the whole suite and repeated runs are the signal.
- **Self-reported years.** `year_range` checks the years the model gives for its own tracks, so it measures consistency with the constraint, not historical truth.
- **Heuristic language detection.** A stopword count, reliable for the replies in the datasets, not a general language identifier.
- **No subjective quality yet.** Coherence of mood, variety and flow are not measured; the natural next step is an LLM-as-judge with a rubric and pairwise comparison between prompt versions, calibrated against a small set of human judgments (fed only the request and the LLM's own title/artist list, never Spotify data).
