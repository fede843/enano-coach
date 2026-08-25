"""Provider-neutral authorization-code boundary for synthetic BFF tests.

This module deliberately stops at the provider boundary.  A provider adapter
must perform token exchange and cryptographic claim verification before it
constructs :class:`ProviderClaims`; this module only binds that verified result
to a server-created transaction and a server-side session reference.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final
from urllib.parse import unquote, urlsplit

DEFAULT_TRANSACTION_TTL: Final = timedelta(minutes=5)
MAX_TRANSACTION_TTL: Final = timedelta(minutes=15)
PKCE_METHOD: Final = "S256"
PUBLIC_ERROR_MESSAGE: Final = "Authorization could not be completed."


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuthorizationBoundaryError(ValueError):
    """A safe, machine-classified authorization failure.

    The error intentionally contains no provider response, token, claim, state,
    nonce, code, verifier, or session value.  ``code`` is suitable for internal
    metrics and a generic public response remains available through ``str``.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(PUBLIC_ERROR_MESSAGE)

    def __repr__(self) -> str:
        return f"AuthorizationBoundaryError(code={self.code!r})"


@dataclass(frozen=True, slots=True, repr=False)
class ProviderClaims:
    """Claims already verified by a provider-specific adapter.

    ``verified`` is a trust-boundary assertion, not a JWT verification
    implementation.  A real adapter must set it only after checking issuer,
    audience, signature, and expiration according to its pinned provider.
    """

    issuer: str
    subject: str
    audience: str | tuple[str, ...]
    nonce: str
    expires_at: datetime
    verified: bool = False

    def __post_init__(self) -> None:
        audience = self.audience
        if isinstance(audience, str):
            normalized = (audience,)
        else:
            try:
                normalized = tuple(audience)
            except TypeError as exc:
                raise ValueError("audience must be text or a sequence") from exc
        object.__setattr__(self, "audience", normalized)

    def __repr__(self) -> str:
        return (
            "ProviderClaims(issuer=<redacted>, subject=<redacted>, "
            "audience=<redacted>, nonce=<redacted>, expires_at=<redacted>, "
            f"verified={self.verified!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class AuthorizationTransaction:
    """A short-lived, server-owned authorization transaction."""

    state: str
    nonce: str
    code_verifier: str
    code_challenge: str
    code_challenge_method: str
    return_to: str
    created_at: datetime
    expires_at: datetime
    session_binding_digest: str

    def __repr__(self) -> str:
        return (
            "AuthorizationTransaction(state=<redacted>, nonce=<redacted>, "
            "code_verifier=<redacted>, code_challenge=<redacted>, "
            "return_to=<redacted>, expires_at=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedIdentity:
    """The only identity projection produced after callback validation."""

    issuer: str
    subject: str
    authenticated_at: datetime

    def __repr__(self) -> str:
        return "VerifiedIdentity(issuer=<redacted>, subject=<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class AuthorizationResult:
    """Validated identity plus the return path stored at transaction start."""

    identity: VerifiedIdentity
    return_to: str

    def __repr__(self) -> str:
        return "AuthorizationResult(identity=<redacted>, return_to=<redacted>)"


def pkce_s256_challenge(code_verifier: str) -> str:
    """Return the RFC 7636 S256 challenge for a code verifier."""

    if not isinstance(code_verifier, str):
        raise ValueError("code verifier must be text")
    try:
        encoded = code_verifier.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("code verifier must be ASCII") from exc
    digest = hashlib.sha256(encoded).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def validate_return_path(return_to: str) -> str:
    """Allow only a local absolute path, never an external redirect target."""

    if not isinstance(return_to, str) or not return_to or len(return_to) > 2048:
        raise AuthorizationBoundaryError("invalid_return_path")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in return_to):
        raise AuthorizationBoundaryError("invalid_return_path")
    if "\\" in return_to:
        raise AuthorizationBoundaryError("invalid_return_path")

    decoded = unquote(return_to)
    while True:
        fully_decoded = unquote(decoded)
        if fully_decoded == decoded:
            break
        decoded = fully_decoded
    if "\\" in decoded or decoded.startswith("//") or not decoded.startswith("/"):
        raise AuthorizationBoundaryError("invalid_return_path")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in decoded):
        raise AuthorizationBoundaryError("invalid_return_path")

    parsed = urlsplit(decoded)
    if parsed.scheme or parsed.netloc or ".." in parsed.path.split("/"):
        raise AuthorizationBoundaryError("invalid_return_path")
    return return_to


def _validate_text(value: object, *, max_length: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise AuthorizationBoundaryError("invalid_request")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise AuthorizationBoundaryError("invalid_request")
    return value


def _validate_code_verifier(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise AuthorizationBoundaryError("invalid_pkce")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise AuthorizationBoundaryError("invalid_pkce")
    verifier = value
    if len(verifier) < 43 or any(
        character
        not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        for character in verifier
    ):
        raise AuthorizationBoundaryError("invalid_pkce")
    return verifier


def _session_digest(session_binding: str) -> str:
    return hashlib.sha256(session_binding.encode("utf-8")).hexdigest()


def _aware_utc(value: object, *, error_code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AuthorizationBoundaryError(error_code)
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError):
        raise AuthorizationBoundaryError(error_code) from None
    if offset is None:
        raise AuthorizationBoundaryError(error_code)
    return value.astimezone(timezone.utc)


def _audience_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values: Iterable[object] = (value,)
    elif isinstance(value, tuple):
        values = value
    else:
        raise AuthorizationBoundaryError("provider_claim_mismatch")
    if not values or any(not isinstance(item, str) or not item for item in values):
        raise AuthorizationBoundaryError("provider_claim_mismatch")
    return tuple(values)


class AuthorizationBoundary:
    """Keep authorization-code state entirely in a server-side memory boundary."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        now: Callable[[], datetime] | None = None,
        transaction_ttl: timedelta = DEFAULT_TRANSACTION_TTL,
    ) -> None:
        self.issuer = _validate_text(issuer, max_length=2048)
        self.audience = _validate_text(audience, max_length=512)
        if not isinstance(transaction_ttl, timedelta):
            raise TypeError("transaction_ttl must be a timedelta")
        if transaction_ttl <= timedelta(0) or transaction_ttl > MAX_TRANSACTION_TTL:
            raise ValueError("transaction_ttl must be short and positive")
        if now is not None and not callable(now):
            raise TypeError("now must be callable")
        self._now = now or _utc_now
        self._transaction_ttl = transaction_ttl
        self._pending: dict[str, AuthorizationTransaction] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def begin(
        self, session_binding: str, *, return_to: str = "/"
    ) -> AuthorizationTransaction:
        """Create a transaction without contacting a provider."""

        binding = _validate_text(session_binding, max_length=512)
        safe_return_to = validate_return_path(return_to)
        created_at = _aware_utc(self._now(), error_code="invalid_clock")
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        while nonce == state:
            nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(32)
        transaction = AuthorizationTransaction(
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            code_challenge=pkce_s256_challenge(code_verifier),
            code_challenge_method=PKCE_METHOD,
            return_to=safe_return_to,
            created_at=created_at,
            expires_at=created_at + self._transaction_ttl,
            session_binding_digest=_session_digest(binding),
        )
        self._pending[state] = transaction
        return transaction

    def complete(
        self,
        *,
        session_binding: str,
        state: str,
        code: str,
        code_verifier: str,
        claims: object,
    ) -> AuthorizationResult:
        """Consume and validate one callback using provider-verified claims."""

        binding = _validate_text(session_binding, max_length=512)
        try:
            state_value = _validate_text(state, max_length=512)
        except AuthorizationBoundaryError:
            raise AuthorizationBoundaryError("invalid_transaction") from None
        transaction = self._pending.get(state_value)
        if transaction is None or not hmac.compare_digest(
            transaction.session_binding_digest,
            _session_digest(binding),
        ):
            raise AuthorizationBoundaryError("invalid_transaction")

        # Consume after the server-session binding check, but before validating
        # the remaining callback values, so a bound transaction is one-use.
        self._pending.pop(state_value, None)
        now = _aware_utc(self._now(), error_code="invalid_clock")
        if now >= transaction.expires_at:
            raise AuthorizationBoundaryError("expired_transaction")

        try:
            code_value = _validate_text(code, max_length=2048)
        except AuthorizationBoundaryError:
            raise AuthorizationBoundaryError("invalid_code") from None
        del code_value  # The provider owns code exchange; no raw code is retained.
        verifier = _validate_code_verifier(code_verifier)
        if not hmac.compare_digest(
            transaction.code_challenge,
            pkce_s256_challenge(verifier),
        ):
            raise AuthorizationBoundaryError("invalid_pkce")

        if not isinstance(claims, ProviderClaims):
            raise AuthorizationBoundaryError("unverified_provider_claims")
        if claims.verified is not True:
            raise AuthorizationBoundaryError("unverified_provider_claims")
        if claims.issuer != self.issuer:
            raise AuthorizationBoundaryError("provider_claim_mismatch")
        if not isinstance(claims.subject, str) or not claims.subject:
            raise AuthorizationBoundaryError("provider_claim_mismatch")
        if any(
            ord(character) < 0x20 or ord(character) == 0x7F
            for character in claims.subject
        ):
            raise AuthorizationBoundaryError("provider_claim_mismatch")
        if self.audience not in _audience_values(claims.audience):
            raise AuthorizationBoundaryError("provider_claim_mismatch")
        if not isinstance(claims.nonce, str) or not hmac.compare_digest(
            claims.nonce,
            transaction.nonce,
        ):
            raise AuthorizationBoundaryError("provider_claim_mismatch")
        identity_expires_at = _aware_utc(
            claims.expires_at,
            error_code="provider_claim_mismatch",
        )
        if now >= identity_expires_at:
            raise AuthorizationBoundaryError("expired_identity")

        return AuthorizationResult(
            identity=VerifiedIdentity(
                issuer=self.issuer,
                subject=claims.subject,
                authenticated_at=now,
            ),
            return_to=transaction.return_to,
        )
