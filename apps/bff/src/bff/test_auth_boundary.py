from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from bff.auth_boundary import (
    AuthorizationBoundary,
    AuthorizationBoundaryError,
    ProviderClaims,
)

ISSUER = "https://issuer.example.test"
AUDIENCE = "enano-coach-client"
START = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _claims(transaction, *, now: datetime = START, **overrides: object):
    values: dict[str, object] = {
        "issuer": ISSUER,
        "subject": "subject-alice-demo",
        "audience": AUDIENCE,
        "nonce": transaction.nonce,
        "expires_at": now + timedelta(minutes=10),
        "verified": True,
    }
    values.update(overrides)
    return ProviderClaims(**values)


def _boundary(now: list[datetime] | None = None) -> AuthorizationBoundary:
    clock = now if now is not None else [START]
    return AuthorizationBoundary(
        issuer=ISSUER,
        audience=AUDIENCE,
        now=lambda: clock[0],
    )


def test_begin_creates_s256_transaction_bound_to_a_server_session() -> None:
    boundary = _boundary()

    transaction = boundary.begin(
        "session-alice-demo",
        return_to="/dashboard?tab=activity",
    )

    assert transaction.code_challenge_method == "S256"
    assert transaction.code_challenge == _pkce_challenge(transaction.code_verifier)
    assert transaction.return_to == "/dashboard?tab=activity"
    assert transaction.expires_at == START + timedelta(minutes=5)
    assert transaction.state
    assert transaction.nonce
    assert transaction.state != transaction.nonce
    assert transaction.state not in repr(transaction)
    assert transaction.nonce not in repr(transaction)
    assert transaction.code_verifier not in repr(transaction)
    assert transaction.return_to not in repr(transaction)


def test_complete_returns_only_provider_verified_issuer_subject_and_stored_return() -> (
    None
):
    boundary = _boundary()
    transaction = boundary.begin("session-alice-demo", return_to="/dashboard")

    result = boundary.complete(
        session_binding="session-alice-demo",
        state=transaction.state,
        code="synthetic-code-alice-demo",
        code_verifier=transaction.code_verifier,
        claims=_claims(transaction),
    )

    assert result.return_to == "/dashboard"
    assert result.identity.issuer == ISSUER
    assert result.identity.subject == "subject-alice-demo"
    assert result.identity.authenticated_at == START
    assert not hasattr(result.identity, "email")
    assert not hasattr(result.identity, "ow_user_id")


def test_complete_consumes_state_once() -> None:
    boundary = _boundary()
    transaction = boundary.begin("session-alice-demo")
    arguments = {
        "session_binding": "session-alice-demo",
        "state": transaction.state,
        "code": "synthetic-code-alice-demo",
        "code_verifier": transaction.code_verifier,
        "claims": _claims(transaction),
    }

    boundary.complete(**arguments)

    with pytest.raises(AuthorizationBoundaryError) as error:
        boundary.complete(**arguments)
    assert error.value.code == "invalid_transaction"


def test_complete_does_not_allow_another_session_to_consume_transaction() -> None:
    boundary = _boundary()
    transaction = boundary.begin("session-alice-demo")

    with pytest.raises(AuthorizationBoundaryError) as error:
        boundary.complete(
            session_binding="session-bob-demo",
            state=transaction.state,
            code="synthetic-code-bob-demo",
            code_verifier=transaction.code_verifier,
            claims=_claims(transaction),
        )

    assert error.value.code == "invalid_transaction"
    boundary.complete(
        session_binding="session-alice-demo",
        state=transaction.state,
        code="synthetic-code-alice-demo",
        code_verifier=transaction.code_verifier,
        claims=_claims(transaction),
    )


def test_expired_transaction_is_rejected_and_consumed() -> None:
    clock = [START]
    boundary = _boundary(clock)
    transaction = boundary.begin("session-alice-demo")
    clock[0] = START + timedelta(minutes=5)

    with pytest.raises(AuthorizationBoundaryError) as error:
        boundary.complete(
            session_binding="session-alice-demo",
            state=transaction.state,
            code="synthetic-code-alice-demo",
            code_verifier=transaction.code_verifier,
            claims=_claims(transaction, now=clock[0]),
        )

    assert error.value.code == "expired_transaction"
    assert boundary.pending_count == 0


@pytest.mark.parametrize(
    ("return_to",),
    [
        ("https://outside.example.test/",),
        ("//outside.example.test/",),
        (r"/\\outside.example.test/",),
        ("/%2F%2Foutside.example.test/",),
        ("/../outside",),
        ("/%2e%2e/outside",),
        ("/%252F%252Foutside.example.test/",),
        ("/%252e%252e/outside",),
        ("/\noutside",),
        ("dashboard",),
    ],
)
def test_begin_rejects_non_local_return_paths(return_to: str) -> None:
    boundary = _boundary()

    with pytest.raises(AuthorizationBoundaryError) as error:
        boundary.begin("session-alice-demo", return_to=return_to)

    assert error.value.code == "invalid_return_path"
    assert return_to not in str(error.value)
    assert return_to not in repr(error.value)


def test_complete_rejects_pkce_mismatch_without_exposing_verifier() -> None:
    boundary = _boundary()
    transaction = boundary.begin("session-alice-demo")
    wrong_verifier = "a" * len(transaction.code_verifier)

    with pytest.raises(AuthorizationBoundaryError) as error:
        boundary.complete(
            session_binding="session-alice-demo",
            state=transaction.state,
            code="synthetic-code-alice-demo",
            code_verifier=wrong_verifier,
            claims=_claims(transaction),
        )

    assert error.value.code == "invalid_pkce"
    assert wrong_verifier not in str(error.value)
    assert wrong_verifier not in repr(error.value)
    assert boundary.pending_count == 0


@pytest.mark.parametrize(
    ("field", "expected_code"),
    [
        ("state", "invalid_transaction"),
        ("code", "invalid_code"),
        ("code_verifier", "invalid_pkce"),
    ],
)
def test_complete_rejects_missing_callback_values(
    field: str, expected_code: str
) -> None:
    boundary = _boundary()
    transaction = boundary.begin("session-alice-demo")
    arguments: dict[str, object] = {
        "session_binding": "session-alice-demo",
        "state": transaction.state,
        "code": "synthetic-code-alice-demo",
        "code_verifier": transaction.code_verifier,
        "claims": _claims(transaction),
    }
    arguments[field] = None

    with pytest.raises(AuthorizationBoundaryError) as error:
        boundary.complete(**arguments)

    assert error.value.code == expected_code
    assert boundary.pending_count == (1 if field == "state" else 0)


@pytest.mark.parametrize(
    "claims_overrides",
    [
        {"verified": False},
        {"issuer": "https://other-issuer.example.test"},
        {"audience": "other-client"},
        {"nonce": "wrong-nonce-demo"},
        {"expires_at": START},
    ],
)
def test_complete_rejects_untrusted_or_mismatched_provider_claims(
    claims_overrides: dict[str, object],
) -> None:
    boundary = _boundary()
    transaction = boundary.begin("session-alice-demo")

    with pytest.raises(AuthorizationBoundaryError) as error:
        boundary.complete(
            session_binding="session-alice-demo",
            state=transaction.state,
            code="synthetic-code-alice-demo",
            code_verifier=transaction.code_verifier,
            claims=_claims(transaction, **claims_overrides),
        )

    assert error.value.code in {
        "unverified_provider_claims",
        "provider_claim_mismatch",
        "expired_identity",
    }
    assert "wrong-nonce-demo" not in str(error.value)


def test_complete_rejects_client_shaped_claim_mapping() -> None:
    boundary = _boundary()
    transaction = boundary.begin("session-alice-demo")

    with pytest.raises(AuthorizationBoundaryError) as error:
        boundary.complete(
            session_binding="session-alice-demo",
            state=transaction.state,
            code="synthetic-code-alice-demo",
            code_verifier=transaction.code_verifier,
            claims={
                "issuer": ISSUER,
                "subject": "subject-alice-demo",
                "email": "alice@example.test",
                "owner_id": "local-user-demo",
                "ow_user_id": "ow-user-demo",
            },
        )

    assert error.value.code == "unverified_provider_claims"
    assert "alice@example.test" not in str(error.value)
    assert "local-user-demo" not in repr(error.value)


def test_public_error_and_typed_claim_repr_do_not_reveal_sensitive_values() -> None:
    boundary = _boundary()
    transaction = boundary.begin("session-alice-demo")
    claims = _claims(transaction)

    assert transaction.nonce not in repr(claims)
    assert transaction.nonce not in str(claims)

    boundary.complete(
        session_binding="session-alice-demo",
        state=transaction.state,
        code="synthetic-code-alice-demo",
        code_verifier=transaction.code_verifier,
        claims=claims,
    )

    with pytest.raises(AuthorizationBoundaryError) as error:
        boundary.complete(
            session_binding="session-alice-demo",
            state=transaction.state,
            code="synthetic-code-alice-demo",
            code_verifier=transaction.code_verifier,
            claims=claims,
        )

    assert error.value.code == "invalid_transaction"
    assert "synthetic-code-alice-demo" not in str(error.value)
    assert transaction.state not in repr(error.value)
