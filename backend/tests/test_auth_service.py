import uuid

import pytest

from app.models.identity import User
from app.services.auth_service import (
    AuthenticationError,
    create_access_token,
    decode_access_token,
    hash_password,
    slugify,
    verify_password,
)


def test_password_hash_round_trip() -> None:
    password = "correct-horse-battery-staple"
    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash)
    assert not verify_password("wrong-password", password_hash)
    assert not verify_password(password, None)


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    user = User(id=user_id, email="owner@example.com", status="active")

    token, expires_in = create_access_token(user)

    assert expires_in > 0
    assert decode_access_token(token) == user_id


def test_invalid_access_token_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token("not-a-valid-token")


def test_workspace_slug_normalization() -> None:
    assert slugify(" Aadil's SEO Agency ") == "aadil-s-seo-agency"
    assert slugify("***") == "workspace"
