# Phase C — Local Verification

**Goal:** prove that the code, the configuration and the live services work together on your machine before anything is deployed.

**Estimated time:** ~30 min (the container build depends heavily on bandwidth).

## C1 — Lint and unit tests (~1 min)

Offline, no credentials needed.
```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
make test-unit
```

## C2 — Integration tests against live services (~2–5 min)

Gemini, Gemma (intent gate), the Spotify catalog and OpenAPI contract, and Firestore, all live.
```bash
make test-integration
```

✅ **Expected:** every test passes and the two smoke tests are **skipped**: they need the `https://` redirect URI that is only set in Phase E.

- A `UserWarning` saying a turn *took more than NFR-01* is a latency warning from Gemini, not a failure.
- The intent-gate tests send about a dozen Gemma requests per run. Gemma's free tier allows 30 requests per minute, so do not rerun them back to back: wait a minute between runs, or the `429`s make the gate fail open and the off-topic tests fail.

## C3 — Manual run (~15 min)

```bash
make run
```

Open **http://127.0.0.1:8501** (never `localhost`: Spotify rejects it and `localStorage` is per-origin) and check:

1. As a guest, request a playlist: 16 tracks with artwork.
2. Ask for 50 tracks: the playlist is capped at 30.
3. Ask something off-topic ("What's the capital of Australia?"): the fixed off-topic reply arrives at once and the terminal logs `Intent gate: OUT`.
4. **Log in with Spotify** with an allowlisted account, confirm **Create on Spotify** and open the link.
5. Reload the page: the chat is restored.
6. **New chat** returns to the landing page.

Stop the server with `Ctrl+C`.

## C4 — Container (~8–10 min on a normal connection)

```bash
make docker-build
make docker-run
```

Open **http://127.0.0.1:8501**: the home page loads and a playlist request works. Stop with `Ctrl+C`.

This local image is built for the host architecture and is only a smoke test of the Dockerfile; the production image is built for `linux/amd64` in Phase D. If `apt-get` fails with *"At least one invalid signature was encountered"* or the build crawls, see [Troubleshooting](deployment-07-troubleshooting.md#docker-build-invalid-signature).

Next: [Phase D — Cloud Run](deployment-04-cloud-run.md).
