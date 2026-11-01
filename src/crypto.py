"""Fernet encryption of Spotify tokens at rest (the session's `spotify_auth` field)."""

import json

from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError

from src.config.errors import ConfigError
from src.config.secrets import get_secrets
from src.schema import SpotifyTokens


def _fernet() -> Fernet:
    """Build the cipher from `SESSION_ENCRYPTION_KEY`.

    Returns:
        A Fernet instance keyed with the configured secret.
    """
    try:
        return Fernet(get_secrets().session_encryption_key)
    except ValueError:
        # binascii.Error (bad base64) subclasses ValueError; the key itself is never echoed.
        raise ConfigError(
            "SESSION_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64-encoded bytes)"
        ) from None


def encrypt_tokens(tokens: SpotifyTokens) -> str:
    """Serialize and encrypt a user's Spotify tokens.

    `model_dump()` masks SecretStr values, so the secrets are revealed explicitly here and
    only ever exist in plaintext inside the encrypted payload.

    Args:
        tokens: The tokens and profile fields to protect.

    Returns:
        An opaque Fernet token (ASCII) safe to store in Firestore.
    """
    payload = tokens.model_dump(mode="json")
    payload["access_token"] = tokens.access_token.get_secret_value()
    payload["refresh_token"] = tokens.refresh_token.get_secret_value()
    blob: bytes = _fernet().encrypt(json.dumps(payload).encode())
    return blob.decode()


def decrypt_tokens(blob: str) -> SpotifyTokens | None:
    """Decrypt a blob produced by `encrypt_tokens`.

    A blob encrypted with another key (e.g. after rotation), tampered with or written by an
    incompatible schema yields None, which the app treats as "logged out".

    Args:
        blob: The stored Fernet token.

    Returns:
        The decrypted tokens, or None when the blob cannot be used.
    """
    cipher = _fernet()
    try:
        tokens: SpotifyTokens = SpotifyTokens.model_validate_json(cipher.decrypt(blob.encode()))
    except (InvalidToken, ValidationError):
        return None
    return tokens
