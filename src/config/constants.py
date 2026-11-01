"""Application-wide constants: fixed by design, so neither configuration nor secrets."""

PLAYLIST_MIN_SIZE = 1  # Smallest playlist the app builds (fixed, not configurable)
PLAYLIST_HARD_MAX_SIZE = 30  # Absolute size cap: playlist.max_size may lower it, never raise it
OVERGENERATION_RATIO = 0.2  # Extra LLM candidates per requested track, absorbing not-found ones
MAX_STORED_MESSAGES = 50  # Messages kept per session document (Firestore 1 MiB limit)
SESSION_ID_STORAGE_KEY = "apg_session_id"  # localStorage key holding the session id
SPOTIFY_SCOPE = "playlist-modify-private"  # The only OAuth scope the app requests
