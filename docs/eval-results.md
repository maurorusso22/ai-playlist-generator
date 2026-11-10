# AI Eval Results: Gemini 3.5 Flash-Lite vs Claude Haiku 5.5 vs Haiku 5.5 with Web Search

| Run | Command | Engines | Result |
| :--- | :--- | :--- | :--- |
| 1, 9 November 2026 | `make eval` | Gemini 3.5 Flash-Lite, Claude Haiku 5.5 **without** web search, Gemma 4 26B gate | 106 cases in 12 min 40 s: 93 passed, 12 failed, 1 skipped |
| 2, 10 November 2026 | `make eval EVAL="tests/evals -k haiku"` | Claude Haiku 5.5 **with** web search (direct calls, at most 3 per reply, Spotify domains blocked) | 26 cases in 4 min 58 s: 17 passed, 9 failed |

Both Haiku runs use `effort = "low"` and `max_tokens = 8192`; every engine gets the same prompt (plus the search rules in run 2), schema and guard. Method and checks: [evals.md](evals.md).

## Summary

| Metric | Gemini 3.5 Flash-Lite | Haiku 5.5 | Haiku 5.5 + web search |
| :--- | :--- | :--- | :--- |
| Conversation cases passed | **100%** (18/18) | 78% (14/18) | 78% (14/18) |
| Suggestions found on Spotify | 56% (89/158) | **73%** (108/148) | 71% (114/160) |
| Playlists filled to their target size | 38% (3/8) | **62%** (5/8) | 38% (3/8) |
| Latency per call, conversation (p50 / p95) | **2.3 s / 4.5 s** | 5.3 s / 15.5 s | 5.8 s / 16.7 s |
| Latency per call, existence (p50 / p95) | **3.6 s / 3.9 s** | 6.4 s / 25.5 s | 6.1 s / 24.5 s |

Intent gate (Gemma 4 26B, run 1): 100% of 53 cases (34/34 IN passed, 19/19 OUT blocked), 98% within the app's 3 s budget, no answer other than IN/OUT; 1 case unavailable (Google `500`).

## Failures

**Conversation.** Gemini passed every case. On Haiku every other check passed in both runs: parsable output, intent, reply language, size and clamping, criteria, titles, revisions that keep the draft, prompt injection and leak.

| Case | Haiku 5.5 | Haiku 5.5 + web search |
| :--- | :--- | :--- |
| `readme-house-example` | `year_range` ✗ | ✓ |
| `clarify-then-answer`, `oversized-request` | ✓ | `candidates` ✗ |
| `remove-one-track` | `candidates` ✗ | `candidates` ✗ |
| `add-artist` | `candidates` ✗ | `includes_artists` ✗ |
| `injection-inside-request` | `candidates` ✗ | ✓ |

`candidates`: fewer than size + 20% candidates; `year_range`: a track outside the requested era; `includes_artists`: a requested artist missing.

**Existence on Spotify** (found / suggested, target 16, threshold 80%):

| Case | Gemini 3.5 Flash-Lite | Haiku 5.5 | Haiku 5.5 + web search |
| :--- | :--- | :--- | :--- |
| `bossa-nova` | 15/19 (79%) ✗ | ✓ | 14/20 (70%) ✗ |
| `city-pop` | 7/20 (35%) ✗ | 3/12 (25%) ✗ | 3/20 (15%) ✗ |
| `krautrock` | 1/20 (5%) ✗ | 5/20 (25%) ✗ | 12/20 (60%) ✗ |
| `modern-jazz` | 1/19 (5%) ✗ | 12/16 (75%) ✗ | 15/20 (75%) ✗ |
| `afrobeat` | 12/20 (60%) ✗ | ✓ | 15/20 (75%) ✗ |

## Takeaways

- **Haiku invents fewer tracks than Gemini:** 71–73% of suggestions found against 56%. Niche genres (city pop, krautrock) stay hard for every engine.
- **Web search does not change these suites:** the datasets hold no recent-release requests, and the rules forbid searching for genres and moods, so run 2 likely ran few or no searches (the log does not record the count). The shifts between the two Haiku runs (bossa nova and afrobeat just under 80%, krautrock up from 25% to 60%) are within run-to-run noise.
- **Where web search matters:** in a manual test ("latest album of Olivia Rodrigo and Sweet II by Jack Harlow"), Haiku without search fell back to older albums; with search it found both new releases and their tracklists.
- **Haiku still under-generates at `effort = "low"`:** 3 conversation cases below size + 20% in each run. In run 2 every existence playlist had 20 suggestions for 16 tracks.
- **Haiku is 2–3× slower:** p95 of 15–17 s per conversation call and about 25 s on the longest playlists, against 4–5 s for Gemini.
- **Cost not measured:** the engine does not log token usage; the Claude Console Usage page shows the real figure.
- **Next steps:** add eval cases for recent and named releases to measure web search, log the search count per case, and rerun Haiku with `effort = "medium"` for the under-generation. One run is one sample: confirm a difference across repeated runs.
