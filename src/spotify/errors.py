"""Spotify error hierarchy and the mapping from HTTP responses to it.

Web API errors carry an `ErrorObject` body (`{"error": {"status", "message"}}`, per the
OpenAPI schema); the accounts service (token endpoint) uses the OAuth format
(`{"error": "<code>", "error_description": "..."}`). Both are parsed here, so callers always
get Spotify's own message to log and show (escaped) to the user.
"""

import httpx

QUOTA_EXCEEDED_REASON = "QUOTA_EXCEEDED"  # 429 reason meaning a retry cannot succeed
INVALID_GRANT = "invalid_grant"  # OAuth error code for a revoked or expired grant


class SpotifyError(Exception):
    """Base Spotify error carrying the HTTP status and Spotify's `error.message`.

    Network failures without a response are reported as `SpotifyServerError` with status 503.
    """

    def __init__(self, status: int, message: str, reason: str | None = None) -> None:
        """Store the error details.

        Args:
            status: HTTP status code returned by Spotify.
            message: Spotify's `error.message` (or the OAuth `error_description`).
            reason: Machine-readable reason (`error.reason` or the OAuth error code), if any.
        """
        super().__init__(f"Spotify error {status}: {message}")
        self.status = status
        self.message = message
        self.reason = reason


class SpotifyBadRequestError(SpotifyError):
    """400: malformed request, i.e. a bug on our side; never retried."""


class SpotifyAuthError(SpotifyError):
    """401: bad or expired access token; the caller refreshes once, then asks for a login."""


class SpotifyForbiddenError(SpotifyError):
    """403: e.g. the user is not in the Development Mode allowlist."""


class SpotifyNotFoundError(SpotifyError):
    """404: the requested resource does not exist."""


class SpotifyRateLimitError(SpotifyError):
    """429 after bounded retries, or a `Retry-After` too long to wait for."""


class SpotifyQuotaError(SpotifyError):
    """429 with reason `QUOTA_EXCEEDED`: raised at once, without retrying."""


class SpotifyServerError(SpotifyError):
    """5xx (or no response at all) after bounded retries."""


# Named as an outcome rather than an error: it signals "send the user through OAuth again".
class SpotifyReauthRequired(SpotifyError):  # noqa: N818
    """The refresh token or authorization code was rejected: the user must log in again."""


STATUS_ERRORS: dict[int, type[SpotifyError]] = {  # Documented statuses and their exceptions
    400: SpotifyBadRequestError,
    401: SpotifyAuthError,
    403: SpotifyForbiddenError,
    404: SpotifyNotFoundError,
    429: SpotifyRateLimitError,
}


def parse_error_body(response: httpx.Response) -> tuple[str, str | None]:
    """Extract Spotify's message and reason from an error response.

    Args:
        response: A non-2xx response from the Web API or the accounts service.

    Returns:
        The human-readable message and the machine-readable reason (None if absent).
    """
    try:
        body = response.json()
    except ValueError:
        return response.reason_phrase or "Unknown error", None
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or response.reason_phrase
        return str(message), error.get("reason") or body.get("reason")
    if isinstance(error, str):
        return str(body.get("error_description") or error), error
    return response.reason_phrase or "Unknown error", None


def error_from_response(response: httpx.Response) -> SpotifyError:
    """Build the exception matching an error response's status and body.

    Args:
        response: A non-2xx response from the Web API or the accounts service.

    Returns:
        The SpotifyError subclass for the status, carrying Spotify's message.
    """
    message, reason = parse_error_body(response)
    status = response.status_code
    if status == 429 and reason == QUOTA_EXCEEDED_REASON:
        return SpotifyQuotaError(status, message, reason)
    if status >= 500:
        return SpotifyServerError(status, message, reason)
    return STATUS_ERRORS.get(status, SpotifyError)(status, message, reason)
