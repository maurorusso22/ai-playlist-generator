# Phase F — Acceptance Tests in Production

**Goal:** confirm the user-facing behaviour, the guardrails and the cost controls on the canonical URL.

**Estimated time:** ~35 min of hands-on work plus ~20 min of idle wait for the cold-start test.

## F1 — End-to-end flow (~20 min)

On `YOUR_CLOUD_RUN_URL/`:

1. As a guest, request a playlist: 16 tracks with artwork. Ask for 50: capped at 30.
2. Ask something off-topic: the fixed off-topic reply arrives at once.
3. **Log in with Spotify** with an allowlisted account → **Create on Spotify** → open the link: the playlist exists and is private.
4. Close and reopen the browser within the session lifetime (60 min): the chat is restored.
5. **New chat** returns to the landing page and the session document disappears from Firestore (Firestore console → `sessions`).

This is the only check that exercises the production redirect URI. In the logs it shows up as a `POST https://accounts.spotify.com/api/token` (code exchange) followed by `GET /v1/me`, `POST /v1/me/playlists` and `POST /v1/playlists/{id}/items`.

## F2 — Rate limit (~3 min)

Send 13 messages within one minute. Use **off-topic** messages ("capital of France?"): the intent gate answers them in under a second without calling Gemini, so the test is fast and spends no Gemini quota.

✅ **Expected:** 12 messages are processed and the 13th is refused. The limiter runs before the gate, so the logs show 12 gate decisions in that minute and nothing for the 13th.

## F3 — Clean logs (~1 min)

```bash
gcloud run services logs read playlist-generator --region=us-central1 --project=YOUR_PROJECT_ID --limit=300 | grep -iE "traceback|error|access_token|refresh_token|bearer"
```

✅ **Expected:** no tracebacks and no tokens. Known benign matches:

- `GET 200 …/static/js/ErrorElement.*.js` and `ErrorOutline.*.js`: Streamlit asset names, not errors.
- `Intent gate failed open (…)` warnings: the gate let a message through after a Gemma error (`500`, `429`, timeout). This is the designed behaviour: Gemini still declines off-topic requests. Occasional bursts of Gemma `500 INTERNAL` are transient on Google's side.

## F4 — Cold start (~20 min idle, 1 min active)

Close every tab of the app and wait about 20 minutes, until the instance has scaled to zero. Then:
```bash
curl -o /dev/null -s -w '%{time_total}\n' YOUR_CLOUD_RUN_URL/_stcore/health
```

✅ **Expected:** under 5 seconds (NFR-07).

## F5 — Billing budget (~5 min)

In the Cloud console: **Billing** → your billing account → **Budgets & alerts** → **Create budget**. Scope it to `YOUR_PROJECT_ID`, set a small amount (e.g. 1 €) and alert thresholds at 50%, 90% and 100%.

The main free-tier risk is open tabs: each Streamlit tab keeps a WebSocket request, and therefore a billable instance, alive. Keep an eye on Cloud Run billable instance time in the first weeks (see [Cost Optimization Strategy](../README.md#cost-optimization-strategy)).

## Done

The deployment is complete when F1–F5 pass. Remaining issues and their fixes are collected in [Troubleshooting](deployment-07-troubleshooting.md).
