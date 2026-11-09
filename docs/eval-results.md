# AI Eval Results: Gemini 3.5 Flash-Lite vs Claude Haiku 5.5

**Run:** 9 November 2026, `make eval` on branch `feat/haiku-llm`: 106 cases in 12 min 40 s (93 passed, 12 failed, 1 skipped).
**Engines:** Gemini 3.5 Flash-Lite and Claude Haiku 5.5 (`effort = "low"`, `max_tokens = 8192`, no web search: added after this run), same prompt, schema and guard. Intent gate: Gemma 4 26B. Method and checks: [evals.md](evals.md).

## Summary

| Metric | Gemini 3.5 Flash-Lite | Claude Haiku 5.5 |
| :--- | :--- | :--- |
| Conversation cases passed | **100%** (18/18) | 78% (14/18) |
| Suggestions found on Spotify | 56% (89/158) | **73%** (108/148) |
| Playlists filled to their target size | 38% (3/8) | **62%** (5/8) |
| Latency per call, conversation (p50 / p95) | **2.3 s / 4.5 s** | 5.3 s / 15.5 s |
| Latency per call, existence (p50 / p95) | **3.6 s / 3.9 s** | 6.4 s / 25.5 s |

Intent gate (Gemma 4 26B): 100% of 53 cases (34/34 IN passed, 19/19 OUT blocked), 98% within the app's 3 s budget, no answer other than IN/OUT; 1 case unavailable (Google `500`).

## Failures

**Conversation (Haiku only).** Every other check passed on both engines: parsable output, intent, reply language, size and clamping, criteria, artist constraints, titles, revisions that keep the draft, prompt injection and leak.

| Case | Failed check |
| :--- | :--- |
| `readme-house-example` | `year_range`: a track outside the requested era |
| `remove-one-track`, `add-artist` | `candidates`: revision with fewer than size + 20% candidates |
| `injection-inside-request` | `candidates`: proposal with fewer than size + 20% candidates |

**Existence on Spotify** (found / suggested, target 16, threshold 80%):

| Case | Gemini 3.5 Flash-Lite | Claude Haiku 5.5 |
| :--- | :--- | :--- |
| `bossa-nova` | 15/19 (79%) ✗ | ✓ |
| `city-pop` | 7/20 (35%) ✗ | 3/12 (25%) ✗ |
| `krautrock` | 1/20 (5%) ✗ | 5/20 (25%) ✗ |
| `modern-jazz` | 1/19 (5%) ✗ | 12/16 (75%) ✗ |
| `afrobeat` | 12/20 (60%) ✗ | ✓ |

## Takeaways

- **Haiku invents fewer tracks:** +17 points of suggestions found and 5 playlists out of 8 filled instead of 3. Niche genres (city pop, krautrock) stay hard for both engines.
- **Haiku under-generates at `effort = "low"`:** 3 conversation cases below the size + 20% over-generation, and for city pop only 12 suggestions for a 16-track target, so the playlist can only come out short.
- **Haiku is 2–3× slower:** p95 of 15.5 s per conversation call and 25.5 s on the longest playlists, against 4–5 s for Gemini.
- **Cost not measured:** the engine does not log token usage; the Claude Console Usage page shows the real figure (estimate: a few cents per run).
- **Next step:** rerun the Haiku cases with `effort = "medium"` and compare candidates, existence, latency and cost before choosing the production setting. One run is one sample: confirm a difference across repeated runs.
