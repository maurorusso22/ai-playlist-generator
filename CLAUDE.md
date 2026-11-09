# AI Playlist Generator

Conversational playlist builder: Streamlit + Gemini (Google AI Studio) + Spotify Web API, on the GCP Free Tier (Cloud Run, Firestore, Terraform).

- `README.md` describes the system as designed (requirements, architecture, deployment).
- `docs/plan.md` is the phased implementation plan (local only, git-ignored). Follow its phases, file names and decisions.

## Project invariants

- **Spotify data never reaches the LLM.** The prompt contains only conversation text and the LLM's own previous draft (title/artist pairs it generated). Resolved Spotify data is used only for display and playlist creation. The Claude engine's web search blocks Spotify domains.
- **No side effect without a click.** The LLM's only tool is the Claude engine's read-only web search, run server-side by Anthropic; a playlist is created only when the user clicks "Create on Spotify".
- **Playlist size:** 16 tracks by default, otherwise the user's number N, always clamped in Python to 1 ≤ N ≤ 30.

## Spotify Web API rules

- **OpenAPI spec:** use the Spotify OpenAPI specification at https://developer.spotify.com/reference/web-api/open-api-schema.yaml for all endpoint paths, parameters and response schemas. Do not guess endpoints or field names.
- **Authorization:** Authorization Code flow on the backend for user data (the client secret stays on the server); Client Credentials only for public catalog data. Never use the Implicit Grant flow (deprecated). PKCE (https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow) is the alternative for clients without a secure backend.
- **Redirect URIs:** HTTPS only, except `http://127.0.0.1` for local development. Never `http://localhost` or wildcard URIs. See https://developer.spotify.com/documentation/web-api/concepts/redirect_uri.
- **Scopes:** request only the minimum scopes (https://developer.spotify.com/documentation/web-api/concepts/scopes). The app requests `playlist-modify-private` only; do not add scopes preemptively.
- **Token management:** store tokens encrypted (Fernet), never log them, never expose the Client Secret in client-side code. Refresh tokens before expiry (https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens) and send the user through authorization again when the refresh token is rejected (`invalid_grant`).
- **Rate limits:** on HTTP 429, respect the `Retry-After` header, otherwise use exponential backoff with jitter. Bounded retries; never retry immediately or in tight loops.
- **Deprecated endpoints:** do not use them. Use `/playlists/{id}/items` (not `/playlists/{id}/tracks`), `POST /me/playlists` (not `/users/{id}/playlists`), and `/me/library` over the type-specific library endpoints.
- **Error handling:** handle every HTTP error status documented in the OpenAPI schema (`400`, `401`, `403`, `404`, `429`) plus `5xx`. Read the returned `error.message` and use it to give the user meaningful, escaped feedback.
- **Developer Terms:** comply with https://developer.spotify.com/terms. Do not cache Spotify content beyond what is needed for immediate use (no cross-request search cache), always attribute content to Spotify, and never use Spotify data to train or feed ML/AI models.
